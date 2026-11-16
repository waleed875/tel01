"""Standalone Arabic engineering AI web application; no Telegram integration."""
import asyncio
import os
import secrets
from pathlib import Path
from functools import lru_cache
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from knowledge import find_references
from questions import BY_ID, select_question
from storage import Storage
from tutor import Tutor, LEVEL_NAMES, SUBJECT_NAMES

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Engineering AI Lab", docs_url=None, redoc_url=None)
storage: Storage | None = None
model: Tutor | None = None

# For local deployment. Login is deliberately not implemented; session cookies
# isolate progress, but a public deployment must add authentication and HTTPS.
COOKIE = "engai_session"
LEVELS = set(LEVEL_NAMES)
SUBJECTS = set(SUBJECT_NAMES)
MAX_PROMPT = 1800


class Settings(BaseModel):
    subject: str
    level: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_PROMPT)


class AnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=80)
    choice: int = Field(ge=0, le=3)


CURRICULUM = {
    "math": [
        {"title": "الجبر والدوال", "level": "beginner", "description": "المعادلات الأساسية وتمثيل الدوال"},
        {"title": "التفاضل والتكامل", "level": "highschool", "description": "معدلات التغير ومساحات المنحنيات"},
        {"title": "الجبر الخطي", "level": "university", "description": "المتجهات والمصفوفات والتطبيقات"},
    ],
    "physics": [
        {"title": "الحركة وقوانين نيوتن", "level": "beginner", "description": "القوة والتسارع والطاقة"},
        {"title": "الكهرباء والمغناطيسية", "level": "highschool", "description": "الحقول والتيارات والدارات"},
        {"title": "الميكانيكا التطبيقية", "level": "university", "description": "نمذجة الأنظمة الفيزيائية"},
    ],
    "software": [
        {"title": "أساسيات البرمجة", "level": "beginner", "description": "المتغيرات والدوال والمنطق"},
        {"title": "الخوارزميات وهياكل البيانات", "level": "intermediate", "description": "حل المسائل وتعقيد التنفيذ"},
        {"title": "تصميم الأنظمة", "level": "university", "description": "واجهات API وقواعد البيانات والاختبار"},
    ],
    "electronics": [
        {"title": "قانون أوم والدارات", "level": "beginner", "description": "الجهد والتيار والمقاومات"},
        {"title": "منطق الدارات الرقمية", "level": "intermediate", "description": "البوابات والمنطق الثنائي"},
        {"title": "الأنظمة المدمجة", "level": "university", "description": "المتحكمات والمستشعرات والاتصال"},
    ],
}

PROJECTS = [
    {"title": "حاسبة الدارات الكهربائية", "subject": "electronics", "description": "احسب المقاومة والتيار والقدرة باستخدام قانون أوم", "difficulty": "مبتدئ"},
    {"title": "محاكاة حركة جسم", "subject": "physics", "description": "طبّق العلاقة بين المسافة والسرعة والزمن", "difficulty": "متوسط"},
    {"title": "محلل تعقيد خوارزمية", "subject": "software", "description": "قارن بين أساليب البحث والفرز", "difficulty": "متوسط"},
    {"title": "اشتقاق الدوال", "subject": "math", "description": "تدرّب على مشتقات الحدود متعددة القوى", "difficulty": "متوسط"},
]


class TrainingReviewRequest(BaseModel):
    approved: bool


class StartTrainingRequest(BaseModel):
    steps: int = Field(ge=50, le=300)
    seed: int = Field(ge=0, le=2147483647)


class TrainingExampleRequest(BaseModel):
    subject: str
    question: str = Field(min_length=8, max_length=1800)
    answer: str = Field(min_length=8, max_length=5000)


@app.on_event("startup")
def startup():
    global storage, model
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured")
    storage = Storage(database_url)
    checkpoint = os.getenv("MODEL_CHECKPOINT", "/app/models/checkpoint.pt")
    model = Tutor(checkpoint_path=checkpoint)


def db() -> Storage:
    if storage is None:
        raise HTTPException(503, "Database not initialized")
    return storage


def session_user(request: Request, response: Response) -> int:
    """Bind a random opaque session to a DB-assigned internal ID."""
    if storage is None:
        raise HTTPException(503, "Database not initialized")
    raw = request.cookies.get(COOKIE, "")
    token = raw if len(raw) == 64 and all(c in "0123456789abcdef" for c in raw) else None
    if not token:
        token = secrets.token_hex(32)
    uid = storage.get_or_create_web_session(token)
    if raw != token:
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
                            max_age=30 * 24 * 3600, path="/")
    return uid


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html")


