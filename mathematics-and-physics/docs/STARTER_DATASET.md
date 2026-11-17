# Four-domain starter training pack — human review required (Issue #45)

`datasets/four_domain_starter.json` contains 24 original Arabic question/
worked-answer examples: six each in mathematics, physics, electronics and
software engineering. They are a **small educational bootstrap**, not an
expert-verified corpus and not evidence of model correctness. The pack has
an explicit CC0-1.0 declaration for its newly written starter examples.

## Use from local authenticated Arabic dashboard

1. Open `http://localhost:8000`, log in and visit **إدارة بيانات التدريب**.
2. Choose **استيراد الأمثلة كمسودات للمراجعة** and confirm. The server
   imports only drafts; no examples are approved or trained automatically.
3. Read and scientifically verify each question/answer, correct by deleting
   and recreating unsuitable examples, then approve individual examples.
4. Only after at least 12 distinct examples are approved may you use
   the existing separate manual **ابدأ التدريب** action.

The import is one per-account PostgreSQL transaction, protected by an
account-scoped advisory lock. Repeated imports skip questions already in that
account, including *approved* examples, without changing their answers or
review statuses. Another account imports its own independent drafts.
Malformed packs or public benchmark question leakage fail the whole import.

## Review limits and leakage

Validators require exactly 24 samples, six in each of the **four supported
domains**, unique normalized questions, recognized domain skill labels,
bounded question/answer lengths, and no exact normalized matches to either
public evaluation benchmark. These checks are necessary, but not semantic
proof of factual correctness, scientific accuracy or lack of paraphrased
leakage. Human review is essential. Keep all publicly scored evaluation
questions separate from training and use private expert-authored held-out
questions for future model quality measurements.

The managed web-worker still trains new small byte-level models from
approved examples; it does not automatically use GPU, resume runs or
consume this pack until you import **and** explicitly review examples.
There are no pretrained weights, cloud AI services, or MinIO dependencies.
