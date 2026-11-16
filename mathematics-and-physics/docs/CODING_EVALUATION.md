# Functional coding benchmark (Issue #18)

This is an **operator-only**, local harness for checking whether the
random-initialized, self-trained text model can produce *working Python
functions*. It does **not** use OpenAI APIs, hosted models, pretrained weights,
MinIO or remote code-execution services.

## Current version

`benchmarks/coding_cases.json` contains five public, versioned Python
function tasks with at least 25 functional input/output cases. The tasks cover
iteration, lists, indexing, counting, boundary cases and bracket parsing.

The benchmark dataset is public and small. These are not secret hold-out
tests. Any training on the task text, reference implementations or test cases
invalidates its usefulness as a generalization measurement. A higher-quality
evaluation must use unseen, independently curated, licensed repository tasks
and project-level deduplication (Issue #18).

## Self-check the evaluator

On a **trusted host with Docker installed**, while in the
`mathematics-and-physics` directory:

```bash
docker pull python:3.12-alpine
python -m benchmarks.run_code_eval --mode reference \
  --output local_benchmark_reference.json
```

A perfect reference score means **only** that the benchmark fixture and runner
work. It says nothing about the trained AI model.

## Evaluate code produced by a local checkpoint

```bash
python -m benchmarks.run_code_eval --mode checkpoint \
  --checkpoint /path/to/local/checkpoint.pt \
  --output local_model_benchmark.json
```

`checkpoint.pt` must be a trusted checkpoint produced by our own training
pipeline. The evaluator uses `LocalModel.answer` to request code, then
executes the returned function only in a disposable Docker container.
Untrained or weak checkpoints may produce zero valid functions. The report
contains the checkpoint SHA-256, benchmark SHA-256, individual task/case pass
rates and elapsed times, making before/after comparisons possible.

You can also evaluate a folder of separately generated functions in files
named after task IDs, e.g. `sum_even.py`:

```bash
python -m benchmarks.run_code_eval --mode candidates \
  --candidate-dir /path/to/generated-functions \
  --output local_candidates_benchmark.json
```

Keep reports out of Git when they contain private checkpoint metadata.

## Isolation and limitations

Candidates are AST-checked before execution: imports, class definitions,
attribute access, `eval`/`exec`/`open`, special attributes and arbitrary
calls are prohibited. Only function definitions and a small set of built-ins
are allowed; the test harness always runs in Docker with:

- `--network=none`, read-only root filesystem and read-only fixture mount;
- non-root UID, all capabilities dropped and no-new-privileges;
- CPU, memory, process count, file descriptor limits and wall-time timeout;
- no Docker socket, host filesystems, secrets, or Gitea volumes mounted;
- uniquely named disposable container removed on timeout.

**This is defense in depth, not a guarantee that arbitrary hostile Python is
safe on every Docker/kernel version.** Only a trusted operator should run the
evaluator. Never expose it as a public API or hand unrestricted Docker access
to the web service. Harder multi-tenant isolation requires stronger VM
separation.

## Next engineering milestones

- Diverse licensed bug-fix and programming tasks grouped by repository,
  leakage-free train/validation/test split and independently reviewed results.
- Test generated patches against isolated project build/test suites; measure
  latency and memory, not just output similarity.
- Add browser screenshot-to-HTML/CSS comparison, mobile breakpoints,
  accessibility and visual quality assessment.
- Record meaningful pass-rate improvements across real training checkpoints.
  Only then consider a model sufficiently capable for broader code workflows.
