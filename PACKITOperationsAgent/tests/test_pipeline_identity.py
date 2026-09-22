"""Business-object identity: activation supersession, and where Dependent
Objects can exist at all.

Both rules were confirmed with the domain owner during the S01 domain-modelling
session; neither concept existed in the code before. See the plan's "identity
model" section and CONTEXT.md's Activation counter / Dependent Object entries.
"""

from app.core.domain import MessageType, SearchParams
from app.tools.transform import Hop, TransferRecord

import app.agents.packspec_status.pipeline as pipeline


def _record(
    counter: str | None,
    *,
    seqno: str | None = "00001",
    status: str | None = "ERROR",
    ps_id: str = "00000000040001253724",
    target: str = "SAPP870110",
    document_links: list[dict] | None = None,
) -> TransferRecord:
    hop = Hop(
        message_id=f"MSG-{counter}-{seqno}-{status}",
        message_type="PackITPackagingSpecification",
        host=f"CPI_SAPPD70110_{target}_CONSUMING",
        target_system=target,
        time="2026-08-05T10:00:00Z",
        business_status=status,
        description="SNR13 not found/ Mark for deletion" if status == "ERROR" else "created",
        ps_id=ps_id,
        dir_key=None,
        plant="0110",
        det_type="SHIP",
        usage="R",
        dependent_ps_links=None,
        envelope="atom",
        seqno=seqno,
        activation_counter=counter,
        document_links=document_links,
    )
    return TransferRecord(
        message_id=hop.message_id,
        message_type=hop.message_type,
        ps_id=ps_id,
        dir_key=None,
        target_system=target,
        hops=[hop],
    )


# --- Activation supersession -------------------------------------------------


def test_error_on_a_superseded_activation_is_dropped():
    """The point of the rule: counter 2 succeeded, so counter 1's error
    describes a version of the PS that no longer exists. Reporting it sends
    someone to fix something already replaced."""
    kept, superseded = pipeline.select_live_activations(
        [_record("1", status="ERROR"), _record("2", status="SUCCESS")]
    )

    assert [r.activation_counter for r in kept] == ["2"]
    assert superseded == 1


def test_a_newer_activation_that_has_not_landed_does_not_hide_a_live_error():
    """Fail-open rule 1, and the one outcome this must never produce. Counter 3
    was triggered but has reached no terminal state anywhere, so counter 2's
    ERROR is still the last thing that actually happened at the target. Blind
    filtering would answer "nothing found" about a visibly failing PS."""
    kept, superseded = pipeline.select_live_activations(
        [_record("2", status="ERROR"), _record("3", status=None)]
    )

    assert {r.activation_counter for r in kept} == {"2", "3"}
    assert superseded == 0


def test_records_with_no_activation_counter_are_never_dropped():
    """Fail-open rule 2 -- never drop a record because a field could not be
    read. Losing a real failure costs far more than mentioning a stale one."""
    kept, superseded = pipeline.select_live_activations(
        [_record(None), _record("2", status="SUCCESS")]
    )

    assert len(kept) == 2
    assert superseded == 0


def test_determination_records_are_superseded_independently():
    """Scoped per (ps_id, seqno), not per PS. An *extend* creates a new
    Determination Record without touching the counter, so two records of one PS
    are independent -- counter 1 on SEQNO 00002 is not superseded by counter 2
    on SEQNO 00001."""
    kept, superseded = pipeline.select_live_activations(
        [
            _record("1", seqno="00001", status="SUCCESS"),
            _record("2", seqno="00001", status="SUCCESS"),
            _record("1", seqno="00002", status="ERROR"),
        ]
    )

    assert superseded == 1
    assert {(r.seqno, r.activation_counter) for r in kept} == {("00001", "2"), ("00002", "1")}


def test_activation_counters_sort_numerically_not_lexically():
    """`10` supersedes `9`. The field is a string in the payload, so a naive
    sort would keep the wrong one."""
    kept, _ = pipeline.select_live_activations(
        [_record("9", status="ERROR"), _record("10", status="SUCCESS")]
    )

    assert [r.activation_counter for r in kept] == ["10"]


# --- Where Dependent Objects can exist at all --------------------------------


