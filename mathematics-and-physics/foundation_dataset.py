"""Validated, original four-domain starter pack; never automatically approve it."""
import json
from collections import Counter
from pathlib import Path
from engineering_domains import DOMAINS, normalize_text, verify_examples, fingerprint
from benchmarks.evaluate_domains import load_benchmark, verify_no_train_leakage
from benchmarks.evaluate_tool_proposals import load_suite

PACK = Path(__file__).resolve().parent / "datasets" / "four_domain_starter.json"
REQUIRED = {"id", "subject", "skill", "question", "answer"}


def validate_starter(data: dict) -> list[dict]:
    if not isinstance(data, dict) or set(data) != {"version", "notice", "license", "examples"}:
        raise ValueError("Malformed starter pack")
    if data["version"] != 1 or data["license"] != "CC0-1.0" or not isinstance(data["notice"], str):
        raise ValueError("Unsupported starter pack")
    examples = data["examples"]
    if not isinstance(examples, list) or len(examples) != 24:
        raise ValueError("Starter must contain exactly 24 examples")
    ids, clean = set(), []
    for row in examples:
        if not isinstance(row, dict) or set(row) != REQUIRED:
            raise ValueError("Malformed starter example")
        if not isinstance(row["id"], str) or not row["id"].startswith("starter_") or row["id"] in ids:
            raise ValueError("Invalid starter ID")
        ids.add(row["id"])
        domain = DOMAINS.get(row["subject"])
        if domain is None or row["skill"] not in domain["skills"]:
            raise ValueError("Invalid domain skill")
        question, answer = row["question"], row["answer"]
        if (not isinstance(question, str) or not isinstance(answer, str)
                or not 8 <= len(question.strip()) <= 1800
                or not 8 <= len(answer.strip()) <= 5000
                or not normalize_text(question) or not normalize_text(answer)):
            raise ValueError("Invalid question/answer")
        clean.append({"subject": row["subject"], "question": question.strip(),
                      "answer": answer.strip()})
    verify_examples(clean)
    counts = Counter(x["subject"] for x in clean)
    if any(counts[domain] != 6 for domain in DOMAINS):
        raise ValueError("Starter needs six examples in each discipline")
    verify_no_train_leakage(load_benchmark()["tasks"], clean)
    verify_no_train_leakage(load_suite()["tasks"], clean)
    return clean


def load_starter() -> list[dict]:
    return validate_starter(json.loads(PACK.read_text(encoding="utf-8")))
