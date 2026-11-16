"""Regression checks for the standalone dashboard and read-only catalog endpoints."""
import json
import unittest
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
