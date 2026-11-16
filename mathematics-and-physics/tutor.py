"""Our custom model inference: no pretrained weights, no Ollama or OpenAI."""
import asyncio
import os
from engine.inference import LocalModel

LEVEL_NAMES = {
    "beginner": "مبتدئ / ابتدائي", "intermediate": "متوسط",
    "highschool": "ثانوي", "university": "جامعي",
}
SUBJECT_NAMES = {
    "math": "الرياضيات", "physics": "الفيزياء",
    "software": "هندسة البرمجيات", "electronics": "هندسة الإلكترونيات",
}

class Tutor:
    def __init__(self, checkpoint_path: str):
        self.checkpoint_path = checkpoint_path
        self.local = LocalModel(checkpoint_path, max_tokens=int(os.getenv("MAX_NEW_TOKENS", "180")))

    async def ask(self, *, level: str, subject: str, question: str,
                  history: list[dict], image_data_url: str | None = None) -> str:
        if image_data_url:
            return "النموذج التدريبي الحالي نصّي فقط."
        prompt = f"المجال: {SUBJECT_NAMES[subject]}\nالمستوى: {LEVEL_NAMES[level]}\n{question}"
        # Run CPU inference off the event loop so Telegram remains responsive.
        return await asyncio.to_thread(self.local.answer, prompt)

    async def close(self):
        return None
