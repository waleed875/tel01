"""Offline unit tests; PostgreSQL integration tests run separately when configured."""
import unittest
from questions import QUESTIONS, select_question
from knowledge import find_references
from tutor import Tutor, SUBJECT_NAMES

class TestLocalCurriculum(unittest.TestCase):
    def test_questions_are_well_formed(self):
        self.assertEqual(len(QUESTIONS), 24)
        for subject in ('math', 'physics'):
            for level in ('beginner', 'intermediate', 'highschool', 'university'):
                first = select_question(subject, level)
                second = select_question(subject, level, first.id)
                self.assertNotEqual(first.id, second.id)
                self.assertIn(first.correct, range(4))

    def test_engineering_subjects(self):
        self.assertIn('software', SUBJECT_NAMES)
        self.assertIn('electronics', SUBJECT_NAMES)

    def test_knowledge_search(self):
        docs = find_references('قانون أوم الجهد المقاومة', 'electronics')
        self.assertTrue(docs)
        self.assertTrue(any('الإلكترونيات' in text for _, text in docs))

    def test_ollama_endpoint(self):
        tutor = Tutor(model='qwen2.5:3b', base_url='http://ollama:11434')
        self.assertEqual(tutor.endpoint, 'http://ollama:11434/api/chat')

if __name__ == '__main__':
    unittest.main()
