from pathlib import Path

from app.tools.splunk_xml_parser import parse_results
from app.tools.transform import group_transfers

_FIXTURES = Path(__file__).parent / "fixtures"
_EXAMPLES = Path(__file__).resolve().parents[1] / "splunkExamples"
"""The real captures committed to the repo. Used directly rather than copied
into `fixtures/` so these tests exercise the same bytes the regression suite
replays -- a divergence between the two would be invisible otherwise."""


def _load_records():
    xml_text = (_FIXTURES / "multi_target_fanout_page.xml").read_text(encoding="utf-8")
    return group_transfers(parse_results(xml_text))


def _records_from(*parts: str):
    return group_transfers(parse_results(_EXAMPLES.joinpath(*parts).read_text(encoding="utf-8")))


def test_multi_target_fanout_each_target_gets_its_own_terminal_status():
    """Regression test for a real bug found via live cross-check against
    screenshots/results/00000000040001498023_1.png: PS 00000000040001498023
    fans out to 3 PackITPackagingSpecification targets from 2 Message IDs.
    One target's own pre-consumption "publish" hop (`CPI_{source}_{target}`,
    no `_CONSUMING` suffix -- a real host shape not previously documented in
    CONTEXT.md's Host entry) was being misclassified as "shared/untargeted"
    and, since it timestamped later than a *different* target's genuine
    terminal hop, was silently overwriting that other target's `.latest`
    with a false no-status/no-description result. See
    docs/components/transform/TECHNICAL_SPEC.md for the confirmed fix.
    """
    records = _load_records()
    by_target = {r.target_system: r for r in records if r.message_type == "PackITPackagingSpecification"}

    assert set(by_target) == {"SAPP990110", "SAPPOE0110", "SAPPT00110"}

    # The dashboard shows all three as Success -- none should be None/blank,
    # which is what the bug produced for SAPP990110 specifically.
    for target, record in by_target.items():
        assert record.current_status == "SUCCESS", f"{target} should resolve to its own terminal SUCCESS hop"
        assert record.current_description, f"{target} should carry its own terminal hop's description"

    # SAPP990110's real terminal description ends with "ECM Already exist"
    # (confirmed against the dashboard screenshot) -- this is the exact
    # signal that was lost when the bug attached a different target's
    # earlier, status-less publish hop as this target's `.latest` instead.
    assert by_target["SAPP990110"].current_description.endswith("ECM Already exist")


def test_multi_target_fanout_untargeted_solace_hops_shared_across_targets():
    """SOLACE hops carry no derivable target at all (confirmed real, see
    CONTEXT.md's Host entry) -- they're genuinely shared context and should
    appear in every target-specific group for a Message ID that fans out,
    not just one."""
    records = _load_records()
    by_target = {r.target_system: r for r in records if r.message_type == "PackITPackagingSpecification"}

    # SAPP990110 and SAPPOE0110 share Message ID 0EBD9DC62D031FD1A480BCBED9595863
    # and its 3 SOLACE hops; SAPPT00110 is a separate Message ID with its own.
    assert any(h.host == "SOLACE" for h in by_target["SAPP990110"].hops)
    assert any(h.host == "SOLACE" for h in by_target["SAPPOE0110"].hops)
    assert any(h.host == "SOLACE" for h in by_target["SAPPT00110"].hops)


def test_determination_body_yields_the_snr13_the_error_is_actually_about():
    """The catalog's rows 2/3 talk about "the 10- or 13-digit number", and the
    app used to pass that phrasing straight through without ever naming the
    number -- because `_parse_atom_hop` read only SINGLEMESSAGEHEADER and never
    the DETERMINATION body where it lives. An engineer cannot act on "the
    SNR13"; they act on 028100944104Y.

    Caught by the `baseline` regression run, S01 (see
    regressionSuite/runs/postfix/S01_large_retry_chain/).
    """
    record = _records_from("example5", "payload5")[0]

    assert record.snr13 == "028100944104Y"
    assert record.identity("matnr") == "0281009441"
    assert record.identity("packindex") == "04Y"
    # SNR13 = MATNR + PACKINDEX -- confirmed across every capture in the repo.
    assert record.snr13 == record.identity("matnr") + record.identity("packindex")


