"""Restore rehearsal CI: seed disposable PostgreSQL databases, create fixture
model/Git archives, then restore them into *another* set of fresh Docker volumes.
No user installation, ports, or existing Compose volumes are used.
"""
import io
import json
import secrets
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from scripts.backup_local import FILES, sha256sum
from scripts.rehearse_restore import rehearse


def docker(*args, capture=False):
    return subprocess.run(["docker", *args], check=True,
                          capture_output=capture, text=True)


def seed_dump(name: str, table: str, output: Path):
    docker("run", "-d", "--name", name, "--network", "none",
           "-e", "POSTGRES_PASSWORD=test-temporary-only", "postgres:17-alpine")
    # Postgres temporarily starts a server during init before restarting it.
    # A single pg_isready success can race with that shutdown.
    stable = 0
    for _ in range(90):
        status = subprocess.run(
            ["docker", "exec", name, "psql", "-U", "postgres",
             "-d", "postgres", "-At", "-c", "SELECT 1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        stable = stable + 1 if status.returncode == 0 and status.stdout.strip() == "1" else 0
        if stable >= 3:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Disposable seeded PostgreSQL did not become stably ready")
    docker("exec", name, "psql", "-U", "postgres", "-d", "postgres",
           "-c", f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, note TEXT)")
    docker("exec", name, "psql", "-U", "postgres", "-d", "postgres",
           "-c", f"INSERT INTO {table} VALUES (1, 'verified-fixture')")
    with output.open("wb") as stream:
        subprocess.run(["docker", "exec", name, "pg_dump", "-Fc",
                        "-U", "postgres", "postgres"],
                       stdout=stream, check=True)


def archive(path: Path, name: str, payload: bytes):
    with tarfile.open(path, "w:gz") as tar:
        meta = tarfile.TarInfo(name)
        meta.size = len(payload)
        tar.addfile(meta, io.BytesIO(payload))


def main():
    prefix = "lab_backup_seed_" + secrets.token_hex(5)
    containers = []
    try:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for label, table, filename in (
                ("app", "engineering_projects", "app_postgres.dump"),
                ("gitea", "repository", "gitea_postgres.dump"),
            ):
                container = prefix + "_" + label
                containers.append(container)
                seed_dump(container, table, base / filename)
            archive(base / "gitea_data.tar.gz",
                    "git/repositories/example.git/HEAD", b"ref: refs/heads/main\n")
            archive(base / "trained_models.tar.gz",
                    "run-47/checkpoint.pt", b"TEST_CHECKPOINT_NOT_A_REAL_MODEL")
            manifest = {
                "format": 2, "files": {
                    name: {"size": (base / name).stat().st_size,
                           "sha256": sha256sum(base / name)}
                    for name in FILES
                },
            }
            (base / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = rehearse(base)
            if result["app_rows"] != 1 or result["gitea_rows"] != 1:
                raise AssertionError("Database fixture rows did not survive restore")
            if result["git"]["restored_files"] != 1 or result["models"]["restored_files"] != 1:
                raise AssertionError("Git or model files did not survive restore")
            print("PASS: real PostgreSQL and Git/model Docker restoration in disposable volumes")
    finally:
        for container in containers:
            subprocess.run(["docker", "rm", "-f", container],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
