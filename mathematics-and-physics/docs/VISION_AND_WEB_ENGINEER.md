# Visual AI and software engineer development roadmap

The project uses **no OpenAI API, hosted vision API or pretrained model
weights**. Existing text learning uses a small randomly initialized nanoGPT
architecture; no amount of UI code alone makes it a strong engineer.

## What is working in this first version

- Authenticated web interface receives PNG/JPEG screenshots and photos up to
  2 MiB and 4 million pixels. Image content stays in request memory by default;
  uploads are not automatically committed to Gitea or stored as training data.
- Deterministic descriptors report orientation, dimensions, mean RGB, dominant
  coarse colors and a rough texture score. **These are pixel features**, NOT
  object identification, OCR, schematic interpretation or semantic reasoning.
- A custom PyTorch patch/Transformer vision encoder starts with **random
  weights** and can be trained locally for specific labeled image categories.
- If you train and install its checkpoint, the API additionally returns an
  **experimental category prediction**, model score, and held-out accuracy.
  This is not a verified image understanding system.
- The website builder makes an HTML/CSS responsive starter page from a title,
  brief, theme and section checklist, with a sandboxed visual preview and
  downloadable source files. It is a deterministic scaffold, **not** AI-based
  generation of arbitrary websites. No Gitea commits happen automatically.

## Training the vision classifier from scratch

Create a dataset under the project folder:

```text
datasets/vision/
  screenshot/
    example-1.png
    example-2.png
    example-3.png
    example-4.png
  circuit/
    example-1.png
    example-2.png
    example-3.png
    example-4.png
```

Use original or properly licensed images, with accurate class labels. At least
four images per category are needed for a smoke test, **many more** for real
accuracy. Images must be PNG or JPEG, <=2 MiB and <=4 million pixels.

From the project directory with Docker Compose configured:

```bash
docker compose --profile train run --rm trainer python -m engine.train_vision \
  --data /app/datasets/vision --output /app/models/vision --steps 200
```

This starts with random weights and writes
`/app/models/vision/vision_checkpoint.pt` plus
`/app/models/vision/vision_metrics.json` into the existing
`trained_models` volume. The web container has that volume mounted read-only
and will offer the experimental classifier on the next image request.

The existing text model is **not yet fused** with the image encoder. It cannot
answer complex questions about images or generate a website from a screenshot
without properly designed image-text training and validated checkpoints.

## What is required for a strong software engineer model

1. Build a licensed, reviewed corpus of source code, PRs, bug fixes, unit
   tests, HTML/CSS layouts, screenshots with matching implementations, circuit
   diagrams and verified scientific explanations.
2. Establish a train/eval/test split by whole project and image family to
   avoid data leakage and duplicate images between train and held-out.
3. Develop an image-text alignment bridge (e.g. visual patch tokens projected
   to the GPT embedding space) and train on **aligned image/question/answer**
   examples. Train it from scratch, not from an existing checkpoint.
4. Increase model capacity, token context and compute to match intended
   coding tasks; the tiny bytewise nanoGPT prototype is not enough.
5. Test with separate software engineering benchmarks: compile/type-check,
   meaningful unit tests, runtime behavior, security tests, mobile layouts,
   keyboard accessibility, and screenshot-to-code similarity.
6. Provide project-file context from Gitea with strict scope and prompt
   injection defenses. Show proposed diffs and require explicit user approval
   before each Git commit. Never run generated code unsandboxed.

The quality milestone is tracked in Issue #18. No claim of strong reasoning or
website-generation intelligence is made until trained-model evaluations
demonstrate it.

## Security notes

The app still requires local login and is localhost-bound. Browser website
previews use an empty iframe sandbox (no scripts, no same-origin). User-provided
text is HTML-escaped in the generated scaffold. The new image API does not
download remote content or call external services. Do not expose the training
CLI or image endpoints to an untrusted public network without further resource
isolation and security review.
