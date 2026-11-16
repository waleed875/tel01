"""Safety and quality gates for initial vision and website-design foundations."""
import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import torch
from PIL import Image
from fastapi.testclient import TestClient

from vision import describe_image
from site_builder import build_website
from engine.vision import PatchVisionEncoder
from engine.train_vision import train_vision
from engine.vision_inference import LocalVisionClassifier
from engine.evaluate_web import inspect_frontend
from webapp import app, session_user


def image_bytes(color=(130, 40, 20), fmt="PNG", size=(64, 64)):
    image = Image.new("RGB", size, color)
    stream = BytesIO()
    image.save(stream, format=fmt)
    return stream.getvalue()


class VisionSafetyTests(unittest.TestCase):
    def test_png_and_jpeg_have_bounded_nonsemantic_descriptors(self):
        for fmt in ("PNG", "JPEG"):
            with self.subTest(fmt=fmt):
                out = describe_image(image_bytes(fmt=fmt))
                self.assertEqual((out["width"], out["height"]), (64, 64))
                self.assertFalse(out["semantic_understanding"])
                self.assertEqual(out["analysis_level"], "pixel-descriptors-only")
                self.assertTrue(out["palette"])

    def test_unsafe_formats_and_oversized_images_rejected(self):
        for payload in (b"not an image", b"x" * (2 * 1024 * 1024 + 1),
                        image_bytes(fmt="GIF")):
            with self.assertRaises(ValueError):
                describe_image(payload)
        with self.assertRaises(ValueError):
            describe_image(image_bytes(size=(2000, 2001)))

    def test_image_endpoint_requires_owner_login(self):
        app.dependency_overrides[session_user] = lambda: 19
        try:
            client = TestClient(app)
            valid = base64.b64encode(image_bytes()).decode("ascii")
            response = client.post("/api/vision/analyze", json={"image_base64": valid})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["semantic_understanding"])
            self.assertEqual(client.post("/api/vision/analyze", json={
                "image_base64": "not-base64///"
            }).status_code, 422)
        finally:
            app.dependency_overrides.clear()


class WebsiteScaffoldTests(unittest.TestCase):
    def test_escaped_user_content_and_accessible_responsive_markup(self):
        scaffold = build_website("<script>alert('x')</script> Site",
            "<img src=x onerror=alert(1)> example product landing page",
            "professional", ["features", "about", "contact"])
        html, css = [row["content"] for row in scaffold["files"]]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('lang="ar" dir="rtl"', html)
        self.assertIn('aria-label="التنقل الرئيسي"', html)
        self.assertIn('href="#main"', html)
        self.assertIn("@media(max-width:650px)", css)
        audit = inspect_frontend(html, css)
        self.assertTrue(audit["all_pass"], audit["checks"])
        self.assertTrue(scaffold["requires_approval"])
        self.assertEqual(scaffold["mode"], "deterministic-scaffold")

    def test_duplicate_and_bad_sections_rejected(self):
        for sections in (["features", "features"], ["not-a-section"], []):
            with self.assertRaises(ValueError):
                build_website("Test site", "Valid details of a useful website",
                              "light", sections)

    def test_endpoint_only_generates_files_without_git_mutations(self):
        app.dependency_overrides[session_user] = lambda: 19
        try:
            client = TestClient(app)
            response = client.post("/api/design/scaffold", json={
                "title": "صفحة برمجيات", "description": "موقع عربي لعرض مشاريع البرمجيات",
                "style": "emerald", "sections": ["portfolio", "contact"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()["files"]), 2)
            self.assertTrue(response.json()["requires_approval"])
            self.assertTrue(response.json()["quality_checks"]["all_pass"])
        finally:
            app.dependency_overrides.clear()


class PatchVisionTrainTests(unittest.TestCase):
    def test_encoder_shapes_and_from_scratch_checkpoint(self):
        torch.set_num_threads(1)
        model = PatchVisionEncoder(width=16, depth=1, heads=4, num_classes=2)
        self.assertEqual(tuple(model(torch.rand(2, 3, 64, 64)).shape), (2, 2))
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "labeled"
            for label, color in (("red", (230, 20, 25)), ("blue", (20, 40, 230))):
                folder = root / label
                folder.mkdir(parents=True)
                for index in range(4):
                    (folder / f"image-{index}.png").write_bytes(image_bytes(color))
            output = Path(tmp) / "weights"
            metrics = train_vision(root, output, steps=2, width=16, depth=1, heads=4)
            self.assertEqual(metrics["heldout_count"], 2)
            self.assertTrue((output / "vision_checkpoint.pt").is_file())
            state = torch.load(output / "vision_checkpoint.pt",
                               weights_only=True, map_location="cpu")
            self.assertEqual(state["labels"], ["blue", "red"])
            self.assertIn("heldout_accuracy", state)
            classifier = LocalVisionClassifier(str(output / "vision_checkpoint.pt"))
            prediction = classifier.classify(image_bytes((225, 25, 30)))
            self.assertIn(prediction["label"], ("red", "blue"))
            self.assertGreaterEqual(prediction["model_score"], 0.5)
            self.assertLessEqual(prediction["model_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
