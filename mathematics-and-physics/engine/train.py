"""Train nanoGPT architecture from random initialization on local text files.

Run from project root: python -m engine.train --data datasets/engineering.txt
Checkpoints are untrusted pickle files; only load checkpoints you created.
"""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
import random

import torch

from .model import GPT, GPTConfig
from .tokenizer import ByteTokenizer


def load_corpus(path: Path):
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("Training corpus is empty")
    return torch.tensor(ByteTokenizer().encode(raw), dtype=torch.long)


def train(data: Path, output: Path, steps: int, block_size: int, batch_size: int,
          layers: int, heads: int, dim: int, learning_rate: float, seed: int,
          metrics_file: Path | None = None):
    if min(steps, block_size, batch_size, layers, heads, dim) <= 0 or dim % heads:
        raise ValueError("Invalid training configuration")
    torch.manual_seed(seed)
    random.seed(seed)
    tokens = load_corpus(data)
    if len(tokens) < block_size * 5:
        raise ValueError("Need at least 5 * block_size bytes for train/validation")
    cut = int(0.9 * len(tokens))
    train_tokens, val_tokens = tokens[:cut], tokens[cut:]
    if len(val_tokens) <= block_size:
        raise ValueError("Not enough validation data")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    config = GPTConfig(block_size=block_size, vocab_size=256, n_layer=layers,
                       n_head=heads, n_embd=dim, dropout=0.0, bias=True)
    model = GPT(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)

    def batch(stream):
        starts = torch.randint(0, len(stream) - block_size, (batch_size,))
        x = torch.stack([stream[i:i+block_size] for i in starts])
        y = torch.stack([stream[i+1:i+block_size+1] for i in starts])
        return x.to(device), y.to(device)

    output.mkdir(parents=True, exist_ok=True)
    if metrics_file:
        metrics_file.parent.mkdir(parents=True, exist_ok=True)
        metrics_file.write_text("", encoding="utf-8")
    for step in range(1, steps + 1):
        model.train()
        x, y = batch(train_tokens)
        _, loss = model(x, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        if step == 1 or step % 50 == 0 or step == steps:
            model.eval()
            with torch.no_grad():
                vx, vy = batch(val_tokens)
                _, vl = model(vx, vy)
            print(f"step={step}/{steps} train_loss={loss.item():.4f} val_loss={vl.item():.4f}", flush=True)
            if metrics_file:
                with metrics_file.open("a", encoding="utf-8") as fd:
                    fd.write(json.dumps({"step":step,"train_loss":float(loss.item()),
                                         "validation_loss":float(vl.item())})+"\n")
            model.train()

    checkpoint = {"model": model.cpu().state_dict(), "config": asdict(config),
                  "steps": steps, "seed": seed, "dataset": str(data)}
    temp = output / "checkpoint.tmp"
    torch.save(checkpoint, temp)
    temp.replace(output / "checkpoint.pt")
    print(f"Saved {output / 'checkpoint.pt'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("datasets/engineering.txt"))
    parser.add_argument("--output", type=Path, default=Path("models"))
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--metrics-file", type=Path, default=None)
    args = parser.parse_args()
    train(args.data, args.output, args.steps, args.block_size, args.batch_size,
          args.layers, args.heads, args.dim, args.learning_rate, args.seed, args.metrics_file)
