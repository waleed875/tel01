# Trusted resumable GPU/CPU training (Issue #37)

The project currently trains a **small, randomly initialized, byte-token GPT**.
Checkpoint continuation is an **operator-only command**, not a model capability
or a web/API button. It retains the existing web training queue unchanged
(50–300 steps per new run, in its existing worker).

## Local CPU test

Inside `mathematics-and-physics` on a trusted machine with PyTorch:

```sh
python -m engine.train --data datasets/engineering.txt --output models/manual --steps 100 --device cpu
python -m engine.train --data datasets/engineering.txt --output models/manual --steps 100 --resume models/manual/checkpoint.pt --device cpu
```

The second command performs **100 additional steps**, making the total 200.
It restores model parameters, optimizer momentum and recorded random state.
It writes `checkpoint.tmp` first, then atomically replaces
`checkpoint.pt` after the run succeeds. Keep independent backups before
changing code, hardware configuration, or the corpus. For safety the loader
accepts **only checkpoints created by this operator on their trusted host**;
never accept checkpoint files from users or unknown download sources.

Resume rejects changed data bytes (SHA-256), incompatible architecture,
different seed/batch size/learning rate, changed device type, or legacy weights
without optimizer and RNG state. The small benchmark self-check is **not**
proof the neural network understands engineering.

## NVIDIA RTX 4050 6GB (optional separate Compose service)

First verify Windows WSL2, NVIDIA driver, Docker Desktop GPU support and:

```sh
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Then, with Docker Compose using the project's locally generated `.env`:

```sh
docker compose --profile gpu run --rm trainer-gpu --steps 100 --block-size 128 --batch-size 4 --layers 4 --heads 4 --dim 128
docker compose --profile gpu run --rm trainer-gpu --steps 100 --block-size 128 --batch-size 4 --layers 4 --heads 4 --dim 128 --resume /app/models/checkpoint.pt
```

The optional `trainer-gpu` service must have GPU access, appropriate CUDA
drivers and a CUDA-enabled PyTorch distribution. It has **no network access
during training** and reads only `./datasets`; it uses the existing
`trained_models` volume. The container's default training file is
`/app/datasets/engineering.txt`. If CUDA isn't visible to PyTorch,
`--device cuda` fails explicitly instead of falling back to CPU.

The GPU commands are **not** the managed training-job UI. Don't run them at
the same time as any worker training job sharing the models volume, and
don't overwrite the `trainer` profile's old checkpoint while it is needed.
GPU memory use depends on batch, context, gradients and optimizer; 6GB is
not a guarantee a larger model fits. Lower batch or context on OOM; verify
actual usage with `nvidia-smi`.

## Important limitations

- This is a compact proof-of-concept network; accurate engineering language,
  long prompts, diagrams and code generation require architectural and data
  changes plus held-out evaluation. The byte tokenizer's context remains small.
- Resume preserves the same corpus and model architecture, rather than
  learning new datasets. A separate **verified migration/fine-tuning pipeline**
  is needed to continue on new data safely.
- No MinIO, third-party AI APIs, hosted model checkpoints or pretrained weights.
