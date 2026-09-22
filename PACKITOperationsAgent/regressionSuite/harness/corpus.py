"""The frozen Splunk corpus: every real captured payload in `splunkExamples/`,
loaded once, time-shifted onto a stable relative clock, and queryable with a
faithful-enough emulation of the SPL that `app/tools/splunk_client.build_spl`
actually produces.

Why a frozen corpus rather than live Splunk: an *expected result set* is only
meaningful if the data behind it cannot move. Live Splunk's contents change
minute to minute, so a wrong answer and a changed backend are indistinguishable
-- exactly the ambiguity a regression suite exists to remove. Freezing the data
means every deviation in the app's answer is attributable to the app.

The one thing deliberately NOT frozen is the LLM: the real configured model
runs for real on every query. Hallucination is an LLM-layer failure, and it can
only be detected by holding the data constant and checking whether the prose
faithfully reports it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _PROJECT_ROOT / "splunkExamples"

PAYLOAD_FILES = (
    _EXAMPLES / "example5" / "payload5",
    _EXAMPLES / "example4" / "payload4",
    _EXAMPLES / "example6" / "payload6",
    _EXAMPLES / "example2" / "payload2",
    _EXAMPLES / "example1" / "payload",
    _EXAMPLES / "example3" / "payload3",
    _EXAMPLES / "example7" / "payload7",
    _EXAMPLES / "example8" / "payload8",
    _EXAMPLES / "example9" / "payload9",
    _EXAMPLES / "example10" / "payload10",
    _EXAMPLES / "URLHierarchy" / "thirdURLPayload",
)
"""Every real Splunk results capture in the repo. payload5 (3.4 MB, 100 rows,
one Message ID retried 100 times) is the large payload this suite is built
around; the rest widen the corpus so cross-PS and multi-target questions have
somewhere real to land.

