"""Offline paired evaluation of *already trained* byte vs character checkpoints.

No test answers are used as prompts and no suggested tool is ever executed.
Checkpoints are trusted local operator artifacts, never user uploads.
"""
import argparse
import hashlib
import json
from pathlib import Path

import torch

from engineering_domains import DOMAINS, subject_prompt
from tutor import build_engineering_prompt
from engine.inference import LocalModel
from engine.tokenizer import tokenizer_from_spec
from benchmarks.evaluate_domains import DATASET as DOMAIN_DATASET
from benchmarks.evaluate_domains import load_benchmark, grade as domain_grade
from benchmarks.evaluate_tool_proposals import DATASET as TOOL_DATASET
from benchmarks.evaluate_tool_proposals import load_suite, grade as tool_grade

SUITES = ("domains", "proposals")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkpoint_metadata(path: Path, kind: str) -> dict:
    if not path.is_file():
        raise ValueError(f"Trusted local {kind} checkpoint not found")
    # Keep checkpoint loading explicit: never load untrusted pickle files.
    state = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(state, dict) or not isinstance(state.get("config"), dict):
        raise ValueError("Malformed checkpoint configuration")
    config = state["config"]
    for field in ("vocab_size", "block_size", "n_layer", "n_head", "n_embd"):
        if type(config.get(field)) is not int or config[field] < 1:
            raise ValueError("Malformed checkpoint architecture")
    token = tokenizer_from_spec(state.get("tokenizer_spec"), config["vocab_size"])
    actual_kind = "byte" if token.vocab_size == 256 and state.get("tokenizer_spec") is None else "char"
    if actual_kind != kind:
        raise ValueError(f"Expected {kind} checkpoint, got {actual_kind}")
    return {
        "sha256": sha256(path), "kind": kind,
        "tokenizer_vocab_size": token.vocab_size,
        "block_size": config["block_size"],
        "model_config": config, "dataset_sha256": state.get("dataset_sha256"),
        "steps": state.get("steps"),
    }


def paired_counts(left: list[dict], right: list[dict]) -> dict:
    if len(left) != len(right):
        raise ValueError("Paired task count differs")
    outcomes = {"both_pass": 0, "byte_only": 0, "char_only": 0, "both_fail": 0}
    for a, z in zip(left, right):
        if a["id"] != z["id"] or a["subject"] != z["subject"]:
            raise ValueError("Paired task ordering differs")
        key = ("both_pass" if a["passed"] and z["passed"] else
               "byte_only" if a["passed"] else "char_only" if z["passed"] else
               "both_fail")
        outcomes[key] += 1
    return outcomes


def _score_suite(suite: str, checkpoint: Path, seed: int, max_tokens: int,
                 domain_tasks: list[dict], tool_tasks: list[dict]) -> list[dict]:
    model = LocalModel(str(checkpoint), max_tokens=max_tokens)
    model.load()
    rows = []
    tasks = domain_tasks if suite == "domains" else tool_tasks
    for index, task in enumerate(tasks):
        prompt = (subject_prompt(task["subject"], "تقييم مستقل", task["question"])
                  if suite == "domains" else
                  build_engineering_prompt("university", task["subject"], task["question"]))
        # Measure the exact pre-generation prompt that LocalModel actually encodes.
        wrapped = "سؤال: " + prompt.strip() + "\nجواب:"
        ids = model.tokenizer.encode(wrapped)
        usable = min(len(ids), model.model.config.block_size)
        # Same seed for the same item, irrespective of which model is evaluated.
        torch.manual_seed(seed + index + (10000 if suite == "proposals" else 0))
        response = model.answer(prompt)
        checked = (domain_grade(task, response) if suite == "domains" else tool_grade(task, response))
        rows.append({
            "id": task["id"], "subject": task["subject"], "passed": bool(checked["passed"]),
            "input_tokens": len(ids), "used_context_tokens": usable,
            "truncated_tokens": len(ids) - usable,
            **({"false_proposal": bool(checked["false_proposal"]),
                "operation_correct": bool(checked["operation_correct"]),
                "inputs_correct": bool(checked["inputs_correct"])}
               if suite == "proposals" else {}),
        })
    return rows


