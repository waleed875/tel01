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
            db.execute("""CREATE INDEX IF NOT EXISTS training_examples_user_idx
                ON training_examples(user_id, id DESC)""")
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

    def delete_user(self, user_id: int):
        with self._connect() as db:
            for table, col in (("training_examples", "user_id"), ("web_sessions", "user_id"), ("users", "id"), ("active_quiz", "user_id"), ("history", "user_id"), ("ai_usage", "user_id")):
                db.execute(f"DELETE FROM {table} WHERE {col}=%s", (user_id,))
