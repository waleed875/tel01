"""Regression checks for the standalone dashboard and read-only catalog endpoints."""
import json
import unittest
import tempfile
from unittest.mock import patch
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from webapp import app, session_user, db


BASE = Path(__file__).resolve().parents[1]


class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.append(attributes["id"])


class FakeStorage:
    def __init__(self):
        self.profile_value = {"subject": "math", "level": "intermediate",
                              "correct": 2, "attempted": 4, "last_question": None}
        self.examples = []
        self.counter = 0

    def profile(self, uid):
        return dict(self.profile_value)

    def set_level(self, uid, level):
        self.profile_value["level"] = level

    def set_subject(self, uid, subject):
        self.profile_value["subject"] = subject

    def clear_history(self, uid):
        return None

    def training_examples(self, uid, limit=100):
        return self.examples[:limit]

    def add_training_example(self, uid, subject, question, answer):
        self.counter += 1
        row = {"id": self.counter, "subject": subject, "question": question,
               "answer": answer, "status": "draft", "created_at": "2026-01-01T00:00:00Z"}
        self.examples.insert(0, row)
        return row

    def review_training_example(self, uid, example_id, action):
        for row in self.examples:
            if row["id"] == example_id:
                row["status"] = action
                row["reviewed_at"] = "2026-01-01T00:00:00Z" if action == "approved" else None
                return row
        return None

    def training_counts(self, uid):
        return {"draft": sum(e["status"] == "draft" for e in self.examples),
                "approved": sum(e["status"] == "approved" for e in self.examples)}

    def create_training_job(self, uid, steps, seed):
        if sum(row["status"] == "approved" for row in self.examples) < 12:
            raise ValueError("At least 12 approved examples are required")
        self.job = {
            "id": 1, "state": "queued", "steps": steps, "seed": seed,
            "training_count": 10, "validation_count": 2,
            "snapshot_sha256": "0123456789abcdef",
        }
        return self.job

    def list_training_jobs(self, uid):
        return [self.job] if hasattr(self, "job") else []

    def training_job(self, uid, job_id):
        return self.job if hasattr(self, "job") and job_id == self.job["id"] else None

    def completed_training_job_path(self, uid, job_id):
        job = self.training_job(uid, job_id)
        return job if job and job["state"] == "completed" else None

    def activate_training_job(self, uid, job_id):
        job = self.completed_training_job_path(uid, job_id)
        if job:
            self.active = job
        return job

    def active_training_job(self, uid):
        return getattr(self, "active", None)

    def training_job_metrics(self, uid, job_id):
        return [{"step": 1, "train_loss": 3.2, "validation_loss": 3.3}]

    def delete_training_example(self, uid, example_id):
        original_len = len(self.examples)
        self.examples = [e for e in self.examples if e["id"] != example_id]
        return len(self.examples) != original_len


