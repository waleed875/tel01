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
