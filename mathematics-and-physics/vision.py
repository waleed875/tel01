"""Local, non-semantic visual descriptors. No model weights or cloud APIs.

A separate trainable model is required for semantic image understanding.
Images are decoded in a subprocess-sized bounded request; never store uploads.
"""
from io import BytesIO
from collections import Counter
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 2 * 1024 * 1024
MAX_PIXELS = 4_000_000
SUPPORTED = {"PNG", "JPEG"}


def describe_image(payload: bytes):
    if not payload or len(payload) > MAX_UPLOAD:
        raise ValueError("Image must be 1 byte to 2 MiB")
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format not in SUPPORTED:
                raise ValueError("Only PNG or JPEG images are accepted")
            width, height = image.size
            if width < 8 or height < 8 or width * height > MAX_PIXELS:
                raise ValueError("Unsupported image dimensions")
            image = ImageOps.exif_transpose(image).convert("RGB")
            width, height = image.size
            # Downsample before any pixel-wise work; no massive image arrays.
            thumbnail = image.resize((min(96, width), min(96, height)))
            rgb = list(thumbnail.getdata())
            means = tuple(round(sum(pixel[i] for pixel in rgb) / len(rgb)) for i in range(3))
            # Coarse color buckets, not trained semantic object labels.
            palette = Counter(tuple((v // 64) * 64 for v in pixel) for pixel in rgb)
            top = [{"rgb": list(k), "share": round(v / len(rgb), 3)}
                   for k, v in palette.most_common(5)]
            grayscale = thumbnail.convert("L")
            lum = list(grayscale.getdata())
            cols, rows = grayscale.size
            gradient = 0
            pairs = 0
            for y in range(rows - 1):
                for x in range(cols - 1):
                    i = y * cols + x
                    gradient += abs(lum[i] - lum[i + 1]) + abs(lum[i] - lum[i + cols])
                    pairs += 2
            texture = round(gradient / max(1, pairs), 2)
            return {
                "width": width, "height": height,
                "orientation": "landscape" if width > height else
                               ("portrait" if height > width else "square"),
                "mean_rgb": list(means), "palette": top,
                "texture_score": texture,
                "analysis_level": "pixel-descriptors-only",
                "semantic_understanding": False,
                "notice": "هذا تحليل هندسي للبكسلات والألوان فقط؛ لا يتعرف بعد على النصوص أو العناصر أو المخططات."
            }
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid, unsafe or corrupted image file") from exc
