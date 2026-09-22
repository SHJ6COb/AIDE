import pytest

from app.core.domain import DeterminationType, MessageType, ReplicationStatus, SearchParams, TimeRange
from app.tools.splunk_client import InvalidSearchTerm, build_spl


def test_build_spl_bare_ps_id_search():
    params = SearchParams(ps_id="00000000040001480970")
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert spl == 'search index=pdbb sourcetype=Native "00000000040001480970" | head 200'


def test_build_spl_message_type_uses_leading_wildcard_source_filter():
    """Confirmed live: a real minority of events carry a `Native/`-prefixed
    `source` (e.g. `Native/PackITPackagingSpecification`). An exact-match
    filter silently undercounts by missing those -- see
    docs/components/splunk-client/TECHNICAL_SPEC.md.
    """
    params = SearchParams(message_type=MessageType.PACKAGING_SPECIFICATION)
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert 'source="*PackITPackagingSpecification"' in spl


def test_build_spl_combines_all_tier1_fields():
    params = SearchParams(
        ps_id="00000000040001480970",
        plant="8150",
        supplier="SUP1",
        customer_index="FU2",
        matnr="60123456",
        document_number="DOC1",
        determination_type=DeterminationType.SHIP,
        message_type=MessageType.COCKPIT_MASTER_DATA,
        usage="R",
        sales_channel="OE",
        target_system="SAPP790110",
        status=ReplicationStatus.ERROR,
    )
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    for expected in (
        'source="*PackITPackagingCockpitMasterData"',
        '"00000000040001480970"',
        '"8150"',
        '"SUP1"',
        '"FU2"',
        '"60123456"',
        '"DOC1"',
        '"SHIP"',
        '"R"',
        '"OE"',
        'host="*SAPP790110*"',
        '"<d:BusinessStatus>ERROR</d:BusinessStatus>"',
    ):
        assert expected in spl


def test_build_spl_target_system_uses_structural_host_filter_not_bare_text():
    """Confirmed live (2026-08-05): a bare full-text term for target_system
    silently returned zero hits for a known-real POE PS, because POE's
    target system id lives only in the `host` field, never repeated inside
    the JSON payload body the way it is for SAPP1M0110/SAPP990110/etc. --
    see splunk_client.py's build_spl docstring/comment."""
    params = SearchParams(target_system="SAPPOE0110")
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert 'host="*SAPPOE0110*"' in spl
    assert '"SAPPOE0110"' not in spl  # must not also appear as a bare full-text term


def test_build_spl_no_target_system_omits_host_filter():
    params = SearchParams()
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert "host=" not in spl


def test_build_spl_status_uses_exact_structural_tag_not_bare_word():
    """Confirmed live: a bare-word search for "SUCCESS" false-matched 196/200
    real results (pre-consumption hops with no actual status at all) --
    only the exact Atom/OData tag is precise. See TECHNICAL_SPEC.md."""
    params = SearchParams(status=ReplicationStatus.SUCCESS)
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert '"<d:BusinessStatus>SUCCESS</d:BusinessStatus>"' in spl
    assert '"SUCCESS"' not in spl  # must not also appear as a bare term


def test_build_spl_no_status_omits_status_clause():
    params = SearchParams()
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert "BusinessStatus" not in spl


def test_build_spl_no_message_type_omits_source_filter():
    params = SearchParams()
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert "source=" not in spl


def test_build_spl_result_cap_is_always_appended():
    spl = build_spl(SearchParams(), index="pdbb", sourcetype="Native")
    assert spl.endswith("| head 200")


def test_build_spl_custom_result_cap():
    spl = build_spl(SearchParams(), index="pdbb", sourcetype="Native", result_cap=50)
    assert spl.endswith("| head 50")


def test_build_spl_additional_terms_included():
    params = SearchParams(additional_terms=("valid-term_1.2",))
    spl = build_spl(params, index="pdbb", sourcetype="Native")
    assert '"valid-term_1.2"' in spl


@pytest.mark.parametrize(
    "bad_term",
    [
        "a | delete",
        "a`b",
        'a"b',
        "a; rm -rf",
        "a$b",
        "a" * 201,
    ],
)
def test_build_spl_rejects_unsafe_tier2_terms(bad_term):
    params = SearchParams(additional_terms=(bad_term,))
    with pytest.raises(InvalidSearchTerm):
        build_spl(params, index="pdbb", sourcetype="Native")