class DashboardTests(unittest.TestCase):
    def test_html_identifiers_unique(self):
        parser = IdParser()
        parser.feed((BASE / "static" / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertIn("dataset-form", parser.ids)
        self.assertIn("chat-form", parser.ids)
        self.assertIn("subject-picker", parser.ids)

    def test_static_files_have_no_remote_url(self):
        css = (BASE / "static" / "style.css").read_text(encoding="utf-8")
        js = (BASE / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("https://", css + js)
        self.assertNotIn("eval(", js)

    def test_catalog_routes(self):
        client = TestClient(app)
        response = client.get("/api/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()["curriculum"]),
                         {"math", "physics", "electronics", "software"})
        self.assertEqual(client.get("/static/app.js").status_code, 200)

    def test_training_jobs_require_reviewed_examples(self):
        fake = FakeStorage()
        app.dependency_overrides[session_user] = lambda: -44
        app.dependency_overrides[db] = lambda: fake
        try:
            client = TestClient(app)
            start = client.post("/api/training/jobs", json={"steps": 50, "seed": 42})
            self.assertEqual(start.status_code, 422)
            for i in range(12):
                fake.add_training_example(-44, "math",
                    f"سؤال رياضيات معتمد {i}", f"إجابة شرح علمي متحقق من الحسابات {i}")
                fake.review_training_example(-44, i+1, "approved")
            self.assertEqual(client.post("/api/training/jobs",
                            json={"steps": 0, "seed": 42}).status_code, 422)
            response = client.post("/api/training/jobs", json={"steps": 50, "seed": 42})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()["id"], 1)
            self.assertEqual(len(client.get("/api/training/jobs").json()["jobs"]), 1)
            detail = client.get("/api/training/jobs/1")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["metrics"][0]["step"], 1)
            self.assertEqual(client.get("/api/training/jobs/2222").status_code, 404)
        finally:
            app.dependency_overrides.clear()

    def test_only_completed_owned_checkpoint_can_be_activated(self):
        fake = FakeStorage()
        fake.job = {"id": 7, "state": "queued", "steps": 50, "seed": 42,
                    "checkpoint_path": None, "heldout_loss": None,
                    "training_count": 12, "validation_count": 2,
                    "snapshot_sha256": "ab" * 32}
        app.dependency_overrides[session_user] = lambda: -44
        app.dependency_overrides[db] = lambda: fake
        try:
            with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"MODEL_ROOT": temp}):
                client = TestClient(app)
                self.assertEqual(
                    client.post("/api/training/jobs/7/activate").status_code, 409
                )
                folder = Path(temp) / "run-7"
                folder.mkdir()
                checkpoint = folder / "checkpoint.pt"
                checkpoint.write_bytes(b"test-checkpoint-file")
                fake.job["state"] = "completed"
                fake.job["checkpoint_path"] = str(checkpoint)
                fake.job["heldout_loss"] = 4.1
                response = client.post("/api/training/jobs/7/activate")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["active_job_id"], 7)
                state = client.get("/api/model/status")
                self.assertEqual(state.status_code, 200)
                self.assertEqual(state.json()["active_job_id"], 7)
                self.assertTrue(state.json()["checkpoint_available"])
        finally:
            app.dependency_overrides.clear()

    def test_training_drafts_are_not_automatic_training(self):
        fake = FakeStorage()
        app.dependency_overrides[session_user] = lambda: -44
        app.dependency_overrides[db] = lambda: fake
        try:
            client = TestClient(app)
            saved = client.post("/api/datasets", json={
                "subject": "electronics",
                "question": "كيف نحسب قيمة التيار في مقاومة 100 أوم؟",
                "answer": "نطبق قانون أوم I=V/R بعد تحديد الجهد والفولتية والمقاومة."
            })
            self.assertEqual(saved.status_code, 201, saved.text)
            examples = client.get("/api/datasets").json()
            self.assertEqual(len(examples["examples"]), 1)
            self.assertEqual(examples["examples"][0]["status"], "draft")
            example_id = saved.json()["id"]
            self.assertEqual(client.get("/api/datasets/stats").json()["approved"], 0)
            reviewed = client.patch(f"/api/datasets/{example_id}/review", json={"approved": True})
            self.assertEqual(reviewed.status_code, 200)
            self.assertEqual(reviewed.json()["status"], "approved")
            self.assertEqual(client.get("/api/datasets/stats").json()["approved"], 1)
            self.assertEqual(client.patch(f"/api/datasets/{example_id}/review",
                                         json={"approved": False}).json()["status"], "draft")
            self.assertEqual(client.patch("/api/datasets/9999/review",
                                         json={"approved": True}).status_code, 404)
            self.assertEqual(client.delete(f"/api/datasets/{example_id}").status_code, 200)
            self.assertEqual(client.get("/api/datasets").json()["examples"], [])
            self.assertEqual(client.post("/api/datasets", json={
                "subject": "fake", "question": "some question 123",
                "answer": "some answer 123"
            }).status_code, 422)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