@app.get("/static/style.css")
def css():
    return FileResponse(BASE / "static" / "style.css", media_type="text/css")


@app.get("/static/app.js")
def js():
    return FileResponse(BASE / "static" / "app.js", media_type="text/javascript")


@app.get("/api/catalog")
def catalog():
    """Curriculum and example projects are static; never present them as mastered content."""
    return {"curriculum": CURRICULUM, "projects": PROJECTS, "subjects": SUBJECT_NAMES,
            "levels": LEVEL_NAMES}


@lru_cache(maxsize=4)
def cached_model(path: str):
    return Tutor(checkpoint_path=path)


def safe_checkpoint(job: dict) -> Path:
    """Check that an owned, completed job points to our worker-owned model directory."""
    folder = Path(os.getenv("MODEL_ROOT", "/app/models")).resolve()
    expected = (folder / f"run-{job['id']}" / "checkpoint.pt").resolve()
    if Path(job["checkpoint_path"]).resolve() != expected or not expected.is_file():
        raise HTTPException(409, "ملف الأوزان لهذا الإصدار غير موجود على الخادم")
    return expected


@app.post("/api/training/jobs/{job_id}/activate")
def activate_model(job_id: int, user: Annotated[int, Depends(session_user)],
                   database: Annotated[Storage, Depends(db)]):
    job = database.training_job(user, job_id)
    if not job or job["state"] != "completed":
        raise HTTPException(409, "لا يمكن تفعيل إصدار غير مكتمل أو غير تابع لجلساتك")
    full = database.completed_training_job_path(user, job_id)
    if not full or not full["checkpoint_path"]:
        raise HTTPException(409, "ملف الإصدار غير جاهز")
    safe_checkpoint(full)
    active = database.activate_training_job(user, job_id)
    if not active:
        raise HTTPException(409, "تعذر تفعيل الإصدار")
    return {"active_job_id": active["id"], "heldout_loss": active["heldout_loss"],
            "notice": "التفعيل لا يعني اعتماد جودة الإجابات الهندسية"}


@app.get("/api/model/status")
def model_status(user: Annotated[int, Depends(session_user)],
                 database: Annotated[Storage, Depends(db)]):
    path = Path(os.getenv("MODEL_CHECKPOINT", "/app/models/checkpoint.pt"))
    active = database.active_training_job(user)
    if active:
        try:
            safe_checkpoint(active)
            path = Path(active["checkpoint_path"])
        except HTTPException:
            active = None
    return {
        "active_job_id": active["id"] if active else None,
        "heldout_loss": active["heldout_loss"] if active else None,
        "checkpoint_available": path.is_file(),
        "checkpoint_size_bytes": path.stat().st_size if path.is_file() else 0,
        "backend": "custom-transformer",
        "training_note": "وجود أوزان لا يعني أن النموذج مؤهل أو دقيق؛ البيانات الحالية تجريبية.",
    }


