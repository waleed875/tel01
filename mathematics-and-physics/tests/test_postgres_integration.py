"""Run with DATABASE_URL pointing at a disposable PostgreSQL test database."""
import os
import unittest
from storage import Storage

@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL for integration tests")
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Storage(os.environ["TEST_DATABASE_URL"])

    def setUp(self):
        self.uid = -92000000000001
        self.db.delete_user(self.uid)

    def tearDown(self):
        self.db.delete_user(self.uid)

    def test_profile_grade_quota_history_delete(self):
        self.assertEqual(self.db.profile(self.uid)["subject"], "math")
        self.db.set_level(self.uid, "university")
        self.db.set_subject(self.uid, "software")
        self.assertEqual(self.db.profile(self.uid)["level"], "university")
        self.db.set_active_quiz(self.uid, "m_b_1")
        self.assertTrue(self.db.grade_quiz(self.uid, "m_b_1", True))
        self.assertFalse(self.db.grade_quiz(self.uid, "m_b_1", True))
        self.assertEqual(self.db.profile(self.uid)["correct"], 1)
        self.assertTrue(self.db.claim_quota(self.uid, 1))
        self.assertFalse(self.db.claim_quota(self.uid, 1))
        self.db.release_quota(self.uid)
        self.assertTrue(self.db.claim_quota(self.uid, 1))
        self.db.add_exchange(self.uid, "مرحبا", "أهلا")
        self.assertEqual(len(self.db.recent_history(self.uid)), 2)
        self.db.clear_history(self.uid)
        self.assertEqual(self.db.recent_history(self.uid), [])

if __name__ == '__main__':
    unittest.main()
