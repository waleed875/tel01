"""Archive transitions and local backup verification tests."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from gitea_client import GiteaClient, GiteaError
from scripts.backup_local import FILES, sha256sum, verify_manifest
from webapp import app, db, session_user


class FakeProjects:
    def __init__(self):
        self.project = {"id": 11, "repo_name": "engineering-onlyowner",
                        "deletion_state": "active"}

    def engineering_project(self, owner, project):
        if owner != 18 or project != 11:
            return None
        return self.project

    def mark_project_archive_transition(self, owner, project, archive):
        item = self.engineering_project(owner, project)
        if item is None:
            return None
        allowed = ("active", "archiving") if archive else ("archived", "restoring")
        if item["deletion_state"] not in allowed:
            return None
        item["deletion_state"] = "archiving" if archive else "restoring"
        return item

    def finish_project_archive_transition(self, owner, project, archive):
        item = self.engineering_project(owner, project)
        if item is None or item["deletion_state"] != ("archiving" if archive else "restoring"):
            return None
        item["deletion_state"] = "archived" if archive else "active"
        return item


class ArchiveAPITests(unittest.TestCase):
    def setUp(self):
        self.db = FakeProjects()
        app.dependency_overrides[session_user] = lambda: 18
        app.dependency_overrides[db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_owner_scoped_recovery_and_no_writes_when_archived(self):
        with patch.object(GiteaClient, "set_archived", new_callable=AsyncMock) as remote:
            remote.side_effect = GiteaError(503, "network issue")
            self.assertEqual(self.client.post("/api/projects/11/archive").status_code, 503)
            self.assertEqual(self.db.project["deletion_state"], "archiving")
            remote.side_effect = None
            remote.return_value = {"archived": True}
            self.assertEqual(self.client.post("/api/projects/11/archive").status_code, 200)
            self.assertEqual(self.db.project["deletion_state"], "archived")
            with patch.object(GiteaClient, "write_file", new_callable=AsyncMock) as write:
                response = self.client.post("/api/projects/11/file", json={
                    "path": "main.py", "content_base64": "cHJpbnQoMSk=",
                    "message": "Update source",
                })
                self.assertEqual(response.status_code, 409)
                write.assert_not_awaited()
            app.dependency_overrides[session_user] = lambda: 99
            self.assertEqual(self.client.post("/api/projects/11/restore").status_code, 409)
            remote.assert_awaited()
            app.dependency_overrides[session_user] = lambda: 18
            remote.return_value = {"archived": False}
            self.assertEqual(self.client.post("/api/projects/11/restore").status_code, 200)
            self.assertEqual(self.db.project["deletion_state"], "active")


class BackupVerificationTests(unittest.TestCase):
    def test_manifest_rejects_missing_and_modified_files(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            for filename in FILES:
                (folder / filename).write_bytes(b"archive-validation" * 20)
            manifest = {
                "format": 1,
                "files": {
                    filename: {"size": (folder / filename).stat().st_size,
                               "sha256": sha256sum(folder / filename)}
                    for filename in FILES
                },
            }
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(verify_manifest(folder))
            (folder / "gitea_postgres.dump").write_bytes(b"tampered")
            with self.assertRaises(RuntimeError):
                verify_manifest(folder)


if __name__ == "__main__":
    unittest.main()
