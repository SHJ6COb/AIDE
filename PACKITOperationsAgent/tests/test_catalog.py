from app.tools.catalog import match_catalog

# Real `description` text (Ret_msgs.Message, newline-joined) recovered by running
# splunkExamples/exampleN/payloadN through splunk_xml_parser.parse_results +
# transform.parse_hop -- not invented text. See docs/components/catalog/TECHNICAL_SPEC.md.

_EXAMPLE1_TEXT = "T141 Bom item status Invalid for material 6000.409.798 in plant 0780"
_EXAMPLE3_TEXT = (
    "Error while saving the Det rule: F00C2G8057BA18740 with RC: 1.001\n"
    "Ref-2: RCPT|F00C2G8057|03.08.2026|8160|0000018740\n"
    "Ref-2: |F00C2G8057BA18740|||\n"
    "Fill out all required entry fields\n"
    "Formatting error in the field KONDP-PACKNR; see next message\n"
    "Fill out all required entry fields\n"
    "Succesfuly changed the PI F00C2G8057BB18740\n"
    "Succesfuly changed the PI F00C2G8057BA18740"
)
_EXAMPLE4_TEXT = "SNR13 not found/ Mark for deletion"
_EXAMPLE6_TEXT = "Cockpit master data dependent object still in progress"


def test_no_match_returns_empty_list():
    assert match_catalog("some completely unrelated error text") == []


def test_empty_or_none_text_returns_empty_list():
    assert match_catalog("") == []
    assert match_catalog(None) == []


def test_single_match_target_error():
    matches = match_catalog(_EXAMPLE1_TEXT)
    assert [m.seq_nr for m in matches] == [15]
    assert matches[0].error_category == "Target Error"
    assert matches[0].responsible == "Plant"


def test_single_match_source_error_dependent_object_blocking():
    matches = match_catalog(_EXAMPLE6_TEXT)
    assert [m.seq_nr for m in matches] == [57]
    assert matches[0].error_category == "Source Error"


def test_loosened_snr13_pattern_matches_real_short_form():
    """Real production text never carries the source PDF's "STATUS EMPTY" /
    "Z0MM_XMARA" scaffolding -- confirmed live, see TECHNICAL_SPEC.md's fixed-
    defect section. Row 2 must match the short real form.
    """
    matches = match_catalog(_EXAMPLE4_TEXT)
    assert [m.seq_nr for m in matches] == [2]
    assert matches[0].responsible == "Plant"


def test_case_insensitive():
    matches = match_catalog(_EXAMPLE4_TEXT.lower())
    assert [m.seq_nr for m in matches] == [2]


def test_dotall_required_for_pattern_spanning_joined_messages():
    """Row 30's pattern spans two Ret_msgs.Message values via `.*` -- only
    matches if `.` crosses the newline that joins them (confirmed live
    necessary, see TECHNICAL_SPEC.md)."""
    text = "Error while saving the Det rule: XYZ\nDo not enter packing instructions twice"
    matches = match_catalog(text)
    assert 30 in [m.seq_nr for m in matches]


def test_multiline_anchors_distinguish_bare_vs_in_plant_variant():
    """Row 11 (bare "doesn't exist") must NOT fire on a line that continues
    with "in plant" (that's row 12's case) -- `^`/`$` anchor per-line under
    MULTILINE against the joined multi-line description, not per-string."""
    bare = "First message\n60000012345 Packaging material doesn't exist\nThird line"
    with_plant = "60000012345 Packaging material doesn't exist in plant 0780"

    bare_matches = {m.seq_nr for m in match_catalog(bare)}
    plant_matches = {m.seq_nr for m in match_catalog(with_plant)}

    assert 11 in bare_matches
    assert 12 not in bare_matches
    assert 12 in plant_matches
    assert 11 not in plant_matches


def test_multiple_real_matches_returned_together_not_first_only():
    """Real example: this text matches both row 31 (the actual diagnostic
    Technical Error) and row 24 (a trailing success-phrase row it happens to
    also contain) -- per the confirmed design (see catalog TECHNICAL_SPEC.md's
    row-21/row-32 conflict), match_catalog returns every actionable match
    instead of picking one, so the human can judge which is relevant.
    """
    matches = match_catalog(_EXAMPLE3_TEXT)
    seq_nrs = {m.seq_nr for m in matches}
    assert 31 in seq_nrs
    assert 24 in seq_nrs
    assert 41 not in seq_nrs  # row 41 requires "MARA / MARM data has been updated..." text, absent here
    assert 30 not in seq_nrs  # row 30 requires "Do not enter packing instructions twice", absent here


def test_informational_category_never_returned():
    """Row 5 ("No action required") has a real, matchable pattern but must
    never be returned -- it was never a candidate fix, just a wait-it-out
    note. See _ACTIONABLE_CATEGORIES."""
    assert match_catalog("the valid from date not reached yet for this record") == []


def test_context_scoped_row_excluded_without_matching_context():
    """Row 34 only applies for RCPT + plant 4100 -- without that context, the
    text should fall through unmatched (no row-9-style generic fallback
    shares this exact pattern text)."""
    text = "Relevant Import Config not maintained for this connection"
    assert match_catalog(text) == []
    assert match_catalog(text, context={"determination_type": "SHIP", "plant": "4100"}) == []


def test_context_scoped_row_matches_with_correct_context():
    text = "Relevant Import Config not maintained for this connection"
    matches = match_catalog(text, context={"determination_type": "RCPT", "plant": "4100"})
    assert [m.seq_nr for m in matches] == [34]


def test_context_scoped_row_fails_closed_when_context_unavailable():
    """Row 7 needs customer_index/sales_channel, which aren't currently
    extracted onto TransferRecord/Hop -- passing a partial context (missing
    those keys entirely) must fail closed, not assume a match."""
    text = "SNR13 NOT FOUND/ STATUS EMPTY/ MARK FOR DELETION - Z0MM_XMARA - P81"
    matches = match_catalog(text, context={"plant": "8160", "determination_type": "ZFER"})
    assert 7 not in {m.seq_nr for m in matches}
    # row 2's more general pattern still catches the same underlying text
    assert 2 in {m.seq_nr for m in matches}
