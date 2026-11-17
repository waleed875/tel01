"""Operator-only paired training from an explicitly exported, reviewed dataset.

Never exposed as an HTTP endpoint or invoked by the AI model.
"""
import argparse
import hashlib
import json
from pathlib import Path

from engineering_domains import DOMAINS, verify_examples
from engine.worker import split_examples, serialize_training
from engine.preflight import inspect as inspect_preflight


def load_export(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("Approved export missing or exceeds 12 MiB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"version", "examples"} or data["version"] != 1:
        raise ValueError("Expected approved export version 1 with examples")
    raw = data["examples"]
    if not isinstance(raw, list) or not 12 <= len(raw) <= 10000:
        raise ValueError("Expected 12..10000 approved examples")
    examples = []
    for index, row in enumerate(raw, 1):
        if not isinstance(row, dict) or set(row) != {"subject", "question", "answer"}:
            raise ValueError("Export contains unexpected fields (identifiers or metadata not allowed)")
        subject, question, answer = row["subject"], row["question"], row["answer"]
        if subject not in DOMAINS or not isinstance(question, str) or not isinstance(answer, str):
            raise ValueError("Invalid approved example")
        if not 8 <= len(question.strip()) <= 1800 or not 8 <= len(answer.strip()) <= 5000:
            raise ValueError("Question or answer length invalid")
        examples.append({"id": index, "subject": subject, "question": question.strip(),
                         "answer": answer.strip()})
    verify_examples(examples)
    return examples


def prepare(source: Path, output: Path, *, seed: int = 42, device: str = "cuda",
            precision: str = "auto", block_size: int = 128,
            batch_size: int = 2, grad_accum_steps: int = 8,
            layers: int = 4, heads: int = 4, dim: int = 128,
            max_char_tokens: int = 512) -> dict:
    """Validate both tokenizers BEFORE creating the destination directory."""
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("Invalid seed")
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Experiment destination already exists; choose a new path")
    rows = load_export(source)
    training, heldout = split_examples(rows, seed)
    # Require coverage for a paired four-domain experiment, not merely the worker's
    # minimum of 12 examples across arbitrary subsets.
    counts = {domain: sum(row["subject"] == domain for row in training) for domain in DOMAINS}
    heldout_counts = {domain: sum(row["subject"] == domain for row in heldout) for domain in DOMAINS}
    if any(counts[k] < 1 or heldout_counts[k] < 1 for k in DOMAINS):
        raise ValueError("Each of the four domains needs >=2 approved examples for train/holdout")
    corpus = serialize_training(training)
    if len(corpus.encode("utf-8")) < 1800:
        raise ValueError("Approved training corpus too small for existing worker minimum")
    # preflight reads a path; use a local, bounded transient file and erase it.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="engineering-preflight-") as folder:
        temporary = Path(folder) / "train.txt"
        temporary.write_text(corpus, encoding="utf-8")
        checks = {}
        for codec in ("byte", "char"):
            report = inspect_preflight(
                temporary, device=device, precision=precision, tokenizer=codec,
                max_char_tokens=max_char_tokens, block_size=block_size,
                batch_size=batch_size, grad_accum_steps=grad_accum_steps,
                layers=layers, heads=heads, dim=dim)
            if not report["ready"]:
                raise ValueError(codec + " preflight blockers: " + "; ".join(report["blockers"]))
            checks[codec] = report
    # No preflight writes into experiment destination or changes checkpoints.
    output.mkdir(parents=True, exist_ok=False)
    (output / "training.txt").write_text(corpus, encoding="utf-8")
    (output / "heldout.json").write_text(
        json.dumps(heldout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "version": 1, "export_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        "training_sha256": hashlib.sha256(corpus.encode("utf-8")).hexdigest(),
        "seed": seed, "steps": None,
        "training_examples": len(training), "heldout_examples": len(heldout),
        "by_domain": {k: {"train": counts[k], "heldout": heldout_counts[k]} for k in DOMAINS},
        "settings": {"device": device, "precision": precision, "block_size": block_size,
                     "batch_size": batch_size, "grad_accum_steps": grad_accum_steps,
                     "layers": layers, "heads": heads, "dim": dim,
                     "max_char_tokens": max_char_tokens},
        "preflight": checks,
        "notice": "Local experiment only. No model intelligence or GPU fit is proven by preflight.",
    }
    (output / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8")
    return metadata


def run_pair(output: Path, *, steps: int = 100) -> dict:
    """Train two isolated fresh models, never resume or overwrite old weights."""
    if type(steps) is not int or not 1 <= steps <= 100000:
        raise ValueError("Invalid training step count")
    output = Path(output)
    manifest_file = output / "manifest.json"
    if not manifest_file.is_file():
        raise ValueError("Prepare the experiment first")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest.get("steps") is not None:
        raise ValueError("Experiment already launched; never overwrite checkpoints")
    data_path = output / "training.txt"
    if not data_path.is_file() or hashlib.sha256(data_path.read_bytes()).hexdigest() != manifest["training_sha256"]:
        raise ValueError("Experiment corpus changed since preparation")
    for codec in ("byte", "char"):
        directory = output / codec
        if directory.exists() or directory.is_symlink():
            raise FileExistsError("Existing model path: refusing to overwrite")
    settings = manifest["settings"]
    # Repeat preflight in case device environment changed after preparation.
    for codec in ("byte", "char"):
        report = inspect_preflight(
            data_path, tokenizer=codec, device=settings["device"], precision=settings["precision"],
            block_size=settings["block_size"], batch_size=settings["batch_size"],
            grad_accum_steps=settings["grad_accum_steps"], layers=settings["layers"],
            heads=settings["heads"], dim=settings["dim"],
            max_char_tokens=settings["max_char_tokens"])
        if not report["ready"]:
            raise ValueError(codec + " no longer ready: " + "; ".join(report["blockers"]))
    manifest["steps"] = steps
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
                             encoding="utf-8")
    from engine.train import train
    checkpoints = {}
    for codec in ("byte", "char"):
        target = output / codec
        train(data_path, target, steps=steps, block_size=settings["block_size"],
              batch_size=settings["batch_size"], layers=settings["layers"],
              heads=settings["heads"], dim=settings["dim"], learning_rate=3e-4,
              seed=manifest["seed"], device=settings["device"],
              grad_accum_steps=settings["grad_accum_steps"], precision=settings["precision"],
              tokenizer_mode=codec, max_char_tokens=settings["max_char_tokens"],
              metrics_file=target / "metrics.jsonl")
        checkpoint = target / "checkpoint.pt"
        if not checkpoint.is_file():
            raise RuntimeError("Missing checkpoint for " + codec)
        checkpoints[codec] = checkpoint
    return {"checkpoints": {key: str(path) for key, path in checkpoints.items()},
            "notice": "Training completed. Evaluate separately; training success is not accuracy."}


def compare(output: Path, *, seed: int | None = None) -> dict:
    output = Path(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for name in ("byte", "char"):
        if not (output / name / "checkpoint.pt").is_file():
            raise ValueError("Both model checkpoints required before comparison")
    from benchmarks.compare_tokenizers import evaluate
    result = evaluate(output / "byte" / "checkpoint.pt",
                      output / "char" / "checkpoint.pt",
                      seed=manifest["seed"] if seed is None else seed)
    (output / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("prepare", "run", "compare"))
    parser.add_argument("--approved-export", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cuda")
    parser.add_argument("--precision", choices=("fp32", "bf16", "auto"), default="auto")
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum-steps", type=int, default=8)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--max-char-tokens", type=int, default=512)
    args = parser.parse_args()
    if args.mode == "prepare":
        if args.approved_export is None:
            parser.error("--approved-export is required for prepare")
        result = prepare(args.approved_export, args.output, seed=args.seed,
                         device=args.device, precision=args.precision,
                         block_size=args.block_size, batch_size=args.batch_size,
                         grad_accum_steps=args.grad_accum_steps,
                         layers=args.layers, heads=args.heads, dim=args.dim,
                         max_char_tokens=args.max_char_tokens)
    elif args.mode == "run":
        result = run_pair(args.output, steps=args.steps)
    else:
        result = compare(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
