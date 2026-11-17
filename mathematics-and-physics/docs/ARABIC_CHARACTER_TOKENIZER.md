# Optional Unicode character tokens for the local Arabic engineer (Issue #41)

The default remains **byte UTF-8** (256 IDs), preserving trained model
compatibility and the existing managed web training worker.

A new experimental `--tokenizer char` mode reserves IDs 0..255 for fallback
UTF-8 bytes, then assigns one token to each frequently occurring non-ASCII
Unicode character (up to `--max-char-tokens`, default 512). These are derived
**only from the first 90% training-text split**, never from validation text,
pretrained weights, remote services or downloaded vocabularies. Unknown
characters safely fall back to UTF-8 bytes, so Arabic + source code remain
lossless. It is **character-level**, not word-level BPE; do not interpret tokens
as words.

From the `mathematics-and-physics` project directory (Python/PyTorch
available on a trusted local machine):

```sh
python -m engine.train --data datasets/engineering.txt --output models/arabic-char \
  --tokenizer char --max-char-tokens 512 --block-size 256 --batch-size 2 \
  --grad-accum-steps 8 --steps 100 --device auto --precision auto
```

Or for the existing optional offline GPU Compose profile, note that
`docker compose run` replaces the service's default argument list, so
provide data/output/device explicitly:

```sh
docker compose --profile gpu run --rm trainer-gpu \
  --data /app/datasets/engineering.txt --output /app/models/arabic-char \
  --device cuda --tokenizer char --max-char-tokens 512 \
  --steps 100 --block-size 256 --batch-size 2 --grad-accum-steps 8 --precision auto
```

Resume **only with identical training data bytes, architecture and tokenizer
options**, plus identical batch/precision/device/seed/learning rate:

```sh
docker compose --profile gpu run --rm trainer-gpu \
  --data /app/datasets/engineering.txt --output /app/models/arabic-char \
  --device cuda --tokenizer char --max-char-tokens 512 \
  --steps 100 --block-size 256 --batch-size 2 --grad-accum-steps 8 \
  --precision auto --resume /app/models/arabic-char/checkpoint.pt
```

A newly generated checkpoint embeds its character vocabulary. Inference and
held-out loss use that same checkpoint vocabulary. Old byte checkpoints
(without tokenizer metadata) still load unchanged. **Never reuse a byte
checkpoint as if it used character tokens**; an architecture/vocabulary
mismatch fails closed, and a newly trained char model is entirely distinct.

The 6GB RTX 4050 may require lower context or microbatch; this has not been
measured on the user's GPU. A shorter token sequence per Arabic sentence is
not proof of improved scientific accuracy. Benchmark separately on unseen
math, physics, electronics and coding questions. No MinIO, OpenAI API,
pretrained weights or new specialties are used.
