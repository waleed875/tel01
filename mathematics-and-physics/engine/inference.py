"""Load only self-generated training checkpoints and generate text locally."""
from pathlib import Path
import torch
from .model import GPT, GPTConfig
from .tokenizer import ByteTokenizer, tokenizer_from_spec


class LocalModel:
    def __init__(self, path: str, max_tokens: int = 180):
        self.path = Path(path)
        self.tokenizer = ByteTokenizer()
        self.max_tokens = max_tokens
        self.model = None

    def load(self):
        if not self.path.is_file():
            raise FileNotFoundError(f"No trained checkpoint at {self.path}. Train first.")
        # Only load operator-created, trusted checkpoints. No external model weights.
        checkpoint = torch.load(self.path, map_location="cpu", weights_only=True)
        config = GPTConfig(**checkpoint["config"])
        self.tokenizer = tokenizer_from_spec(checkpoint.get("tokenizer_spec"), config.vocab_size)
        model = GPT(config)
        model.load_state_dict(checkpoint["model"], strict=True)
        model.eval()
        self.model = model
        return model

    @torch.inference_mode()
    def answer(self, prompt: str) -> str:
        model = self.model if self.model is not None else self.load()
        source = "سؤال: " + prompt.strip() + "\nجواب:"
        idx = self.tokenizer.encode(source)[-model.config.block_size:]
        if not idx:
            raise ValueError("Empty prompt")
        tensor = torch.tensor([idx], dtype=torch.long)
        output = model.generate(tensor, max_new_tokens=self.max_tokens,
                                temperature=0.8, top_k=32)
        generated = output[0].tolist()[len(idx):]
        return self.tokenizer.decode(generated).split("\nسؤال:")[0].strip() or "لا توجد إجابة مدربة كافية بعد."
