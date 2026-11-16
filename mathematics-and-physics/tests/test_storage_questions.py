import unittest
from questions import QUESTIONS, select_question
from knowledge import find_references
from engine.tokenizer import ByteTokenizer
from tutor import SUBJECT_NAMES

class TestEngine(unittest.TestCase):
    def test_questions(self):
        self.assertEqual(len(QUESTIONS), 24)
        for subject in ("math", "physics"):
            for level in ("beginner", "intermediate", "highschool", "university"):
                a = select_question(subject, level)
                b = select_question(subject, level, a.id)
                self.assertNotEqual(a.id, b.id)

    def test_arabic_byte_tokenizer(self):
        sample = "رياضيات وهندسة Python: F=ma"
        tok = ByteTokenizer()
        self.assertEqual(tok.decode(tok.encode(sample)), sample)
        self.assertEqual(tok.vocab_size, 256)

    def test_domains(self):
        self.assertIn("software", SUBJECT_NAMES)
        self.assertIn("electronics", SUBJECT_NAMES)
        self.assertTrue(find_references("قانون أوم المقاومة", "electronics"))

if __name__ == "__main__":
    unittest.main()
