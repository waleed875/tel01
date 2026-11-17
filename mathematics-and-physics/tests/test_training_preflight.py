"""Training preflight is read-only and flags missing resources before training."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engine.preflight import inspect


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "corpus.txt"
        self.path.write_text(("رياضيات: مشتقة س² = 2س. Python: def f(x): return x*x\n" * 60),
                             encoding="utf-8")

    def test_byte_and_char_training_split_match_trainer(self):
        with patch("engine.preflight.torch.cuda.is_available", return_value=False):
            byte = inspect(self.path, device="cpu", block_size=16)
            char = inspect(self.path, device="cpu", tokenizer="char", block_size=16)
        self.assertTrue(byte["ready"], byte)
        self.assertTrue(char["ready"], char)
        self.assertLess(char["data"]["total_tokens"], byte["data"]["total_tokens"])
        self.assertEqual(byte["data"]["total_tokens"], len(self.path.read_bytes()))
        self.assertEqual(char["data"]["vocab_size"] > 256, True)
        self.assertEqual(len(byte["data"]["sha256"]), 64)
        self.assertEqual(byte["runtime"]["selected_device"], "cpu")
        self.assertEqual(byte["training"]["effective_batch_size"], 8)

    def test_cuda_missing_is_blocker_not_silent_fallback(self):
        with patch("engine.preflight.torch.cuda.is_available", return_value=False):
            report = inspect(self.path, device="cuda", block_size=16)
            self.assertFalse(report["ready"])
            self.assertEqual(report["runtime"]["selected_device"], "unavailable")
            self.assertTrue(any("CUDA requested" in s for s in report["blockers"]))
            unsupported = inspect(self.path, device="cpu", precision="bf16", block_size=16)
            self.assertFalse(unsupported["ready"])
            self.assertTrue(any("BF16" in s for s in unsupported["blockers"]))

    def test_simulated_cuda_reports_card_no_training(self):
        props = SimpleNamespace(name="Fake 4050", total_memory=6 * 1024 ** 3)
        with patch("engine.preflight.torch.cuda.is_available", return_value=True), \
             patch("engine.preflight.torch.cuda.get_device_properties", return_value=props), \
             patch("engine.preflight.torch.cuda.is_bf16_supported", return_value=True):
            report = inspect(self.path, device="cuda", precision="auto",
                             batch_size=2, grad_accum_steps=8, block_size=16)
        self.assertTrue(report["ready"])
        self.assertEqual(report["runtime"]["gpu"]["name"], "Fake 4050")
        self.assertEqual(report["runtime"]["selected_precision"], "bf16")
        self.assertEqual(report["training"]["effective_batch_size"], 16)
        self.assertGreater(report["memory_estimate"]["approx_trainable_parameters"], 0)

    def test_oversized_context_and_missing_corrupt_data(self):
        with patch("engine.preflight.torch.cuda.is_available", return_value=False):
            failure = inspect(self.path, device="cpu", block_size=2048)
        self.assertFalse(failure["ready"])
        self.assertTrue(failure["blockers"])
        with self.assertRaisesRegex(ValueError, "not found"):
            inspect(self.path.parent / "absent.txt")
        self.path.write_bytes(b"invalid utf8 \xff")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            inspect(self.path)

    def test_invalid_configuration_rejected(self):
        for bad in ({"heads": 3, "dim": 128}, {"grad_accum_steps": 0},
                    {"batch_size": 0}, {"tokenizer": "unknown"},
                    {"max_char_tokens": 0}, {"block_size": 16385}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inspect(self.path, **bad)


if __name__ == "__main__":
    unittest.main()
