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

## First image-text fusion experiment

The experimental module `engine/multimodal.py` attaches 16 learned image
patch embeddings ahead of byte-token input to the existing local GPT decoder.
Text tokens can attend causally to the image prefix. Both the visual patch
projection and text transformer are **random-initialized and jointly
trainable**. This is the first architectural step toward genuine joint
image-and-text models; it is not yet ready for the chat UI.

To assemble the initial aligned dataset, create
`datasets/visual_qa/pairs.jsonl` containing JSON lines such as:

```json
{"image":"image-01.png","question":"What is shown?","answer":"A switch and a resistor."}
{"image":"image-02.png","question":"Describe the circuit","answer":"A simple series circuit."}
```

Include **at least eight unique** owned/licensed PNG/JPEG files beside the
manifest and make the answers accurate. The trainer refuses duplicate image
files, rejects unsafe paths and keeps separate held-out examples.

Train locally on the existing Docker trainer profile (without downloading any
pretrained weights):

```bash
docker compose --profile train run --rm trainer python -m engine.train_multimodal \
  --data /app/datasets/visual_qa --output /app/models/multimodal --steps 200
```

The worker writes `multimodal_checkpoint.pt` and a holdout-loss metric.
After training, open **المختبر والأدوات** and choose a PNG/JPEG image;
the new **اسأل النموذج البصري التجريبي** form sends an image and short question
to the locally trained multimodal checkpoint. The endpoint gives a raw
generated answer plus a conspicuous experimental warning and makes no Gitea
changes. The general engineering conversation still uses the existing
text-only checkpoint.

The standard chat API **does not use this checkpoint yet**. Held-out
next-byte loss is not proof that it understands diagrams, objects,
screenshot layouts, or accurately generates website designs.

Next stage: assess licensed image-caption datasets, improve tokenizer/context
length, add a proper dataset manifest, held-out diagram QA tests and a gated
multimodal inference endpoint, *then* connect to an owner-reviewed website
code-generation workflow. See Issues #16, #17, #18.

## Review generated website changes in Gitea (Issue #17)

1. Generate the local HTML/CSS website scaffold and inspect its sandboxed preview.
2. Select an **existing active software project** from the Gitea project selector.
3. Enter a destination inside `sites/<your-project>` or
   `websites/<your-project>`; paths outside these directories are rejected.
4. Click **عرض الفروقات قبل الحفظ** and inspect both full unified source diffs.
   The server reads existing files and captures Git blob hashes. A file that
   does not exist appears as a proposed create, not an overwrite.
5. Click **أوافق على التغييرات** only after reviewing them. The server
   regenerates files itself, checks ownership and project state, validates
   the signed 10-minute proposal fingerprint and source hashes, then asks
   Gitea for **one multi-file Git commit**. If either file has changed since
   the review, the approval is refused and new diffs must be reviewed.
6. Use Gitea commit history for auditing and reverting unwanted changes.

This is still a **deterministic template generator**, not free-form
intelligent site design. It never executes arbitrary user code, never runs
generated JavaScript inside previews, and does not auto-commit without explicit
approval. The preview is sandboxed and new content is escaped before inclusion
in HTML. No MinIO or external model service is used.

Only the HTML/CSS starter files are currently handled in this workflow.
True model-generated site layouts, comprehensive headless-browser accessibility
checks and visual screenshot-to-frontend comparisons remain in Issues #17 and
#18. Test this workflow on a disposable local project first.
