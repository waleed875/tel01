"""End-to-end smoke test of new, random-weight GPT training and held-out loss.

Uses a deliberately tiny network; it tests the pipeline, not model intelligence.
"""
import json
import math
from pathlib import Path
import tempfile
import unittest

import torch
from engine.train import train
from engine.eval_holdout import evaluate_heldout


class TrainSmokeTests(unittest.TestCase):
    def test_train_checkpoint_metrics_and_heldout_loss(self):
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            corpus = folder / "tiny.txt"
            corpus.write_text(
                ("سؤال: كيف نحسب الجهد؟\nجواب: V=IR، الفولت هو وحدة الجهد.\n" * 30),
                encoding="utf-8",
            )
            output = folder / "model"
            metrics = folder / "metrics.jsonl"
            train(corpus, output, steps=2, block_size=16,
                  batch_size=2, layers=1, heads=1, dim=16,
                  learning_rate=3e-4, seed=42, metrics_file=metrics)
            checkpoint = output / "checkpoint.pt"
            self.assertTrue(checkpoint.is_file())
            rows = [json.loads(row) for row in metrics.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["step"] for row in rows], [1, 2])
            self.assertTrue(math.isfinite(rows[-1]["validation_loss"]))
            heldout = [{
                "subject": "physics",
                "question": "ما الفرق بين السرعة والتسارع؟",
                "answer": "السرعة تغير الموضع مع الزمن والتسارع تغير السرعة."
            }]
            result = evaluate_heldout(checkpoint, heldout)
            self.assertTrue(math.isfinite(result))
            self.assertGreater(result, 0)


if __name__ == "__main__":
    unittest.main()
