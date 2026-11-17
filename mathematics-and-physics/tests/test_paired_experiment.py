"""Owner-export and isolated paired training regression checks."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from webapp import app, session_user, db
from engine.paired_experiment import load_export, prepare, run_pair


class PairedExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "approved-engineering.json"
        from foundation_dataset import load_starter
        self.rows = load_starter()
        self.source.write_text(json.dumps({"version": 1, "examples": self.rows},
                                          ensure_ascii=False), encoding="utf-8")

    def test_export_strict_data_contract_and_leakage_rejection(self):
        self.assertEqual(len(load_export(self.source)), 24)
        original = self.source.read_text(encoding="utf-8")
        altered = json.loads(original)
        altered["examples"][0]["user_id"] = 99
        self.source.write_text(json.dumps(altered, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            load_export(self.source)
        altered["examples"][0].pop("user_id")
        altered["examples"][0]["subject"] = "medicine"
        self.source.write_text(json.dumps(altered, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid approved"):
            load_export(self.source)
        self.source.write_text(original, encoding="utf-8")

    def test_prepare_splits_before_training_with_no_overwrite(self):
        dest = self.root / "experiment"
        with patch("engine.paired_experiment.inspect_preflight",
                   side_effect=lambda *a, **k: {"ready": True, "blockers": []}) as fake:
            result = prepare(self.source, dest, device="cpu", block_size=16)
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(result["training_examples"] + result["heldout_examples"], 24)
        self.assertEqual(set(result["by_domain"]), {"math","physics","electronics","software"})
        self.assertTrue((dest / "training.txt").is_file())
        self.assertTrue((dest / "heldout.json").is_file())
        heldout = json.loads((dest / "heldout.json").read_text(encoding="utf-8"))
        contents = (dest / "training.txt").read_text(encoding="utf-8")
        for row in heldout:
            self.assertNotIn("سؤال: " + row["question"] + "\nجواب:", contents)
        with self.assertRaises(FileExistsError):
            prepare(self.source, dest, device="cpu", block_size=16)

    def test_blocker_does_not_create_output(self):
        dest = self.root / "blocked"
        with patch("engine.paired_experiment.inspect_preflight",
                   side_effect=lambda *a, **k: {"ready": False, "blockers": ["No CUDA"]}):
            with self.assertRaisesRegex(ValueError, "No CUDA"):
                prepare(self.source, dest, device="cuda", block_size=16)
        self.assertFalse(dest.exists())

    def test_training_calls_exact_two_codecs_without_overwrite(self):
        dest = self.root / "experiment"
        with patch("engine.paired_experiment.inspect_preflight",
                   return_value={"ready": True, "blockers": []}):
            prepare(self.source, dest, device="cpu", block_size=16)
            with patch("engine.train.train") as train:
                def fake_trainer(data, output, **kwargs):
                    output.mkdir()
                    (output / "checkpoint.pt").write_bytes(b"placeholder")
                train.side_effect = fake_trainer
                info = run_pair(dest, steps=1)
                self.assertEqual([c.kwargs["tokenizer_mode"] for c in train.call_args_list],
                                 ["byte", "char"])
                self.assertEqual(len(info["checkpoints"]), 2)
            with self.assertRaisesRegex(ValueError, "already launched"):
                run_pair(dest, steps=1)

    def test_non_authenticated_export_cannot_return_any_data(self):
        client = TestClient(app)
        from webapp import auth_store
        with patch("webapp.auth_store") as mock_auth:
            mock_auth.verify_csrf.return_value = True
            mock_auth.session.return_value = None
            response = client.get("/api/datasets/approved/export")
        self.assertEqual(response.status_code, 401)

    def test_authenticated_export_owner_only(self):
        class FakeDB:
            def export_approved_training_examples(self, uid):
                self.assert_owner = uid
                return [{"subject": "math", "question": "احسب ناتج 2+3",
                         "answer": "النتيجة 5"}]
        fake = FakeDB()
        app.dependency_overrides[session_user] = lambda: 8765
        app.dependency_overrides[db] = lambda: fake
        try:
            result = TestClient(app).get("/api/datasets/approved/export")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(fake.assert_owner, 8765)
            self.assertEqual(set(result.json()), {"version", "examples"})
            self.assertEqual(set(result.json()["examples"][0]),
                             {"subject", "question", "answer"})
            self.assertIn("attachment", result.headers["content-disposition"])
        finally:
            app.dependency_overrides.pop(session_user, None)
            app.dependency_overrides.pop(db, None)


if __name__ == "__main__":
    unittest.main()
