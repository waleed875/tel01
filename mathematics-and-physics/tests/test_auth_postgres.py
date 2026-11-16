"""Real PostgreSQL tests for account isolation and explicit legacy migration."""
import os
import secrets
import unittest

from auth import AuthStore
from storage import Storage


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class AuthPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = AuthStore(os.environ["TEST_DATABASE_URL"])
        cls.storage = Storage(os.environ["TEST_DATABASE_URL"])

    def setUp(self):
        self.username = "user" + secrets.token_hex(7)
        self.uid = self.auth.create_user(self.username, "Local_test_password_2026!")
        self.legacy_token = None

    def tearDown(self):
        if self.legacy_token:
            digest = __import__("hashlib").sha256(self.legacy_token.encode()).hexdigest()
            with self.auth.connect() as db:
                old = db.execute("SELECT user_id FROM web_sessions WHERE token_hash=%s", (digest,)).fetchone()
            if old:
                self.storage.delete_user(old["user_id"])
        with self.auth.connect() as db:
            db.execute("DELETE FROM local_accounts WHERE id=%s", (self.uid,))
        self.storage.delete_user(self.uid)

    def test_login_csrf_session_expiry_and_lockout(self):
        self.assertIsNone(self.auth.login(self.username, "wrong"))
        session = self.auth.login(self.username, "Local_test_password_2026!")
        self.assertIsNotNone(session)
        self.assertEqual(session["user_id"], self.uid)
        self.assertIsNotNone(self.auth.session(session["token"]))
        self.assertTrue(self.auth.verify_csrf(session["token"], session["csrf"]))
        self.assertFalse(self.auth.verify_csrf(session["token"], "a" * 64))
        fresh = self.auth.rotate_csrf(session["token"])
        self.assertTrue(self.auth.verify_csrf(session["token"], fresh))
        self.assertFalse(self.auth.verify_csrf(session["token"], session["csrf"]))
        self.auth.logout(session["token"])
        self.assertIsNone(self.auth.session(session["token"]))
        for _ in range(6):
            self.assertIsNone(self.auth.login(self.username, "bad-password"))
        self.assertIsNone(self.auth.login(self.username, "Local_test_password_2026!"))

    def test_legacy_claim_preserves_git_mapping_and_training(self):
        token = secrets.token_hex(32)
        self.legacy_token = token
        old_id = self.storage.get_or_create_web_session(token)
        self.assertLess(old_id, 0)
        project_name = "engineering-migrated-" + secrets.token_hex(5)
        project = self.storage.create_engineering_project(
            old_id, "Legacy microcontroller", "electronics", project_name
        )
        example = self.storage.add_training_example(
            old_id, "electronics", "What is Ohm's law in circuits?",
            "Voltage equals current multiplied by resistance.")
        self.assertTrue(self.auth.claim_legacy(self.uid, token))
        self.assertFalse(self.auth.claim_legacy(self.uid, token))
        self.assertEqual(self.storage.engineering_project(self.uid, project["id"])["repo_name"], project_name)
        self.assertIsNone(self.storage.engineering_project(old_id, project["id"]))
        self.assertEqual(self.storage.training_examples(self.uid)[0]["id"], example["id"])
        self.assertTrue(self.storage.begin_engineering_project_deletion(self.uid, project["id"]))
        self.assertTrue(self.storage.finish_engineering_project_deletion(self.uid, project["id"]))


if __name__ == "__main__":
    unittest.main()
