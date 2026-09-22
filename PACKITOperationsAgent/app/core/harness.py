"""The fixed two-LLM-turn harness loop: parse the query into `SearchParams`,
run `get_ps_status` once, compose the final answer. See
docs/components/harness/TECHNICAL_SPEC.md and ADR-0001 -- no open-ended
tool-orchestration loop, no retry-until-valid loop for bad LLM arguments.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from app.agents.packspec_status.pipeline import (
    DependentObjectsView,
    RoutingCheck,
    StatusResult,
    get_ps_status,
)
from app.core import knowledge
from app.core.config import AgentConfig
from app.core.domain import SearchParams, TimeRange, is_underspecified, parse_search_params
from app.core.llm_client import LLMClient, Message, ToolSchema, wrap_untrusted_data
from app.core.time_window import (
    TimeWindowMention,
    bare_window_reply,
    find_time_windows,
    mentions_a_time_period,
    parse_time_window,
)
from app.tools.catalog import CatalogMatch
from app.tools.transform import TransferRecord

OnStep = Callable[[str], None]

_SKILL_PATH = Path(__file__).resolve().parents[1] / "agents" / "packspec_status" / "skill.md"
"""The project's own domain glossary is appended to `skill.md` in the system
instruction so the LLM can answer genuine "how does this work" domain
questions directly (see skill.md's scope-boundary rule) using the same
grounded vocabulary this whole codebase is built on, rather than either
refusing every non-status question outright or answering from its own
ungrounded general knowledge of what "PackIT" might mean.

It now lives as topic files under `agents/packspec_status/knowledge/` rather
than as one `CONTEXT.md` -- see `app/core/knowledge.py` for why, and for why
selective loading is structured but not yet switched on."""

_GET_PS_STATUS_TOOL = ToolSchema(
    name="get_ps_status",
    description=(
        "Search PackIT/PDMI Splunk data for a Packaging Specification's Replication Status. "
        "Call this exactly once per question, even if you're unsure of some fields -- leave "
        "anything you're not confident about unset rather than guessing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ps_id": {"type": "string", "description": "The Packaging Specification's numeric ID, as given."},
            "plant": {"type": "string", "description": "A plant code (WERKS), e.g. 0780."},
            "supplier": {"type": "string", "description": "A supplier code (inbound/RCPT context)."},
            "customer_index": {"type": "string", "description": "A customer index code (outbound/SHIP context)."},
            "matnr": {"type": "string", "description": "A material number."},
            "document_number": {"type": "string", "description": "A Document Info Record's document number."},
            "determination_type": {"type": "string", "enum": ["SHIP", "RCPT", "ZFER", "STOC", "PALE", "DOLL", "KIT"]},
            "message_type": {
                "type": "string",
                "enum": ["PackITPackagingSpecification", "DocumentInfoRecord", "PackITPackagingCockpitMasterData"],
            },
            "usage": {"type": "string", "enum": ["R", "A1", "A2", "A3", "A4"]},
            "sales_channel": {"type": "string", "enum": ["OE", "OES", "IAM"]},
            "target_system": {
                "type": "string",
                "description": "A specific Target System ID (e.g. SAPP790110, SAPPT00110) if the user names one -- what actually received (or should have received) the transfer.",
            },
            "status": {
                "type": "string",
                "enum": ["ERROR", "SUCCESS"],
                "description": (
                    "The Replication Status the user is asking about, if any. Map natural language: "
                    "'failed'/'failing'/'stuck'/'not working'/'error' -> ERROR; "
                    "'completed'/'worked'/'healthy'/'fine'/'succeeded' -> SUCCESS. "
                    "Leave unset if the user isn't asking about outcome specifically -- this narrows "
                    "the search, so only set it when the user's own words clearly ask for one outcome."
                ),
            },
            "time_earliest": {
                "type": "string",
                "description": "Splunk relative time, e.g. -3h, -7d. Omit for the default (last 15 minutes).",
            },
            "time_latest": {"type": "string", "description": "Splunk relative time, default 'now'."},
            "additional_terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Free-text terms that don't map to any field above (a brand, an error fragment, a username).",
            },
        },
    },
)

_TICKET_FALLBACK_MARKERS = ("mservicehub", "raise a ticket", "support ticket", "file a ticket")
_GROUNDING_FALLBACK_ANSWER = (
    "I don't have a documented fix for this specific error. Please raise a ticket via "
    "mServiceHub so the support team can investigate."
)

_EXPLAIN_FALLBACK_ANSWER = (
    "Sorry, I couldn't put an answer together for that one. Could you rephrase it?"
)
"""Used when the domain-question turn returns no text at all.

That slot previously held `turn1.text` -- whatever the parsing turn happened
to have written. Turn 1 is instructed to emit only "a single short line naming
what is being asked about", so the fallback was a fragment of an internal
handoff, shown to a user as if it were an answer. It is also the turn with no
glossary, which is exactly why `EXPLAIN` re-derives the answer rather than
reusing it (see the `params is None` branch).

It matters more now than it did: `_load_skill` no longer sends `Tone` to
`PARSE`, so turn-1 prose is no longer written under any user-facing rules at
all. A fixed, honest sentence beats an unguarded one."""

_QUERY_FAILED_MARKER = (
    "Sorry, this question couldn't be answered -- the request failed before it completed. "
    "Please try asking again. (If your next question would refer back to this one, please "
    "restate it in full -- nothing was actually found here to refer back to.)"
)
"""Persisted in place of a real assistant reply when `_run_query_body` raises
-- see `run_query`'s except clause. A distinct, recognizable fixed string
(not the SSE error text, which is ephemeral) since this one lands in
permanent history and in the `/api/issues` mailto transcript, not just the
live stream. Worded for a human reader, not the model -- caught live via QA
testing that the original phrasing ("restate it in full, since this turn
produced nothing to refer back to", wrapped in brackets) read like leaked
internal/prompt text sitting permanently in a real user's transcript."""

_NOT_FOUND_MARKERS = (
    "couldn't find", "could not find", "didn't find", "did not find",
    "no records", "no results", "nothing found", "widen", "double-check", "double check",
)


def _not_found_answer(params: SearchParams, routing_check: RoutingCheck | None = None) -> str:
    """Caught live via QA testing: a static "not found" message never says
    what window was actually searched, so it reads as "this doesn't exist"
    rather than "not found in the last 15 minutes" -- very different
    claims, and a real PS with real data from a week ago got the same
    reply as a genuinely nonexistent PS ID. Stating the concrete window
    gives the user the actual fix (ask again with a wider one) instead of
    an unquantified "should I widen it?".

    The `target_system` caveat below is deterministic, not left to the
    LLM's own phrasing -- caught live (2026-08-05) that `_enforce_grounding`
    silently discards the LLM's own answer whenever its wording doesn't
    contain one of `_NOT_FOUND_MARKERS`, and skill.md's guidance for this
    exact scenario encourages phrasing ("outside what I can check here")
    that doesn't match any of those markers, so the LLM's compliant answer
    was getting overridden by this same function's *un-caveated* template.
    Stating it here guarantees it appears regardless of what the LLM said.

    When `routing_check` is populated (`get_ps_status` found the PS
    elsewhere and successfully queried the Additional Routing plan for its
    real Plant/Determination Type -- see `pipeline.RoutingCheck`), state
    the actual, grounded answer instead of the generic "can't check here"
    caveat: whether the requested target was ever configured to receive it.
    """
    if params.status is not None:
        # A *filtered* empty result is not the same statement as an unfiltered
        # one, and running them together produces a wrong answer. Caught in the
        # `explain_fix2` run (S07/q2): asked "any errors at all on that one?"
        # about a PS whose SUCCESS transfer had just been reported, the search
        # correctly scoped itself to status=ERROR, found none -- and the generic
        # template announced "I couldn't find any records matching that" and
        # advised double-checking a PS ID that was demonstrably fine. Zero
        # ERROR records is the *answer* to that question, not a failure to find
        # anything.
        subject = f"PS {params.ps_id}" if params.ps_id else "that"
        base = (
            f"No {params.status.value} records for {subject} in {params.time_range.describe()}. "
            "That's the answer to what you asked rather than a lookup failure -- other records may "
            "exist with a different status, or outside this window."
        )
    elif params.time_range == TimeRange.default():
        # No window was asked for, so the search ran the deliberately narrow
        # 15-minute default and found nothing -- which for live data is the
        # common case, not an unusual one. Offer the widths outright instead of
        # asking the user to restate the whole question with a window in it.
        # Written here rather than left to the model because the reply has to
        # be understood when it comes back: `time_window.bare_window_reply`
        # recognises exactly these forms.
        base = (
            f"I couldn't find any records matching that in {params.time_range.describe()} "
            "-- the default window when none is given, which is narrow. That doesn't mean it "
            "doesn't exist.\n\nWiden the search to which?\n"
            "- last 1 hour\n- last 4 hours\n- last 24 hours\n- last 7 days\n\n"
            "Reply with one of those (or name your own window, e.g. \"last 3 hours\"), "
            "and I'll re-run the same question over it."
        )
    else:
        base = (
            f"I couldn't find any records matching that in {params.time_range.describe()}. "
            "That doesn't mean it doesn't exist -- it may just be outside this window. Try "
            "asking again with a wider window (e.g. \"in the last 7 days\"), or double-check the PS ID."
        )
    if routing_check is not None:
        if routing_check.requested_target_was_configured:
            base += (
                f" One thing this does rule out: per the Additional Routing plan, "
                f"{routing_check.requested_target_system} *is* configured to receive Plant "
                f"{routing_check.plant} / {routing_check.determination_type} transfers -- so if it's "
                "genuinely missing there, that's likely a real transfer issue, not a routing gap."
            )
        elif routing_check.configured_target_systems:
            targets = ", ".join(routing_check.configured_target_systems)
            base += (
                f" Per the Additional Routing plan, Plant {routing_check.plant} / "
                f"{routing_check.determination_type} transfers aren't configured to reach "
                f"{routing_check.requested_target_system} at all -- they're routed to {targets} instead. "
                "That's likely why it's not there, not a failed transfer."
            )
        else:
            base += (
                f" Per the Additional Routing plan, Plant {routing_check.plant} / "
                f"{routing_check.determination_type} transfers have no configured destination at all "
                f"right now -- so {routing_check.requested_target_system} not having it isn't unusual."
            )
    elif params.target_system is not None:
        base += (
            f" Note: whether this was ever supposed to reach {params.target_system} at all isn't "
            "something I can check here -- that depends on the Additional Routing plan and "
            "per-plant Import Configuration, not just this Transfer history. The PST team can confirm."
        )
    return base


@dataclass(frozen=True)
class AgentAnswer:
    """The only shape the UI ever sees. See
    docs/agents/packspec-status/TECHNICAL_SPEC.md's Output Context."""

    query: str
    interpreted_params: SearchParams | None
    primary_records: list[TransferRecord]
    dependent_objects: DependentObjectsView | None
    catalog_matches: list[CatalogMatch]
    plain_language_answer: str


class ConversationStore(Protocol):
    """Per-conversation message history, persisted across restarts (see
    ADR-0002) -- deliberately a small interface, not a bare in-memory list,
    so a single-process SQLite-backed implementation (`app/core/storage.py`)
    can be swapped later without touching the harness."""

    def get_history(self, conversation_id: str) -> list[Message]: ...
    def append_message(self, conversation_id: str, role: str, content: str) -> None: ...


_SKILL_HEADINGS = (
    "## Turn 1: parse the question into `SearchParams`",
    "## Turn 2: compose the answer from `StatusResult`",
    '## Turn 2 (domain mode): answer a "how does this work" question',
    "## Tone",
)
PARSE, COMPOSE, EXPLAIN, TONE = range(4)


def _skill_sections() -> list[str]:
    """Split `skill.md` on its top-level headings, in order.

    Raises if a heading moves or is renamed, rather than silently returning an
    empty section -- a turn quietly losing its rules is exactly the kind of
    failure that surfaces weeks later as degraded answers with no error
    anywhere to point at.
    """
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    missing = [h for h in _SKILL_HEADINGS if h not in skill]
    if missing:
        raise ValueError(f"skill.md is missing heading(s) the per-turn split relies on: {missing}")

    sections, rest = [], skill
    for heading in _SKILL_HEADINGS:
        before, rest = rest.split(heading, 1)
        sections.append(before)
    sections.append(rest)
    # sections[0] is the preamble; the rest are each heading's own body.
    return [sections[0]] + [heading + body for heading, body in zip(_SKILL_HEADINGS, sections[1:])]


def _load_skill(mode: int) -> str:
    """The system instruction for one turn -- deliberately not the same text
    for each.

    Every turn previously received the whole of `skill.md` *and* the whole of
    `CONTEXT.md`: ~12,200 tokens each, ~24,400 per question, against a data
    payload of ~140. The instruction was ~174x the data it reasoned about, so it
    dominated both cost and time-to-first-token while most of it was irrelevant
    to the turn reading it. Measured after this split: ~12,500 per question, a
    49% reduction with no change to what any turn can actually do.

    - `PARSE` turns a question into tool arguments. It needs the field rules,
      the reference-resolution rules and the scope guard -- not the composition
      rules, the catalog rules, or the glossary, none of which can change which
      arguments it picks.
    - `COMPOSE` writes prose from an already-summarized `StatusResult`. It needs
      the glossary and the answer rules, not the tool-argument guidance: there
      is no tool call left to make.
    - `EXPLAIN` answers a domain question, where no search ran at all. It needs
      the glossary and nothing else.

    `Tone` goes to `COMPOSE` and `EXPLAIN` only -- it governs user-facing
    prose, and `PARSE` produces none. Every branch either reads
    `turn1.tool_calls` and discards the text, or (when there is no tool call)
    runs a fresh `EXPLAIN` generate whose output replaces it. Nothing turn 1
    writes reaches a user, so 785 characters of tone guidance per query bought
    nothing. `_EXPLAIN_FALLBACK_ANSWER` is what closes the one path that used
    to leak turn-1 prose, and it must stay closed for this to hold.

    Note `PARSE` deliberately does **not** get the glossary. That is why
    `skill.md`'s turn-1 section tells it to *defer* a domain question rather
    than answer one: the two must stay in step, or the model is told to answer
    from a glossary it does not have.
    """
    sections = _skill_sections()
    preamble, tone = sections[0], sections[TONE + 1]
    body = sections[mode + 1]
    if mode == PARSE:
        return f"{preamble}{body}"
    glossary = knowledge.load_all()
    return f"{preamble}{body}\n{tone}\n\n---\n\n# Project glossary\n\n{glossary}"


_FIELD_LABELS = {
    "ps_id": "PS ID",
    "plant": "plant",
    "supplier": "supplier",
    "customer_index": "customer index",
    "matnr": "material",
    "document_number": "document number",
    "determination_type": "determination type",
    "message_type": "message type",
    "usage": "usage",
    "sales_channel": "sales channel",
    "target_system": "target system",
    "status": "status",
}

_FIELD_HINTS = {
    "target_system": 'name it as "P87" or "SAPP870110"',
    "determination_type": "one of SHIP, RCPT, ZFER, STOC, PALE, DOLL, KIT",
    "message_type": "PackITPackagingSpecification, DocumentInfoRecord or PackITPackagingCockpitMasterData",
    "sales_channel": "OE, OES or IAM",
    "usage": "R for Regular, or A1-A4 for the Alternatives",
    # Only the two values `ReplicationStatus` accepts. It previously offered
    # "RETRY" as well, which is a bucket the dashboard derives downstream from
    # the catalog category, not a raw searchable status -- a user who took the
    # suggestion failed validation again and got this same question back.
    "status": "SUCCESS or ERROR",
}


def _unresolved_field_question(unresolved: tuple[tuple[str, str], ...]) -> str:
    """Ask about values that could not be turned into a filter.

    Deliberately names the value back verbatim. "I couldn't interpret that"
    leaves the user guessing which of the things they said was the problem,
    and on a multi-field question that is most of the message.
    """
    parts = []
    for name, value in unresolved:
        label = _FIELD_LABELS.get(name, name.replace("_", " "))
        hint = _FIELD_HINTS.get(name)
        parts.append(f"- **{label}**: I couldn't interpret `{value}`" + (f" — {hint}." if hint else "."))

    return (
        "I didn't run the search, because part of what you asked for couldn't be applied as a filter "
        "— and searching without it would have quietly answered a wider question than you asked.\n\n"
        + "\n".join(parts)
        + "\n\nCorrect that value and I'll run it."
    )


def _resolve_window_reply(history: list[Message]) -> list[Message]:
    """Turn a bare "24 hours" into the original question plus that window.

    When the not-found answer offers "last 1 hour / 4 hours / 24 hours / 7
    days", the reply is a fragment: on its own it names no PS, no plant,
    nothing to search for. Leaving turn 1 to reconstruct the question from
    conversation history is exactly the reference-resolution this codebase has
    repeatedly measured as unreliable -- and getting it wrong here means
    silently answering about a different PS.

    So it is done in code instead: rewrite the fragment into the last real
    question with the window appended, and hand turn 1 a complete question of
    the shape it already handles well. Returns the history unchanged whenever
    the latest message isn't purely a window, or there is no earlier question
    to attach it to.
    """
    if not history or history[-1].role != "user":
        return history
    window = bare_window_reply(history[-1].content)
    if window is None:
        return history

    previous = next(
        (
            m.content
            for m in reversed(history[:-1])
            if m.role == "user" and bare_window_reply(m.content) is None
        ),
        None,
    )
    if previous is None:
        return history

    described = TimeRange(earliest=window).describe()
    return history[:-1] + [Message(role="user", content=f"{previous.rstrip().rstrip('?')} in {described}")]


def _user_named_a_period_this_turn(history: list[Message]) -> bool:
    """Whether the user raised time in the message being answered right now.

    Reads **only the latest `user` message**, for two reasons.

    The app's own prose contains window phrases -- the widen offer literally
    lists "last 7 days" -- so counting assistant text would let the app talk
    itself into a window the user never chose. That is the same reason
    `_window_from_user_messages` reads only user messages.

    And it is scoped to *this* turn rather than the whole conversation. The
    conversation-wide version licensed the model to supply a window on every
    later turn once the user had named one anywhere, which is a permission
    that should not be granted retroactively and forever: the caller's strip
    branch then never ran again. A window the user stated earlier still
    carries forward -- but through `_window_from_user_messages`, from what
    they actually typed, not through whatever the model produced this turn.

    `_resolve_window_reply` runs before this, so `history[-1]` is the current
    question with any bare-window reply already folded into it.
    """
    latest = next((m for m in reversed(history) if m.role == "user"), None)
    return latest is not None and mentions_a_time_period(latest.content or "")


def _window_from_user_messages(history: list[Message]) -> str | None:
    """The window the user themself last asked for, most recent turn first,
    or `None` if they never named one.

    **Only `user` messages are read, never assistant prose.** That is the
    exact intent of skill.md's anti-echo rule, which exists because a "last
    7 days" window was once lifted from an *example phrase* in this app's
    own fallback answer ("...e.g. 'in the last 7 days'") and presented as
    the window the user had asked for. Reading only what the user typed
    keeps that impossible while still letting a window carry forward across
    follow-ups -- including the case where the user accepts a window the app
    offered ("Try the last 7 days then."), which is the user stating a
    window, not the app echoing itself.

    Needed because the `baseline` regression run measured the model
    re-deriving a window from prior prose on 2 of 10 window-less follow-ups
    -- see `time_window`'s module docstring.
    """
    for message in reversed(history):
        if message.role != "user":
            continue
        window = parse_time_window(message.content)
        if window is not None:
            return window
    return None


_MAX_HOPS_SERIALIZED = 12
"""Above this, only the hop *count* is sent, not the hops themselves.

Sized from the real corpus: the biggest genuine hop histories a person asks
about are single-figure (the 4-hop example that exposed this gap), while S01's
100-attempt retry chain and S02's 48 re-publishes are the cases where sending
each hop would be thousands of tokens of near-identical repetition and tell the
reader nothing the count doesn't."""

_MAX_HOP_DESCRIPTION_CHARS = 400
"""Real Status Descriptions are one or a few lines ("6099.801.262 Packaging
material doesn't exist in plant 5550"). The cap bounds a pathological one
rather than trimming a normal one."""

_SUBJECT_FIELDS = (
    # (key in the payload, TransferRecord attribute or Hop field name)
    # Every key is prefixed `ps_` on purpose. "Plant" and "material" each mean
    # two different things in one answer -- the PS's own, and the one the error
    # text names -- and S03 is the case that proves it: PS 00000000040000434427
    # is at plant 0780 with material 0273011047, while its error reads
    # "packaging material 6000.409.798 in plant 078W". A bare `plant` key beside
    # that description invites cross-attribution, which would send an engineer
    # to the wrong material at the wrong plant. That is worse than vagueness, so
    # the key itself carries the role.
    ("ps_id", "ps_id"),
    ("ps_snr13", "snr13"),
    ("ps_material", "matnr"),
    ("ps_plant", "plant"),
    ("ps_determination_type", "det_type"),
    ("ps_usage", "usage"),
    # Which party the packaging rule is for. Determination Type decides which of
    # the two is populated, and the other being empty is *by design*, not
    # missing: SHIP carries a Customer Index, RCPT carries a Supplier, and the
    # repackaging types (STOC/PALE/DOLL) carry neither. Both are part of
    # OBJECTKEY, so an object-key answer missing one is incomplete for that
    # record type.
    #
    # Supplier was not extracted at all until 2026-08-07, so "give me the object
    # key details" for an RCPT record answered without the field that record
    # type is keyed by. `packindex` was extracted at the same time but never
    # promoted here, leaving the identical gap on every *outbound* record --
    # five of the seven PS captures in this repo -- until 2026-08-08. The
    # comment naming Customer Index as the outbound counterpart was already
    # sitting here when only half the pair was added.
    ("ps_supplier", "supplier"),
    ("ps_customer_index", "packindex"),
    ("ps_sales_channel", "sales_channel"),
    # `AENNR`. Constant `00000001` on the normal path, but part of OBJECTKEY --
    # and `00000002` with an empty activation counter is the PT0 pre-Active
    # signature. See the packaging-specification knowledge topic.
    ("ps_change_number", "change_number"),
    ("ps_group", "ps_group"),
    ("ps_packspec_status", "packspec_status"),
    ("determination_record_seqno", "seqno"),
    ("activation_counter", "activation_counter"),
    # The PS's own declaration of its linked Document Info Records, always
    # present. Previously these were parsed off the payload and then only ever
    # shown inside `dependent_objects` -- which is populated only when the PS is
    # dependent-object-*blocked* on an xOE target. So "do we have a DIR linked
    # to this PS?" was unanswerable for any ordinary PS, even though the app was
    # holding the answer. An empty tuple is itself the answer ("none declared"),
    # not missing information: a DIR trigger is optional.
    ("ps_document_links", "document_link_keys"),
)


def _field(record: TransferRecord, name: str) -> object:
    """Read a subject field off a Transfer, preferring the business-object
    value that any hop carries over whatever `.latest` happens to hold."""
    value = getattr(record, name, None)
    return value if value is not None else record.identity(name)


def _summarize_outcome(record: TransferRecord) -> dict:
    """What actually happened to one Transfer, with the two count concepts kept
    apart.

    `hops` is processing attempts *at the Target System* for a single trigger --
    S01's 100. The number of distinct Transfers is source-side *retriggers* --
    S02's 48. Both were previously called "attempts", which made two opposite
    situations (the target failing to process one message, versus the source
    re-sending) indistinguishable in an answer, though they need different
    fixes."""
    outcome = {
        "target_system": record.target_system,
        "status": record.current_status,
        "description": record.current_description,
        "hops_at_target": len(record.hops),
    }

    # The hop history itself, when it is short enough to be worth the tokens.
    #
    # Until 2026-08-07 only the count was sent, so every hop but the latest was
    # discarded before the model saw anything -- and "can you provide the error
    # logs recorded in those 4 hops?" was answered "I don't have direct access
    # to the error logs", while the app was holding two Business Errors
    # ("6099.801.262 Packaging material doesn't exist in plant 5550") for
    # exactly those hops. A confidently wrong *negative* about data already in
    # memory, which is the worst kind: nothing about it looks suspicious.
    #
    # The cap is what makes this safe. S01's 100-hop retry chain would add
    # thousands of tokens of near-identical repetition to every answer, which
    # is why `docs/components/transform/TECHNICAL_SPEC.md` specified a
    # code-decided rule rather than always sending them. Above the cap the
    # count still tells the story ("100 attempts, all the same error"); below
    # it, the individual hops are the story.
    if len(record.hops) <= _MAX_HOPS_SERIALIZED:
        outcome["hops"] = [
            {
                "time": hop.time,
                "host": hop.host,
                "status": hop.business_status,
                "description": (hop.description or "")[:_MAX_HOP_DESCRIPTION_CHARS] or None,
            }
            for hop in record.hops
        ]

        # Errors that have since been overtaken by a Success are *history*, and
        # must be labelled as such rather than left for the reader to infer
        # from hop ordering.
        #
        # Sending the hop list at all is what created this risk. Before it, the
        # model never saw the error text of a resolved Transfer; with it, the
        # first Gemini run of S14 answered a question about six historical
        # failures with a confident "Cause & Solution: extend material
        # 6099.801.262 to plant 5550" -- remediation for a problem the seventh
        # attempt had already resolved, and with `catalog_matches` empty,
        # since catalog matching runs on the *latest* description (a success).
        # So the advice was both stale and ungrounded, in the exact shape of a
        # documented catalog answer.
        earlier_errors = sum(1 for hop in record.hops if hop.business_status == "ERROR")
        if earlier_errors and record.current_status == "SUCCESS":
            outcome["earlier_errors_resolved"] = earlier_errors
    return outcome


def _summarize_records(records: list[TransferRecord]) -> dict:
    """Hoist what every Transfer shares into one `subject` block, and list only
    what actually differs.

    Records for one PS repeat their identity verbatim -- S02's 48 differ only by
    Message ID -- so stating it once is both richer and much cheaper there.

    Measured against the previous flat shape, honestly mixed:

        S02 (48 records)   ~2664 -> ~140 tokens   -95%
        S03 (2 records)    ~125  -> ~194          +55%
        S01 (1 record)     ~51   -> ~135         +164%

    The saving is real only where records repeat; a single-record result pays
    ~84 extra tokens for SNR13, SEQNO, activation counter, PS Group, Sales
    Channel and Packspec Status that the flat shape never carried at all. That
    trade is worth taking on absolute numbers -- 84 tokens is noise beside a
    ~2000-token skill instruction -- and it pays for itself the moment it saves
    one follow-up turn, since each of those costs two LLM calls plus a full
    Splunk job (S01's q2 and q3 existed only to chase facts the first turn
    already held).

    The shared/varying split is **computed, never assumed** -- a field that
    differs across records drops out of `subject` entirely rather than having
    one record's value stand for all of them.
    """
    if not records:
        return {"subject": None, "outcomes": [], "transfer_count": 0}

    subject: dict[str, object] = {}
    for key, attribute in _SUBJECT_FIELDS:
        values = {_field(record, attribute) for record in records}
        values.discard(None)
        if len(values) == 1:
            subject[key] = values.pop()
        elif values:
            # Genuinely divergent -- surfacing one value would be a guess.
            subject[key] = sorted(str(v) for v in values)

    outcomes = [_summarize_outcome(record) for record in records]
    deduped: list[dict] = []
    for outcome in outcomes:
        match = next((d for d in deduped if _same_outcome(d, outcome)), None)
        if match is None:
            deduped.append({**outcome, "transfers": 1})
        else:
            match["transfers"] += 1
            match["hops_at_target"] += outcome["hops_at_target"]

    return {
        "subject": subject,
        # `transfers` on each outcome is how many separate triggers produced
        # that same result -- S02's 48 retriggers collapse to one entry saying
        # so, instead of 48 identical ones.
        "outcomes": deduped,
        "transfer_count": len(records),
        "message_type": records[0].message_type,
    }


def _same_outcome(left: dict, right: dict) -> bool:
    return all(left[k] == right[k] for k in ("target_system", "status", "description"))


def _summarize_dependent_objects(view: DependentObjectsView | None) -> dict | None:
    """`None` means the question does not arise on this target line -- Dependent
    Object and DIR triggers are only ever sent to xOE (POE/QOE), so anywhere
    else there is nothing to have found and nothing to say. Distinct from a
    populated view with empty lists, which means we looked and found none."""
    if view is None:
        return None
    return {
        "document_info_records": _summarize_records(view.document_info_records),
        "cockpit_master_data": _summarize_records(view.cockpit_master_data),
        # A PS trigger to POE always carries a Dependent Object trigger, so an
        # empty `cockpit_master_data` here is a real finding. The same emptiness
        # anywhere else means nothing at all.
        "missing_dependent_object_is_anomalous": view.missing_is_anomalous,
        # What the PS's own payload declares, found or not -- so "declares no
        # linked documents" stays distinguishable from "declares two, neither
        # has appeared".
        "declared_document_links": list(view.linked_document_keys),
    }


def _summarize_catalog_match(match: CatalogMatch) -> dict:
    return {
        "seq_nr": match.seq_nr,
        "error_category": match.error_category,
        "responsible": match.responsible,
        "summary": match.summary,
        "solution": match.solution,
    }


def _summarize_routing_check(check: RoutingCheck | None) -> dict | None:
    if check is None:
        return None
    return {
        "plant": check.plant,
        "determination_type": check.determination_type,
        "configured_target_systems": list(check.configured_target_systems),
        "requested_target_system": check.requested_target_system,
        "requested_target_was_configured": check.requested_target_was_configured,
    }


def _summarize_status_result(result: StatusResult, params: SearchParams) -> dict:
    return {
        "found": _summarize_records(result.primary_records),
        "dependent_objects": _summarize_dependent_objects(result.dependent_objects),
        # Transfers dropped as belonging to an older activation of the same
        # Determination Record. Reported rather than silently omitted: the
        # answer should be able to say older activations exist, and a result set
        # that quietly shrank is how a tool loses trust.
        "superseded_transfer_count": result.superseded_count,
        "catalog_matches": [_summarize_catalog_match(m) for m in result.catalog_matches],
        # Caught live via QA testing: without this, the model literally has
        # no way to state what window it searched when composing a "not
        # found" answer -- it was never given that data, only the search
        # results. It would say generic things like "try widening the
        # window" without a number, which technically satisfies the
        # not-found-acknowledgement check but isn't actually the honest,
        # specific answer skill.md's rule 1 asks for.
        "time_range_searched": params.time_range.describe(),
        # Only populated when a specific target_system was asked about and
        # nothing was found there but the PS existed elsewhere -- see
        # pipeline.RoutingCheck. `_not_found_answer` states this
        # deterministically regardless of what the LLM does with it (see
        # that function's docstring), but it's included here too so the
        # LLM's own answer can lead with it directly when the search DID
        # find something (e.g. an error on another target) alongside it.
        "routing_check": _summarize_routing_check(result.routing_check),
    }


def _has_ungrounded_fix_claim(answer: str, result: StatusResult) -> bool:
    """True if the answer looks like it's asserting a documented fix despite
    `catalog_matches` being empty -- the case the strict grounding rule
    forbids. Cheap heuristic against already-structured data, not a second
    LLM call; see ARCHITECTURE.md's Guardrails section."""
    has_error = any(r.current_status == "ERROR" for r in result.primary_records)
    if not has_error or result.catalog_matches:
        return False
    return not any(marker in answer.lower() for marker in _TICKET_FALLBACK_MARKERS)


_REMEDIATION_BLOCK_RE = re.compile(
    r"\n[^\n]{0,40}?\b(?:cause\s*(?:&|and|/)\s*(?:suggested\s+action|solution|fix)"
    r"|suggested\s+action|recommended\s+action|solution|remediation)\b.*",
    re.IGNORECASE | re.DOTALL,
)
"""A trailing "Cause & Suggested Action" style block, from its heading to the
end of the answer."""

_RESOLVED_NO_ACTION = (
    "\n\nThose errors are history — the Transfer went on to succeed, so there is nothing "
    "outstanding to fix here. No documented cause is on file for them in the error catalog."
)


def _strip_ungrounded_remediation(answer: str, result: StatusResult) -> str:
    """Remove a cause/fix block the catalog does not support.

    `_has_ungrounded_fix_claim` covers the case where a Transfer is *currently*
    failing. It cannot cover this one: when a Transfer failed six times and then
    succeeded, `current_status` is SUCCESS, so that guard never fires -- yet the
    hop history now puts six error descriptions in front of the model, and it
    fills the gap with plausible SAP advice of its own.

    Measured, twice, on the first live runs of S14: "Cause: The plant view for
    packaging material 6099.801.262 has not been created in plant 5550.
    Solution: Extend packaging material 6099.801.262 to plant 5550" -- for a
    problem the seventh attempt had already resolved, with `catalog_matches`
    empty, formatted exactly like a documented answer. Both a `skill.md` rule
    and an `earlier_errors_resolved` flag in the payload were ignored, which is
    this codebase's recurring result for anything enforced only by prompt.

    The whole answer is not discarded: the hop-by-hop history above the block is
    exactly what was asked for and is correct. Only the unsupported tail goes.
    """
    if result.catalog_matches:
        return answer
    resolved = any(
        record.current_status == "SUCCESS" and any(hop.business_status == "ERROR" for hop in record.hops)
        for record in result.primary_records
    )
    if not resolved:
        return answer
    stripped = _REMEDIATION_BLOCK_RE.sub("", answer)
    if stripped == answer:
        return answer
    return stripped.rstrip() + _RESOLVED_NO_ACTION


def _has_missing_not_found_acknowledgement(answer: str, result: StatusResult) -> bool:
    """True if `primary_records` is completely empty (nothing found in
    Splunk at all) but the answer doesn't acknowledge that. Distinct from
    `_has_ungrounded_fix_claim`: conflating "nothing found" with "found, but
    an undocumented error" sends the user down the wrong path (raising a
    ticket) instead of the actually useful one (check the ID, widen the
    window) -- caught live via adversarial testing, see
    scripts/adversarial_eval.py's GRD-01 case."""
    if result.primary_records:
        return False
    return not any(marker in answer.lower() for marker in _NOT_FOUND_MARKERS)


_WINDOW_CLAIM_CUE_RE = re.compile(
    r"\b(?:searched|searching|search of|checked|scanned|looked|found|returned|showed|shows|"
    r"no records|no results|records for|results for)\b",
    re.IGNORECASE,
)
_WINDOW_SUGGESTION_CUE_RE = re.compile(
    r"(?:\be\.g\.|\b(?:try|trying|widen|wider|expand|broaden|example|consider|instead|"
    r"recommend|suggest|you could|you can|you may|you might|want me to|would you|again with)\b)",
    re.IGNORECASE,
)
"""Matched on word boundaries, not as substrings: "couldn't find" contains
"could" and "the retry chain" contains "try", and either would have
suppressed a genuine false claim as if it were a suggestion."""

_WINDOW_CLAIM_CONTEXT = 80
"""Characters of preceding text that decide whether a window phrase is a
*claim about what was searched* or a *suggestion to search something else*.
`_not_found_answer` itself ends with `Try asking again with a wider window
(e.g. "in the last 7 days")`, and the LLM legitimately paraphrases that --
so the suggestion cues are checked first and win."""


def _claimed_time_windows(answer: str, params: SearchParams) -> list[TimeWindowMention]:
    """Window phrases the answer asserts were actually searched, but which
    disagree with the window that actually was.

    Caught by the `baseline` regression run (S05/02_q2_widen): handed
    `time_range_searched = "the last 15 minutes"`, the model wrote *"even
    when searched in the last 7 days"* -- over 7 days that PS returns 100
    rows, so the claim is false, not merely unverified. It reached the user
    because `_has_missing_not_found_acknowledgement` returns `False` the
    moment any not-found marker appears ("couldn't find" was in the same
    sentence), leaving everything after that marker unexamined. This check
    is deliberately independent of it: a fabrication about the product's own
    behaviour is exactly as ungrounded as a fabricated fix, and the true
    window is already in scope here.
    """
    claimed = []
    for mention in find_time_windows(answer):
        if mention.earliest == params.time_range.earliest:
            continue
        context = answer[max(0, mention.start - _WINDOW_CLAIM_CONTEXT) : mention.start]
        if _WINDOW_SUGGESTION_CUE_RE.search(context):
            continue
        if _WINDOW_CLAIM_CUE_RE.search(context):
            claimed.append(mention)
    return claimed


def _correct_stated_time_window(answer: str, params: SearchParams, claimed: list[TimeWindowMention]) -> str:
    """Replace each falsely-claimed window phrase with the real one, in
    place. Both strings are known exactly, so there's no reason to discard
    an otherwise-grounded answer over one wrong phrase -- unlike the empty
    result case, where `_not_found_answer` is the better answer anyway
    because it also states what to do next."""
    for mention in reversed(claimed):  # right to left, so earlier spans stay valid
        answer = answer[: mention.start] + params.time_range.describe() + answer[mention.end :]
    return answer


_CONTINUATION_PROMISE_RE = re.compile(
    r"\b(?:"
    r"please hold on|hold on|bear with|one moment|give me a moment|stay tuned|"
    r"i(?:'ll|’ll| will| am going to|'m going to|’m going to| need to| still need to| have to)"
    r"\s+(?:now\s+)?(?:check|look|search|verify|retrieve|fetch|pull|review|gather|confirm|investigate)|"
    r"(?:i am|i'm|i’m)\s+(?:now\s+)?(?:checking|looking|searching|retrieving|fetching|reviewing)|"
    r"now checking|checking now|"
    r"let me (?:check|look|search|verify|retrieve|pull|gather)"
    r")",
    re.IGNORECASE,
)
"""First-person commitments to *further work by the assistant*. Matched
narrowly on purpose: "Let me know if you need more detail" and
`_not_found_answer`'s "Try asking again with a wider window" are innocent
and must not trip this."""

_UNFULFILLED_PROMISE_NOTICE = (
    "I can only run one search per question, so nothing beyond that search was checked here -- "
    "ask about anything else as a separate question and I can look it up then."
)

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])(\s+)")


