"""Offline exact-match benchmark of operator-created question/answer samples."""
import argparse
import json
from pathlib import Path
from .inference import LocalModel


def evaluate(checkpoint: str, benchmark: Path):
    examples = [json.loads(line) for line in benchmark.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not examples:
        raise ValueError("Empty benchmark")
    model = LocalModel(checkpoint)
    successes = 0
    for item in examples:
        result = model.answer(item["question"])
        accepted = [s.strip() for s in item["accepted_answers"]]
        match = any(s and s in result for s in accepted)
        successes += match
        print(json.dumps({"question": item["question"], "generated": result, "match": match}, ensure_ascii=False))
    print(f"Exact substring accuracy: {successes}/{len(examples)} = {successes/len(examples):.1%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="models/checkpoint.pt")
    parser.add_argument("--benchmark", type=Path, default=Path("datasets/eval.jsonl"))
    args = parser.parse_args()
    evaluate(args.checkpoint, args.benchmark)
