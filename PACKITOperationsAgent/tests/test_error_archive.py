import pytest

from app.tools.error_archive import ErrorArchive
from app.tools.transform import Hop, TransferRecord


def _hop(*, status=None, time="2026-08-06T10:00:00", plant="0780", det_type="SHIP", description=None):
    return Hop(
        message_id="MSG1",
        message_type="PackITPackagingSpecification",
        host="CPI_SAPPD70110_SAPP790110_CONSUMING",
        target_system="SAPP790110",
        time=time,
        business_status=status,
        description=description,
        ps_id="00000000040000054543",
        dir_key=None,
        plant=plant,
        det_type=det_type,
        usage="R",
        dependent_ps_links=None,
        envelope="atom",
    )


def _record(*, message_id="MSG1", target="SAPP790110", hops=None, ps_id="00000000040000054543"):
    return TransferRecord(
        message_id=message_id,
        message_type="PackITPackagingSpecification",
        ps_id=ps_id,
        dir_key=None,
        target_system=target,
        hops=hops or [_hop(status="ERROR")],
    )


@pytest.fixture
def archive(tmp_path):
    return ErrorArchive(tmp_path / "test.db")


# -- rule 1: the latest hop decides ---------------------------------------


def test_latest_hop_error_is_persisted(archive):
    report = archive.reconcile([_record(hops=[_hop(status="ERROR", description="SNR13 not found")])])
    assert report.persisted == [("MSG1", "SAPP790110")]
    assert archive.get("MSG1", "SAPP790110").description == "SNR13 not found"


def test_latest_hop_success_is_not_persisted_even_when_earlier_hops_failed(archive):
    """The specified rule: only the latest hop matters. A Transfer that failed
    twice and then succeeded is not a current failure."""
    hops = [
        _hop(status="ERROR", time="2026-08-06T10:00:00"),
        _hop(status="ERROR", time="2026-08-06T11:00:00"),
        _hop(status="SUCCESS", time="2026-08-06T12:00:00"),
    ]
    report = archive.reconcile([_record(hops=hops)])
    assert report.persisted == []
    assert report.already_clean == 1
    assert archive.count_open_errors() == 0


def test_refreshing_a_still_failing_transfer_preserves_how_long_it_has_been_failing(archive):
    """`first_persisted_at` is the one fact here that Splunk's retention
    window will eventually destroy -- a refresh must not reset it."""
    archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])])
    first = archive.get("MSG1", "SAPP790110").first_persisted_at

    report = archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T14:00:00", description="still broken")])])

    stored = archive.get("MSG1", "SAPP790110")
    assert report.refreshed == [("MSG1", "SAPP790110")]
    assert report.persisted == []
    assert stored.first_persisted_at == first
    assert stored.description == "still broken"
    assert stored.latest_hop_time == "2026-08-06T14:00:00"


# -- rule 2: resolve on a later run ---------------------------------------


def test_persisted_error_is_deleted_once_a_later_run_sees_a_success(archive):
    """The core of the requested mechanism: run 1 persists the failure, run 2
    sees the Retrigger succeed and removes the entry."""
    archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])])
    assert archive.count_open_errors() == 1

    report = archive.reconcile(
        [_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00"), _hop(status="SUCCESS", time="2026-08-06T15:00:00")])]
    )

    assert report.resolved == [("MSG1", "SAPP790110")]
    assert archive.count_open_errors() == 0
    assert archive.get("MSG1", "SAPP790110") is None


def test_success_for_a_transfer_never_persisted_is_not_reported_as_resolved(archive):
    """Only an entry that was actually removed counts as resolved -- otherwise
    every healthy Transfer in the window inflates the number."""
    report = archive.reconcile([_record(hops=[_hop(status="SUCCESS")])])
    assert report.resolved == []
    assert report.already_clean == 1


def test_resolving_one_target_leaves_another_target_still_failing(archive):
    """One Message ID fans out to several Transfers with independent
    outcomes. Keying by Message ID alone would delete a target that is still
    broken (CONTEXT.md's Transfer entry)."""
    failing_a = _record(target="SAPP790110", hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])
    failing_b = _record(target="SAPPT00110", hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])
    archive.reconcile([failing_a, failing_b])
    assert archive.count_open_errors() == 2

    fixed_a = _record(target="SAPP790110", hops=[_hop(status="SUCCESS", time="2026-08-06T15:00:00")])
    report = archive.reconcile([fixed_a, failing_b])

    assert report.resolved == [("MSG1", "SAPP790110")]
    assert archive.count_open_errors() == 1
    assert archive.get("MSG1", "SAPPT00110") is not None


