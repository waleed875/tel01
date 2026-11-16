"""Offline backup manifest / archive safety tests (no Docker required)."""
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.backup_local import FILES, LEGACY_FILES, sha256sum, verify_manifest, check_preconditions
from scripts.rehearse_restore import safe_archive, rehearse


def create_archive(path: Path, *, member: str = "run-1/checkpoint.pt"):
    with tarfile.open(path, "w:gz") as archive:
        data = b"private test checkpoint"
        meta = tarfile.TarInfo(member)
        meta.size = len(data)
        archive.addfile(meta, io.BytesIO(data))


class BackupManifestTests(unittest.TestCase):
    def make_manifest(self, folder, version):
        expected = LEGACY_FILES if version == 1 else FILES
        for name in expected:
            path = folder / name
            if name.endswith(".tar.gz"):
                create_archive(path)
            else:
                path.write_bytes(b"mock-pg-dump" * 20)
        manifest = {"format": version, "files": {
            name: {"size": (folder / name).stat().st_size,
                   "sha256": sha256sum(folder / name)}
            for name in expected
        }}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_model_inclusive_manifest_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.make_manifest(folder, 2)
            self.assertEqual(verify_manifest(folder)["format"], 2)
            (folder / "trained_models.tar.gz").write_bytes(b"tampered")
            with self.assertRaises(RuntimeError):
                verify_manifest(folder)

    def test_legacy_backup_detected_but_not_rehearsed_as_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.make_manifest(folder, 1)
            self.assertEqual(verify_manifest(folder)["format"], 1)
            with self.assertRaises(RuntimeError):
                rehearse(folder)

    def test_unsafe_tar_member_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "unsafe.tar.gz"
            create_archive(file, member="../../escape")
            with self.assertRaises(ValueError):
                safe_archive(file)
            create_archive(file, member="valid/data.txt")
            self.assertEqual(safe_archive(file), 1)

    def test_preflight_refuses_active_manual_training(self):
        class Result:
            stdout = "postgres\ngitea-db\ntrainer\n"
        with patch("scripts.backup_local.Path.is_file", return_value=True), \
             patch("scripts.backup_local.compose", return_value=Result()):
            with self.assertRaisesRegex(RuntimeError, "trainer"):
                check_preconditions()


if __name__ == "__main__":
    unittest.main()
