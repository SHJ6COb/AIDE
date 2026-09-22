"""Docupedia error catalog matching -- structured regex, not RAG.

See docs/components/catalog/TECHNICAL_SPEC.md for the empirical grounding.
Source document: db/docupediaContext/PackIT (PD7) Interface Error-....pdf,
transcribed into db/docupediaContext/error_catalog.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "db" / "docupediaContext" / "error_catalog.yaml"

_ACTIONABLE_CATEGORIES = frozenset({"Target Error", "Source Error", "Technical Error", "Retrigger required"})
"""Categories a user can actually act on. `HINT`/`No action required` rows
are never returned by `match_catalog` -- they were never a candidate fix,
just catalog background/policy notes (see error_catalog.yaml's own header)."""

_PATTERN_FLAGS = re.IGNORECASE | re.DOTALL | re.MULTILINE
"""IGNORECASE + DOTALL: confirmed necessary live -- `description` is
newline-joined from multiple Ret_msgs.Message values, and several patterns
(e.g. row 30) span more than one of them via `.`, which only crosses
newlines under DOTALL (91/91 real Technical Error examples matched once
applied). MULTILINE: several rows anchor `^`/`$` to one specific line within
that same joined, multi-line text (e.g. row 11 vs row 12's differing
"in plant" suffix) -- those anchors are per-line, not per-string, under
MULTILINE."""


@dataclass(frozen=True)
class CatalogMatch:
    """One catalog row that matched a Transfer's error description."""

    seq_nr: int | str
    error_category: str
    responsible: str | None
    summary: str
    solution: str


@dataclass(frozen=True)
class _CatalogRow:
    seq_nr: int | str
    error_category: str
    pattern: re.Pattern[str] | None
    responsible: str | None
    summary: str
    solution: str
    context: dict[str, str] | None


@lru_cache(maxsize=1)
def _load_rows() -> tuple[_CatalogRow, ...]:
    raw = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))
    rows = []
    for entry in raw:
        pattern_text = entry.get("pattern")
        rows.append(
            _CatalogRow(
                seq_nr=entry["seq_nr"],
                error_category=entry["error_category"],
                pattern=re.compile(pattern_text, _PATTERN_FLAGS) if pattern_text else None,
                responsible=entry.get("responsible"),
                summary=entry["summary"],
                solution=entry.get("solution") or "",
                context=entry.get("context"),
            )
        )
    return tuple(rows)


def _context_satisfied(row_context: dict[str, str] | None, context: dict[str, str | None]) -> bool:
    """A row's `context` requirement (see error_catalog.yaml's header) is
    satisfied only when every key it names is present in the caller's
    `context` *and* equal -- a key that's missing/unextracted fails closed
    (row excluded), never assumed to match. Necessary because not every
    OBJECTKEY field a `context` block can name (e.g. customer_index,
    sales_channel) is currently extracted onto TransferRecord/Hop -- see
    docs/components/transform/TECHNICAL_SPEC.md. Failing closed here means
    a context-scoped row (e.g. row 7's narrow Buffer Monitoring case)
    simply doesn't fire when it can't be confirmed, rather than over- or
    under-matching on an unknown field.
    """
    if row_context is None:
        return True
    return all(context.get(key) == expected for key, expected in row_context.items())


def match_catalog(error_text: str | None, context: dict[str, str | None] | None = None) -> list[CatalogMatch]:
    """Return every actionable catalog row whose pattern matches
    `error_text` (and whose `context` requirement, if any, is satisfied).

    Deliberately returns *all* matches rather than picking one "best" row.
    A single description can legitimately match more than one row at once
    (confirmed real -- see TECHNICAL_SPEC.md's row-21-and-row-32 example);
    the strict-grounding design here is to surface every grounded candidate
    and let the end user judge, rather than have code silently guess which
    one is "the" answer. Purely informational rows (`HINT`/`No action
    required`) are never returned -- they were never a candidate fix to
    begin with.

    Returns an empty list if nothing matches -- callers must never invent a
    fix in that case (see ARCHITECTURE.md's strict grounding rule).
    """
    if not error_text:
        return []
    ctx = context or {}
    matches = []
    for row in _load_rows():
        if row.pattern is None or row.error_category not in _ACTIONABLE_CATEGORIES:
            continue
        if not _context_satisfied(row.context, ctx):
            continue
        if row.pattern.search(error_text):
            matches.append(
                CatalogMatch(
                    seq_nr=row.seq_nr,
                    error_category=row.error_category,
                    responsible=row.responsible,
                    summary=row.summary,
                    solution=row.solution,
                )
            )
    return matches
