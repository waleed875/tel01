import tempfile
import unittest
from pathlib import Path
from questions import QUESTIONS, select_question
from storage import Storage


class TutorDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Storage(str(Path(self.temp.name) / 'test.sqlite3'))

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_and_settings(self):
        self.assertEqual(self.db.profile(42)['subject'], 'math')
        self.db.set_level(42, 'university')
        self.db.set_subject(42, 'physics')
        self.assertEqual(self.db.profile(42)['level'], 'university')
        self.assertEqual(self.db.profile(42)['subject'], 'physics')

    def test_grade_only_once(self):
        self.db.set_active_quiz(42, 'm_b_1')
        self.assertTrue(self.db.grade_quiz(42, 'm_b_1', True))
        self.assertFalse(self.db.grade_quiz(42, 'm_b_1', True))
        self.assertEqual(self.db.profile(42)['correct'], 1)
        self.assertEqual(self.db.profile(42)['attempted'], 1)

    def test_stale_answers_ignored(self):
        self.db.set_active_quiz(42, 'm_b_1')
        self.db.set_active_quiz(42, 'm_b_2')
        self.assertFalse(self.db.grade_quiz(42, 'm_b_1', True))

    def test_history_and_delete(self):
        self.db.add_exchange(42, 'سؤال', 'جواب')
        self.assertEqual(len(self.db.recent_history(42)), 2)
        self.db.delete_user(42)
        self.assertEqual(self.db.recent_history(42), [])
        self.assertEqual(self.db.profile(42)['attempted'], 0)

    def test_quota(self):
        self.assertTrue(self.db.claim_quota(42, 1))
        self.assertFalse(self.db.claim_quota(42, 1))
        self.db.release_quota(42)
        self.assertTrue(self.db.claim_quota(42, 1))

    def test_question_bank(self):
        self.assertEqual(len(QUESTIONS), 24)
        for subject in ('math', 'physics'):
            for level in ('beginner', 'intermediate', 'highschool', 'university'):
                q = select_question(subject, level)
                another = select_question(subject, level, q.id)
                self.assertNotEqual(q.id, another.id)
                self.assertEqual(len(q.options), 4)
                self.assertIn(q.correct, range(4))


if __name__ == '__main__':
    unittest.main()
