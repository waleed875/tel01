"""Our custom model inference: no pretrained weights, no Ollama or OpenAI."""
import asyncio
import os
from engine.inference import LocalModel
from engineering_domains import DOMAINS, subject_prompt

LEVEL_NAMES = {
    "beginner": "مبتدئ / ابتدائي", "intermediate": "متوسط",
    "highschool": "ثانوي", "university": "جامعي",
}
SUBJECT_NAMES = {key: domain["label"] for key, domain in DOMAINS.items()}

class Tutor:
    def __init__(self, checkpoint_path: str):
        self.checkpoint_path = checkpoint_path
        self.local = LocalModel(checkpoint_path, max_tokens=int(os.getenv("MAX_NEW_TOKENS", "180")))

    async def ask(self, *, level: str, subject: str, question: str,
                  history: list[dict], image_data_url: str | None = None) -> str:
        if image_data_url:
            return "النموذج التدريبي الحالي نصّي فقط."
        prompt = subject_prompt(subject, LEVEL_NAMES[level], question)
        # Run CPU inference off the event loop so Telegram remains responsive.
        return await asyncio.to_thread(self.local.answer, prompt)

    async def close(self):
        return None
