"""
Strat de persistență și autentificare SQLite partajat între utilitarul desktop Tkinter
(`Login/main.py`) și serverul Web SME (`src/eaton_pxr/auth.py`).

Caracteristici de securitate și robustețe:
  - Conexiuni administrate prin context manager (`get_connection`) cu rollback + close garantat
    (previne blocajele `sqlite3.OperationalError: database is locked` la erori precum username duplicat).
  - Mod SQLite WAL + `busy_timeout = 5000 ms` + `foreign_keys = ON`.
  - Hashing PBKDF2-HMAC-SHA256 (310.000 iterații, salt aleator 16 bytes) și comparare
    în timp constant (`hmac.compare_digest`), cu dummy hash pentru protecție la enumerarea utilizatorilor.
  - Blocare temporară a contului după 5 încercări eșuate consecutive.
  - Sesiuni server-side cu token-uri hash-uite SHA-256, protecție CSRF și jurnal de audit (`auth_audit_log`).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from typing import Any, Dict, Iterator, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.environ.get("SME_USERS_DB", os.path.join(BASE_DIR, "users.db"))

PBKDF2_ITERATIONS = 310_000
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 5
DEFAULT_SESSION_TTL_SECONDS = 8 * 3600

VALID_ROLES = ("admin", "user")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_DUMMY_SALT = b"\x00" * 16


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now_iso() -> str:
    return _to_iso(_utc_now())


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    raw = str(ts).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    return db_path if db_path is not None else DB_NAME


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Deschide o conexiune SQLite configurată cu WAL, busy_timeout și foreign keys."""
    resolved = _resolve_db_path(db_path)
    if resolved != ":memory:":
        parent = os.path.dirname(os.path.abspath(resolved))
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def get_connection(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Context manager care garantează commit, rollback la eroare și închiderea conexiunii."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    """Calculează `(salt_hex, password_hash_hex)` folosind PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = secrets.token_bytes(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return salt.hex(), password_hash.hex()


def validate_username(username: Any) -> Tuple[bool, str]:
    """Validează numele de utilizator (3–32 caractere alfanumerice, `.`, `_`, `-`)."""
    if not isinstance(username, str):
        return False, "Numele de utilizator este invalid!"
    clean = username.strip()
    if not clean:
        return False, "Numele de utilizator este obligatoriu!"
    if len(clean) < 3 or len(clean) > 32:
        return False, "Numele de utilizator trebuie să aibă între 3 și 32 de caractere!"
    if not USERNAME_PATTERN.match(clean):
        return (
            False,
            "Numele de utilizator poate conține doar litere, cifre și caracterele . _ -",
        )
    return True, ""


def validate_password(password: Any) -> Tuple[bool, str]:
    """Validează parola (fără spații goale, 8–128 caractere, cel puțin o literă și o cifră)."""
    if not isinstance(password, str) or not password or not password.strip():
        return False, "Parola este obligatorie și nu poate conține doar spații!"
    if len(password) < 8:
        return False, "Parola trebuie să aibă cel puțin 8 caractere!"
    if len(password) > 128:
        return False, "Parola nu poate depăși 128 de caractere!"
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return False, "Parola trebuie să conțină cel puțin o literă și o cifră!"
    return True, ""


def _row_to_public_user(row: sqlite3.Row) -> Dict[str, Any]:
    locked_dt = _parse_iso(row["locked_until"])
    is_locked = bool(locked_dt is not None and locked_dt > _utc_now())
    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "role": str(row["role"]),
        "is_active": bool(row["is_active"]),
        "failed_attempts": int(row["failed_attempts"] or 0),
        "locked_until": row["locked_until"],
        "is_locked": is_locked,
        "must_change_password": bool(row["must_change_password"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def _insert_audit_in_tx(
    conn: sqlite3.Connection,
    actor: str,
    action: str,
    target: str = "",
    details: str = "",
    ip_address: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO auth_audit_log (timestamp, actor, action, target, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            _utc_now_iso(),
            (actor or "system")[:64],
            (action or "unknown")[:64],
            (target or "")[:128],
            (details or "")[:512],
            (ip_address or "")[:64],
        ),
    )


def create_database(db_path: Optional[str] = None) -> None:
    """Creează sau migrează tabelele SQLite și inițializează administratorul implicit."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                is_active INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT DEFAULT NULL,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_login_at TEXT DEFAULT NULL
            )
            """
        )

        # Migrare sigură pentru baze de date create cu schema veche (5 coloane)
        cursor.execute("PRAGMA table_info(users)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        migrations = (
            ("is_active", "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"),
            ("failed_attempts", "ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0"),
            ("locked_until", "ALTER TABLE users ADD COLUMN locked_until TEXT DEFAULT NULL"),
            (
                "must_change_password",
                "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0",
            ),
            ("created_at", "ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT NULL"),
            ("last_login_at", "ALTER TABLE users ADD COLUMN last_login_at TEXT DEFAULT NULL"),
        )
        for col_name, ddl in migrations:
            if col_name not in existing_cols:
                cursor.execute(ddl)
        if "created_at" not in existing_cols:
            cursor.execute(
                "UPDATE users SET created_at = ? WHERE created_at IS NULL OR created_at = ''",
                (_utc_now_iso(),),
            )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                csrf_token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                ip_address TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)"
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT DEFAULT '',
                details TEXT DEFAULT '',
                ip_address TEXT DEFAULT ''
            )
            """
        )

        # Creăm administratorul inițial în aceeași tranzacție dacă tabela este goală
        cursor.execute("SELECT COUNT(*) FROM users")
        count = int(cursor.fetchone()[0])
        if count == 0:
            default_user = os.environ.get("SME_DEFAULT_ADMIN_USER", "admin").strip() or "admin"
            default_pass = os.environ.get("SME_DEFAULT_ADMIN_PASSWORD", "Admin123!")
            salt_hex, hash_hex = hash_password(default_pass)
            now_iso = _utc_now_iso()
            cursor.execute(
                """
                INSERT INTO users (username, salt, password_hash, role, is_active, created_at)
                VALUES (?, ?, ?, 'admin', 1, ?)
                """,
                (default_user, salt_hex, hash_hex, now_iso),
            )
            _insert_audit_in_tx(
                conn,
                actor="system",
                action="seed_admin",
                target=default_user,
                details="Administrator inițial creat automat",
            )


def register_user(
    username: str,
    password: str,
    role: str = "user",
    actor: str = "system",
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Înregistrează un utilizator nou după validarea strictă a datelor."""
    ok_user, err_user = validate_username(username)
    if not ok_user:
        return False, err_user

    ok_pass, err_pass = validate_password(password)
    if not ok_pass:
        return False, err_pass

    if role not in VALID_ROLES:
        return False, "Rol invalid! Rolurile permise sunt 'admin' și 'user'."

    clean_username = username.strip()
    salt, password_hash = hash_password(password)
    now_iso = _utc_now_iso()

    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM users WHERE LOWER(username) = LOWER(?)",
                (clean_username,),
            )
            if cursor.fetchone() is not None:
                return False, "Acest utilizator există deja!"

            cursor.execute(
                """
                INSERT INTO users (username, salt, password_hash, role, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (clean_username, salt, password_hash, role, now_iso),
            )
            _insert_audit_in_tx(
                conn,
                actor=actor,
                action="user_created",
                target=clean_username,
                details=f"Rol: {role}",
                ip_address=ip_address,
            )
        return True, "Utilizator adăugat cu succes!"
    except sqlite3.IntegrityError:
        return False, "Acest utilizator există deja!"


def authenticate_user(
    username: str,
    password: str,
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str, int]:
    """
    Autentifică utilizatorul verificând parola, starea contului și blocarea temporară.
    Returnează `(user_dict | None, message, http_status)`.
    """
    clean_username = (username or "").strip() if isinstance(username, str) else ""
    if not clean_username or not isinstance(password, str) or password == "":
        return None, "Completează numele de utilizator și parola!", 400

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, salt, password_hash, role, is_active,
                   failed_attempts, locked_until, must_change_password,
                   created_at, last_login_at
            FROM users
            WHERE LOWER(username) = LOWER(?)
            """,
            (clean_username,),
        )
        row = cursor.fetchone()

        if row is None:
            # Dummy PBKDF2 hash pentru timp de răspuns uniform (anti user-enumeration)
            hash_password(password, _DUMMY_SALT)
            _insert_audit_in_tx(
                conn,
                actor=clean_username,
                action="login_failed",
                target=clean_username,
                details="Utilizator inexistent",
                ip_address=ip_address,
            )
            return None, "Nume utilizator sau parolă incorectă!", 401

        if int(row["is_active"]) == 0:
            hash_password(password, _DUMMY_SALT)
            _insert_audit_in_tx(
                conn,
                actor=row["username"],
                action="login_blocked_disabled",
                target=row["username"],
                details="Încercare autentificare pe cont dezactivat",
                ip_address=ip_address,
            )
            return None, "Contul este dezactivat. Contactează administratorul.", 403

        now = _utc_now()
        locked_dt = _parse_iso(row["locked_until"])
        if locked_dt is not None and locked_dt > now:
            _insert_audit_in_tx(
                conn,
                actor=row["username"],
                action="login_blocked_locked",
                target=row["username"],
                details=f"Cont blocat până la {row['locked_until']}",
                ip_address=ip_address,
            )
            return (
                None,
                "Cont temporar blocat din cauza încercărilor eșuate. Încearcă din nou mai târziu.",
                423,
            )

        _, entered_hash = hash_password(password, bytes.fromhex(row["salt"]))
        if hmac.compare_digest(entered_hash, row["password_hash"]):
            now_iso = _to_iso(now)
            cursor.execute(
                """
                UPDATE users
                SET failed_attempts = 0, locked_until = NULL, last_login_at = ?
                WHERE id = ?
                """,
                (now_iso, row["id"]),
            )
            _insert_audit_in_tx(
                conn,
                actor=row["username"],
                action="login_success",
                target=row["username"],
                details=f"Rol: {row['role']}",
                ip_address=ip_address,
            )
            user_dict = _row_to_public_user(row)
            user_dict["failed_attempts"] = 0
            user_dict["locked_until"] = None
            user_dict["is_locked"] = False
            user_dict["last_login_at"] = now_iso
            return user_dict, "Autentificare reușită!", 200

        # Dacă o blocare anterioară a expirat deja, resetăm contorul de la 0 înainte de incrementare
        prev_attempts = (
            0
            if (locked_dt is not None and locked_dt <= now)
            else int(row["failed_attempts"] or 0)
        )
        attempts = prev_attempts + 1
        lock_until_iso: Optional[str] = None
        if attempts >= LOCKOUT_THRESHOLD:
            lock_until_iso = _to_iso(now + timedelta(minutes=LOCKOUT_MINUTES))

        cursor.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, lock_until_iso, row["id"]),
        )
        detail = f"Parolă incorectă ({attempts}/{LOCKOUT_THRESHOLD})"
        if lock_until_iso:
            detail += f" — cont blocat {LOCKOUT_MINUTES} minute"
        _insert_audit_in_tx(
            conn,
            actor=row["username"],
            action="login_failed",
            target=row["username"],
            details=detail,
            ip_address=ip_address,
        )
        return None, "Nume utilizator sau parolă incorectă!", 401


