"""Measure token loss on wholly held-out training examples.

This is a development diagnostic, NOT proof that engineering answers are correct.
No held-out answers are used to optimize model weights.
"""
from pathlib import Path
import torch
from .model import GPT, GPTConfig
from .tokenizer import ByteTokenizer


@torch.inference_mode()
def evaluate_heldout(checkpoint_path: str | Path, examples: list[dict]) -> float:
    if not examples:
        raise ValueError("A held-out set is required")
    state = torch.load(str(checkpoint_path), map_location="cpu", weights_only=True)
    cfg = GPTConfig(**state["config"])
    if cfg.vocab_size != 256:
        raise ValueError("Unexpected tokenizer")
    model = GPT(cfg)
    model.load_state_dict(state["model"], strict=True)
    model.eval()
    tokenizer = ByteTokenizer()
    total = 0.0
    seen = 0
    for example in examples:
        message = (f"المجال: {example['subject']}\n"
                   f"سؤال: {example['question']}\n"
                   f"جواب: {example['answer']}\n")
        ids = tokenizer.encode(message)
        # Each example is evaluated independently, so no inter-example leakage.
        for offset in range(0, len(ids)-1, cfg.block_size):
            x = ids[offset:offset+cfg.block_size]
            y = ids[offset+1:offset+len(x)+1]
            n = min(len(x), len(y))
            if n < 2:
                continue
            inp = torch.tensor([x[:n]], dtype=torch.long)
            target = torch.tensor([y[:n]], dtype=torch.long)
            _, loss = model(inp, target)
            total += float(loss.item()) * n
            seen += n
    if seen == 0:
        raise ValueError("The held-out set has no valid tokens")
    return total / seen
