# Memory-aware training on 6GB GPU (Issue #39)

This is an operator-only enhancement for the project's randomly initialized,
byte-token GPT specializing in software, mathematics, electronics and physics.

`--grad-accum-steps N` (1–64) calculates N microbatch gradients, dividing
each microbatch loss by N, before *one* optimizer step. For instance,
`--batch-size 2 --grad-accum-steps 8` gives an effective 16 samples/step
while keeping roughly a 2-example forward activation footprint. This trades
memory for computation time; model/optimizer memory still has to fit.

`--precision fp32` is unchanged default. CUDA-only BF16 autocast can be
selected with `--precision bf16`. It fails rather than silently downgrading if
CUDA BF16 is unsupported. `--precision auto` chooses BF16 only when PyTorch
confirms its availability, otherwise FP32. Optimizer and master parameters
remain FP32; no untested FP16 scaler is introduced.

Example, run from project directory after verifying Docker Desktop/WSL2,
drivers, GPU visibility and the current CUDA-enabled PyTorch image:

```sh
docker compose --profile gpu run --rm trainer-gpu --steps 100 --block-size 256 --batch-size 2 --grad-accum-steps 8 --precision auto
docker compose --profile gpu run --rm trainer-gpu --steps 100 --block-size 256 --batch-size 2 --grad-accum-steps 8 --precision auto --resume /app/models/checkpoint.pt
```

**Important**: the second command can resume only with exactly the same
corpus bytes, seed, architecture, batch, accumulation, learning rate, device
and resolved precision. It does not let you change an existing checkpoint's
context from 128 to 256. To train at 256 you must create a **new** checkpoint
(and ideally a separate output directory). Verify dataset token length before
increasing context. Do not run this manual trainer concurrently with web jobs.

These are **experimental trial settings**, not measured safe RTX 4050 limits.
CUDA BF16 support, Docker GPU pass-through and 6GB VRAM usage must be
verified on the actual device; lower context or microbatch if OOM. Do not
infer faster training or better answers from successful execution.

The web-managed worker keeps its current defaults. The byte-level context
is still limited, and no tokenizer migration or pretrained weights have
been added. Real engineering accuracy requires independently held-out tests.
