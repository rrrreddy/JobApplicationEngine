"""SQLite storage: profile, watched channels, job queue, recruiter dedup."""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "engine.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier TEXT UNIQUE NOT NULL,  -- telegram username / invite link / numeric id
    label TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    message_id INTEGER,
    content_hash TEXT UNIQUE NOT NULL,
    raw_text TEXT NOT NULL,
    is_fit INTEGER,
    fit_reason TEXT,
    recruiter_email TEXT,
    job_signature TEXT,  -- short "<role> at <company>" identifier, used to dedup per-opening
    draft_subject TEXT,
    draft_body TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
        -- queued (discovered, not yet judged) | pending (judged as a fit, awaiting your
        -- approval) | rejected | approved | sent | failed | not_a_fit | no_contact | already_applied
    approval_chat_message_id INTEGER,
    created_at REAL NOT NULL,
    decided_at REAL,
    sent_at REAL
);

-- One row per (recruiter, specific opening) actually emailed. Reposts of
-- the same opening are blocked; a genuinely different opening from the
-- same recruiter/company is not.
CREATE TABLE IF NOT EXISTS sent_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recruiter_email TEXT NOT NULL,
    job_signature TEXT NOT NULL,
    job_id INTEGER NOT NULL,
    sent_at REAL NOT NULL,
    UNIQUE(recruiter_email, job_signature)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # WAL mode lets readers/writers proceed concurrently instead of blocking
    # each other -- important here since backfill/poll writes from a
    # background thread and the bot's handlers on the event loop both hit
    # this file at once. busy_timeout backstops any remaining brief locks
    # with a retry instead of the 5s default before raising "database is
    # locked".
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def content_hash(text: str) -> str:
    normalized = " ".join(text.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------- profile ----------

def save_profile(profile: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO profile (id, data) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (json.dumps(profile),),
        )


def load_profile() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT data FROM profile WHERE id = 1").fetchone()
        return json.loads(row["data"]) if row else None


# ---------- channels ----------

def add_channel(identifier: str, label: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO channels (identifier, label) VALUES (?, ?) "
            "ON CONFLICT(identifier) DO UPDATE SET active = 1, label = excluded.label",
            (identifier, label),
        )


def remove_channel(identifier: str):
    with get_conn() as conn:
        conn.execute("UPDATE channels SET active = 0 WHERE identifier = ?", (identifier,))


def list_channels(active_only: bool = True) -> list[sqlite3.Row]:
    with get_conn() as conn:
        query = "SELECT * FROM channels"
        if active_only:
            query += " WHERE active = 1"
        return conn.execute(query).fetchall()


# ---------- jobs ----------

def job_exists(chash: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE content_hash = ?", (chash,)).fetchone()
        return row is not None


def already_applied(email: str, job_signature: str) -> bool:
    """True if we've already sent this exact recruiter an application for
    this exact opening. A different opening from the same recruiter/company
    is allowed through."""
    if not email or not job_signature:
        return False
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_applications WHERE recruiter_email = ? AND job_signature = ?",
            (email.strip().lower(), job_signature.strip().lower()),
        ).fetchone()
        return row is not None


def create_job(channel: str, message_id: int, raw_text: str) -> int | None:
    """Returns a job id to process, or None if this exact post has already
    been seen and resolved. A post that previously ended in 'failed' (e.g.
    a transient LLM/API error) is reset and returned for retry rather than
    being treated as a permanent duplicate."""
    chash = content_hash(raw_text)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, status FROM jobs WHERE content_hash = ?", (chash,)
        ).fetchone()
        if existing is not None:
            if existing["status"] == "failed":
                conn.execute(
                    "UPDATE jobs SET status = 'queued', is_fit = NULL, fit_reason = NULL, "
                    "recruiter_email = NULL, job_signature = NULL, draft_subject = NULL, "
                    "draft_body = NULL, decided_at = NULL, sent_at = NULL, channel = ?, "
                    "message_id = ? WHERE id = ?",
                    (channel, message_id, existing["id"]),
                )
                return existing["id"]
            return None  # already seen and resolved this exact post

        cur = conn.execute(
            "INSERT INTO jobs (channel, message_id, content_hash, raw_text, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel, message_id, chash, raw_text, time.time()),
        )
        return cur.lastrowid


def update_job(job_id: int, **fields):
    if not fields:
        return
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)


def get_job(job_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def get_job_ids_by_status(status: str) -> list[int]:
    """Used for crash recovery: finds jobs that were discovered and
    persisted (status='queued') but never got processed, e.g. because the
    app restarted while they were still sitting in the in-memory queue."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM jobs WHERE status = ?", (status,)).fetchall()
        return [r["id"] for r in rows]


def mark_applied(email: str, job_signature: str, job_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_applications (recruiter_email, job_signature, job_id, sent_at) "
            "VALUES (?, ?, ?, ?)",
            (email.strip().lower(), job_signature.strip().lower(), job_id, time.time()),
        )


def jobs_between(start_ts: float, end_ts: float) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (start_ts, end_ts),
        ).fetchall()


# ---------- meta (cooldown timestamps etc.) ----------

def get_meta(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_meta(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_channel_last_checked(identifier: str) -> float | None:
    value = get_meta(f"last_checked:{identifier}")
    return float(value) if value else None


def set_channel_last_checked(identifier: str, timestamp: float):
    set_meta(f"last_checked:{identifier}", str(timestamp))
