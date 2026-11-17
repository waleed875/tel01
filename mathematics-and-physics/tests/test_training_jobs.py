"""Unit tests for snapshot isolation and bounded training-worker inputs."""
import unittest

from engine.worker import split_examples, serialize_training


class TrainingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"id": n, "subject": "physics", "question": f"سؤال فيزياء رقم {n} عن القوة",
             "answer": f"الإجابة المعتمدة رقم {n} تستخدم قانون نيوتن F=ma."}
            for n in range(1, 21)
        ]

    def test_heldout_is_disjoint_and_deterministic(self):
        a, b = split_examples(self.rows, seed=42)
        c, d = split_examples(self.rows, seed=42)
        self.assertEqual([r["id"] for r in a], [r["id"] for r in c])
        self.assertEqual([r["id"] for r in b], [r["id"] for r in d])
        self.assertFalse({r["id"] for r in a} & {r["id"] for r in b})
        self.assertEqual(len(a) + len(b), len(self.rows))
        self.assertGreaterEqual(len(b), 2)

    def test_rejects_tool_benchmark_leakage_before_split(self):
        from benchmarks.evaluate_tool_proposals import load_suite
        from benchmarks.evaluate_domains import load_benchmark
        for task in (load_suite()["tasks"][0], load_suite()["tasks"][-1]):
            rows = [dict(row) for row in self.rows]
            rows[0] = {"id": 1, "subject": task["subject"],
                       "question": "  " + task["question"] + " ",
                       "answer": "تفسير علمي مدقق"}
            with self.assertRaisesRegex(ValueError, "Evaluation question"):
                split_examples(rows, seed=42)
        task = load_benchmark()["tasks"][0]
        rows = [dict(row) for row in self.rows]
        rows[0] = {"id": 1, "subject": task["subject"], "question": task["question"],
                   "answer": "جواب"}
        with self.assertRaisesRegex(ValueError, "Evaluation question"):
            split_examples(rows, seed=42)

    def test_minimum_examples(self):
        with self.assertRaises(ValueError):
            split_examples(self.rows[:11], seed=42)

    def test_serialization_contains_subject_questions_and_answers(self):
        output = serialize_training(self.rows[:2])
        self.assertIn("المجال: physics", output)
        self.assertIn("سؤال: سؤال فيزياء", output)
        self.assertIn("جواب: الإجابة المعتمدة", output)


if __name__ == "__main__":
    unittest.main()
