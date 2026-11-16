"""PostgreSQL persistence for tutor profiles, exercises and conversations."""
from datetime import datetime, timezone
import hashlib
import psycopg
from psycopg.rows import dict_row

VALID_LEVELS = {"beginner", "intermediate", "highschool", "university"}
VALID_SUBJECTS = {"math", "physics", "software", "electronics"}

class Storage:
    def __init__(self, database_url: str):
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must point to PostgreSQL")
        self.database_url = database_url
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY, level TEXT NOT NULL DEFAULT 'intermediate',
                subject TEXT NOT NULL DEFAULT 'math', correct INTEGER NOT NULL DEFAULT 0,
                attempted INTEGER NOT NULL DEFAULT 0, last_question TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS active_quiz (
                user_id BIGINT PRIMARY KEY, question_id TEXT NOT NULL,
                answered BOOLEAN NOT NULL DEFAULT FALSE)""")
            db.execute("""CREATE TABLE IF NOT EXISTS history (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS history_user_id_id_idx ON history(user_id, id DESC)""")
            db.execute("""CREATE SEQUENCE IF NOT EXISTS web_user_ids START -1 INCREMENT -1 MINVALUE -9223372036854775808""")
            db.execute("""CREATE TABLE IF NOT EXISTS web_sessions (token_hash TEXT PRIMARY KEY, user_id BIGINT UNIQUE NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            db.execute("""CREATE TABLE IF NOT EXISTS training_examples (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                subject TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            db.execute("""ALTER TABLE training_examples ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ""")
            db.execute("""CREATE INDEX IF NOT EXISTS training_examples_user_idx
                ON training_examples(user_id, id DESC)""")
            db.execute("""CREATE TABLE IF NOT EXISTS training_jobs (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued',
                steps INTEGER NOT NULL,
                seed INTEGER NOT NULL,
                training_count INTEGER NOT NULL,
                validation_count INTEGER NOT NULL,
                snapshot_sha256 TEXT NOT NULL,
                snapshot_json JSONB NOT NULL,
                train_loss DOUBLE PRECISION,
                validation_loss DOUBLE PRECISION,
                checkpoint_path TEXT,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ
            )""")
            db.execute("""ALTER TABLE training_jobs ADD COLUMN IF NOT EXISTS heldout_loss DOUBLE PRECISION""")
            db.execute("""CREATE TABLE IF NOT EXISTS active_models (
                user_id BIGINT PRIMARY KEY,
                job_id BIGINT NOT NULL REFERENCES training_jobs(id)
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS training_jobs_user_idx ON training_jobs(user_id,id DESC)""")
            db.execute("""CREATE TABLE IF NOT EXISTS training_metrics (
                job_id BIGINT NOT NULL REFERENCES training_jobs(id) ON DELETE CASCADE,
                step INTEGER NOT NULL,
                train_loss DOUBLE PRECISION,
                validation_loss DOUBLE PRECISION,
                PRIMARY KEY(job_id, step)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS engineering_projects (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                repo_name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            db.execute("""ALTER TABLE engineering_projects ADD COLUMN IF NOT EXISTS
                deletion_state TEXT NOT NULL DEFAULT 'active'""")
            db.execute("""CREATE INDEX IF NOT EXISTS engineering_projects_owner_idx
                ON engineering_projects(user_id,id DESC)""")
            db.execute("""CREATE TABLE IF NOT EXISTS ai_usage (
                user_id BIGINT NOT NULL, day DATE NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, day))""")

    def _connect(self):
        return psycopg.connect(self.database_url, autocommit=False, row_factory=dict_row, connect_timeout=10)

    def get_or_create_web_session(self, token: str) -> int:
        """Keep random session tokens out of the database; store only SHA-256."""
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        with self._connect() as db:
            row = db.execute("""INSERT INTO web_sessions(token_hash,user_id)
                VALUES(%s, nextval('web_user_ids'))
                ON CONFLICT(token_hash) DO UPDATE SET token_hash=excluded.token_hash
                RETURNING user_id""", (digest,)).fetchone()
            return row["user_id"]

    def ensure(self, user_id: int):
        with self._connect() as db:
            db.execute("INSERT INTO users(id) VALUES(%s) ON CONFLICT DO NOTHING", (user_id,))

    def profile(self, user_id: int):
        self.ensure(user_id)
        with self._connect() as db:
            return db.execute("SELECT level, subject, correct, attempted, last_question FROM users WHERE id=%s", (user_id,)).fetchone()

    def set_level(self, user_id: int, level: str):
        if level not in VALID_LEVELS:
            raise ValueError("Invalid level")
        self.ensure(user_id)
        with self._connect() as db:
            db.execute("UPDATE users SET level=%s WHERE id=%s", (level, user_id))

    def set_subject(self, user_id: int, subject: str):
        if subject not in VALID_SUBJECTS:
            raise ValueError("Invalid subject")
        self.ensure(user_id)
        with self._connect() as db:
            db.execute("UPDATE users SET subject=%s WHERE id=%s", (subject, user_id))

    def set_active_quiz(self, user_id: int, question_id: str):
        self.ensure(user_id)
        with self._connect() as db:
            db.execute("""INSERT INTO active_quiz(user_id,question_id,answered) VALUES(%s,%s,FALSE)
                ON CONFLICT(user_id) DO UPDATE SET question_id=excluded.question_id,answered=FALSE""", (user_id, question_id))
            db.execute("UPDATE users SET last_question=%s WHERE id=%s", (question_id, user_id))

    def grade_quiz(self, user_id: int, question_id: str, correct: bool) -> bool:
        with self._connect() as db:
            row = db.execute("""UPDATE active_quiz SET answered=TRUE
                WHERE user_id=%s AND question_id=%s AND answered=FALSE RETURNING user_id""",
                (user_id, question_id)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE users SET attempted=attempted+1,correct=correct+%s WHERE id=%s", (int(correct), user_id))
            return True

    def recent_history(self, user_id: int, limit: int = 6):
        with self._connect() as db:
            rows = db.execute("SELECT role,content FROM history WHERE user_id=%s ORDER BY id DESC LIMIT %s", (user_id, limit)).fetchall()
            return list(reversed(rows))

    def add_exchange(self, user_id: int, question: str, answer: str):
        with self._connect() as db:
            db.execute("INSERT INTO history(user_id,role,content) VALUES(%s,'user',%s)", (user_id, question[:1400]))
            db.execute("INSERT INTO history(user_id,role,content) VALUES(%s,'assistant',%s)", (user_id, answer[:3500]))
            db.execute("""DELETE FROM history WHERE user_id=%s AND id NOT IN
                (SELECT id FROM history WHERE user_id=%s ORDER BY id DESC LIMIT 10)""", (user_id, user_id))

    def clear_history(self, user_id: int):
        with self._connect() as db:
            db.execute("DELETE FROM history WHERE user_id=%s", (user_id,))

    def claim_quota(self, user_id: int, daily_limit: int) -> bool:
        today = datetime.now(timezone.utc).date()
        with self._connect() as db:
            db.execute("INSERT INTO ai_usage(user_id,day,count) VALUES(%s,%s,0) ON CONFLICT DO NOTHING", (user_id, today))
            row = db.execute("""UPDATE ai_usage SET count=count+1
                WHERE user_id=%s AND day=%s AND count<%s RETURNING count""",
                (user_id, today, daily_limit)).fetchone()
            return row is not None

    def release_quota(self, user_id: int):
        today = datetime.now(timezone.utc).date()
        with self._connect() as db:
            db.execute("UPDATE ai_usage SET count=GREATEST(0,count-1) WHERE user_id=%s AND day=%s", (user_id, today))


    def training_examples(self, user_id: int, limit: int = 100):
        with self._connect() as db:
            return db.execute(
                """SELECT id, subject, question, answer, status, created_at
                   FROM training_examples WHERE user_id=%s ORDER BY id DESC LIMIT %s""",
                (user_id, min(max(limit, 1), 250)),
            ).fetchall()

    def review_training_example(self, user_id: int, example_id: int, action: str):
        """Explicitly approve or revoke an example owned by the current session."""
        if action not in ("approved", "draft"):
            raise ValueError("Invalid review action")
        with self._connect() as db:
            return db.execute(
                """UPDATE training_examples SET status=%s,
                   reviewed_at=CASE WHEN %s='approved' THEN NOW() ELSE NULL END
                   WHERE id=%s AND user_id=%s
                   RETURNING id, subject, question, answer, status, created_at, reviewed_at""",
                (action, action, example_id, user_id),
            ).fetchone()

    def training_counts(self, user_id: int):
        with self._connect() as db:
            result = db.execute(
                """SELECT COUNT(*) FILTER(WHERE status='draft') AS draft,
                          COUNT(*) FILTER(WHERE status='approved') AS approved
                   FROM training_examples WHERE user_id=%s""",
                (user_id,),
            ).fetchone()
            return {"draft": result["draft"], "approved": result["approved"]}

    def approved_training_examples(self, user_id: int):
        with self._connect() as db:
            return db.execute(
                """SELECT id, subject, question, answer FROM training_examples
                   WHERE user_id=%s AND status='approved'
                   ORDER BY id ASC""",
                (user_id,),
            ).fetchall()

    def training_example_count(self, user_id: int):
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM training_examples WHERE user_id=%s",
                (user_id,),
            ).fetchone()
            return row["count"]

    def add_training_example(self, user_id: int, subject: str, question: str, answer: str):
        if subject not in VALID_SUBJECTS:
            raise ValueError("Invalid subject")
        self.ensure(user_id)
        with self._connect() as db:
            return db.execute(
                """INSERT INTO training_examples(user_id, subject, question, answer)
                   VALUES(%s, %s, %s, %s)
                   RETURNING id, subject, question, answer, status, created_at""",
                (user_id, subject, question, answer),
            ).fetchone()

    def delete_training_example(self, user_id: int, example_id: int) -> bool:
        with self._connect() as db:
            row = db.execute(
                "DELETE FROM training_examples WHERE user_id=%s AND id=%s RETURNING id",
                (user_id, example_id),
            ).fetchone()
            return row is not None

    def create_training_job(self, user_id: int, steps: int, seed: int):
        """Snapshot approved examples atomically; no drafts can enter the queue."""
        import hashlib
        import json
        if not (50 <= steps <= 300 and 0 <= seed <= 2147483647):
            raise ValueError("Training configuration outside safe limits")
        with self._connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
            pending = db.execute(
                """SELECT COUNT(*) AS n FROM training_jobs
                   WHERE user_id=%s AND state IN ('queued','running')""",
                (user_id,),
            ).fetchone()["n"]
            if pending:
                raise ValueError("An unfinished training run already exists")
            examples = db.execute(
                """SELECT id,subject,question,answer FROM training_examples
                   WHERE user_id=%s AND status='approved' ORDER BY id""",
                (user_id,),
            ).fetchall()
            if len(examples) < 12:
                raise ValueError("At least 12 approved examples are required")
            # This snapshot survives subsequent edits to the source examples.
            snapshot = json.dumps(examples, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
            row = db.execute(
                """INSERT INTO training_jobs(user_id,steps,seed,training_count,
                   validation_count,snapshot_sha256,snapshot_json)
                   VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)
                   RETURNING id,state,steps,seed,training_count,validation_count,
                   snapshot_sha256,created_at""",
                (user_id, steps, seed, len(examples)-max(2, len(examples)//5),
                 max(2, len(examples)//5), digest, snapshot),
            ).fetchone()
            return row

    def list_training_jobs(self, user_id: int, limit: int = 30):
        with self._connect() as db:
            return db.execute(
                """SELECT id,state,steps,seed,training_count,validation_count,
                   snapshot_sha256,train_loss,validation_loss,heldout_loss,created_at,started_at,
                   finished_at,error FROM training_jobs WHERE user_id=%s
                   ORDER BY id DESC LIMIT %s""",
                (user_id, limit),
            ).fetchall()

    def training_job(self, user_id: int, job_id: int):
        with self._connect() as db:
            return db.execute(
                """SELECT id,state,steps,seed,training_count,validation_count,
                   snapshot_sha256,train_loss,validation_loss,heldout_loss,created_at,started_at,
                   finished_at,error FROM training_jobs WHERE user_id=%s AND id=%s""",
                (user_id, job_id),
            ).fetchone()

    def completed_training_job_path(self, user_id: int, job_id: int):
        """Return checkpoint metadata only for a completed run owned by this user."""
        with self._connect() as db:
            return db.execute(
                """SELECT id,checkpoint_path,heldout_loss FROM training_jobs
                   WHERE id=%s AND user_id=%s AND state='completed'
                   AND checkpoint_path IS NOT NULL""",
                (job_id, user_id),
            ).fetchone()

    def activate_training_job(self, user_id: int, job_id: int):
        """Select only a completed checkpoint belonging to the active session."""
        with self._connect() as db:
            row = db.execute(
                """SELECT id,checkpoint_path,heldout_loss FROM training_jobs
                   WHERE id=%s AND user_id=%s AND state='completed'
                   AND checkpoint_path IS NOT NULL""",
                (job_id, user_id),
            ).fetchone()
            if not row:
                return None
            db.execute(
                """INSERT INTO active_models(user_id,job_id) VALUES(%s,%s)
                   ON CONFLICT(user_id) DO UPDATE SET job_id=excluded.job_id""",
                (user_id, job_id),
            )
            return row

    def active_training_job(self, user_id: int):
        with self._connect() as db:
            return db.execute(
                """SELECT j.id,j.checkpoint_path,j.heldout_loss
                   FROM active_models a JOIN training_jobs j ON j.id=a.job_id
                   WHERE a.user_id=%s AND j.user_id=%s AND j.state='completed'""",
                (user_id, user_id),
            ).fetchone()

    def training_job_metrics(self, user_id: int, job_id: int):
        with self._connect() as db:
            return db.execute(
                """SELECT m.step,m.train_loss,m.validation_loss
                   FROM training_metrics m JOIN training_jobs j ON j.id=m.job_id
                   WHERE j.user_id=%s AND j.id=%s ORDER BY m.step""",
                (user_id, job_id),
            ).fetchall()

    def fail_interrupted_training_jobs(self):
        """A single training worker runs on this host; mark interrupted runs failed."""
        with self._connect() as db:
            db.execute(
                """UPDATE training_jobs SET state='failed',
                   error='Training worker restarted; retry with a new job',
                   finished_at=NOW() WHERE state='running'"""
            )

    def claim_training_job(self):
        """Single runner claims next queued job using row locking."""
        with self._connect() as db:
            row = db.execute(
                """SELECT id FROM training_jobs WHERE state='queued'
                   ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            db.execute(
                """UPDATE training_jobs SET state='running',started_at=NOW()
                   WHERE id=%s""", (row["id"],))
            return db.execute(
                """SELECT id,user_id,steps,seed,training_count,validation_count,
                   snapshot_sha256,snapshot_json FROM training_jobs WHERE id=%s""",
                (row["id"],),
            ).fetchone()

    def record_training_metric(self, job_id: int, step: int, train_loss: float, validation_loss: float):
        with self._connect() as db:
            db.execute(
                """INSERT INTO training_metrics(job_id,step,train_loss,validation_loss)
                   VALUES(%s,%s,%s,%s) ON CONFLICT(job_id,step)
                   DO UPDATE SET train_loss=excluded.train_loss,
                                 validation_loss=excluded.validation_loss""",
                (job_id, step, train_loss, validation_loss),
            )
            db.execute(
                """UPDATE training_jobs SET train_loss=%s,validation_loss=%s
                   WHERE id=%s AND state='running'""",
                (train_loss, validation_loss, job_id),
            )

    def finish_training_job(self, job_id: int, success: bool, checkpoint_path: str | None = None,
                            error: str | None = None, heldout_loss: float | None = None):
        with self._connect() as db:
            db.execute(
                """UPDATE training_jobs SET state=%s,checkpoint_path=%s,error=%s,
                   heldout_loss=%s,finished_at=NOW() WHERE id=%s AND state='running'""",
                ("completed" if success else "failed", checkpoint_path, (error or "")[:500],
                 heldout_loss, job_id),
            )

    def create_engineering_project(self, user_id: int, title: str, kind: str, repo_name: str):
        if kind not in {"software", "electronics", "physics", "math", "general"}:
            raise ValueError("Invalid project type")
        self.ensure(user_id)
        with self._connect() as db:
            return db.execute(
                """INSERT INTO engineering_projects(user_id,title,kind,repo_name)
                   VALUES(%s,%s,%s,%s)
                   RETURNING id,title,kind,repo_name,created_at""",
                (user_id, title, kind, repo_name),
            ).fetchone()

    def list_engineering_projects(self, user_id: int):
        with self._connect() as db:
            return db.execute(
                """SELECT id,title,kind,deletion_state,created_at FROM engineering_projects
                   WHERE user_id=%s ORDER BY id DESC LIMIT 100""",
                (user_id,),
            ).fetchall()

    def engineering_project(self, user_id: int, project_id: int):
        with self._connect() as db:
            return db.execute(
                """SELECT id,title,kind,repo_name,deletion_state,created_at FROM engineering_projects
                   WHERE user_id=%s AND id=%s""",
                (user_id, project_id),
            ).fetchone()

    def begin_engineering_project_deletion(self, user_id: int, project_id: int):
        """Keep the mapping until the remote Git repo is successfully removed."""
        with self._connect() as db:
            return db.execute(
                """UPDATE engineering_projects SET deletion_state='deleting'
                   WHERE user_id=%s AND id=%s
                   RETURNING id,repo_name,deletion_state""",
                (user_id, project_id),
            ).fetchone()

    def finish_engineering_project_deletion(self, user_id: int, project_id: int) -> bool:
        with self._connect() as db:
            result = db.execute(
                """DELETE FROM engineering_projects WHERE user_id=%s AND id=%s
                   AND deletion_state='deleting' RETURNING id""",
                (user_id, project_id),
            ).fetchone()
            return result is not None

    def delete_user(self, user_id: int):
        with self._connect() as db:
            projects = db.execute(
                "SELECT COUNT(*) AS n FROM engineering_projects WHERE user_id=%s",
                (user_id,),
            ).fetchone()["n"]
            if projects:
                raise ValueError("احذف مشاريع Gitea أولًا قبل حذف الجلسة؛ لن نفقد مرجع المستودعات.")
            db.execute("""DELETE FROM training_metrics WHERE job_id IN
                          (SELECT id FROM training_jobs WHERE user_id=%s)""", (user_id,))
            for table, col in (("active_models", "user_id"), ("training_jobs", "user_id"), ("training_examples", "user_id"), ("web_sessions", "user_id"), ("users", "id"), ("active_quiz", "user_id"), ("history", "user_id"), ("ai_usage", "user_id")):
                db.execute(f"DELETE FROM {table} WHERE {col}=%s", (user_id,))
