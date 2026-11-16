"""Local workspace tests. Never contact a real Gitea instance in unit tests."""
import base64
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from gitea_client import GiteaClient, GiteaError, validate_path
from webapp import app, db, session_user


class FakeStorage:
    projects = ()
    def __init__(self):
        self.projects = []
        self.counter = 0

    def create_engineering_project(self, user_id, title, kind, repo_name):
        self.counter += 1
        project = {"id": self.counter, "title": title, "kind": kind,
                   "repo_name": repo_name, "user_id": user_id,
                   "created_at": "2026-01-01T00:00:00Z"}
        self.projects.append(project)
        return project

    def list_engineering_projects(self, user_id):
        return [{key: val for key, val in p.items() if key not in ("user_id", "repo_name")}
                for p in self.projects if p["user_id"] == user_id]

    def engineering_project(self, user_id, project_id):
        return next((p for p in self.projects if p["user_id"] == user_id and p["id"] == project_id), None)


class GiteaValidationTests(unittest.TestCase):
    def test_rejects_traversal_absolute_and_git_paths(self):
        for item in ("../etc/passwd", "src/../secret", "/etc/shadow",
                     "src//file.py", "src\\evil.py", ".git/config"):
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    validate_path(item)
        self.assertEqual(validate_path("src/logic/main.py"), "src/logic/main.py")
        self.assertEqual(validate_path(".gitignore"), ".gitignore")
        self.assertEqual(validate_path("", allow_root=True), "")

    def test_gitea_host_restriction(self):
        for url in ("https://example.com", "http://127.0.0.1:3000",
                    "http://evil.example:3000", "http://gitea:3001",
                    "http://gitea:3000/other"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    GiteaClient(base_url=url, token="x", owner="dev")
        self.assertTrue(GiteaClient(base_url="http://gitea:3000", token="token",
                                    owner="engineer").configured())

    def test_sha_required_for_update_or_delete(self):
        gitea = GiteaClient(token="some-token", owner="engineer")
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(gitea.write_file("lab-demo", "main.py", b"Hi", sha="bad", message="Update test"))
        with self.assertRaises(ValueError):
            asyncio.run(gitea.delete_file("lab-demo", "main.py", "bad", "Delete file"))


class ProjectAPIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.storage = FakeStorage()
        app.dependency_overrides[session_user] = lambda: 22
        app.dependency_overrides[db] = lambda: self.storage
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_private_repo_creation_and_owner_isolation(self):
        with patch.object(GiteaClient, "create_repo", new_callable=AsyncMock) as create:
            create.return_value = {"name": "private"}
            response = self.client.post("/api/projects", json={
                "title": "مشروع محرك روبوت", "kind": "electronics"})
            self.assertEqual(response.status_code, 201, response.text)
            kwargs = create.await_args.args
            self.assertTrue(kwargs[0].startswith("engineering-"))
            self.assertEqual(kwargs[1], "مشروع محرك روبوت")
        project_id = response.json()["id"]
        self.assertEqual(len(self.client.get("/api/projects").json()["projects"]), 1)
        app.dependency_overrides[session_user] = lambda: 50
        denied = self.client.get(f"/api/projects/{project_id}/files")
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.client.get("/api/projects").json()["projects"], [])

    def test_edit_binary_download_conflict_and_delete(self):
        self.storage.create_engineering_project(22, "Code", "software", "engineering-abcd1234")
        item = {"path": "src/main.py", "sha": "a" * 40,
                "size": 5, "data": b"hello"}
        with patch.object(GiteaClient, "read_file", new_callable=AsyncMock) as read, \
             patch.object(GiteaClient, "write_file", new_callable=AsyncMock) as write, \
             patch.object(GiteaClient, "delete_file", new_callable=AsyncMock) as delete:
            read.return_value = item
            write.return_value = {"commit": {"sha": "c" * 40}, "content": {"sha": "b" * 40}}
            delete.return_value = {"commit": {"sha": "d" * 40}}
            file = self.client.get("/api/projects/1/file?path=src/main.py")
            self.assertEqual(file.status_code, 200)
            self.assertEqual(file.json()["content"], "hello")
            download = self.client.get("/api/projects/1/download?path=src/main.py")
            self.assertEqual(download.content, b"hello")
            upload = self.client.post("/api/projects/1/file", json={
                "path": "src/main.py", "content_base64": base64.b64encode(b"new").decode(),
                "sha": "a" * 40, "message": "Update source"
            })
            self.assertEqual(upload.status_code, 200, upload.text)
            self.assertEqual(write.await_args.kwargs["sha"], "a" * 40)
            gone = self.client.request("DELETE", "/api/projects/1/file", json={
                "path": "src/main.py", "sha": "b" * 40, "message": "Delete source"
            })
            self.assertEqual(gone.status_code, 200)
            self.assertTrue(delete.await_count)
            rejected = self.client.post("/api/projects/1/file", json={
                "path": "../secret", "content_base64": "eA==",
                "message": "Unsafe upload"
            })
            self.assertEqual(rejected.status_code, 422)
            missing = self.client.get("/api/projects/100/file?path=src/main.py")
            self.assertEqual(missing.status_code, 404)

    def test_binary_files_not_treated_as_editable_text(self):
        self.storage.create_engineering_project(22, "PCB", "electronics", "engineering-xyz")
        with patch.object(GiteaClient, "read_file", new_callable=AsyncMock) as read:
            read.return_value = {"path": "pcb.bin", "sha": "a" * 40,
                                 "size": 3, "data": b"\xff\xfe\x00"}
            self.assertEqual(self.client.get("/api/projects/1/file?path=pcb.bin").status_code, 415)
            self.assertEqual(self.client.get("/api/projects/1/download?path=pcb.bin").content,
                             b"\xff\xfe\x00")


if __name__ == "__main__":
    unittest.main()
