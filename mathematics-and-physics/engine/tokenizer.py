"""Deterministic UTF-8 byte tokenizer; no pretrained vocabulary or tokenizer files."""
class ByteTokenizer:
    vocab_size = 256

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def decode(self, tokens: list[int]) -> str:
        return bytes(int(t) for t in tokens if 0 <= int(t) <= 255).decode("utf-8", errors="replace")
