"""Independent public four-domain evaluation, separate from training examples.

This is a small smoke benchmark, not evidence of expert-level competence.
Answers are NEVER sent to the checkpoint, only the question and subject.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from engineering_domains import DOMAINS, normalize_text, fingerprint, subject_prompt

DATASET = Path(__file__).with_name("four_domains.json")
NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?![\w.])")


def load_benchmark(path: Path = DATASET) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("tasks"), list):
        raise ValueError("Unsupported four-domain benchmark")
    counts = {domain: 0 for domain in DOMAINS}
    ids, questions = set(), set()
    for case in data["tasks"]:
        subject, name, question = case["subject"], case["id"], case["question"]
        if subject not in DOMAINS or not re.fullmatch(r"[a-z][a-z0-9_]{2,50}", name):
            raise ValueError("Invalid domain or task ID")
        key = fingerprint(subject, question)
        if name in ids or key in questions:
            raise ValueError("Duplicate benchmark task")
        ids.add(name)
        questions.add(key)
        counts[subject] += 1
        rubric = case.get("checks", {})
        if ("numeric" in rubric) == ("terms" in rubric):
            raise ValueError("Each case needs either a numeric or term-based rubric")
        if "terms" in rubric and not rubric["terms"]:
            raise ValueError("Term rubric has no acceptable terms")
    if not all(n >= 3 for n in counts.values()):
        raise ValueError("At least three tasks in every domain are required")
    return data


def grade(case: dict, answer: str) -> dict:
    if not isinstance(answer, str):
        return {"passed": False, "value": False, "unit": False}
    rubric = case["checks"]
    text = unicodedata.normalize("NFKC", answer)
    if "numeric" in rubric:
        wanted = float(rubric["numeric"])
        numbers = [float(match.group(0)) for match in NUMBER.finditer(text)]
        has_value = any(abs(number - wanted) <= 1e-9 * max(1, abs(wanted))
                        for number in numbers)
    else:
        value = normalize_text(text)
        has_value = any(normalize_text(term) in value for term in rubric["terms"])
    if rubric.get("units"):
        # Unit detection is a simple diagnostic, not full dimensional analysis.
        has_unit = any(re.search(r"(?<!\w)" + re.escape(unit.casefold()) + r"(?!\w)",
                                 text.casefold()) is not None for unit in rubric["units"])
    else:
        has_unit = True
    return {"passed": bool(has_value and has_unit),
            "value": bool(has_value), "unit": bool(has_unit)}


def verify_no_train_leakage(tasks: list[dict], training_examples: list[dict]):
    test_keys = {fingerprint(task["subject"], task["question"]) for task in tasks}
    for example in training_examples:
        if fingerprint(example["subject"], example["question"]) in test_keys:
            raise ValueError("Evaluation question found in training corpus")


def evaluate(mode: str, checkpoint: Path | None = None,
             benchmark: Path = DATASET) -> dict:
    if mode not in ("reference", "checkpoint"):
        raise ValueError("Unknown evaluation mode")
    suite = load_benchmark(benchmark)
    model = None
    checkpoint_sha = None
    if mode == "checkpoint":
        if checkpoint is None or not checkpoint.is_file():
            raise ValueError("Own trusted local checkpoint is required")
        from engine.inference import LocalModel
        model = LocalModel(str(checkpoint), max_tokens=120)
        checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    items = []
    for task in suite["tasks"]:
        # No rubric/answer is sent to the model.
        prompt = subject_prompt(task["subject"], "تقييم مستقل", task["question"])
        answer = task["answer"] if mode == "reference" else model.answer(prompt)
        item = grade(task, answer)
        items.append({"id": task["id"], "subject": task["subject"],
                      "passed": item["passed"], "value_passed": item["value"],
                      "unit_passed": item["unit"]})
    per_domain = {
        key: {"passed": sum(i["passed"] for i in items if i["subject"] == key),
              "total": sum(i["subject"] == key for i in items)}
        for key in DOMAINS
    }
    return {
        "mode": mode, "suite_sha256": hashlib.sha256(benchmark.read_bytes()).hexdigest(),
        "checkpoint_sha256": checkpoint_sha, "domains": per_domain, "tasks": items,
        "passed": sum(item["passed"] for item in items), "total": len(items),
        "notice": ("النتيجة المرجعية تختبر أداة التقييم فقط، ولا تقيس ذكاء النموذج."
                   if mode == "reference" else
                   "مقياس تجريبي علني وصغير؛ يجب اختبار النموذج على مهام مستقلة أكبر.")
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("reference", "checkpoint"), required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.mode, checkpoint=args.checkpoint)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
