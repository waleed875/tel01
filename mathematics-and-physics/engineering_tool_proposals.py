"""Review-only model tool protocol and explicit owner-approved calculation.

The model is not trusted to execute anything. This code accepts only one
strict JSON fenced block, validates the allowlisted operation + inputs,
signs a time-limited proposal, and verifies it before calculating.
No Git, file, network, Python execution or session storage access.
"""
import hashlib
import hmac
import json
import re
import secrets
import time

from engineering_calculators import OPERATIONS, calculate

_KEY = secrets.token_bytes(32)
_TTL = 10 * 60
_MAX_JSON = 20000
_BLOCK = re.compile(r"```engineering-tool\s*\n(.*?)\n```", re.S)


def _canonical(user_id: int, operation: str, inputs: dict, expires: int) -> bytes:
    return json.dumps(
        {"user_id": user_id, "operation": operation, "inputs": inputs,
         "expires": expires}, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _validate(operation, inputs):
    if operation not in OPERATIONS:
        raise ValueError("Unsupported engineering operation")
    if not isinstance(inputs, dict) or set(inputs) != set(OPERATIONS[operation]["inputs"]):
        raise ValueError("Operation inputs do not match the documented schema")
    if len(json.dumps(inputs, ensure_ascii=False, allow_nan=False)) > _MAX_JSON:
        raise ValueError("Proposal is too large")


def _sign(user_id, operation, inputs, expires):
    data = _canonical(user_id, operation, inputs, expires)
    return f"{expires}." + hmac.new(_KEY, data, hashlib.sha256).hexdigest()


def propose(text: str, user_id: int):
    """Extract a single explicit tool proposal from model text; NEVER execute it."""
    if not isinstance(text, str):
        return None
    matches = list(_BLOCK.finditer(text))
    if len(matches) != 1 or len(matches[0].group(1)) > _MAX_JSON:
        return None
    try:
        parsed = json.loads(matches[0].group(1), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite input")))
        if not isinstance(parsed, dict) or set(parsed) != {"operation", "inputs"}:
            return None
        operation, inputs = parsed["operation"], parsed["inputs"]
        _validate(operation, inputs)
        # Preview checks only the exact operation and JSON input shape.
        # Calculation and numerical validation happen AFTER owner approval.
    except (ValueError, TypeError, OverflowError):
        return None
    expires = int(time.time()) + _TTL
    return {
        "operation": operation, "inputs": inputs, "label": OPERATIONS[operation]["label"],
        "domain": OPERATIONS[operation]["domain"],
        "token": _sign(user_id, operation, inputs, expires),
        "expires_at": expires,
        "notice": "اقتراح من النموذج فقط. لم يُنفذ الحساب. راجع المدخلات ثم وافق صراحة.",
    }


def approved_calculate(user_id: int, operation: str, inputs: dict, token: str):
    if not isinstance(token, str) or not re.fullmatch(r"\d{10,12}\.[a-f0-9]{64}", token):
        raise ValueError("Invalid approval token")
    expires = int(token.split(".", 1)[0])
    now = int(time.time())
    if expires < now or expires > now + _TTL:
        raise ValueError("Proposal expired; request a new review")
    _validate(operation, inputs)
    expected = _sign(user_id, operation, inputs, expires)
    if not hmac.compare_digest(token, expected):
        raise ValueError("Approval does not match user or proposed inputs")
    return calculate(operation, inputs)