@app.post("/api/training/jobs", status_code=202)
def create_training_job(body: StartTrainingRequest, user: Annotated[int, Depends(session_user)],
                        database: Annotated[Storage, Depends(db)]):
    try:
        return database.create_training_job(user, body.steps, body.seed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/training/jobs")
def training_jobs(user: Annotated[int, Depends(session_user)],
                  database: Annotated[Storage, Depends(db)]):
    return {"jobs": database.list_training_jobs(user)}


@app.get("/api/training/jobs/{job_id}")
def training_job(job_id: int, user: Annotated[int, Depends(session_user)],
                 database: Annotated[Storage, Depends(db)]):
    job = database.training_job(user, job_id)
    if not job:
        raise HTTPException(404, "مهمة التدريب غير موجودة")
    return {"job": job, "metrics": database.training_job_metrics(user, job_id)}


@app.get("/api/datasets")
def training_examples(user: Annotated[int, Depends(session_user)],
                      database: Annotated[Storage, Depends(db)]):
    return {"examples": database.training_examples(user, 100),
            "note": "المسودات تحفظ في PostgreSQL فقط ولا تدخل في تدريب النموذج تلقائيًا."}


@app.patch("/api/datasets/{example_id}/review")
def review_example(example_id: int, body: TrainingReviewRequest,
                   user: Annotated[int, Depends(session_user)],
                   database: Annotated[Storage, Depends(db)]):
    updated = database.review_training_example(user, example_id,
                                               "approved" if body.approved else "draft")
    if not updated:
        raise HTTPException(404, "المثال غير موجود")
    return updated


@app.get("/api/datasets/stats")
def dataset_stats(user: Annotated[int, Depends(session_user)],
                  database: Annotated[Storage, Depends(db)]):
    return database.training_counts(user)


@app.post("/api/datasets", status_code=201)
def add_example(body: TrainingExampleRequest, user: Annotated[int, Depends(session_user)],
                database: Annotated[Storage, Depends(db)]):
    if body.subject not in SUBJECTS:
        raise HTTPException(422, "التخصص غير صالح")
    question, answer = body.question.strip(), body.answer.strip()
    if len(question) < 8 or len(answer) < 8:
        raise HTTPException(422, "النص قصير جدًا")
    return database.add_training_example(user, body.subject, question, answer)


@app.delete("/api/datasets/{example_id}")
def delete_example(example_id: int, user: Annotated[int, Depends(session_user)],
                   database: Annotated[Storage, Depends(db)]):
    if not database.delete_training_example(user, example_id):
        raise HTTPException(404, "المثال غير موجود")
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok", "backend": "custom-transformer", "database": "postgresql"}


@app.get("/api/profile")
def profile(user: Annotated[int, Depends(session_user)], database: Annotated[Storage, Depends(db)]):
    return database.profile(user)


@app.put("/api/profile")
def update_profile(settings: Settings, user: Annotated[int, Depends(session_user)],
                   database: Annotated[Storage, Depends(db)]):
    if settings.subject not in SUBJECTS or settings.level not in LEVELS:
        raise HTTPException(422, "المستوى أو التخصص غير صالح")
    database.set_subject(user, settings.subject)
    database.set_level(user, settings.level)
    database.clear_history(user)
    return database.profile(user)


@app.get("/api/history")
def history(user: Annotated[int, Depends(session_user)], database: Annotated[Storage, Depends(db)]):
    return {"messages": database.recent_history(user, limit=20)}


@app.delete("/api/history")
def delete_history(user: Annotated[int, Depends(session_user)],
                   database: Annotated[Storage, Depends(db)]):
    database.clear_history(user)
    return {"ok": True}


@app.post("/api/chat")
async def chat(body: ChatRequest, user: Annotated[int, Depends(session_user)],
               database: Annotated[Storage, Depends(db)]):
    if model is None:
        raise HTTPException(503, "محرك الذكاء الاصطناعي غير جاهز")
    active = database.active_training_job(user)
    serving_model = cached_model(str(safe_checkpoint(active))) if active else model
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "الرجاء كتابة السؤال")
    profile = database.profile(user)
    # This first version shares one locally trained checkpoint, never
    # sends the question outside our server.
    history = database.recent_history(user, 6)
    try:
        answer = await asyncio.wait_for(
            serving_model.ask(level=profile["level"], subject=profile["subject"],
                      question=question, history=history), timeout=120)
    except (FileNotFoundError, RuntimeError, ValueError):
        raise HTTPException(503, "لم يتم تدريب النموذج بعد، أو تعذر تحميل ملف الأوزان.")
    except TimeoutError:
        raise HTTPException(504, "انتهت مهلة التوليد. جرّب سؤالاً أقصر.")
    database.add_exchange(user, question, answer)
    references = find_references(question, profile["subject"], 3)
    return {"answer": answer, "references": [name for name, _ in references],
            "notice": "النموذج تجريبي وغير مؤهل بعد للإجابات الهندسية الموثوقة."}


@app.get("/api/quiz")
def quiz(user: Annotated[int, Depends(session_user)], database: Annotated[Storage, Depends(db)]):
    profile = database.profile(user)
    if profile["subject"] not in {"math", "physics"}:
        return {"available": False, "message": "الاختبارات الثابتة متاحة حاليًا للرياضيات والفيزياء."}
    q = select_question(profile["subject"], profile["level"], profile["last_question"])
    database.set_active_quiz(user, q.id)
    return {"available": True, "id": q.id, "subject": q.subject, "prompt": q.prompt,
            "options": q.options}


@app.post("/api/quiz/answer")
def answer(body: AnswerRequest, user: Annotated[int, Depends(session_user)],
           database: Annotated[Storage, Depends(db)]):
    q = BY_ID.get(body.question_id)
    if not q:
        raise HTTPException(404, "السؤال غير موجود")
    accepted = database.grade_quiz(user, q.id, body.choice == q.correct)
    if not accepted:
        raise HTTPException(409, "هذا السؤال أُجيب عنه أو انتهت صلاحيته")
    return {"correct": body.choice == q.correct, "correct_choice": q.correct,
            "explanation": q.explanation}


@app.delete("/api/account")
def delete_account(request: Request, response: Response,
                   user: Annotated[int, Depends(session_user)],
                   database: Annotated[Storage, Depends(db)]):
    database.delete_user(user)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
