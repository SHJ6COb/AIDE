"""Core query-intent types shared across tools/agents.

See docs/agents/packspec-status/TECHNICAL_SPEC.md's "Strict Input/Output
Context" section for the two-tier design this implements: Tier 1 fields are
each validated (enum/pattern) before ever reaching a `SearchParams` instance
-- an out-of-enum LLM-supplied value is never stored here, it's dropped to
`None` upstream (no retry loop, see ARCHITECTURE.md's token-minimization
principle). Tier 2 (`additional_terms`) is guarded separately, at SPL-build
time -- see `app/tools/splunk_client.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """The three real Message Types confirmed live -- see CONTEXT.md."""

    PACKAGING_SPECIFICATION = "PackITPackagingSpecification"
    DOCUMENT_INFO_RECORD = "DocumentInfoRecord"
    COCKPIT_MASTER_DATA = "PackITPackagingCockpitMasterData"


class ReplicationStatus(str, Enum):
    """The two real `BusinessStatus` values confirmed live on the
    Atom-staged hop -- see transform TECHNICAL_SPEC.md fact 4. Only these
    two are raw-searchable; the dashboard's finer 5-bucket taxonomy
    (Business/Technical Error, RETRY, ...) is derived downstream from the
    Docupedia catalog category, not from a distinct raw status value -- see
    docs/components/splunk-client/TECHNICAL_SPEC.md's status-filter section.
    """

    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


class DeterminationType(str, Enum):
    """Confirmed real values -- see CONTEXT.md's Determination Type entry.

    `KIT` is real and live (assigned to PS Group PSTU) despite not
    appearing in the packspec-status agent spec's original enum list.
    """

    SHIP = "SHIP"
    RCPT = "RCPT"
    ZFER = "ZFER"
    STOC = "STOC"
    PALE = "PALE"
    DOLL = "DOLL"
    KIT = "KIT"


@dataclass(frozen=True)
class TimeRange:
    """A resolved, concrete Splunk `earliest_time`/`latest_time` pair.

    Never a vague user phrase past this point -- resolving "last week" or
    similar into these strings is the caller's job. Capped at `MAX_DAYS`
    (see components/splunk-client's confirmed gateway `MessageBlocked`
    behavior on unbounded/broad searches -- an overly wide window makes that
    block far more likely).
    """

    earliest: str
    latest: str = "now"

    MAX_DAYS = 30

    @classmethod
    def default(cls) -> "TimeRange":
        """Last 15 minutes -- confirmed default when the user specifies no
        window at all (see packspec-status TECHNICAL_SPEC.md): no
        clarification round-trip, the no-match answer offers to widen it.
        """
        return cls(earliest="-15m", latest="now")

    def describe(self) -> str:
        """Human-readable rendering for user-facing "not found" answers.

        Caught live via QA testing: a "not found" answer that never states
        the actual window searched reads as "this doesn't exist" rather
        than "not found in the last 15 minutes" -- the two are very
        different claims, and only the second one is honest when the
        default window applies. Falls back to the raw Splunk-syntax string
        for anything that doesn't match the standard `-<N><unit>` shape
        (e.g. a caller-constructed `TimeRange` outside `parse_search_params`).
        """
        if self.latest != "now":
            return f"{self.earliest} to {self.latest}"
        match = _RELATIVE_TIME_RE.match(self.earliest)
        if not match:
            return f"the last {self.earliest}"
        amount, unit = match.group(1), match.group(2)
        unit_word = {"m": "minute", "h": "hour", "d": "day"}[unit]
        if amount != "1":
            unit_word += "s"
        return f"the last {amount} {unit_word}"


@dataclass(frozen=True)
class SearchParams:
    """Tier 1 (validated) + Tier 2 (guarded free-text) query intent for
    `get_ps_status`. Every Tier 1 field is `None` unless it already passed
    its own enum/pattern check upstream of this dataclass's construction.
    """

    ps_id: str | None = None
    plant: str | None = None
    supplier: str | None = None
    customer_index: str | None = None
    matnr: str | None = None
    document_number: str | None = None
    determination_type: DeterminationType | None = None
    message_type: MessageType | None = None
    usage: str | None = None
    sales_channel: str | None = None
    target_system: str | None = None
    status: ReplicationStatus | None = None
    time_range: TimeRange = field(default_factory=TimeRange.default)
    additional_terms: tuple[str, ...] = ()

    unresolved: tuple[tuple[str, str], ...] = ()
    """`(field_name, the value that could not be resolved)` for every field
    that was **supplied and non-empty** but failed validation.

    Validation dropping a field to `None` is safe for the SPL and dangerous
    for the answer: the clause simply disappears and the search silently
    widens, so the result no longer matches the question while reading exactly
    as though it does. Live example -- "the latest successful transfer to
    target system P87" lost its `host=` clause, searched every system, and the
    answer confidently named SAPPT00110. The same shape has now bitten this
    project four times (the `IAM/OES` Sales Channel enum, `LABEL_SALESCHANL`,
    the omitted time window, this).

    Recording it is what lets `harness` ask instead of guess. A caller must
    never run a search that silently ignores something the user asked for."""


_SELF_SUFFICIENT_FIELDS = ("ps_id", "document_number")
"""Fields specific enough on their own to run a search -- a PS ID or a DIR
document number each already identify a small, real result set."""

_IDENTIFYING_FIELDS = (
    "plant", "determination_type", "message_type", "supplier",
    "customer_index", "matnr", "usage", "sales_channel", "target_system",
)
"""Fields that narrow a search but aren't individually specific enough --
need at least two together, or one plus `status` (see `is_underspecified`).
`status` on its own never counts: `status=ERROR` alone is as broad as "every
failure across the whole pipeline right now". Caught live, though, that
`status` genuinely does narrow things when paired with even one of these --
"failed transfers to SAPP790110" (target_system + status) is a real,
well-scoped question, not the same failure mode as a fully unscoped search;
originally over-corrected to exclude `status` entirely, which wrongly
blocked that case too."""


def is_underspecified(params: SearchParams) -> bool:
    """True if the search isn't specific enough to run safely against real
    production data -- either nothing at all was extracted, or only a
    single broad identifying field with nothing to pair it with (e.g.
    `sales_channel=OE` alone can still match a large, arbitrary slice of
    traffic, and so can `status=ERROR` alone). Caught live: an off-topic
    question led to a fully unscoped search that dumped random real
    production records as if relevant (see ARCHITECTURE.md's Guardrails
    section); a single weak field is a milder version of the same failure
    mode, not a different one. One identifying field plus `status` together
    *is* sufficient -- also caught live, as an over-correction that blocked
    legitimate, well-scoped questions like "failed transfers to plant 0580".

    Lives here, next to `SearchParams`, rather than in `harness.py` where it
    started: the `baseline` regression run found the guard was reachable
    around (`pipeline._check_routing_if_target_missing` broadens a search
    and re-runs it), and `harness` already imports `pipeline`, so the
    pipeline could not import the guard back without a cycle. A property of
    a `SearchParams` belongs with `SearchParams`.
    """
    if any(getattr(params, f) is not None for f in _SELF_SUFFICIENT_FIELDS):
        return False
    if params.additional_terms:
        return False
    identifying_count = sum(1 for f in _IDENTIFYING_FIELDS if getattr(params, f) is not None)
    if identifying_count >= 2:
        return False
    if identifying_count == 1 and params.status is not None:
        return False
    return True


# Tier 1 patterns -- best-effort validation against every real example seen
# in this repo's live investigations (e.g. plant "0780"/"8160"/"078W", ps_id
# "00000000040001498023", customer_index "FU2", matnr "6000.409.798"). Not
# yet confirmed against a large real sample the way splunk-client's/catalog's
# patterns are -- honestly a reasonable bound, not a "confirmed live" claim.
_PS_ID_RE = re.compile(r"^\d{6,25}$")
_PLANT_RE = re.compile(r"^[A-Za-z0-9]{2,4}$")
_SUPPLIER_RE = re.compile(r"^[A-Za-z0-9]{1,15}$")
_CUSTOMER_INDEX_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")
_MATNR_RE = re.compile(r"^[A-Za-z0-9.]{1,20}$")
_DOCUMENT_NUMBER_RE = re.compile(r"^[A-Za-z0-9]{1,20}$")
_TARGET_SYSTEM_RE = re.compile(r"^[A-Za-z0-9]{6,15}$")  # e.g. SAPP790110, SAPPT00110, SAPP1M0110

_SHORT_TARGET_SYSTEM_RE = re.compile(r"^P([A-Za-z0-9]{2})$")
"""How people actually name these systems out loud: **P87**, **POE**, **PT0**,
**P1M** -- `P` plus the two-character system code, against the full technical
id `SAPP{code}0110`.

