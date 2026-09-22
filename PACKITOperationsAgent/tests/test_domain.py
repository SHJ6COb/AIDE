from app.core.domain import (
    DeterminationType,
    MessageType,
    ReplicationStatus,
    SearchParams,
    TimeRange,
    is_underspecified,
    parse_search_params,
)


def test_all_valid_fields_pass_through():
    params = parse_search_params(
        {
            "ps_id": "00000000040001498023",
            "plant": "0780",
            "supplier": "SUP123",
            "customer_index": "FU2",
            "matnr": "6000.409.798",
            "document_number": "DOC1",
            "determination_type": "SHIP",
            "message_type": "PackITPackagingSpecification",
            "usage": "R",
            "sales_channel": "OE",
            "target_system": "SAPP790110",
            "status": "ERROR",
            "time_earliest": "-3h",
            "additional_terms": ["brand X"],
        }
    )
    assert params.ps_id == "00000000040001498023"
    assert params.plant == "0780"
    assert params.determination_type == DeterminationType.SHIP
    assert params.message_type == MessageType.PACKAGING_SPECIFICATION
    assert params.usage == "R"
    assert params.sales_channel == "OE"
    assert params.target_system == "SAPP790110"
    assert params.status == ReplicationStatus.ERROR
    assert params.time_range == TimeRange(earliest="-3h", latest="now")
    assert params.additional_terms == ("brand X",)


def test_target_system_pattern_validation():
    assert parse_search_params({"target_system": "SAPP790110"}).target_system == "SAPP790110"
    assert parse_search_params({"target_system": "SAPPT00110"}).target_system == "SAPPT00110"
    assert parse_search_params({"target_system": "a"}).target_system is None  # too short
    assert parse_search_params({"target_system": "has a space"}).target_system is None


def test_status_out_of_enum_dropped_to_none():
    assert parse_search_params({"status": "RETRY"}).status is None  # not a raw BusinessStatus value
    assert parse_search_params({"status": "success"}).status is None  # case-sensitive, must match enum exactly
    assert parse_search_params({}).status is None


def test_missing_fields_default_to_none_and_default_time_range():
    params = parse_search_params({})
    assert params.ps_id is None
    assert params.message_type is None
    assert params.time_range == TimeRange.default()
    assert params.additional_terms == ()


def test_invalid_enum_value_dropped_to_none_not_raised():
    params = parse_search_params({"determination_type": "NOT_REAL", "message_type": "AlsoFake"})
    assert params.determination_type is None
    assert params.message_type is None


def test_invalid_pattern_value_dropped_to_none():
    params = parse_search_params({"ps_id": "not-a-real-ps-id!!!", "plant": "way-too-long-for-a-plant-code"})
    assert params.ps_id is None
    assert params.plant is None


def test_invalid_usage_and_sales_channel_dropped_to_none():
    params = parse_search_params({"usage": "A9", "sales_channel": "MADE_UP"})
    assert params.usage is None
    assert params.sales_channel is None


def test_time_range_capped_at_max_days():
    params = parse_search_params({"time_earliest": "-90d"})
    assert params.time_range.earliest == "-30d"


def test_unparseable_time_range_falls_back_to_default():
    params = parse_search_params({"time_earliest": "last week"})
    assert params.time_range == TimeRange.default()


def test_blank_additional_terms_filtered_out():
    params = parse_search_params({"additional_terms": ["real term", "  ", ""]})
    assert params.additional_terms == ("real term",)


# `is_underspecified` and these tests moved here from harness.py/test_harness.py
# when the `baseline` regression run found the guard reachable around, via
# pipeline._check_routing_if_target_missing -- which could not import it back
# out of harness.py without a cycle.


def test_is_underspecified_true_when_completely_empty():
    assert is_underspecified(SearchParams())


def test_is_underspecified_false_when_ps_id_set_alone():
    assert not is_underspecified(SearchParams(ps_id="123456"))


def test_is_underspecified_false_when_document_number_set_alone():
    assert not is_underspecified(SearchParams(document_number="DOC1"))


def test_is_underspecified_false_when_any_additional_term_set():
    assert not is_underspecified(SearchParams(additional_terms=("France",)))


def test_is_underspecified_true_when_only_one_identifying_field_set():
    """A single broad field (e.g. sales_channel alone) is a milder version
    of the same "unscoped enough to dump arbitrary real data" problem as a
    fully empty search -- not sufficient on its own."""
    assert is_underspecified(SearchParams(sales_channel="OE"))
    assert is_underspecified(SearchParams(plant="0780"))
    assert is_underspecified(SearchParams(target_system="SAPP790110"))


def test_is_underspecified_false_when_two_identifying_fields_set_together():
    assert not is_underspecified(SearchParams(plant="0780", determination_type=None, target_system="SAPP790110"))


def test_is_underspecified_true_when_only_status_set_alone():
    """`status` never counts toward sufficiency by itself -- `status=ERROR`
    alone is still as broad as "every failure right now" across the whole
    pipeline, the exact class of problem this guard exists to catch."""
    assert is_underspecified(SearchParams(status=ReplicationStatus.ERROR))


def test_is_underspecified_false_when_status_paired_with_one_identifying_field():
    """Regression test: caught live -- "failed transfers to target system
    SAPP790110" and "failed transfers for plant 0580" are legitimate,
    well-scoped questions (one identifying field + status), not the same
    failure mode as an unscoped search. An earlier version of this guard
    over-corrected and blocked both."""
    assert not is_underspecified(SearchParams(status=ReplicationStatus.ERROR, target_system="SAPP790110"))
    assert not is_underspecified(SearchParams(status=ReplicationStatus.ERROR, plant="0580"))


def test_is_underspecified_false_when_status_paired_with_two_identifying_fields():
    assert not is_underspecified(
        SearchParams(status=ReplicationStatus.ERROR, plant="0780", target_system="SAPP790110")
    )


def test_short_target_system_names_resolve_to_the_real_id():
    """"P87" is how people name SAPP870110 out loud, and `_TARGET_SYSTEM_RE`
    demands 6-15 characters -- so it validated to None, the `host=` clause
    vanished from the SPL, and a live question about P87 was answered with
    successes from every other system instead.
    """
    from app.core.domain import resolve_target_system

    assert resolve_target_system("P87") == "SAPP870110"
    assert resolve_target_system("POE") == "SAPPOE0110"
    assert resolve_target_system("pt0") == "SAPPT00110"
    assert resolve_target_system("SAPP1M0110") == "SAPP1M0110"
    # A bare two-character code collides with plant codes and Usage values.
    # Guessing between them is how a search silently widens.
    assert resolve_target_system("87") is None


def test_a_supplied_value_that_cannot_be_resolved_is_recorded_not_discarded():
    """Validation dropping a field to None is safe for the SPL and dangerous
    for the answer: the clause disappears, the search widens, and the reply
    still reads as though the constraint applied."""
    params = parse_search_params({"ps_id": "00000000040001253724", "plant": "much-too-long-for-a-plant"})

    assert params.plant is None
    assert params.unresolved == (("plant", "much-too-long-for-a-plant"),)


def test_absent_and_empty_fields_are_not_reported_as_unresolved():
    """Only a *real value that vanished* is a failure. Treating absence as a
    failure would make the guard fire on every ordinary search."""
    params = parse_search_params({"ps_id": "00000000040001253724", "plant": "", "supplier": None})

    assert params.unresolved == ()
