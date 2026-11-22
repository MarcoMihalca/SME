"""
Teste de integrare HTTP pentru autentificare, sesiuni cookie HttpOnly,
protecție CSRF, izolare preferințe UI per utilizator și matricea RBAC.
"""

from __future__ import annotations

import gc
import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from src.eaton_pxr.auth import AuthManager
from src.eaton_pxr.csv_exporter import CsvExporter
from src.eaton_pxr.models import SerialConnectionConfig
from src.eaton_pxr.web import server
from src.eaton_pxr.web.server import MultiDeviceDashboardState, create_dashboard_server


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _HttpSessionClient:
    """Client HTTP bazat pe `urllib.request` cu cookie jar și suport CSRF."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            _NoRedirectHandler(),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.csrf_token: str = ""

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        csrf: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        data = None
        headers: dict[str, str] = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=5) as resp:
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                return resp.status, hdrs, resp.read()
        except urllib.error.HTTPError as err:
            hdrs = {k.lower(): v for k, v in err.headers.items()}
            payload = err.read()
            err.close()
            return err.code, hdrs, payload

    def login(self, username: str, password: str) -> tuple[int, dict, dict[str, str]]:
        status, hdrs, raw = self.request(
            "POST",
            "/api/auth/login",
            {"username": username, "password": password},
        )
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        if status == 200:
            self.csrf_token = parsed.get("csrf_token", "")
        return status, parsed, hdrs


class TestWebAuthAndRbac(unittest.TestCase):
    """Suite de teste HTTP reale peste ThreadingHTTPServer."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "users.db")
        self.csv_path = os.path.join(self.tmpdir.name, "telemetry.csv")
        self.orig_ui_prefs = server.UI_PREFS_PATH
        server.UI_PREFS_PATH = os.path.join(self.tmpdir.name, "ui_prefs.json")

        self.auth_manager = AuthManager(db_path=self.db_path)
        self.csv_exporter = CsvExporter(self.csv_path)
        self.state = MultiDeviceDashboardState(
            config=SerialConnectionConfig(port="COM5"),
            csv_path=self.csv_path,
            db_writer=None,
        )
        self.wake_event = threading.Event()
        self.httpd = create_dashboard_server(
            state=self.state,
            csv_exporter=self.csv_exporter,
            db_writer=None,
            wake_event=self.wake_event,
            auth_manager=self.auth_manager,
            host="127.0.0.1",
            port=0,
        )
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.server_thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True
        )
        self.server_thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server_thread.join(timeout=3.0)
        server.UI_PREFS_PATH = self.orig_ui_prefs
        gc.collect()
        self.tmpdir.cleanup()

    def test_unauthenticated_access_and_security_headers(self) -> None:
        client = _HttpSessionClient(self.base_url)

        st, hdrs, _ = client.request("GET", "/")
        self.assertEqual(st, 302)
        self.assertEqual(hdrs.get("location"), "/login")
        self.assertEqual(hdrs.get("x-content-type-options"), "nosniff")
        self.assertEqual(hdrs.get("x-frame-options"), "DENY")
        self.assertIn("default-src 'self'", hdrs.get("content-security-policy", ""))

        st_login, _, body_login = client.request("GET", "/login")
        self.assertEqual(st_login, 200)
        self.assertIn(b"Autentificare", body_login)

        st_health, _, _ = client.request("GET", "/api/health")
        self.assertEqual(st_health, 200)

        for protected in ("/api/data", "/api/ports", "/api/users", "/api/csv"):
            st_api, _, _ = client.request("GET", protected)
            self.assertEqual(st_api, 401, f"Expected 401 on {protected}")

    def test_admin_login_cookie_flags_csrf_and_user_management(self) -> None:
        admin = _HttpSessionClient(self.base_url)

        st_bad, _, _ = admin.login("admin", "WrongPass1")
        self.assertEqual(st_bad, 401)

        st_ok, data_ok, hdrs_ok = admin.login("admin", "Admin123!")
        self.assertEqual(st_ok, 200)
        self.assertEqual(data_ok["user"]["role"], "admin")
        self.assertIn("users:manage", data_ok["permissions"])
        set_cookie = hdrs_ok.get("set-cookie", "")
        self.assertIn("sme_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Lax", set_cookie)

        # /api/auth/me funcționează și /login redirecționează către /
        st_me, _, raw_me = admin.request("GET", "/api/auth/me")
        self.assertEqual(st_me, 200)
        me_json = json.loads(raw_me.decode("utf-8"))
        self.assertEqual(me_json["user"]["username"], "admin")

        st_redir, hdr_redir, _ = admin.request("GET", "/login")
        self.assertEqual(st_redir, 302)
        self.assertEqual(hdr_redir.get("location"), "/")

        # Protecția CSRF refuză mutațiile fără X-CSRF-Token sau cu token greșit
        for path, body in (
            ("/api/users", {"username": "stu1", "password": "UserPass1", "role": "user"}),
            ("/api/connect", {"port": "COM6", "baudrate": 19200}),
            ("/api/auth/logout", {}),
        ):
            st_nocsrf, _, _ = admin.request("POST", path, body, csrf=None)
            self.assertEqual(st_nocsrf, 403)
            st_badcsrf, _, _ = admin.request("POST", path, body, csrf="invalid-csrf")
            self.assertEqual(st_badcsrf, 403)

        # Admin creează un utilizator obișnuit
        st_create, _, _ = admin.request(
            "POST",
            "/api/users",
            {"username": "student_lab", "password": "LabUser123", "role": "user"},
            csrf=admin.csrf_token,
        )
        self.assertEqual(st_create, 201)

        # Lista utilizatorilor nu expune salt sau password_hash
        st_list, _, raw_list = admin.request("GET", "/api/users")
        self.assertEqual(st_list, 200)
        users_list = json.loads(raw_list.decode("utf-8"))["users"]
        self.assertEqual(len(users_list), 2)
        for u in users_list:
            self.assertNotIn("salt", u)
            self.assertNotIn("password_hash", u)

        stu_id = [u["id"] for u in users_list if u["username"] == "student_lab"][0]
        admin_id = [u["id"] for u in users_list if u["username"] == "admin"][0]

        # Auto-protecție admin (nu se poate șterge, retrograda sau dezactiva)
        st_self_del, _, _ = admin.request(
            "DELETE", f"/api/users/{admin_id}", csrf=admin.csrf_token
        )
        self.assertEqual(st_self_del, 400)
        st_self_demote, _, _ = admin.request(
            "PATCH",
            f"/api/users/{admin_id}",
            {"role": "user"},
            csrf=admin.csrf_token,
        )
        self.assertEqual(st_self_demote, 400)

        # Admin poate reseta parola și consulta audit logs
        st_reset, _, _ = admin.request(
            "POST",
            f"/api/users/{stu_id}/reset-password",
            {"new_password": "LabUser999"},
            csrf=admin.csrf_token,
        )
        self.assertEqual(st_reset, 200)

        st_audit, _, raw_audit = admin.request("GET", "/api/audit-logs?limit=20")
        self.assertEqual(st_audit, 200)
        logs = json.loads(raw_audit.decode("utf-8"))["logs"]
        self.assertTrue(any(entry["action"] == "user_created" for entry in logs))

    def test_regular_user_rbac_and_session_invalidation(self) -> None:
        admin = _HttpSessionClient(self.base_url)
        st_a, _, _ = admin.login("admin", "Admin123!")
        self.assertEqual(st_a, 200)
        st_c, _, _ = admin.request(
            "POST",
            "/api/users",
            {"username": "viewer1", "password": "ViewerPass1", "role": "user"},
            csrf=admin.csrf_token,
        )
        self.assertEqual(st_c, 201)
        _, _, raw_list = admin.request("GET", "/api/users")
        viewer_id = [
            u["id"]
            for u in json.loads(raw_list.decode("utf-8"))["users"]
            if u["username"] == "viewer1"
        ][0]

        user_client = _HttpSessionClient(self.base_url)
        st_u, u_data, _ = user_client.login("viewer1", "ViewerPass1")
        self.assertEqual(st_u, 200)
        self.assertEqual(u_data["user"]["role"], "user")

        # Rute permise pentru rolul `user`
        for path in ("/", "/api/auth/me", "/api/data", "/api/ports", "/api/csv"):
            st_ok, _, _ = user_client.request("GET", path)
            self.assertEqual(st_ok, 200, f"Expected 200 for user on GET {path}")

        st_demo, _, _ = user_client.request(
            "POST",
            "/api/db-enqueue-demo",
            {"values": {"I_A": 400.0}, "persist_to_db": False},
            csrf=user_client.csrf_token,
        )
        self.assertEqual(st_demo, 200)

        # Izolare preferințe UI per utilizator
        st_p1, _, _ = admin.request(
            "POST",
            "/api/ui-config",
            {"viewMode": "advanced", "theme": "dark"},
            csrf=admin.csrf_token,
        )
        self.assertEqual(st_p1, 200)
        st_p2, _, _ = user_client.request(
            "POST",
            "/api/ui-config",
            {"viewMode": "simple", "theme": "light"},
            csrf=user_client.csrf_token,
        )
        self.assertEqual(st_p2, 200)
        _, _, raw_up = user_client.request("GET", "/api/ui-config")
        _, _, raw_ap = admin.request("GET", "/api/ui-config")
        self.assertEqual(json.loads(raw_up.decode("utf-8"))["theme"], "light")
        self.assertEqual(json.loads(raw_ap.decode("utf-8"))["theme"], "dark")

        # Rute interzise (403) pentru rolul `user`
        forbidden_gets = ("/api/users", "/api/audit-logs")
        for path in forbidden_gets:
            st_403, _, _ = user_client.request("GET", path)
            self.assertEqual(st_403, 403, f"Expected 403 on GET {path}")

        forbidden_posts = (
            ("/api/connect", {"port": "COM6", "baudrate": 19200}),
            ("/api/scan-chain", {"port": "COM6", "baudrate": 19200}),
            ("/api/chain-alert-action", {"action": "ok"}),
            ("/api/resume-reading", {}),
            ("/api/sync-time", {}),
            ("/api/refresh-settings", {}),
            ("/api/db-flush", {}),
            ("/api/db-enqueue-demo", {"values": {"I_A": 400.0}, "persist_to_db": True}),
            ("/api/users", {"username": "x1", "password": "PassWord1", "role": "user"}),
            (f"/api/users/{viewer_id}/reset-password", {"new_password": "NewPass12"}),
        )
        for path, body in forbidden_posts:
            st_403, _, _ = user_client.request(
                "POST", path, body, csrf=user_client.csrf_token
            )
            self.assertEqual(st_403, 403, f"Expected 403 on POST {path}")

        st_patch_403, _, _ = user_client.request(
            "PATCH", "/api/users/1", {"role": "user"}, csrf=user_client.csrf_token
        )
        self.assertEqual(st_patch_403, 403)
        st_del_403, _, _ = user_client.request(
            "DELETE", "/api/users/1", csrf=user_client.csrf_token
        )
        self.assertEqual(st_del_403, 403)

        # Schimbarea parolei proprii de către user
        st_cp, _, _ = user_client.request(
            "POST",
            "/api/auth/change-password",
            {"current_password": "ViewerPass1", "new_password": "ViewerPass2"},
            csrf=user_client.csrf_token,
        )
        self.assertEqual(st_cp, 200)

        # Când admin resetează parola utilizatorului, sesiunea acestuia devine invalidă (401)
        st_adm_rst, _, _ = admin.request(
            "POST",
            f"/api/users/{viewer_id}/reset-password",
            {"new_password": "ViewerPass3"},
            csrf=admin.csrf_token,
        )
        self.assertEqual(st_adm_rst, 200)

        st_after_reset, _, _ = user_client.request("GET", "/api/data")
        self.assertEqual(st_after_reset, 401)

        # Re-autentificare și logout -> cookie-ul devine invalid (401)
        st_relog, _, _ = user_client.login("viewer1", "ViewerPass3")
        self.assertEqual(st_relog, 200)
        st_out, _, _ = user_client.request(
            "POST", "/api/auth/logout", {}, csrf=user_client.csrf_token
        )
        self.assertEqual(st_out, 200)
        st_after_out, _, _ = user_client.request("GET", "/api/data")
        self.assertEqual(st_after_out, 401)


if __name__ == "__main__":
    unittest.main()
