"""Corpus-derived Unicode tokens: strict old-checkpoint compatibility."""
import math
import tempfile
import unittest
from pathlib import Path

import torch

from engine.tokenizer import (ByteTokenizer, CharByteTokenizer,
                              build_character_tokenizer, tokenizer_from_spec,
                              tokenizer_spec)
from engine.train import train
from engine.inference import LocalModel
from engine.eval_holdout import evaluate_heldout


class CharacterTokenizerTests(unittest.TestCase):
    def test_roundtrip_arabic_code_and_unknown_utf8(self):
        tok = build_character_tokenizer(("معادلة فيزياء إلكترونيات Python " * 15), 80)
        sample = "مرحبا Python: x = 2 ** 3; Ω=5 Ω؛ 💡 🧠"
        self.assertEqual(tok.decode(tok.encode(sample)), sample)
        self.assertEqual(tok.decode(tok.encode("☃️")), "☃️")
        self.assertTrue(all(t < tok.vocab_size for t in tok.encode(sample)))

    def test_arabic_reduces_tokens_relative_to_bytes(self):
        training = ("الرياضيات والفيزياء والإلكترونيات " * 20)
        tok = build_character_tokenizer(training, 100)
        self.assertLess(len(tok.encode(training)), len(ByteTokenizer().encode(training)))
        self.assertEqual(len(tok.encode("abc123")), 6)

    def test_deterministic_and_strict_spec(self):
        source = "برمجة فيزياء رياضيات " * 12
        one = build_character_tokenizer(source, 80)
        two = build_character_tokenizer(source, 80)
        self.assertEqual(tokenizer_spec(one), tokenizer_spec(two))
        state = tokenizer_spec(one)
        restored = tokenizer_from_spec(state, one.vocab_size)
        self.assertEqual(restored.encode(source), one.encode(source))
        self.assertEqual(tokenizer_from_spec(None, 256).vocab_size, 256)
        for spec in ({"version": 1, "kind": "char-byte", "chars": "اا"},
                     {"version": 1, "kind": "char-byte", "chars": "a"},
                     {"version": 2, "kind": "char-byte", "chars": "آ"},
                     {"version": 1, "kind": "char-byte", "chars": "آ", "secret": 5}):
            with self.assertRaises(ValueError):
                tokenizer_from_spec(spec, 257)
        with self.assertRaises(ValueError):
            tokenizer_from_spec(state, one.vocab_size + 1)
        with self.assertRaises(ValueError):
            tokenizer_from_spec(None, 257)

    def test_training_split_vocab_excludes_heldout_only_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "data.txt"
            # Last character occurs only in the validation split.
            corpus.write_text("رياضيات " * 25 + "⛔" * 10, encoding="utf-8")
            output = root / "model"
            torch.set_num_threads(1)
            train(corpus, output, steps=1, block_size=8, batch_size=2,
                  layers=1, heads=1, dim=16, learning_rate=3e-4, seed=42,
                  device="cpu", tokenizer_mode="char", max_char_tokens=80)
            checkpoint = torch.load(output / "checkpoint.pt", map_location="cpu",
                                    weights_only=True)
            self.assertNotIn("⛔", checkpoint["tokenizer_spec"]["chars"])

    def test_checkpoint_training_resume_and_inference(self):
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "training.txt"
            corpus.write_text(("سؤال: ما قانون أوم؟\nجواب: V = I * R.\n" * 35),
                              encoding="utf-8")
            output = root / "model"
            settings = dict(steps=2, block_size=16, batch_size=2,
                            layers=1, heads=1, dim=16, learning_rate=3e-4,
                            seed=42, device="cpu", tokenizer_mode="char",
                            max_char_tokens=80)
            train(corpus, output, **settings)
            path = output / "checkpoint.pt"
            snapshot = torch.load(path, map_location="cpu", weights_only=True)
            self.assertGreater(snapshot["config"]["vocab_size"], 256)
            model = LocalModel(str(path), max_tokens=4)
            self.assertIsNotNone(model.load())
            self.assertEqual(model.tokenizer.vocab_size, snapshot["config"]["vocab_size"])
            self.assertIsInstance(model.answer("قانون أوم؟"), str)
            val = evaluate_heldout(path, [{"subject": "electronics",
                 "question": "ما الجهد؟", "answer": "الجهد يساوي التيار مضروبًا بالمقاومة"}])
            self.assertTrue(math.isfinite(val))
            with self.assertRaisesRegex(ValueError, "architecture|tokenizer"):
                train(corpus, output, resume=path, **{**settings, "tokenizer_mode": "byte"})
            train(corpus, output, resume=path, **settings)
            self.assertEqual(torch.load(path, weights_only=True)["steps"], 4)


if __name__ == "__main__":
    unittest.main()
