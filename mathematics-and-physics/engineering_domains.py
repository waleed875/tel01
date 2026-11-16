"""The only four supported Engineering AI Lab knowledge domains.

This is an explicit specialization policy, not a claim that a small neural
network understands these subjects. Cross-disciplinary questions are welcome.
"""
import hashlib
import json
import re
import unicodedata

DOMAINS = {
    "software": {
        "label": "هندسة البرمجيات",
        "skills": ["programming", "algorithms", "testing", "debugging",
                   "architecture", "web", "databases", "security"],
    },
    "math": {
        "label": "الرياضيات",
        "skills": ["algebra", "calculus", "linear_algebra", "probability",
                   "statistics", "numerical_methods"],
    },
    "electronics": {
        "label": "هندسة الإلكترونيات",
        "skills": ["circuits", "components", "digital_logic", "embedded_systems",
                   "microcontrollers", "signals"],
    },
    "physics": {
        "label": "الفيزياء",
        "skills": ["mechanics", "electromagnetism", "energy", "waves",
                   "thermodynamics", "measurement"],
    },
}
DOMAIN_IDS = frozenset(DOMAINS)


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Expected text")
    # Normalize Unicode and whitespace without removing mathematical signs.
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", value).strip()


def fingerprint(subject: str, question: str) -> str:
    if subject not in DOMAIN_IDS:
        raise ValueError("Outside the four approved engineering domains")
    value = normalize_text(question)
    if not value:
        raise ValueError("Empty question")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_examples(examples: list[dict]) -> dict:
    """Reject duplicate normalized questions even across different subjects.

    Answer duplication alone is valid (e.g. two exercises both yielding 3).
    Domain coverage is reported honestly, not artificially equalized.
    """
    seen = set()
    counts = {name: 0 for name in DOMAINS}
    for row in examples:
        subject = row.get("subject")
        if subject not in DOMAIN_IDS:
            raise ValueError("Training example uses an unsupported domain")
        question, answer = row.get("question"), row.get("answer")
        if not isinstance(answer, str) or not normalize_text(answer):
            raise ValueError("Training example has no verified answer")
        key = fingerprint(subject, question)
        if key in seen:
            raise ValueError("Duplicate normalized training question: train/eval leakage risk")
        seen.add(key)
        counts[subject] += 1
    return {"total": len(examples), "counts": counts,
            "missing_domains": [name for name, count in counts.items() if not count]}


def coverage(train: list[dict], holdout: list[dict]) -> dict:
    all_rows = train + holdout
    verify_examples(all_rows)
    counts = {}
    for subject in DOMAINS:
        counts[subject] = {
            "training": sum(row["subject"] == subject for row in train),
            "heldout": sum(row["subject"] == subject for row in holdout),
        }
    return {"domains": counts, "covered_domains": sum(
        item["training"] > 0 and item["heldout"] > 0 for item in counts.values()),
        "total_domains": len(DOMAINS)}


def subject_prompt(subject: str, level: str, question: str) -> str:
    if subject not in DOMAINS:
        raise ValueError("Unknown engineering domain")
    return (
        "النطاق الوحيد لهذا المساعد: هندسة البرمجيات، الرياضيات، "
        "هندسة الإلكترونيات، والفيزياء.\n"
        f"التخصص المختار: {DOMAINS[subject]['label']}. المستوى: {level}.\n"
        "أجب في نطاق هذه المجالات، واسمح بالمسائل المشتركة بينها. "
        "اذكر خطوات الحساب والوحدات عند الحاجة، ولا تخترع قياسات أو مصادر. "
        "إذا كانت الإجابة غير مؤكدة فوضّح ذلك. "
        "إذا كان الطلب خارج المجالات الأربعة، اعتذر باختصار وبيّن حدود التخصص.\n"
        # Keep subject near the question: small byte-GPT context truncates the prefix.
        f"المجال: {DOMAINS[subject]['label']}\nسؤال: {question}"
    )


def catalog() -> dict:
    return {"domains": DOMAINS, "only_these_domains": True,
            "notice": "التركيز على أربعة مجالات لا يثبت بعد جودة إجابات النموذج؛ قيّم كل مجال على حدة."}
