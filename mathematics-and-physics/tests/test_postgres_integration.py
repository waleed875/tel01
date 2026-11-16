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


    def test_project_archive_state_transitions(self):
        import secrets
        name = "engineering-archive-" + secrets.token_hex(7)
        row = self.db.create_engineering_project(
            self.uid, "Archived physics circuit", "electronics", name)
        project_id = row["id"]
        try:
            self.assertIsNone(self.db.mark_project_archive_transition(self.uid + 1, project_id, True))
            transition = self.db.mark_project_archive_transition(self.uid, project_id, True)
            self.assertEqual(transition["deletion_state"], "archiving")
            self.assertEqual(
                self.db.finish_project_archive_transition(self.uid, project_id, True)["deletion_state"],
                "archived",
            )
            self.assertIsNotNone(self.db.engineering_project(self.uid, project_id)["archived_at"])
            self.assertIsNone(self.db.mark_project_archive_transition(self.uid, project_id, True))
            self.assertEqual(
                self.db.mark_project_archive_transition(self.uid, project_id, False)["deletion_state"],
                "restoring",
            )
            self.assertEqual(
                self.db.finish_project_archive_transition(self.uid, project_id, False)["deletion_state"],
                "active",
            )
            self.assertIsNone(self.db.engineering_project(self.uid, project_id)["archived_at"])
        finally:
            self.db.begin_engineering_project_deletion(self.uid, project_id)
            self.db.finish_engineering_project_deletion(self.uid, project_id)


    def test_training_artifact_cleanup_queue_and_database_removal(self):
        for n in range(12):
            item = self.db.add_training_example(
                self.uid, "math", f"Validated calculation number {n} in algebra",
                "Step-by-step solution with units and clearly verified algebra.")
            self.db.review_training_example(self.uid, item["id"], "approved")
        job = self.db.create_training_job(self.uid, steps=50, seed=42)
        with self.assertRaises(ValueError):
            self.db.queue_training_cleanup(self.uid)
        claimed = self.db.claim_training_job()
        self.assertEqual(claimed["id"], job["id"])
        with self.assertRaises(ValueError):
            self.db.queue_training_cleanup(self.uid)
        self.db.finish_training_job(job["id"], False, error="test-only stop")
        cleanup = self.db.queue_training_cleanup(self.uid)
        self.assertEqual(cleanup["state"], "queued")
        self.assertEqual(self.db.queue_training_cleanup(self.uid)["id"], cleanup["id"])
        with self.assertRaises(ValueError):
            self.db.create_training_job(self.uid, steps=50, seed=42)
        work = self.db.claim_training_cleanup()
        self.assertEqual(work["id"], cleanup["id"])
        self.assertEqual(work["job_ids"], [job["id"]])
        self.db.finish_training_cleanup(cleanup["id"])
        self.assertEqual(self.db.cleanup_status(self.uid)["state"], "completed")
        self.assertEqual(self.db.list_training_jobs(self.uid), [])
        self.assertEqual(self.db.training_examples(self.uid), [])


    def test_cleanup_removes_actual_run_directory_and_corresponding_rows(self):
        import tempfile
        from pathlib import Path
        from engine.worker import remove_owned_model_runs
        item = self.db.add_training_example(
            self.uid, "physics", "Newton's second law concept in mechanics?",
            "Force equals mass multiplied by acceleration.")
        for n in range(11):
            another = self.db.add_training_example(
                self.uid, "physics", f"Validated physics problem number {n}",
                "A complete solution with verified SI units and derivation.")
            self.db.review_training_example(self.uid, another["id"], "approved")
        self.db.review_training_example(self.uid, item["id"], "approved")
        job = self.db.create_training_job(self.uid, steps=50, seed=123)
        self.db.claim_training_job()
        self.db.finish_training_job(job["id"], True, "/app/models/run-test/checkpoint.pt")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / f"run-{job['id']}"
            run.mkdir()
            (run / "checkpoint.pt").write_bytes(b"private checkpoint")
            (run / "train.txt").write_text("private training source")
            cleanup = self.db.queue_training_cleanup(self.uid)
            claimed = self.db.claim_training_cleanup()
            self.assertEqual(claimed["id"], cleanup["id"])
            remove_owned_model_runs(claimed["job_ids"], root)
            self.assertFalse(run.exists())
            self.db.finish_training_cleanup(cleanup["id"])
            self.assertEqual(self.db.cleanup_status(self.uid)["state"], "completed")
            self.assertFalse(self.db.list_training_jobs(self.uid))
            self.assertFalse(self.db.training_examples(self.uid))


    def test_training_requires_approved_examples(self):
        for n in range(12):
            self.db.add_training_example(self.uid, "physics",
                f"ما شرح المفهوم الفيزيائي رقم {n} بالتفصيل؟",
                "الإجابة تتضمن المعطيات والقانون الفيزيائي المستخدم ووحداته.")
        with self.assertRaises(ValueError):
            self.db.create_training_job(self.uid, steps=50, seed=42)


if __name__ == '__main__':
    unittest.main()
