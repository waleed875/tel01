"""Read-only preflight for operator-owned local engineering-GPT training.

The checks never instantiate a model, write weights, or run training.
Memory estimates exclude activations and CUDA allocator overhead.
"""
import argparse
import hashlib
import json
from pathlib import Path

import torch

from .tokenizer import ByteTokenizer, build_character_tokenizer
from .train import choose_device, select_precision


def inspect(data: Path, *, device: str = "auto", precision: str = "fp32",
            tokenizer: str = "byte", max_char_tokens: int = 512,
            block_size: int = 128, batch_size: int = 8,
            grad_accum_steps: int = 1, layers: int = 4,
            heads: int = 4, dim: int = 128) -> dict:
    """Report independent blocking issues without creating any checkpoints."""
    errors = []
    if (type(block_size) is not int or type(batch_size) is not int or
            type(grad_accum_steps) is not int or type(layers) is not int or
            type(heads) is not int or type(dim) is not int or
            not 1 <= block_size <= 16384 or not 1 <= batch_size <= 4096 or
            not 1 <= grad_accum_steps <= 64 or not 1 <= layers <= 128 or
            not 1 <= heads <= 128 or not 1 <= dim <= 8192 or dim % heads):
        raise ValueError("Invalid architecture, batch or accumulation configuration")
    if tokenizer not in ("byte", "char") or type(max_char_tokens) is not int or not 1 <= max_char_tokens <= 2048:
        raise ValueError("Invalid tokenizer configuration")
    path = Path(data)
    if not path.is_file():
        raise ValueError("Training corpus file not found")
    raw = path.read_bytes()
    if len(raw) > 128 * 1024 * 1024:
        raise ValueError("Preflight corpus exceeds 128 MiB safety bound")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Training corpus must be valid UTF-8") from exc
    if not source.strip():
        raise ValueError("Training corpus is empty")

    if tokenizer == "byte":
        tokens = ByteTokenizer().encode(source)
        cut = int(0.9 * len(tokens))
        train_count, val_count, vocab = cut, len(tokens) - cut, 256
    else:
        cut = int(0.9 * len(source))
        codec = build_character_tokenizer(source[:cut], max_char_tokens)
        train_count = len(codec.encode(source[:cut]))
        val_count = len(codec.encode(source[cut:]))
        vocab = codec.vocab_size

    if train_count + val_count < block_size * 5:
        errors.append("Insufficient tokens: trainer requires total >= 5 * block_size")
    if val_count <= block_size:
        errors.append("Validation split must exceed block_size")
    if train_count <= block_size:
        errors.append("Training split must exceed block_size")

    try:
        selected_device = choose_device(device)
    except RuntimeError as exc:
        errors.append(str(exc))
        selected_device = "unavailable"
    try:
        resolved_precision = select_precision(precision, selected_device)
    except RuntimeError as exc:
        errors.append(str(exc))
        resolved_precision = "unavailable"

    cuda = torch.cuda.is_available()
    gpu = None
    if cuda:
        try:
            props = torch.cuda.get_device_properties(0)
            gpu = {"name": props.name, "total_vram_bytes": int(props.total_memory),
                   "bf16_supported": bool(torch.cuda.is_bf16_supported())}
        except (RuntimeError, AssertionError) as exc:
            errors.append("CUDA device properties unavailable: " + type(exc).__name__)
    # Analytical parameter count for this project's tied-embedding nanoGPT.
    # Each block: attention (4D² + 4D) + MLP (8D² + 5D)
    # + two layer norms (4D). + final LN (2D), tied WTE (V*D), WPE (T*D).
    params = (layers * (12 * dim * dim + 13 * dim)
              + (vocab + block_size) * dim + 2 * dim)
    # Upper-bound heuristic for trainable parameters, gradients, two AdamW
    # moments and checkpoint/temporary states; NOT peak resident GPU memory.
    base_bytes = params * 16
    return {
        "ready": not errors, "blockers": errors,
        "data": {"sha256": hashlib.sha256(raw).hexdigest(),
                 "size_bytes": len(raw), "tokenizer": tokenizer,
                 "train_tokens": train_count, "validation_tokens": val_count,
                 "total_tokens": train_count + val_count,
                 "utf8_bytes_per_token": round(len(raw) / (train_count + val_count), 4),
                 "vocab_size": vocab},
        "training": {"block_size": block_size, "microbatch_size": batch_size,
                     "gradient_accumulation": grad_accum_steps,
                     "effective_batch_size": batch_size * grad_accum_steps,
                     "layers": layers, "heads": heads, "dim": dim},
        "runtime": {"requested_device": device, "selected_device": selected_device,
                    "requested_precision": precision, "selected_precision": resolved_precision,
                    "torch_version": torch.__version__, "cuda_runtime": torch.version.cuda,
                    "cuda_available": cuda, "gpu": gpu},
        "memory_estimate": {
            "approx_trainable_parameters": params,
            "approx_parameter_gradient_adam_bytes": base_bytes,
            "note": "Not peak GPU memory: excludes activations, attention buffers, CUDA runtime, optimizer implementation and allocator overhead; measure on hardware.",
        },
        "notice": "Preflight is configuration checking, not a measured VRAM fit or model-quality test.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("datasets/engineering.txt"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--precision", choices=("fp32", "bf16", "auto"), default="fp32")
    parser.add_argument("--tokenizer", choices=("byte", "char"), default="byte")
    parser.add_argument("--max-char-tokens", type=int, default=512)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--grad-accum-steps", type=int, default=1)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.data, device=args.device, precision=args.precision,
                         tokenizer=args.tokenizer, max_char_tokens=args.max_char_tokens,
                         block_size=args.block_size, batch_size=args.batch_size,
                         grad_accum_steps=args.grad_accum_steps, layers=args.layers,
                         heads=args.heads, dim=args.dim)
    except (ValueError, OSError) as exc:
        result = {"ready": False, "blockers": [str(exc)]}
    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
