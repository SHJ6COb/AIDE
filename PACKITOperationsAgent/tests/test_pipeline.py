from app.agents.packspec_status.pipeline import RoutingCheck, _check_routing_if_target_missing
from app.core.domain import DeterminationType, MessageType, SearchParams
from app.tools.routing_plan import RoutingPlanError, RoutingPlanResult
from app.tools.transform import Hop, TransferRecord

import app.agents.packspec_status.pipeline as pipeline


def _record(plant: str | None, det_type: str | None) -> TransferRecord:
    hop = Hop(
        message_id="MSG1",
        message_type="PackITPackagingSpecification",
        host="CPI_SAPPD70110_SAPP450110_CONSUMING",
        target_system="SAPP450110",
        time="2026-08-05T10:00:00Z",
        business_status="ERROR",
        description="some error",
        ps_id="00000000040001498023",
        dir_key=None,
        plant=plant,
        det_type=det_type,
        usage="R",
        dependent_ps_links=None,
        envelope="atom",
    )
    return TransferRecord(message_id="MSG1", message_type="PackITPackagingSpecification", ps_id=hop.ps_id, dir_key=None, target_system="SAPP450110", hops=[hop])


def test_no_routing_check_when_target_system_not_asked_about():
    params = SearchParams(ps_id="00000000040001498023")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[])
    assert result is None


def test_no_routing_check_when_primary_records_already_found():
    params = SearchParams(ps_id="00000000040001498023", target_system="SAPP1M0110")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[_record("8150", "SHIP")])
    assert result is None


def test_fails_closed_when_broader_search_finds_nothing(monkeypatch):
    """If the PS genuinely doesn't exist anywhere (not just at the
    requested target), there's no Plant/Determination Type to check routing
    against -- must not guess, must return None."""
    monkeypatch.setattr(pipeline, "_run_search", lambda config, params: [])
    params = SearchParams(ps_id="00000000040001498023", target_system="SAPP1M0110")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[])
    assert result is None


def test_fails_closed_when_plant_or_det_type_unresolvable(monkeypatch):
    monkeypatch.setattr(pipeline, "_run_search", lambda config, params: [_record(None, None)])
    params = SearchParams(ps_id="00000000040001498023", target_system="SAPP1M0110")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[])
    assert result is None


def test_fails_closed_when_routing_plan_call_fails(monkeypatch):
    monkeypatch.setattr(pipeline, "_run_search", lambda config, params: [_record("8150", "SHIP")])

    def _raise(*args, **kwargs):
        raise RoutingPlanError("gateway down")

    monkeypatch.setattr(pipeline.routing_plan, "query_target_systems", _raise)
    params = SearchParams(ps_id="00000000040001498023", target_system="SAPP1M0110")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[])
    assert result is None


def test_fails_closed_when_broadening_the_search_would_make_it_underspecified(monkeypatch):
    """Regression test: the `baseline` run's S06/q3. "Failed transfers to
    SAPP870110" is target_system + status, which the scope guard rightly
    allows -- but dropping `target_system` to broaden it leaves
    `status=ERROR` alone, and that bare sweep really did reach the backend:
    the exact query the guard had refused outright one turn earlier,
    returning 200 of the corpus's 257 events. No search may run here at
    all."""
    from app.core.domain import ReplicationStatus

    def _fail_if_called(config, params):
        raise AssertionError("must not run an underspecified broadened search")

    monkeypatch.setattr(pipeline, "_run_search", _fail_if_called)
    params = SearchParams(target_system="SAPP870110", status=ReplicationStatus.ERROR)
    assert _check_routing_if_target_missing(config=None, params=params, primary_records=[]) is None


def test_broadened_search_still_runs_when_it_stays_specific_enough(monkeypatch):
    """The scope re-check must not block the routing path it was added
    beside: a PS-ID-scoped search is still self-sufficient without its
    target system, which is the whole S04 routing-gap scenario."""
    monkeypatch.setattr(pipeline, "_run_search", lambda config, params: [_record("0110", "SHIP")])
    monkeypatch.setattr(
        pipeline.routing_plan,
        "query_target_systems",
        lambda config, *, plant, determination_type: RoutingPlanResult(
            plant=plant, determination_type=determination_type, target_systems=("SAPP870110",)
        ),
    )
    params = SearchParams(ps_id="00000000040001253724", target_system="SAPP790110")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[])
    assert result is not None and result.configured_target_systems == ("SAPP870110",)


def test_populates_routing_check_when_target_was_not_configured(monkeypatch):
    monkeypatch.setattr(pipeline, "_run_search", lambda config, params: [_record("8150", "SHIP")])
    monkeypatch.setattr(
        pipeline.routing_plan,
        "query_target_systems",
        lambda config, *, plant, determination_type: RoutingPlanResult(
            plant=plant, determination_type=determination_type, target_systems=("SAPP450110", "SAPP1M0110")
        ),
    )
    params = SearchParams(ps_id="00000000040001498023", target_system="SAPP790110")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[])
    assert result == RoutingCheck(
        plant="8150",
        determination_type="SHIP",
        configured_target_systems=("SAPP450110", "SAPP1M0110"),
        requested_target_system="SAPP790110",
        requested_target_was_configured=False,
    )


def test_populates_routing_check_when_target_was_configured(monkeypatch):
    monkeypatch.setattr(pipeline, "_run_search", lambda config, params: [_record("8150", "SHIP")])
    monkeypatch.setattr(
        pipeline.routing_plan,
        "query_target_systems",
        lambda config, *, plant, determination_type: RoutingPlanResult(
            plant=plant, determination_type=determination_type, target_systems=("SAPP1M0110",)
        ),
    )
    params = SearchParams(ps_id="00000000040001498023", target_system="SAPP1M0110")
    result = _check_routing_if_target_missing(config=None, params=params, primary_records=[])
    assert result.requested_target_was_configured is True