def login_user(
    username: str,
    password: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Compatibilitate cu API-ul anterior: returnează dicționarul utilizatorului sau `None`."""
    user, _, _ = authenticate_user(username, password, db_path=db_path)
    return user


def get_users(db_path: Optional[str] = None) -> List[Tuple[int, str, str]]:
    """Compatibilitate cu API-ul anterior: returnează listă de tupluri `(id, username, role)`."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, username, role FROM users ORDER BY id ASC"
        ).fetchall()
        return [(int(r["id"]), str(r["username"]), str(r["role"])) for r in rows]


def list_users_detailed(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returnează toți utilizatorii cu metadate (fără salt sau hash)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, username, role, is_active, failed_attempts, locked_until,
                   must_change_password, created_at, last_login_at
            FROM users
            ORDER BY id ASC
            """
        ).fetchall()
        return [_row_to_public_user(r) for r in rows]


def get_user_by_id(
    user_id: int, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Returnează un utilizator după ID (fără salt sau hash)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, username, role, is_active, failed_attempts, locked_until,
                   must_change_password, created_at, last_login_at
            FROM users
            WHERE id = ?
            """,
            (int(user_id),),
        ).fetchone()
        return _row_to_public_user(row) if row is not None else None


def delete_user_checked(
    user_id: int,
    actor: str = "system",
    actor_id: Optional[int] = None,
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Șterge un utilizator non-admin, prevenind auto-ștergerea și ștergerea administratorilor."""
    if actor_id is not None and int(user_id) == int(actor_id):
        return False, "Nu îți poți șterge propriul cont!"

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, username, role FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        if row is None:
            return False, "Utilizatorul nu există!"
        if row["role"] == "admin":
            return False, "Conturile cu rol de administrator nu pot fi șterse!"

        cur = conn.execute(
            "DELETE FROM users WHERE id = ? AND role != 'admin'",
            (int(user_id),),
        )
        if cur.rowcount <= 0:
            return False, "Utilizatorul nu a putut fi șters!"

        _insert_audit_in_tx(
            conn,
            actor=actor,
            action="user_deleted",
            target=row["username"],
            details=f"ID={user_id}",
            ip_address=ip_address,
        )
    return True, "Utilizator șters cu succes!"


def delete_user(user_id: int, db_path: Optional[str] = None) -> bool:
    """Compatibilitate cu API-ul anterior: șterge un utilizator non-admin și returnează bool."""
    ok, _ = delete_user_checked(user_id, db_path=db_path)
    return ok


def update_user(
    user_id: int,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    unlock: bool = False,
    actor: str = "system",
    actor_id: Optional[int] = None,
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Actualizează rolul, starea activă sau deblochează un utilizator (cu protecție ultimul admin)."""
    if role is not None and role not in VALID_ROLES:
        return False, "Rol invalid! Rolurile permise sunt 'admin' și 'user'."

    if actor_id is not None and int(user_id) == int(actor_id):
        if role == "user":
            return False, "Nu îți poți retrograda propriul rol!"
        if is_active is False:
            return False, "Nu îți poți dezactiva propriul cont!"

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, username, role, is_active FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        if row is None:
            return False, "Utilizatorul nu există!"

        currently_active_admin = row["role"] == "admin" and int(row["is_active"]) == 1
        demoting_or_disabling = (role == "user") or (is_active is False)
        if currently_active_admin and demoting_or_disabling:
            other_admins = int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?",
                    (int(user_id),),
                ).fetchone()[0]
            )
            if other_admins == 0:
                return (
                    False,
                    "Nu poți retrograda sau dezactiva ultimul administrator activ!",
                )

        new_role = role if role is not None else str(row["role"])
        new_active = (1 if is_active else 0) if is_active is not None else int(row["is_active"])
        changes: List[str] = []

        if new_role != row["role"]:
            changes.append(f"rol: {row['role']}->{new_role}")
        if new_active != int(row["is_active"]):
            changes.append(f"activ: {bool(new_active)}")

        if unlock:
            conn.execute(
                """
                UPDATE users
                SET role = ?, is_active = ?, failed_attempts = 0, locked_until = NULL
                WHERE id = ?
                """,
                (new_role, new_active, int(user_id)),
            )
            changes.append("deblocat")
        else:
            conn.execute(
                "UPDATE users SET role = ?, is_active = ? WHERE id = ?",
                (new_role, new_active, int(user_id)),
            )

        if is_active is False:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))

        _insert_audit_in_tx(
            conn,
            actor=actor,
            action="user_updated",
            target=row["username"],
            details=", ".join(changes) if changes else "fără modificări",
            ip_address=ip_address,
        )

    return True, "Utilizator actualizat cu succes!"