Resolved here in code rather than left to the model, because the failure is
silent and expensive. `_TARGET_SYSTEM_RE` demands 6-15 characters, so a real
question -- "the latest successful transfer to target system P87" -- had
`target_system` validated to `None`, the `host=` clause vanished from the SPL
entirely, and the search returned successes across *every* system. The answer
then named SAPPT00110 as though that had been asked for. It also took four
minutes, because without a host filter Splunk full-text matched
`<d:BusinessStatus>SUCCESS</d:BusinessStatus>` across seven days of every
target. One dropped filter produced both the wrong answer and the latency.

Deliberately not accepting a bare two-character code (`87`, `OE`): it collides
with plant codes and Usage values, and guessing which the user meant is how a
search silently widens. See `resolve_target_system`."""


def resolve_target_system(value: object) -> str | None:
    """`P87` -> `SAPP870110`; a full id passes through; anything else is `None`.

    `None` means *unresolvable*, and callers must treat that as a question to
    ask rather than a filter to drop -- see `SearchParams.unresolved`.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().upper()
    match = _SHORT_TARGET_SYSTEM_RE.match(text)
    if match:
        text = f"SAPP{match.group(1)}0110"
    return text if _TARGET_SYSTEM_RE.match(text) else None
_USAGE_VALUES = frozenset({"R", "A1", "A2", "A3", "A4"})
_SALES_CHANNEL_VALUES = frozenset({"OE", "OES", "IAM"})
"""Confirmed real: three separate values, not the composite `"IAM/OES"` this
previously held -- which matched nothing, so a question scoped to IAM or OES had
the field silently dropped to `None` and the search quietly widened. Seen live
in every capture, both as the `TOPICSTRING` Sales Channel segment
(`.../V1/OES/SHIP/0110/60/No`) and as `DETERMINATION.LABEL_SALESCHANL`.

`"IAM/OES"` survives in prose (CONTEXT.md, the routing-plan spec) as the name of
the *combined* channel PT0 serves; it is not a value any payload carries."""
_RELATIVE_TIME_RE = re.compile(r"^-(\d+)(m|h|d)$")
_UNIT_TO_DAYS = {"m": 1 / 1440, "h": 1 / 24, "d": 1}


