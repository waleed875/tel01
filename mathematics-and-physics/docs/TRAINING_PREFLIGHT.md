# Training readiness preflight for RTX 4050 6GB (Issue #47)

Preflight is an **offline, operator-only, read-only** check. It never allocates
the model, executes examples, starts training, reads checkpoints, or modifies
datasets/model weights. Only the explicitly requested JSON report is written.

## Run on a locally configured Python environment

From the `mathematics-and-physics` directory:

```sh
python -m engine.preflight --data datasets/engineering.txt \
  --device auto --tokenizer char --block-size 256 --batch-size 2 \
  --grad-accum-steps 8 --layers 4 --heads 4 --dim 128 --precision auto \
  --output preflight.json
```

The exit status is 0 when checks pass, 2 when a dataset or CUDA compatibility
check fails. A passing check **does not** prove the model will fit in GPU VRAM,
run quickly, or achieve useful mathematical/engineering answers.

## On Windows with Docker Desktop / WSL2 and NVIDIA

First independently verify that Docker can see the GPU:

```sh
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

The optional `trainer-gpu` service has network access disabled and sees the
GPU and read-only `./datasets`. For a container preflight, explicitly override
its entrypoint (the default entrypoint launches training):

```sh
docker compose --profile gpu run --rm --entrypoint python trainer-gpu \
  -m engine.preflight --data /app/datasets/engineering.txt \
  --device cuda --tokenizer char --block-size 256 --batch-size 2 \
  --grad-accum-steps 8 --precision auto
```

If PyTorch inside the container lacks CUDA, the command reports a blocker
instead of silently falling back to CPU. The report includes torch/CUDA
version, GPU name and reported VRAM, BF16 availability, exact SHA-256 of the
training corpus, dataset byte/token counts, the training/validation sizes
according to the real trainer's byte/character split, and blocking errors.

The approximate parameter/gradient/Adam state estimate uses model dimensions
only and **excludes all activations, attention buffers, GPU runtime and CUDA
allocator overhead**. It is not a peak-memory prediction. Use the actual GPU
with conservative microbatch sizes to measure usage if checks pass.

The database-managed worker continues to train from approved examples; this
preflight does **not** approve starter data, create training jobs or expose
a web endpoint. Only the four specializations remain supported. No
third-party model provider, pretrained weights or MinIO is needed.
