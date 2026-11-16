"""Tiny from-scratch image/question/answer training experiment.

JSONL rows: {"image":"sample.png","question":"...","answer":"..."}.
Each image path is relative to the dataset directory. Distinct images are
required across train/held-out splits. This is an educational smoke pipeline,
not evidence of reliable image question-answering.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random

from PIL import Image, ImageOps
import torch
from torch.nn import functional as F

from .model import GPTConfig
from .multimodal import MultimodalGPT
from .tokenizer import ByteTokenizer
from vision import describe_image


def load_pairs(folder: Path):
    folder = folder.resolve(strict=True)
    manifest = folder / "pairs.jsonl"
    records = []
    seen_images = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        raw_name = item["image"]
        if (not isinstance(raw_name, str) or raw_name.startswith("/")
                or ".." in Path(raw_name).parts or "\\" in raw_name):
            raise ValueError("Unsafe relative image name")
        image_path = (folder / raw_name).resolve(strict=True)
        if folder not in image_path.parents or image_path.is_symlink():
            raise ValueError("Image path escapes dataset")
        if image_path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError("Unsupported training image")
        data = image_path.read_bytes()
        describe_image(data)
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen_images:
            raise ValueError("Duplicate image bytes in dataset would leak across splits")
        seen_images.add(digest)
        if not isinstance(item.get("question"), str) or not item["question"].strip():
            raise ValueError("Image question missing")
        if not isinstance(item.get("answer"), str) or not item["answer"].strip():
            raise ValueError("Expected verified reference answer")
        with Image.open(image_path) as source:
            source = ImageOps.exif_transpose(source).convert("RGB").resize((64, 64))
            rgb = torch.tensor(list(source.getdata()), dtype=torch.float32)
            rgb = rgb.reshape(64, 64, 3).permute(2, 0, 1) / 255.0
        records.append((rgb, item["question"].strip(), item["answer"].strip(), digest))
    if len(records) < 8:
        raise ValueError("At least eight distinct aligned image Q&A examples required")
    return records


def _example(example, max_text: int):
    image, question, answer, _ = example
    tokenizer = ByteTokenizer()
    prompt = tokenizer.encode("سؤال: " + question + "\nجواب: ")
    response = tokenizer.encode(answer + "\n")
    # Keep the answer intact where possible, rather than losing supervision.
    if len(response) >= max_text:
        raise ValueError("Reference answer exceeds the model context")
    prompt = prompt[-(max_text - len(response)):]
    source = prompt + response
    inputs = source[:-1]
    targets = source[1:]
    # Only train on answer bytes; prompt bytes are input context, not labels.
    labels = [-1] * max(0, len(prompt) - 1) + targets[len(prompt)-1:]
    if len(inputs) < 2 or not any(v != -1 for v in labels):
        raise ValueError("No trainable answer tokens")
    return image, torch.tensor(inputs), torch.tensor(labels)


def train_pairs(folder: Path, output: Path, *, steps=10, seed=42,
                width=32, depth=1, heads=4, block_size=128):
    if not 1 <= steps <= 10000:
        raise ValueError("Invalid training steps")
    torch.manual_seed(seed)
    records = load_pairs(folder)
    rng = random.Random(seed)
    rng.shuffle(records)
    hold_count = max(2, len(records) // 5)
    train, heldout = records[:-hold_count], records[-hold_count:]
    config = GPTConfig(vocab_size=256, block_size=block_size, n_layer=depth,
                       n_head=heads, n_embd=width, dropout=0.0, bias=True)
    model = MultimodalGPT(config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    max_text = block_size - model.patch_count
    encoded_train = [_example(x, max_text) for x in train]
    encoded_hold = [_example(x, max_text) for x in heldout]
    model.train()
    for step in range(steps):
        image, text, labels = encoded_train[step % len(encoded_train)]
        _, loss = model(image.unsqueeze(0), text.unsqueeze(0),
                        labels.unsqueeze(0))
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.inference_mode():
        losses = []
        for image, text, labels in encoded_hold:
            _, loss = model(image.unsqueeze(0), text.unsqueeze(0),
                            labels.unsqueeze(0))
            losses.append(float(loss))
    value = sum(losses) / len(losses)
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "multimodal_checkpoint.pt"
    temporary = output / "multimodal_checkpoint.tmp"
    torch.save({"model": model.state_dict(), "config": {
        "vocab_size": 256, "block_size": block_size, "n_layer": depth,
        "n_head": heads, "n_embd": width, "dropout": 0.0, "bias": True},
        "image_size": 64, "patch_size": 16,
        "steps": steps, "seed": seed, "holdout_loss": value,
        "training_images": len(train), "heldout_images": len(heldout)},
        temporary)
    temporary.replace(checkpoint)
    result = {"checkpoint": str(checkpoint), "holdout_loss": value,
              "heldout_images": len(heldout), "training_images": len(train),
              "note": "Next-byte answer loss only; no semantic reasoning quality claim"}
    (output / "multimodal_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("models/multimodal"))
    parser.add_argument("--steps", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(train_pairs(args.data, args.output, steps=args.steps),
                     ensure_ascii=False, indent=2))
