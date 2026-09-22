import json

import pytest

from app.tools.routing_plan import (
    RoutingPlanError,
    _build_request_filter,
    _parse_target_systems,
)


def test_build_request_filter_omits_objectkey_wildcards_never_passes_star_inside():
    """Confirmed live critical asymmetry: "*" inside OBJECTKEY is a literal
    exact-match string, not a wildcard -- WERKS/DETTYPE must be the real
    values, never "*", and there must be no other OBJECTKEY sub-field set
    to "*" either."""
    request_filter = _build_request_filter(plant="8150", determination_type="SHIP")
    header = request_filter["SINGLEMESSAGEHEADER"]
    assert header["OBJECTKEY"] == {"WERKS": "8150", "DETTYPE": "SHIP"}


def test_build_request_filter_top_level_wildcards_and_mandatory_logical_connection():
    """SOURCESYSTEMID="*" at the top level IS a true wildcard (unlike inside
    OBJECTKEY) -- confirmed live. LOGICALCONNECTION is mandatory -- omitting
    it causes a real HTTP 400, so it must always be present, even as "*"."""
    request_filter = _build_request_filter(plant="0780", determination_type="RCPT")
    header = request_filter["SINGLEMESSAGEHEADER"]
    assert header["SOURCESYSTEMID"] == "*"
    assert header["LOGICALCONNECTION"] == "*"
    assert header["MESSAGETYPE"] == "PackITPackagingSpecification"


def test_parse_target_systems_extracts_from_real_response_shape():
    response = json.dumps(
        [
            {
                "SINGLEMESSAGEHEADER": {
                    "SOURCESYSTEMID": "SAPP1M0110",
                    "TARGETSYSTEMS": [{"SYSTEMID": "SAPP1M0110"}],
                }
            },
            {
                "SINGLEMESSAGEHEADER": {
                    "SOURCESYSTEMID": "SAPP450110",
                    "TARGETSYSTEMS": [{"SYSTEMID": "SAPP450110"}],
                }
            },
        ]
    )
    result = _parse_target_systems(response)
    assert result == ("SAPP1M0110", "SAPP450110")


def test_parse_target_systems_deduplicates_and_sorts():
    response = json.dumps(
        [
            {"SINGLEMESSAGEHEADER": {"TARGETSYSTEMS": [{"SYSTEMID": "SAPP990110"}]}},
            {"SINGLEMESSAGEHEADER": {"TARGETSYSTEMS": [{"SYSTEMID": "SAPP450110"}]}},
            {"SINGLEMESSAGEHEADER": {"TARGETSYSTEMS": [{"SYSTEMID": "SAPP990110"}]}},
        ]
    )
    assert _parse_target_systems(response) == ("SAPP450110", "SAPP990110")


def test_parse_target_systems_empty_array_returns_empty_tuple():
    assert _parse_target_systems("[]") == ()


def test_parse_target_systems_not_registered_sentinel_returns_empty_not_error():
    """Confirmed real: an unregistered/unknown scope returns HTTP 200 with
    this literal plain-text (non-JSON) body -- must be treated as "no
    configured destination", not parsed as JSON (which would raise)."""
    assert _parse_target_systems("AR AGREEMENT NOT REGISTERED") == ()


def test_parse_target_systems_unexpected_non_json_raises_routing_plan_error():
    with pytest.raises(RoutingPlanError):
        _parse_target_systems("<html>gateway error</html>")
