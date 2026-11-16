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


    def begin_engineering_project_deletion(self, user_id, project_id):
        project = self.engineering_project(user_id, project_id)
        if project:
            project["deletion_state"] = "deleting"
        return project

    def finish_engineering_project_deletion(self, user_id, project_id):
        project = self.engineering_project(user_id, project_id)
        if project and project.get("deletion_state") == "deleting":
            self.projects.remove(project)
            return True
        return False

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


class GiteaFileSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_recursive_search_with_pagination(self):
        api_client = GiteaClient(token="test-token", owner="engineering")
        pages = [
            {"tree": [
                {"path": "src/Main.py", "type": "blob", "sha": "a" * 40, "size": 4},
                {"path": "docs", "type": "tree", "sha": "b" * 40},
                {"path": "archive/main.py", "type": "blob", "sha": "c" * 40, "size": 5},
            ], "truncated": True},
            {"tree": [
                {"path": "lib/MAIN_TEST.py", "type": "blob", "sha": "d" * 40, "size": 6}
            ], "truncated": False},
        ]
        with patch.object(api_client, "_call", new_callable=AsyncMock) as call:
            call.side_effect = pages
            result = await api_client.search_paths("project", "main")
        self.assertEqual(len(result["matches"]), 3)
        self.assertEqual(result["scanned"], 3)
        self.assertTrue(result["complete"])
        self.assertEqual(call.await_count, 2)

    async def test_reports_truncated_results(self):
        client = GiteaClient(token="token", owner="owner")
        with patch.object(client, "_call", new_callable=AsyncMock) as call:
            call.return_value = {
                "tree": [{"path": "src/power.py", "type": "blob", "sha": "a" * 40}],
                "truncated": True,
            }
            result = await client.search_paths("project", "power", max_pages=2)
        self.assertFalse(result["complete"])
        self.assertEqual(call.await_count, 2)


class ProjectAPIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.storage = FakeStorage()
        app.dependency_overrides[session_user] = lambda: 22
        app.dependency_overrides[db] = lambda: self.storage
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_project_search_requires_ownership(self):
        self.storage.create_engineering_project(22, "Robotics", "electronics",
                                                "engineering-search-test")
        with patch.object(GiteaClient, "search_paths", new_callable=AsyncMock) as search:
            search.return_value = {
                "matches": [{"path": "src/circuit.py", "type": "file"}],
                "complete": True, "scanned": 4
            }
            response = self.client.get("/api/projects/1/search?query=circuit")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["matches"][0]["path"], "src/circuit.py")
            self.assertEqual(self.client.get("/api/projects/1/search?query=a").status_code, 422)
            app.dependency_overrides[session_user] = lambda: 33
            self.assertEqual(self.client.get("/api/projects/1/search?query=circuit").status_code, 404)
            self.assertEqual(search.await_count, 1)

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

    def test_delete_project_removes_remote_before_mapping(self):
        self.storage.create_engineering_project(22, "Circuit", "electronics",
                                                "engineering-test-project")
        with patch.object(GiteaClient, "delete_repo", new_callable=AsyncMock) as remote:
            response = self.client.delete("/api/projects/1")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(remote.await_count, 1)
        self.assertEqual(self.client.get("/api/projects").json()["projects"], [])

    def test_delete_failure_preserves_mapping_for_retry(self):
        self.storage.create_engineering_project(22, "PCB", "electronics",
                                                "engineering-test-project")
        with patch.object(GiteaClient, "delete_repo", new_callable=AsyncMock) as remote:
            remote.side_effect = GiteaError(503, "Gitea unavailable")
            response = self.client.delete("/api/projects/1")
            self.assertEqual(response.status_code, 503)
            projects = self.client.get("/api/projects").json()["projects"]
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0].get("deletion_state"), "deleting")
            remote.side_effect = GiteaError(404, "Already absent")
            self.assertEqual(self.client.delete("/api/projects/1").status_code, 200)
            self.assertEqual(self.client.get("/api/projects").json()["projects"], [])

    def test_other_user_cannot_delete_project(self):
        self.storage.create_engineering_project(22, "Private", "software", "engineering-test")
        app.dependency_overrides[session_user] = lambda: 99
        with patch.object(GiteaClient, "delete_repo", new_callable=AsyncMock) as remote:
            self.assertEqual(self.client.delete("/api/projects/1").status_code, 404)
            remote.assert_not_awaited()
        self.assertEqual(len(self.storage.projects), 1)

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
