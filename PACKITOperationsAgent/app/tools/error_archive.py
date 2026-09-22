"""Persistence of currently-failing Transfers, reconciled on every run.

The rule, as specified: **the latest hop is what matters.** A Transfer whose
latest hop is an error is persisted; a Transfer whose latest hop is a success
is not -- regardless of whether its earlier hops failed. And because a
persisted error can be fixed later (a Retrigger succeeds once the underlying
master data is corrected), each run also *removes* entries whose latest hop
has since become a success. The store therefore always answers exactly one
question: "what is failing right now?"

Design notes worth knowing before changing anything here:

- **Keyed by (Message ID, Target System), never Message ID alone.** One
  Message ID fans out to several Transfers, one per Target System, with
  independent outcomes -- resolved on one target while still failing on
  another, at the same moment (see CONTEXT.md's Transfer entry). Keying by
  Message ID would let a success on one target delete a target that is still
  broken.
- **A hop-time guard prevents older data from overwriting newer.** The latest
  hop *within one search window* is not necessarily the Transfer's latest hop
  globally: a run covering an earlier window can legitimately surface only
  the old error hops of a Transfer that has since succeeded. Without the
  guard, such a run would re-persist an already-resolved error and the two
  runs would fight. See `_is_stale`.
- **Only SUCCESS resolves; only ERROR persists.** Anything else -- no status
  at all, or a status this codebase has not confirmed the shape of -- leaves
  the store untouched and is counted as `undetermined` in the report. Two
  real open gaps make this branch load-bearing rather than theoretical:
  `DocumentInfoRecord` has no observed error/success signal at its processed
  stage, and the RETRY-bucket payload shape has never been captured despite
  dedicated searches (see docs/agents/packspec-status/TECHNICAL_SPEC.md's
  "Still open"). Failing closed here means an unclassifiable hop can neither
  invent a failure nor silently clear a real one.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.core.storage import DEFAULT_DB_PATH
from app.tools.transform import TransferRecord

_ERROR = "ERROR"
_SUCCESS = "SUCCESS"

_NO_TARGET = ""
"""Stand-in for a `TransferRecord` with no derivable Target System (every
`DocumentInfoRecord`, whose hosts are content-server names with no Target
System concept at all). SQLite treats NULLs in a composite PRIMARY KEY as
distinct from each other, so a real NULL here would silently allow unlimited
duplicate rows for the same Message ID."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS persisted_errors (
    message_id TEXT NOT NULL,
    target_system TEXT NOT NULL,
    message_type TEXT NOT NULL,
    ps_id TEXT,
    dir_key TEXT,
    plant TEXT,
    det_type TEXT,
    description TEXT,
    latest_hop_time TEXT,
    hop_count INTEGER NOT NULL,
    first_persisted_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (message_id, target_system)
);

CREATE INDEX IF NOT EXISTS ix_persisted_errors_ps ON persisted_errors(ps_id);
"""


@dataclass(frozen=True)
class PersistedError:
    """One currently-failing Transfer, as stored."""

    message_id: str
    target_system: str | None
    message_type: str
    ps_id: str | None
    dir_key: str | None
    plant: str | None
    det_type: str | None
    description: str | None
    latest_hop_time: str | None
    hop_count: int
    first_persisted_at: str
    last_seen_at: str


@dataclass
class ReconcileReport:
    """What one `reconcile` pass actually changed -- returned rather than
    logged so a scheduled caller can surface it. A run that silently does
    nothing and a run that silently fails look identical otherwise."""

    persisted: list[tuple[str, str | None]] = field(default_factory=list)
    """Newly failing Transfers added to the store."""

    refreshed: list[tuple[str, str | None]] = field(default_factory=list)
    """Already-stored Transfers still failing, whose details were updated."""

    resolved: list[tuple[str, str | None]] = field(default_factory=list)
    """Stored Transfers whose latest hop is now a success -- deleted."""

    already_clean: int = 0
    """Successful Transfers that were never in the store. Counted, not
    listed: on a healthy pipeline this is the overwhelming majority."""

    undetermined: list[tuple[str, str | None]] = field(default_factory=list)
    """Transfers whose latest hop is neither ERROR nor SUCCESS -- deliberately
    left untouched. See this module's docstring."""

    stale_skipped: list[tuple[str, str | None]] = field(default_factory=list)
    """Transfers whose incoming latest hop predates what's already stored --
    ignored so an older window can't overwrite newer data."""

    @property
    def open_error_delta(self) -> int:
        return len(self.persisted) - len(self.resolved)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(record: TransferRecord) -> tuple[str, str]:
    return (record.message_id, record.target_system or _NO_TARGET)


def _is_stale(incoming_hop_time: str | None, stored_hop_time: str | None) -> bool:
    """True if `incoming` describes an *older* state than what's stored.

    Both timestamps missing, or either one missing, means no ordering can be
    established -- treat as not stale and let the incoming record win, since
    the alternative is a store that can never be updated. Timestamps come
    from Splunk's own `_time` and are ISO-8601, so string comparison matches
    chronological order.
    """
    if not incoming_hop_time or not stored_hop_time:
        return False
    return incoming_hop_time < stored_hop_time


