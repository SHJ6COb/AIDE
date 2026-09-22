"""Splunk search: SPL construction + the confirmed 4-call async REST flow.

See docs/components/splunk-client/TECHNICAL_SPEC.md for the empirical
grounding behind every rule here -- this is not oneshot search, and several
details (the `source=` field-filter wildcard, the result-count gateway
block, the `KeyID` auth header) were only discovered by testing against the
real Bosch gateway, not from documentation.
"""

from __future__ import annotations

import re
import time

import httpx

from app.core.config import AgentConfig
from app.core.domain import SearchParams

RESULT_PAGE_SIZE = 200
"""Confirmed safe per-call ceiling -- the gateway hard-blocks (`MessageBlocked`
SOAP fault) `count=0` or large `count` values on a broad search. Fetching
more requires paginating via `offset`, never a bigger single page."""

_RESULT_TAG_RE = re.compile(r"<result[ >]")
_TIER2_ALLOWED_RE = re.compile(r"^[A-Za-z0-9 ._-]+$")
_TIER2_MAX_LENGTH = 200
_UNSAFE_CHARS = ('"', "|", "`")


class InvalidSearchTerm(ValueError):
    """A value meant for interpolation into the SPL string failed the
    injection guardrail -- rejected outright, never escaped."""


class SplunkSearchError(Exception):
    """The search job itself failed server-side (Splunk `isFailed`)."""


class SplunkGatewayBlocked(Exception):
    """The Bosch API gateway hard-rejected the request (`MessageBlocked`
    SOAP fault) -- confirmed real on `count=0`/large-`count` results
    requests against a broad search. Never retry with a bigger page; the
    fix is a smaller `count` and more `offset`-paginated calls."""


class SplunkPollTimeout(Exception):
    """The search job never reached `DONE` within the configured timeout."""


def _quote(value: str, *, tier2: bool = False) -> str:
    """Wrap an interpolated value in double quotes, after checking it can't
    break out of that quoting or inject an SPL pipe/command.

    Tier 1 values are expected to already be enum/pattern-validated
    upstream (see docs/agents/packspec-status/TECHNICAL_SPEC.md) -- this is
    defense-in-depth, not the primary guardrail, for them. Tier 2 free-text
    terms get the full allowlist + length cap, since they're the actual
    LLM/user-derived overflow this guardrail exists for.
    """
    if any(ch in value for ch in _UNSAFE_CHARS):
        raise InvalidSearchTerm(f"value contains a disallowed character: {value!r}")
    if tier2:
        if len(value) > _TIER2_MAX_LENGTH:
            raise InvalidSearchTerm(f"term exceeds {_TIER2_MAX_LENGTH} chars: {value!r}")
        if not _TIER2_ALLOWED_RE.match(value):
            raise InvalidSearchTerm(f"term contains a disallowed character: {value!r}")
    return f'"{value}"'


