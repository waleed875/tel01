"""Paired offline report scoring and checkpoint integrity checks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import torch

from benchmarks.compare_tokenizers import (paired_counts, checkpoint_metadata,
                                            evaluate, _by_domain)


def rows(a, b, domain="math"):
    return ([{"id": "x", "subject": domain, "passed": a}],
            [{"id": "x", "subject": domain, "passed": b}])


class PairedComparisonTests(unittest.TestCase):
    def test_four_paired_outcomes_and_order_integrity(self):
        for left, right, expected in ((True, True, "both_pass"),
                                      (True, False, "byte_only"),
                                      (False, True, "char_only"),
                                      (False, False, "both_fail")):
            a, b = rows(left, right)
            result = paired_counts(a, b)
            self.assertEqual(result[expected], 1)
            self.assertEqual(sum(result.values()), 1)
        a, b = rows(True, False)
        b[0]["id"] = "different"
        with self.assertRaisesRegex(ValueError, "ordering"):
            paired_counts(a, b)

    def test_per_domain_does_not_mix_subjects(self):
        a, b = rows(True, False, "software")
        report = _by_domain(a, b)
        self.assertEqual(report["software"]["byte_only"], 1)
        self.assertEqual(report["math"]["total"], 0)

    def test_checkpoint_kind_validation_and_metadata(self):
        from engine.tokenizer import tokenizer_spec, CharByteTokenizer
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = {"vocab_size": 256, "block_size": 64, "n_layer": 1,
                      "n_head": 1, "n_embd": 16, "dropout": 0.0, "bias": True}
            a, z = folder / "byte.pt", folder / "char.pt"
            torch.save({"config": config, "steps": 12, "dataset_sha256": "ab" * 32}, a)
            spec = tokenizer_spec(CharByteTokenizer("رياض"))
            torch.save({"config": {**config, "vocab_size": 260},
                        "tokenizer_spec": spec, "steps": 12,
                        "dataset_sha256": "ab" * 32}, z)
            self.assertEqual(checkpoint_metadata(a, "byte")["block_size"], 64)
            self.assertEqual(checkpoint_metadata(z, "char")["tokenizer_vocab_size"], 260)
            with self.assertRaisesRegex(ValueError, "Expected char"):
                checkpoint_metadata(a, "char")
            with self.assertRaisesRegex(ValueError, "Expected byte"):
                checkpoint_metadata(z, "byte")
            with self.assertRaisesRegex(ValueError, "distinct"):
                evaluate(a, a)
            with self.assertRaisesRegex(ValueError, "not found"):
                checkpoint_metadata(folder / "missing.pt", "byte")
            # Real model generation should not be required to inspect/check validity.
            with patch("benchmarks.compare_tokenizers._score_suite", side_effect=
                       lambda suite, checkpoint, seed, max_tokens, dt, tt: [
                           {"id": task["id"], "subject": task["subject"],
                            "passed": checkpoint == a, "input_tokens": 20,
                            "used_context_tokens": 20, "truncated_tokens": 0,
                            **({"false_proposal": False} if suite == "proposals" else {})}
                           for task in (dt if suite == "domains" else tt)
                       ]):
                report = evaluate(a, z)
            self.assertEqual(report["suites"]["domains"]["byte_passed"], 12)
            self.assertEqual(report["suites"]["domains"]["char_passed"], 0)
            self.assertEqual(report["suites"]["domains"]["paired"]["byte_only"], 12)
            self.assertEqual(len(report["checkpoints"]["byte"]["sha256"]), 64)
            self.assertEqual(set(report["benchmarks_sha256"]), {"domains", "proposals"})
            self.assertNotIn("unknown_training_data", report["confounds"])

    def test_no_checkpoint_or_invalid_seed_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, z = Path(tmp) / "none-a", Path(tmp) / "none-b"
            with self.assertRaisesRegex(ValueError, "Seed"):
                evaluate(a, z, seed=-2)
            with self.assertRaisesRegex(ValueError, "not found"):
                evaluate(a, z)


if __name__ == "__main__":
    unittest.main()
