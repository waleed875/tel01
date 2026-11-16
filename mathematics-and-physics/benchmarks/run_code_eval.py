"""Operator-only coding evaluation. Candidate code executes ONLY inside Docker.

This command is intentionally not exposed as a web API. It is run by the
trusted machine owner with Docker installed. Do not mount docker.sock into web.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


BASE = Path(__file__).resolve().parent
DATASET = BASE / "coding_cases.json"
IMAGE = "python:3.12-alpine"
RUN_SECONDS = 12


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tasks(path: Path = DATASET):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1 or not isinstance(raw.get("tasks"), list):
        raise ValueError("Unsupported coding benchmark version")
    ids = set()
    for task in raw["tasks"]:
        if (not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", task["id"])
                or task["id"] in ids or
                not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", task["function"])
                or not 1 <= len(task.get("cases", [])) <= 100):
            raise ValueError("Invalid benchmark task")
        ids.add(task["id"])
    return raw


def extract_source(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.S | re.I)
    return match.group(1).strip() + "\n" if match else text + "\n"


def _sandbox(task: dict, source: str, *, image: str = IMAGE) -> dict:
    if len(source.encode("utf-8")) > 16384:
        return {"passed": 0, "total": len(task["cases"]), "outcomes": [],
                "error": "Source too long"}
    with tempfile.TemporaryDirectory(prefix="lab-code-eval-") as name:
        folder = Path(name)
        task_data = {key: task[key] for key in ("id", "function", "cases")}
        (folder / "candidate.py").write_text(source, encoding="utf-8")
        (folder / "task.json").write_text(json.dumps(task_data), encoding="utf-8")
        (folder / "sandbox_worker.py").write_bytes(
            (BASE / "sandbox_worker.py").read_bytes())
        # Container runs as nobody; files are readable but not writable.
        for item in folder.iterdir():
            item.chmod(0o444)
        folder.chmod(0o555)
        command = [
            "docker", "run", "--rm", "--pull=never",
            "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=32", "--memory=128m", "--memory-swap=128m",
            "--cpus=0.5", "--user=65534:65534",
            "--ulimit=nofile=32:32", "--tmpfs=/tmp:rw,nosuid,noexec,size=8m",
            "--mount", "type=bind,src=" + str(folder.resolve()) + ",dst=/work,readonly",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "--workdir=/work", image, "python", "-I", "/work/sandbox_worker.py",
        ]
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                command, text=True, capture_output=True, timeout=RUN_SECONDS,
                check=False)
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": len(task["cases"]), "outcomes": [],
                    "error": "Sandbox timeout", "elapsed_s": RUN_SECONDS}
        except FileNotFoundError as exc:
            raise RuntimeError("Docker not installed on the trusted evaluator host") from exc
        elapsed = round(time.perf_counter() - start, 3)
        if completed.returncode != 0:
            return {"passed": 0, "total": len(task["cases"]), "outcomes": [],
                    "error": "Container execution failed", "elapsed_s": elapsed}
        try:
            result = json.loads(completed.stdout)
        except (ValueError, TypeError):
            raise RuntimeError("Invalid sandbox result") from None
        if (not isinstance(result.get("passed"), int)
                or result.get("total") != len(task["cases"])):
            raise RuntimeError("Malformed sandbox case counters")
        result["elapsed_s"] = elapsed
        return result


def evaluate(*, mode: str, checkpoint: Path | None = None,
             candidate_dir: Path | None = None, dataset: Path = DATASET):
    if mode not in ("reference", "candidates", "checkpoint"):
        raise ValueError("Unknown evaluation mode")
    data = load_tasks(dataset)
    model = None
    model_sha = None
    if mode == "checkpoint":
        if checkpoint is None or not checkpoint.is_file():
            raise ValueError("A locally trained checkpoint path is required")
        from engine.inference import LocalModel
        model_sha = digest(checkpoint)
        model = LocalModel(str(checkpoint), max_tokens=512)
    if mode == "candidates" and (candidate_dir is None or not candidate_dir.is_dir()):
        raise ValueError("Candidate directory is required")
    results = []
    for task in data["tasks"]:
        if mode == "reference":
            source = task["reference"]
        elif mode == "candidates":
            candidate = candidate_dir / (task["id"] + ".py")
            source = candidate.read_text(encoding="utf-8") if candidate.is_file() else ""
        else:
            source = extract_source(model.answer(task["prompt"]))
        output = _sandbox(task, source)
        results.append({"task": task["id"], "passed": output["passed"],
                        "total": output["total"], "all_pass": output["passed"] == output["total"],
                        "elapsed_s": output.get("elapsed_s"),
                        "error": output.get("error")})
    passed = sum(r["passed"] for r in results)
    total = sum(r["total"] for r in results)
    return {
        "benchmark_version": data["version"], "benchmark_sha256": digest(dataset),
        "mode": mode, "checkpoint_sha256": model_sha, "tasks": results,
        "passed_cases": passed, "total_cases": total,
        "case_pass_rate": round(passed / total, 4) if total else None,
        "solved_tasks": sum(r["all_pass"] for r in results),
        "total_tasks": len(results),
        "notice": ("Reference is a harness self-check, NOT a model score"
                   if mode == "reference" else
                   "Small public functional fixture, not proof of general software engineering ability"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["reference", "candidates", "checkpoint"], required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(mode=args.mode, checkpoint=args.checkpoint,
                      candidate_dir=args.candidate_dir)
    formatted = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(formatted + "\n", encoding="utf-8")
    print(formatted)


if __name__ == "__main__":
    main()
