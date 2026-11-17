"""Train project-owned nanoGPT on local data, optionally continuing a trusted run.

Only resume operator-created checkpoints. This is not a safe arbitrary checkpoint
loader or a promise of engineering competence.
"""
import argparse
from contextlib import nullcontext
import hashlib
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


def choose_device(requested: str) -> str:
    if requested not in ("auto", "cpu", "cuda"):
        raise ValueError("Device must be one of auto, cpu, cuda")
    has_cuda = torch.cuda.is_available()
    if requested == "cuda" and not has_cuda:
        raise RuntimeError("CUDA requested but not available to PyTorch in this environment")
    return ("cuda" if has_cuda else "cpu") if requested == "auto" else requested


def _check_resume(state, config: GPTConfig, dataset_sha256: str):
    if not isinstance(state, dict) or not isinstance(state.get("config"), dict):
        raise ValueError("Invalid trusted training checkpoint")
    if state["config"] != asdict(config):
        raise ValueError("Resume checkpoint architecture differs from requested model")
    if state.get("dataset_sha256") != dataset_sha256:
        raise ValueError("Resume dataset SHA-256 differs: do not silently change training data")
    if not all(k in state for k in ("model", "optimizer", "torch_rng_state", "steps")):
        raise ValueError("Legacy checkpoint cannot resume without optimizer and RNG state")
    if type(state["steps"]) is not int or state["steps"] < 1:
        raise ValueError("Invalid previous training step count")


def select_precision(requested: str, device: str) -> str:
    """No silent downgrade of explicitly requested CUDA BF16."""
    if requested not in ("fp32", "bf16", "auto"):
        raise ValueError("Precision must be fp32, bf16 or auto")
    if requested == "fp32":
        return "fp32"
    supported = (device == "cuda" and torch.cuda.is_available()
                 and torch.cuda.is_bf16_supported())
    if requested == "bf16" and not supported:
        raise RuntimeError("BF16 requested but CUDA BF16 is unavailable")
    return "bf16" if supported else "fp32"


