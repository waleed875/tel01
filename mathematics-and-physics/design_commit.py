"""Owner-reviewed website proposals; verification before one atomic Gitea commit.

Never trust client-submitted generated file contents. Rebuild files on the
server and bind a short-lived HMAC to their exact current Git blob revisions.
"""
import base64
import difflib
import hashlib
import hmac
import json
import re
import secrets
import time

from gitea_client import GiteaClient, GiteaError, MAX_FILE_BYTES, validate_path
from site_builder import build_website

_PROPOSAL_KEY = secrets.token_bytes(32)
_PROPOSAL_TTL = 10 * 60
_MAX_DIFF_CHARS = 15000


def project_site_paths(folder: str) -> tuple[str, str]:
    folder = validate_path(folder)
    if len(folder) > 450:
        raise ValueError("Destination directory is too long")
    if folder.split("/")[0] not in ("sites", "websites"):
        raise ValueError("The destination must be inside sites/ or websites/")
    if len(folder.split("/")) < 2:
        raise ValueError("Use a project subdirectory such as sites/my-website")
    return folder + "/index.html", folder + "/style.css"


def _digest(user_id: int, project_id: int, config: dict,
            files: list[dict], timestamp: int) -> str:
    payload = json.dumps({
        "user": user_id, "project": project_id, "config": config,
        "files": [
            {"path": row["path"], "sha": row["sha"],
             "content_sha256": hashlib.sha256(row["content"].encode("utf-8")).hexdigest()}
            for row in files
        ], "expires": timestamp,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_PROPOSAL_KEY, payload, hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"


async def build_proposal(client: GiteaClient, repo_name: str, *, user_id: int,
                         project_id: int, config: dict, expires_at: int | None = None):
    target_paths = project_site_paths(config["directory"])
    generated = build_website(config["title"], config["description"],
                              config["style"], config["sections"])
    files = []
    for target, item in zip(target_paths, generated["files"]):
        content = item["content"]
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Generated website file is too large")
        try:
            previous = await client.read_file(repo_name, target)
        except GiteaError as exc:
            if exc.status != 404:
                raise
            previous = None
        if previous:
            try:
                old_text = previous["data"].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise GiteaError(409, "Destination file is binary; cannot overwrite") from exc
            revision = previous["sha"]
        else:
            old_text, revision = "", None
        action = "unchanged" if previous and old_text == content else (
            "update" if previous else "create")
        diff = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile="a/" + target if previous else "/dev/null",
            tofile="b/" + target, n=3))
        if len(diff) > _MAX_DIFF_CHARS:
            raise ValueError("Diff exceeds the safe review limit; review the files manually")
        files.append({"path": target, "sha": revision, "content": content,
                      "operation": action, "diff": diff})
    expires_at = int(time.time()) + _PROPOSAL_TTL if expires_at is None else expires_at
    return {"files": files,
            "fingerprint": _digest(user_id, project_id, config, files, expires_at),
            "expires_at": expires_at,
            "can_apply": any(item["operation"] != "unchanged" for item in files)}


async def commit_proposal(client: GiteaClient, repo_name: str, *,
                          user_id: int, project_id: int, config: dict,
                          fingerprint: str):
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9]{10,12}\.[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid proposal approval token")
    expires_at = int(fingerprint.split(".", 1)[0])
    if expires_at < int(time.time()) or expires_at > int(time.time()) + _PROPOSAL_TTL:
        raise GiteaError(409, "Proposal expired; review a new diff before saving")
    proposal = await build_proposal(client, repo_name, user_id=user_id,
                                    project_id=project_id, config=config,
                                    expires_at=expires_at)
    if not hmac.compare_digest(proposal["fingerprint"], fingerprint):
        raise GiteaError(409, "Files or source revisions have changed; review a new diff")
    if not proposal["can_apply"]:
        raise GiteaError(409, "No changes to commit")
    operations = []
    for item in proposal["files"]:
        if item["operation"] == "unchanged":
            continue
        payload = {
            "operation": item["operation"], "path": item["path"],
            "content": base64.b64encode(item["content"].encode("utf-8")).decode("ascii"),
        }
        if item["sha"] is not None:
            if not re.fullmatch(r"[0-9a-f]{40}", item["sha"]):
                raise GiteaError(409, "Invalid Git blob SHA")
            payload["sha"] = item["sha"]
        operations.append(payload)
    # Gitea applies a multi-file contents operation as one commit. A conflict
    # at submission is reported to the user, not retried or force-pushed.
    result = await client._call(
        "POST", client._repo_prefix(repo_name) + "/contents",
        json={"branch": "main", "message": "Build reviewed website scaffold",
              "files": operations})
    return {"ok": True, "changed_paths": [row["path"] for row in operations],
            "result": result}
