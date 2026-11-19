
import sqlite3
import hashlib
import secrets
import hmac

DB_NAME = "users.db"


def connect():
    return sqlite3.connect(DB_NAME)


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        310000
    )

    return salt.hex(), password_hash.hex()


def create_database():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)

    conn.commit()

    # Creăm administratorul inițial dacă baza este goală
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]

    if count == 0:
        register_user("admin", "Admin123!", "admin")

    conn.close()


def register_user(username, password, role="user"):
    if not username.strip() or not password:
        return False, "Completează toate câmpurile!"

    if role not in ("admin", "user"):
        return False, "Rol invalid!"

    salt, password_hash = hash_password(password)

    try:
        conn = connect()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO users (username, salt, password_hash, role)
            VALUES (?, ?, ?, ?)
        """, (username.strip(), salt, password_hash, role))

        conn.commit()
        conn.close()

        return True, "Utilizator adăugat cu succes!"

    except sqlite3.IntegrityError:
        return False, "Acest utilizator există deja!"


def login_user(username, password):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, username, salt, password_hash, role
        FROM users
        WHERE username = ?
    """, (username.strip(),))

    user = cursor.fetchone()
    conn.close()

    if user is None:
        return None

    user_id, name, salt, saved_hash, role = user

    _, entered_hash = hash_password(
        password,
        bytes.fromhex(salt)
    )

    if hmac.compare_digest(entered_hash, saved_hash):
        return {
            "id": user_id,
            "username": name,
            "role": role
        }

    return None


def get_users():
    conn = connect()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, username, role
        FROM users
        ORDER BY id
    """)

    users = cursor.fetchall()
    conn.close()

    return users


def delete_user(user_id):
    conn = connect()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM users WHERE id = ? AND role != 'admin'",
        (user_id,)
    )

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted > 0
