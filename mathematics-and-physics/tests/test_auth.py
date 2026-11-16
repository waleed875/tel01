"""Authentication regression tests: password hashing, session CSRF and isolation."""
import secrets
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from auth import hash_password, verify_password, AuthStore
from webapp import app


class PasswordTests(unittest.TestCase):
    def test_unique_salted_hashes_and_verification(self):
        password = "A_very_long_private_password_2026"
        a, b = hash_password(password), hash_password(password)
        self.assertNotEqual(a, b)
        self.assertTrue(verify_password(password, a))
        self.assertFalse(verify_password("incorrect!", a))
        with self.assertRaises(ValueError):
            hash_password("short")

    def test_reject_unknown_format(self):
        self.assertFalse(verify_password("anything", "bad"))
        self.assertFalse(verify_password("anything", "scrypt$1$1$1$0$0"))


class FakeAuthStore:
    def __init__(self):
        self.sessions = {}
        self.logins = 0

    def login(self, username, password):
        self.logins += 1
        if username != "admin" or password != "valid-local-password":
            return None
        token, csrf = "a"*64, "b"*64
        self.sessions[token] = {"user_id": 1, "username": "admin", "role": "admin",
                                "csrf_hash": csrf}
        return {"token": token, "csrf": csrf, "user_id": 1,
                "username": "admin", "role": "admin"}

    def session(self, token):
        return self.sessions.get(token)

    def rotate_csrf(self, token):
        return "b"*64 if token in self.sessions else None

    def verify_csrf(self, token, csrf):
        return token in self.sessions and csrf == "b"*64

    def logout(self, token):
        self.sessions.pop(token, None)


class LoginAPITests(unittest.TestCase):
    def test_login_cookie_rejected_unsafe_requests_and_logout(self):
        store = FakeAuthStore()
        with patch("webapp.auth_store", store):
            client = TestClient(app)
            self.assertFalse(client.get("/api/auth/state").json()["authenticated"])
            missing = client.get("/api/profile")
            self.assertEqual(missing.status_code, 401)
            failed = client.post("/api/auth/login",
                json={"username": "admin", "password": "wrong"})
            self.assertEqual(failed.status_code, 401)
            login = client.post("/api/auth/login",
                json={"username": "admin", "password": "valid-local-password"})
            self.assertEqual(login.status_code, 200)
            self.assertIn("httponly", login.headers["set-cookie"].lower())
            self.assertIn("samesite=strict", login.headers["set-cookie"].lower())
            state = client.get("/api/auth/state").json()
            self.assertEqual(state["username"], "admin")
            self.assertEqual(state["csrf"], "b"*64)
            csrf_fail = client.post("/api/auth/logout")
            self.assertEqual(csrf_fail.status_code, 403)
            origin_fail = client.post("/api/auth/logout",
                headers={"Origin": "http://evil.example",
                         "X-CSRF-Token": "b"*64})
            self.assertEqual(origin_fail.status_code, 403)
            success = client.post("/api/auth/logout", headers={"X-CSRF-Token": "b"*64})
            self.assertEqual(success.status_code, 200)
            self.assertFalse(client.get("/api/auth/state").json()["authenticated"])
            self.assertEqual(client.post("/api/auth/logout", headers={
                "X-CSRF-Token": "b"*64
            }).status_code, 403)


class ProtectedProjectTests(unittest.TestCase):
    def test_cookie_identity_controls_cross_account_gitea_access(self):
        class FakeProjectDB:
            def engineering_project(self, user_id, project_id):
                if user_id == 1 and project_id == 7:
                    return {"id": 7, "repo_name": "engineering-private", "deletion_state": "active"}
                return None

        store = FakeAuthStore()
        store.sessions["a"*64] = {"user_id": 1, "username": "alice",
                                  "role": "admin", "csrf_hash": "b"*64}
        store.sessions["c"*64] = {"user_id": 2, "username": "bob",
                                  "role": "user", "csrf_hash": "d"*64}
        with patch("webapp.auth_store", store):
            from webapp import db
            from gitea_client import GiteaClient
            from unittest.mock import AsyncMock
            app.dependency_overrides[db] = lambda: FakeProjectDB()
            try:
                client = TestClient(app)
                client.cookies.set("engai_auth", "a"*64)
                with patch.object(GiteaClient, "entries", new_callable=AsyncMock) as entries:
                    entries.return_value = []
                    self.assertEqual(client.get("/api/projects/7/files").status_code, 200)
                    client.cookies.set("engai_auth", "c"*64)
                    self.assertEqual(client.get("/api/projects/7/files").status_code, 404)
                    self.assertEqual(entries.await_count, 1)
            finally:
                app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
