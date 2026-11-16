"""Dry-run restoration into disposable Docker volumes and PostgreSQL containers.

Only creates randomly named resources; never mounts or modifies live Compose
volumes. Requires a verified version-2 backup from backup_local.py.
"""
import secrets
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from scripts.backup_local import verify_manifest


def docker(*args, capture=False):
    return subprocess.run(["docker", *args], check=True, text=True, capture_output=capture)


def safe_archive(path: Path):
    """Reject links, special files and paths escaping the isolated target."""
    with tarfile.open(path, "r:gz") as archive:
        count = 0
        for item in archive:
            if (item.name.startswith("/") or ".." in item.name.split("/")
                    or not (item.isfile() or item.isdir())
                    or item.issym() or item.islnk()):
                raise ValueError("Unsafe archive entry: " + item.name)
            count += 1
        return count


def restore_database(container, volume, directory, dump):
    password = secrets.token_urlsafe(24)
    docker("run", "-d", "--name", container, "--network", "none",
           "-e", "POSTGRES_PASSWORD=" + password,
           "-v", volume + ":/var/lib/postgresql/data",
           "-v", str(directory) + ":/backup:ro", "postgres:17-alpine")
    for attempt in range(50):
        result = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "postgres"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Disposable PostgreSQL did not become ready")
    docker("exec", container, "pg_restore", "--exit-on-error",
           "--no-owner", "--no-acl", "-U", "postgres",
           "-d", "postgres", "/backup/" + dump)
    table = "engineering_projects" if dump == "app_postgres.dump" else "repository"
    query = 'SELECT COUNT(*) FROM "' + table + '"'
    result = docker("exec", container, "psql", "-U", "postgres", "-d", "postgres",
                    "-At", "-c", query, capture=True)
    return int(result.stdout.strip())


def restore_volume(volume, directory, file):
    members = safe_archive(directory / file)
    docker("run", "--rm", "--network", "none",
           "-v", volume + ":/restored",
           "-v", str(directory) + ":/backup:ro", "alpine:3.21",
           "tar", "-xzf", "/backup/" + file, "-C", "/restored")
    result = docker("run", "--rm", "--network", "none",
                    "-v", volume + ":/restored:ro", "alpine:3.21",
                    "sh", "-c", "find /restored -type f | wc -l", capture=True)
    return {"archive_members": members, "restored_files": int(result.stdout.strip())}


def rehearse(directory: Path):
    directory = directory.resolve(strict=True)
    manifest = verify_manifest(directory)
    if manifest["format"] != 2:
        raise RuntimeError("Full restore rehearsal requires model-inclusive v2 backup")
    for name in ("gitea_data.tar.gz", "trained_models.tar.gz"):
        safe_archive(directory / name)
    prefix = "lab_restore_" + secrets.token_hex(6)
    vols = {k: prefix + "_" + k for k in ("app", "gitea", "git", "models")}
    containers = []
    created_volumes = []
    try:
        for volume in vols.values():
            docker("volume", "create", volume)
            created_volumes.append(volume)
        output = {}
        for key, filename in (("app", "app_postgres.dump"),
                              ("gitea", "gitea_postgres.dump")):
            container = prefix + "_" + key
            # Record name before starting, in case startup partially succeeds.
            containers.append(container)
            output[key + "_rows"] = restore_database(container, vols[key], directory, filename)
        output["git"] = restore_volume(vols["git"], directory, "gitea_data.tar.gz")
        output["models"] = restore_volume(vols["models"], directory, "trained_models.tar.gz")
        print("PASS: isolated databases and Git/model data restored:", output)
        return output
    finally:
        for name in containers:
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        for name in created_volumes:
            subprocess.run(["docker", "volume", "rm", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.rehearse_restore BACKUP_DIR")
    rehearse(Path(sys.argv[1]))
