"""
Teste unitare și de regresie pentru modulul `Login/` (SQLite + interfață Tkinter).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gc
import importlib
import os
import sqlite3
import tempfile
import unittest

from Login import database


class TestLoginDatabase(unittest.TestCase):
    """Teste pentru funcționalitatea de autentificare, securitate și gestiune utilizatori."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "users.db")
        database.create_database(db_path=self.db_path)

    def tearDown(self) -> None:
        gc.collect()
        self.tmpdir.cleanup()

    def test_create_database_seeds_admin_and_is_idempotent(self) -> None:
        database.create_database(db_path=self.db_path)
        users = database.get_users(db_path=self.db_path)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0][1], "admin")
        self.assertEqual(users[0][2], "admin")

        user, msg, status = database.authenticate_user(
            "admin", "Admin123!", db_path=self.db_path
        )
        self.assertEqual(status, 200)
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "admin")
        self.assertIn("reușită", msg)

    def test_legacy_five_column_schema_migrates_cleanly(self) -> None:
        legacy_path = os.path.join(self.tmpdir.name, "legacy.db")
        salt_hex, hash_hex = database.hash_password("Legacy123")
        conn = sqlite3.connect(legacy_path)
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user'
            )
            """
        )
        conn.execute(
            "INSERT INTO users (username, salt, password_hash, role) VALUES (?, ?, ?, ?)",
            ("legacy_op", salt_hex, hash_hex, "user"),
        )
        conn.commit()
        conn.close()

        database.create_database(db_path=legacy_path)
        user, _, status = database.authenticate_user(
            "legacy_op", "Legacy123", db_path=legacy_path
        )
        self.assertEqual(status, 200)
        self.assertIsNotNone(user)
        self.assertTrue(user["is_active"])

    def test_duplicate_register_does_not_lock_database(self) -> None:
        ok1, _ = database.register_user(
            "alice", "Secret123", "user", db_path=self.db_path
        )
        self.assertTrue(ok1)

        ok_dup, msg_dup = database.register_user(
            "alice", "OtherPass9", "user", db_path=self.db_path
        )
        self.assertFalse(ok_dup)
        self.assertIn("există deja", msg_dup)

        # Următoarele operații nu trebuie să arunce `database is locked`
        ok2, _ = database.register_user(
            "bob", "Pass1234", "user", db_path=self.db_path
        )
        self.assertTrue(ok2)

        alice_id = [u[0] for u in database.get_users(db_path=self.db_path) if u[1] == "alice"][0]
        self.assertTrue(database.delete_user(alice_id, db_path=self.db_path))

    def test_validation_rules(self) -> None:
        bad_cases = [
            ("ab", "ValidPass1", "user"),
            ("bad user!", "ValidPass1", "user"),
            ("valid_user", "        ", "user"),
            ("valid_user", "short1", "user"),
            ("valid_user", "abcdefgh", "user"),
            ("valid_user", "12345678", "user"),
            ("valid_user", "ValidPass1", "superadmin"),
        ]
        for uname, pw, role in bad_cases:
            ok, msg = database.register_user(uname, pw, role, db_path=self.db_path)
            self.assertFalse(ok, f"Expected failure for {(uname, pw, role)}: {msg}")

    def test_case_insensitive_username_and_login(self) -> None:
        ok, _ = database.register_user(
            "Operator1", "StrongPass1", "user", db_path=self.db_path
        )
        self.assertTrue(ok)

        ok_dup, _ = database.register_user(
            "operator1", "StrongPass2", "user", db_path=self.db_path
        )
        self.assertFalse(ok_dup)

        user, _, status = database.authenticate_user(
            "  OPERATOR1 ", "StrongPass1", db_path=self.db_path
        )
        self.assertEqual(status, 200)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "Operator1")

    def test_account_lockout_and_admin_unlock(self) -> None:
        database.register_user("student1", "LabPass12", "user", db_path=self.db_path)
        for _ in range(database.LOCKOUT_THRESHOLD):
            user, _, status = database.authenticate_user(
                "student1", "WrongPass9", db_path=self.db_path
            )
            self.assertIsNone(user)
            self.assertEqual(status, 401)

        # A 6-a încercare chiar cu parola corectă este blocată (423)
        user, _, status = database.authenticate_user(
            "student1", "LabPass12", db_path=self.db_path
        )
        self.assertIsNone(user)
        self.assertEqual(status, 423)

        uid = [u["id"] for u in database.list_users_detailed(db_path=self.db_path) if u["username"] == "student1"][0]
        ok_unlock, _ = database.update_user(
            uid, unlock=True, actor="admin", db_path=self.db_path
        )
        self.assertTrue(ok_unlock)

        user, _, status = database.authenticate_user(
            "student1", "LabPass12", db_path=self.db_path
        )
        self.assertEqual(status, 200)
        self.assertIsNotNone(user)

    def test_admin_guards_delete_and_update(self) -> None:
        database.register_user("lab_user", "UserPass1", "user", db_path=self.db_path)
        users = database.list_users_detailed(db_path=self.db_path)
        admin_id = [u["id"] for u in users if u["username"] == "admin"][0]
        user_id = [u["id"] for u in users if u["username"] == "lab_user"][0]

        ok_del_self, _ = database.delete_user_checked(
            admin_id, actor="admin", actor_id=admin_id, db_path=self.db_path
        )
        self.assertFalse(ok_del_self)
        self.assertFalse(database.delete_user(admin_id, db_path=self.db_path))

        ok_demote_self, _ = database.update_user(
            admin_id, role="user", actor="admin", actor_id=admin_id, db_path=self.db_path
        )
        self.assertFalse(ok_demote_self)

        ok_last_admin, _ = database.update_user(
            admin_id, is_active=False, actor="system", db_path=self.db_path
        )
        self.assertFalse(ok_last_admin)

        ok_del_user, _ = database.delete_user_checked(
            user_id, actor="admin", actor_id=admin_id, db_path=self.db_path
        )
        self.assertTrue(ok_del_user)

    def test_password_change_reset_and_session_lifecycle(self) -> None:
        database.register_user("eng1", "InitialPass1", "user", db_path=self.db_path)
        eng_id = [u["id"] for u in database.list_users_detailed(db_path=self.db_path) if u["username"] == "eng1"][0]

        tok1, _ = database.create_session(eng_id, db_path=self.db_path)
        tok2, _ = database.create_session(eng_id, db_path=self.db_path)
        self.assertIsNotNone(database.validate_session(tok1, db_path=self.db_path))
        self.assertIsNotNone(database.validate_session(tok2, db_path=self.db_path))

        # Schimbare parolă cu parolă veche greșită eșuează
        ok_bad, _ = database.change_password(
            eng_id, "WrongOld1", "NewStrong2", keep_session_token=tok1, db_path=self.db_path
        )
        self.assertFalse(ok_bad)

        # Schimbare reușită păstrează tok1 și revocă tok2
        ok_good, _ = database.change_password(
            eng_id, "InitialPass1", "NewStrong2", keep_session_token=tok1, db_path=self.db_path
        )
        self.assertTrue(ok_good)
        self.assertIsNotNone(database.validate_session(tok1, db_path=self.db_path))
        self.assertIsNone(database.validate_session(tok2, db_path=self.db_path))

        # Resetare parolă de către admin revocă toate sesiunile
        ok_reset, _ = database.reset_password(
            eng_id, "AdminReset9", actor="admin", db_path=self.db_path
        )
        self.assertTrue(ok_reset)
        self.assertIsNone(database.validate_session(tok1, db_path=self.db_path))

        # Sesiune expirată este curățată
        tok_exp, _ = database.create_session(eng_id, ttl_seconds=60, db_path=self.db_path)
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        with database.get_connection(self.db_path) as conn:
            conn.execute("UPDATE sessions SET expires_at = ?", (past_iso,))
        self.assertIsNone(database.validate_session(tok_exp, db_path=self.db_path))

        # Audit log înregistrat
        logs = database.get_audit_logs(limit=20, db_path=self.db_path)
        actions = {entry["action"] for entry in logs}
        self.assertIn("seed_admin", actions)
        self.assertIn("user_created", actions)
        self.assertIn("password_changed", actions)
        self.assertIn("password_reset", actions)

    def test_tkinter_login_module_imports_without_launching_gui(self) -> None:
        mod = importlib.import_module("Login.main")
        self.assertTrue(hasattr(mod, "LoginApp"))
        self.assertTrue(hasattr(mod, "main"))


if __name__ == "__main__":
    unittest.main()
