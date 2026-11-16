# tel01 multi-provider AI router (phase 1)

The `ai_router.py` module adds text-only asynchronous OpenAI-compatible chat routing without replacing the existing local training/inference engine.

## Providers

- OpenRouter: `OPENROUTER_API_KEY`, optional `OPENROUTER_MODEL` (default `openrouter/free`)
- Groq: `GROQ_API_KEY`, required `GROQ_MODEL`
- Gemini OpenAI-compatible endpoint: `GEMINI_API_KEY`, required `GEMINI_MODEL`
- Mistral: `MISTRAL_API_KEY`, required `MISTRAL_MODEL`
- OpenCode Big Pickle: `OPENCODE_API_KEY`, optional `BIG_PICKLE_MODEL` (default `big-pickle`)
- Local OpenAI-compatible server: required `LOCAL_AI_MODEL`, optional `LOCAL_AI_BASE_URL` (default `http://127.0.0.1:11434/v1`), optional `LOCAL_AI_API_KEY`.

Model IDs and free quotas can change: verify them in each provider's dashboard. Big Pickle endpoint/access may depend on the account and should be validated before production use. The local provider expects an OpenAI-compatible server (such as Ollama); the existing custom tel01 inference engine is **not yet** connected through an adapter.

## Example

```python
import asyncio
from ai_router import route_chat

async def main():
    result = await route_chat([{"role": "user", "content": "Write a Python function"}])
    print(result["provider"], result["content"])

asyncio.run(main())
```

Only configured providers are considered. Domain classification uses simple deterministic keywords, not a trained classifier. Providers are attempted sequentially, with a timeout and fallback on network, HTTP, or malformed-response errors. The router does not yet implement streaming, image inputs, token budgets, circuit breakers, per-provider quotas, retries with backoff, or a public HTTP route. Do not send confidential project files to third-party providers without authorization. Keep API keys in server environment variables and never commit them. Restrict `LOCAL_AI_BASE_URL` to trusted internal hosts.
