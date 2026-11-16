"""Inference for locally trained image classifier checkpoints only.

Labels reflect whatever classes the owner trained. Accuracy is not guaranteed
by the existence of a checkpoint; this is not a general vision-language AI.
"""
from io import BytesIO

import torch
from PIL import Image, ImageOps

from .vision import PatchVisionEncoder
from vision import describe_image


class LocalVisionClassifier:
    def __init__(self, checkpoint: str):
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        config = state["config"]
        if (config.get("image_size") != 64 or config.get("patch_size") != 8
                or not isinstance(state.get("labels"), list)
                or len(state["labels"]) != config["num_classes"]):
            raise ValueError("Unsupported local vision checkpoint")
        self.labels = state["labels"]
        self.heldout_accuracy = float(state.get("heldout_accuracy", 0.0))
        self.net = PatchVisionEncoder(**config)
        self.net.load_state_dict(state["model"], strict=True)
        self.net.eval()

    @torch.inference_mode()
    def classify(self, data: bytes):
        # Validate before opening image for classification.
        describe_image(data)
        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB").resize((64, 64))
            tensor = torch.tensor(list(image.getdata()), dtype=torch.float32)
            tensor = tensor.reshape(64, 64, 3).permute(2, 0, 1) / 255.0
        probabilities = torch.softmax(self.net(tensor.unsqueeze(0)), dim=-1)[0]
        index = int(probabilities.argmax())
        return {"label": self.labels[index],
                "model_score": round(float(probabilities[index]), 4),
                "heldout_accuracy": round(self.heldout_accuracy, 4),
                "notice": "تصنيف تجريبي من نموذج محلي. درجة النموذج ليست ضمان دقة أو فهم المشهد."}
