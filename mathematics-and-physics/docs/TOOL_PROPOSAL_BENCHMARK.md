# Offline local-model tool-proposal benchmark (Issue #32)

The benchmark tests whether **our own locally trained GPT** selects the
appropriate operation, copies the exact engineering inputs, and correctly
abstains when no supported tool fits. It does not run any proposed operation
or grant model access to Git, Docker, the shell, internet or files.

Run in `mathematics-and-physics`:

```sh
python -m benchmarks.evaluate_tool_proposals --mode reference
python -m benchmarks.evaluate_tool_proposals --mode checkpoint --checkpoint models/checkpoint.pt --output /tmp/tool-report.json
python -m unittest tests.test_tool_proposal_benchmark -v
```

Reference mode feeds *expected* responses to the parser, proving only that
the scoring harness works. It is **not** evidence the AI is intelligent.
Checkpoint mode requires an operator-trusted local model checkpoint; absent
checkpoints produce an explicit error rather than fabricated percentages.

The 12 public cases are held out from training and cover the four permitted
domains (2 applicable operations and 1 no-tool question per subject).
`protocol_valid` measures valid, same-domain proposals on applicable cases.
`operation_correct` measures choosing the exact intended tool;
`inputs_correct` requires exact JSON arguments; `passed` includes correct
no-tool abstention. `false_proposals` counts unsafe-to-trust tool suggestions
on questions where the benchmark expects no tool, including attempted but malformed\n`engineering-tool` requests. A malformed request must not be mistaken for\ncorrect abstention. Training-worker snapshots reject exact normalized question\nmatches against both this benchmark and the four-domain reference benchmark. Counts are raw, with
denominators `positive_total` and `negative_total`. No calculator is
executed, including during the reference evaluation. Reports include the
dataset and actual checkpoint SHA-256 for reproducibility, not chat messages.

Limitations: These hand-written questions are small and public, so passing
them does not imply broad capability or generalization. Exact JSON equality
can reject mathematically equivalent input representations, and the parser
can accept a proposal that is structurally valid but semantically irrelevant.
The negative-case benchmark is normative for these specific questions only.
Use larger independently authored, licensed unseen datasets with near-
duplicate checks before claiming any model-quality improvement. Never train
on `benchmarks/tool_proposals.json`; keep actual evaluation questions separate
from training snapshots, and independently check paraphrase leakage.
