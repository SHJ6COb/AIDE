"""Live survey: what do real `DocumentInfoRecord` and
`PackITPackagingCockpitMasterData` events actually look like, over 30 days?

The frozen corpus holds 266 `PackITPackagingSpecification` events across 8
distinct topic strings -- but exactly **one** DIR event and **one** Cockpit
event. Every claim this project makes about those two Message Types rests on a
single sample each, which has already produced real errors (see the Document
Info Record topic file's correction history).

Read-only, not part of the pytest suite -- same convention as the other
`scripts/live_*.py` investigations.

Two phases, because they answer different questions:

* **Phase A** computes distinct values *Splunk-side* across the whole window.
  This is the point of the script. `build_spl` appends a hard `| head 200`, so
  pulling raw events and counting them here would measure the cap, not the
  data: 200 events can all fall inside one busy hour, and "only 1 distinct
  topic string" would be an artefact of the query. `stats ... by topic` is
  computed over every matching event, so its counts are true.

* **Phase B** then pulls one full raw event per distinct topic string, to read
  the `OBJECTKEY` structure and body shape that Phase A's aggregate discards.

`TOPICSTRING` lives inside the JSON payload and has no Splunk field extraction
(confirmed live -- a `PS_ID` field=value filter returns zero against values
bare-text search finds), so Phase A must `rex` it out of `_raw`. If that regex
is wrong the result is *one* topic string per Message Type, which looks exactly
like a real finding -- hence `--check`, which fails loudly on that case rather
than letting it be reported as data.

Usage:
    python scripts/live_survey_dependent_objects.py [--days 30] [--dump DIR]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.core.config import AgentConfig
from app.tools import splunk_client, splunk_xml_parser

MESSAGE_TYPES = ("DocumentInfoRecord", "PackITPackagingCockpitMasterData")

_TOPIC_IN_RAW = re.compile(r'"TOPICSTRING"\s*:\s*"([^"]+)"')


def _stats_spl(index: str, sourcetype: str, message_type: str) -> str:
    """Distinct TOPICSTRING with counts and first/last seen, over the whole
    window. Deliberately no `| head` -- that is the entire reason this script
    bypasses `build_spl`.
    """
    return (
        f"search index={index} sourcetype={sourcetype} source=\"*{message_type}\" "
        '| rex field=_raw max_match=0 "\\"TOPICSTRING\\"\\s*:\\s*\\"(?<topics>[^\\"]+)\\"" '
        "| eval topic_header=mvindex(topics, 0), topic=mvindex(topics, -1) "
        "| stats count as events, min(_time) as first_seen, max(_time) as last_seen, "
        "dc(host) as hosts by topic_header, topic "
        "| sort -events"
    )


def _sample_spl(index: str, sourcetype: str, message_type: str, topic: str) -> str:
    """One page of raw events for a single topic string.

    `topic` comes from Phase A's own results -- Splunk's own output, not user
    input -- but it is still quoted as a bare full-text term and checked for
    the characters that would break out of the quoting.
    """
    if any(ch in topic for ch in ('"', "|", "`", "\\")):
        raise ValueError(f"refusing to interpolate topic string containing quoting characters: {topic!r}")
    return f'search index={index} sourcetype={sourcetype} source="*{message_type}" "{topic}" | head 5'


def _payload_of(raw: str) -> dict | None:
    """The JSON payload of a hop, at whichever stage it was captured.

    A consumed hop is Atom/OData with the JSON inside `<d:Payload>`; a
    pre-consumption hop is the plain JSON itself. DIR differs from the other
    two again in having no `SINGLEMESSAGES` wrapper once consumed, so this
    returns the raw dict and lets callers cope rather than assuming a shape.
    """
    match = re.search(r"<d:Payload>(.*?)</d:Payload>", raw, re.S)
    text = html.unescape(match.group(1)) if match else raw
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _headers_of(payload: dict) -> list[dict]:
    if "SINGLEMESSAGES" in payload:
        return [m.get("SINGLEMESSAGEHEADER") or {} for m in payload["SINGLEMESSAGES"]]
    if "SINGLEMESSAGEHEADER" in payload:
        return [payload["SINGLEMESSAGEHEADER"]]
    return []


def _bodies_of(payload: dict) -> list[dict]:
    """The master node's own fields, so "populated vs empty" is per *structure*.

    Descends one level past the envelope in each shape, or the answer is
    useless: for a consumed DIR the envelope has a single key
    (`DocumentMessageRoot`), and reporting "populated: DocumentMessageRoot"
    says nothing about which link arrays are filled -- which is the entire
    question for an `L01` document.
    """
    bodies = []
    if "SINGLEMESSAGES" in payload:
        for message in payload["SINGLEMESSAGES"]:
            body = message.get("SINGLEMESSAGEBODY") or {}
            # A PS body wraps everything under DETERMINATION; Cockpit's
            # structures sit at the top level already.
            bodies.append(body.get("DETERMINATION") or body)
        return bodies
    # A consumed DIR carries its master node beside the header, not beneath a
    # SINGLEMESSAGEBODY -- see the Document Info Record topic file.
    envelope = {k: v for k, v in payload.items() if k != "SINGLEMESSAGEHEADER"}
    root = envelope.get("DocumentMessageRoot")
    return [root if isinstance(root, dict) else envelope]


def _is_populated(value: object) -> bool:
    if isinstance(value, list):
        return any(_is_populated(v) for v in value)
    if isinstance(value, dict):
        return any(_is_populated(v) for v in value.values())
    if value is None:
        return False
    return str(value).strip().strip("0") != ""


def _field(result, name: str, default: str = "?") -> str:
    """`RawResult.get` has no default and can return a list for multivalued
    fields -- flatten both cases so formatting never blows up mid-survey."""
    value = result.get(name)
    if value is None:
        return default
    return value if isinstance(value, str) else ", ".join(value)


def phase_a(config: AgentConfig, message_type: str, days: int) -> list:
    spl = _stats_spl(config.splunk_index, config.splunk_sourcetype, message_type)
    print(f"\n{'=' * 78}\n{message_type}  --  distinct TOPICSTRING over last {days}d\n{'=' * 78}")
    print(f"SPL: {spl}\n")
    try:
        pages = splunk_client.search_spl(config, spl, f"-{days}d", "now", max_pages=5)
    except Exception as exc:
        print(f"  SEARCH FAILED: {type(exc).__name__}: {exc}")
        return []

    rows = [r for page in pages for r in splunk_xml_parser.parse_results(page)]
    if not rows:
        print("  no rows -- either no events in the window, or the rex matched nothing")
        return []

    # TOPICSTRING appears at two levels and they are not the same string.
    # `SINGLEMESSAGEHEADER.TOPICSTRING` is coarse (Message Type + Source
    # System); `SINGLEMESSAGES[n].TOPICSTRING`, its sibling, carries the
    # business context. Taking the first match makes a DIR look as though it
    # has 3 distinct topics when the specific level has far more -- reporting
    # both levels is what stops that going unnoticed.
    for row in rows:
        print(f"  {_field(row, 'events'):>7}  hosts={_field(row, 'hosts'):>3}  {_field(row, 'topic')}")
        header_topic = _field(row, "topic_header", "")
        if header_topic and header_topic != _field(row, "topic"):
            print(f"  {'':>7}  header-level: {header_topic}")
    return rows


def phase_b(config: AgentConfig, message_type: str, topics: list[str], days: int, dump: Path | None) -> None:
    print(f"\n{'-' * 78}\n{message_type}  --  OBJECTKEY + body shape per topic\n{'-' * 78}")
    for topic in topics:
        spl = _sample_spl(config.splunk_index, config.splunk_sourcetype, message_type, topic)
        try:
            pages = splunk_client.search_spl(config, spl, f"-{days}d", "now", max_pages=1)
        except Exception as exc:
            print(f"\n  {topic}\n    SAMPLE FAILED: {type(exc).__name__}: {exc}")
            continue

        results = [r for page in pages for r in splunk_xml_parser.parse_results(page)]
        print(f"\n  {topic}   ({len(results)} sampled)")
        if dump and pages:
            target = dump / f"{message_type}_{re.sub(r'[^A-Za-z0-9]+', '_', topic)}.xml"
            target.write_text(pages[0], encoding="utf-8")
            print(f"    saved raw: {target}")

        key_shapes: Counter[tuple[str, ...]] = Counter()
        for result in results:
            payload = _payload_of(result.raw())
            if not payload:
                print(f"    host={_field(result, 'host')!r}  (payload not JSON at this stage)")
                continue
            for header, body in zip(_headers_of(payload), _bodies_of(payload)):
                key = header.get("OBJECTKEY")
                if isinstance(key, dict):
                    key_shapes[tuple(key)] += 1
                    print(f"    host={_field(result, 'host')}")
                    print(f"    OBJECTKEY: {json.dumps(key)}")
                populated = [k for k, v in body.items() if _is_populated(v)]
                empty = [k for k, v in body.items() if not _is_populated(v)]
                if populated or empty:
                    print(f"    body populated: {populated}")
                    print(f"    body empty    : {empty}")
                break  # one hop is enough to read the shape

        if len(key_shapes) > 1:
            print(f"    !! {len(key_shapes)} different OBJECTKEY field sets under one topic string")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dump", type=Path, default=None, help="directory to save raw results XML into")
    parser.add_argument("--check", action="store_true", help="exit non-zero if a Message Type yields <2 distinct topics")
    args = parser.parse_args()

    if args.dump:
        args.dump.mkdir(parents=True, exist_ok=True)

    config = AgentConfig.from_env()
    suspicious = []
    for message_type in MESSAGE_TYPES:
        rows = phase_a(config, message_type, args.days)
        topics = [t for r in rows if isinstance(t := r.get("topic"), str) and t]
        if len(topics) < 2:
            suspicious.append(message_type)
        phase_b(config, message_type, topics[:20], args.days, args.dump)

    if suspicious:
        print(
            f"\n!! {', '.join(suspicious)} yielded fewer than 2 distinct topic strings.\n"
            "   Treat this as a broken `rex`, not a finding about the data, until the\n"
            "   sampled raw events above are confirmed to genuinely share one topic."
        )
        if args.check:
            sys.exit(1)


if __name__ == "__main__":
    main()
