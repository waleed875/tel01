"""Owner-approved Gitea website changes must be atomic and revision checked."""
import unittest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from gitea_client import GiteaClient, GiteaError
from design_commit import build_proposal, commit_proposal, project_site_paths
from webapp import app, db, session_user


CONFIG = {
    "title": "موقع تجريبي",
    "description": "نظام هندسي عربي يعرض المشاريع والتقنيات.",
    "style": "light",
    "sections": ["features", "about"],
    "directory": "sites/engineering",
}
SHA = "a" * 40


class FakeProjects:
    def engineering_project(self, user, project_id):
        if user == 45 and project_id == 10:
            return {"id": 10, "repo_name": "engineering-owner-repo",
                    "kind": "software", "deletion_state": "active"}
        if user == 45 and project_id == 11:
            return {"id": 11, "repo_name": "engineering-archive",
                    "kind": "software", "deletion_state": "archived"}
        return None


class ProposalTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_two_files_in_one_commit_and_explicit_approval_token(self):
        client = GiteaClient(token="token", owner="testowner")
        with patch.object(client, "read_file", new_callable=AsyncMock) as read, \
             patch.object(client, "_call", new_callable=AsyncMock) as call:
            read.side_effect = GiteaError(404, "missing")
            preview = await build_proposal(client, "engineering-repo",
                                           user_id=45, project_id=10, config=CONFIG)
            self.assertEqual([x["operation"] for x in preview["files"]],
                             ["create", "create"])
            call.assert_not_awaited()
            self.assertTrue(preview["can_apply"])
            call.return_value = {"commit": {"sha": "b" * 40}}
            done = await commit_proposal(client, "engineering-repo", user_id=45,
                                         project_id=10, config=CONFIG,
                                         fingerprint=preview["fingerprint"])
            self.assertEqual(done["changed_paths"],
                             ["sites/engineering/index.html", "sites/engineering/style.css"])
            self.assertEqual(call.await_count, 1)
            request = call.await_args
            self.assertEqual(request.args, ("POST", "repos/testowner/engineering-repo/contents"))
            self.assertEqual(len(request.kwargs["json"]["files"]), 2)
            self.assertEqual(request.kwargs["json"]["files"][0]["operation"], "create")

    async def test_existing_files_are_updates_and_identical_files_are_unchanged(self):
        client = GiteaClient(token="token", owner="testowner")
        with patch.object(client, "read_file", new_callable=AsyncMock) as read, \
             patch.object(client, "_call", new_callable=AsyncMock) as call:
            read.side_effect = GiteaError(404, "missing")
            first = await build_proposal(client, "engineering-repo",
                                         user_id=45, project_id=10, config=CONFIG)
            html, css = first["files"]
            read.side_effect = [
                {"data": html["content"].encode("utf-8"), "sha": "a"*40},
                {"data": b"old css", "sha": "b"*40},
                {"data": html["content"].encode("utf-8"), "sha": "a"*40},
                {"data": b"old css", "sha": "b"*40},
            ]
            preview = await build_proposal(client, "engineering-repo",
                                           user_id=45, project_id=10, config=CONFIG)
            self.assertEqual([f["operation"] for f in preview["files"]],
                             ["unchanged", "update"])
            call.return_value = {"commit": {"sha": "c"*40}}
            result = await commit_proposal(client, "engineering-repo",
                                           user_id=45, project_id=10,
                                           config=CONFIG,
                                           fingerprint=preview["fingerprint"])
            self.assertEqual(result["changed_paths"], ["sites/engineering/style.css"])
            operations = call.await_args.kwargs["json"]["files"]
            self.assertEqual(len(operations), 1)
            self.assertEqual(operations[0]["operation"], "update")
            self.assertEqual(operations[0]["sha"], "b"*40)

    async def test_changed_existing_git_blob_requires_review_again(self):
        client = GiteaClient(token="token", owner="testowner")
        with patch.object(client, "read_file", new_callable=AsyncMock) as read, \
             patch.object(client, "_call", new_callable=AsyncMock) as call:
            read.side_effect = GiteaError(404, "missing")
            preview = await build_proposal(client, "engineering-repo",
                                           user_id=45, project_id=10, config=CONFIG)
            read.side_effect = [
                {"data": b"new, unrelated user change", "sha": SHA},
                GiteaError(404, "missing")
            ]
            with self.assertRaises(GiteaError) as changed:
                await commit_proposal(client, "engineering-repo", user_id=45,
                                      project_id=10, config=CONFIG,
                                      fingerprint=preview["fingerprint"])
            self.assertEqual(changed.exception.status, 409)
            call.assert_not_awaited()

    async def test_update_only_changed_files_and_sign_ownership(self):
        client = GiteaClient(token="token", owner="testowner")
        with patch.object(client, "read_file", new_callable=AsyncMock) as read, \
             patch.object(client, "_call", new_callable=AsyncMock) as call:
            read.side_effect = GiteaError(404, "missing")
            preview = await build_proposal(client, "engineering-repo",
                                           user_id=45, project_id=10, config=CONFIG)
            with self.assertRaises(GiteaError):
                await commit_proposal(client, "engineering-repo", user_id=46,
                                      project_id=10, config=CONFIG,
                                      fingerprint=preview["fingerprint"])
            call.assert_not_awaited()

    def test_path_restrictions(self):
        for bad in ("site", "docs", "websites", "sites/../admin",
                    ".git/config", "src/website", "sites/a//b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                project_site_paths(bad)
        self.assertEqual(project_site_paths("sites/my-company"),
                         ("sites/my-company/index.html", "sites/my-company/style.css"))


class WebsiteAPIReviewTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[session_user] = lambda: 45
        app.dependency_overrides[db] = FakeProjects
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_draft_no_git_writes_until_user_confirms(self):
        with patch.object(GiteaClient, "read_file", new_callable=AsyncMock) as read, \
             patch.object(GiteaClient, "_call", new_callable=AsyncMock) as call:
            read.side_effect = GiteaError(404, "not found")
            preview = self.client.post("/api/projects/10/design/preview", json=CONFIG)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual([r["operation"] for r in preview.json()["files"]],
                             ["create", "create"])
            call.assert_not_awaited()
            approval = {**CONFIG, "fingerprint": preview.json()["fingerprint"],
                        "approved": False}
            self.assertEqual(self.client.post("/api/projects/10/design/apply",
                                              json=approval).status_code, 409)
            call.assert_not_awaited()
            approval["approved"] = True
            call.return_value = {"commit": {"sha": "b" * 40}}
            self.assertEqual(self.client.post("/api/projects/10/design/apply",
                                              json=approval).status_code, 200)
            self.assertEqual(call.await_count, 1)

    def test_unknown_user_archived_project_and_invalid_paths_cannot_write(self):
        with patch.object(GiteaClient, "_call", new_callable=AsyncMock) as call:
            self.assertEqual(self.client.post("/api/projects/11/design/preview",
                                               json=CONFIG).status_code, 409)
            self.assertEqual(self.client.post("/api/projects/999/design/preview",
                                               json=CONFIG).status_code, 404)
            self.assertEqual(self.client.post("/api/projects/10/design/preview",
                                               json={**CONFIG, "directory": "src"}).status_code, 422)
            app.dependency_overrides[session_user] = lambda: 66
            self.assertEqual(self.client.post("/api/projects/10/design/preview",
                                               json=CONFIG).status_code, 404)
            call.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