payload7/8/9 were added 2026-08-07 and are the first real `DocumentInfoRecord`
and standalone `PackITPackagingCockpitMasterData` events in the corpus -- until
then it held exactly one of each, so every dependent-object question this suite
could ask was answered from a single sample. See `splunkExamples/README.md`."""

NEWEST_EVENT_OFFSET = timedelta(minutes=20)
"""Where the corpus's newest event sits relative to suite-run time. The whole
corpus is rigidly shifted so this holds, which makes every time-window scenario
reproducible forever instead of only until the captures age out:

  -15m  (the app's default window) -> finds nothing, every time
  -1h                              -> only the tail of the retry chain
  -24h                             -> effectively the whole corpus
  -7d                              -> the whole corpus

Relative spacing between events is preserved exactly, so the 100-hop retry
chain still spans its real ~8 hours."""

_FIELD_TEXT = "value/text"
_TOKENISH = re.compile(r"^[A-Za-z0-9.]+$")


class CorpusError(Exception):
    """A capture file could not be loaded -- never silently skipped, since a
    missing fixture would quietly shrink every expected result set."""


@dataclass(frozen=True)
class Event:
    """One `<result>` row, kept both as parsed fields (for filtering) and as
    its original XML element (for byte-faithful replay back to the app)."""

    element: ET.Element
    raw: str
    host: str
    source: str
    time: datetime
    origin: str


def _read_capture(path: Path) -> str:
    """Read one capture, tolerating trailing junk after `</results>`.

    `splunkExamples/example2/payload2` has the literal word `example` appended
    after the closing tag -- a note left in the capture file itself, not
    something Splunk ever emits. Truncating at the closing tag is right for a
    fixture loader; the app's own parser correctly rejects the file as
    malformed, and that behaviour is not what this suite is testing.
    """
    text = path.read_text(encoding="utf-8")
    end = text.rfind("</results>")
    if end == -1:
        raise CorpusError(f"{path} has no closing </results> tag")
    return text[: end + len("</results>")]


def _field_text(result_el: ET.Element, key: str) -> str:
    for field_el in result_el.findall("field"):
        if field_el.get("k") != key:
            continue
        if key == "_raw":
            v_el = field_el.find("v")
            return "".join(v_el.itertext()) if v_el is not None else ""
        text_el = field_el.find(_FIELD_TEXT)
        return (text_el.text or "") if text_el is not None else ""
    return ""


def _set_time(result_el: ET.Element, value: str) -> None:
    for field_el in result_el.findall("field"):
        if field_el.get("k") == "_time":
            text_el = field_el.find(_FIELD_TEXT)
            if text_el is not None:
                text_el.text = value


def load_events(*, now: datetime | None = None) -> list[Event]:
    """Load every capture, dedupe, and shift onto the stable relative clock."""
    now = now or datetime.now(timezone.utc)
    loaded: list[tuple[ET.Element, str, str, str, datetime, str]] = []
    seen: set[str] = set()

    for path in PAYLOAD_FILES:
        try:
            root = ET.fromstring(_read_capture(path))
        except ET.ParseError as exc:
            raise CorpusError(f"{path} failed to parse: {exc}") from exc
        for result_el in root.findall("result"):
            raw = _field_text(result_el, "_raw")
            time_text = _field_text(result_el, "_time")
            if not raw or not time_text:
                continue
            identity = f"{time_text}|{raw[:400]}"
            if identity in seen:
                continue
            seen.add(identity)
            loaded.append(
                (
                    result_el,
                    raw,
                    _field_text(result_el, "host"),
                    _field_text(result_el, "source"),
                    datetime.fromisoformat(time_text),
                    path.name,
                )
            )

    if not loaded:
        raise CorpusError("no events loaded from any capture file")

    # Shift each capture *independently*, so every file's own newest event
    # lands at `NEWEST_EVENT_OFFSET` before now.
    #
    # A single global shift anchored on the newest event across all files
    # cannot survive captures taken on different days: adding the 2026-08-07
    # dependent-object captures alongside PS captures from 2026-08-02/03 made
    # the new files the anchor and pushed every PS event four days further
    # into the past, so scenarios searching a window of hours found nothing
    # and 22 of 33 turns failed on data that was present the whole time.
    #
    # Per-file is also what the suite actually needs: the timing that carries
    # meaning is *within* a capture -- the spacing of a retry chain, the order
    # of hops -- and that is preserved exactly. Relative age *between*
    # unrelated captures never encoded anything, it was an accident of when
    # each was taken.
    shift_by_origin = {
        origin: (now - NEWEST_EVENT_OFFSET) - max(item[4] for item in loaded if item[5] == origin)
        for origin in {item[5] for item in loaded}
    }

    events: list[Event] = []
    for element, raw, host, source, original_time, origin in loaded:
        shifted = original_time + shift_by_origin[origin]
        _set_time(element, shifted.isoformat())
        events.append(Event(element=element, raw=raw, host=host, source=source, time=shifted, origin=origin))
    events.sort(key=lambda e: e.time, reverse=True)
    return events


@dataclass(frozen=True)
class ParsedSPL:
    """The parts of a `build_spl` string this emulator acts on."""

    index: str | None
    sourcetype: str | None
    source_suffix: str | None
    host_substring: str | None
    terms: tuple[str, ...]
    head: int


def _tokenize(spl: str) -> list[str]:
    return re.findall(r'"[^"]*"|\S+', spl)


def parse_spl(spl: str) -> ParsedSPL:
    """Parse the fixed template `build_spl` emits. Anything unrecognized is an
    error rather than a silent no-op -- if the app starts emitting SPL this
    emulator doesn't model, the suite must fail loudly instead of quietly
    returning results that don't reflect the real query.
    """
    index = sourcetype = source_suffix = host_substring = None
    terms: list[str] = []
    head = 200
    tokens = _tokenize(spl)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "search":
            pass
        elif token.startswith("index="):
            index = token.split("=", 1)[1]
        elif token.startswith("sourcetype="):
            sourcetype = token.split("=", 1)[1]
        elif token.startswith('source="'):
            source_suffix = token.split("=", 1)[1].strip('"').lstrip("*")
        elif token.startswith('host="'):
            host_substring = token.split("=", 1)[1].strip('"').strip("*")
        elif token == "|":
            if i + 2 < len(tokens) and tokens[i + 1] == "head":
                head = int(tokens[i + 2])
                i += 2
            else:
                raise CorpusError(f"unmodelled SPL pipe command in: {spl!r}")
        elif token.startswith('"') and token.endswith('"'):
            terms.append(token[1:-1])
        else:
            raise CorpusError(f"unmodelled SPL token {token!r} in: {spl!r}")
        i += 1
    return ParsedSPL(
        index=index,
        sourcetype=sourcetype,
        source_suffix=source_suffix,
        host_substring=host_substring,
        terms=tuple(terms),
        head=head,
    )


def _term_matches(term: str, raw: str) -> bool:
    """Approximate Splunk's token-based full-text search, not naive substring.

    The difference is load-bearing here: plant `0110` must NOT match the target
    system `SAPP870110`, which contains it. Real Splunk breaks `_raw` on
    non-alphanumeric characters and matches whole tokens, so a boundary-anchored
    match is much closer to the truth than `in`. Phrases carrying punctuation
    (the `<d:BusinessStatus>ERROR</d:BusinessStatus>` structural clause) fall
    back to substring, which is what a quoted phrase search does anyway.
    """
    if _TOKENISH.match(term):
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", raw, re.IGNORECASE) is not None
    return term.lower() in raw.lower()


def _parse_relative(value: str, now: datetime) -> datetime:
    """Resolve a Splunk relative-time string, or refuse.

    Deliberately raises rather than returning `None` on anything unmodelled
    (`-7d@d`, `-1w`, an absolute timestamp). An earlier version returned `None`,
    which the caller treated as "no bound" — so an unrecognized window silently
    *disabled* time filtering and returned the whole corpus. That is the worst
    possible failure for a suite whose expectations are built on which records a
    window contains: it would have manufactured passes.
    """
    value = (value or "").strip()
    if value in ("", "now"):
        return now
    match = re.match(r"^-(\d+)(m|h|d)$", value)
    if not match:
        raise CorpusError(
            f"unmodelled time expression {value!r} -- the emulator only implements the "
            "-<N>(m|h|d) shape that `domain._validate_time_range` can produce"
        )
    amount, unit = int(match.group(1)), match.group(2)
    return now - timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: amount})


def search(events: list[Event], spl: str, earliest: str, latest: str, *, now: datetime | None = None) -> list[Event]:
    """Apply the parsed SPL plus the job's time window to the frozen corpus."""
    now = now or datetime.now(timezone.utc)
    parsed = parse_spl(spl)
    start = _parse_relative(earliest, now)
    end = _parse_relative(latest, now)

    matched: list[Event] = []
    for event in events:
        if event.time < start or event.time > end:
            continue
        if parsed.source_suffix and not event.source.endswith(parsed.source_suffix):
            continue
        if parsed.host_substring and parsed.host_substring.lower() not in event.host.lower():
            continue
        if not all(_term_matches(term, event.raw) for term in parsed.terms):
            continue
        matched.append(event)
    return matched[: parsed.head]


_META = """    <meta>
        <fieldOrder>
            <field>_bkt</field><field>_cd</field><field>_indextime</field>
            <field>_raw</field><field>_serial</field><field>_si</field>
            <field>_sourcetype</field><field>_time</field><field>host</field>
            <field>index</field><field>linecount</field><field>source</field>
            <field>sourcetype</field><field>splunk_server</field>
        </fieldOrder>
    </meta>
"""


def to_results_xml(events: list[Event]) -> str:
    """Re-serialize matched events into the exact `output_mode=xml` envelope
    the app's own parser consumes -- original `<result>` elements verbatim, so
    `<sg>` highlight tags and `xml:space="preserve"` survive the round trip.
    """
    body = "".join(ET.tostring(event.element, encoding="unicode") for event in events)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<results preview="0">\n{_META}{body}</results>'
