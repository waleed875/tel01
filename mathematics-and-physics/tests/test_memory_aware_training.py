"""CPU deterministic checks for accumulation and precision handling."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import torch
from engine.train import train, select_precision


class MemoryAwareTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "corpus.txt"
        self.data.write_text(("سؤال: كيف نحسب التيار؟\nجواب: I = V / R.\n" * 30), encoding="utf-8")
        self.output = self.root / "model"

    def small(self, *, accum=1, resume=None, precision="fp32"):
        train(self.data, self.output, steps=2, block_size=16, batch_size=2,
              layers=1, heads=1, dim=16, learning_rate=3e-4, seed=42,
              device="cpu", grad_accum_steps=accum, resume=resume, precision=precision)

    def test_accumulation_writes_compatible_checkpoint_and_resumes(self):
        self.small(accum=3)
        path = self.output / "checkpoint.pt"
        first = torch.load(path, map_location="cpu", weights_only=True)
        self.assertEqual(first["grad_accum_steps"], 3)
        self.assertEqual(first["precision"], "fp32")
        self.assertEqual(first["steps"], 2)
        self.assertTrue(torch.isfinite(first["model"]["transformer.wte.weight"]).all())
        self.small(accum=3, resume=path)
        second = torch.load(path, map_location="cpu", weights_only=True)
        self.assertEqual(second["steps"], 4)

    def test_accumulation_change_refused_without_modifying_checkpoint(self):
        self.small(accum=2)
        path = self.output / "checkpoint.pt"
        baseline = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "training settings"):
            self.small(accum=3, resume=path)
        self.assertEqual(path.read_bytes(), baseline)

    def test_default_is_compatible_with_previous_checkpoint_format(self):
        self.small()
        path = self.output / "checkpoint.pt"
        data = torch.load(path, map_location="cpu", weights_only=True)
        data.pop("grad_accum_steps")
        data.pop("precision")
        torch.save(data, path)
        self.small(resume=path)
        self.assertEqual(torch.load(path, map_location="cpu", weights_only=True)["steps"], 4)

    def test_precision_fail_closed_and_accumulation_bounds(self):
        with patch("engine.train.torch.cuda.is_available", return_value=False):
            self.assertEqual(select_precision("auto", "cpu"), "fp32")
            self.assertEqual(select_precision("fp32", "cpu"), "fp32")
            with self.assertRaisesRegex(RuntimeError, "BF16 requested"):
                select_precision("bf16", "cpu")
        for n in (0, 65, True):
            with self.assertRaisesRegex(ValueError, "accumulation"):
                train(self.data, self.output, steps=1, block_size=16, batch_size=2,
                      layers=1, heads=1, dim=16, learning_rate=3e-4, seed=42,
                      device="cpu", grad_accum_steps=n)


if __name__ == "__main__":
    unittest.main()
