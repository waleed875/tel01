"""Consistent local Docker Compose backup of Engineering AI Lab + Gitea.

Run from the project's root on a trusted host: python scripts/backup_local.py
Requires Docker Compose, .env configured and a healthy running stack.

This script deliberately creates backups only. Restore must be rehearsed
using a separate, carefully reviewed procedure; never restore to a live stack.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SERVICES_TO_STOP = ("web", "training-worker", "gitea")
FILES = {
    "app_postgres.dump": ["exec", "-T", "postgres", "sh", "-c",
                          'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
    "gitea_postgres.dump": ["exec", "-T", "gitea-db", "sh", "-c",
                            'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
    "gitea_data.tar.gz": ["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar",
                          "gitea", "-C", "/data", "-czf", "-", "."],
}
SAFE_BASE = Path("local_backups")


def compose(*arguments, **kwargs):
    return subprocess.run(["docker", "compose", *arguments], check=True, **kwargs)


def stream_compose_dump(arguments: list[str], output: Path):
    with output.open("wb") as handle:
        process = subprocess.run(
            ["docker", "compose", *arguments], stdout=handle,
            stderr=subprocess.PIPE, check=False,
        )
    if process.returncode:
        output.unlink(missing_ok=True)
        raise RuntimeError("Docker backup command failed: " +
                           process.stderr.decode("utf-8", "replace")[-1200:])
    if output.stat().st_size < 128:
        raise RuntimeError("Backup file unexpectedly empty: " + output.name)


def sha256sum(path: Path):
    hash_value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return hash_value.hexdigest()


def backup(directory: Path):
    if not Path(".env").is_file():
        raise RuntimeError("A local .env file is required")
    if directory.exists():
        raise FileExistsError("Backup directory already exists")
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Prevent accidental permission leaks in the directory created by this process.
    old_umask = os.umask(0o077)
    try:
        directory.mkdir(mode=0o700)
    finally:
        os.umask(old_umask)
    stopped = False
    try:
        compose("stop", *SERVICES_TO_STOP, stdout=subprocess.DEVNULL)
        stopped = True
        for filename, command in FILES.items():
            print(f"Backing up {filename}", flush=True)
            stream_compose_dump(command, directory / filename)
        manifest = {
            "format": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "description": "Local Engineering AI Lab and Gitea data backup",
            "files": {},
        }
        for filename in FILES:
            target = directory / filename
            manifest["files"][filename] = {
                "size": target.stat().st_size,
                "sha256": sha256sum(target),
            }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        verify_manifest(directory)
        print("Backup checksums validated", flush=True)
    finally:
        if stopped:
            # Start services even if a dump fails. Failing to restart is surfaced.
            compose("start", *SERVICES_TO_STOP, stdout=subprocess.DEVNULL)


def verify_manifest(directory: Path):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1:
        raise RuntimeError("Unknown backup manifest version")
    if set(manifest["files"]) != set(FILES):
        raise RuntimeError("Incomplete backup file set")
    for filename, info in manifest["files"].items():
        target = directory / filename
        if not target.is_file() or target.stat().st_size != info["size"]:
            raise RuntimeError("Backup file missing or size mismatch: " + filename)
        if sha256sum(target) != info["sha256"]:
            raise RuntimeError("Backup integrity check failed: " + filename)
    return True


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify_manifest(Path(sys.argv[2]))
        print("All backup checksums match")
        return
    if len(sys.argv) != 1:
        raise SystemExit("Usage: python scripts/backup_local.py [verify BACKUP_DIR]")
    target = SAFE_BASE / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup(target)
    print(f"Backup saved at {target} (store offline securely; never commit)")


if __name__ == "__main__":
    main()
