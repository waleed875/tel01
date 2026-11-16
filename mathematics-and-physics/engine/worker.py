"""Single-host, bounded training worker.

This runs in a separate Docker service; the web process never executes training
commands. It accepts only a validated, immutable snapshot of APPROVED examples.
"""
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

from storage import Storage
from .eval_holdout import evaluate_heldout

MODEL_ROOT = Path(os.environ.get("MODEL_ROOT", "/app/models"))
POLL_SECONDS = 3


def remove_owned_model_runs(job_ids: list[int], root: Path = MODEL_ROOT):
    """Never follow symlinks or accept arbitrary paths from untrusted records."""
    if not isinstance(job_ids, list):
        raise ValueError("Invalid cleanup job list")
    root = root.resolve(strict=True)
    for raw in job_ids:
        if type(raw) is not int or raw < 1 or raw > 9223372036854775807:
            raise ValueError("Invalid cleanup job identifier")
        target = root / f"run-{raw}"
        if target.is_symlink():
            raise ValueError("Refusing to follow model-directory symlink")
        if not target.exists():
            continue
        if target.resolve(strict=True).parent != root or not target.is_dir():
            raise ValueError("Model path escaped trusted root")
        shutil.rmtree(target)


def split_examples(examples: list[dict], seed: int):
    """Split by whole examples, never by bytes, to avoid train/eval overlap."""
    if len(examples) < 12:
        raise ValueError("At least twelve approved examples are required")
    records = sorted(examples, key=lambda e: int(e["id"]))
    random.Random(seed).shuffle(records)
    evaluation_count = max(2, len(records) // 5)
    train = records[evaluation_count:]
    validation = records[:evaluation_count]
    if set(x["id"] for x in train) & set(x["id"] for x in validation):
        raise AssertionError("Data leakage: overlapping train and validation examples")
    return train, validation


def serialize_training(examples: list[dict]) -> str:
    return "\n\n".join(
        f"المجال: {ex['subject']}\nسؤال: {ex['question']}\nجواب: {ex['answer']}"
        for ex in examples
    ) + "\n\n"


def run_job(storage: Storage, job: dict):
    job_id = int(job["id"])
    folder = MODEL_ROOT / f"run-{job_id}"
    folder.mkdir(parents=True, exist_ok=False)
    source = job["snapshot_json"]
    if isinstance(source, str):
        source = json.loads(source)
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != job["snapshot_sha256"]:
        raise ValueError("Dataset snapshot checksum mismatch")
    train, validation = split_examples(source, int(job["seed"]))
    training_data = serialize_training(train)
    # The initial byte tokenizer needs a minimum training corpus.
    if len(training_data.encode("utf-8")) < 1800:
        raise ValueError("Not enough training data: please add longer approved examples")
    data_file = folder / "train.txt"
    data_file.write_text(training_data, encoding="utf-8")
    (folder / "heldout.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metadata = {
        "id":job_id,
        "seed":job["seed"],
        "steps":job["steps"],
        "snapshot_sha256":digest,
        "train_ids":[x["id"] for x in train],
        "heldout_ids":[x["id"] for x in validation],
    }
    (folder / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metrics_path = folder / "metrics.jsonl"
    command = [
        sys.executable, "-m", "engine.train",
        "--data", str(data_file),
        "--output", str(folder),
        "--metrics-file", str(metrics_path),
        "--steps", str(int(job["steps"])),
        "--seed", str(int(job["seed"])),
    ]
    # This is intentionally never a shell command; no user-controlled flags.
    with (folder / "training.log").open("wb") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        offset = 0
        observed = set()
        while proc.poll() is None:
            offset = persist_metrics(storage, job_id, metrics_path, offset, observed)
            time.sleep(1.5)
        offset = persist_metrics(storage, job_id, metrics_path, offset, observed)
        result = proc.wait()
    if result:
        raise RuntimeError(f"Training exited with code {result}. Review server-side logs.")
    checkpoint = folder / "checkpoint.pt"
    if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        raise RuntimeError("Training finished without a valid checkpoint file")
    heldout_loss = evaluate_heldout(checkpoint, validation)
    return str(checkpoint), heldout_loss


def persist_metrics(storage: Storage, job_id: int, path: Path, offset: int, observed: set) -> int:
    if not path.exists():
        return offset
    with path.open("r", encoding="utf-8") as f:
        f.seek(offset)
        while True:
            pos = f.tell()
            line = f.readline()
            if not line:
                return pos
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                return pos
            step = int(item["step"])
            if step not in observed:
                storage.record_training_metric(
                    job_id, step, float(item["train_loss"]), float(item["validation_loss"])
                )
                observed.add(step)
            offset = f.tell()


def main():
    database = os.environ.get("DATABASE_URL")
    if not database:
        raise SystemExit("DATABASE_URL is required")
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    storage = Storage(database)
    storage.fail_interrupted_training_jobs()
    storage.requeue_interrupted_cleanup()
    print("Training worker started; polling approved job snapshots", flush=True)
    while True:
        cleanup = storage.claim_training_cleanup()
        if cleanup:
            try:
                remove_owned_model_runs(cleanup["job_ids"])
                storage.finish_training_cleanup(cleanup["id"])
                print(f"Artifact cleanup {cleanup['id']}: completed", flush=True)
            except Exception as exc:
                storage.fail_training_cleanup(cleanup["id"], str(exc))
                print(f"Artifact cleanup {cleanup['id']}: failed: {exc}", flush=True)
            continue
        job = storage.claim_training_job()
        if job is None:
            time.sleep(POLL_SECONDS)
            continue
        job_id = job["id"]
        try:
            checkpoint, heldout_loss = run_job(storage, job)
            storage.finish_training_job(job_id, True, checkpoint_path=checkpoint,
                                        heldout_loss=heldout_loss)
            print(f"Training job {job_id}: completed", flush=True)
        except Exception as exc:
            storage.finish_training_job(job_id, False, error=str(exc))
            print(f"Training job {job_id}: failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