def _strip_continuation_promise(answer: str) -> str:
    """Drop any sentence promising a further check, and say plainly that
    there won't be one.

    Caught by the `baseline` regression run (S08, all three turns): every
    reply ended "I will now check PS 00000000040001399187... Please hold
    on." Across all 28 Splunk jobs in the run, that PS was never searched --
    the architecture runs two LLM calls and one tool call per question and
    then stops (ADR-0001), and the UI shows no pending state, so the silence
    reads as "nothing to report" about a PS that is really in ERROR. All
    three turns passed their mechanical checks; the user has nothing on
    screen to catch it with.

    skill.md now states the one-tool-call rule outright, but the same run
    established that a prompt rule alone doesn't hold in this app (the
    window-extraction rule was rewritten three ways and never got above
    3/5), so this is the code-level half -- the same reason
    `is_underspecified` and the checks above aren't prompt rules either.
    """
    pieces = _SENTENCE_BOUNDARY_RE.split(answer)
    kept: list[str] = []
    dropped = False
    for index in range(0, len(pieces), 2):
        sentence = pieces[index]
        if _CONTINUATION_PROMISE_RE.search(sentence):
            dropped = True
            continue
        separator = pieces[index - 1] if index and kept else ""
        kept.append(separator + sentence)
    if not dropped:
        return answer
    remaining = "".join(kept).strip()
    return f"{remaining}\n\n{_UNFULFILLED_PROMISE_NOTICE}" if remaining else _UNFULFILLED_PROMISE_NOTICE


