# Local training-data cleanup

The Engineering AI Lab stores engineering training data in PostgreSQL and in
the Docker `trained_models` volume. Deleting SQL rows alone does not erase
the datasets embedded in checkpoint and training run directories.

## Use the dashboard

1. Log in to the local web app.
2. Open **بيانات التدريب**.
3. Select **طلب حذف جميع بيانات التدريب**.
4. Confirm the destructive action twice.
5. Use the training-panel refresh action to view the cleanup status.

Only the logged-in account's training data is targeted. The request is
queued in PostgreSQL and executed by the isolated `training-worker` service,
which owns the writable `/app/models` volume. The web server never receives
volume write access. A cleanup request is refused while this account has
queued or running training jobs, and new training jobs are refused while
cleanup is queued/running.

Cleanup scans **only** numeric `run-<job_id>` folders recorded by that
account's training-job entries. It validates the IDs, refuses symlink
directories, and will not remove the root volume or arbitrary paths. It
removes the example corpus, held-out records, logs, checkpoint, and metrics
from each removed run folder, then removes corresponding SQL training
records. A worker restart requeues interrupted requests; a failed request
can be submitted again after addressing the error.

### What is not removed

- Gitea repositories, project files or Git commit history.
- The global example starter dataset included in the source tree.
- A legacy `/app/models/checkpoint.pt` created by manual model training
  outside the managed `run-<job_id>` pipeline.
- External backup copies of PostgreSQL, Gitea or the model volume.
- Cached copies held by external tools, host snapshots or hardware backups.

Deleting the entire account is **still disabled** until independent Gitea
project cleanup and full artifact lifecycle are implemented. Logging out
only invalidates the current session.

The operation is destructive and irreversible; export anything needed before
requesting deletion. Keep the app restricted to localhost and verify cleanup
on the local Docker host before treating it as a privacy guarantee.
