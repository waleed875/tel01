"""Standalone Arabic engineering AI web application; no Telegram integration."""
import asyncio
import base64
import binascii
import re
import os
import secrets
from pathlib import Path
from functools import lru_cache
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from knowledge import find_references
from questions import BY_ID, select_question
from storage import Storage
from tutor import Tutor, LEVEL_NAMES, SUBJECT_NAMES
from gitea_client import GiteaClient, GiteaError, MAX_FILE_BYTES, validate_path
from auth import AuthStore, SESSION_SECONDS

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Engineering AI Lab", docs_url=None, redoc_url=None)
storage: Storage | None = None
model: Tutor | None = None
auth_store: AuthStore | None = None

# For local deployment. Login is deliberately not implemented; session cookies
# isolate progress, but a public deployment must add authentication and HTTPS.
COOKIE = "engai_auth"
LEGACY_COOKIE = "engai_session"
LEVELS = set(LEVEL_NAMES)
SUBJECTS = set(SUBJECT_NAMES)
MAX_PROMPT = 1800


class ProjectRequest(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    kind: str = Field(default="software")


class ProjectFileWrite(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content_base64: str = Field(min_length=1, max_length=2800000)
    sha: str | None = None
    message: str = Field(min_length=3, max_length=240)


class ProjectFileRename(BaseModel):
    from_path: str = Field(min_length=1, max_length=500)
    to_path: str = Field(min_length=1, max_length=500)
    sha: str = Field(min_length=40, max_length=40)
    message: str = Field(min_length=3, max_length=240)


class ProjectFileDelete(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    sha: str = Field(min_length=40, max_length=40)
    message: str = Field(min_length=3, max_length=240)


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
    global storage, model, auth_store
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured")
    storage = Storage(database_url)
    auth_store = AuthStore(database_url)
    checkpoint = os.getenv("MODEL_CHECKPOINT", "/app/models/checkpoint.pt")
    model = Tutor(checkpoint_path=checkpoint)


def db() -> Storage:
    if storage is None:
        raise HTTPException(503, "Database not initialized")
    return storage


def session_user(request: Request) -> int:
    """Require an authenticated, unexpired local account for private data."""
    if auth_store is None:
        raise HTTPException(503, "Authentication service is not initialized")
    token = request.cookies.get(COOKIE, "")
    session = auth_store.session(token)
    if not session:
        raise HTTPException(401, "يجب تسجيل الدخول للوصول إلى بيانات المشروع")
    return session["user_id"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=128)


def cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").lower() == "true"


@app.get("/api/auth/state")
def auth_state(request: Request):
    if auth_store is None:
        raise HTTPException(503, "Authentication service is not initialized")
    token = request.cookies.get(COOKIE, "")
    session = auth_store.session(token)
    if not session:
        return {"authenticated": False, "legacy_available": bool(request.cookies.get(LEGACY_COOKIE))}
    csrf = auth_store.rotate_csrf(token)
    return {"authenticated": True, "username": session["username"],
            "role": session["role"], "csrf": csrf,
            "legacy_available": bool(request.cookies.get(LEGACY_COOKIE))}


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response):
    if auth_store is None:
        raise HTTPException(503, "Authentication service is not initialized")
    result = auth_store.login(body.username, body.password)
    if result is None:
        raise HTTPException(401, "اسم المستخدم أو كلمة المرور غير صحيحة أو الحساب مقفل مؤقتًا")
    response.set_cookie(COOKIE, result["token"], httponly=True, samesite="strict",
                        secure=cookie_secure(), max_age=SESSION_SECONDS, path="/")
    return {"authenticated": True, "username": result["username"],
            "role": result["role"], "csrf": result["csrf"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    if auth_store is not None:
        auth_store.logout(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.post("/api/auth/claim-legacy")
def claim_legacy_data(request: Request, user: Annotated[int, Depends(session_user)]):
    if auth_store is None:
        raise HTTPException(503, "Authentication service is not initialized")
    old = request.cookies.get(LEGACY_COOKIE, "")
    try:
        claimed = auth_store.claim_legacy(user, old)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not claimed:
        raise HTTPException(404, "لا توجد بيانات قديمة مرتبطة بهذه الجلسة")
    result = Response(content='{"ok":true}', media_type="application/json")
    result.delete_cookie(LEGACY_COOKIE, path="/")
    return result


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method in {"POST","PUT","PATCH","DELETE"}:
        origin = request.headers.get("origin")
        target = str(request.base_url).rstrip("/")
        if origin and origin != target:
            return Response("Cross-origin operation denied", status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return Response("Cross-site operation denied", status_code=403)
        if auth_store is not None and request.url.path != "/api/auth/login":
            token = request.cookies.get(COOKIE, "")
            csrf = request.headers.get("x-csrf-token", "")
            if not auth_store.verify_csrf(token, csrf):
                return Response("CSRF verification failed", status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data: blob:; frame-src 'self'; connect-src 'self'; object-src 'none'; "
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


@app.exception_handler(GiteaError)
async def gitea_error_handler(request: Request, exc: GiteaError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


def owned_project(database: Storage, user: int, project_id: int):
    project = database.engineering_project(user, project_id)
    if project is None:
        raise HTTPException(404, "المشروع غير موجود أو لا تملك صلاحية الوصول")
    if project.get("deletion_state", "active") != "active":
        raise HTTPException(409, "المشروع بانتظار إكمال الحذف، ويمكن إعادة محاولة حذفه.")
    return project


@app.get("/api/gitea/status")
def gitea_status():
    client = GiteaClient()
    return {"configured": client.configured(), "server": "local-only",
            "note": "يلزم إعداد مستخدم Gitea ورمز وصول خاص بالخادم."}


@app.get("/api/projects")
def list_projects(user: Annotated[int, Depends(session_user)],
                  database: Annotated[Storage, Depends(db)]):
    return {"projects": database.list_engineering_projects(user)}


@app.post("/api/projects", status_code=201)
async def create_project(body: ProjectRequest, user: Annotated[int, Depends(session_user)],
                         database: Annotated[Storage, Depends(db)]):
    title = body.title.strip()
    if not 3 <= len(title) <= 120 or body.kind not in {"software", "electronics", "physics", "math", "general"}:
        raise HTTPException(422, "عنوان المشروع أو نوعه غير صالح")
    import secrets
    repo_name = "engineering-" + secrets.token_hex(12)
    client = GiteaClient()
    await client.create_repo(repo_name, title)
    try:
        item = database.create_engineering_project(user, title, body.kind, repo_name)
    except Exception:
        # Compensate for failed DB write: no orphan repo should remain.
        await client.delete_repo(repo_name)
        raise
    return {"id": item["id"], "title": item["title"],
            "kind": item["kind"], "created_at": item["created_at"]}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int,
                         user: Annotated[int, Depends(session_user)],
                         database: Annotated[Storage, Depends(db)]):
    """Mark pending before remote deletion so an interrupted request is retryable."""
    item = database.begin_engineering_project_deletion(user, project_id)
    if not item:
        raise HTTPException(404, "المشروع غير موجود أو لا تملك صلاحية الوصول")
    try:
        await GiteaClient().delete_repo(item["repo_name"])
    except GiteaError as exc:
        # The previous deletion attempt may have removed the remote repo already.
        if exc.status != 404:
            raise
    if not database.finish_engineering_project_deletion(user, project_id):
        raise HTTPException(409, "تم حذف المستودع ولكن تعذر تنظيف ربط المشروع؛ أعد المحاولة.")
    return {"ok": True, "deleted_project_id": project_id}


@app.get("/api/projects/{project_id}/search")
async def search_project_files(project_id: int,
                               user: Annotated[int, Depends(session_user)],
                               database: Annotated[Storage, Depends(db)],
                               query: str = Query(min_length=2, max_length=100)):
    project = owned_project(database, user, project_id)
    try:
        return await GiteaClient().search_paths(project["repo_name"], query)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/projects/{project_id}/files")
async def project_files(project_id: int,
                        user: Annotated[int, Depends(session_user)],
                        database: Annotated[Storage, Depends(db)],
                        path: str = Query(default="", max_length=500)):
    project = owned_project(database, user, project_id)
    try:
        validate_path(path, allow_root=True)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"files": await GiteaClient().entries(project["repo_name"], path),
            "path": path}


@app.post("/api/projects/{project_id}/rename")
async def rename_project_file(project_id: int, body: ProjectFileRename,
                              user: Annotated[int, Depends(session_user)],
                              database: Annotated[Storage, Depends(db)]):
    project = owned_project(database, user, project_id)
    try:
        result = await GiteaClient().rename_file(
            project["repo_name"], body.from_path, body.to_path,
            sha=body.sha, message=body.message)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "result": result}


def safe_preview_type(path: str, data: bytes) -> str:
    """Never allow HTML, SVG, executable scripts, or unverified binary previews."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf" and data.startswith(b"%PDF-"):
        return "application/pdf"
    if suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix in (".jpg", ".jpeg") and data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix == ".gif" and data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if suffix == ".webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if suffix in (".md", ".markdown", ".txt"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text/plain"
    raise HTTPException(415, "هذا النوع غير مدعوم في المعاينة الآمنة؛ استخدم التنزيل.")


@app.get("/api/projects/{project_id}/file-metadata")
async def project_file_metadata(project_id: int, path: str,
                                user: Annotated[int, Depends(session_user)],
                                database: Annotated[Storage, Depends(db)]):
    project = owned_project(database, user, project_id)
    try:
        item = await GiteaClient().read_file(project["repo_name"], path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"path": item["path"], "sha": item["sha"], "size": item["size"]}


@app.get("/api/projects/{project_id}/preview")
async def preview_project_file(project_id: int, path: str,
                               user: Annotated[int, Depends(session_user)],
                               database: Annotated[Storage, Depends(db)]):
    project = owned_project(database, user, project_id)
    try:
        item = await GiteaClient().read_file(project["repo_name"], path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    mime = safe_preview_type(path, item["data"])
    return Response(
        item["data"], media_type=mime,
        headers={"Content-Disposition": "inline",
                 "Cache-Control": "private, no-store",
                 "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "sandbox"})


@app.get("/api/projects/{project_id}/file")
async def project_file(project_id: int, path: str,
                       user: Annotated[int, Depends(session_user)],
                       database: Annotated[Storage, Depends(db)]):
    project = owned_project(database, user, project_id)
    try:
        item = await GiteaClient().read_file(project["repo_name"], path)
        text = item["data"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(415, "هذا ملف ثنائي؛ استخدم تنزيل الملف بدل تحريره كنص.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"path": path, "sha": item["sha"], "size": item["size"], "content": text}


@app.get("/api/projects/{project_id}/download")
async def download_project_file(project_id: int, path: str,
                                user: Annotated[int, Depends(session_user)],
                                database: Annotated[Storage, Depends(db)]):
    from urllib.parse import quote
    project = owned_project(database, user, project_id)
    try:
        item = await GiteaClient().read_file(project["repo_name"], path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    filename = path.split("/")[-1]
    return Response(item["data"], media_type="application/octet-stream",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
                             "X-Content-Type-Options": "nosniff"})


@app.post("/api/projects/{project_id}/file")
async def save_project_file(project_id: int, body: ProjectFileWrite,
                            user: Annotated[int, Depends(session_user)],
                            database: Annotated[Storage, Depends(db)]):
    project = owned_project(database, user, project_id)
    try:
        validate_path(body.path)
        data = base64.b64decode(body.content_base64, validate=True)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, "الحد الأقصى للملف 2 ميغابايت")
        result = await GiteaClient().write_file(project["repo_name"], body.path, data,
                                                 sha=body.sha, message=body.message)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "commit": result.get("commit", {}).get("sha"),
            "sha": result.get("content", {}).get("sha")}


@app.delete("/api/projects/{project_id}/file")
async def remove_project_file(project_id: int, body: ProjectFileDelete,
                              user: Annotated[int, Depends(session_user)],
                              database: Annotated[Storage, Depends(db)]):
    project = owned_project(database, user, project_id)
    try:
        validate_path(body.path)
        result = await GiteaClient().delete_file(project["repo_name"], body.path,
                                                  body.sha, body.message)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "commit": result.get("commit", {}).get("sha")}


@app.get("/api/projects/{project_id}/commits")
async def project_commits(project_id: int, user: Annotated[int, Depends(session_user)],
                          database: Annotated[Storage, Depends(db)]):
    project = owned_project(database, user, project_id)
    return {"commits": await GiteaClient().commits(project["repo_name"])}


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
    raise HTTPException(
        409,
        "تعطيل حذف الحساب مؤقتًا لحماية مستودعات Gitea وملفات التدريب. استخدم تسجيل الخروج.")
