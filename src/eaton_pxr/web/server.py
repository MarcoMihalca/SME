"""
Serverul HTTP și firul de execuție pentru achiziția în fundal (o dată la 2 secunde)
al Dashboard-ului Web Multi-Device în lanț (daisy-chain RS-485).

Caracteristici cheie:
  1. Caută automat Slave ID-urile în lanț (1, 2, 3, ...).
  2. Unde nu se mai primește răspuns (la scanare sau dacă un aparat cade în timpul
     funcționării), aparatele următoare din lanț "dispar" (informația nu trece mai departe)
     și se afișează un Pop-up în Dashboard cu numărul total de aparate găsite și opțiunile:
       - "OK" (confirmă că acestea sunt toate aparatele și continuă citirea)
       - "Problemă!" (oprește complet citirea pentru intervenție/reparație hardware).
  3. Calculează mediile (Average-urile) tuturor aparatelor active și păstrează datele
     individuale (măsurători, setări protecție, istoric declanșări) pentru fiecare ID separat.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from ..connection import (
    get_available_serial_ports,
    normalize_com_port,
    open_usb_modbus_client,
)
from ..csv_exporter import CsvExporter
from ..models import PxrSnapshot, SerialConnectionConfig, TripEvent
from ..reader import read_device_on_client
from ..scanner import compute_fleet_averages, discover_daisy_chain


TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "templates", "dashboard.html"
)


class MultiDeviceDashboardState:
    """Starea partajată thread-safe pentru întregul lanț de aparate PXR25."""

    def __init__(self, config: SerialConnectionConfig, csv_path: str) -> None:
        self.lock = threading.Lock()
        self.config: SerialConnectionConfig = config
        self.csv_path = csv_path

        self.ok: bool = False
        self.halted: bool = False
        self.last_error: str = "Se scanează automat lanțul de dispozitive (Slave ID 1, 2, ...)..."
        self.timestamp: str = "—"
        self.poll_count: int = 0
        self.csv_rows: int = 0

        # Lanțul de ID-uri detectate și confirmate
        self.active_ids: List[int] = []
        self.confirmed_ids: Optional[List[int]] = None
        self.needs_discovery: bool = True
        self.force_settings_refresh: bool = True

        # Datele per Slave ID și mediile pe întregul lanț
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.averages: List[Dict[str, Any]] = []

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
                "chain_alert": dict(self.chain_alert),
            }


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
    și serverul HTTP al Dashboard-ului Web.
    """
    state = MultiDeviceDashboardState(config=config, csv_path=csv_exporter.csv_path)
    stop_event = threading.Event()
    wake_event = threading.Event()

    # Păstrăm în memorie setările de protecție și istoricul fiecărui Slave ID
    settings_cache: Dict[int, List[Dict[str, Any]]] = {}
    events_cache: Dict[int, List[Dict[str, Any]]] = {}
    session_events_per_id: Dict[int, List[TripEvent]] = {}
    last_cause_per_id: Dict[int, str] = {}

    def polling_worker() -> None:
        while not stop_event.is_set():
            t0 = time.time()
            wake_event.clear()

            with state.lock:
                is_halted = state.halted
                need_disc = state.needs_discovery
                need_settings = state.force_settings_refresh
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
                    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                    with state.lock:
                        state.needs_discovery = False
                        state.active_ids = list(found_ids)
                        state.force_settings_refresh = True
                        need_settings = True

                        # Eliminăm din afișare orice dispozitiv care nu se află în lanțul găsit
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
                            state.averages = [asdict(m) for m in compute_fleet_averages({})]
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
                            # S-au găsit `found_ids` (ex: 1..N), iar la `stopped_at_id` (N+1) nu s-a mai primit răspuns
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
                    for sid in chain_to_poll:
                        dev_cfg = active_cfg.with_slave(sid)
                        fetch_full = need_settings or (sid not in settings_cache)
                        try:
                            snap = read_device_on_client(
                                client=client,
                                config=dev_cfg,
                                include_settings_and_events=fetch_full,
                            )
                            current_snapshots[sid] = snap
                        except Exception:
                            # Deoarece conexiunea este în lanț (daisy-chain), dacă `sid` (ex: ID 10)
                            # se defectează / nu mai răspunde, OPRIM IMEDIAT citirea aici!
                            # Nimic de la `sid` încolo (ex: 10..20) nu mai continuă — restul "dispar".
                            broken_at_id = sid
                            break

                now_str = time.strftime("%Y-%m-%d %H:%M:%S")

                # Actualizăm cache-ul și CSV-ul doar pentru dispozitivele care au răspuns până la întrerupere
                surviving_ids = sorted(current_snapshots.keys())
                for sid in surviving_ids:
                    snap = current_snapshots[sid]
                    csv_exporter.append_snapshot(snap)

                    if snap.protection_settings:
                        settings_cache[sid] = [asdict(s) for s in snap.protection_settings]
                    if snap.event_history:
                        events_cache[sid] = [
                            asdict(ev) for ev in snap.event_history if ev.event_id != "ACTIV"
                        ]

                    cur_cause = (
                        f"{snap.status_info.get('Stare Principală Disjunctor', '')} — "
                        f"{snap.status_info.get('Cauză Stare / Eveniment', '')}"
                    )
                    if last_cause_per_id.get(sid) != cur_cause:
                        last_cause_per_id[sid] = cur_cause
                        by_key = {m.key: (m.value or 0.0) for m in snap.measurements}
                        cur_fmt = (
                            f"IA={by_key.get('I_A', 0.0):.1f}A, "
                            f"IB={by_key.get('I_B', 0.0):.1f}A, "
                            f"IC={by_key.get('I_C', 0.0):.1f}A, "
                            f"IG={by_key.get('I_G', 0.0):.1f}A"
                        )
                        lst = session_events_per_id.setdefault(sid, [])
                        lst.insert(
                            0,
                            TripEvent(
                                event_id=str(len(lst) + 1),
                                event_type="Live",
                                timestamp=snap.timestamp,
                                cause=cur_cause,
                                currents=cur_fmt,
                            ),
                        )

                fleet_avg = compute_fleet_averages(current_snapshots)
                total_csv_rows = csv_exporter.append_averages_row(
                    timestamp=now_str,
                    active_count=len(surviving_ids),
                    averages=fleet_avg,
                )

                with state.lock:
                    state.force_settings_refresh = False
                    state.timestamp = now_str
                    state.poll_count += 1
                    state.csv_rows = total_csv_rows

                    # Construim dicționarul `devices` DOAR cu ID-urile vizibile (1 .. broken_at_id-1)
                    # Tot ce era de la `broken_at_id` încolo DISPARE imediat!
                    new_devices_dict: Dict[str, Dict[str, Any]] = {}
                    for sid in surviving_ids:
                        snap = current_snapshots[sid]
                        combined_ev = [
                            asdict(ev) for ev in session_events_per_id.get(sid, [])[:10]
                        ] + events_cache.get(sid, [])
                        new_devices_dict[str(sid)] = {
                            "slave_id": sid,
                            "timestamp": snap.timestamp,
                            "connection_desc": snap.connection_desc,
                            "status_info": snap.status_info,
                            "measurements": [asdict(m) for m in snap.measurements],
                            "protection_settings": settings_cache.get(sid, []),
                            "event_history": combined_ev,
                        }

                    state.devices = new_devices_dict
                    state.averages = [asdict(m) for m in fleet_avg]
                    state.active_ids = surviving_ids

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
                    else:
                        state.ok = True
                        state.last_error = ""

            except Exception as exc:
                with state.lock:
                    state.ok = False
                    state.last_error = str(exc)
                    state.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            elapsed = time.time() - t0
            wake_event.wait(max(0.2, interval_sec - elapsed))

    worker = threading.Thread(target=polling_worker, daemon=True)
    worker.start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/index.html"):
                with open(TEMPLATE_PATH, "rb") as f:
                    html_bytes = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)

            elif self.path.startswith("/api/ports"):
                raw_ports = get_available_serial_ports()
                port_list = []
                for dev, desc in raw_ports:
                    upper = desc.upper()
                    is_usb = any(
                        k in upper for k in ("USB", "CH340", "FTDI", "CP210", "RS485")
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
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif self.path.startswith("/api/data"):
                body = json.dumps(state.to_json_dict(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif self.path.startswith("/api/csv"):
                if os.path.exists(csv_exporter.csv_path):
                    with open(csv_exporter.csv_path, "rb") as csv_f:
                        csv_bytes = csv_f.read()
                    filename = os.path.basename(csv_exporter.csv_path)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header(
                        "Content-Disposition", f'attachment; filename="{filename}"'
                    )
                    self.send_header("Content-Length", str(len(csv_bytes)))
                    self.end_headers()
                    self.wfile.write(csv_bytes)
                else:
                    msg = "Fișierul CSV nu are încă înregistrări.".encode("utf-8")
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(msg)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                req = json.loads(raw_body.decode("utf-8"))
            except Exception:
                req = {}

            if self.path.startswith("/api/connect") or self.path.startswith("/api/scan-chain"):
                with state.lock:
                    new_port = normalize_com_port(req.get("port", state.config.port))
                    new_baud = int(req.get("baudrate", state.config.baudrate))
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
                wake_event.set()
                self._send_ok()

            elif self.path.startswith("/api/chain-alert-action"):
                # Acțiunea aleasă de utilizator în Pop-up: "ok" sau "problem"
                action = req.get("action", "ok")
                with state.lock:
                    state.chain_alert["pending"] = False
                    if action == "problem":
                        # Oprește complet citirea pentru ca tehnicianul să poată repara hardware-ul!
                        state.halted = True
                        state.ok = False
                        state.last_error = (
                            "CITIRE OPRITĂ PENTRU INTERVENȚIE HARDWARE "
                            f"(Problema raportată la Slave ID #{state.chain_alert.get('stopped_at_id', '?')})."
                        )
                    else:
                        # Utilizatorul a confirmat "OK" -> continuăm cu dispozitivele active găsite
                        state.confirmed_ids = list(state.active_ids)
                        state.halted = False
                wake_event.set()
                self._send_ok()

            elif self.path.startswith("/api/resume-reading"):
                with state.lock:
                    state.halted = False
                    state.needs_discovery = True
                    state.force_settings_refresh = True
                wake_event.set()
                self._send_ok()

            elif self.path.startswith("/api/refresh-settings"):
                with state.lock:
                    state.force_settings_refresh = True
                wake_event.set()
                self._send_ok()
            else:
                self.send_response(404)
                self.end_headers()

        def _send_ok(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print("\n" + "=" * 78)
    print(f" DASHBOARD WEB MULTI-DEVICE PORNIT: {url}")
    print(" -> Scanare automată Slave ID în lanț (1, 2, 3, ...)")
    print(" -> Pagină de Medii (Average-uri) + Pagini individuale per Slave ID")
    print(f" -> Actualizare automată: la fiecare {interval_sec:.1f} secunde")
    print(f" -> Salvare automată CSV: {csv_exporter.csv_path}")
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
        server.server_close()
