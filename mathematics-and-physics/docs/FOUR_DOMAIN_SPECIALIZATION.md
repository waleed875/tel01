# Four-domain Engineering AI Lab specialization (Issue #26)

The project is intentionally dedicated to **only four disciplines**:
**software engineering**, **mathematics**, **electronics engineering**, and
**physics**. There is no requirement to add everyday general-assistant topics.
Related crossover tasks (e.g. Python algorithms for circuit simulation or
calculus used in mechanics) remain in scope.

## What this iteration changes

1. `engineering_domains.py` is the canonical taxonomy of these four
   disciplines and their technical skills. The `/api/catalog` endpoint
   publishes the list, allowing future training and evaluation UI to reflect
   one consistent specialization.
2. Local model prompts identify the selected domain and educational level,
   request units and derivations where relevant, warn against inventing
   unsupported facts, and ask the model to decline unrelated topics.
   **This is an instruction to a small model, not an enforced semantic
   classifier or evidence that it will obey consistently.**
3. Before training, the worker rejects repeated normalized questions even
   if a question was assigned to two different subjects. Repeating an answer
   is permitted (different problems can have the same numerical solution).
   It also blocks exact questions from the **public evaluation fixtures**.
4. Training/holdout splits are made independently within each discipline,
   using a reproducible seed. Each discipline with at least two examples
   supplies at least one held-out example. Domains with just one approved
   example remain train-only. Training metadata records domain counts and
   the number with both train and held-out coverage.
5. `benchmarks/four_domains.json` supplies 12 *public* reference tasks,
   three per discipline. The evaluator checks precise numerical answers
   and, for engineering calculations, indicated units, plus simple software
   algorithm concepts. Reports include per-domain pass counts, dataset
   SHA-256 and checkpoint SHA-256.

## Evaluate the tool, then evaluate a model

From `mathematics-and-physics`:

```bash
python -m benchmarks.evaluate_domains --mode reference
python -m benchmarks.evaluate_domains --mode checkpoint \
  --checkpoint /path/to/trusted-local-checkpoint.pt \
  --output four_domain_eval.json
```

`reference` returning 12/12 only verifies that the rubric recognizes its
known answers; it is **not a model score**. `checkpoint` runs our own
trained Transformer, then scores generated answers per discipline. Missing
units, wrong numbers, or missing software concepts count against the result.

The benchmark is intentionally tiny and public. It cannot establish expert
competence and should not be used in training or hyperparameter selection.
The exact-duplicate contamination check cannot detect every paraphrase or
semantically equivalent exercise. Independent, privately held and
human-reviewed questions must be added for meaningful generalization checks.

## Practical quality gates

The development target is for each subject to eventually have:
- Verified, appropriately licensed problems with worked solutions and units.
- Independent project- or problem-family-level train/validation/test splits,
  including duplicate and paraphrase contamination checks.
- Evaluation on real tasks: tests passing for software projects; exact symbolic
  and numerical answers in mathematics; circuit measurements and design checks
  for electronics; physical equations, dimensions and scenarios for physics.
- Reporting *separate* correctness rates per domain rather than a single
  misleading average. No new model is approved for autonomous code edits or
  high-stakes engineering decisions without dedicated validation.

A later iteration should add computational solvers and circuit-analysis
verification, improve the tokenizer/context and model capacity, curate
substantially larger datasets, and evaluate on unseen task families before
asserting the model gives consistently satisfactory results.

No MinIO, OpenAI API, hosted model service, or pretrained weights are used.
