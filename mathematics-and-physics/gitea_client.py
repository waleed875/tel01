"""Narrow Gitea API client for localhost-only engineering repositories.

All upstream requests target a single administrator-configured Gitea service.
Repository names come from the session-owned project registry, never raw URLs.
"""
import base64
import os
import re
from urllib.parse import quote, urlsplit

import httpx

MAX_FILE_BYTES = 2 * 1024 * 1024
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$")


class GiteaError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def validate_path(value: str, allow_root: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("File path must be text")
    if value == "" and allow_root:
        return ""
    if (not value or len(value) > 500 or value.startswith("/")
            or "\\" in value or "\x00" in value
            or any(ord(ch) < 32 for ch in value)
            or any(segment in ("", ".", "..") for segment in value.split("/"))):
        raise ValueError("Unsafe relative file path")
    if any(segment == ".git" for segment in value.split("/")):
        raise ValueError("Internal Git paths are not editable")
    return value


def validated_repo_name(value: str) -> str:
    if not _NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise ValueError("Invalid repository name")
    return value


class GiteaClient:
    def __init__(self, base_url: str | None = None, token: str | None = None,
                 owner: str | None = None):
        self.base_url = (base_url or os.getenv("GITEA_INTERNAL_URL", "http://gitea:3000")).rstrip("/")
        self.token = token if token is not None else os.getenv("GITEA_API_TOKEN", "")
        self.owner = owner if owner is not None else os.getenv("GITEA_OWNER", "")
        url = urlsplit(self.base_url)
        # Gitea is an internal, non-public service. Never use arbitrary external addresses.
        if (url.scheme != "http" or url.hostname != "gitea" or url.port != 3000
                or url.username or url.password or url.path or url.query or url.fragment):
            raise ValueError("Gitea must be the internal Docker service http://gitea:3000")
        if self.owner and not _NAME_RE.fullmatch(self.owner):
            raise ValueError("Invalid Gitea service-account username")

    def configured(self) -> bool:
        return bool(self.token and self.owner and not self.token.startswith("REPLACE_"))

    async def _call(self, method: str, endpoint: str, *, json: dict | None = None,
                    params: dict | None = None):
        if not self.configured():
            raise GiteaError(503, "لم يتم إعداد حساب Gitea ورمز API الخاص به على الخادم.")
        url = self.base_url + "/api/v1/" + endpoint
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0),
                                         follow_redirects=False, trust_env=False) as client:
                response = await client.request(
                    method, url, headers={
                        "Authorization": f"token {self.token}",
                        "Accept": "application/json",
                    }, json=json, params=params)
        except httpx.RequestError as exc:
            raise GiteaError(503, "تعذر الاتصال بخدمة Gitea المحلية") from exc
        if response.status_code >= 400:
            if response.status_code in (401, 403):
                raise GiteaError(503, "رمز Gitea لا يملك الصلاحيات المطلوبة")
            if response.status_code == 404:
                raise GiteaError(404, "العنصر غير موجود في مستودع Gitea")
            if response.status_code in (409, 422):
                raise GiteaError(409, "تعارض الإصدار أو الملف موجود مسبقًا؛ حدّث المحتوى ثم حاول مجددًا")
            raise GiteaError(502, f"فشلت عملية Gitea (HTTP {response.status_code})")
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise GiteaError(502, "استجابة Gitea غير صالحة") from exc

    def _repo_prefix(self, name: str) -> str:
        validated_repo_name(name)
        return f"repos/{quote(self.owner, safe='')}/{quote(name, safe='')}"

    async def create_repo(self, name: str, description: str) -> dict:
        validated_repo_name(name)
        return await self._call("POST", "user/repos", json={
            "name": name, "description": description[:240],
            "private": True, "auto_init": True,
            "default_branch": "main",
        })

    async def set_archived(self, name: str, archived: bool) -> dict:
        """Archive/unarchive a private repository without losing Git history."""
        if not isinstance(archived, bool):
            raise ValueError("Archived flag must be boolean")
        result = await self._call(
            "PATCH", self._repo_prefix(name), json={"archived": archived}
        )
        if not isinstance(result, dict) or result.get("archived") is not archived:
            raise GiteaError(502, "Gitea did not confirm requested archive state")
        return {"archived": archived, "name": name}

    async def delete_repo(self, name: str):
        await self._call("DELETE", self._repo_prefix(name))

    async def entries(self, name: str, path: str = "") -> list[dict]:
        path = validate_path(path, allow_root=True)
        endpoint = self._repo_prefix(name) + "/contents"
        if path:
            endpoint += "/" + quote(path, safe="/")
        payload = await self._call("GET", endpoint, params={"ref": "main"})
        if isinstance(payload, list):
            return [{"name": e.get("name"), "path": e.get("path"), "type": e.get("type"),
                     "size": e.get("size"), "sha": e.get("sha")} for e in payload]
        if isinstance(payload, dict):
            return [{"name": payload.get("name"), "path": payload.get("path"),
                     "type": payload.get("type"), "size": payload.get("size"),
                     "sha": payload.get("sha")}]
        raise GiteaError(502, "تعذر قراءة قائمة الملفات")

    async def read_file(self, name: str, path: str) -> dict:
        path = validate_path(path)
        item = await self._call(
            "GET", self._repo_prefix(name) + "/contents/" + quote(path, safe="/"),
            params={"ref": "main"})
        if not isinstance(item, dict) or item.get("type") != "file":
            raise GiteaError(422, "المسار ليس ملفًا")
        if item.get("size", 0) > MAX_FILE_BYTES:
            raise GiteaError(413, "حجم الملف أكبر من حد المعاينة")
        if item.get("encoding") != "base64":
            raise GiteaError(415, "صيغة الملف غير مدعومة في معاينة Gitea")
        try:
            raw = base64.b64decode(item.get("content", ""), validate=False)
        except (ValueError, base64.binascii.Error) as exc:
            raise GiteaError(502, "تعذر فك محتوى الملف") from exc
        if len(raw) > MAX_FILE_BYTES:
            raise GiteaError(413, "حجم الملف أكبر من الحد المسموح")
        return {"path": path, "sha": item.get("sha"), "size": len(raw), "data": raw}

    async def write_file(self, name: str, path: str, data: bytes, *,
                         sha: str | None, message: str):
        path = validate_path(path)
        if len(data) > MAX_FILE_BYTES:
            raise GiteaError(413, "حجم الملف يتجاوز 2 ميغابايت")
        if not 3 <= len(message.strip()) <= 240:
            raise ValueError("Commit message must contain 3–240 characters")
        payload = {"content": base64.b64encode(data).decode("ascii"),
                   "message": message.strip(), "branch": "main"}
        if sha is not None:
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("Invalid source revision SHA")
            payload["sha"] = sha
            return await self._call(
                "PUT", self._repo_prefix(name) + "/contents/" + quote(path, safe="/"),
                json=payload)
        return await self._call(
            "POST", self._repo_prefix(name) + "/contents/" + quote(path, safe="/"),
            json=payload)

    async def delete_file(self, name: str, path: str, sha: str, message: str):
        path = validate_path(path)
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid source revision SHA")
        return await self._call("DELETE",
            self._repo_prefix(name) + "/contents/" + quote(path, safe="/"),
            json={"sha": sha, "message": message[:240], "branch": "main"})

    async def rename_file(self, name: str, old_path: str, new_path: str,
                          *, sha: str, message: str) -> dict:
        """Perform a safe, single-commit Gitea rename with optimistic locking."""
        old_path = validate_path(old_path)
        new_path = validate_path(new_path)
        if old_path == new_path:
            raise ValueError("The destination path must differ from the original")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid source revision SHA")
        if not 3 <= len(message.strip()) <= 240:
            raise ValueError("Invalid commit message")
        current = await self.read_file(name, old_path)
        if current["sha"] != sha:
            raise GiteaError(409, "تغيّر الملف الأصلي، افتح آخر إصدار ثم حاول النقل.")
        # Reject existing destinations before sending the atomic change request.
        try:
            await self.read_file(name, new_path)
        except GiteaError as exc:
            if exc.status != 404:
                if exc.status in (413, 415, 422):
                    raise GiteaError(409, "مسار الوجهة موجود بالفعل") from exc
                raise
        else:
            raise GiteaError(409, "لا يمكن الاستبدال: ملف الوجهة موجود بالفعل")
        return await self._call("POST", self._repo_prefix(name) + "/contents",
                                json={"branch": "main", "message": message.strip(),
                                      "files": [{"operation": "rename", "path": new_path,
                                                 "from_path": old_path, "sha": sha}]})

    async def search_paths(self, name: str, query: str, *, max_pages: int = 5) -> dict:
        """Bounded filename/path discovery using Gitea's paginated recursive Git tree."""
        validated_repo_name(name)
        search = query.strip().casefold()
        if not (2 <= len(search) <= 100):
            raise ValueError("Search text must contain 2–100 characters")
        matches = []
        scanned = 0
        complete = True
        for page in range(1, max_pages + 1):
            result = await self._call(
                "GET", self._repo_prefix(name) + "/git/trees/main",
                params={"recursive": "true", "page": page, "per_page": 100},
            )
            entries = result.get("tree", [])
            if not isinstance(entries, list):
                raise GiteaError(502, "Invalid Gitea tree response")
            for item in entries:
                path = item.get("path")
                if (item.get("type") != "blob" or not isinstance(path, str)
                        or len(path) > 500):
                    continue
                scanned += 1
                if search in path.casefold():
                    matches.append({"path": path, "size": item.get("size"),
                                    "sha": item.get("sha"), "type": "file"})
            if not result.get("truncated", False):
                break
            if page == max_pages:
                complete = False
        return {"matches": matches, "complete": complete, "scanned": scanned}

    async def commits(self, name: str) -> list[dict]:
        items = await self._call("GET", self._repo_prefix(name) + "/commits",
                                 params={"sha": "main", "limit": 20})
        return [{"sha": e.get("sha"), "message": e.get("commit", {}).get("message", ""),
                 "date": e.get("commit", {}).get("author", {}).get("date", "")}
                for e in items[:20]] if isinstance(items, list) else []