def build_spl(params: SearchParams, index: str, sourcetype: str, *, result_cap: int = RESULT_PAGE_SIZE) -> str:
    """Pure function: `SearchParams` -> the SPL string to send as the
    `search` form field. No network access, fully unit-testable.

    Structure is a fixed template the code controls -- only validated
    *values* are plugged into it, never LLM/user-derived text for the
    structure itself (see the SPL construction guardrails in
    components/splunk-client/TECHNICAL_SPEC.md).
    """
    # index/sourcetype come from AgentConfig (developer-controlled, not
    # LLM/user-derived), so they're interpolated bare -- matching the
    # confirmed real pattern `search index=pdbb sourcetype=Native ...`.
    clauses = [f"search index={index}", f"sourcetype={sourcetype}"]

    if params.message_type is not None:
        # Leading wildcard is mandatory, not stylistic -- confirmed live
        # that a real minority of events carry a `Native/`-prefixed
        # `source` (e.g. `Native/PackITPackagingSpecification`) rather than
        # the bare Message Type string. An exact match silently undercounts
        # by missing every one of those. See TECHNICAL_SPEC.md.
        clauses.append(f'source="*{params.message_type.value}"')

    # No field extraction exists for anything living inside the JSON
    # payload (confirmed live: a PS_ID field=value filter returns zero
    # against values bare-text search confirms are present) -- every one
    # of these remains a bare, quoted full-text term against `_raw`.
    for value in (
        params.ps_id,
        params.plant,
        params.supplier,
        params.customer_index,
        params.matnr,
        params.document_number,
    ):
        if value is not None:
            clauses.append(_quote(value))

    if params.target_system is not None:
        # Structural `host` filter, NOT a bare full-text term -- confirmed
        # live necessary (2026-08-05): a bare-text search for a known-real
        # POE (`SAPPOE0110`) PS's target system returned zero hits despite
        # all 8 of that PS's real hops having `SAPPOE0110` in their `host`
        # field, because unlike SAPP1M0110/SAPP990110/etc. (whose target
        # system id also happens to repeat inside the payload body's
        # per-hop TOPICSTRING copy), POE's target system id lives only in
        # `host`, never inside `_raw`'s JSON payload text. The bare-text
        # approach also false-matched unrelated `MaterialBOM/TRS` events
        # that happened to mention the string elsewhere. `host` is a real,
        # separately indexed Splunk field (confirmed from raw XML
        # captures) -- every real Host shape (see CONTEXT.md's Host entry)
        # carries the target system id as a literal substring, so a
        # both-sides-wildcarded structural filter (matching the same
        # leading-wildcard pattern already proven for `source` above)
        # catches all of them. Tier 1-validated upstream
        # (`_TARGET_SYSTEM_RE`), so safe to interpolate directly.
        clauses.append(f'host="*{params.target_system}*"')

    if params.determination_type is not None:
        clauses.append(_quote(params.determination_type.value))
    if params.usage is not None:
        clauses.append(_quote(params.usage))
    if params.sales_channel is not None:
        clauses.append(_quote(params.sales_channel))

    if params.status is not None:
        # Confirmed live: a bare-word search (e.g. "SUCCESS") is unreliable
        # -- 196/200 real matches in one live sample were pre-consumption
        # hops with no actual status at all (the word appears incidentally
        # elsewhere in the payload). The exact Atom/OData structural tag is
        # precise (0/200 false positives, both ERROR and SUCCESS, live-
        # verified) -- see docs/components/splunk-client/TECHNICAL_SPEC.md.
        # Code-controlled clause, not user/LLM-derived text, so it bypasses
        # Tier 2's character allowlist (which would otherwise reject `<`/`>`).
        clauses.append(f'"<d:BusinessStatus>{params.status.value}</d:BusinessStatus>"')

    for term in params.additional_terms:
        clauses.append(_quote(term, tier2=True))

    clauses.append(f"| head {result_cap}")
    return " ".join(clauses)


