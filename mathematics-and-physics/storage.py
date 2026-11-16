"""Local SQLite student profiles, quiz results, chat context, and AI quotas."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

VALID_LEVELS = {'beginner', 'intermediate', 'highschool', 'university'}
VALID_SUBJECTS = {'math', 'physics'}


class Storage:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, level TEXT NOT NULL DEFAULT 'intermediate',
                    subject TEXT NOT NULL DEFAULT 'math', correct INTEGER NOT NULL DEFAULT 0,
                    attempted INTEGER NOT NULL DEFAULT 0, last_question TEXT
                );
                CREATE TABLE IF NOT EXISTS active_quiz (
                    user_id INTEGER PRIMARY KEY, question_id TEXT NOT NULL,
                    answered INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_usage (
                    user_id INTEGER NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, day)
                );
            ''')

    def _connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def ensure(self, user_id: int):
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO users(id) VALUES (?)', (user_id,))

    def profile(self, user_id: int):
        self.ensure(user_id)
        with self._connect() as db:
            row = db.execute('SELECT level, subject, correct, attempted, last_question FROM users WHERE id=?', (user_id,)).fetchone()
        return {'level': row[0], 'subject': row[1], 'correct': row[2], 'attempted': row[3], 'last_question': row[4]}

    def set_level(self, user_id: int, level: str):
        if level not in VALID_LEVELS:
            raise ValueError('Invalid level')
        self.ensure(user_id)
        with self._connect() as db:
            db.execute('UPDATE users SET level=? WHERE id=?', (level, user_id))

    def set_subject(self, user_id: int, subject: str):
        if subject not in VALID_SUBJECTS:
            raise ValueError('Invalid subject')
        self.ensure(user_id)
        with self._connect() as db:
            db.execute('UPDATE users SET subject=? WHERE id=?', (subject, user_id))

    def set_active_quiz(self, user_id: int, question_id: str):
        self.ensure(user_id)
        with self._connect() as db:
            db.execute('''INSERT INTO active_quiz(user_id, question_id, answered)
                VALUES (?, ?, 0) ON CONFLICT(user_id) DO UPDATE SET
                question_id=excluded.question_id, answered=0''', (user_id, question_id))
            db.execute('UPDATE users SET last_question=? WHERE id=?', (question_id, user_id))

    def grade_quiz(self, user_id: int, question_id: str, correct: bool) -> bool:
        """Atomically accept at most one answer to the active quiz."""
        with self._connect() as db:
            cursor = db.execute('''UPDATE active_quiz SET answered=1
                WHERE user_id=? AND question_id=? AND answered=0''', (user_id, question_id))
            if cursor.rowcount != 1:
                return False
            db.execute('UPDATE users SET attempted=attempted+1, correct=correct+? WHERE id=?', (int(correct), user_id))
        return True

    def recent_history(self, user_id: int, limit: int = 6):
        with self._connect() as db:
            rows = db.execute('SELECT role, content FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?', (user_id, limit)).fetchall()
        return [{'role': role, 'content': content} for role, content in reversed(rows)]

    def add_exchange(self, user_id: int, question: str, answer: str):
        with self._connect() as db:
            db.execute('INSERT INTO history(user_id, role, content) VALUES (?, ?, ?)', (user_id, 'user', question[:1400]))
            db.execute('INSERT INTO history(user_id, role, content) VALUES (?, ?, ?)', (user_id, 'assistant', answer[:3500]))
            db.execute('''DELETE FROM history WHERE user_id=? AND id NOT IN
                (SELECT id FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10)''', (user_id, user_id))

    def clear_history(self, user_id: int):
        with self._connect() as db:
            db.execute('DELETE FROM history WHERE user_id=?', (user_id,))

    def claim_quota(self, user_id: int, daily_limit: int) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as db:
            db.execute('''INSERT OR IGNORE INTO ai_usage(user_id,day,count) VALUES(?,?,0)''', (user_id, today))
            cur = db.execute('''UPDATE ai_usage SET count=count+1
                WHERE user_id=? AND day=? AND count<?''', (user_id, today, daily_limit))
            return cur.rowcount == 1

    def release_quota(self, user_id: int):
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as db:
            db.execute('UPDATE ai_usage SET count=max(0,count-1) WHERE user_id=? AND day=?', (user_id, today))

    def delete_user(self, user_id: int):
        with self._connect() as db:
            for table, col in [('users', 'id'), ('active_quiz', 'user_id'), ('history', 'user_id'), ('ai_usage', 'user_id')]:
                db.execute(f'DELETE FROM {table} WHERE {col}=?', (user_id,))
