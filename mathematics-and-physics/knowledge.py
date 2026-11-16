"""Small local reference retriever, no external service."""
from pathlib import Path
import re

ROOT = Path(__file__).parent / "knowledge"
STOP = {"كيف", "ماذا", "اشرح", "شرح", "اريد", "أريد", "في", "من", "على", "الى", "إلى", "the", "and", "for", "what", "how"}

def tokens(text):
    return set(re.findall(r"[\w\u0621-\u064a]{3,}", text.lower())) - STOP

def find_references(question, subject, limit=3):
    words = tokens(question)
    results = []
    for file in sorted(ROOT.glob("*.md")):
        for part in file.read_text(encoding="utf-8").split("\n## "):
            part = part.strip()[:1600]
            if not part:
                continue
            score = len(words & tokens(part)) + (3 if file.stem == subject else 0)
            if score:
                results.append((score, file.name, part))
    results.sort(key=lambda row: (-row[0], row[1]))
    return [(name, body) for _, name, body in results[:limit]]

def format_references(items):
    return "\n\n".join(f"[{name}] {body}" for name, body in items) if items else "لا توجد مراجع محلية مطابقة لهذا السؤال."