# -- ordering safeguards ---------------------------------------------------


def test_an_older_window_cannot_resurrect_a_resolved_error(archive):
    """The latest hop *in one search window* is not the Transfer's latest hop
    globally. A run covering an earlier window can surface only the old error
    hops of a Transfer that has since succeeded -- without the hop-time guard
    the two runs would fight, flip-flopping the entry on every pass."""
    archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])])
    archive.reconcile([_record(hops=[_hop(status="SUCCESS", time="2026-08-06T15:00:00")])])
    assert archive.count_open_errors() == 0

    # A later run re-scanning an earlier window sees only the old error hop.
    report = archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])])

    # Nothing is stored, so there is no newer state to compare against and the
    # error is persisted again -- documented, not silently surprising.
    assert report.persisted == [("MSG1", "SAPP790110")]


def test_an_older_error_hop_does_not_overwrite_a_newer_stored_one(archive):
    archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T14:00:00", description="newer")])])

    report = archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00", description="older")])])

    assert report.stale_skipped == [("MSG1", "SAPP790110")]
    assert archive.get("MSG1", "SAPP790110").description == "newer"


def test_an_older_success_does_not_delete_a_newer_stored_error(archive):
    """Symmetric to the above, and the more dangerous direction: a stale
    success must not clear a failure that happened after it."""
    archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T14:00:00")])])

    report = archive.reconcile([_record(hops=[_hop(status="SUCCESS", time="2026-08-06T10:00:00")])])

    assert report.stale_skipped == [("MSG1", "SAPP790110")]
    assert archive.count_open_errors() == 1


# -- the third branch: neither error nor success ---------------------------


def test_a_hop_with_no_status_leaves_the_store_untouched(archive):
    """Two confirmed-open gaps make this branch real rather than theoretical:
    DocumentInfoRecord has no observed error/success signal at its processed
    stage, and the RETRY payload shape has never been captured. An
    unclassifiable hop must neither invent a failure nor clear a real one."""
    archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])])

    report = archive.reconcile([_record(hops=[_hop(status=None, time="2026-08-06T15:00:00")])])

    assert report.undetermined == [("MSG1", "SAPP790110")]
    assert report.resolved == []
    assert archive.count_open_errors() == 1


def test_an_unrecognized_status_value_is_undetermined_not_a_resolution(archive):
    archive.reconcile([_record(hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])])
    report = archive.reconcile([_record(hops=[_hop(status="RETRY", time="2026-08-06T15:00:00")])])
    assert report.undetermined == [("MSG1", "SAPP790110")]
    assert archive.count_open_errors() == 1


# -- misc ------------------------------------------------------------------


def test_a_transfer_with_no_target_system_stores_and_reads_back_as_none(archive):
    """Every DocumentInfoRecord has no derivable Target System. SQLite treats
    NULLs in a composite PRIMARY KEY as distinct, so a real NULL would allow
    unlimited duplicate rows for the same Message ID."""
    archive.reconcile([_record(target=None, hops=[_hop(status="ERROR")])])
    archive.reconcile([_record(target=None, hops=[_hop(status="ERROR")])])

    assert archive.count_open_errors() == 1
    assert archive.get("MSG1", None).target_system is None


def test_list_open_errors_filters_by_ps_id(archive):
    archive.reconcile(
        [
            _record(message_id="MSG1", ps_id="PS_A", hops=[_hop(status="ERROR")]),
            _record(message_id="MSG2", ps_id="PS_B", hops=[_hop(status="ERROR")]),
        ]
    )
    assert [e.message_id for e in archive.list_open_errors(ps_id="PS_B")] == ["MSG2"]
    assert len(archive.list_open_errors()) == 2


def test_report_delta_summarizes_the_run(archive):
    archive.reconcile([_record(message_id="OLD", hops=[_hop(status="ERROR", time="2026-08-06T10:00:00")])])
    report = archive.reconcile(
        [
            _record(message_id="OLD", hops=[_hop(status="SUCCESS", time="2026-08-06T15:00:00")]),
            _record(message_id="NEW1", hops=[_hop(status="ERROR", time="2026-08-06T15:00:00")]),
            _record(message_id="NEW2", hops=[_hop(status="ERROR", time="2026-08-06T15:00:00")]),
        ]
    )
    assert report.open_error_delta == 1
    assert archive.count_open_errors() == 2
