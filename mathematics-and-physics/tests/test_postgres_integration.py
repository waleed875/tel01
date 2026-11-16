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
    def test_training_review_queue_metrics(self):
        for n in range(12):
            item = self.db.add_training_example(self.uid, "math",
                f"ما هو المثال العلمي المعتمد رقم {n} في الرياضيات؟",
                f"الحل العلمي رقم {n} يعتمد على الحساب والتحقق من الوحدات في المعادلات.")
            self.assertEqual(item["status"], "draft")
            self.assertIsNotNone(self.db.review_training_example(self.uid, item["id"], "approved"))
        self.assertEqual(self.db.training_counts(self.uid)["approved"], 12)
        job = self.db.create_training_job(self.uid, steps=50, seed=42)
        self.assertEqual(job["state"], "queued")
        with self.assertRaises(ValueError):
            self.db.create_training_job(self.uid, steps=50, seed=42)
        self.assertEqual(self.db.list_training_jobs(self.uid)[0]["id"], job["id"])
        claimed = self.db.claim_training_job()
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["training_count"] + claimed["validation_count"], 12)
        self.db.record_training_metric(job["id"], 1, 3.1, 3.2)
        detail = self.db.training_job_metrics(self.uid, job["id"])
        self.assertEqual(detail[0]["step"], 1)
        self.db.finish_training_job(job["id"], True, "/app/models/run-test/checkpoint.pt")
        self.assertEqual(self.db.training_job(self.uid, job["id"])["state"], "completed")

    def test_engineering_project_ownership(self):
        project = self.db.create_engineering_project(
            self.uid, "Math robot control", "electronics",
            "engineering-test-" + str(abs(self.uid))
        )
        self.assertEqual(project["title"], "Math robot control")
        self.assertEqual(self.db.engineering_project(self.uid, project["id"])["kind"], "electronics")
        self.assertIsNone(self.db.engineering_project(self.uid + 1, project["id"]))
        own = self.db.list_engineering_projects(self.uid)
        self.assertTrue(any(p["id"] == project["id"] for p in own))
        self.assertFalse(any(p["id"] == project["id"]
                             for p in self.db.list_engineering_projects(self.uid + 1)))
        with self.assertRaises(ValueError):
            self.db.delete_user(self.uid)
        self.assertEqual(
            self.db.begin_engineering_project_deletion(self.uid, project["id"])["deletion_state"],
            "deleting",
        )
        self.assertFalse(self.db.finish_engineering_project_deletion(self.uid + 1, project["id"]))
        self.assertTrue(self.db.finish_engineering_project_deletion(self.uid, project["id"]))
        self.assertEqual(self.db.list_engineering_projects(self.uid), [])


    def test_training_requires_approved_examples(self):
        for n in range(12):
            self.db.add_training_example(self.uid, "physics",
                f"ما شرح المفهوم الفيزيائي رقم {n} بالتفصيل؟",
                "الإجابة تتضمن المعطيات والقانون الفيزيائي المستخدم ووحداته.")
        with self.assertRaises(ValueError):
            self.db.create_training_job(self.uid, steps=50, seed=42)


if __name__ == '__main__':
    unittest.main()
