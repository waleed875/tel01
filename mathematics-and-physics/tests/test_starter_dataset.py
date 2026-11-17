"""Starter pack integrity and transactional draft-only import regression tests."""
import copy
import os
import unittest
from collections import Counter

from foundation_dataset import load_starter, validate_starter
from engineering_domains import DOMAINS
from benchmarks.evaluate_domains import load_benchmark, verify_no_train_leakage
from benchmarks.evaluate_tool_proposals import load_suite


class StarterPackUnitTests(unittest.TestCase):
    def setUp(self):
        import json
        from foundation_dataset import PACK
        self.package = json.loads(PACK.read_text(encoding="utf-8"))

    def test_pack_is_balanced_and_free_of_public_benchmark_questions(self):
        examples = load_starter()
        self.assertEqual(len(examples), 24)
        self.assertEqual(Counter(row["subject"] for row in examples),
                         {domain: 6 for domain in DOMAINS})
        verify_no_train_leakage(load_benchmark()["tasks"], examples)
        verify_no_train_leakage(load_suite()["tasks"], examples)

    def test_rejects_duplicates_out_of_scope_and_bad_questions(self):
        for edit in ("duplicate", "domain", "short", "missing", "benchmark"):
            pack = copy.deepcopy(self.package)
            if edit == "duplicate":
                pack["examples"][1]["question"] = "   " + pack["examples"][0]["question"] + "  "
            elif edit == "domain":
                pack["examples"][0]["subject"] = "medicine"
            elif edit == "short":
                pack["examples"][0]["answer"] = ""
            elif edit == "missing":
                del pack["examples"][0]["skill"]
            else:
                task = next(t for t in load_benchmark()["tasks"] if t["subject"] == "math")
                pack["examples"][0]["question"] = task["question"]
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate_starter(pack)

    def test_endpoint_requires_authentication_and_import_never_approves(self):
        from fastapi.testclient import TestClient
        from webapp import app
        client = TestClient(app)
        response = client.post("/api/datasets/starter/import")
        self.assertIn(response.status_code, (401, 403))
        # No training job is queued by the pack parser.
        self.assertEqual(set(load_starter()[0]), {"subject", "question", "answer"})


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class StarterPackDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from storage import Storage
        cls.db = Storage(os.environ["TEST_DATABASE_URL"])

    def setUp(self):
        import secrets
        self.owner = -int.from_bytes(secrets.token_bytes(6), "big") - 300000
        self.other = self.owner - 1

    def tearDown(self):
        self.db.delete_user(self.owner)
        self.db.delete_user(self.other)

    def test_import_is_owner_scoped_draft_only_idempotent_and_preserves_reviews(self):
        examples = load_starter()
        first = self.db.import_starter_drafts(self.owner, examples)
        self.assertEqual(first, {"inserted": 24, "skipped": 0, "total": 24, "status": "draft"})
        rows = self.db.training_examples(self.owner, 100)
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(row["status"] == "draft" for row in rows))
        chosen = rows[0]
        self.db.review_training_example(self.owner, chosen["id"], "approved")
        second = self.db.import_starter_drafts(self.owner, examples)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["skipped"], 24)
        self.assertEqual(self.db.training_counts(self.owner), {"draft": 23, "approved": 1})
        self.assertEqual(self.db.training_examples(self.other), [])
        other = self.db.import_starter_drafts(self.other, examples)
        self.assertEqual(other["inserted"], 24)
        self.assertEqual(self.db.training_counts(self.other)["approved"], 0)

    def test_import_does_not_commit_partial_invalid_pack(self):
        examples = [dict(row) for row in load_starter()]
        examples[-1]["answer"] = "x" * 5001
        with self.assertRaises(ValueError):
            self.db.import_starter_drafts(self.owner, examples)
        self.assertEqual(self.db.training_examples(self.owner), [])
        self.assertEqual(self.db.training_counts(self.owner)["approved"], 0)


if __name__ == "__main__":
    unittest.main()
