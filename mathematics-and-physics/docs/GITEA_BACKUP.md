# Gitea project archives and consistent local backups

## Archive a project without losing Git history

From the Engineering AI Lab project's **المشاريع العملية** section, select
**أرشفة المشروع**. Gitea marks the repository archived; the Lab allows only
browsing/downloading and blocks file edits, uploads, rename and deletion of
files until you choose **استعادة المشروع**.

The PostgreSQL project state transitions through `archiving` or
`restoring`, allowing a retry if Gitea is temporarily unavailable.
No Git commits, file content or history are erased by archiving.

A project can still be **permanently deleted** by its owner. Deletion removes
the Gitea repository and its entire Git history; archive instead if you
might need the files again.

## Back up both Gitea and the Engineering AI Lab

On the **trusted Docker host**, run from the
`mathematics-and-physics` directory with Docker Compose and Python 3:

```bash
python scripts/backup_local.py
```

This command temporarily stops `web`, `training-worker` and `gitea`,
then captures:

1. `app_postgres.dump` — Engineering AI Lab PostgreSQL database
2. `gitea_postgres.dump` — Gitea PostgreSQL database
3. `gitea_data.tar.gz` — Gitea repositories, metadata and attachments
4. `trained_models.tar.gz` — model checkpoints, run data and logs
5. `manifest.json` — file sizes and SHA-256 checksums

The services are restarted afterwards, even when the backup command fails.
Backups are saved under `local_backups/<UTC timestamp>/`, ignored by Git.
Store them encrypted offline; they include source code, records and
potentially confidential user information. **Do not commit the backups.**

To check backup integrity without touching the databases:

```bash
python scripts/backup_local.py verify local_backups/<TIMESTAMP>
```

### Important limitations

- This script validates **file checksums**, not successful database restore.
  It has not yet been validated end-to-end on the target machine.
- The `trained_models` volume is included in backup **format v2**. Legacy v1 backups lack model checkpoints. Local credentials in `.env` remain excluded; store them in encrypted offline credential storage.
- The backup does not include your host Docker installation or DNS/TLS config.
- Do not use `docker compose down -v` when preserving data; this deletes
  the named volumes.
- **Do not attempt to restore to a live production stack.** Restoration needs
  separate volumes, empty databases, version compatibility checks, and a
  rehearsal before trusting a backup. The restore workflow remains a task
  under Issue #8.

These tools are for **local maintenance**, not unattended cloud backups.

## Verify recoverability in disposable containers

Run from the project directory, after a version-2 backup:

```bash
python -m scripts.rehearse_restore local_backups/TIMESTAMP
```

The rehearsal verifies the manifest, refuses unsafe TAR entries, restores both
PostgreSQL dumps in **new disposable containers**, extracts Gitea Git data and
model checkpoints into **new disposable volumes**, queries restored database
rows and then removes only the resources it created. It never mounts, erases or
overwrites the real Compose project volumes and opens no ports.

This rehearsal does not prove the entire Gitea application can start from
a restored backup or that a trained model produces correct answers. These
require separate application-level checks on your trusted local computer.
The GitHub Actions test runs a disposable fixture restore automatically.

Never commit backups. Store them encrypted offline. Preserve the original
Gitea and database credentials separately; the archive does not include .env.
