"""Local-only password authentication, persistent sessions and bootstrap CLI.

No registration endpoint is exposed. Credentials and session secrets never
leave the local server. Authenticated user IDs are positive, distinct from
legacy anonymous IDs allocated by the negative web_user_ids sequence.
"""
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

USERNAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{2,39}$")
SESSION_SECONDS = 7 * 86400
MAX_FAILURES = 6
LOCK_SECONDS = 15 * 60


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 14 or len(password) > 128:
        raise ValueError("Password must be between 14 and 128 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14,
                           r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}".replace("\\", "")


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = encoded.split("$")
        if (algorithm, int(n), int(r), int(p)) != ("scrypt", 16384, 8, 1):
            return False
        expected = bytes.fromhex(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError, OverflowError, MemoryError):
        return False


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class AuthStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS local_accounts (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','user')),
                failed_logins INTEGER NOT NULL DEFAULT 0,
                locked_until TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES local_accounts(id) ON DELETE CASCADE,
                csrf_hash TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS auth_sessions_user_idx
                          ON auth_sessions(user_id)""")

    def connect(self):
        return psycopg.connect(self.database_url, autocommit=False, row_factory=dict_row,
                               connect_timeout=10)

    def bootstrap_admin(self, username: str, password: str) -> int:
        username = username.strip().lower()
        if not USERNAME.fullmatch(username):
            raise ValueError("Invalid username (3–40 ASCII characters)")
        encoded = hash_password(password)
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(7463821)")
            if db.execute("SELECT id FROM local_accounts LIMIT 1").fetchone():
                raise ValueError("An account exists. Bootstrap is available only once.")
            row = db.execute(
                """INSERT INTO local_accounts(username,password_hash,role)
                   VALUES(%s,%s,'admin') RETURNING id""", (username, encoded)).fetchone()
            return row["id"]

    def login(self, username: str, password: str):
        username = username.strip().lower()[:40]
        # Invalid usernames perform a dummy expensive check to reduce timing signals.
        with self.connect() as db:
            account = db.execute(
                """SELECT id,username,password_hash,role,failed_logins,locked_until
                   FROM local_accounts WHERE username=%s FOR UPDATE""",
                (username,),
            ).fetchone()
            if not account:
                verify_password(password, DUMMY_PASSWORD_HASH)
                return None
            now = datetime.now(timezone.utc)
            if account["locked_until"] and account["locked_until"] > now:
                return None
            valid = verify_password(password, account["password_hash"])
            if not valid:
                failures = account["failed_logins"] + 1
                db.execute(
                    """UPDATE local_accounts SET failed_logins=%s,locked_until=%s
                       WHERE id=%s""",
                    (failures, now + timedelta(seconds=LOCK_SECONDS)
                     if failures >= MAX_FAILURES else None, account["id"]),
                )
                return None
            db.execute(
                "UPDATE local_accounts SET failed_logins=0,locked_until=NULL WHERE id=%s",
                (account["id"],),
            )
            raw = secrets.token_hex(32)
            csrf = secrets.token_hex(32)
            db.execute(
                """INSERT INTO auth_sessions(token_hash,user_id,csrf_hash,expires_at)
                   VALUES(%s,%s,%s,%s)""",
                (token_hash(raw), account["id"], token_hash(csrf),
                 now + timedelta(seconds=SESSION_SECONDS)),
            )
            return {"token": raw, "csrf": csrf,
                    "user_id": account["id"], "username": account["username"],
                    "role": account["role"]}

    def session(self, token: str):
        if not isinstance(token, str) or not re.fullmatch("[0-9a-f]{64}", token):
            return None
        with self.connect() as db:
            return db.execute(
                """SELECT s.user_id,s.csrf_hash,a.username,a.role,s.expires_at
                   FROM auth_sessions s JOIN local_accounts a ON a.id=s.user_id
                   WHERE s.token_hash=%s AND s.expires_at>NOW()""",
                (token_hash(token),),
            ).fetchone()

    def verify_csrf(self, token: str, csrf: str) -> bool:
        if not isinstance(csrf, str) or not re.fullmatch("[0-9a-f]{64}", csrf):
            return False
        session = self.session(token)
        return bool(session and hmac.compare_digest(session["csrf_hash"], token_hash(csrf)))

    def logout(self, token: str):
        if not isinstance(token, str) or not re.fullmatch("[0-9a-f]{64}", token):
            return
        with self.connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (token_hash(token),))

    def role(self, user_id: int) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT role FROM local_accounts WHERE id=%s", (user_id,)).fetchone()
            return row["role"] if row else None


# Valid dummy hash, to avoid username-existence timing information.
DUMMY_PASSWORD_HASH = (
    "scrypt$16384$8$1$00000000000000000000000000000000$"
    "76516b07c5493eec20ffec837bc75b82e58fb243f93390c669ed522f12974cf7"
)


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "bootstrap":
        raise SystemExit("Usage: python -m auth bootstrap")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL must be set inside the Docker container")
    username = input("Initial local admin username: ").strip()
    password = getpass.getpass("Admin password (14-128 characters): ")
    confirmation = getpass.getpass("Repeat admin password: ")
    if password != confirmation:
        raise SystemExit("Password confirmation did not match")
    user_id = AuthStore(database_url).bootstrap_admin(username, password)
    print(f"Created the first local administrator (id={user_id}); credentials not printed.")


if __name__ == "__main__":
    main()
