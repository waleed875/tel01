"""Safe project previews and atomic Gitea rename regression tests."""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from gitea_client import GiteaClient, GiteaError
from webapp import app, db, session_user, safe_preview_type
from fastapi import HTTPException


class FakeProjects:
    def engineering_project(self, user_id, project_id):
        if user_id != 101 or project_id != 8:
            return None
        return {"id": 8, "repo_name": "engineering-test-repo",
                "title": "Test", "deletion_state": "active"}


class PreviewTests(unittest.TestCase):
    def test_validate_pdf_and_images_only_by_extension_and_signature(self):
        valid = [
            ("manual.pdf", b"%PDF-1.7\n", "application/pdf"),
            ("circuit.png", b"\x89PNG\r\n\x1a\n", "image/png"),
            ("photo.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"),
            ("sim.gif", b"GIF89a", "image/gif"),
            ("capture.webp", b"RIFFabcdWEBP", "image/webp"),
            ("notes.md", "# محاضرة\n".encode("utf-8"), "text/plain"),
        ]
        for path, body, mime in valid:
            with self.subTest(path=path):
                self.assertEqual(safe_preview_type(path, body), mime)
        for path, body in [
            ("unsafe.svg", b"<svg onload=alert(1)></svg>"),
            ("index.html", b"<script>bad()</script>"),
            ("fake.pdf", b"<html>unsafe</html>"),
            ("fake.png", b"not png"),
            ("image.jpg", b"not jpeg"),
            ("notes.md", b"\xff\xfe"),
        ]:
            with self.subTest(path=path):
                with self.assertRaises(HTTPException):
                    safe_preview_type(path, body)

    def test_preview_and_metadata_are_owned_and_nosniff(self):
        app.dependency_overrides[session_user] = lambda: 101
        app.dependency_overrides[db] = FakeProjects
        try:
            client = TestClient(app)
            with patch.object(GiteaClient, "read_file", new_callable=AsyncMock) as read:
                read.return_value = {"path": "docs/notes.md", "size": 11,
                                     "sha": "a"*40, "data": b"# example\n"}
                result = client.get("/api/projects/8/preview?path=docs/notes.md")
                self.assertEqual(result.status_code, 200)
                self.assertTrue(result.headers["content-type"].startswith("text/plain"))
                self.assertEqual(result.headers["x-content-type-options"], "nosniff")
                self.assertEqual(result.headers["content-security-policy"], "sandbox")
                self.assertEqual(client.get("/api/projects/8/file-metadata?path=docs/notes.md").json()["sha"], "a"*40)
                app.dependency_overrides[session_user] = lambda: 999
                self.assertEqual(client.get("/api/projects/8/preview?path=docs/notes.md").status_code, 404)
                self.assertEqual(client.get("/api/projects/8/file-metadata?path=docs/notes.md").status_code, 404)
        finally:
            app.dependency_overrides.clear()

    def test_api_rename_requires_ownership(self):
        app.dependency_overrides[session_user] = lambda: 101
        app.dependency_overrides[db] = FakeProjects
        try:
            client = TestClient(app)
            with patch.object(GiteaClient, "rename_file", new_callable=AsyncMock) as rename:
                rename.return_value = {"commit": {"sha": "c"*40}}
                payload = {"from_path": "a.py", "to_path": "src/a.py",
                           "sha": "a"*40, "message": "Move source code"}
                response = client.post("/api/projects/8/rename", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(rename.await_args.kwargs["sha"], "a"*40)
                app.dependency_overrides[session_user] = lambda: 55
                self.assertEqual(client.post("/api/projects/8/rename", json=payload).status_code, 404)
                self.assertEqual(rename.await_count, 1)
        finally:
            app.dependency_overrides.clear()


class AtomicRenameTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_commit_rename_payload_and_conflict_guards(self):
        client = GiteaClient(token="test-token", owner="dev")
        sha = "a"*40
        with patch.object(client, "read_file", new_callable=AsyncMock) as read, \
             patch.object(client, "_call", new_callable=AsyncMock) as request:
            read.side_effect = [
                {"sha": sha, "data": b"print(3)", "path": "src/demo.py"},
                GiteaError(404, "not found"),
            ]
            request.return_value = {"commit": {"sha": "b"*40}}
            await client.rename_file("engineering-demo", "src/demo.py",
                                     "src/renamed.py", sha=sha, message="Rename source")
            self.assertEqual(request.await_count, 1)
            self.assertEqual(request.await_args.args[:2], ("POST", "repos/dev/engineering-demo/contents"))
            operations = request.await_args.kwargs["json"]["files"]
            self.assertEqual(operations, [{"operation": "rename", "path": "src/renamed.py",
                                           "from_path": "src/demo.py", "sha": sha}])
        with patch.object(client, "read_file", new_callable=AsyncMock) as read, \
             patch.object(client, "_call", new_callable=AsyncMock) as request:
            read.return_value = {"sha": "b"*40, "data": b"x"}
            with self.assertRaises(GiteaError) as exc:
                await client.rename_file("engineering-demo", "a.py", "b.py",
                                         sha=sha, message="Rename source")
            self.assertEqual(exc.exception.status, 409)
            request.assert_not_awaited()
        with self.assertRaises(ValueError):
            await client.rename_file("engineering-demo", "a.py", "../secret.py",
                                     sha=sha, message="Rename source")


if __name__ == "__main__":
    unittest.main()