_WIDEN_OFFER = (
    "\n\nWiden the search to which?\n"
    "- last 1 hour\n- last 4 hours\n- last 24 hours\n- last 7 days\n\n"
    "Reply with one of those (or name your own window, e.g. \"last 3 hours\"), "
    "and I'll re-run the same question over it."
)


def _append_widen_offer(answer: str, result: StatusResult, params: SearchParams) -> str:
    """Offer concrete windows whenever the narrow default found nothing.

    Appended rather than substituted, and unconditionally rather than only when
    the answer is overridden. `_has_missing_not_found_acknowledgement` stops
    checking as soon as the reply contains any not-found marker, so a model
    answer that says "not found in the last 15 minutes" in its own words keeps
    that wording and never reaches `_not_found_answer` -- which is where the
    offer lives. Measured: the offer appeared in none of those replies.

    The options are worded exactly as `time_window.bare_window_reply` reads
    them back, so the user's one-word answer resolves instead of dead-ending.
    """
    if result.primary_records or params.time_range != TimeRange.default():
        return answer
    if "widen the search to which" in answer.lower():
        return answer  # already carries it, via _not_found_answer
    return answer.rstrip() + _WIDEN_OFFER


def _enforce_grounding(answer: str, result: StatusResult, params: SearchParams) -> str:
    if _has_missing_not_found_acknowledgement(answer, result):
        return _append_widen_offer(_not_found_answer(params, result.routing_check), result, params)
    if _has_ungrounded_fix_claim(answer, result):
        return _GROUNDING_FALLBACK_ANSWER
    claimed_windows = _claimed_time_windows(answer, params)
    if claimed_windows:
        if not result.primary_records:
            return _append_widen_offer(_not_found_answer(params, result.routing_check), result, params)
        answer = _correct_stated_time_window(answer, params, claimed_windows)
    answer = _strip_ungrounded_remediation(answer, result)
    return _append_widen_offer(_strip_continuation_promise(answer), result, params)


