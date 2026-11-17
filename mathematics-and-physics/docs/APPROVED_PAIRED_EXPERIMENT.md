# Local RTX 4050 paired experiment from reviewed examples (Issue #49)

This is an operator-owned, offline training workflow. **No model is trained
automatically when you import or export training data.** No cloud AI or
pretrained weights are involved. Its tiny from-scratch architecture is
experimental; do not expect ChatGPT-like expertise.

## 1. Export approved-only data

On the localhost Arabic dashboard, review drafts, approve examples individually,
then choose **تنزيل الأمثلة المعتمدة** under **إدارة بيانات التدريب**.
Only your approved Q&A records are exported to `approved-engineering.json`.
The export omits account/user/database IDs and never includes drafts.
Treat this file as private. Never commit it to GitHub.

The starter pack has 24 examples, but these are not expert-verified. Review
scientific correctness yourself and supplement with trustworthy licensed
examples before expecting any useful learning.

## 2. Prepare identical corpus / independent held-out examples

Move the JSON export into `mathematics-and-physics` locally and confirm that
PyTorch on your Windows/WSL2 environment has NVIDIA CUDA support.

```sh
python -m engine.paired_experiment --mode prepare \
  --approved-export approved-engineering.json \
  --output experiments/first-4050 \
  --device cuda --precision auto --block-size 128 \
  --batch-size 2 --grad-accum-steps 8
```

This validates that all four disciplines have training and held-out examples,
checks benchmark leakage using the same train/validation splitting rules as
the web worker, checks corpus/tokenizer/context sizes for both modes, and only
then creates `experiments/first-4050` with `training.txt`, `heldout.json`
and `manifest.json`. It does **not** create model weights or start training.
If the folder already exists it refuses to overwrite it.

For separate Docker use, mount the private exported file into a container
only by an explicit *read-only* bind mount and keep GPU access isolated.
The easiest documented path is a local CUDA-capable Python environment.
The managed web training worker is unrelated to this CLI.

## 3. Train two separate models

```sh
python -m engine.paired_experiment --mode run \
  --output experiments/first-4050 --steps 100
```

Both models use the same training corpus, random seed, architecture and
optimizer steps. One uses the legacy byte tokenizer, the second uses
character-aware tokenization. They run sequentially with distinct checkpoint
directories. A launched run cannot silently start again or overwrite old
weights. Do not run multiple training processes against the same directory.

## 4. Compare the actual local checkpoints

```sh
python -m engine.paired_experiment --mode compare \
  --output experiments/first-4050
```

The existing evaluator scores the same public domain and tool-proposal
questions, records SHA-256 and context/truncation measurements, and writes
`comparison.json`. It does not execute generated programs or suggestions.
It cannot invent quality results if either checkpoint is missing. It can be
rerun after an interrupted *comparison*.

**Limitations:** A 6GB RTX 4050 has not been benchmarked by us in your local
environment; preflight does not predict true peak VRAM or training time.
The trainer's internal 90/10 token split is an additional loss diagnostic;
whole held-out examples are not included in the exported training corpus.
Public benchmark scores are small and cannot prove engineering capability
or causal gains from a tokenizer. Before using the model in production,
evaluate on new independent, expert-written math, physics, electronics
and programming tasks.
