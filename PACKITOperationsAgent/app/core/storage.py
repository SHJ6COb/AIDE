"""SQLite-backed persistence: multi-conversation history and issue reports.

A project-local file, not a server -- see ADR-0002 (single-user-per-process,
no multi-tenant scoping needed). One short-lived connection per call rather
than a shared long-lived connection, so calls from `get_ps_status`'s
background thread (see docs/agents/packspec-status/TECHNICAL_SPEC.md) never
have to coordinate with the request-handling thread over one connection.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.core.llm_client import Message

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "packit_agent.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issue_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""

_TITLE_MAX_LENGTH = 60


@dataclass(frozen=True)
class ConversationSummary:
    id: str
    title: str
    updated_at: str


@dataclass(frozen=True)
class StoredMessage:
    role: str
    content: str
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_timestamp(iso_timestamp: str) -> str:
    dt = datetime.fromisoformat(iso_timestamp)
    return f"{dt:%b} {dt.day}, {dt:%I:%M %p}"


_ID_SUFFIX_LENGTH = 6


def _derive_title(conn: sqlite3.Connection, first_user_message: str, created_at: str, conversation_id: str) -> str:
    """Caught live via QA testing, in two parts:

    1. Two conversations both opening with "Hi" got the identical title
       "Hi", indistinguishable in the sidebar except by hovering for the
       timestamp.
    2. A timestamp suffix *always* appended (an earlier fix for #1) turned
       out to be its own problem: real user feedback (from the same QA
       round) called the common case -- most conversations, which never
       collide -- "close to useless" once every title carried a cryptic
       timestamp/id tail, even when nothing else shared that title.

    Resolved by only appending the disambiguator when a real collision
    exists (checked against other conversations' titles here) -- the common
    case stays a clean, bare title; only actual collisions get suffixed.
    Second-level timestamp precision alone still isn't enough to guarantee
    uniqueness (confirmed live: two conversations created back-to-back can
    land in the same wall-clock second), so the id suffix stays as the
    actual uniqueness guarantee once a collision is detected.
    """
    first_line = first_user_message.strip().splitlines()[0] if first_user_message.strip() else "New conversation"
    base = first_line if len(first_line) <= _TITLE_MAX_LENGTH else first_line[: _TITLE_MAX_LENGTH - 1].rstrip() + "..."
    collision = conn.execute(
        "SELECT 1 FROM conversations WHERE id != ? AND (title = ? OR title LIKE ?) LIMIT 1",
        (conversation_id, base, f"{base} (%"),
    ).fetchone()
    if not collision:
        return base
    return f"{base} ({_short_timestamp(created_at)}, {conversation_id[:_ID_SUFFIX_LENGTH]})"


class SqliteConversationStore:
    """Implements `app.core.harness.ConversationStore` against SQLite, plus
    the extra listing/create/delete/issue-report operations the FastAPI
    backend needs (see docs/components/ui/API_CONTRACT.md)."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- ConversationStore protocol (consumed by app.core.harness) --------

    def get_history(self, conversation_id: str) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [Message(role=role, content=content) for role, content in rows]

    def append_message(self, conversation_id: str, role: str, content: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
            if role == "user":
                row = conn.execute("SELECT title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
                if row is not None and not row[0]:
                    conn.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (_derive_title(conn, content, now, conversation_id), conversation_id),
                    )

    # -- Extra operations for the UI backend -------------------------------

    def create_conversation(self) -> str:
        conversation_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, '', ?, ?)",
                (conversation_id, now, now),
            )
        return conversation_id

    def list_conversations(self) -> list[ConversationSummary]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC").fetchall()
        return [ConversationSummary(id=r[0], title=r[1] or "New conversation", updated_at=r[2]) for r in rows]

    def get_messages(self, conversation_id: str) -> list[StoredMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [StoredMessage(role=r[0], content=r[1], created_at=r[2]) for r in rows]

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def record_issue(self, conversation_id: str | None, description: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO issue_reports (conversation_id, description, created_at) VALUES (?, ?, ?)",
                (conversation_id, description, _now()),
            )
            return cursor.lastrowid
