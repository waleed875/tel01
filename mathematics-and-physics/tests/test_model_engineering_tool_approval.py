"""User-bound reviewed engineering tool proposals; no autonomous execution."""
import json
import time
import unittest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from engineering_tool_proposals import propose, approved_calculate
from webapp import app, session_user, db


def proposed_text(operation="physics.force", inputs=None):
    if inputs is None:
        inputs = {"mass": 3, "acceleration": 4}
    return (
        "سأقترح تحققًا رياضيًا، ولا أنفذه دون إذنك.\n"
        "```engineering-tool\n" +
        json.dumps({"operation": operation, "inputs": inputs}, ensure_ascii=False) +
        "\n```"
    )


class ToolProposalTests(unittest.TestCase):
    def test_proposal_never_executes_and_approval_calculates(self):
        with patch("engineering_tool_proposals.calculate", wraps=__import__(
                "engineering_calculators").calculate) as calculator:
            found = propose(proposed_text(), user_id=25)
            self.assertIsNotNone(found)
            # Preview must never call the calculator; the token is review-only.
            self.assertEqual(found["operation"], "physics.force")
            self.assertNotIn("values", found)
            self.assertNotIn("force_n", found)
            self.assertEqual(found["label"], "قانون نيوتن الثاني")
            self.assertEqual(calculator.call_count, 0)
            result = approved_calculate(
                25, found["operation"], found["inputs"], found["token"])
            self.assertEqual(result["values"]["force_n"], 12)

    def test_other_user_changes_and_forged_approval_rejected(self):
        proposal = propose(proposed_text(), 25)
        for uid, inputs, token in [
            (26, proposal["inputs"], proposal["token"]),
            (25, {"mass": 3, "acceleration": 5}, proposal["token"]),
            (25, proposal["inputs"], proposal["token"][:-1] + (
                "0" if proposal["token"][-1] != "0" else "1")),
            (25, proposal["inputs"], "abc"),
        ]:
            with self.subTest(uid=uid, inputs=inputs, token=token):
                with self.assertRaises(ValueError):
                    approved_calculate(uid, "physics.force", inputs, token)

    def test_expired_and_unreasonably_future_tokens(self):
        with patch("engineering_tool_proposals.time.time", return_value=1_800_000_000):
            proposal = propose(proposed_text(), 25)
        with patch("engineering_tool_proposals.time.time", return_value=1_800_000_700):
            with self.assertRaisesRegex(ValueError, "expired"):
                approved_calculate(25, proposal["operation"], proposal["inputs"],
                                   proposal["token"])
        with patch("engineering_tool_proposals.time.time", return_value=1_700_000_000):
            with self.assertRaisesRegex(ValueError, "expired"):
                approved_calculate(25, proposal["operation"], proposal["inputs"],
                                   proposal["token"])

    def test_reject_non_protocol_text_and_malformed_content(self):
        samples = [
            "من فضلك شغل كود Python لحساب القوة",
            "```python\nimport os\n```",
            proposed_text("shell.run", {"command": "whoami"}),
            proposed_text("physics.force", {"mass": -3, "acceleration": 4}),
            proposed_text("physics.force", {"mass": 3, "acceleration": True}),
            proposed_text() + "\n" + proposed_text(),
            "```engineering-tool\n{broken JSON}\n```",
            "```engineering-tool\n" + '{"operation":"physics.force","inputs":' +
            '{"mass":NaN,"acceleration":4}}' + "\n```",
        ]
        for text in samples:
            with self.subTest(sample=text[:90]):
                self.assertIsNone(propose(text, 12))

    def test_whitelist_allows_math_and_electronics_but_never_code_exec(self):
        for operation, inputs in [
            ("math.quadratic", {"a": 1, "b": -3, "c": 2}),
            ("electronics.ohm", {"voltage": 12, "resistance": 1000}),
            ("software.analyze_python", {"source": "print('not executed')"}),
        ]:
            item = propose(proposed_text(operation, inputs), 12)
            self.assertIsNotNone(item)
            out = approved_calculate(12, operation, inputs, item["token"])
            self.assertEqual(out["domain"], operation.split(".")[0])

    def test_no_hidden_code_execution(self):
        text = proposed_text("software.analyze_python", {
            "source": "__import__('os').system('echo executed')"
        })
        with patch("os.system", side_effect=AssertionError("executed!")):
            item = propose(text, 5)
            self.assertIsNotNone(item)
            result = approved_calculate(5, item["operation"], item["inputs"],
                                        item["token"])
        self.assertEqual(result["values"]["imports"], 0)


class ChatToolProposalTests(unittest.TestCase):
    def setUp(self):
        class FakeStorage:
            subject = "physics"
            def active_training_job(self, user):
                return None
            def profile(self, user):
                return {"subject": self.subject, "level": "intermediate"}
            def recent_history(self, user, limit):
                return []
            def add_exchange(self, user, question, answer):
                return None
        self.storage = FakeStorage()
        app.dependency_overrides[session_user] = lambda: 42
        app.dependency_overrides[db] = lambda: self.storage
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_chat_proposes_but_never_runs_calculator(self):
        fake_model = type("FakeModel", (), {})()
        fake_model.ask = AsyncMock(return_value=proposed_text())
        with patch("webapp.model", fake_model), \\
             patch("engineering_tool_proposals.calculate",
                   side_effect=AssertionError("Calculator ran during preview")):
            response = self.client.post("/api/chat", json={
                "question": "احسب قوة جسم 3 كغ بتسارع 4 م/ث²",
                "use_research": False,
            })
        self.assertEqual(response.status_code, 200, response.text)
        proposal = response.json()["tool_proposal"]
        self.assertEqual(proposal["operation"], "physics.force")
        self.assertIn("token", proposal)
        self.assertNotIn("values", proposal)

    def test_proposals_for_other_subjects_are_not_offered(self):
        self.storage.subject = "math"
        fake_model = type("FakeModel", (), {})()
        fake_model.ask = AsyncMock(return_value=proposed_text())
        with patch("webapp.model", fake_model):
            response = self.client.post("/api/chat", json={
                "question": "السؤال الرياضي",
                "use_research": False,
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["tool_proposal"])


class ToolApprovalAPITests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[session_user] = lambda: 42
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_needs_explicit_confirmation_and_is_read_only(self):
        item = propose(proposed_text(), 42)
        data = {"operation": item["operation"], "inputs": item["inputs"],
                "token": item["token"], "approved": False}
        with patch("webapp.GiteaClient") as gitea:
            response = self.client.post("/api/engineering/model-tool/apply", json=data)
            self.assertEqual(response.status_code, 409)
            data["approved"] = True
            response = self.client.post("/api/engineering/model-tool/apply", json=data)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["values"]["force_n"], 12)
            self.assertEqual(response.json()["approval"], "explicit-user-approval")
            gitea.assert_not_called()

    def test_other_account_forged_invalid(self):
        item = propose(proposed_text(), 99)
        data = {"operation": item["operation"], "inputs": item["inputs"],
                "token": item["token"], "approved": True}
        response = self.client.post("/api/engineering/model-tool/apply", json=data)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post("/api/engineering/model-tool/apply",
                         json={**data, "token": "garbage"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
