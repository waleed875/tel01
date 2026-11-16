"""Provider-agnostic text chat routing for tel01. No keys are exposed to clients."""
from __future__ import annotations
import os
import re
import time
from dataclasses import dataclass
from typing import Any
import httpx

SYSTEM = "You are tel01. Specialize in software engineering, mathematics, physics and electronics. Explain uncertainty and verify calculations."

@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    key_env: str
    model_env: str
    default_model: str

PROVIDERS = {
    "openrouter": Provider("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "openrouter/free"),
    "groq": Provider("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", ""),
    "gemini": Provider("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "GEMINI_MODEL", ""),
    "mistral": Provider("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "MISTRAL_MODEL", ""),
    "big_pickle": Provider("big_pickle", "https://opencode.ai/inference/openai/v1", "OPENCODE_API_KEY", "BIG_PICKLE_MODEL", "big-pickle"),
    "local": Provider("local", "http://127.0.0.1:11434/v1", "LOCAL_AI_API_KEY", "LOCAL_AI_MODEL", ""),
}
DOMAIN_ORDER = {
    "software": ["big_pickle", "groq", "openrouter", "mistral", "gemini", "local"],
    "mathematics": ["groq", "gemini", "openrouter", "mistral", "big_pickle", "local"],
    "physics": ["gemini", "groq", "openrouter", "mistral", "big_pickle", "local"],
    "electronics": ["gemini", "openrouter", "groq", "mistral", "big_pickle", "local"],
    "general": ["openrouter", "groq", "gemini", "mistral", "big_pickle", "local"],
}
PATTERNS = {
    "software": r"\b(code|python|javascript|typescript|react|api|bug|docker|git|sql|programming)\b|برمج|كود|واجهة|موقع|تطبيق",
    "electronics": r"\b(circuit|pcb|resistor|transistor|voltage|arduino)\b|دائرة|إلكترون|مقاوم|ترانزستور|جهد",
    "physics": r"\b(physics|velocity|acceleration|force|newton|quantum)\b|فيزياء|سرعة|تسارع|قوة|نيوتن",
    "mathematics": r"\b(equation|integral|derivative|matrix|algebra|calculus)\b|رياضيات|معادلة|تكامل|مشتقة|مصفوفة",
}

class RouterError(Exception):
    pass

def classify_task(text: str) -> str:
    for domain in ("software", "electronics", "physics", "mathematics"):
        if re.search(PATTERNS[domain], text, re.IGNORECASE):
            return domain
    return "general"

def configured(provider: Provider) -> bool:
    return bool(os.getenv(provider.model_env, provider.default_model)) and (
        provider.name == "local" or bool(os.getenv(provider.key_env))
    )

def candidates(domain: str, preferred: str | None = None) -> list[str]:
    if preferred is not None and preferred not in PROVIDERS:
        raise ValueError("Unknown provider")
    order = DOMAIN_ORDER.get(domain, DOMAIN_ORDER["general"])
    if preferred:
        order = [preferred] + [p for p in order if p != preferred]
    return [name for name in order if configured(PROVIDERS[name])]

def _endpoint(provider: Provider) -> str:
    # Custom endpoints are accepted only for the local provider, to avoid leaking API keys.
    if provider.name == "local":
        return os.getenv("LOCAL_AI_BASE_URL", provider.url).rstrip("/")
    return provider.url

async def route_chat(messages: list[dict[str, Any]], preferred: str | None = None,
                     timeout: float = 35.0) -> dict[str, Any]:
    if not messages or any(m.get("role") not in ("system", "user", "assistant") or
                           not isinstance(m.get("content"), str) for m in messages):
        raise ValueError("Only nonempty text chat messages are supported")
    domain = classify_task(" ".join(m["content"] for m in messages if m["role"] == "user"))
    names = candidates(domain, preferred)
    if not names:
        raise RouterError("No configured AI providers")
    failures = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        for name in names:
            p = PROVIDERS[name]
            key = os.getenv(p.key_env, "") if name != "local" else os.getenv(p.key_env, "local")
            payload = {"model": os.getenv(p.model_env, p.default_model),
                       "messages": [{"role": "system", "content": SYSTEM}, *messages]}
            try:
                response = await client.post(
                    _endpoint(p) + "/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
                if not isinstance(answer, str):
                    raise ValueError("Unexpected non-text response")
                return {"provider": name, "model": payload["model"],
                        "domain": domain, "content": answer, "usage": data.get("usage")}
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                # Do not leak provider error bodies, URLs with credentials, or request content.
                failures.append(name + ": " + type(exc).__name__)
                continue
    raise RouterError("All configured providers failed: " + "; ".join(failures))