def run_query(
    conversation_id: str,
    user_query: str,
    *,
    config: AgentConfig,
    llm: LLMClient,
    store: ConversationStore,
    on_step: OnStep | None = None,
) -> AgentAnswer:
    """Run one full query: persist it, ask the LLM to parse it into
    `SearchParams` (turn 1), run `get_ps_status` once, ask the LLM to
    compose the final answer from the already-summarized result (turn 2),
    enforce the grounding rule in code, and persist the answer. Exactly two
    LLM calls -- see ADR-0001.
    """

    def step(message: str) -> None:
        if on_step is not None:
            on_step(message)

    store.append_message(conversation_id, "user", user_query)
    try:
        return _run_query_body(conversation_id, user_query, config=config, llm=llm, store=store, step=step)
    except Exception:
        # Caught live via QA testing: without this, a failure here (an
        # LLMUnavailableError, a Splunk error) left the just-persisted user
        # message with no paired reply anywhere -- in `get_history` (so the
        # next turn's context has an unanswered dangling question) and in
        # the `/api/issues` mailto body (so a support report reproduces the
        # same gap). A paired marker keeps the transcript coherent and
        # honest about what happened, instead of the question silently
        # appearing to have been ignored.
        store.append_message(conversation_id, "assistant", _QUERY_FAILED_MARKER)
        raise


