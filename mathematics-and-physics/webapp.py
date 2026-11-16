"""Standalone Arabic engineering AI web application; no Telegram integration."""
import asyncio
import os
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response, Cookie, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from knowledge import find_references, format_references
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
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "الرجاء كتابة السؤال")
    profile = database.profile(user)
    # This first version shares one locally trained checkpoint, never
    # sends the question outside our server.
    history = database.recent_history(user, 6)
    try:
        answer = await asyncio.wait_for(
            model.ask(level=profile["level"], subject=profile["subject"],
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
