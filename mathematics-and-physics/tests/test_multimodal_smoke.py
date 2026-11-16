"""Verify image/text fusion trains from random weights and checkpoints safely."""
import json
from pathlib import Path
import tempfile
import unittest

import torch
from PIL import Image

from engine.model import GPTConfig
from engine.multimodal import MultimodalGPT
from engine.train_multimodal import load_pairs, train_pairs
from engine.multimodal_inference import ExperimentalVisualQA
from io import BytesIO


class MultimodalTests(unittest.TestCase):
    def test_gradients_flow_into_visual_patches(self):
        torch.set_num_threads(1)
        config = GPTConfig(vocab_size=256, block_size=64, n_layer=1,
                           n_head=4, n_embd=16, dropout=0, bias=True)
        model = MultimodalGPT(config)
        image = torch.rand(1, 3, 64, 64)
        idx = torch.randint(0, 256, (1, 12), dtype=torch.long)
        targets = idx.clone()
        logits, loss = model(image, idx, targets)
        self.assertEqual(tuple(logits.shape), (1, 12, 256))
        loss.backward()
        self.assertIsNotNone(model.visual_patch.weight.grad)
        self.assertGreater(float(model.visual_patch.weight.grad.abs().sum()), 0)

    def test_train_aligned_distinct_images_and_save_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for i in range(8):
                filename = f"fixture_{i}.png"
                Image.new("RGB", (64, 64),
                          (i * 20 + 10, i * 12 + 8, i * 6 + 10)).save(root / filename)
                rows.append({"image": filename,
                             "question": f"Which code sample is shown {i}?",
                             "answer": f"Example {i}."})
            (root / "pairs.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            self.assertEqual(len(load_pairs(root)), 8)
            output = root / "output"
            result = train_pairs(root, output, steps=2, seed=9,
                                 width=16, depth=1, heads=4, block_size=128)
            self.assertEqual(result["heldout_images"], 2)
            state = torch.load(output / "multimodal_checkpoint.pt",
                               map_location="cpu", weights_only=True)
            self.assertEqual(state["training_images"], 6)
            self.assertGreater(result["holdout_loss"], 0)
            self.assertLess(result["holdout_loss"], 20)
            classifier = ExperimentalVisualQA(str(output / "multimodal_checkpoint.pt"))
            with BytesIO() as image_data:
                Image.new("RGB", (64, 64), (60, 20, 15)).save(image_data, "PNG")
                prediction = classifier.ask(image_data.getvalue(), "What is this?", max_new_tokens=2)
            self.assertTrue(prediction["experimental"])
            self.assertIn("answer", prediction)
            rows[1]["image"] = rows[0]["image"]
            (root / "pairs.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate image"):
                load_pairs(root)


if __name__ == "__main__":
    unittest.main()