class ErrorArchive:
    """Stores currently-failing Transfers in the project's SQLite database.

    Follows `app/core/storage.py`'s connection pattern -- one short-lived
    connection per call, no shared long-lived connection -- so a scheduled
    reconcile running on its own thread never has to coordinate with the
    request-handling thread.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._db_path = str(db_path)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- the two mechanisms ------------------------------------------------

    def reconcile(self, records: list[TransferRecord]) -> ReconcileReport:
        """Apply both rules in one pass over `records`.

        Persist every Transfer whose latest hop is an error; delete every
        stored entry whose latest hop is now a success. Doing both in a
        single pass over the same data is what keeps the store consistent
        with one point in time -- splitting them into two passes over two
        separately-fetched result sets would let a Transfer be persisted by
        one and deleted by the other within the same run.
        """
        report = ReconcileReport()
        now = _now()
        with self._connect() as conn:
            stored = self._stored_hop_times(conn)
            for record in records:
                key = _key(record)
                status = record.current_status
                stored_hop_time = stored.get(key)

                if status not in (_ERROR, _SUCCESS):
                    report.undetermined.append((record.message_id, record.target_system))
                    continue

                if key in stored and _is_stale(record.latest.time, stored_hop_time):
                    report.stale_skipped.append((record.message_id, record.target_system))
                    continue

                if status == _ERROR:
                    target = report.refreshed if key in stored else report.persisted
                    self._upsert(conn, record, now=now)
                    target.append((record.message_id, record.target_system))
                elif key in stored:
                    conn.execute(
                        "DELETE FROM persisted_errors WHERE message_id = ? AND target_system = ?", key
                    )
                    report.resolved.append((record.message_id, record.target_system))
                else:
                    report.already_clean += 1
        return report

    def _stored_hop_times(self, conn: sqlite3.Connection) -> dict[tuple[str, str], str | None]:
        """One read of every stored key up front, rather than a SELECT per
        record -- a reconcile pass routinely handles hundreds of records
        against a store holding far fewer open errors."""
        rows = conn.execute("SELECT message_id, target_system, latest_hop_time FROM persisted_errors").fetchall()
        return {(r[0], r[1]): r[2] for r in rows}

    def _upsert(self, conn: sqlite3.Connection, record: TransferRecord, *, now: str) -> None:
        """Insert a newly-failing Transfer, or refresh one still failing.

        `first_persisted_at` is deliberately absent from the UPDATE clause:
        how long a Transfer has been failing is the one fact this store holds
        that cannot be recovered from Splunk once its retention window passes,
        so a refresh must not reset it.
        """
        message_id, target_system = _key(record)
        latest = record.latest
        conn.execute(
            """
            INSERT INTO persisted_errors (
                message_id, target_system, message_type, ps_id, dir_key, plant, det_type,
                description, latest_hop_time, hop_count, first_persisted_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id, target_system) DO UPDATE SET
                message_type = excluded.message_type,
                ps_id = excluded.ps_id,
                dir_key = excluded.dir_key,
                plant = excluded.plant,
                det_type = excluded.det_type,
                description = excluded.description,
                latest_hop_time = excluded.latest_hop_time,
                hop_count = excluded.hop_count,
                last_seen_at = excluded.last_seen_at
            """,
            (
                message_id,
                target_system,
                record.message_type,
                record.ps_id,
                record.dir_key,
                latest.plant,
                latest.det_type,
                record.current_description,
                latest.time,
                len(record.hops),
                now,
                now,
            ),
        )

    # -- reads --------------------------------------------------------------

    def list_open_errors(self, *, ps_id: str | None = None) -> list[PersistedError]:
        """Every Transfer currently failing, newest failure first."""
        query = "SELECT * FROM persisted_errors"
        params: tuple = ()
        if ps_id is not None:
            query += " WHERE ps_id = ?"
            params = (ps_id,)
        query += " ORDER BY latest_hop_time DESC"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [_to_persisted_error(row) for row in rows]

    def get(self, message_id: str, target_system: str | None) -> PersistedError | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM persisted_errors WHERE message_id = ? AND target_system = ?",
                (message_id, target_system or _NO_TARGET),
            ).fetchone()
        return _to_persisted_error(row) if row is not None else None

    def count_open_errors(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM persisted_errors").fetchone()[0]


def _to_persisted_error(row: sqlite3.Row) -> PersistedError:
    return PersistedError(
        message_id=row["message_id"],
        # Round-trip the sentinel back to None so callers never have to know
        # about it -- it exists only to satisfy SQLite's PRIMARY KEY.
        target_system=row["target_system"] or None,
        message_type=row["message_type"],
        ps_id=row["ps_id"],
        dir_key=row["dir_key"],
        plant=row["plant"],
        det_type=row["det_type"],
        description=row["description"],
        latest_hop_time=row["latest_hop_time"],
        hop_count=row["hop_count"],
        first_persisted_at=row["first_persisted_at"],
        last_seen_at=row["last_seen_at"],
    )