def _by_domain(left: list[dict], right: list[dict]) -> dict:
    output = {}
    for domain in DOMAINS:
        a = [item for item in left if item["subject"] == domain]
        z = [item for item in right if item["subject"] == domain]
        output[domain] = {
            "total": len(a),
            "byte_passed": sum(t["passed"] for t in a),
            "char_passed": sum(t["passed"] for t in z),
            **paired_counts(a, z),
        }
    return output


def evaluate(byte_checkpoint: Path, char_checkpoint: Path, *, seed: int = 42) -> dict:
    if type(seed) is not int or not 0 <= seed <= 2147470000:
        raise ValueError("Seed is outside bounded range")
    byte_checkpoint, char_checkpoint = Path(byte_checkpoint), Path(char_checkpoint)
    if byte_checkpoint.resolve() == char_checkpoint.resolve():
        raise ValueError("Comparison needs two distinct checkpoints")
    left_meta = checkpoint_metadata(byte_checkpoint, "byte")
    right_meta = checkpoint_metadata(char_checkpoint, "char")
    domain_tasks = load_benchmark()["tasks"]
    tool_tasks = load_suite()["tasks"]
    suites = {}
    for name, budget, tasks in (("domains", 120, domain_tasks), ("proposals", 180, tool_tasks)):
        a = _score_suite(name, byte_checkpoint, seed, budget, domain_tasks, tool_tasks)
        z = _score_suite(name, char_checkpoint, seed, budget, domain_tasks, tool_tasks)
        suites[name] = {
            "total": len(tasks), "generation_budget_tokens": budget,
            "byte_passed": sum(x["passed"] for x in a),
            "char_passed": sum(x["passed"] for x in z),
            "paired": paired_counts(a, z), "per_domain": _by_domain(a, z),
            "byte_context": {
                "input_tokens": sum(x["input_tokens"] for x in a),
                "truncated_tokens": sum(x["truncated_tokens"] for x in a),
                "truncated_prompts": sum(bool(x["truncated_tokens"]) for x in a),
            },
            "char_context": {
                "input_tokens": sum(x["input_tokens"] for x in z),
                "truncated_tokens": sum(x["truncated_tokens"] for x in z),
                "truncated_prompts": sum(bool(x["truncated_tokens"]) for x in z),
            },
            **({"byte_false_proposals": sum(x["false_proposal"] for x in a),
                "char_false_proposals": sum(x["false_proposal"] for x in z)}
               if name == "proposals" else {}),
            "tasks": [{"id": a[i]["id"], "subject": a[i]["subject"],
                       "byte_passed": a[i]["passed"], "char_passed": z[i]["passed"],
                       "byte_input_tokens": a[i]["input_tokens"],
                       "char_input_tokens": z[i]["input_tokens"],
                       "byte_truncated_tokens": a[i]["truncated_tokens"],
                       "char_truncated_tokens": z[i]["truncated_tokens"]}
                      for i in range(len(a))],
        }
    differences = []
    for key in ("dataset_sha256", "steps", "block_size"):
        if left_meta[key] != right_meta[key]:
            differences.append(key)
    for key in ("n_layer", "n_head", "n_embd"):
        if left_meta["model_config"][key] != right_meta["model_config"][key]:
            differences.append(key)
    if left_meta["dataset_sha256"] is None or right_meta["dataset_sha256"] is None:
        differences.append("unknown_training_data")
    return {
        "version": 1, "seed": seed,
        "checkpoints": {"byte": left_meta, "char": right_meta},
        "benchmarks_sha256": {"domains": sha256(DOMAIN_DATASET),
                              "proposals": sha256(TOOL_DATASET)},
        "confounds": differences, "suites": suites,
        "notice": ("Paired public smoke evaluation only: differences cannot be attributed "
                   "to tokenizer alone, even when metadata matches. No real checkpoints "
                   "were downloaded or trained by the evaluator; inspect training-data "
                   "leakage and use independent held-out questions."),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byte-checkpoint", type=Path, required=True)
    parser.add_argument("--char-checkpoint", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.byte_checkpoint, args.char_checkpoint, seed=args.seed)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
