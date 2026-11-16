"""Offline, consistent backup of the Lab, Gitea and model Docker volumes.

Invoke from the mathematics-and-physics Compose directory on the trusted host.
All stateful write services are stopped before dumps/snapshots; the two DBs
remain running. The manual trainer must not be running.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


SERVICES_TO_STOP = ("web", "training-worker", "gitea")
FILES = {
    "app_postgres.dump": ["exec", "-T", "postgres", "sh", "-c",
                          'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
    "gitea_postgres.dump": ["exec", "-T", "gitea-db", "sh", "-c",
                            'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
    "gitea_data.tar.gz": ["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar",
                          "gitea", "-C", "/data", "-czf", "-", "."],
    "trained_models.tar.gz": ["run", "--rm", "--no-deps", "-T",
                              "--entrypoint", "tar", "training-worker",
                              "-C", "/app/models", "-czf", "-", "."],
}
LEGACY_FILES = frozenset(FILES) - {"trained_models.tar.gz"}
SAFE_BASE = Path("local_backups")


def compose(*arguments, **kwargs):
    return subprocess.run(["docker", "compose", *arguments], check=True, **kwargs)


def check_preconditions():
    if not Path(".env").is_file():
        raise RuntimeError("A local .env file is required")
    active = compose("ps", "--services", "--status", "running",
                     capture_output=True, text=True).stdout.splitlines()
    if "trainer" in active:
        raise RuntimeError("Stop the manual trainer before creating a backup")
    for name in ("postgres", "gitea-db"):
        if name not in active:
            raise RuntimeError(f"Database service {name} is not running")


def stream_compose_dump(arguments: list[str], output: Path):
    with output.open("wb") as handle:
        process = subprocess.run(["docker", "compose", *arguments],
                                 stdout=handle, stderr=subprocess.PIPE,
                                 check=False)
    if process.returncode:
        output.unlink(missing_ok=True)
        raise RuntimeError("Docker backup command failed: " +
                           process.stderr.decode("utf-8", "replace")[-1200:])
    if output.stat().st_size < 128:
        output.unlink(missing_ok=True)
        raise RuntimeError("Backup file unexpectedly empty: " + output.name)


def sha256sum(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def verify_manifest(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("format")
    if version not in (1, 2):
        raise RuntimeError("Unknown backup manifest version")
    expected = LEGACY_FILES if version == 1 else frozenset(FILES)
    if set(manifest.get("files", {})) != expected:
        raise RuntimeError("Incomplete backup file set")
    for filename, metadata in manifest["files"].items():
        file = directory / filename
        if (file.is_symlink() or not file.is_file() or
                file.stat().st_size != metadata["size"]):
            raise RuntimeError("Missing or invalid backup file: " + filename)
        if sha256sum(file) != metadata["sha256"]:
            raise RuntimeError("Backup integrity check failed: " + filename)
    if version == 1:
        print("WARNING: Legacy backup lacks trained_models; it cannot fully restore trained AI.")
    return manifest


def backup(directory: Path):
    check_preconditions()
    if directory.exists():
        raise FileExistsError("Backup directory already exists")
    directory.parent.mkdir(parents=True, exist_ok=True)
    previous_umask = os.umask(0o077)
    try:
        directory.mkdir(mode=0o700)
    finally:
        os.umask(previous_umask)
    stop_attempted = False
    try:
        stop_attempted = True
        compose("stop", *SERVICES_TO_STOP, stdout=subprocess.DEVNULL)
        for filename, command in FILES.items():
            print(f"Backing up {filename}", flush=True)
            stream_compose_dump(command, directory / filename)
        manifest = {
            "format": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "description": "Local Lab, Gitea and trained model checkpoint backup",
            "files": {
                filename: {"size": (directory / filename).stat().st_size,
                           "sha256": sha256sum(directory / filename)}
                for filename in FILES
            },
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        verify_manifest(directory)
        print("Backup checksums validated", flush=True)
    finally:
        if stop_attempted:
            # Restart even when Compose partially stopped services or a dump failed.
            compose("start", *SERVICES_TO_STOP, stdout=subprocess.DEVNULL)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "verify":
        verify_manifest(Path(sys.argv[2]))
        print("Backup checksum verification succeeded")
        return
    if len(sys.argv) != 1:
        raise SystemExit("Usage: python scripts/backup_local.py [verify BACKUP_DIR]")
    target = SAFE_BASE / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup(target)
    print(f"Backup saved to {target}; encrypt/store offline and never commit")


if __name__ == "__main__":
    main()