def _validate_pattern(value: str | None, pattern: re.Pattern[str]) -> str | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    return value if pattern.match(value) else None


def _validate_enum(value: Any, enum_cls: type[Enum]) -> Any:
    if not value:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _validate_time_range(earliest: str | None, latest: str | None) -> TimeRange:
    """Resolve raw earliest/latest strings from an LLM tool call into a
    `TimeRange`, capped at `TimeRange.MAX_DAYS` -- enforced here since this
    is the one place a caller-supplied time window is turned into the type
    every downstream tool trusts as already-bounded (see `TimeRange`'s own
    docstring and the confirmed gateway `MessageBlocked` risk on overly wide
    searches, `components/splunk-client/TECHNICAL_SPEC.md`).
    """
    if not earliest:
        return TimeRange.default()
    match = _RELATIVE_TIME_RE.match(earliest.strip())
    if not match:
        return TimeRange.default()
    amount, unit = int(match.group(1)), match.group(2)
    if amount * _UNIT_TO_DAYS[unit] > TimeRange.MAX_DAYS:
        earliest = f"-{TimeRange.MAX_DAYS}d"
    return TimeRange(earliest=earliest.strip(), latest=(latest or "now").strip() or "now")


def parse_search_params(raw: dict[str, Any]) -> SearchParams:
    """Build a `SearchParams` from an LLM tool call's raw argument dict.

    Every Tier 1 field is validated against its enum/pattern here; anything
    out-of-shape or unparseable is dropped to `None` rather than bounced back
    to the LLM in a retry loop -- see the token-minimization principle in
    `ARCHITECTURE.md` and the Strict Input Context in
    `docs/agents/packspec-status/TECHNICAL_SPEC.md`. Tier 2
    `additional_terms` pass through as plain strings; their own guardrail
    (character allowlist, length cap, injection rejection) is applied later,
    at SPL-build time, in `app/tools/splunk_client.py`.
    """
    usage = raw.get("usage")
    sales_channel = raw.get("sales_channel")
    resolved = {
        "ps_id": _validate_pattern(raw.get("ps_id"), _PS_ID_RE),
        "plant": _validate_pattern(raw.get("plant"), _PLANT_RE),
        "supplier": _validate_pattern(raw.get("supplier"), _SUPPLIER_RE),
        "customer_index": _validate_pattern(raw.get("customer_index"), _CUSTOMER_INDEX_RE),
        "matnr": _validate_pattern(raw.get("matnr"), _MATNR_RE),
        "document_number": _validate_pattern(raw.get("document_number"), _DOCUMENT_NUMBER_RE),
        "determination_type": _validate_enum(raw.get("determination_type"), DeterminationType),
        "message_type": _validate_enum(raw.get("message_type"), MessageType),
        "usage": usage if usage in _USAGE_VALUES else None,
        "sales_channel": sales_channel if sales_channel in _SALES_CHANNEL_VALUES else None,
        # Resolved, not merely validated -- "P87" is a real way to name
        # SAPP870110 and must not be discarded as malformed.
        "target_system": resolve_target_system(raw.get("target_system")),
        "status": _validate_enum(raw.get("status"), ReplicationStatus),
    }
    # A field the caller *supplied* but that resolved to nothing. Empty and
    # absent values are not failures; a real value that vanished is.
    unresolved = tuple(
        (name, str(raw.get(name)).strip())
        for name, value in resolved.items()
        if value is None and str(raw.get(name) or "").strip()
    )
    return SearchParams(
        **resolved,
        time_range=_validate_time_range(raw.get("time_earliest"), raw.get("time_latest")),
        additional_terms=tuple(str(t) for t in (raw.get("additional_terms") or []) if str(t).strip()),
        unresolved=unresolved,
    )