def _extract(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _auth_headers(config: AgentConfig) -> dict[str, str]:
    """The gateway's auth is a single bare header carrying the token -- not
    Bearer, not Basic (confirmed live, see TECHNICAL_SPEC.md). The header
    name is config-driven because it differs from the Additional Routing
    API's by casing alone (`KeyID` vs `KeyId`), a distinction easy to break
    silently; keeping it in one place means all four calls below can't drift
    apart from each other."""
    return {config.splunk_auth_header: config.splunk_api_token}


def _start_job(client: httpx.Client, config: AgentConfig, spl: str, earliest: str, latest: str) -> str:
    response = client.post(
        f"{config.splunk_base_url}/services/search/jobs",
        headers=_auth_headers(config),
        data={"earliest_time": earliest, "latest_time": latest, "search": spl, "output_mode": "xml"},
    )
    response.raise_for_status()
    sid = _extract(r"<sid>([^<]+)</sid>", response.text)
    if sid is None:
        raise SplunkSearchError(f"job creation response had no <sid>: {response.text[:500]!r}")
    return sid


def _poll_until_done(client: httpx.Client, config: AgentConfig, sid: str) -> None:
    deadline = time.monotonic() + config.splunk_search_timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(
            f"{config.splunk_base_url}/services/search/jobs/{sid}",
            headers=_auth_headers(config),
            params={"output_mode": "xml"},
        )
        response.raise_for_status()
        text = response.text
        if 'name="isFailed">1' in text:
            raise SplunkSearchError(f"search job {sid} failed: {text[:1000]!r}")
        if 'name="dispatchState">DONE' in text:
            return
        time.sleep(1.5)
    raise SplunkPollTimeout(f"job {sid} did not reach DONE within {config.splunk_search_timeout_seconds}s")


def _fetch_results_page(client: httpx.Client, config: AgentConfig, sid: str, offset: int, count: int) -> str:
    response = client.get(
        f"{config.splunk_base_url}/services/search/v2/jobs/{sid}/results",
        headers=_auth_headers(config),
        params={"output_mode": "xml", "count": count, "offset": offset},
    )
    response.raise_for_status()
    if "MessageBlocked" in response.text:
        raise SplunkGatewayBlocked(
            f"gateway blocked results fetch (sid={sid}, offset={offset}, count={count}) -- "
            "confirmed real on count=0 or large count against a broad search, see TECHNICAL_SPEC.md"
        )
    return response.text


def _delete_job(client: httpx.Client, config: AgentConfig, sid: str) -> None:
    client.delete(
        f"{config.splunk_base_url}/services/search/jobs/{sid}",
        headers=_auth_headers(config),
        params={"output_mode": "xml"},
    )


def search_spl(
    config: AgentConfig,
    spl: str,
    earliest: str,
    latest: str,
    *,
    max_pages: int = 1,
) -> list[str]:
    """Run the confirmed 4-call async flow for an **already-built** SPL string.

    **`spl` must be developer-authored, never LLM- or user-derived.** The
    guardrails in `docs/components/splunk-client/TECHNICAL_SPEC.md` work by
    keeping SPL *structure* under code control and admitting only validated
    *values* -- `build_spl` is what enforces that, and `search()` below is the
    only path reachable from a question. This function sits beneath both and
    does no validation of its own, so calling it with anything derived from a
    question would step straight around the guardrail.

    It exists for offline investigation scripts (`scripts/live_*.py`) that need
    SPL `build_spl`'s fixed template cannot express -- specifically Splunk-side
    aggregation (`stats`, `dedup`, `rex`). That matters because `build_spl`
    appends a hard `| head 200`: fine for answering about one PS, useless for
    "how many distinct topic strings exist across 30 days", where the cap would
    silently turn a property of the *query* into an apparent property of the
    *data*.
    """
    pages: list[str] = []
    with httpx.Client(verify=config.splunk_verify_ssl, trust_env=True, timeout=config.splunk_search_timeout_seconds) as client:
        sid = _start_job(client, config, spl, earliest, latest)
        try:
            _poll_until_done(client, config, sid)
            for page_index in range(max_pages):
                page_text = _fetch_results_page(client, config, sid, offset=page_index * RESULT_PAGE_SIZE, count=RESULT_PAGE_SIZE)
                pages.append(page_text)
                # Real `<result>` tags carry an `offset` attribute (e.g.
                # `<result offset='0'>`), confirmed from live captures --
                # a bare `.count("<result>")` substring check never matches.
                if len(_RESULT_TAG_RE.findall(page_text)) < RESULT_PAGE_SIZE:
                    break
        finally:
            _delete_job(client, config, sid)
    return pages


def search(config: AgentConfig, params: SearchParams, *, max_pages: int = 1) -> list[str]:
    """Run the confirmed 4-call async flow, returning each page's raw
    `output_mode=xml` results text (feed each into
    `splunk_xml_parser.parse_results`).

    Always fetches in `RESULT_PAGE_SIZE`-row increments -- never a bigger
    single page, per the confirmed gateway block. Stops early if a page
    comes back short (fewer than `RESULT_PAGE_SIZE` rows means no more
    results exist). `max_pages` defaults to 1 (200 results); the pipeline
    only needs to ask for more when 200 genuinely isn't enough.

    **This is the only search path reachable from a user's question**, and
    `build_spl` is what keeps it safe -- see `search_spl`'s docstring.
    """
    return search_spl(
        config,
        build_spl(params, config.splunk_index, config.splunk_sourcetype),
        params.time_range.earliest,
        params.time_range.latest,
        max_pages=max_pages,
    )