def test_build_spl_rejects_unsafe_tier1_value_defense_in_depth():
    """Tier 1 values are expected to already be validated upstream, but
    build_spl still refuses a value that could break out of SPL quoting --
    defense in depth, not the primary guardrail for these fields.
    """
    params = SearchParams(ps_id='000"| delete')
    with pytest.raises(InvalidSearchTerm):
        build_spl(params, index="pdbb", sourcetype="Native")


def test_time_range_default_is_last_15_minutes():
    assert TimeRange.default() == TimeRange(earliest="-15m", latest="now")


def test_search_params_default_time_range_is_15_minutes():
    assert SearchParams().time_range == TimeRange.default()


def test_auth_header_name_comes_from_config_not_a_literal():
    """All four REST calls go through _auth_headers, so the header name can't
    drift between them -- and a gateway-side rename is one config change."""
    from types import SimpleNamespace

    from app.tools.splunk_client import _auth_headers

    config = SimpleNamespace(splunk_auth_header="KeyID", splunk_api_token="tok")
    assert _auth_headers(config) == {"KeyID": "tok"}
    assert _auth_headers(SimpleNamespace(splunk_auth_header="X-Api-Key", splunk_api_token="tok")) == {"X-Api-Key": "tok"}


def _record_flow(monkeypatch, *, pages: list[str] | None = None) -> list[tuple]:
    """Replace the four REST calls with recorders, returning the call log.

    The flow itself is not re-tested here -- `_start_job`/`_poll_until_done`/
    `_fetch_results_page`/`_delete_job` are unchanged. What matters is that
    extracting `search_spl` out of `search` did not drop a call, reorder them,
    or lose the `finally`-guaranteed job deletion.
    """
    from app.tools import splunk_client

    log: list[tuple] = []
    pages = pages if pages is not None else ["<results/>"]

    monkeypatch.setattr(splunk_client, "_start_job", lambda c, cfg, spl, e, l: log.append(("start", spl, e, l)) or "sid-1")
    monkeypatch.setattr(splunk_client, "_poll_until_done", lambda c, cfg, sid: log.append(("poll", sid)))
    monkeypatch.setattr(
        splunk_client,
        "_fetch_results_page",
        lambda c, cfg, sid, offset, count: log.append(("fetch", sid, offset, count)) or pages[len(log) % len(pages) - 1],
    )
    monkeypatch.setattr(splunk_client, "_delete_job", lambda c, cfg, sid: log.append(("delete", sid)))
    return log


def test_search_spl_runs_the_four_calls_in_order_and_always_deletes(monkeypatch):
    from types import SimpleNamespace

    from app.tools import splunk_client

    log = _record_flow(monkeypatch)
    config = SimpleNamespace(splunk_verify_ssl=True, splunk_search_timeout_seconds=60)

    splunk_client.search_spl(config, "search index=pdbb | stats count by topic", "-30d", "now")

    assert [entry[0] for entry in log] == ["start", "poll", "fetch", "delete"]
    assert log[0] == ("start", "search index=pdbb | stats count by topic", "-30d", "now")
    assert log[2] == ("fetch", "sid-1", 0, splunk_client.RESULT_PAGE_SIZE)


def test_search_spl_deletes_the_job_even_when_polling_fails(monkeypatch):
    """A leaked search job is a server-side resource nobody reclaims. The
    `finally` must survive the refactor, so this asserts it directly."""
    from types import SimpleNamespace

    from app.tools import splunk_client

    log = _record_flow(monkeypatch)

    def boom(client, config, sid):
        log.append(("poll", sid))
        raise splunk_client.SplunkPollTimeout("never finished")

    monkeypatch.setattr(splunk_client, "_poll_until_done", boom)
    config = SimpleNamespace(splunk_verify_ssl=True, splunk_search_timeout_seconds=60)

    with pytest.raises(splunk_client.SplunkPollTimeout):
        splunk_client.search_spl(config, "search index=pdbb", "-15m", "now")

    assert log[-1] == ("delete", "sid-1")


def test_search_still_sends_exactly_what_build_spl_produces(monkeypatch):
    """`search` is the only path reachable from a question, so it must keep
    going through `build_spl` -- delegating to `search_spl` must not become a
    way for an unvalidated SPL string to reach the gateway."""
    from types import SimpleNamespace

    from app.tools import splunk_client

    log = _record_flow(monkeypatch)
    config = SimpleNamespace(
        splunk_verify_ssl=True,
        splunk_search_timeout_seconds=60,
        splunk_index="pdbb",
        splunk_sourcetype="Native",
    )
    params = SearchParams(ps_id="00000000040001480970", time_range=TimeRange(earliest="-4h"))

    splunk_client.search(config, params)

    assert log[0] == ("start", build_spl(params, index="pdbb", sourcetype="Native"), "-4h", "now")
