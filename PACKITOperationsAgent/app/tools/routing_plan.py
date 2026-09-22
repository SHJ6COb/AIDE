"""Additional Routing plan client -- a separate API/data source from Splunk,
confirmed live against the real Bosch gateway. See
docs/components/routing-plan/TECHNICAL_SPEC.md for the full empirical
grounding behind every rule here; this implements that spec's runtime
filter-building rules for the first time (previously recorded there only as
confirmed domain grounding for a "likely future capability").
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.core.config import AgentConfig

_MESSAGE_TYPE = "PackITPackagingSpecification"
"""The only Message Type confirmed queried against this API so far -- see
TECHNICAL_SPEC.md's "Confidence status" section."""

_NOT_REGISTERED_SENTINEL = "AR AGREEMENT NOT REGISTERED"
"""Confirmed real: an unregistered/unknown SOURCESYSTEMID returns HTTP 200
with this literal plain-text (non-JSON) body, not an empty JSON array or an
error status -- must be checked before attempting to parse as JSON."""


class RoutingPlanError(Exception):
    """The routing-plan API call itself failed (network error, non-2xx
    status, or a response that's neither the confirmed sentinel nor valid
    JSON) -- distinct from "queried successfully, found no routes"."""


@dataclass(frozen=True)
class RoutingPlanResult:
    """Which Target System(s) a Plant + Determination Type is configured to
    route to, per the Additional Routing plan. Confirmed real that this
    plan is keyed generically this way, never by individual PS (see
    CONTEXT.md's Additional Routing entry) -- there is deliberately no
    ps_id parameter on the query function this wraps."""

    plant: str
    determination_type: str
    target_systems: tuple[str, ...]


def _build_request_filter(*, plant: str, determination_type: str) -> dict:
    """Confirmed live critical asymmetry: inside `OBJECTKEY`, `"*"` is a
    literal exact-match string, not a wildcard -- so to leave a sub-field
    unscoped you must omit the key entirely, never pass `"*"` for it. Only
    `WERKS`/`DETTYPE` are set here since only those are needed to answer
    "what target(s) does this Plant + Determination Type route to" --
    confirmed live that combining just these two returns exactly the same
    entries as the full unscoped dump filtered client-side.
    """
    return {
        "SINGLEMESSAGEHEADER": {
            # Top-level "*" IS a true wildcard here (unlike inside
            # OBJECTKEY) -- confirmed real. This field means "any
            # Target/Subscriber system" despite its name; the real
            # originating Source System lives in OBJECTKEY.SYSTEMID
            # instead, not queried here since we don't filter on it.
            "SOURCESYSTEMID": "*",
            "MESSAGETYPE": _MESSAGE_TYPE,
            # Mandatory field -- confirmed real that omitting it entirely
            # causes an HTTP 400, even though it's never populated with a
            # real non-"*" value in any of the 554 real entries seen.
            "LOGICALCONNECTION": "*",
            "OBJECTKEY": {"WERKS": plant, "DETTYPE": determination_type},
        }
    }


def _parse_target_systems(response_text: str) -> tuple[str, ...]:
    """Pure parsing of the API's raw response text -- separated from the
    network call so it's directly unit-testable, matching this codebase's
    pattern elsewhere (e.g. `splunk_client.build_spl`) of unit-testing the
    pure logic and live-verifying the actual I/O via scripts, not mocks.
    """
    text = response_text.strip()
    if text == _NOT_REGISTERED_SENTINEL:
        # Confirmed real: means no Additional Routing agreement exists at
        # all for the queried scope -- a real, informative answer (there
        # is no configured destination), not a lookup failure.
        return ()

    try:
        entries = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RoutingPlanError(f"unexpected non-JSON Additional Routing response: {text[:300]!r}") from exc

    target_systems: list[str] = []
    for entry in entries:
        header = entry.get("SINGLEMESSAGEHEADER", {})
        for target in header.get("TARGETSYSTEMS") or []:
            system_id = target.get("SYSTEMID")
            if system_id:
                target_systems.append(system_id)
    return tuple(sorted(set(target_systems)))


def query_target_systems(config: AgentConfig, *, plant: str, determination_type: str) -> RoutingPlanResult:
    """Ask the Additional Routing plan which Target System(s) a Plant +
    Determination Type combination is configured to route to.

    Deliberately takes Plant/Determination Type, not a PS ID or Message ID
    -- confirmed live that every real entry stores PS_ID/AENNR/SEQNO/MATNR/
    SUPPLIER as the literal string `"*"`, so filtering by any of those
    returns zero regardless of whether the PS is real (see
    TECHNICAL_SPEC.md). Callers must resolve a specific PS's own Plant/
    Determination Type from its Transfer/Splunk data first.
    """
    request_filter = _build_request_filter(plant=plant, determination_type=determination_type)
    try:
        response = httpx.get(
            config.additional_routing_url,
            headers={
                # Confirmed real header name casing -- "KeyId", not "KeyID"
                # (Splunk's header), despite the similar mechanism. Held in
                # config rather than inline precisely because that one-letter
                # difference is invisible at a glance and breaks silently.
                config.additional_routing_auth_header: config.additional_routing_api_token,
                "Request-Filter": json.dumps(request_filter),
            },
            verify=config.splunk_verify_ssl,
            trust_env=True,
            timeout=config.splunk_search_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RoutingPlanError(f"Additional Routing API call failed: {exc}") from exc

    target_systems = _parse_target_systems(response.text)
    return RoutingPlanResult(plant=plant, determination_type=determination_type, target_systems=target_systems)
