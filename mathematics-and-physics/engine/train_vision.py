"""Train the project-owned patch encoder from scratch on labeled local images.

Dataset layout: ROOT/<class-name>/*.png or *.jpg. Minimum four images per
class. All images are locally labeled by the owner; this is a supervised
classification experiment, not a general visual reasoning model.
"""
import argparse
import hashlib
import json
import random
from pathlib import Path

import torch
from PIL import Image, ImageOps

from .vision import PatchVisionEncoder
from vision import describe_image


def prepare_dataset(root: Path, *, seed: int, size: int = 64):
    classes = sorted(p.name for p in root.iterdir() if p.is_dir())
    if len(classes) < 2:
        raise ValueError("At least two class folders are required")
    rows = []
    seen_hashes = set()
    for idx, label in enumerate(classes):
        files = sorted(x for x in (root / label).iterdir()
                       if x.suffix.lower() in (".png", ".jpg", ".jpeg"))
        if len(files) < 4:
            raise ValueError("At least four labeled images per class are required")
        for file in files:
            if file.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Image exceeds 2 MiB")
            # The same safety constraints used by the upload endpoint.
            data = file.read_bytes()
            describe_image(data)
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen_hashes:
                raise ValueError("Duplicate image bytes may leak between training and held-out examples")
            seen_hashes.add(digest)
            with Image.open(file) as image:
                image = ImageOps.exif_transpose(image).convert("RGB").resize((size, size))
                tensor = torch.tensor(list(image.getdata()), dtype=torch.float32)
                tensor = tensor.reshape(size, size, 3).permute(2, 0, 1) / 255.0
                rows.append((tensor, idx, str(file)))
    rng = random.Random(seed)
    train, heldout = [], []
    for idx in range(len(classes)):
        group = [r for r in rows if r[1] == idx]
        rng.shuffle(group)
        heldout.append(group[0])
        train.extend(group[1:])
    rng.shuffle(train)
    return classes, train, heldout


def train_vision(root: Path, output: Path, *, steps=20, seed=42,
                 width=32, depth=1, heads=4):
    if steps < 1 or steps > 10000:
        raise ValueError("Invalid training steps")
    torch.manual_seed(seed)
    classes, train, heldout = prepare_dataset(root, seed=seed)
    network = PatchVisionEncoder(width=width, depth=depth, heads=heads,
                                 num_classes=len(classes))
    optimizer = torch.optim.AdamW(network.parameters(), lr=3e-4)
    network.train()
    batch_size = min(8, len(train))
    for _ in range(steps):
        chosen = torch.randint(0, len(train), (batch_size,))
        images = torch.stack([train[i][0] for i in chosen])
        labels = torch.tensor([train[i][1] for i in chosen])
        loss = torch.nn.functional.cross_entropy(network(images), labels)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    network.eval()
    with torch.inference_mode():
        images = torch.stack([r[0] for r in heldout])
        targets = torch.tensor([r[1] for r in heldout])
        predictions = network(images)
        validation_loss = float(torch.nn.functional.cross_entropy(predictions, targets))
        accuracy = float((predictions.argmax(dim=1) == targets).float().mean())
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "vision_checkpoint.pt"
    temp = output / "vision_checkpoint.tmp"
    torch.save({
        "model": network.state_dict(),
        "config": {"image_size": 64, "patch_size": 8, "width": width,
                   "depth": depth, "heads": heads, "num_classes": len(classes)},
        "labels": classes, "seed": seed, "steps": steps,
        "validation_loss": validation_loss, "heldout_accuracy": accuracy,
    }, temp)
    temp.replace(checkpoint)
    metrics = {"checkpoint": str(checkpoint), "validation_loss": validation_loss,
               "heldout_accuracy": accuracy, "heldout_count": len(heldout),
               "labels": classes,
               "warning": "This is a tiny supervised classifier, not verified semantic scene understanding."}
    (output / "vision_metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("models/vision"))
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(train_vision(args.data, args.output, steps=args.steps),
                     indent=2, ensure_ascii=False))
