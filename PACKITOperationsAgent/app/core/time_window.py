"""Deterministic natural-language time-window extraction.

Caught by the `baseline` regression run (see
`regressionSuite/runs/baseline/findings/ORCHESTRATOR-EXPERIMENTS.md`): the
configured model omits `time_earliest` from its `get_ps_status` tool call
even when the user states a window in plain English -- **11 of 12 controlled
trials**, with validation dropping a supplied value zero times. So the app
searched its default 15 minutes and answered "not found" about a window
nobody asked for, and every PS in the frozen corpus returns zero rows at
15 minutes. Neither a more directive tool-schema description nor a rewrite
of skill.md's own time-window guidance moved the follow-up cases off 0/5.

Extraction therefore cannot depend on the model judging correctly -- the
same reasoning that put `is_underspecified` and `_enforce_grounding` in
code rather than in the prompt. This module is that code-level guard, kept
separate from the harness so it is directly unit-testable.

Deliberately conservative: only a *trailing window relative to now* is
recognised. Anything else ("yesterday", "since Tuesday", "between 9 and
11") yields `None` and leaves the documented default in place, because
searching a window the user did not ask for is the defect this exists to
prevent, not a fallback it may take liberties with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UNIT_WORDS = {
    "minute": "minute", "minutes": "minute", "min": "minute", "mins": "minute",
    "hour": "hour", "hours": "hour", "hr": "hour", "hrs": "hour",
    "day": "day", "days": "day",
    "week": "week", "weeks": "week",
    "month": "month", "months": "month",
    "year": "year", "years": "year",
}

_UNIT_TO_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
"""Everything coarser than an hour is emitted in **days**, never in its own
initial letter. Splunk's relative-time `m` means *minutes*, so a naive
"months -> -3m" mapping would turn "the last 3 months" into a three-minute
search -- the exact defect this module fixes, reintroduced by the fix and
invisible in a test that only asserts a value came back. Months/years are
converted here and then capped by `TimeRange.MAX_DAYS` (30 days) in
`domain._validate_time_range`, the same way an over-wide model-supplied
value already is.
"""

_UNITS_PATTERN = "|".join(sorted(_UNIT_WORDS, key=len, reverse=True))
_LEAD_IN = r"(?:the\s+)?(?:last|past|previous)"

_NUMBERED_RE = re.compile(rf"\b{_LEAD_IN}\s+(\d{{1,4}})\s*({_UNITS_PATTERN})\b", re.IGNORECASE)
_SINGULAR_RE = re.compile(r"\b(?:the\s+)?(?:last|past|previous|this)\s+(minute|hour|day|week|month|year)\b", re.IGNORECASE)
_TODAY_RE = re.compile(r"\btoday\b", re.IGNORECASE)


@dataclass(frozen=True)
class TimeWindowMention:
    """One window phrase found in a piece of text, with the span it occupies
    so a caller can correct that phrase in place rather than discarding the
    whole text around it -- see `harness._correct_stated_time_window`."""

    start: int
    end: int
    text: str
    earliest: str


def _relative_time(amount: int, unit: str) -> str | None:
    if amount <= 0:
        return None
    if unit == "minute":
        return f"-{amount}m"
    if unit == "hour":
        return f"-{amount}h"
    days = amount * _UNIT_TO_DAYS[unit]
    # "the last day" and "the last 24 hours" are the same window; emitting
    # -24h for both keeps `TimeRange.describe()` reading naturally ("the
    # last 24 hours", not "the last 1 day") in the not-found answer.
    return "-24h" if days == 1 else f"-{days}d"


def find_time_windows(text: str) -> list[TimeWindowMention]:
    """Every trailing-window phrase in `text`, in order of appearance.

    Used both to read a window out of what the user typed and to audit what
    an answer *claims* was searched (defect D2 of the `baseline` run: an
    answer that says "even when searched in the last 7 days" about a search
    that covered 15 minutes).
    """
    mentions: list[TimeWindowMention] = []

    for match in _NUMBERED_RE.finditer(text):
        earliest = _relative_time(int(match.group(1)), _UNIT_WORDS[match.group(2).lower()])
        if earliest:
            mentions.append(TimeWindowMention(match.start(), match.end(), match.group(0), earliest))
    for match in _SINGULAR_RE.finditer(text):
        earliest = _relative_time(1, match.group(1).lower())
        if earliest:
            mentions.append(TimeWindowMention(match.start(), match.end(), match.group(0), earliest))
    for match in _TODAY_RE.finditer(text):
        mentions.append(TimeWindowMention(match.start(), match.end(), match.group(0), "-24h"))

    mentions.sort(key=lambda mention: (mention.start, -(mention.end - mention.start)))
    deduped: list[TimeWindowMention] = []
    for mention in mentions:
        if deduped and mention.start < deduped[-1].end:
            continue  # e.g. "today" inside a longer phrase -- keep the longer read
        deduped.append(mention)
    return deduped


_BARE_WINDOW_RE = re.compile(
    rf"^\W*(?:{_LEAD_IN}\s+)?(\d{{1,4}})\s*({_UNITS_PATTERN})\W*$|^\W*-?(\d{{1,4}})\s*([mhd])\W*$",
    re.IGNORECASE,
)


def bare_window_reply(text: str) -> str | None:
    """The window a message asks for when the message is **nothing but** a
    window -- "24 hours", "7d", "last 7 days", "-24h".

    Deliberately anchored to the whole message. When the app has just asked
    "widen to 1 hour / 4 hours / 24 hours / 7 days?", the natural reply is a
    bare "24 hours", which `parse_time_window` refuses on purpose: without the
    "last/past" lead-in, a number-plus-unit inside a longer sentence is far too
    easy to misread ("this has been failing for 3 days", "activated 2 days
    ago"). Requiring the message to consist of nothing else keeps the reply
    understood without opening that door.

    Returns `None` for "other", a bare number, or anything with more words in
    it -- all of which mean the user is saying something the caller should not
    guess at.
    """
    match = _BARE_WINDOW_RE.match(text.strip())
    if not match:
        return None
    if match.group(1):
        return _relative_time(int(match.group(1)), _UNIT_WORDS[match.group(2).lower()])
    unit = {"m": "minute", "h": "hour", "d": "day"}[match.group(4).lower()]
    return _relative_time(int(match.group(3)), unit)


_PERIOD_WORDS_RE = re.compile(
    rf"\b(?:{_UNITS_PATTERN}|today|yesterday|tonight|overnight|ago|since|between|"
    r"morning|afternoon|evening|night|week|weekend|so\s+far)\b",
    re.IGNORECASE,
)


def mentions_a_time_period(text: str) -> bool:
    """Whether the user named a period at all -- however loosely.

    Not the same question as `parse_time_window`, which asks whether a window
    can be resolved *exactly*. This one asks whether the user raised the
    subject of time, so a caller can tell "since this morning" (a real window
    this module deliberately declines to guess at) from a question that says
    nothing about time whatsoever.

    That distinction is what protects the documented default. The rule is:
    search the default 15 minutes, and if nothing is found, offer to widen.
    A model free to invent `-7d` on a question with no time in it bypasses
    that entirely -- seen live on "the latest successful transfer to target
    system P87", answered over seven days without ever offering, because the
    model chose the window and the harness honoured it.

    Note **"latest"/"most recent" are not periods**. They order results; they
    do not bound them. Treating them as a window is how "the latest transfer"
    silently became "everything in the last week".
    """
    return bool(_PERIOD_WORDS_RE.search(text))


def parse_time_window(text: str) -> str | None:
    """The Splunk relative `earliest` `text` asks for, or `None`.

    `None` whenever the answer isn't a single unambiguous one -- no window
    phrase at all, or two different ones in the same message ("not the last
    hour, the last 7 days"). Guessing between them would re-create the
    defect this module exists to prevent, and the default window is at
    least stated back to the user by `harness._not_found_answer`.
    """
    values = {mention.earliest for mention in find_time_windows(text)}
    return values.pop() if len(values) == 1 else None