def change_password(
    user_id: int,
    current_password: str,
    new_password: str,
    keep_session_token: Optional[str] = None,
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Permite utilizatorului să își schimbe propria parolă și revocă celelalte sesiuni."""
    if not isinstance(current_password, str) or not current_password:
        return False, "Introdu parola actuală!"

    ok_pass, err_pass = validate_password(new_password)
    if not ok_pass:
        return False, err_pass

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, username, salt, password_hash FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        if row is None:
            return False, "Utilizatorul nu există!"

        _, cur_hash = hash_password(current_password, bytes.fromhex(row["salt"]))
        if not hmac.compare_digest(cur_hash, row["password_hash"]):
            return False, "Parola actuală este incorectă!"

        _, same_check = hash_password(new_password, bytes.fromhex(row["salt"]))
        if hmac.compare_digest(same_check, row["password_hash"]):
            return False, "Noua parolă trebuie să fie diferită de parola actuală!"

        new_salt, new_hash = hash_password(new_password)
        conn.execute(
            """
            UPDATE users
            SET salt = ?, password_hash = ?, must_change_password = 0
            WHERE id = ?
            """,
            (new_salt, new_hash, int(user_id)),
        )

        if keep_session_token:
            conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                (int(user_id), _hash_token(keep_session_token)),
            )
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))

        _insert_audit_in_tx(
            conn,
            actor=row["username"],
            action="password_changed",
            target=row["username"],
            details="Parolă schimbată de utilizator",
            ip_address=ip_address,
        )

    return True, "Parola a fost schimbată cu succes!"


def reset_password(
    user_id: int,
    new_password: str,
    actor: str = "admin",
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Resetează parola unui utilizator (admin), deblochează contul și revocă sesiunile."""
    ok_pass, err_pass = validate_password(new_password)
    if not ok_pass:
        return False, err_pass

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, username FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        if row is None:
            return False, "Utilizatorul nu există!"

        new_salt, new_hash = hash_password(new_password)
        conn.execute(
            """
            UPDATE users
            SET salt = ?, password_hash = ?, failed_attempts = 0,
                locked_until = NULL, must_change_password = 0
            WHERE id = ?
            """,
            (new_salt, new_hash, int(user_id)),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
        _insert_audit_in_tx(
            conn,
            actor=actor,
            action="password_reset",
            target=row["username"],
            details="Parolă resetată de administrator",
            ip_address=ip_address,
        )

    return True, "Parola a fost resetată și sesiunile active au fost revocate!"


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(
    user_id: int,
    ip_address: str = "",
    user_agent: str = "",
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    db_path: Optional[str] = None,
) -> Tuple[str, str]:
    """Creează o sesiune persistentă în SQLite și returnează `(raw_token, csrf_token)`."""
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    now = _utc_now()
    now_iso = _to_iso(now)
    expires_iso = _to_iso(now + timedelta(seconds=max(60, int(ttl_seconds))))

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                token_hash, user_id, csrf_token, created_at,
                expires_at, last_seen_at, ip_address, user_agent
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token_hash,
                int(user_id),
                csrf_token,
                now_iso,
                expires_iso,
                now_iso,
                (ip_address or "")[:64],
                (user_agent or "")[:256],
            ),
        )
    return raw_token, csrf_token


