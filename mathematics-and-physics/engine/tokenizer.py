"""Deterministic local tokenizers; neither requires external vocabulary files.

Byte mode remains the project default. Character mode assigns whole-token IDs
only to frequent non-ASCII scalars from the training split. Unseen characters
are losslessly encoded using the original UTF-8 byte IDs 0..255.
"""
from collections import Counter

MAX_CHAR_TOKENS = 2048


class ByteTokenizer:
    vocab_size = 256

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def decode(self, tokens: list[int]) -> str:
        return bytes(int(t) for t in tokens if 0 <= int(t) <= 255).decode("utf-8", errors="replace")


class CharByteTokenizer:
    """Bilingual Unicode efficiency experiment, not a pretrained BPE model."""

    def __init__(self, chars: str):
        if (not isinstance(chars, str) or len(chars) > MAX_CHAR_TOKENS
                or len(set(chars)) != len(chars)):
            raise ValueError("Invalid character vocabulary")
        # ASCII already has single-token encoding; do not duplicate it.
        if any(ord(c) < 128 or 0xD800 <= ord(c) <= 0xDFFF for c in chars):
            raise ValueError("Character vocabulary contains invalid entries")
        self.chars = chars
        self.vocab_size = 256 + len(chars)
        self.char_to_id = {c: i + 256 for i, c in enumerate(chars)}

    def encode(self, text: str) -> list[int]:
        if not isinstance(text, str):
            raise TypeError("Text must be a string")
        result = []
        for char in text:
            token = self.char_to_id.get(char)
            if token is not None:
                result.append(token)
            else:
                result.extend(char.encode("utf-8"))
        return result

    def decode(self, tokens: list[int]) -> str:
        chunks, raw = [], bytearray()
        for token in tokens:
            if type(token) is not int or not 0 <= token < self.vocab_size:
                raise ValueError("Invalid token id")
            if token >= 256:
                if raw:
                    chunks.append(raw.decode("utf-8", errors="replace"))
                    raw.clear()
                chunks.append(self.chars[token - 256])
            else:
                raw.append(token)
        if raw:
            chunks.append(raw.decode("utf-8", errors="replace"))
        return "".join(chunks)


def build_character_tokenizer(training_text: str, max_chars: int = 512) -> CharByteTokenizer:
    if type(max_chars) is not int or not 1 <= max_chars <= MAX_CHAR_TOKENS:
        raise ValueError("max_chars must be 1..2048")
    # Only the training split is used; held-out evaluation text is excluded.
    frequencies = Counter(c for c in training_text if ord(c) >= 128
                          and not 0xD800 <= ord(c) <= 0xDFFF)
    selected = sorted((c for c, n in frequencies.items() if n >= 2),
                      key=lambda c: (-frequencies[c], ord(c)))[:max_chars]
    return CharByteTokenizer("".join(selected))


def tokenizer_from_spec(spec, vocab_size: int):
    """Load only recognized, bounded vocab formats; reject corrupt metadata."""
    if spec is None:
        if vocab_size != 256:
            raise ValueError("Legacy byte checkpoint must use vocabulary 256")
        return ByteTokenizer()
    if not isinstance(spec, dict) or set(spec) != {"version", "kind", "chars"}:
        raise ValueError("Invalid checkpoint tokenizer specification")
    if type(spec["version"]) is not int or spec["version"] != 1 or spec["kind"] != "char-byte":
        raise ValueError("Unsupported tokenizer specification")
    result = CharByteTokenizer(spec["chars"])
    if result.vocab_size != vocab_size:
        raise ValueError("Checkpoint vocabulary and tokenizer do not match")
    return result


def tokenizer_spec(tokenizer):
    if isinstance(tokenizer, ByteTokenizer):
        return None
    if isinstance(tokenizer, CharByteTokenizer):
        return {"version": 1, "kind": "char-byte", "chars": tokenizer.chars}
    raise ValueError("Unknown tokenizer instance")
