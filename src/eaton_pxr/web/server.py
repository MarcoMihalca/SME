"""
Serverul HTTP și firul de execuție pentru achiziția în fundal (o dată la 2 secunde)
al Dashboard-ului Web Multi-Device în lanț (daisy-chain RS-485), cu autentificare
pe bază de sesiune cookie HttpOnly, protecție CSRF și autorizare RBAC.

Caracteristici cheie:
  1. Caută automat Slave ID-urile în lanț (1, 2, 3, ...).
  2. Unde nu se mai primește răspuns (la scanare sau dacă un aparat cade în timpul
     funcționării), aparatele următoare din lanț "dispar" (informația nu trece mai departe)
     și se afișează un Pop-up în Dashboard cu numărul total de aparate găsite și opțiunile:
       - "OK" (confirmă că acestea sunt toate aparatele și continuă citirea)
       - "Problemă!" (oprește complet citirea pentru intervenție/reparație hardware).
  3. Calculează mediile (Average-urile) tuturor aparatelor active și păstrează datele
     individuale (măsurători, setări protecție, istoric declanșări) pentru fiecare ID separat.
  4. Protejează interfața și rutele API prin sesiuni persistente (`Login/users.db`),
     protecție CSRF și permisiuni separate pentru rolurile `admin` și `user`.
"""

from __future__ import annotations

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
import webbrowser

from ..analytics import (
    compute_energy_indicators,
    evaluate_alarm_state,
    evaluate_overcurrent_notification,
)
from ..auth import (
    AuthManager,
    PERM_AUDIT_READ,
    PERM_CSV_EXPORT,
    PERM_DB_FLUSH,
    PERM_DEMO_RUN,
    PERM_HARDWARE_CONTROL,
    PERM_TELEMETRY_READ,
    PERM_UI_PREFS,
    PERM_USERS_MANAGE,
    SessionContext,
)
from ..connection import (
    get_available_serial_ports,
    normalize_com_port,
    open_usb_modbus_client,
)
from ..csv_exporter import CsvExporter
from ..database import TimescaleBatchWriter
from ..models import MeasuredValue, PxrSnapshot, SerialConnectionConfig, TripEvent
from ..reader import read_device_on_client
from ..registers import (
    DEFAULT_MAX_CURRENT_AMPS,
    PXR25_PARAMETERS,
    RTC_SYNC_INTERVAL_SEC,
)
from ..scanner import compute_fleet_averages, discover_daisy_chain

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "dashboard.html")
LOGIN_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "login.html")
UI_PREFS_PATH = os.path.abspath("ui_preferences.json")
MAX_HISTORY_POINTS = 120

_UI_PREFS_LOCK = threading.Lock()
_CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
_USER_PATCH_RE = re.compile(r"^/api/users/(\d+)$")
_USER_RESET_PW_RE = re.compile(r"^/api/users/(\d+)/reset-password$")


