"""The frozen Additional Routing plan.

Provenance, stated plainly: unlike the Splunk corpus, this is **not** a live
capture. The repo contains no saved routing-plan response body -- only a
screenshot of the Postman call. It is reconstructed from
`docs/components/routing-plan/TECHNICAL_SPEC.md`, which records the real
554-entry plan's confirmed structure and several exact, named facts from live
calls. Everything below either restates one of those confirmed facts or is a
Plant/Determination Type combination that the frozen Splunk corpus itself
proves must exist (a transfer observably reached that target from that plant).

That is enough for regression testing, whose question is "given a known backend
response, does the product report it faithfully?" -- but it is not evidence
about what the live plan contains today. Re-derive from a real capture before
using any number here as a claim about production.
"""

from __future__ import annotations

import json

MESSAGE_TYPE = "PackITPackagingSpecification"
NOT_REGISTERED_SENTINEL = "AR AGREEMENT NOT REGISTERED"

ROUTES: dict[tuple[str, str], tuple[str, ...]] = {
    # --- Grounded in the frozen Splunk corpus: a real transfer from this
    # plant/determination type was observed arriving at this target. ---
    ("0110", "SHIP"): ("SAPP870110",),      # PS 00000000040001253724, payload5
    ("0500", "SHIP"): ("SAPP990110",),      # PS 00000000040001399187, payload4
    ("0780", "SHIP"): ("SAPP720110", "SAPPOE0110"),  # PS ...434427 fanned out to both
    ("929P", "SHIP"): ("SAPPOE0110",),      # PS 00000000040001497551, payload6
    ("1810", "SHIP"): ("SAPPOE0110",),      # PS 00000000040000681411, payload2
    ("8160", "RCPT"): ("SAPP810110",),      # PS 00000000040001399043, payload3
    # --- Restated from TECHNICAL_SPEC.md's confirmed-live findings. ---
    ("8150", "SHIP"): ("SAPP450110", "SAPP1M0110"),  # confirmed intentional dual delivery
    ("9050", "SHIP"): ("SAPP450110", "SAPP1M0110"),  # confirmed intentional dual delivery
    ("3000", "SHIP"): ("SAPP1M0110", "SAPP790110"),  # confirmed intentional dual delivery
    ("0110", "STOC"): ("SAPP1M0110",),      # SAPP1M0110 concentrates STOC/PALE/DOLL
    ("0110", "RCPT"): ("SAPP870110",),      # regular targets handle SHIP/RCPT/ZFER/KIT uniformly per plant
    ("0500", "RCPT"): ("SAPP990110",),
}

UNREGISTERED_PLANTS = frozenset({"0001"})
"""Plants that return the confirmed plain-text `AR AGREEMENT NOT REGISTERED`
sentinel rather than a JSON array -- the real API's response for a scope with
no routing agreement at all."""


def _entry(plant: str, determination_type: str, target: str) -> dict:
    """One routing-plan entry in the confirmed real shape.

    Note `SOURCESYSTEMID` == the *target* system, not the originating one --
    the field-naming gotcha recorded in TECHNICAL_SPEC.md. The real originating
    system (`SAPPD70110`/PD7) lives in `OBJECTKEY.SYSTEMID`. Every key that the
    live plan stores as the literal string `"*"` on all 554 entries is `"*"`
    here too.
    """
    return {
        "SINGLEMESSAGEHEADER": {
            "SOURCESYSTEMID": target,
            "MESSAGETYPE": MESSAGE_TYPE,
            "LOGICALCONNECTION": "*",
            "OBJECTKEY": {
                "SYSTEMID": "SAPPD70110",
                "WERKS": plant,
                "DETTYPE": determination_type,
                "PS_ID": "*",
                "AENNR": "*",
                "SEQNO": "*",
                "ZACTCOUNTER": "*",
                "MATNR": "*",
                "SUPPLIER": "*",
                "ABRVW": "*",
            },
            "TOPICSTRING": f"PD7/{MESSAGE_TYPE}/{plant}/{determination_type}/V1/*/*/*/*/No",
            # Confirmed: exactly one target per entry across all 554 real
            # entries -- fan-out is multiple entries, never a multi-value list.
            "TARGETSYSTEMS": [{"SYSTEMID": target}],
        }
    }


def respond(request_filter_header: str) -> tuple[int, str]:
    """Emulate the real endpoint's response to a `Request-Filter` header.

    Reproduces the four confirmed behaviours that a client can get wrong:
    the mandatory `LOGICALCONNECTION` (HTTP 400 when absent), the non-JSON
    `AR AGREEMENT NOT REGISTERED` sentinel, case-sensitive exact matching, and
    the `OBJECTKEY`-level `"*"` being a literal rather than a wildcard.
    """
    try:
        parsed = json.loads(request_filter_header)
    except (json.JSONDecodeError, TypeError):
        return 400, json.dumps({"errorClass": "java.lang.IllegalArgumentException", "errorMessage": "Request-Filter is not valid JSON"})

    header = parsed.get("SINGLEMESSAGEHEADER", {})
    if not header.get("LOGICALCONNECTION"):
        return 400, json.dumps(
            {
                "errorClass": "java.lang.IllegalArgumentException",
                "errorMessage": f"LOGICALCONNECTION is missing or empty for MESSAGETYPE: {header.get('MESSAGETYPE')}",
            }
        )

    objectkey = header.get("OBJECTKEY") or {}
    plant = objectkey.get("WERKS")
    determination_type = objectkey.get("DETTYPE")

    if plant in UNREGISTERED_PLANTS:
        return 200, NOT_REGISTERED_SENTINEL

    entries = [
        _entry(key_plant, key_det, target)
        for (key_plant, key_det), targets in sorted(ROUTES.items())
        for target in targets
        # Exact, case-sensitive match; an omitted key means unscoped. A literal
        # "*" passed for an OBJECTKEY sub-field matches only entries whose own
        # stored value is literally "*", which none of these have -- the
        # confirmed asymmetry.
        if (plant is None or key_plant == plant) and (determination_type is None or key_det == determination_type)
    ]
    return 200, json.dumps(entries)


def expected_targets(plant: str, determination_type: str) -> tuple[str, ...]:
    """What `routing_plan.query_target_systems` must return for this scope --
    the expectation side of the suite reads this, so fixture and expectation
    can never drift apart."""
    if plant in UNREGISTERED_PLANTS:
        return ()
    return tuple(sorted(ROUTES.get((plant, determination_type), ())))
