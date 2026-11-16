# Verified Engineering Tools — Issue #28

This phase improves **verifiable task results** in Engineering AI Lab's only
four specialties: mathematics, electronics engineering, physics and software
engineering. It does not add generic assistant domains.

## Architecture

`engineering_calculators.py` contains eight **deterministic** tools using
Python's standard library only. They do **not** load a neural model, download
packages, run submitted code, read/write Gitea projects, or execute a shell.

Two authenticated FastAPI routes are available:
- `GET /api/engineering/tools` returns a machine-readable operation registry.
- `POST /api/engineering/calculate` accepts an operation name and a JSON
  object with *exactly* the declared fields.

Example request:

```json
{"operation":"electronics.ohm","inputs":{"voltage":12,"resistance":1000}}
```

Example response values: `current_a=0.012`, `power_w=0.144`.
The response includes the formula and physical assumptions. Other operations:
- `math.polynomial`: evaluate a real polynomial and its first derivative at x;
  coefficients are highest-degree-first.
- `math.quadratic`: solve for the real/complex roots of a quadratic with a
  nonzero leading coefficient; uses a numerically stable real-root formula.
- `electronics.resistors`: equivalent resistance for positive ideal series/
  parallel resistors (up to 20 components).
- `physics.force`: Newton's second law with mass in kg, acceleration m/s².
- `physics.kinetic_energy`: classical kinetic energy, mass kg, velocity m/s.
- `physics.velocity`: nonnegative distance over positive time, m/s.
- `software.analyze_python`: parse up to 16,000 characters with the Python
  AST and count functions/classes/imports/loops/conditionals. It **never
  executes** the supplied program and makes no correctness/security claim.

All operations have bounded input size and finite numeric constraints. The
client form under **المختبر الهندسي** offers worked JSON examples and shows
results as text (not interpreted HTML). This is a separate service from model
chat, so a weak local checkpoint cannot silently override a calculated value.

## Verify reference calculations

```bash
python -m unittest tests.test_engineering_calculators -v
```

Selected fixed examples:

| Domain | Example | Expected |
|---|---|---|
| Math | f(x)=3x²+2x+1, x=2 | f(2)=17, f'(2)=14 |
| Math | x²−3x+2=0 | roots 1 and 2 |
| Electronics | 12 V, 1000 Ω | I=0.012 A, P=0.144 W |
| Electronics | 100 Ω and 100 Ω in parallel | 50 Ω |
| Physics | m=3 kg, a=4 m/s² | F=12 N |
| Physics | m=2 kg, v=3 m/s | Ek=9 J |
| Physics | d=150 m, t=30 s | 5 m/s |
| Software | valid `def add(a,b)` code | syntax report; no execution |

## Important limitations

- A correct deterministic calculation **is not** evidence the trained GPT
  model has learned engineering reasoning. It is a usable reference tool.
- Numeric input units are currently fixed to SI as documented. Automatic
  unit conversion and dimensional algebra are not yet implemented.
- Polynomial and quadratic solvers are intentionally bounded and do not
  handle arbitrary symbolic expressions.
- Ideal circuit calculations do not model thermal, transient, tolerances,
  semiconductor nonlinearities or real safety considerations.
- Physics formulas represent simple classroom models, not full simulations.
- AST parsing checks source structure and syntax only; it cannot decide
  whether code is safe, correct or efficient.
- Errors reject missing/extra inputs, NaN, infinity, zero resistance/time,
  negative mass and excessively large values.

## Next steps

Only after an independent security review, expose **explicitly gated**
model-to-tool proposals, rather than letting the model silently invent
operations or replace verified output. Then evaluate real trained checkpoints
with/without those tools on independently held-out, licensed engineering
problems and report per-subject correctness. Follow Issues #18 and #26.

No MinIO, hosted AI APIs, pretrained model weights or new README are required.