def test_xoe_target_detection():
    """Target IDs are SAPP + a 2-char system code + 0110; only the `OE` code is
    the xOE line. Deliberately a segment match -- a bare "OE" substring test
    would misclassify a future system code containing those letters."""
    assert pipeline.is_xoe_target("SAPPOE0110")
    assert pipeline.is_xoe_target("SAPQOE0110")  # the Q landscape, same rule
    assert not pipeline.is_xoe_target("SAPP870110")
    assert not pipeline.is_xoe_target("SAPPT00110")
    assert not pipeline.is_xoe_target("SAPP1M0110")
    assert not pipeline.is_xoe_target(None)
    assert not pipeline.is_xoe_target("SAPP")


def test_no_dependent_object_search_runs_against_a_non_xoe_target(monkeypatch):
    """DIR and Dependent Object triggers only ever go to the xOE line, so
    searching elsewhere cannot match. It was two guaranteed-empty Splunk jobs
    per blocked PS, whose empty result was then reported as "the dependent
    object hasn't been published yet" -- a claim about the Source system the
    data never supported. `_run_search` raises so a regression is loud."""

    def _fail(*args, **kwargs):
        raise AssertionError("no dependent-object search may run against a non-xOE target")

    monkeypatch.setattr(pipeline, "_run_search", _fail)

    view = pipeline._lookup_dependent_objects(
        config=None,
        params=SearchParams(ps_id="00000000040001253724"),
        blocked_records=[_record("2", target="SAPP870110")],
    )

    # None, not an empty view: "not applicable here" is a different statement
    # from "looked and found nothing".
    assert view is None


def test_dependent_object_search_runs_against_an_xoe_target(monkeypatch):
    monkeypatch.setattr(pipeline, "_run_search", lambda *a, **k: [])

    view = pipeline._lookup_dependent_objects(
        config=None,
        params=SearchParams(ps_id="00000000040001497551"),
        blocked_records=[_record("2", target="SAPPOE0110")],
    )

    assert view is not None
    # A PS trigger to POE always carries a Dependent Object trigger, so its
    # absence *here* is a real finding -- unlike on any other target.
    assert view.missing_is_anomalous is True


def test_dir_lookup_uses_declared_document_links_not_a_ps_id_search(monkeypatch):
    """Message ID is per trigger *per message type*, so it cannot link a PS to
    its DIRs. DOCUMENT_LINKS on the PS's own payload is the link, already in
    hand -- so the DIR search is by document number, and only for documents the
    PS actually declares."""
    searched: list[SearchParams] = []

    def _capture(config, params):
        searched.append(params)
        return []

    monkeypatch.setattr(pipeline, "_run_search", _capture)

    record = _record(
        "2",
        target="SAPPOE0110",
        document_links=[
            {
                "DOCUMENT_TYPE": "PAC",
                "DOCUMENT_NUMBER": "0000000000000000001627019",
                "DOCUMENT_PART": "FRE",
                "DOCUMENT_VERSION": "00",
            }
        ],
    )

    view = pipeline._lookup_dependent_objects(
        config=None, params=SearchParams(ps_id=record.ps_id), blocked_records=[record]
    )

    dir_searches = [p for p in searched if p.message_type == MessageType.DOCUMENT_INFO_RECORD]
    assert [p.document_number for p in dir_searches] == ["0000000000000000001627019"]
    assert all(p.ps_id is None for p in dir_searches), "a DIR is not findable by PS ID"
    # The declared key is reported whether or not a Transfer was found for it,
    # so "declares none" and "declares one that has not appeared" stay distinct.
    assert view.linked_document_keys == ("PAC-0000000000000000001627019-FRE-00",)


def test_no_dir_search_when_the_ps_declares_no_document_links(monkeypatch):
    """A DIR trigger is optional even on the xOE line, so a PS with no declared
    links has nothing to look for -- and searching anyway is the same wasted
    round trip the target gate removes."""
    searched: list[SearchParams] = []

    def _capture(config, params):
        searched.append(params)
        return []

    monkeypatch.setattr(pipeline, "_run_search", _capture)

    pipeline._lookup_dependent_objects(
        config=None,
        params=SearchParams(ps_id="00000000040001497551"),
        blocked_records=[_record("2", target="SAPPOE0110")],
    )

    assert not [p for p in searched if p.message_type == MessageType.DOCUMENT_INFO_RECORD]