_log = logging.getLogger(__name__)


def _observe_predicates(user_query: str, result: StatusResult) -> None:
    """Record which `loads_when` predicates this turn would have satisfied.

    **Observation only, and it must stay that way.** Every topic is still
    loaded on every turn; this changes no answer. It exists because the case
    for selective loading rests on a number nobody has: how often each
    predicate actually fires. Withholding a topic before that is measured
    trades a known cost (tokens) for an unknown one (an answer that needed it).

    Swallows everything. A miscount in instrumentation must never be able to
    cost a user their answer -- which is the whole reason this is a separate
    function with a bare `except` rather than four expressions inlined above.
    """
    try:
        records = result.primary_records
        _log.info(
            "loads_when_would_fire=%s",
            sorted(
                knowledge.firing_predicates(
                    user_query,
                    superseded_count=result.superseded_count,
                    has_dependent_objects=result.dependent_objects is not None,
                    target_system_count=len({r.target_system for r in records if r.target_system}),
                    max_hops=max((len(r.hops) for r in records), default=0),
                )
            ),
        )
    except Exception:  # noqa: BLE001 -- instrumentation may never break a turn
        _log.debug("predicate observation failed", exc_info=True)


def _run_query_body(
    conversation_id: str,
    user_query: str,
    *,
    config: AgentConfig,
    llm: LLMClient,
    store: ConversationStore,
    step: OnStep,
) -> AgentAnswer:
    history = _resolve_window_reply(store.get_history(conversation_id))

    step("Interpreting your question...")
    turn1 = llm.generate(history, tools=[_GET_PS_STATUS_TOOL], system_instruction=_load_skill(PARSE))

    params = None
    if turn1.tool_calls:
        arguments = turn1.tool_calls[0].arguments
        if not arguments.get("time_earliest"):
            # The model left the window out -- measured at 11 of 12 trials
            # in the `baseline` regression run even when the user stated one
            # in plain English (see app/core/time_window.py). Fill it in
            # from the user's own words instead. Fed in as a raw argument
            # rather than onto the finished `SearchParams` so
            # `parse_search_params` still applies its own validation and
            # `TimeRange.MAX_DAYS` capping to it.
            window = _window_from_user_messages(history)
            if window is not None:
                arguments = {**arguments, "time_earliest": window}
        elif not _user_named_a_period_this_turn(history):
            # The model supplied a window on a turn where the user raised no
            # time at all. Two ways that can be wrong, and they need different
            # repairs.
            #
            # The rule being protected: search the last 15 minutes, and if
            # nothing turns up, *offer* concrete widths and let the user
            # choose. A model free to invent `-7d` bypasses that -- seen live
            # on "the latest successful transfer to target system P87",
            # answered across seven days with no offer ever made, because the
            # window came from the model rather than the user.
            #
            # The model's value is still honoured whenever the user did raise
            # time in some form the parser declines to resolve exactly ("since
            # this morning", "over the weekend") -- that was the original
            # reason for trusting it. Note that test is now scoped to *this
            # turn*. It used to ask whether the user had named a period
            # anywhere in the conversation, which meant one "in the last 3
            # hours" at turn 1 licensed the model to supply any window it
            # liked for the rest of the conversation, and the branch below
            # never ran again. That reopened the echo failure
            # `_window_from_user_messages` exists to prevent: a "-7d" lifted
            # from `_not_found_answer`'s own example phrase went straight to
            # Splunk. See the regression test named for it.
            carried = _window_from_user_messages(history)
            if carried is not None:
                # The user did state a window earlier; carry theirs forward
                # rather than the model's. Same precedence as the branch
                # above -- what the user typed beats what the model produced.
                arguments = {**arguments, "time_earliest": carried}
            else:
                # Invented out of nothing. Back to the documented default.
                arguments = {k: v for k, v in arguments.items() if k != "time_earliest"}
        params = parse_search_params(arguments)

    if params is None or is_underspecified(params):
        # Either the LLM didn't call the tool at all, it called it with
        # nothing usable, or it called it with only a single broad field
        # (e.g. sales_channel alone) -- e.g. an off-topic question ("what's
        # the capital of France?"), pure small talk, or a genuinely vague
        # on-topic one. Caught live via manual scope-boundary testing: an
        # all-null (or nearly-null) SearchParams still builds a valid SPL
        # query (see splunk_client.build_spl) that can return up to 200
        # arbitrary real production records -- get_ps_status would then
        # dutifully catalog-match whatever random errors happened to be in
        # that batch and present them as if relevant. Never run that search
        # at all; this is a code-level guard, not a prompt instruction,
        # because it doesn't depend on the LLM correctly judging
        # specificity -- it structurally prevents an unscoped-enough query
        # from ever reaching Splunk regardless of why the params ended up
        # that way.
        # Two different situations reach here, and they need different answers.
        #
        # No tool call at all (`params is None`) means the model judged this a
        # "how does this work" question. Answer it in a second turn that has the
        # glossary -- turn 1 deliberately does not. This also closes the gap
        # where the branch returned raw turn-1 text with no grounding pass: 6 of
        # 28 turns in the `baseline` run took it, and it produced "there is no
        # documented fix" for an error that has catalog row 2. A confidently
        # wrong *negative* about documented knowledge is worse than an invented
        # fix, because nothing about it looks suspicious.
        #
        # A tool call whose params are too broad means the model *tried* to
        # search and could not pin the question down -- typically a follow-up
        # whose reference it failed to resolve. Sending that to the glossary
        # turn produces a confident essay about the domain in place of an
        # answer about the data the user actually asked for. Caught in the
        # `enriched_full` run (S02/q3, "which dependent objects exactly are
        # holding it up?"): zero searches, and a general explanation of what a
        # Dependent Object is. Ask instead.
        if params is not None:
            answer_text = (
                "I need at least something more specific to search on -- a PS ID, or two or more of "
                "plant/determination type/message type/target system/etc. Could you narrow it down?"
            )
        else:
            step("Composing answer...")
            explained = llm.generate(history, tools=[], system_instruction=_load_skill(EXPLAIN))
            answer_text = _strip_continuation_promise(explained.text or "") or _EXPLAIN_FALLBACK_ANSWER
        store.append_message(conversation_id, "assistant", answer_text)
        return AgentAnswer(
            query=user_query,
            interpreted_params=params,
            primary_records=[],
            dependent_objects=None,
            catalog_matches=[],
            plain_language_answer=answer_text,
        )

    if params.unresolved:
        # Something the user asked for could not be turned into a filter. The
        # SPL simply omits it, so the search silently widens and the answer
        # reads as though the constraint applied -- live example: "the latest
        # successful transfer to target system P87" lost its `host=` clause,
        # searched every system, and confidently reported SAPPT00110. It also
        # took four minutes, because an unscoped search is a far heavier one.
        #
        # Asking is the only honest option, and it must be decided in code:
        # the model has no way to know a value it supplied was discarded after
        # it made the call.
        answer_text = _unresolved_field_question(params.unresolved)
        store.append_message(conversation_id, "assistant", answer_text)
        return AgentAnswer(
            query=user_query,
            interpreted_params=params,
            primary_records=[],
            dependent_objects=None,
            catalog_matches=[],
            plain_language_answer=answer_text,
        )

    status_result = get_ps_status(params, config, on_step=step)
    _observe_predicates(user_query, status_result)

    step("Composing answer...")
    turn2_messages = history + [Message(role="user", content=wrap_untrusted_data(_summarize_status_result(status_result, params)))]
    turn2 = llm.generate(turn2_messages, tools=[], system_instruction=_load_skill(COMPOSE))
    answer_text = _enforce_grounding(turn2.text or _GROUNDING_FALLBACK_ANSWER, status_result, params)

    store.append_message(conversation_id, "assistant", answer_text)

    return AgentAnswer(
        query=user_query,
        interpreted_params=params,
        primary_records=status_result.primary_records,
        dependent_objects=status_result.dependent_objects,
        catalog_matches=status_result.catalog_matches,
        plain_language_answer=answer_text,
    )
