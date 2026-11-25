"""
Serviciul de autentificare, sesiuni cookie HttpOnly, protecție CSRF, limitare rată
și control de acces bazat pe roluri (RBAC) pentru serverul Web SME.

Partajează aceeași bază de date SQLite (`Login/users.db`) cu utilitarul desktop
`Login/main.py` prin modulul `Login/database.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
from http.cookies import CookieError, SimpleCookie
import importlib.util
import os
import threading
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOGIN_DB_MODULE_PATH = os.path.join(PROJECT_ROOT, "Login", "database.py")

# Permisiuni granulare RBAC
PERM_TELEMETRY_READ = "telemetry:read"
PERM_CSV_EXPORT = "csv:export"
PERM_UI_PREFS = "ui:prefs"
PERM_DEMO_RUN = "demo:run"
PERM_HARDWARE_CONTROL = "hardware:control"
PERM_DB_FLUSH = "db:flush"
PERM_USERS_MANAGE = "users:manage"
PERM_AUDIT_READ = "audit:read"

ROLE_PERMISSIONS: Dict[str, FrozenSet[str]] = {
    "user": frozenset(
        {
            PERM_TELEMETRY_READ,
            PERM_CSV_EXPORT,
            PERM_UI_PREFS,
            PERM_DEMO_RUN,
        }
    ),
    "admin": frozenset(
        {
            PERM_TELEMETRY_READ,
            PERM_CSV_EXPORT,
            PERM_UI_PREFS,
            PERM_DEMO_RUN,
            PERM_HARDWARE_CONTROL,
            PERM_DB_FLUSH,
            PERM_USERS_MANAGE,
            PERM_AUDIT_READ,
        }
    ),
}


def _load_login_db_module() -> Any:
    """Încarcă `Login/database.py` indiferent de directorul de lucru sau `sys.path`."""
    try:
        from Login import database as login_db  # type: ignore

        return login_db
    except ImportError:
        spec = importlib.util.spec_from_file_location(
            "login_database", LOGIN_DB_MODULE_PATH
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"Nu s-a putut încărca modulul Login/database.py de la {LOGIN_DB_MODULE_PATH}"
            )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


class SlidingWindowRateLimiter:
    """Limitator thread-safe cu fereastră glisantă pentru încercări eșuate pe IP."""

    def __init__(self, max_attempts: int = 15, window_seconds: int = 300) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self._lock = threading.Lock()
        self._attempts: Dict[str, List[float]] = {}

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [t for t in self._attempts.get(key, []) if t > cutoff]
            if recent:
                self._attempts[key] = recent
            else:
                self._attempts.pop(key, None)
            if len(recent) >= self.max_attempts:
                retry_after = max(
                    1, int(self.window_seconds - (now - recent[0])) + 1
                )
                return False, retry_after
            return True, 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [t for t in self._attempts.get(key, []) if t > cutoff]
            recent.append(now)
            self._attempts[key] = recent

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


@dataclass(frozen=True)
class SessionContext:
    """Contextul autentificat al unei cereri HTTP."""

    user: Dict[str, Any]
    permissions: List[str]
    csrf_token: str
    token: str
    expires_at: str


class AuthManager:
    """Coordonează autentificarea, sesiunile cookie, CSRF, RBAC și auditul."""

    SESSION_COOKIE_NAME = "sme_session"

    def __init__(
        self,
        db_path: Optional[str] = None,
        session_ttl_seconds: int = 8 * 3600,
        max_failed_per_ip: int = 15,
        rate_limit_window_sec: int = 300,
    ) -> None:
        self._db = _load_login_db_module()
        self.db_path = db_path if db_path is not None else self._db.DB_NAME
        self.session_ttl_seconds = max(60, int(session_ttl_seconds))
        self.rate_limiter = SlidingWindowRateLimiter(
            max_attempts=max_failed_per_ip,
            window_seconds=rate_limit_window_sec,
        )
        self._db.create_database(db_path=self.db_path)
        self._db.purge_expired_sessions(db_path=self.db_path)

    @staticmethod
    def permissions_for_role(role: str) -> List[str]:
        return sorted(ROLE_PERMISSIONS.get(str(role), frozenset()))

    def extract_session_token(self, cookie_header: Optional[str]) -> Optional[str]:
        if not cookie_header:
            return None
        cookie: SimpleCookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except CookieError:
            return None
        morsel = cookie.get(self.SESSION_COOKIE_NAME)
        if morsel is None or not morsel.value:
            return None
        return str(morsel.value).strip() or None

    def build_session_cookie(
        self,
        token: str,
        max_age: Optional[int] = None,
        secure: bool = False,
    ) -> str:
        ttl = self.session_ttl_seconds if max_age is None else max(0, int(max_age))
        parts = [
            f"{self.SESSION_COOKIE_NAME}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={ttl}",
        ]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    def build_clear_cookie(self, secure: bool = False) -> str:
        parts = [
            f"{self.SESSION_COOKIE_NAME}=",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            "Max-Age=0",
        ]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    def authenticate_request(
        self, cookie_header: Optional[str]
    ) -> Optional[SessionContext]:
        token = self.extract_session_token(cookie_header)
        if not token:
            return None
        sess = self._db.validate_session(
            token,
            sliding_ttl_seconds=self.session_ttl_seconds,
            db_path=self.db_path,
        )
        if sess is None:
            return None
        user = sess["user"]
        return SessionContext(
            user=user,
            permissions=self.permissions_for_role(str(user.get("role", ""))),
            csrf_token=str(sess["csrf_token"]),
            token=token,
            expires_at=str(sess["expires_at"]),
        )

    @staticmethod
    def has_permission(ctx: Optional[SessionContext], permission: str) -> bool:
        if ctx is None:
            return False
        role = str(ctx.user.get("role", ""))
        return permission in ROLE_PERMISSIONS.get(role, frozenset())

    @staticmethod
    def verify_csrf(
        header_token: Optional[str], ctx: Optional[SessionContext]
    ) -> bool:
        if not header_token or ctx is None or not ctx.csrf_token:
            return False
        return hmac.compare_digest(str(header_token).strip(), ctx.csrf_token)

    def login(
        self,
        username: str,
        password: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> Tuple[Optional[SessionContext], str, int, int]:
        ip_key = ip_address or "127.0.0.1"
        allowed, retry_after = self.rate_limiter.is_allowed(ip_key)
        if not allowed:
            self._db.log_audit(
                actor=(username or "anonymous").strip() or "anonymous",
                action="login_rate_limited",
                target=(username or "").strip(),
                details=f"IP limitat ({retry_after}s)",
                ip_address=ip_key,
                db_path=self.db_path,
            )
            return (
                None,
                f"Prea multe încercări eșuate de pe această adresă. Încearcă din nou peste {retry_after} secunde.",
                429,
                retry_after,
            )

        user, msg, status = self._db.authenticate_user(
            username=username,
            password=password,
            ip_address=ip_key,
            db_path=self.db_path,
        )
        if user is None:
            self.rate_limiter.record_failure(ip_key)
            return None, msg, status, 0

        self.rate_limiter.reset(ip_key)
        token, csrf_token = self._db.create_session(
            user_id=int(user["id"]),
            ip_address=ip_key,
            user_agent=user_agent,
            ttl_seconds=self.session_ttl_seconds,
            db_path=self.db_path,
        )
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=self.session_ttl_seconds)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        ctx = SessionContext(
            user=user,
            permissions=self.permissions_for_role(str(user.get("role", ""))),
            csrf_token=csrf_token,
            token=token,
            expires_at=expires_at,
        )
        return ctx, msg, 200, 0

    def logout(self, ctx: SessionContext, ip_address: str = "") -> None:
        self._db.revoke_session(ctx.token, db_path=self.db_path)
        self._db.log_audit(
            actor=str(ctx.user.get("username", "unknown")),
            action="logout",
            target=str(ctx.user.get("username", "")),
            details="Sesiune închisă",
            ip_address=ip_address,
            db_path=self.db_path,
        )

    def change_password(
        self,
        ctx: SessionContext,
        current_password: str,
        new_password: str,
        ip_address: str = "",
    ) -> Tuple[bool, str]:
        return self._db.change_password(
            user_id=int(ctx.user["id"]),
            current_password=current_password,
            new_password=new_password,
            keep_session_token=ctx.token,
            ip_address=ip_address,
            db_path=self.db_path,
        )

    def list_users(self) -> List[Dict[str, Any]]:
        return self._db.list_users_detailed(db_path=self.db_path)

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        actor_ctx: SessionContext,
        ip_address: str = "",
    ) -> Tuple[bool, str, int]:
        ok, msg = self._db.register_user(
            username=username,
            password=password,
            role=role,
            actor=str(actor_ctx.user.get("username", "admin")),
            ip_address=ip_address,
            db_path=self.db_path,
        )
        if ok:
            return True, msg, 201
        if "există deja" in msg:
            return False, msg, 409
        return False, msg, 400

    def update_user(
        self,
        user_id: int,
        role: Optional[str],
        is_active: Optional[bool],
        unlock: bool,
        actor_ctx: SessionContext,
        ip_address: str = "",
    ) -> Tuple[bool, str, int]:
        ok, msg = self._db.update_user(
            user_id=user_id,
            role=role,
            is_active=is_active,
            unlock=unlock,
            actor=str(actor_ctx.user.get("username", "admin")),
            actor_id=int(actor_ctx.user["id"]),
            ip_address=ip_address,
            db_path=self.db_path,
        )
        if ok:
            return True, msg, 200
        if "nu există" in msg:
            return False, msg, 404
        return False, msg, 400

    def reset_password(
        self,
        user_id: int,
        new_password: str,
        actor_ctx: SessionContext,
        ip_address: str = "",
    ) -> Tuple[bool, str, int]:
        ok, msg = self._db.reset_password(
            user_id=user_id,
            new_password=new_password,
            actor=str(actor_ctx.user.get("username", "admin")),
            ip_address=ip_address,
            db_path=self.db_path,
        )
        if ok:
            return True, msg, 200
        if "nu există" in msg:
            return False, msg, 404
        return False, msg, 400

    def delete_user(
        self,
        user_id: int,
        actor_ctx: SessionContext,
        ip_address: str = "",
    ) -> Tuple[bool, str, int]:
        ok, msg = self._db.delete_user_checked(
            user_id=user_id,
            actor=str(actor_ctx.user.get("username", "admin")),
            actor_id=int(actor_ctx.user["id"]),
            ip_address=ip_address,
            db_path=self.db_path,
        )
        if ok:
            return True, msg, 200
        if "nu există" in msg:
            return False, msg, 404
        return False, msg, 400

    def get_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._db.get_audit_logs(limit=limit, db_path=self.db_path)

    def log_action(
        self,
        actor: str,
        action: str,
        target: str = "",
        details: str = "",
        ip_address: str = "",
    ) -> None:
        self._db.log_audit(
            actor=actor,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
            db_path=self.db_path,
        )