def train(data: Path, output: Path, steps: int, block_size: int, batch_size: int,
          layers: int, heads: int, dim: int, learning_rate: float, seed: int,
          metrics_file: Path | None = None, *, resume: Path | None = None,
          device: str = "auto", grad_accum_steps: int = 1,
          precision: str = "fp32"):
    if min(steps, block_size, batch_size, layers, heads, dim) <= 0 or dim % heads:
        raise ValueError("Invalid training configuration")
    if type(grad_accum_steps) is not int or not 1 <= grad_accum_steps <= 64:
        raise ValueError("Gradient accumulation steps must be 1..64")
    if not (0 < learning_rate <= 1) or not isinstance(seed, int) or seed < 0:
        raise ValueError("Invalid learning rate or seed")
    data = Path(data)
    output = Path(output)
    raw_bytes = data.read_bytes()
    dataset_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    # Preserve tokenizer behavior and reject invalid/empty data as before.
    tokens = load_corpus(data)
    if len(tokens) < block_size * 5:
        raise ValueError("Need at least 5 * block_size bytes for train/validation")
    cut = int(0.9 * len(tokens))
    train_tokens, val_tokens = tokens[:cut], tokens[cut:]
    if len(val_tokens) <= block_size:
        raise ValueError("Not enough validation data")

    selected_device = choose_device(device)
    selected_precision = select_precision(precision, selected_device)
    torch.manual_seed(seed)
    random.seed(seed)
    config = GPTConfig(block_size=block_size, vocab_size=256, n_layer=layers,
                       n_head=heads, n_embd=dim, dropout=0.0, bias=True)
    model = GPT(config).to(selected_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    completed_steps = 0
    if resume is not None:
        resume = Path(resume)
        if not resume.is_file():
            raise ValueError("Trusted resume checkpoint not found")
        state = torch.load(resume, map_location=selected_device, weights_only=True)
        _check_resume(state, config, dataset_sha256)
        if (state.get("seed") != seed or state.get("learning_rate") != learning_rate
                or state.get("batch_size") != batch_size
                or state.get("grad_accum_steps", 1) != grad_accum_steps
                or state.get("precision", "fp32") != selected_precision):
            raise ValueError("Resume training settings (seed, batch, accumulation, precision or learning rate) differ")
        model.load_state_dict(state["model"], strict=True)
        optimizer.load_state_dict(state["optimizer"])
        completed_steps = state["steps"]
        if state.get("saved_device") != selected_device:
            raise ValueError("Resume must use the same device type as the original run")
        torch.set_rng_state(state["torch_rng_state"].cpu())
        if selected_device == "cuda":
            cuda_state = state.get("cuda_rng_state")
            if cuda_state is None:
                raise ValueError("Resume checkpoint lacks CUDA RNG state")
            torch.cuda.set_rng_state(cuda_state.cpu())
        elif state.get("saved_device") == "cuda":
            raise ValueError("CUDA run must resume on CUDA to preserve random stream")
        if "python_rng_state" in state:
            random.setstate(state["python_rng_state"])
    print(f"Training on {selected_device} ({selected_precision}), effective batch={batch_size * grad_accum_steps}; previous steps={completed_steps}, additional steps={steps}", flush=True)

    def batch(stream):
        starts = torch.randint(0, len(stream) - block_size, (batch_size,))
        x = torch.stack([stream[i:i+block_size] for i in starts])
        y = torch.stack([stream[i+1:i+block_size+1] for i in starts])
        return x.to(selected_device), y.to(selected_device)

    output.mkdir(parents=True, exist_ok=True)
    if metrics_file:
        metrics_file = Path(metrics_file)
        metrics_file.parent.mkdir(parents=True, exist_ok=True)
        # Retain historic metrics only for in-place continuation.
        append = (resume is not None and resume.resolve() == (output / "checkpoint.pt").resolve()
                  and metrics_file.exists())
        if not append:
            metrics_file.write_text("", encoding="utf-8")
    for step in range(1, steps + 1):
        absolute_step = completed_steps + step
        model.train()
        optimizer.zero_grad(set_to_none=True)
        train_loss = 0.0
        for _ in range(grad_accum_steps):
            x, y = batch(train_tokens)
            context = (torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                       if selected_precision == "bf16" else nullcontext())
            with context:
                _, loss = model(x, y)
            train_loss += float(loss.detach())
            (loss / grad_accum_steps).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        mean_loss = train_loss / grad_accum_steps
        if step == 1 or step % 50 == 0 or step == steps:
            model.eval()
            with torch.no_grad():
                vx, vy = batch(val_tokens)
                context = (torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                           if selected_precision == "bf16" else nullcontext())
                with context:
                    _, vl = model(vx, vy)
            print(f"step={absolute_step}/{completed_steps + steps} train_loss={mean_loss:.4f} val_loss={vl.item():.4f}", flush=True)
            if metrics_file:
                with metrics_file.open("a", encoding="utf-8") as fd:
                    fd.write(json.dumps({"step": absolute_step, "train_loss": mean_loss,
                                         "validation_loss": float(vl.item())}) + "\n")
            model.train()

    checkpoint = {
        "model": model.cpu().state_dict(), "config": asdict(config),
        "optimizer": optimizer.state_dict(), "steps": completed_steps + steps,
        "seed": seed, "dataset": str(data), "dataset_sha256": dataset_sha256,
        "learning_rate": learning_rate, "batch_size": batch_size, "saved_device": selected_device,
        "grad_accum_steps": grad_accum_steps, "precision": selected_precision,
        "torch_rng_state": torch.get_rng_state(), "python_rng_state": random.getstate(),
        "cuda_rng_state": torch.cuda.get_rng_state().cpu() if selected_device == "cuda" else None,
    }
    temp = output / "checkpoint.tmp"
    torch.save(checkpoint, temp)
    temp.replace(output / "checkpoint.pt")
    print(f"Saved {output / 'checkpoint.pt'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("datasets/engineering.txt"))
    parser.add_argument("--output", type=Path, default=Path("models"))
    parser.add_argument("--steps", type=int, default=300, help="Additional training steps when resuming")
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--metrics-file", type=Path, default=None)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--precision", choices=("fp32", "bf16", "auto"), default="fp32")
    parser.add_argument("--grad-accum-steps", type=int, default=1)
    parser.add_argument("--resume", type=Path, help="Operator-trusted checkpoint from same architecture and data")
    args = parser.parse_args()
    train(args.data, args.output, args.steps, args.block_size, args.batch_size,
          args.layers, args.heads, args.dim, args.learning_rate, args.seed, args.metrics_file,
          resume=args.resume, device=args.device,
          grad_accum_steps=args.grad_accum_steps, precision=args.precision)
