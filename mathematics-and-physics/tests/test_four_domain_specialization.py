"""Four-domain boundaries, data integrity and independent reference evaluation."""
import tempfile
from pathlib import Path
import json
import unittest

from fastapi.testclient import TestClient
from engineering_domains import DOMAINS, catalog, normalize_text, verify_examples, coverage, subject_prompt
from engine.worker import split_examples
from benchmarks.evaluate_domains import load_benchmark, grade, evaluate, verify_no_train_leakage
from webapp import app


class SpecializationTests(unittest.TestCase):
    def test_only_four_engineering_domains(self):
        self.assertEqual(set(DOMAINS), {"software", "math", "electronics", "physics"})
        self.assertTrue(catalog()["only_these_domains"])
        response = TestClient(app).get("/api/catalog")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()["specialization"]["domains"]), set(DOMAINS))

    def test_prompt_scope_and_cross_domain_questions(self):
        prompt = subject_prompt("electronics", "جامعي",
                                "اكتب كود Python لحساب جهد الدارة باستخدام قانون أوم")
        self.assertIn("هندسة البرمجيات", prompt)
        self.assertIn("هندسة الإلكترونيات", prompt)
        self.assertIn("Python", prompt)
        with self.assertRaises(ValueError):
            subject_prompt("medicine", "جامعي", "أجب")

    def test_normalized_duplicate_questions_rejected_across_domains(self):
        samples = [
            {"id": 1, "subject": "math", "question": "  حل  2+2  ", "answer": "4"},
            {"id": 2, "subject": "physics", "question": "حل 2+2", "answer": "4"},
        ]
        self.assertEqual(normalize_text(samples[0]["question"]), normalize_text(samples[1]["question"]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            verify_examples(samples)
        with self.assertRaises(ValueError):
            verify_examples([{"subject": "medicine", "question": "سؤال", "answer": "نتيجة"}])

    def test_stratified_split_by_domain_and_missing_coverage_report(self):
        examples = []
        index = 1
        for subject in DOMAINS:
            for local in range(5):
                examples.append({"id": index, "subject": subject,
                                 "question": f"السؤال {subject} رقم {local}",
                                 "answer": f"نتيجة علمية موثقة {local}"})
                index += 1
        a, b = split_examples(examples, seed=17)
        self.assertEqual(len(a), 16)
        self.assertEqual(len(b), 4)
        self.assertEqual({row["subject"] for row in b}, set(DOMAINS))
        self.assertEqual(([x["id"] for x in a], [x["id"] for x in b]),
                         ([x["id"] for x in split_examples(examples, 17)[0]],
                          [x["id"] for x in split_examples(examples, 17)[1]]))
        report = coverage(a, b)
        self.assertEqual(report["covered_domains"], 4)
        single_domain = [x for x in examples if x["subject"] == "math"]
        self.assertEqual(verify_examples(single_domain)["missing_domains"],
                         ["software", "electronics", "physics"])


class DomainEvaluationTests(unittest.TestCase):
    def test_reference_answers_earn_full_score_only_as_harness_self_check(self):
        data = load_benchmark()
        self.assertEqual(set(x["subject"] for x in data["tasks"]), set(DOMAINS))
        report = evaluate("reference")
        self.assertEqual(report["passed"], report["total"], report)
        self.assertIsNone(report["checkpoint_sha256"])
        self.assertIn("المرجعية", report["notice"])

    def test_wrong_numerical_values_or_missing_units_fail(self):
        case = next(x for x in load_benchmark()["tasks"]
                    if x["id"] == "electronics_ohm")
        self.assertTrue(grade(case, "الجهد يساوي 4 فولت")["passed"])
        self.assertFalse(grade(case, "الجهد يساوي 4 أمبير")["passed"])
        self.assertFalse(grade(case, "الجهد يساوي 40 فولت")["passed"])
        self.assertFalse(grade(case, "الجهد يساوي 4")["passed"])

    def test_public_benchmark_training_contamination_fails(self):
        task = load_benchmark()["tasks"][0]
        with self.assertRaisesRegex(ValueError, "Evaluation question"):
            verify_no_train_leakage([task], [{"subject": task["subject"],
                                               "question": "  " + task["question"] + " "}])
        verify_no_train_leakage([task], [{"subject": "math", "question": "تمرين مستقل"}])


if __name__ == "__main__":
    unittest.main()
