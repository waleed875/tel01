"""Evaluation protocol checks; model responses are never trusted/executed."""
import copy
import unittest
from unittest.mock import patch

from benchmarks.evaluate_tool_proposals import (load_suite, grade, evaluate,
                                                 format_reference)
from tutor import build_engineering_prompt


class ProposalBenchmarkTests(unittest.TestCase):
    def test_reference_self_check_only(self):
        with patch("engineering_tool_proposals.calculate", side_effect=AssertionError("Executed calculator")):
            report = evaluate("reference")
        self.assertEqual(report["passed"], report["total"])
        self.assertEqual(report["positive_total"], 8)
        self.assertEqual(report["negative_total"], 4)
        self.assertEqual(report["false_proposals"], 0)
        self.assertIsNone(report["checkpoint_sha256"])
        self.assertEqual(set(report["domains"]), {"math", "software", "electronics", "physics"})

    def test_wrong_operation_and_wrong_numbers_fail(self):
        case = load_suite()["tasks"][0]
        wrong_tool = {"operation": "math.quadratic", "inputs": {"a": 2, "b": 3, "c": 5}}
        self.assertFalse(grade(case, format_reference(wrong_tool))["passed"])
        wrong_number = copy.deepcopy(case["expected"])
        wrong_number["inputs"]["x"] = 40
        result = grade(case, format_reference(wrong_number))
        self.assertTrue(result["operation_correct"])
        self.assertFalse(result["inputs_correct"])

    def test_malformed_and_cross_domain_fail_without_calculation(self):
        case = load_suite()["tasks"][3]
        with patch("engineering_tool_proposals.calculate", side_effect=AssertionError("Must not execute")):
            for response in ("not JSON", "```engineering-tool\n{}\n```",
                             format_reference({"operation": "physics.force",
                                               "inputs": {"mass": 3, "acceleration": 4}})):
                self.assertFalse(grade(case, response)["passed"])

    def test_no_tool_false_positive_and_proper_abstention(self):
        case = next(x for x in load_suite()["tasks"] if x["id"] == "electronics_missing")
        self.assertTrue(grade(case, "تحتاج إلى الجهد أولاً.")["passed"])
        self.assertTrue(grade(case, format_reference({"operation":"electronics.ohm",
                          "inputs":{"voltage":10,"resistance":15}}))["false_proposal"])

    def test_same_prompt_as_chat_and_non_executing_reference(self):
        prompt = build_engineering_prompt("university", "physics", "ما محصلة القوة؟")
        self.assertIn("engineering-tool", prompt)
        self.assertTrue(prompt.endswith("ما محصلة القوة؟"))


if __name__ == "__main__":
    unittest.main()
