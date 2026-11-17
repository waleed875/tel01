# Paired checkpoint comparison: byte vs Arabic character (Issue #43)

This operator-only CLI uses the **same public questions and scoring code**
for two distinct, trusted, already-trained local checkpoints. It makes no
claim about intelligence from tokenizer compression, and never runs model-
suggested tools, generated Python or downloads model weights.

From `mathematics-and-physics`, with trusted local checkpoint paths:

```sh
python -m benchmarks.compare_tokenizers \
  --byte-checkpoint models/byte/checkpoint.pt \
  --char-checkpoint models/arabic-char/checkpoint.pt \
  --seed 42 --output comparison.json
```

The runner evaluates two suites, the 12 four-domain response questions and
the 12 model engineering-tool-proposal questions. Each task uses identical
prompts and matching grade functions for the byte and character models.
Both receive identical pseudo-random seeds **per task** and the same
generation token budget (120 for answer questions, 180 for proposals).
Because these vocabularies have different token lengths and model weights,
token-budget equality is not equality of characters produced or equal
capacity. Model responses are not recorded; only aggregate scores and
pass/fail metadata are saved.

The report includes checkpoint/dataset hashes, model dimensions/steps,
benchmark hashes, per-domain and paired wins/losses, no-tool false proposal
counts, prompt token counts and actual truncation counts. Training-data
differences, training steps, context lengths and architecture differences
are flagged as confounds. **Even with no detected differences, do not
claim that any gain was caused only by tokenization**; separate training
runs and stochastic generation prevent causal attribution. Report public
benchmarks as preliminary regression checks, not production quality.

Not suitable for user-uploaded or downloaded checkpoints: PyTorch checkpoint
deserialization is only allowed for operator-owned trusted local artifacts.
Run offline, separately from active training, and keep benchmark fixtures
out of training data. No MinIO, third-party model or additional disciplines.
