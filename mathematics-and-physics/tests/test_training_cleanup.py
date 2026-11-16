"""Training artifacts: only numeric owned worker folders can be removed."""
from pathlib import Path
import tempfile
import unittest

from engine.worker import remove_owned_model_runs


class CleanupPathTests(unittest.TestCase):
    def test_removes_only_requested_run_folders(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            wanted = root / "run-21"
            wanted.mkdir()
            (wanted / "checkpoint.pt").write_bytes(b"not-real-weights")
            other = root / "run-22"
            other.mkdir()
            (other / "train.txt").write_text("private training data")
            remove_owned_model_runs([21], root)
            self.assertFalse(wanted.exists())
            self.assertTrue(other.exists())
            # Safe retry: already-deleted run is a no-op.
            remove_owned_model_runs([21], root)
            self.assertTrue(other.exists())

    def test_rejects_non_integer_and_symlink_paths(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            out = root / "outside"
            out.mkdir()
            (out / "important.txt").write_text("do not delete")
            target = root / "run-13"
            try:
                target.symlink_to(out, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation unavailable")
            with self.assertRaises(ValueError):
                remove_owned_model_runs([13], root)
            self.assertTrue((out / "important.txt").exists())
            for unsafe in ("../../", -1, True, None, 0, 2**65):
                with self.subTest(value=str(unsafe)):
                    with self.assertRaises(ValueError):
                        remove_owned_model_runs([unsafe], root)


if __name__ == "__main__":
    unittest.main()