def test_snr13_is_the_bare_snr10_when_there_is_no_pack_index():
    """Why the catalog says "10- **or** 13-digit": with an empty PACKINDEX the
    value is just the 10-digit SNR10. Reporting it as "the SNR13" would be
    wrong, so nothing may assume a 13-character value."""
    record = _records_from("example3", "payload3")[0]

    assert record.snr13 == "F00C2G8057"
    assert record.identity("packindex") is None


def test_business_object_identity_is_read_from_objectkey():
    """PS_ID alone does not identify what replicated. SEQNO says *which
    Determination Record*, and ZACTCOUNTER which version of the PS structure --
    the field the Target System uses to pick the newest trigger. ZACTCOUNTER is
    space-padded in the payload (`" 3"`) and must not surface that way."""
    record = _records_from("example1", "payload")[0]

    assert record.seqno == "00001"
    assert record.activation_counter == "3"
    assert record.identity("ps_group") == "PS2"
    assert record.identity("packspec_status") == "A"


def test_sales_channel_comes_from_pack_usage_not_label_saleschanl():
    """Sales Channel is `PACK_USAGE`. `LABEL_SALESCHANL` is a different field
    that merely happens to hold the same value on outbound records -- which is
    why reading the wrong one survived 217 passing tests.

    example3 is the case that separates them: an inbound (RCPT) record, where
    `LABEL_SALESCHANL` is empty and `PACK_USAGE` is `OE`, agreeing with the
    TOPICSTRING Sales Channel segment as it does on all 254 PS records in the
    corpus. Reading the wrong field reported *no* Sales Channel for every
    inbound Determination Record. See `CONTEXT.md`'s Sales Channel entry for
    why SAP naming makes this trap easy to fall into.
    """
    record = _records_from("example3", "payload3")[0]

    assert record.identity("sales_channel") == "OE"
    assert record.identity("det_type") == "RCPT"


def test_document_links_carry_the_ps_to_dir_edge():
    """Message ID is per trigger *per message type*, so it can never link a PS
    to its Document Info Records. DOCUMENT_LINKS on the PS's own payload is the
    link -- each entry already shaped like the four-part DIR key."""
    record = _records_from("example1", "payload")[0]

    assert len(record.document_links) == 2
    assert {link["DOCUMENT_NUMBER"] for link in record.document_links} == {
        "0000000000000000001627019",
        "0000000000000000001507973",
    }
    for link in record.document_links:
        assert {"DOCUMENT_TYPE", "DOCUMENT_NUMBER", "DOCUMENT_PART", "DOCUMENT_VERSION"} <= set(link)


def test_cockpit_master_data_has_no_determination_and_must_not_raise():
    """`PackITPackagingCockpitMasterData` carries a wholly different body
    (LABELDATA, SNR13_TANGO, PLANT_DATA, ...) with no DETERMINATION node at all.
    Every new field is optional precisely so this parses cleanly -- a dependent
    object must never be dropped because it isn't a PackSpec."""
    record = _records_from("URLHierarchy", "thirdURLPayload")[0]

    assert record.message_type == "PackITPackagingCockpitMasterData"
    assert record.snr13 is None
    assert record.identity("ps_group") is None
    assert record.document_links == []
    # Its OBJECTKEY still points at the business object, which is how a
    # dependent object is found from its PS at all.
    assert record.ps_id == "00000000040000588527"
    assert record.seqno == "00001"
    assert record.activation_counter == "2"


def test_identity_reads_across_hops_not_just_the_latest():
    """A Transfer's newest hop is often the one with the least detail: SOLACE
    and pre-consumption hops are attached to every target group (see
    `group_transfers`), so `.latest` can easily be a hop carrying no
    DETERMINATION at all. Identity fields describe the business object, so any
    hop that has one has the same one."""
    record = _records_from("URLHierarchy", "thirdURLPayload")[0]

    assert len(record.hops) > 1
    assert record.ps_id == record.identity("ps_id")


