"""Resumable offline model training: optimizer, hashes, bounds, device selection."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from engine.train import train, choose_device


class ResumeTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "training.txt"
        self.dataset.write_text(("سؤال: ما هو قانون أوم؟\nجواب: فرق الجهد يساوي التيار مضروبًا بالمقاومة.\n" * 15), encoding="utf-8")
        self.output = self.root / "checkpoint"
        self.metrics = self.root / "metrics.jsonl"

    def run_small(self, steps=2, resume=None):
        return train(self.dataset, self.output, steps=steps, block_size=16,
                     batch_size=2, layers=1, heads=1, dim=16, learning_rate=3e-4,
                     seed=42, metrics_file=self.metrics, resume=resume, device="cpu")

    def test_checkpoint_can_resume_with_optimizer_and_metrics(self):
        self.run_small()
        path = self.output / "checkpoint.pt"
        initial = torch.load(path, map_location="cpu", weights_only=True)
        self.assertEqual(initial["steps"], 2)
        self.assertIn("optimizer", initial)
        self.assertEqual(len(initial["dataset_sha256"]), 64)
        self.run_small(steps=3, resume=path)
        end = torch.load(path, map_location="cpu", weights_only=True)
        self.assertEqual(end["steps"], 5)
        self.assertEqual(initial["dataset_sha256"], end["dataset_sha256"])
        self.assertFalse(torch.equal(initial["model"]["transformer.wte.weight"],
                                     end["model"]["transformer.wte.weight"]))
        steps = [json.loads(x)["step"] for x in self.metrics.read_text().splitlines()]
        self.assertEqual(steps, [1, 2, 3, 5])

    def test_reject_modified_data_and_incompatible_architecture(self):
        self.run_small()
        path = self.output / "checkpoint.pt"
        initial = path.read_bytes()
        self.dataset.write_text(self.dataset.read_text() + "different", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dataset SHA-256"):
            self.run_small(resume=path)
        self.assertEqual(path.read_bytes(), initial)
        self.dataset.write_text(self.dataset.read_text()[:-len("different")], encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "architecture"):
            train(self.dataset, self.output, steps=1, block_size=16, batch_size=2,
                  layers=1, heads=1, dim=32, learning_rate=3e-4, seed=42,
                  resume=path, device="cpu")

    def test_refuse_legacy_checkpoint_without_optimizer(self):
        self.run_small()
        path = self.output / "checkpoint.pt"
        state = torch.load(path, map_location="cpu", weights_only=True)
        state.pop("optimizer")
        torch.save(state, path)
        with self.assertRaisesRegex(ValueError, "Legacy checkpoint"):
            self.run_small(resume=path)

    def test_explicit_cuda_fails_closed_and_cpu_allowed(self):
        with patch("engine.train.torch.cuda.is_available", return_value=False):
            self.assertEqual(choose_device("cpu"), "cpu")
            self.assertEqual(choose_device("auto"), "cpu")
            with self.assertRaisesRegex(RuntimeError, "CUDA requested"):
                choose_device("cuda")
        with self.assertRaises(ValueError):
            choose_device("tpu")

    def test_checkpoint_still_supports_old_inference_and_heldout(self):
        self.run_small()
        from engine.eval_holdout import evaluate_heldout
        val = evaluate_heldout(self.output / "checkpoint.pt",
                              [{"subject": "math", "question": "ما قيمة 2+2؟",
                                "answer": "القيمة تساوي أربعة."}])
        self.assertTrue(math.isfinite(val))


if __name__ == "__main__":
    unittest.main()