def _read_raw_ui_preferences() -> Dict[str, Any]:
    if os.path.exists(UI_PREFS_PATH):
        try:
            with open(UI_PREFS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def load_ui_preferences(username: Optional[str] = None) -> Dict[str, Any]:
    """Încarcă preferințele UI (izolate per utilizator, cu fallback la formatul legacy)."""
    with _UI_PREFS_LOCK:
        raw = _read_raw_ui_preferences()
    legacy_defaults = {k: v for k, v in raw.items() if k != "by_user"}
    if username:
        by_user = raw.get("by_user")
        if isinstance(by_user, dict):
            user_prefs = by_user.get(username)
            if isinstance(user_prefs, dict):
                return dict(user_prefs)
    return legacy_defaults


def save_ui_preferences(
    prefs: Dict[str, Any], username: Optional[str] = None
) -> None:
    """Salvează preferințele UI (per utilizator dacă `username` este furnizat)."""
    if not isinstance(prefs, dict):
        return
    with _UI_PREFS_LOCK:
        raw = _read_raw_ui_preferences()
        if username:
            by_user = raw.get("by_user")
            if not isinstance(by_user, dict):
                by_user = {}
            by_user[username] = dict(prefs)
            raw["by_user"] = by_user
        else:
            by_user = raw.get("by_user")
            raw = dict(prefs)
            if isinstance(by_user, dict):
                raw["by_user"] = by_user
        try:
            with open(UI_PREFS_PATH, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


class MultiDeviceDashboardState:
    """Starea partajată thread-safe pentru întregul lanț de aparate PXR25."""

    def __init__(
        self,
        config: SerialConnectionConfig,
        csv_path: str,
        db_writer: Optional[TimescaleBatchWriter] = None,
    ) -> None:
        self.lock = threading.Lock()
        self.config: SerialConnectionConfig = config
        self.csv_path = csv_path
        self.db_writer = db_writer

        self.ok: bool = False
        self.halted: bool = False
        self.last_error: str = (
            "Se scanează automat lanțul de dispozitive (Slave ID 1, 2, ...)..."
        )
        self.timestamp: str = "—"
        self.poll_count: int = 0
        self.csv_rows: int = 0

        # Lanțul de ID-uri detectate și confirmate
        self.active_ids: List[int] = []
        self.confirmed_ids: Optional[List[int]] = None
        self.needs_discovery: bool = True
        self.force_settings_refresh: bool = True
        self.force_time_sync: bool = True
        self.last_time_sync: str = "—"

        # Datele per Slave ID și mediile pe întregul lanț
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.averages: List[Dict[str, Any]] = []
        self.averages_indicators: List[Dict[str, Any]] = []
        self.history: Dict[str, List[Dict[str, Any]]] = {"averages": []}
        self.overcurrent_alerts: List[Dict[str, Any]] = []
        self.alarm_state: Dict[str, Any] = {
            "active": False,
            "severity": "normal",
            "count": 0,
            "reasons": [],
            "signature": "",
        }

        # Stare Pop-up verificare lanț / întrerupere hardware
        self.chain_alert: Dict[str, Any] = {
            "pending": False,
            "reason": "",
            "detected_count": 0,
            "active_ids": [],
            "stopped_at_id": 1,
            "previous_count": 0,
            "lost_ids": [],
            "message": "",
        }

    def to_json_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "ok": self.ok,
                "halted": self.halted,
                "last_error": self.last_error,
                "current_port": self.config.port,
                "baudrate": self.config.baudrate,
                "connection_desc": self.config.description,
                "csv_path": self.csv_path,
                "timestamp": self.timestamp,
                "poll_count": self.poll_count,
                "csv_rows": self.csv_rows,
                "active_ids": list(self.active_ids),
                "devices": dict(self.devices),
                "averages": list(self.averages),
                "averages_indicators": list(self.averages_indicators),
                "history": {k: list(v) for k, v in self.history.items()},
                "last_time_sync": self.last_time_sync,
                "overcurrent_alerts": list(self.overcurrent_alerts),
                "alarm_state": dict(self.alarm_state),
                "chain_alert": dict(self.chain_alert),
                "db_status": self.db_writer.get_status_dict() if self.db_writer else {},
            }


def record_live_status_transition(
    snap: PxrSnapshot,
    last_cause_per_id: Dict[int, str],
    session_events_per_id: Dict[int, List[TripEvent]],
    db_writer: Optional[TimescaleBatchWriter] = None,
) -> Optional[TripEvent]:
    """
    Detectează schimbările de stare/cauză în timpul monitorizării live, le adaugă în
    istoricul sesiunii și (dacă reprezintă o avarie/declanșare/tranziție) le trimite
    și în tabelul permanent `trip_events` din TimescaleDB.
    """
    sid = snap.slave_id
    prim = snap.status_info.get("Stare Principală Disjunctor", "")
    cause = snap.status_info.get("Cauză Stare / Eveniment", "")
    cur_cause = f"{prim} — {cause}"

    if last_cause_per_id.get(sid) == cur_cause:
        return None

    had_previous = sid in last_cause_per_id
    last_cause_per_id[sid] = cur_cause

    by_key = {m.key: (m.value or 0.0) for m in snap.measurements}
    cur_fmt = (
        f"IA={by_key.get('I_A', 0.0):.1f}A, "
        f"IB={by_key.get('I_B', 0.0):.1f}A, "
        f"IC={by_key.get('I_C', 0.0):.1f}A, "
        f"IG={by_key.get('I_G', 0.0):.1f}A"
    )
    lst = session_events_per_id.setdefault(sid, [])
    live_ev = TripEvent(
        event_id=str(len(lst) + 1),
        event_type="Live",
        timestamp=snap.timestamp,
        cause=cur_cause,
        currents=cur_fmt,
    )
    lst.insert(0, live_ev)

    is_fault = any(
        k in prim for k in ("[0x03]", "[0x04]", "Tripped", "Declanșat", "Alarm")
    ) or (bool(cause) and "[0x0000]" not in cause and "Normal" not in cause)

    if db_writer is not None and (is_fault or had_previous):
        db_writer.enqueue_trip_event(sid, live_ev)

    return live_ev


def update_state_after_poll(
    state: MultiDeviceDashboardState,
    chain_to_poll: List[int],
    current_snapshots: Dict[int, PxrSnapshot],
    broken_at_id: Optional[int],
    now_str: str,
    total_csv_rows: int,
    settings_cache: Dict[int, List[Dict[str, Any]]],
    events_cache: Dict[int, List[Dict[str, Any]]],
    session_events_per_id: Dict[int, List[TripEvent]],
    time_sync_cache: Optional[Dict[int, str]] = None,
) -> None:
    """Actualizează thread-safe starea Dashboard-ului după un ciclu de citire în lanț."""
    surviving_ids = sorted(current_snapshots.keys())
    fleet_avg = compute_fleet_averages(current_snapshots)
    fleet_indicators = compute_energy_indicators(fleet_avg)
    time_short = now_str.split(" ")[-1] if " " in now_str else now_str

    with state.lock:
        state.force_settings_refresh = False
        state.force_time_sync = False
        state.timestamp = now_str
        state.poll_count += 1
        state.csv_rows = total_csv_rows

        new_devices_dict: Dict[str, Dict[str, Any]] = {}
        overcurrent_alerts: List[Dict[str, Any]] = []
        latest_sync_ts: Optional[str] = None

        for sid in surviving_ids:
            snap = current_snapshots[sid]
            combined_ev = [
                asdict(ev) for ev in session_events_per_id.get(sid, [])[:10]
            ] + events_cache.get(sid, [])

            oc_alert = snap.overcurrent_alert
            if oc_alert is None:
                oc_alert = evaluate_overcurrent_notification(
                    snap.measurements,
                    max_current_limit_a=snap.max_current_limit_a,
                    slave_id=sid,
                    register_label=snap.max_current_register,
                )
            if oc_alert.get("exceeded"):
                overcurrent_alerts.append(oc_alert)

            synced_at = snap.time_synced_at or (
                time_sync_cache.get(sid) if time_sync_cache else None
            )
            if synced_at:
                latest_sync_ts = synced_at

            new_devices_dict[str(sid)] = {
                "slave_id": sid,
                "timestamp": snap.timestamp,
                "connection_desc": snap.connection_desc,
                "status_info": snap.status_info,
                "measurements": [asdict(m) for m in snap.measurements],
                "energy_indicators": [asdict(ind) for ind in snap.energy_indicators],
                "protection_settings": settings_cache.get(sid, []),
                "event_history": combined_ev,
                "max_current_limit_a": snap.max_current_limit_a,
                "nominal_current_in_a": snap.nominal_current_in_a,
                "max_current_register": snap.max_current_register,
                "time_synced_at": synced_at or "—",
                "overcurrent_alert": oc_alert,
            }
            dev_hist = state.history.setdefault(str(sid), [])
            dev_hist.append(
                {
                    "t": time_short,
                    "values": {m.key: m.value for m in snap.measurements},
                    "indicators": {
                        ind.key: ind.value for ind in snap.energy_indicators
                    },
                }
            )
            if len(dev_hist) > MAX_HISTORY_POINTS:
                del dev_hist[:-MAX_HISTORY_POINTS]

        state.devices = new_devices_dict
        state.averages = [asdict(m) for m in fleet_avg]
        state.averages_indicators = [asdict(ind) for ind in fleet_indicators]
        state.active_ids = surviving_ids
        state.overcurrent_alerts = overcurrent_alerts
        if latest_sync_ts:
            state.last_time_sync = latest_sync_ts

        if surviving_ids:
            avg_hist = state.history.setdefault("averages", [])
            avg_hist.append(
                {
                    "t": time_short,
                    "values": {m.key: m.value for m in fleet_avg},
                    "indicators": {ind.key: ind.value for ind in fleet_indicators},
                }
            )
            if len(avg_hist) > MAX_HISTORY_POINTS:
                del avg_hist[:-MAX_HISTORY_POINTS]

        if broken_at_id is not None:
            lost_ids = [x for x in chain_to_poll if x >= broken_at_id]
            state.ok = len(surviving_ids) > 0
            state.last_error = (
                f"Întrerupere lanț la Slave ID #{broken_at_id}! "
                f"Dispozitivele #{broken_at_id}..#{chain_to_poll[-1]} au dispărut."
            )
            state.chain_alert = {
                "pending": True,
                "reason": "chain_break",
                "detected_count": len(surviving_ids),
                "active_ids": surviving_ids,
                "stopped_at_id": broken_at_id,
                "previous_count": len(chain_to_poll),
                "lost_ids": lost_ids,
                "message": (
                    f"ATENȚIE: Nu se mai primește răspuns de la Dispozitivul cu Slave ID #{broken_at_id}! "
                    f"Deoarece conexiunea este în lanț, toate dispozitivele de la #{broken_at_id} "
                    f"până la #{chain_to_poll[-1]} ({len(lost_ids)} aparate) au dispărut. "
                    f"Dispozitive rămase active: {len(surviving_ids)}."
                ),
            }
        elif not state.chain_alert.get("pending"):
            state.ok = len(surviving_ids) > 0
            state.last_error = ""

        state.alarm_state = evaluate_alarm_state(
            state.devices, state.chain_alert, state.halted
        )


def trigger_manual_time_sync(state: MultiDeviceDashboardState) -> str:
    """Marchează sincronizarea imediată a ceasului RTC pe toate dispozitivele la următorul ciclu."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with state.lock:
        state.force_time_sync = True
        state.last_time_sync = ts
    return ts


def apply_chain_alert_action(state: MultiDeviceDashboardState, action: str) -> None:
    """Aplică decizia operatorului din Pop-up ('ok' sau 'problem') asupra stării lanțului."""
    with state.lock:
        state.chain_alert["pending"] = False
        if action == "problem":
            state.halted = True
            state.ok = False
            state.last_error = (
                "CITIRE OPRITĂ PENTRU INTERVENȚIE HARDWARE "
                f"(Problema raportată la Slave ID #{state.chain_alert.get('stopped_at_id', '?')})."
            )
        else:
            state.confirmed_ids = list(state.active_ids)
            state.halted = False
            if state.active_ids:
                state.ok = True
                state.last_error = ""
            else:
                state.needs_discovery = True
        state.alarm_state = evaluate_alarm_state(
            state.devices, state.chain_alert, state.halted
        )


def build_http_handler(
    state: MultiDeviceDashboardState,
    csv_exporter: CsvExporter,
    db_writer: Optional[TimescaleBatchWriter],
    wake_event: threading.Event,
    auth_manager: AuthManager,
) -> type[BaseHTTPRequestHandler]:
    """Construiește clasa handler HTTP legată de starea aplicației și `AuthManager`."""

    class Handler(BaseHTTPRequestHandler):
        def _client_ip(self) -> str:
            return self.client_address[0] if self.client_address else "127.0.0.1"

        def _is_https(self) -> bool:
            return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

        def _send_security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", _CSP_HEADER)

        def _send_json(
            self,
            status: int,
            payload: Dict[str, Any],
            extra_headers: Optional[Dict[str, str]] = None,
            no_store: bool = True,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if no_store:
                self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self._send_security_headers()
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _send_html_file(self, file_path: str) -> None:
            with open(file_path, "rb") as f:
                html_bytes = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(html_bytes)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(html_bytes)

        def _send_redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self._send_security_headers()
            self.end_headers()

        def _send_ok(self) -> None:
            self._send_json(200, {"status": "ok"}, no_store=False)

        def _read_json_body(self) -> Tuple[Dict[str, Any], bool]:
            try:
                length = max(
                    0, min(65536, int(self.headers.get("Content-Length", "0")))
                )
            except (TypeError, ValueError):
                length = 0
            if length == 0:
                return {}, True
            raw_body = self.rfile.read(length)
            if not raw_body.strip():
                return {}, True
            try:
                parsed = json.loads(raw_body.decode("utf-8"))
                if not isinstance(parsed, dict):
                    return {}, False
                return parsed, True
            except Exception:
                return {}, False

        def _require_auth(self, is_api: bool = True) -> Optional[SessionContext]:
            ctx = auth_manager.authenticate_request(self.headers.get("Cookie"))
            if ctx is None:
                if is_api:
                    self._send_json(
                        401,
                        {
                            "error": "Autentificare necesară.",
                            "code": "unauthenticated",
                        },
                    )
                else:
                    self._send_redirect("/login")
                return None
            return ctx

        def _require_permission(
            self, ctx: SessionContext, permission: str
        ) -> bool:
            if not auth_manager.has_permission(ctx, permission):
                self._send_json(
                    403,
                    {
                        "error": "Acces interzis: nu ai permisiunea necesară pentru această acțiune.",
                        "code": "forbidden",
                        "required_permission": permission,
                    },
                )
                return False
            return True

        def _require_csrf(self, ctx: SessionContext) -> bool:
            csrf_token = self.headers.get("X-CSRF-Token")
            if not auth_manager.verify_csrf(csrf_token, ctx):
                self._send_json(
                    403,
                    {
                        "error": "Token CSRF lipsă sau invalid.",
                        "code": "csrf_invalid",
                    },
                )
                return False
            return True

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/health":
                self._send_json(200, {"status": "ok"})
                return

            if path == "/login":
                existing = auth_manager.authenticate_request(self.headers.get("Cookie"))
                if existing is not None:
                    self._send_redirect("/")
                    return
                self._send_html_file(LOGIN_TEMPLATE_PATH)
                return

            if path in ("/", "/index.html"):
                ctx = self._require_auth(is_api=False)
                if ctx is None:
                    return
                self._send_html_file(TEMPLATE_PATH)
                return

            if path == "/api/auth/me":
                ctx = self._require_auth(is_api=True)
                if ctx is None:
                    return
                self._send_json(
                    200,
                    {
                        "user": ctx.user,
                        "permissions": ctx.permissions,
                        "csrf_token": ctx.csrf_token,
                        "expires_at": ctx.expires_at,
                    },
                )
                return

            if path == "/api/ports":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_permission(
                    ctx, PERM_TELEMETRY_READ
                ):
                    return
                raw_ports = get_available_serial_ports()
                port_list = []
                for dev, desc in raw_ports:
                    upper = desc.upper()
                    is_usb = any(
                        k in upper
                        for k in ("USB", "CH340", "FTDI", "CP210", "RS485")
                    ) and ("BLUETOOTH" not in upper)
                    port_list.append(
                        {"device": dev, "description": desc, "is_usb": is_usb}
                    )
                with state.lock:
                    payload = {
                        "ports": port_list,
                        "current_port": state.config.port,
                        "baudrate": state.config.baudrate,
                    }
                self._send_json(200, payload)
                return

            if path == "/api/data":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_permission(
                    ctx, PERM_TELEMETRY_READ
                ):
                    return
                self._send_json(200, state.to_json_dict())
                return

            if path == "/api/ui-config":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_permission(ctx, PERM_UI_PREFS):
                    return
                prefs = load_ui_preferences(username=str(ctx.user["username"]))
                self._send_json(200, prefs)
                return

            if path == "/api/csv":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_permission(ctx, PERM_CSV_EXPORT):
                    return
                if os.path.exists(csv_exporter.csv_path):
                    with open(csv_exporter.csv_path, "rb") as csv_f:
                        csv_bytes = csv_f.read()
                    filename = os.path.basename(csv_exporter.csv_path)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header(
                        "Content-Disposition",
                        f'attachment; filename="{filename}"',
                    )
                    self.send_header("Content-Length", str(len(csv_bytes)))
                    self._send_security_headers()
                    self.end_headers()
                    self.wfile.write(csv_bytes)
                else:
                    msg = "Fișierul CSV nu are încă înregistrări.".encode("utf-8")
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(msg)))
                    self._send_security_headers()
                    self.end_headers()
                    self.wfile.write(msg)
                return

            if path == "/api/users":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_permission(ctx, PERM_USERS_MANAGE):
                    return
                self._send_json(200, {"users": auth_manager.list_users()})
                return

            if path == "/api/audit-logs":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_permission(ctx, PERM_AUDIT_READ):
                    return
                qs = parse_qs(parsed.query)
                try:
                    limit = int(qs.get("limit", ["100"])[0])
                except (TypeError, ValueError):
                    limit = 100
                self._send_json(200, {"logs": auth_manager.get_audit_logs(limit=limit)})
                return

            self._send_json(
                404, {"error": "Resursa solicitată nu există.", "code": "not_found"}
            )

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            req, valid_json = self._read_json_body()
            if not valid_json:
                self._send_json(
                    400,
                    {"error": "Payload JSON invalid.", "code": "invalid_json"},
                )
                return

            client_ip = self._client_ip()
            is_https = self._is_https()

            if path == "/api/auth/login":
                username = str(req.get("username") or "")
                password = str(req.get("password") or "")
                ctx, msg, status, retry_after = auth_manager.login(
                    username=username,
                    password=password,
                    ip_address=client_ip,
                    user_agent=self.headers.get("User-Agent", ""),
                )
                if ctx is None:
                    extra = (
                        {"Retry-After": str(retry_after)}
                        if status == 429 and retry_after > 0
                        else None
                    )
                    self._send_json(
                        status,
                        {"error": msg, "code": "auth_failed"},
                        extra_headers=extra,
                    )
                    return

                cookie_val = auth_manager.build_session_cookie(
                    ctx.token, secure=is_https
                )
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "message": msg,
                        "user": ctx.user,
                        "permissions": ctx.permissions,
                        "csrf_token": ctx.csrf_token,
                        "expires_at": ctx.expires_at,
                    },
                    extra_headers={"Set-Cookie": cookie_val},
                )
                return

            if path == "/api/auth/logout":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_csrf(ctx):
                    return
                auth_manager.logout(ctx, ip_address=client_ip)
                self._send_json(
                    200,
                    {"status": "ok"},
                    extra_headers={
                        "Set-Cookie": auth_manager.build_clear_cookie(secure=is_https)
                    },
                )
                return

            if path == "/api/auth/change-password":
                ctx = self._require_auth(is_api=True)
                if ctx is None or not self._require_csrf(ctx):
                    return
                cur_pw = str(req.get("current_password") or "")
                new_pw = str(req.get("new_password") or "")
                ok, msg = auth_manager.change_password(
                    ctx, cur_pw, new_pw, ip_address=client_ip
                )
                if ok:
                    self._send_json(200, {"status": "ok", "message": msg})
                else:
                    self._send_json(
                        400, {"error": msg, "code": "password_change_failed"}
                    )
                return

            if path == "/api/ui-config":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_UI_PREFS)
                    or not self._require_csrf(ctx)
                ):
                    return
                save_ui_preferences(req, username=str(ctx.user["username"]))
                self._send_ok()
                return

            if path == "/api/db-enqueue-demo":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_DEMO_RUN)
                    or not self._require_csrf(ctx)
                ):
                    return
                if req.get("persist_to_db") is True and not auth_manager.has_permission(
                    ctx, PERM_DB_FLUSH
                ):
                    self._send_json(
                        403,
                        {
                            "error": "Salvarea datelor simulate în baza de date necesită rol de administrator.",
                            "code": "forbidden",
                            "required_permission": PERM_DB_FLUSH,
                        },
                    )
                    return

                vals = req.get("values") if isinstance(req.get("values"), dict) else {}
                demo_meas = [
                    MeasuredValue(
                        p.key,
                        p.name,
                        p.category,
                        float(vals[p.key])
                        if p.key in vals and vals[p.key] is not None
                        else None,
                        p.unit,
                    )
                    for p in PXR25_PARAMETERS
                ]
                try:
                    max_limit = float(
                        req.get("max_current_limit_a") or DEFAULT_MAX_CURRENT_AMPS
                    )
                except (TypeError, ValueError):
                    max_limit = DEFAULT_MAX_CURRENT_AMPS
                try:
                    demo_sid = int(req.get("slave_id") or 1)
                except (TypeError, ValueError):
                    demo_sid = 1

                demo_inds = compute_energy_indicators(
                    demo_meas, nominal_current_in=max_limit
                )
                overcurrent_alert = evaluate_overcurrent_notification(
                    demo_meas,
                    max_current_limit_a=max_limit,
                    slave_id=demo_sid,
                    register_label="403007 (0x0BBE)",
                )
                if req.get("persist_to_db") is True and db_writer is not None:
                    db_writer.enqueue_averages(
                        active_count=1,
                        averages=demo_meas,
                        indicators=demo_inds,
                    )
                    auth_manager.log_action(
                        actor=str(ctx.user["username"]),
                        action="demo_persist_db",
                        target=f"Slave #{demo_sid}",
                        ip_address=client_ip,
                    )
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "measurements": [asdict(m) for m in demo_meas],
                        "indicators": [asdict(ind) for ind in demo_inds],
                        "max_current_limit_a": max_limit,
                        "overcurrent_alert": overcurrent_alert,
                        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    no_store=False,
                )
                return

            if path in ("/api/connect", "/api/scan-chain"):
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_HARDWARE_CONTROL)
                    or not self._require_csrf(ctx)
                ):
                    return
                with state.lock:
                    raw_port = req.get("port")
                    new_port = normalize_com_port(
                        str(raw_port) if raw_port else state.config.port
                    )
                    try:
                        new_baud = int(req.get("baudrate") or state.config.baudrate)
                    except (TypeError, ValueError):
                        new_baud = state.config.baudrate
                    state.config = SerialConnectionConfig(
                        port=new_port,
                        baudrate=new_baud,
                        parity=state.config.parity,
                        stopbits=state.config.stopbits,
                        bytesize=state.config.bytesize,
                        slave_id=1,
                        timeout=state.config.timeout,
                        use_float=state.config.use_float,
                        word_swap=state.config.word_swap,
                    )
                    state.halted = False
                    state.needs_discovery = True
                    state.force_settings_refresh = True
                    state.force_time_sync = True
                wake_event.set()
                auth_manager.log_action(
                    actor=str(ctx.user["username"]),
                    action="scan_chain" if path == "/api/scan-chain" else "connect_port",
                    target=new_port,
                    details=f"baudrate={new_baud}",
                    ip_address=client_ip,
                )
                self._send_ok()
                return

            if path == "/api/chain-alert-action":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_HARDWARE_CONTROL)
                    or not self._require_csrf(ctx)
                ):
                    return
                action = str(req.get("action") or "ok")
                apply_chain_alert_action(state, action)
                wake_event.set()
                auth_manager.log_action(
                    actor=str(ctx.user["username"]),
                    action="chain_alert_action",
                    details=f"action={action}",
                    ip_address=client_ip,
                )
                self._send_ok()
                return

            if path == "/api/db-flush":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_DB_FLUSH)
                    or not self._require_csrf(ctx)
                ):
                    return
                if db_writer is not None:
                    db_writer.trigger_flush()
                auth_manager.log_action(
                    actor=str(ctx.user["username"]),
                    action="db_flush",
                    ip_address=client_ip,
                )
                self._send_ok()
                return

            if path == "/api/sync-time":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_HARDWARE_CONTROL)
                    or not self._require_csrf(ctx)
                ):
                    return
                synced_at = trigger_manual_time_sync(state)
                wake_event.set()
                auth_manager.log_action(
                    actor=str(ctx.user["username"]),
                    action="sync_time",
                    details=synced_at,
                    ip_address=client_ip,
                )
                self._send_json(
                    200,
                    {"status": "ok", "synced_at": synced_at},
                    no_store=False,
                )
                return

            if path == "/api/resume-reading":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_HARDWARE_CONTROL)
                    or not self._require_csrf(ctx)
                ):
                    return
                with state.lock:
                    state.halted = False
                    state.needs_discovery = True
                    state.force_settings_refresh = True
                    state.force_time_sync = True
                wake_event.set()
                auth_manager.log_action(
                    actor=str(ctx.user["username"]),
                    action="resume_reading",
                    ip_address=client_ip,
                )
                self._send_ok()
                return

            if path == "/api/refresh-settings":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_HARDWARE_CONTROL)
                    or not self._require_csrf(ctx)
                ):
                    return
                with state.lock:
                    state.force_settings_refresh = True
                wake_event.set()
                auth_manager.log_action(
                    actor=str(ctx.user["username"]),
                    action="refresh_settings",
                    ip_address=client_ip,
                )
                self._send_ok()
                return

            if path == "/api/users":
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_USERS_MANAGE)
                    or not self._require_csrf(ctx)
                ):
                    return
                username = str(req.get("username") or "")
                password = str(req.get("password") or "")
                role = str(req.get("role") or "user")
                ok, msg, status = auth_manager.create_user(
                    username=username,
                    password=password,
                    role=role,
                    actor_ctx=ctx,
                    ip_address=client_ip,
                )
                if ok:
                    self._send_json(201, {"status": "ok", "message": msg})
                else:
                    self._send_json(
                        status, {"error": msg, "code": "user_create_failed"}
                    )
                return

            reset_match = _USER_RESET_PW_RE.match(path)
            if reset_match:
                ctx = self._require_auth(is_api=True)
                if (
                    ctx is None
                    or not self._require_permission(ctx, PERM_USERS_MANAGE)
                    or not self._require_csrf(ctx)
                ):
                    return
                target_id = int(reset_match.group(1))
                new_pw = str(req.get("new_password") or "")
                ok, msg, status = auth_manager.reset_password(
                    user_id=target_id,
                    new_password=new_pw,
                    actor_ctx=ctx,
                    ip_address=client_ip,
                )
                if ok:
                    self._send_json(200, {"status": "ok", "message": msg})
                else:
                    self._send_json(
                        status, {"error": msg, "code": "reset_password_failed"}
                    )
                return

            self._send_json(
                404, {"error": "Rută inexistentă.", "code": "not_found"}
            )

        def do_PATCH(self) -> None:
            path = urlparse(self.path).path
            match = _USER_PATCH_RE.match(path)
            if not match:
                self._send_json(
                    404, {"error": "Rută inexistentă.", "code": "not_found"}
                )
                return

            ctx = self._require_auth(is_api=True)
            if (
                ctx is None
                or not self._require_permission(ctx, PERM_USERS_MANAGE)
                or not self._require_csrf(ctx)
            ):
                return

            req, valid_json = self._read_json_body()
            if not valid_json:
                self._send_json(
                    400,
                    {"error": "Payload JSON invalid.", "code": "invalid_json"},
                )
                return

            target_id = int(match.group(1))
            role = req.get("role")
            if role is not None:
                role = str(role)
            is_active = req.get("is_active")
            if is_active is not None:
                is_active = bool(is_active)
            unlock = bool(req.get("unlock", False))

            ok, msg, status = auth_manager.update_user(
                user_id=target_id,
                role=role,
                is_active=is_active,
                unlock=unlock,
                actor_ctx=ctx,
                ip_address=self._client_ip(),
            )
            if ok:
                self._send_json(200, {"status": "ok", "message": msg})
            else:
                self._send_json(
                    status, {"error": msg, "code": "user_update_failed"}
                )

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            match = _USER_PATCH_RE.match(path)
            if not match:
                self._send_json(
                    404, {"error": "Rută inexistentă.", "code": "not_found"}
                )
                return

            ctx = self._require_auth(is_api=True)
            if (
                ctx is None
                or not self._require_permission(ctx, PERM_USERS_MANAGE)
                or not self._require_csrf(ctx)
            ):
                return

            target_id = int(match.group(1))
            ok, msg, status = auth_manager.delete_user(
                user_id=target_id,
                actor_ctx=ctx,
                ip_address=self._client_ip(),
            )
            if ok:
                self._send_json(200, {"status": "ok", "message": msg})
            else:
                self._send_json(
                    status, {"error": msg, "code": "user_delete_failed"}
                )

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def create_dashboard_server(
    state: MultiDeviceDashboardState,
    csv_exporter: CsvExporter,
    db_writer: Optional[TimescaleBatchWriter],
    wake_event: threading.Event,
    auth_manager: Optional[AuthManager] = None,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """Instanțiază `ThreadingHTTPServer` pentru Dashboard + Auth (util și în teste)."""
    mgr = auth_manager or AuthManager()
    handler_cls = build_http_handler(
        state=state,
        csv_exporter=csv_exporter,
        db_writer=db_writer,
        wake_event=wake_event,
        auth_manager=mgr,
    )
    return ThreadingHTTPServer((host, port), handler_cls)


def run_dashboard_server(
    config: SerialConnectionConfig,
    csv_exporter: CsvExporter,
    host: str = "127.0.0.1",
    port: int = 8080,
    interval_sec: float = 2.0,
    open_browser: bool = True,
) -> None:
    """
    Pornește firul de scanare + achiziție ciclică la 2 secunde pentru lanțul de dispozitive
    și serverul HTTP al Dashboard-ului Web protejat prin autentificare.
    """
    auth_manager = AuthManager()
    db_writer = TimescaleBatchWriter()
    state = MultiDeviceDashboardState(
        config=config, csv_path=csv_exporter.csv_path, db_writer=db_writer
    )
    stop_event = threading.Event()
    wake_event = threading.Event()

    # Păstrăm în memorie setările de protecție, pragul maxim Ir, sincronizarea RTC și istoricul fiecărui Slave ID
    settings_cache: Dict[int, List[Dict[str, Any]]] = {}
    events_cache: Dict[int, List[Dict[str, Any]]] = {}
    session_events_per_id: Dict[int, List[TripEvent]] = {}
    last_cause_per_id: Dict[int, str] = {}
    max_current_cache: Dict[int, float] = {}
    nominal_in_cache: Dict[int, float] = {}
    time_sync_cache: Dict[int, str] = {}
    last_sync_epoch: Dict[int, float] = {}

    def polling_worker() -> None:
        while not stop_event.is_set():
            t0 = time.time()
            wake_event.clear()

            with state.lock:
                is_halted = state.halted
                need_disc = state.needs_discovery
                need_settings = state.force_settings_refresh
                need_time_sync = state.force_time_sync
                active_cfg = state.config

            if is_halted:
                wake_event.wait(0.5)
                continue

            try:
                # 1. Dacă este necesară scanarea automată a lanțului (la pornire / schimbare port / rescanare)
                if need_disc:
                    found_ids, stopped_at_id = discover_daisy_chain(
                        config=active_cfg, start_id=1, max_id=247
                    )
                    with state.lock:
                        state.needs_discovery = False
                        state.active_ids = list(found_ids)
                        state.force_settings_refresh = True
                        need_settings = True

                        state.devices = {
                            str(sid): state.devices[str(sid)]
                            for sid in found_ids
                            if str(sid) in state.devices
                        }

                        if len(found_ids) == 0:
                            state.ok = False
                            state.last_error = (
                                f"Niciun dispozitiv nu a răspuns la Slave ID #1 pe {active_cfg.port}."
                            )
                            empty_avg = compute_fleet_averages({})
                            state.averages = [asdict(m) for m in empty_avg]
                            state.averages_indicators = [
                                asdict(ind)
                                for ind in compute_energy_indicators(empty_avg)
                            ]
                            state.chain_alert = {
                                "pending": True,
                                "reason": "initial_scan",
                                "detected_count": 0,
                                "active_ids": [],
                                "stopped_at_id": 1,
                                "previous_count": 0,
                                "lost_ids": [],
                                "message": (
                                    f"La scanarea portului {active_cfg.port}, nu s-a primit răspuns "
                                    "nici măcar de la primul dispozitiv din lanț (Slave ID #1). "
                                    "Verifică dacă toate dispozitivele sunt conectate sau dacă există o problemă hardware!"
                                ),
                            }
                        else:
                            state.chain_alert = {
                                "pending": True,
                                "reason": "initial_scan",
                                "detected_count": len(found_ids),
                                "active_ids": list(found_ids),
                                "stopped_at_id": stopped_at_id,
                                "previous_count": len(found_ids),
                                "lost_ids": [],
                                "message": (
                                    f"Scanarea automată a găsit {len(found_ids)} dispozitiv(e) în lanț "
                                    f"(ID #{found_ids[0]} .. ID #{found_ids[-1]}). "
                                    f"De la Slave ID #{stopped_at_id} încolo nu se mai primește răspuns. "
                                    "Toate dispozitivele sunt conectate sau a apărut o problemă în sistem?"
                                ),
                            }

                # 2. Citirea ciclică în lanț (1, 2, ..., K)
                with state.lock:
                    chain_to_poll = list(state.active_ids)

                if not chain_to_poll:
                    wake_event.wait(interval_sec)
                    continue

                current_snapshots: Dict[int, PxrSnapshot] = {}
                broken_at_id: Optional[int] = None

                with open_usb_modbus_client(active_cfg) as client:
                    now_epoch = time.time()
                    for sid in chain_to_poll:
                        dev_cfg = active_cfg.with_slave(sid)
                        fetch_full = (
                            need_settings
                            or (sid not in settings_cache)
                            or (sid not in max_current_cache)
                        )
                        should_sync_rtc = (
                            need_time_sync
                            or need_settings
                            or (sid not in last_sync_epoch)
                            or ((now_epoch - last_sync_epoch[sid]) >= RTC_SYNC_INTERVAL_SEC)
                        )
                        try:
                            snap = read_device_on_client(
                                client=client,
                                config=dev_cfg,
                                include_settings_and_events=fetch_full,
                                sync_time=should_sync_rtc,
                                cached_max_current_a=max_current_cache.get(sid),
                                cached_nominal_in_a=nominal_in_cache.get(sid),
                            )
                            if snap.time_synced_at:
                                time_sync_cache[sid] = snap.time_synced_at
                                last_sync_epoch[sid] = now_epoch
                            if fetch_full:
                                max_current_cache[sid] = snap.max_current_limit_a
                                nominal_in_cache[sid] = snap.nominal_current_in_a
                            current_snapshots[sid] = snap
                        except Exception:
                            broken_at_id = sid
                            break

                now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                surviving_ids = sorted(current_snapshots.keys())
                for sid in surviving_ids:
                    snap = current_snapshots[sid]
                    csv_exporter.append_snapshot(snap)
                    db_writer.enqueue_snapshot(snap)

                    if snap.protection_settings:
                        settings_cache[sid] = [
                            asdict(s) for s in snap.protection_settings
                        ]
                    if snap.event_history:
                        events_cache[sid] = [
                            asdict(ev)
                            for ev in snap.event_history
                            if ev.event_id != "ACTIV"
                        ]

                    record_live_status_transition(
                        snap=snap,
                        last_cause_per_id=last_cause_per_id,
                        session_events_per_id=session_events_per_id,
                        db_writer=db_writer,
                    )

                fleet_avg = compute_fleet_averages(current_snapshots)
                fleet_indicators = compute_energy_indicators(fleet_avg)
                total_csv_rows = csv_exporter.append_averages_row(
                    timestamp=now_str,
                    active_count=len(surviving_ids),
                    averages=fleet_avg,
                )
                db_writer.enqueue_averages(
                    active_count=len(surviving_ids),
                    averages=fleet_avg,
                    indicators=fleet_indicators,
                )

                update_state_after_poll(
                    state=state,
                    chain_to_poll=chain_to_poll,
                    current_snapshots=current_snapshots,
                    broken_at_id=broken_at_id,
                    now_str=now_str,
                    total_csv_rows=total_csv_rows,
                    settings_cache=settings_cache,
                    events_cache=events_cache,
                    session_events_per_id=session_events_per_id,
                    time_sync_cache=time_sync_cache,
                )

            except Exception as exc:
                with state.lock:
                    state.ok = False
                    state.last_error = str(exc)
                    state.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            elapsed = time.time() - t0
            wake_event.wait(max(0.2, interval_sec - elapsed))

    worker = threading.Thread(target=polling_worker, daemon=True)
    worker.start()

    server = create_dashboard_server(
        state=state,
        csv_exporter=csv_exporter,
        db_writer=db_writer,
        wake_event=wake_event,
        auth_manager=auth_manager,
        host=host,
        port=port,
    )
    url = f"http://{host}:{port}"
    print("\n" + "=" * 78)
    print(f" DASHBOARD WEB MULTI-DEVICE PORNIT: {url}")
    print(f" -> Autentificare obligatorie activată: {url}/login")
    print(" -> Scanare automată Slave ID în lanț (1, 2, 3, ...)")
    print(f" -> Actualizare automată: la fiecare {interval_sec:.1f} secunde")
    print(f" -> Salvare automată CSV: {csv_exporter.csv_path}")
    print(
        " -> TimescaleDB (Container Docker SME): Coadă RAM (max 5000) + Bulk Insert la 15s / 150 rânduri (max 300/batch)"
    )
    print(" Apasă Ctrl+C în acest terminal pentru a opri serverul.")
    print("=" * 78 + "\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nOprire Dashboard Web...")
    finally:
        stop_event.set()
        wake_event.set()
        db_writer.close()
        server.server_close()