def test_document_link_keys_render_the_same_four_part_dir_key():
    """A link the PS *declares* and a DIR Transfer actually *found* must be
    directly comparable, so both use `_compute_dir_key`'s format."""
    record = _records_from("example1", "payload")[0]

    assert record.document_link_keys == (
        "PAC-0000000000000000001627019-FRE-00",
        "PAC-0000000000000000001507973-ARC-00",
    )


def test_document_link_keys_are_empty_not_absent_when_none_are_declared():
    """An empty tuple is the answer to "does this PS have a DIR?" -- a DIR
    trigger is optional, so declaring none is normal rather than missing
    information. Reported as `()` so the summary layer can state it."""
    record = _records_from("example5", "payload5")[0]

    assert record.document_link_keys == ()
    assert record.document_links == []


def test_dir_resolves_the_ps_it_belongs_to():
    """A DIR's OBJECTKEY is purely the document's own key, so without reading
    its link array a DIR hop knows nothing about its Packaging Specification.

    This is the *authoritative* direction of the PS-DIR edge: a PS's own
    DOCUMENT_LINKS is only a snapshot of what was linked when that PS trigger
    was built, and a document attached afterwards never refreshes it.
    """
    records = _records_from("example9", "payload9")
    by_key = {r.identity("dir_key"): r for r in records}

    linked = by_key["PAC-0000000000000100000182279-000-00"]
    assert linked.identity("ps_id") == "00000000040000603801"


def test_l01_document_links_a_workstep_not_a_ps():
    """Confirmed live 2026-08-07: Document Type discriminates which link array
    a DIR populates -- `PAC` fills OBJECTLINKSPACKITPACKSPEC, `L01` fills
    OBJECTLINKSWORKSTEP instead. So a missing PS on an `L01` is correct
    behaviour, not a parse failure, and must not be reported as a gap.
    """
    records = _records_from("example7", "payload7")

    assert records, "example7 should hold L01 DIR events"
    assert all((r.identity("dir_key") or "").startswith("L01-") for r in records)
    assert all(r.identity("ps_id") is None for r in records)


def test_standalone_cockpit_trigger_names_no_ps():
    """A Packaging Cockpit Master Data trigger can fire on its own, for a pure
    master-data change with no PS activation behind it. Confirmed live: it
    carries an empty PS_ID and SEQNO `00000`.

    This is what stops a master-data change being narrated as PS activity --
    and it means a PS-ID search cannot return this noise, because there is no
    PS ID on it to match.
    """
    records = _records_from("example8", "payload8")

    assert records
    assert all(r.message_type == "PackITPackagingCockpitMasterData" for r in records)
    assert all(not r.identity("ps_id") for r in records)


def test_message_codes_separate_two_errors_that_look_alike():
    """The structured SAP code is the only thing distinguishing a technical
    error from a business one in the payload.

    Both records are ERROR at SAPP870110 on a single Message ID, and both match
    the catalog as "Target Error" -- yet one is retried every few minutes and
    the other once a day. `d:BusinessStatus` says only ERROR for both. The
    code was parsed alongside the message text since the beginning and then
    thrown away, which left free prose as the only thing anything could
    classify on.
    """
    def codes(example: str, payload: str) -> set[str]:
        record = next(
            r for r in _records_from(example, payload)
            if r.target_system == "SAPP870110" and r.message_type == "PackITPackagingSpecification"
        )
        return {code for hop in record.hops for code in hop.message_codes}

    assert codes("example5", "payload5") == {"/RB9X/PD4P_EAI/109"}
    assert codes("example10", "payload10") == {"/RB9X/PD4P_EAI/009"}


def test_message_codes_ignore_the_blank_padding_rows():
    """The Ret_msgs feed carries empty rows (`Type` blank, `Number` 000) that
    are not messages; only `Type == "E"` entries are real."""
    record = next(
        r for r in _records_from("example10", "payload10")
        if r.target_system == "SAPP870110" and r.message_type == "PackITPackagingSpecification"
    )
    for hop in record.hops:
        assert all("/000" not in code for code in hop.message_codes)
