"""Experimental local image+question inference from an owner's own weights.

Unverified checkpoints are not accepted as trusted engineering answers.
"""
from pathlib import Path

from PIL import Image, ImageOps
from io import BytesIO
import torch

from .model import GPTConfig
from .multimodal import MultimodalGPT
from .tokenizer import ByteTokenizer
from vision import describe_image


class ExperimentalVisualQA:
    def __init__(self, checkpoint: str):
        state = torch.load(Path(checkpoint), weights_only=True, map_location="cpu")
        config = GPTConfig(**state["config"])
        if config.vocab_size != 256 or state["image_size"] != 64 or state["patch_size"] != 16:
            raise ValueError("Invalid multimodal model configuration")
        model = MultimodalGPT(config)
        model.load_state_dict(state["model"], strict=True)
        model.eval()
        self.model = model
        self.tokenizer = ByteTokenizer()
        self.heldout_loss = float(state.get("holdout_loss", 0))

    @torch.inference_mode()
    def ask(self, image_data: bytes, question: str, max_new_tokens: int = 48):
        describe_image(image_data)
        question = question.strip()
        if not 1 <= len(question) <= 500:
            raise ValueError("Image question is missing or too long")
        with Image.open(BytesIO(image_data)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB").resize((64, 64))
            pixels = torch.tensor(list(image.getdata()), dtype=torch.float32)
            pixels = pixels.reshape(64, 64, 3).permute(2, 0, 1) / 255.0
        prefix = "سؤال: " + question + "\nجواب: "
        keep = self.model.language.config.block_size - self.model.patch_count
        ids = self.tokenizer.encode(prefix)[-keep:]
        if not ids:
            raise ValueError("Invalid image question")
        text = torch.tensor([ids], dtype=torch.long)
        generated = self.model.generate(
            pixels.unsqueeze(0), text, max_new_tokens=max_new_tokens, top_k=32)
        answer = self.tokenizer.decode(generated[0].tolist()[len(ids):])
        return {
            "answer": answer.strip() or "لم يتم تعلم إجابة مفهومة بعد.",
            "experimental": True,
            "heldout_loss": self.heldout_loss,
            "notice": "إجابة خام من نموذج بصري-لغوي صغير مدرب محليًا؛ ليست معلومة هندسية مؤكدة ولا تستخدم لإجراء تعديلات تلقائية.",
        }
