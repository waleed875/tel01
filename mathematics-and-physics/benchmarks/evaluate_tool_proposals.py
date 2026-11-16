"""Offline evaluation of locally trained model tool *proposals*, never execution.

Run from mathematics-and-physics: python -m benchmarks.evaluate_tool_proposals
"""
import argparse
import hashlib
import json
from pathlib import Path

from engineering_domains import DOMAINS, fingerprint
from engineering_tool_proposals import propose
from tutor import build_engineering_prompt

DATASET = Path(__file__).with_name("tool_proposals.json")


def load_suite(path=DATASET):
    suite = json.loads(Path(path).read_text(encoding="utf-8"))
    if suite.get("version") != 1 or not isinstance(suite.get("tasks"), list):
        raise ValueError("Unsupported proposal benchmark version")
    seen_ids, seen_questions = set(), set()
    counts = {domain: {"positive": 0, "negative": 0} for domain in DOMAINS}
    for case in suite["tasks"]:
        if not isinstance(case, dict) or set(case) != {"id", "subject", "question", "expected"}:
            raise ValueError("Unexpected task fields")
        subject, question, name = case["subject"], case["question"], case["id"]
        if subject not in DOMAINS or not isinstance(name, str) or not name.isidentifier():
            raise ValueError("Invalid domain or task ID")
        key = fingerprint(subject, question)
        if name in seen_ids or key in seen_questions:
            raise ValueError("Duplicate benchmark task")
        seen_ids.add(name)
        seen_questions.add(key)
        expected = case["expected"]
        if expected is not None:
            if not isinstance(expected, dict) or set(expected) != {"operation", "inputs"}:
                raise ValueError("Malformed expected proposal")
            # No calculator runs here: the validation-only proposal parser is used.
            proposed = propose(format_reference(expected), user_id=0)
            if proposed is None or proposed["domain"] != subject:
                raise ValueError("Invalid reference proposal or mismatched domain")
        counts[subject]["positive" if expected is not None else "negative"] += 1
    if not all(item["positive"] >= 2 and item["negative"] >= 1 for item in counts.values()):
        raise ValueError("Require two positive and one no-tool task per domain")
    return suite


def format_reference(expected):
    if expected is None:
        return "لا توجد عملية متاحة دون معلومات كافية."
    return "```engineering-tool\n" + json.dumps(expected, ensure_ascii=False, sort_keys=True) + "\n```"


def grade(case, model_output):
    expected = case["expected"]
    proposal = propose(model_output, user_id=0)
    correct_domain = proposal is not None and proposal["domain"] == case["subject"]
    valid = correct_domain
    if expected is None:
        return {"passed": proposal is None, "protocol_valid": proposal is not None,
                "operation_correct": False, "inputs_correct": False,
                "abstained": proposal is None, "false_proposal": proposal is not None}
    operation_correct = correct_domain and proposal["operation"] == expected["operation"]
    inputs_correct = bool(operation_correct and proposal["inputs"] == expected["inputs"])
    return {"passed": inputs_correct, "protocol_valid": valid,
            "operation_correct": bool(operation_correct), "inputs_correct": inputs_correct,
            "abstained": proposal is None, "false_proposal": False}


def evaluate(mode, checkpoint=None, benchmark=DATASET):
    if mode not in ("reference", "checkpoint"):
        raise ValueError("Unsupported evaluation mode")
    benchmark = Path(benchmark)
    suite = load_suite(benchmark)
    model = None
    checkpoint_sha = None
    if mode == "checkpoint":
        path = Path(checkpoint) if checkpoint is not None else None
        if path is None or not path.is_file():
            raise ValueError("Trusted locally trained checkpoint path is required")
        from engine.inference import LocalModel
        model = LocalModel(str(path), max_tokens=180)
        checkpoint_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    tasks = []
    for case in suite["tasks"]:
        output = (format_reference(case["expected"]) if mode == "reference"
                  else model.answer(build_engineering_prompt("university", case["subject"], case["question"])))
        result = grade(case, output)
        tasks.append({"id": case["id"], "subject": case["subject"],
                      "expects_tool": case["expected"] is not None, **result})
    domains = {}
    for domain in DOMAINS:
        selected = [item for item in tasks if item["subject"] == domain]
        domains[domain] = {"total": len(selected), "passed": sum(t["passed"] for t in selected),
                           "operation_correct": sum(t["operation_correct"] for t in selected),
                           "inputs_correct": sum(t["inputs_correct"] for t in selected),
                           "false_proposals": sum(t["false_proposal"] for t in selected)}
    positives = [t for t in tasks if t["expects_tool"]]
    negatives = [t for t in tasks if not t["expects_tool"]]
    return {
        "mode": mode, "suite_sha256": hashlib.sha256(benchmark.read_bytes()).hexdigest(),
        "checkpoint_sha256": checkpoint_sha, "total": len(tasks),
        "passed": sum(t["passed"] for t in tasks),
        "protocol_valid": sum(t["protocol_valid"] for t in positives),
        "operation_correct": sum(t["operation_correct"] for t in positives),
        "inputs_correct": sum(t["inputs_correct"] for t in positives),
        "positive_total": len(positives),
        "correct_abstentions": sum(t["abstained"] for t in negatives),
        "false_proposals": sum(t["false_proposal"] for t in negatives),
        "negative_total": len(negatives), "domains": domains, "tasks": tasks,
        "notice": ("مرجع لا يقيس جودة الذكاء العصبي؛ يتحقق من عمل المقيم فقط."
                   if mode == "reference" else
                   "نتائج نموذج محلي تجريبي؛ يتطلب تقييمًا مستقلًا أكبر واختبارًا عمليًا."),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("reference", "checkpoint"))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--benchmark", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.mode, checkpoint=args.checkpoint, benchmark=args.benchmark)
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