def validate_session(
    raw_token: Optional[str],
    sliding_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Validează un cookie de sesiune și prelungește fereastra de expirare."""
    if not raw_token or not isinstance(raw_token, str):
        return None
    token_hash = _hash_token(raw_token)

    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT s.token_hash, s.csrf_token, s.expires_at,
                   u.id, u.username, u.role, u.is_active,
                   u.failed_attempts, u.locked_until, u.must_change_password,
                   u.created_at, u.last_login_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None

        now = _utc_now()
        exp_dt = _parse_iso(row["expires_at"])
        if int(row["is_active"]) != 1 or exp_dt is None or exp_dt <= now:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            return None

        new_expires_iso = _to_iso(
            now + timedelta(seconds=max(60, int(sliding_ttl_seconds)))
        )
        conn.execute(
            "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
            (_to_iso(now), new_expires_iso, token_hash),
        )
        return {
            "user": _row_to_public_user(row),
            "csrf_token": str(row["csrf_token"]),
            "expires_at": new_expires_iso,
        }


def revoke_session(raw_token: Optional[str], db_path: Optional[str] = None) -> None:
    """Revocă o singură sesiune după token."""
    if not raw_token:
        return
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (_hash_token(raw_token),),
        )


def revoke_user_sessions(user_id: int, db_path: Optional[str] = None) -> None:
    """Revocă toate sesiunile active ale unui utilizator."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))


def purge_expired_sessions(db_path: Optional[str] = None) -> int:
    """Șterge sesiunile expirate din SQLite și returnează numărul eliminărilor."""
    now_iso = _utc_now_iso()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?",
            (now_iso,),
        )
        return int(cur.rowcount)


def log_audit(
    actor: str,
    action: str,
    target: str = "",
    details: str = "",
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> None:
    """Înregistrează un eveniment în jurnalul de audit."""
    with get_connection(db_path) as conn:
        _insert_audit_in_tx(
            conn,
            actor=actor,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
        )


def get_audit_logs(
    limit: int = 100, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Returnează ultimele intrări din jurnalul de audit în ordine invers cronologică."""
    safe_limit = max(1, min(500, int(limit)))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, actor, action, target, details, ip_address
            FROM auth_audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "timestamp": str(r["timestamp"]),
                "actor": str(r["actor"]),
                "action": str(r["action"]),
                "target": str(r["target"] or ""),
                "details": str(r["details"] or ""),
                "ip_address": str(r["ip_address"] or ""),
            }
            for r in rows
        ]
