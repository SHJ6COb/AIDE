from dataclasses import dataclass, field

import pytest

import app.core.harness as harness
from app.agents.packspec_status.pipeline import DependentObjectsView, RoutingCheck, StatusResult
from app.core.domain import SearchParams, TimeRange
from app.core.llm_client import Message, Response, ToolCall
from app.tools.catalog import CatalogMatch
from app.tools.transform import Hop, TransferRecord

_DEFAULT_PARAMS = SearchParams()


def _record(status: str | None, description: str | None, message_type: str = "PackITPackagingSpecification") -> TransferRecord:
    hop = Hop(
        message_id="MSG1",
        message_type=message_type,
        host="SAPP790110_CONSUMING",
        target_system="SAPP790110",
        time="2026-08-04T10:00:00",
        business_status=status,
        description=description,
        ps_id="00000000040000054543",
        dir_key=None,
        plant="0580",
        det_type="SHIP",
        usage="R",
        dependent_ps_links=None,
        envelope="atom",
    )
    return TransferRecord(message_id="MSG1", message_type=message_type, ps_id=hop.ps_id, dir_key=None, target_system="SAPP790110", hops=[hop])


def test_summarize_status_result_sends_a_short_hop_history():
    """A short hop chain is sent hop by hop, not condensed to a count.

    Until 2026-08-07 only `hops_at_target` was sent, so every hop but the
    latest was discarded before the model saw anything -- and "can you provide
    the error logs recorded in those 4 hops?" was answered "I don't have direct
    access to the error logs" while the app held two Business Errors for
    exactly those hops. The count still names the two different retry concepts
    apart (`hops_at_target` is reprocessing at the target, distinct from
    source-side retriggers), it just no longer *replaces* the history.
    """
    record = _record("ERROR", "SNR13 not found/ Mark for deletion")
    result = StatusResult(primary_records=[record], dependent_objects=None, catalog_matches=[])
    summary = harness._summarize_status_result(result, _DEFAULT_PARAMS)

    outcome = summary["found"]["outcomes"][0]
    assert outcome["target_system"] == "SAPP790110"
    assert outcome["status"] == "ERROR"
    assert outcome["hops_at_target"] == 1
    assert outcome["transfers"] == 1
    assert outcome["hops"] == [
        {
            "time": "2026-08-04T10:00:00",
            "host": "SAPP790110_CONSUMING",
            "status": "ERROR",
            "description": "SNR13 not found/ Mark for deletion",
        }
    ]
    assert summary["found"]["message_type"] == "PackITPackagingSpecification"


def test_a_long_retry_chain_sends_only_its_count():
    """S01's 100-attempt chain is why the cap exists: sending each hop would be
    thousands of tokens of near-identical repetition that tells the reader
    nothing the count doesn't."""
    hop = _record("ERROR", "SNR13 not found/ Mark for deletion").hops[0]
    record = TransferRecord(
        message_id="MSG1",
        message_type="PackITPackagingSpecification",
        ps_id=hop.ps_id,
        dir_key=None,
        target_system="SAPP790110",
        hops=[hop] * (harness._MAX_HOPS_SERIALIZED + 1),
    )
    result = StatusResult(primary_records=[record], dependent_objects=None, catalog_matches=[])

    outcome = harness._summarize_status_result(result, _DEFAULT_PARAMS)["found"]["outcomes"][0]

    assert outcome["hops_at_target"] == harness._MAX_HOPS_SERIALIZED + 1
    assert "hops" not in outcome


def test_both_party_fields_reach_the_subject():
    """Determination Type decides which party field is populated: SHIP carries a
    Customer Index, RCPT a Supplier, and the repackaging types neither. Both are
    part of OBJECTKEY, so both must reach the model or "give me the object key"
    is structurally incomplete for one record type or the other.

    Supplier was added on 2026-08-07 and `packindex` was not, which left the
    outbound half of the pair missing until 2026-08-08 -- on five of the seven
    PS captures in this repo."""
    outbound = _record("ERROR", "x")
    object.__setattr__(outbound.hops[0], "packindex", "211")
    object.__setattr__(outbound.hops[0], "supplier", None)

    inbound = _record("ERROR", "x")
    object.__setattr__(inbound.hops[0], "supplier", "0000131512")
    object.__setattr__(inbound.hops[0], "packindex", None)

    def subject_of(record):
        return harness._summarize_status_result(
            StatusResult(primary_records=[record], dependent_objects=None, catalog_matches=[]),
            _DEFAULT_PARAMS,
        )["found"]["subject"]

    assert subject_of(outbound)["ps_customer_index"] == "211"
    assert subject_of(inbound)["ps_supplier"] == "0000131512"


def test_subject_hoists_shared_identity_and_uses_role_qualified_keys():
    """Identity is stated once, not repeated per Transfer, and every key names
    its role. There is deliberately no bare `plant` or `material` key: those
    words each mean two different things in one answer -- the PS's own, and the
    one the error text names -- and conflating them would send an engineer to
    the wrong material at the wrong plant."""
    record = _record("ERROR", "SNR13 not found/ Mark for deletion")
    object.__setattr__(record.hops[0], "snr13", "028100944104Y")
    object.__setattr__(record.hops[0], "seqno", "00001")
    object.__setattr__(record.hops[0], "activation_counter", "2")

    summary = harness._summarize_status_result(
        StatusResult(primary_records=[record, record], dependent_objects=None, catalog_matches=[]),
        _DEFAULT_PARAMS,
    )
    subject = summary["found"]["subject"]

    assert subject["ps_snr13"] == "028100944104Y"
    assert subject["ps_plant"] == "0580"
    assert subject["determination_record_seqno"] == "00001"
    assert subject["activation_counter"] == "2"
    assert "plant" not in subject and "material" not in subject
    # Two identical Transfers collapse to one outcome that says how many.
    assert summary["found"]["outcomes"][0]["transfers"] == 2
    assert summary["found"]["transfer_count"] == 2


def test_a_field_that_differs_across_transfers_is_not_hoisted_as_one_value():
    """The shared/varying split is computed, never assumed -- letting one
    record's value stand for all of them is exactly the cross-attribution this
    shape exists to prevent."""
    first = _record("ERROR", "failed here")
    second = _record("SUCCESS", "fine here")
    object.__setattr__(second.hops[0], "plant", "078W")

    summary = harness._summarize_status_result(
        StatusResult(primary_records=[first, second], dependent_objects=None, catalog_matches=[]),
        _DEFAULT_PARAMS,
    )

    assert summary["found"]["subject"]["ps_plant"] == ["0580", "078W"]
    assert len(summary["found"]["outcomes"]) == 2


def test_dependent_objects_none_means_not_applicable_on_this_target_line():
    """`None` and "populated but empty" are different statements: Dependent
    Object triggers only go to the xOE line, so anywhere else there was never
    anything to find -- as opposed to having looked and found none."""
    result = StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])
    assert harness._summarize_status_result(result, _DEFAULT_PARAMS)["dependent_objects"] is None

    looked = StatusResult(
        primary_records=[],
        dependent_objects=DependentObjectsView(
            document_info_records=[], cockpit_master_data=[], missing_is_anomalous=True
        ),
        catalog_matches=[],
    )
    summarized = harness._summarize_status_result(looked, _DEFAULT_PARAMS)["dependent_objects"]
    assert summarized["missing_dependent_object_is_anomalous"] is True


def test_summarize_status_result_includes_the_actual_window_searched():
    """Regression test: caught live via QA testing -- turn 2 previously had
    no access to what window was searched at all, so it could only say
    generic things like "try widening the window" without a number, which
    technically passed the not-found-acknowledgement check without being
    the honest, specific answer skill.md actually asks for."""
    result = StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])
    summary = harness._summarize_status_result(result, SearchParams(time_range=TimeRange(earliest="-3h", latest="now")))
    assert summary["time_range_searched"] == "the last 3 hours"
    assert "hops" not in str(summary)  # no raw hop payload leaks through


def test_enforce_grounding_passes_through_when_catalog_matches_present():
    result = StatusResult(primary_records=[_record("ERROR", "x")], dependent_objects=None, catalog_matches=[CatalogMatch(2, "Target Error", "Plant", "s", "sol")])
    answer = harness._enforce_grounding("The Plant should create the missing number.", result, _DEFAULT_PARAMS)
    assert answer == "The Plant should create the missing number."


def test_enforce_grounding_overrides_ungrounded_fix_claim():
    result = StatusResult(primary_records=[_record("ERROR", "some unmatched error")], dependent_objects=None, catalog_matches=[])
    answer = harness._enforce_grounding("You should just delete the material and recreate it.", result, _DEFAULT_PARAMS)
    assert answer == harness._GROUNDING_FALLBACK_ANSWER


def test_enforce_grounding_allows_honest_no_fix_answer():
    result = StatusResult(primary_records=[_record("ERROR", "some unmatched error")], dependent_objects=None, catalog_matches=[])
    honest = "I don't have a documented fix for this. Please raise a ticket via mServiceHub."
    assert harness._enforce_grounding(honest, result, _DEFAULT_PARAMS) == honest


def test_enforce_grounding_no_check_when_no_error_at_all():
    result = StatusResult(primary_records=[_record("SUCCESS", "all good")], dependent_objects=None, catalog_matches=[])
    answer = harness._enforce_grounding("Everything looks healthy.", result, _DEFAULT_PARAMS)
    assert answer == "Everything looks healthy."


def test_enforce_grounding_overrides_when_empty_search_answered_as_if_error_found():
    """Regression test: caught live via scripts/adversarial_eval.py's GRD-01
    case -- an empty primary_records list must not be answered with the
    "no documented fix, raise a ticket" phrasing, which implies a record was
    found. That conflates two different honest answers."""
    result = StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])
    answer = harness._enforce_grounding(
        "I don't have a documented fix for this specific error. Please raise a ticket via mServiceHub.",
        result,
        _DEFAULT_PARAMS,
    )
    assert answer == harness._not_found_answer(_DEFAULT_PARAMS)


def test_enforce_grounding_keeps_an_honest_not_found_answer_and_adds_the_widths():
    """The model's own honest wording is kept -- but "want me to widen?" leaves
    the user to invent the window and restate the question. The concrete widths
    are appended in code, because `_has_missing_not_found_acknowledgement`
    short-circuits on the first not-found marker and so never reaches
    `_not_found_answer`, where the offer otherwise lives. Measured: the offer
    appeared in none of those replies."""
    result = StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])
    honest = "I couldn't find any records for that PS ID in the last 15 minutes -- want me to widen the window?"

    answer = harness._enforce_grounding(honest, result, _DEFAULT_PARAMS)

    assert answer.startswith(honest)
    for option in ("last 1 hour", "last 4 hours", "last 24 hours", "last 7 days"):
        assert option in answer


def test_the_widths_are_not_offered_when_the_user_chose_the_window():
    """Only the narrow default earns the offer. A user who asked for 7 days and
    got nothing does not need a menu -- they need the honest not-found."""
    result = StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])
    chosen = SearchParams(ps_id="00000000099999999999", time_range=TimeRange(earliest="-7d"))

    answer = harness._enforce_grounding("I couldn't find any records in the last 7 days.", result, chosen)

    assert "Widen the search to which?" not in answer


def test_the_widths_are_not_offered_twice():
    """`_not_found_answer` already carries the offer on the path where it is
    used, so appending again would duplicate the menu."""
    result = StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])

    answer = harness._enforce_grounding("nothing here", result, _DEFAULT_PARAMS)

    assert answer.count("Widen the search to which?") == 1


def test_not_found_answer_states_the_actual_window_searched():
    """Regression test: caught live via QA testing -- a static "not found"
    message never said what window was searched, so a real PS with real
    data from a week ago got the identical reply as a genuinely nonexistent
    PS ID. The answer must state the concrete window."""
    answer = harness._not_found_answer(SearchParams(time_range=TimeRange(earliest="-15m", latest="now")))
    assert "15 minute" in answer

    answer_wide = harness._not_found_answer(SearchParams(time_range=TimeRange(earliest="-7d", latest="now")))
    assert "7 day" in answer_wide


def test_not_found_answer_adds_generic_routing_caveat_when_no_routing_check_available():
    """Regression test: caught live (2026-08-05) -- skill.md's own prose
    guidance for this scenario got silently discarded by
    `_enforce_grounding`'s marker-list check whenever the LLM phrased it in
    words that didn't happen to match `_NOT_FOUND_MARKERS`. Since
    `_not_found_answer` is what actually reaches the user whenever that
    marker check fails, the caveat must be deterministic here, not just in
    skill.md prose. This is the fallback when routing_check is None (e.g.
    the PS wasn't found anywhere, so there was nothing to check routing
    against -- see pipeline._check_routing_if_target_missing)."""
    with_target = harness._not_found_answer(SearchParams(target_system="SAPP1M0110"))
    assert "SAPP1M0110" in with_target
    assert "Additional Routing" in with_target

    without_target = harness._not_found_answer(_DEFAULT_PARAMS)
    assert "Additional Routing" not in without_target


def test_not_found_answer_states_real_routing_result_when_target_not_configured():
    check = RoutingCheck(
        plant="8150",
        determination_type="SHIP",
        configured_target_systems=("SAPP450110", "SAPP1M0110"),
        requested_target_system="SAPP790110",
        requested_target_was_configured=False,
    )
    answer = harness._not_found_answer(SearchParams(target_system="SAPP790110"), check)
    assert "SAPP790110" in answer
    assert "SAPP450110" in answer and "SAPP1M0110" in answer
    assert "aren't configured to reach" in answer


def test_not_found_answer_states_real_routing_result_when_target_was_configured():
    check = RoutingCheck(
        plant="8150",
        determination_type="SHIP",
        configured_target_systems=("SAPP1M0110",),
        requested_target_system="SAPP1M0110",
        requested_target_was_configured=True,
    )
    answer = harness._not_found_answer(SearchParams(target_system="SAPP1M0110"), check)
    assert "is* configured to receive" in answer
    assert "real transfer issue" in answer


@dataclass
class _FakeConversationStore:
    messages: dict = field(default_factory=dict)

    def get_history(self, conversation_id):
        return list(self.messages.get(conversation_id, []))

    def append_message(self, conversation_id, role, content):
        self.messages.setdefault(conversation_id, []).append(Message(role=role, content=content))


class _FakeLLMClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, messages, tools, *, system_instruction):
        self.calls.append((list(messages), list(tools)))
        return self._responses.pop(0)


def test_run_query_full_flow(monkeypatch):
    canned_result = StatusResult(
        primary_records=[_record("ERROR", "SNR13 not found/ Mark for deletion")],
        dependent_objects=None,
        catalog_matches=[CatalogMatch(2, "Target Error", "Plant", "material missing", "create or delete the DR")],
    )
    monkeypatch.setattr(harness, "get_ps_status", lambda params, config, on_step=None: canned_result)
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "00000000040000054543"})]),
            Response(text="PS 00000000040000054543 failed: material missing. Plant should create or delete the DR.", tool_calls=[]),
        ]
    )
    store = _FakeConversationStore()
    steps = []

    answer = harness.run_query(
        "conv-1", "what's the status of PS 00000000040000054543?",
        config=object(), llm=llm, store=store, on_step=steps.append,
    )

    assert answer.interpreted_params.ps_id == "00000000040000054543"
    assert answer.catalog_matches[0].seq_nr == 2
    assert "material missing" in answer.plain_language_answer
    assert steps == ["Interpreting your question...", "Composing answer..."]
    assert [m.role for m in store.messages["conv-1"]] == ["user", "assistant"]


def test_run_query_skips_search_when_extracted_params_are_completely_empty(monkeypatch):
    """Regression test: caught live via manual scope-boundary testing --
    off-topic questions ("what's the capital of France?", "what's today's
    weather?") led the LLM to still call get_ps_status with every field
    empty, which ran a fully UNSCOPED Splunk query returning arbitrary real
    production records, then presented unrelated real catalog matches as if
    they answered the question. Must never call get_ps_status at all in this
    case, regardless of what the LLM decided."""
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    def _fail_if_called(params, config, on_step=None):
        raise AssertionError("get_ps_status must not be called with fully empty SearchParams")

    monkeypatch.setattr(harness, "get_ps_status", _fail_if_called)

    llm = _FakeLLMClient(
        [Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={})])]
    )
    store = _FakeConversationStore()

    answer = harness.run_query("conv-1", "what is the capital of France?", config=object(), llm=llm, store=store)

    assert answer.primary_records == []
    assert answer.catalog_matches == []
    # The model *tried* to search and produced nothing usable, which is a
    # different situation from a domain question: it gets the deterministic
    # "narrow it down" ask, not a second glossary turn. Routing it to the
    # glossary produced a confident essay about the domain in place of an
    # answer about the data -- caught in the `enriched_full` run at S02/q3.
    assert len(llm.calls) == 1
    assert "narrow it down" in answer.plain_language_answer


def test_run_query_no_tool_call_returns_gracefully(monkeypatch):
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")
    llm = _FakeLLMClient(
        [
            Response(text="(deferring)", tool_calls=[]),
            Response(text="Could you clarify which PS you mean?", tool_calls=[]),
        ]
    )
    store = _FakeConversationStore()

    answer = harness.run_query("conv-1", "what about that thing", config=object(), llm=llm, store=store)

    assert answer.interpreted_params is None
    # The answer comes from the second turn, which has the glossary -- turn 1
    # deliberately does not, so its reply is a deferral rather than an answer.
    assert answer.plain_language_answer == "Could you clarify which PS you mean?"
    assert len(llm.calls) == 2


def test_run_query_never_shows_turn_1_prose_when_the_domain_turn_returns_nothing(monkeypatch):
    """Turn-1 text must never reach a user, even on the one path that used to
    let it.

    The slot held `explained.text or turn1.text or ""`, so an empty domain turn
    surfaced whatever the parsing turn wrote. Turn 1 is told to emit "a single
    short line naming what is being asked about" -- an internal handoff, shown
    as though it were the answer -- and since `_load_skill` stopped sending
    `Tone` to `PARSE`, that prose is written under no user-facing rules at all.
    """
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")
    llm = _FakeLLMClient(
        [
            Response(text="User is asking what a Determination Record is.", tool_calls=[]),
            Response(text="", tool_calls=[]),
        ]
    )

    answer = harness.run_query(
        "conv-1", "what's a Determination Record?", config=object(), llm=llm, store=_FakeConversationStore()
    )

    assert answer.plain_language_answer == harness._EXPLAIN_FALLBACK_ANSWER
    assert "Determination Record is" not in answer.plain_language_answer


def test_tone_reaches_the_turns_that_write_prose_and_not_the_one_that_does_not():
    """`PARSE` emits only tool arguments, so tone guidance cannot change its
    output -- 785 characters per query for nothing. `COMPOSE` and `EXPLAIN`
    write what the user actually reads, and keep it."""
    tone_marker = "Match the user's brevity and formality"

    assert tone_marker not in harness._load_skill(harness.PARSE)
    assert tone_marker in harness._load_skill(harness.COMPOSE)
    assert tone_marker in harness._load_skill(harness.EXPLAIN)


def test_parse_turn_is_not_given_the_glossary():
    """The cost split `_load_skill` exists for: the parsing turn cannot use
    domain knowledge to choose tool arguments, so it does not carry it. This
    is what licenses skill.md's turn-1 rule to *defer* a domain question
    rather than answer one -- the two must stay in step."""
    parse = harness._load_skill(harness.PARSE)

    assert "# Project glossary" not in parse
    assert "# Project glossary" in harness._load_skill(harness.COMPOSE)
    assert len(parse) < len(harness._load_skill(harness.COMPOSE)) / 5


def test_run_query_enforces_grounding_when_llm_ignores_rule(monkeypatch):
    canned_result = StatusResult(primary_records=[_record("ERROR", "some unmatched error")], dependent_objects=None, catalog_matches=[])
    monkeypatch.setattr(harness, "get_ps_status", lambda params, config, on_step=None: canned_result)
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "123456"})]),
            Response(text="Just delete the record and recreate it, that should fix it.", tool_calls=[]),
        ]
    )
    store = _FakeConversationStore()

    answer = harness.run_query("conv-1", "why is this failing?", config=object(), llm=llm, store=store)

    assert answer.plain_language_answer == harness._GROUNDING_FALLBACK_ANSWER


def test_run_query_persists_paired_marker_when_pipeline_fails(monkeypatch):
    """Regression test: caught live via QA testing -- a failed query left
    the user's message orphaned in history with no paired assistant reply
    at all (not even an error record), both in get_history and in the
    /api/issues mailto transcript. A failure must still leave a coherent,
    paired turn behind."""

    class _RaisingLLMClient:
        def generate(self, messages, tools, *, system_instruction):
            raise RuntimeError("simulated LLM failure")

    store = _FakeConversationStore()
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    with pytest.raises(RuntimeError):
        harness.run_query("conv-1", "why is this failing?", config=object(), llm=_RaisingLLMClient(), store=store)

    history = store.messages["conv-1"]
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == harness._QUERY_FAILED_MARKER


def _window_capturing_run(monkeypatch, llm, store, query: str, conversation_id: str = "conv-1") -> str:
    """Run one query and return the `earliest` the pipeline was actually
    handed -- the only evidence of what window the app really searched."""
    searched: list[SearchParams] = []

    def _capture(params, config, on_step=None):
        searched.append(params)
        return StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])

    monkeypatch.setattr(harness, "get_ps_status", _capture)
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")
    harness.run_query(conversation_id, query, config=object(), llm=llm, store=store)
    return searched[0].time_range.earliest


def test_run_query_fills_in_the_window_the_user_stated_when_the_model_omits_it(monkeypatch):
    """Regression test: the `baseline` run's highest-impact defect. The model
    omitted `time_earliest` from the tool call in 11 of 12 controlled trials
    even when the user stated a window in plain English, so the app searched
    its default 15 minutes and answered "not found" about a window the user
    never asked for."""
    for question, expected in (
        ("What's the status of PS 00000000040001253724 in the last 24 hours?", "-24h"),
        ("What's going on with PS 00000000099999999999 in the last 7 days?", "-7d"),
    ):
        llm = _FakeLLMClient(
            [
                Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "00000000040001253724"})]),
                Response(text="I couldn't find any records.", tool_calls=[]),
            ]
        )
        assert _window_capturing_run(monkeypatch, llm, _FakeConversationStore(), question) == expected


def test_run_query_never_overrides_a_window_the_model_did_supply(monkeypatch):
    llm = _FakeLLMClient(
        [
            Response(
                text=None,
                tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "123456", "time_earliest": "-3h"})],
            ),
            Response(text="I couldn't find any records.", tool_calls=[]),
        ]
    )
    assert _window_capturing_run(monkeypatch, llm, _FakeConversationStore(), "anything in the last 7 days?") == "-3h"


def test_run_query_carries_a_window_forward_from_an_earlier_user_turn(monkeypatch):
    """A window the user stated once holds until they change it -- the
    `baseline` run measured the model re-deriving it from prior prose on
    only 2 of 10 window-less follow-ups, so a follow-up about a PS found
    over 24 hours silently collapsed back to 15 minutes and reported it as
    "no records"."""
    store = _FakeConversationStore()
    store.append_message("conv-1", "user", "What happened to PS 00000000040000434427 in the last 24 hours?")
    store.append_message("conv-1", "assistant", "It failed at SAPP720110 and SAPPOE0110.")

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "00000000040000434427"})]),
            Response(text="I couldn't find any records.", tool_calls=[]),
        ]
    )
    assert _window_capturing_run(monkeypatch, llm, store, "Are those two the same error, or different?") == "-24h"


def test_run_query_does_not_let_the_model_swap_a_carried_window_for_an_echoed_one(monkeypatch):
    """The anti-echo gap: a window the user named *once* licensed the model to
    supply any window it liked on every later turn.

    `_user_named_a_period` scans the whole conversation, so after the user says
    "in the last 3 hours" at turn 1 it stays `True` forever -- and the strip
    branch that exists to delete an invented window never runs again. A model
    echoing "in the last 7 days" out of `_not_found_answer`'s own example
    phrase then reaches Splunk unchallenged, which is the exact failure
    `qa_report.txt` recorded and `_window_from_user_messages` was written to
    make impossible.

    The user's own window carries forward instead. The model may still
    introduce one, but only on a turn where the user actually raised time.
    """
    store = _FakeConversationStore()
    store.append_message("conv-1", "user", "Did PS 00000000040001253724 fail in the last 3 hours?")
    store.append_message("conv-1", "assistant", harness._not_found_answer(_DEFAULT_PARAMS))

    llm = _FakeLLMClient(
        [
            Response(
                text=None,
                tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "00000000040001253724", "time_earliest": "-7d"})],
            ),
            Response(text="I couldn't find any records.", tool_calls=[]),
        ]
    )
    assert _window_capturing_run(monkeypatch, llm, store, "What about the other one?") == "-3h"


def test_run_query_takes_the_window_from_a_user_accepting_the_one_the_app_offered(monkeypatch):
    """Regression test: `_not_found_answer` offers 'in the last 7 days' as
    an example, and 0 of 4 controlled trials extracted the window when the
    user took it up ("Try the last 7 days then."). Reading it from the
    *user's* own message honours skill.md's anti-echo rule -- the value
    comes from what the user typed, never from the app's own prose."""
    store = _FakeConversationStore()
    store.append_message("conv-1", "user", "What's the status of PS 00000000040001253724?")
    store.append_message("conv-1", "assistant", harness._not_found_answer(_DEFAULT_PARAMS))

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "00000000040001253724"})]),
            Response(text="I couldn't find any records.", tool_calls=[]),
        ]
    )
    assert _window_capturing_run(monkeypatch, llm, store, "Try the last 7 days then.") == "-7d"


def test_window_is_never_taken_from_assistant_prose():
    """The anti-echo rule in code: `_not_found_answer`'s own example phrase
    ("e.g. \"in the last 7 days\"") is exactly what was once lifted and
    presented as a window the user had asked for."""
    history = [
        Message(role="user", content="What's the status of PS 00000000040001253724?"),
        Message(role="assistant", content=harness._not_found_answer(_DEFAULT_PARAMS)),
        Message(role="user", content="And what plant is it at?"),
    ]
    assert harness._window_from_user_messages(history) is None


def test_enforce_grounding_replaces_a_not_found_answer_that_claims_the_wrong_window():
    """Regression test: the `baseline` run's S05/q2. Handed
    `time_range_searched = "the last 15 minutes"`, the model wrote "I still
    couldn't find any records for PS ..., even when searched in the last 7
    days" -- over 7 days that PS returns 100 rows, so the claim is false.
    It survived because `_has_missing_not_found_acknowledgement` stops
    checking at the first not-found marker ("couldn't find"), leaving the
    rest of the sentence unguarded."""
    result = StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])
    answer = harness._enforce_grounding(
        "I still couldn't find any records for PS 00000000040001253724, even when searched in the last 7 days.",
        result,
        _DEFAULT_PARAMS,
    )
    assert answer == harness._not_found_answer(_DEFAULT_PARAMS)
    assert "15 minutes" in answer


def test_enforce_grounding_corrects_the_false_window_in_place_when_records_were_found():
    """A wrong window phrase is not a reason to throw away an otherwise
    grounded answer -- both strings are known exactly, so correct the one
    that's wrong."""
    result = StatusResult(primary_records=[_record("ERROR", "x")], dependent_objects=None, catalog_matches=[CatalogMatch(2, "Target Error", "Plant", "s", "sol")])
    params = SearchParams(time_range=TimeRange(earliest="-24h", latest="now"))
    answer = harness._enforce_grounding(
        "PS 00000000040001253724 failed at SAPP870110. I searched the last 7 days and found 1 record.",
        result,
        params,
    )
    assert answer == "PS 00000000040001253724 failed at SAPP870110. I searched the last 24 hours and found 1 record."


def test_enforce_grounding_leaves_a_suggested_wider_window_alone():
    """`_not_found_answer` itself suggests "in the last 7 days" as an
    example of a wider window, and the LLM paraphrases that legitimately.
    A suggestion is not a claim about what was searched."""
    result = StatusResult(primary_records=[_record("ERROR", "x")], dependent_objects=None, catalog_matches=[CatalogMatch(2, "Target Error", "Plant", "s", "sol")])
    honest = "I found 1 record in the last 15 minutes. You could try the last 7 days for more history."
    assert harness._enforce_grounding(honest, result, _DEFAULT_PARAMS) == honest
    assert harness._enforce_grounding(harness._not_found_answer(_DEFAULT_PARAMS), result, _DEFAULT_PARAMS) == (
        harness._not_found_answer(_DEFAULT_PARAMS)
    )


def test_enforce_grounding_strips_a_promise_of_a_further_check():
    """Regression test: the `baseline` run's S08, all three turns. Each
    reply ended "I will now check PS 00000000040001399187... Please hold
    on." and across all 28 Splunk jobs in the run that PS was never
    searched. One tool call per question, no continuation (ADR-0001), and
    the UI shows no pending state -- so the promise reads as a pending
    check that silently never happens."""
    result = StatusResult(primary_records=[_record("ERROR", "x")], dependent_objects=None, catalog_matches=[CatalogMatch(2, "Target Error", "Plant", "s", "sol")])
    answer = harness._enforce_grounding(
        "PS 00000000040001253724 is in ERROR with SNR13 not found.\n\n"
        "I will now check PS 00000000040001399187 to complete the comparison. Please hold on.",
        result,
        _DEFAULT_PARAMS,
    )
    assert "hold on" not in answer.lower()
    assert "00000000040001399187" not in answer
    assert "PS 00000000040001253724 is in ERROR with SNR13 not found." in answer
    assert harness._UNFULFILLED_PROMISE_NOTICE in answer


def test_enforce_grounding_leaves_invitations_to_the_user_alone():
    """"Let me know if you need more detail" is not a promise of further
    work by the app -- only first-person commitments are."""
    result = StatusResult(primary_records=[_record("SUCCESS", "all good")], dependent_objects=None, catalog_matches=[])
    honest = "The transfer completed successfully. Let me know if you need more details!"
    assert harness._enforce_grounding(honest, result, _DEFAULT_PARAMS) == honest


def test_run_query_strips_a_promise_from_the_no_search_branch_too(monkeypatch):
    """The branch that never searches at all is where an unfulfillable
    promise is least excusable -- and `_enforce_grounding` doesn't run on
    it, so the guard is applied directly to the composing turn's output."""
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")
    llm = _FakeLLMClient(
        [
            Response(text="(deferring)", tool_calls=[]),
            Response(text="Sure -- I will now check that for you. Please hold on.", tool_calls=[]),
        ]
    )
    store = _FakeConversationStore()

    answer = harness.run_query("conv-1", "show me all the errors", config=object(), llm=llm, store=store)

    assert answer.plain_language_answer == harness._UNFULFILLED_PROMISE_NOTICE


def test_run_query_reraises_the_original_exception(monkeypatch):
    class _RaisingLLMClient:
        def generate(self, messages, tools, *, system_instruction):
            raise ValueError("a specific real failure")

    store = _FakeConversationStore()
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    with pytest.raises(ValueError, match="a specific real failure"):
        harness.run_query("conv-1", "anything", config=object(), llm=_RaisingLLMClient(), store=store)


def test_not_found_answer_distinguishes_a_filtered_empty_result():
    """"No ERROR records" is the answer to "any errors?", not a failure to find
    anything. Caught in the `explain_fix2` regression run (S07/q2): the search
    correctly scoped itself to status=ERROR on a PS whose SUCCESS transfer had
    just been reported, found none, and the generic template told the user to
    double-check a PS ID that was demonstrably fine."""
    from app.core.domain import ReplicationStatus

    filtered = SearchParams(ps_id="00000000040000588527", status=ReplicationStatus.ERROR)
    answer = harness._not_found_answer(filtered)

    assert "No ERROR records" in answer
    assert "double-check the PS ID" not in answer

    # An explicit window that found nothing is still the old wording: the user
    # chose that window, so pointing at the PS ID is the useful next step.
    explicit = SearchParams(ps_id="00000000099999999999", time_range=TimeRange(earliest="-7d"))
    assert "double-check the PS ID" in harness._not_found_answer(explicit)


def test_not_found_on_the_default_window_offers_concrete_widths():
    """No window given means the search ran the deliberately narrow 15-minute
    default, which for live data finds nothing far more often than not. Offer
    the widths outright rather than asking the user to restate the whole
    question -- and offer exactly the forms `bare_window_reply` can read back."""
    from app.core.time_window import bare_window_reply

    answer = harness._not_found_answer(SearchParams(ps_id="00000000099999999999"))

    assert "the last 15 minutes" in answer
    for option in ("last 1 hour", "last 4 hours", "last 24 hours", "last 7 days"):
        assert option in answer
        # Every offered option must round-trip, or the conversation dead-ends
        # on the user's reply.
        assert bare_window_reply(option.removeprefix("last ")) is not None


def test_a_bare_window_reply_is_rewritten_into_the_original_question():
    """The reply to that offer is a fragment -- "24 hours" names no PS. Leaving
    turn 1 to reconstruct the question from history is the reference resolution
    this codebase has repeatedly measured as unreliable, and getting it wrong
    means answering about a different PS. Done in code instead."""
    history = [
        Message(role="user", content="what about the PS 00000000040001398976"),
        Message(role="assistant", content="I couldn't find any records ... Widen the search to which?"),
        Message(role="user", content="24 hours"),
    ]

    resolved = harness._resolve_window_reply(history)

    assert resolved[-1].content == "what about the PS 00000000040001398976 in the last 24 hours"
    assert len(resolved) == len(history)


def test_window_reply_rewrite_leaves_anything_else_alone():
    """Only a message that is *nothing but* a window is rewritten. A question
    that merely contains a duration must not be hijacked."""
    untouched = [Message(role="user", content="why has this been failing for 3 days")]
    assert harness._resolve_window_reply(untouched) == untouched

    # Nothing earlier to attach the window to -- leave it be rather than invent
    # a subject.
    orphan = [Message(role="user", content="24 hours")]
    assert harness._resolve_window_reply(orphan) == orphan


def test_unresolvable_value_asks_instead_of_searching_without_it(monkeypatch):
    """The live failure this exists to prevent.

    "the latest successful transfer to target system P87" had `target_system`
    validated to None, so the `host=` clause vanished, the search covered every
    system, and the answer confidently reported SAPPT00110 -- a system the user
    had not asked about. It also took four minutes, because an unscoped search
    over seven days is a far heavier one.

    Running a search that silently ignores part of the question is never the
    right move; the model cannot know its value was discarded after the call,
    so the decision has to be made here.
    """
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    def _fail_if_called(params, config, on_step=None):
        raise AssertionError("must not search while part of the question is unapplied")

    monkeypatch.setattr(harness, "get_ps_status", _fail_if_called)

    llm = _FakeLLMClient(
        [
            Response(
                text=None,
                tool_calls=[ToolCall(name="get_ps_status", arguments={
                    "ps_id": "00000000040001253724", "plant": "not-a-real-plant-code",
                })],
            )
        ]
    )

    answer = harness.run_query(
        "conv-u", "status of PS 00000000040001253724 at plant not-a-real-plant-code",
        config=object(), llm=llm, store=_FakeConversationStore(), on_step=lambda s: None,
    )

    assert "not-a-real-plant-code" in answer.plain_language_answer
    assert "plant" in answer.plain_language_answer.lower()
    assert answer.primary_records == []


def test_short_target_system_reaches_the_search_as_the_full_id(monkeypatch):
    """P87 must arrive at the pipeline as SAPP870110, not be dropped."""
    seen = {}

    def _capture(params, config, on_step=None):
        seen["target_system"] = params.target_system
        return StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])

    monkeypatch.setattr(harness, "get_ps_status", _capture)
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={
                "target_system": "P87", "message_type": "PackITPackagingSpecification", "status": "SUCCESS",
            })]),
            Response(text="Nothing found.", tool_calls=[]),
        ]
    )

    harness.run_query(
        "conv-p87", "latest successful PackITPackagingSpecification transfer to target system P87",
        config=object(), llm=llm, store=_FakeConversationStore(), on_step=lambda s: None,
    )

    assert seen["target_system"] == "SAPP870110"


def test_model_invented_window_is_dropped_when_the_user_named_no_period(monkeypatch):
    """The documented rule is: search 15 minutes, and if nothing is found,
    *offer* to widen. A model free to invent `-7d` on a question containing no
    time reference bypasses that -- which is why the live P87 question was
    answered over seven days without the offer ever appearing."""
    seen = {}

    def _capture(params, config, on_step=None):
        seen["earliest"] = params.time_range.earliest
        return StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])

    monkeypatch.setattr(harness, "get_ps_status", _capture)
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={
                "target_system": "P87", "message_type": "PackITPackagingSpecification",
                "status": "SUCCESS", "time_earliest": "-7d",
            })]),
            Response(text="Nothing found.", tool_calls=[]),
        ]
    )

    harness.run_query(
        "conv-w", "can you provide the latest successful transfer to target system P87",
        config=object(), llm=llm, store=_FakeConversationStore(), on_step=lambda s: None,
    )

    assert seen["earliest"] == TimeRange.default().earliest


def test_model_window_survives_when_the_user_did_raise_time(monkeypatch):
    """The original reason for trusting a model-supplied window: the user said
    something temporal that `parse_time_window` deliberately declines to guess
    at. That case must keep working."""
    seen = {}

    def _capture(params, config, on_step=None):
        seen["earliest"] = params.time_range.earliest
        return StatusResult(primary_records=[], dependent_objects=None, catalog_matches=[])

    monkeypatch.setattr(harness, "get_ps_status", _capture)
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={
                "ps_id": "00000000040001253724", "time_earliest": "-2d",
            })]),
            Response(text="Nothing found.", tool_calls=[]),
        ]
    )

    harness.run_query(
        "conv-m", "what happened to PS 00000000040001253724 since this morning?",
        config=object(), llm=llm, store=_FakeConversationStore(), on_step=lambda s: None,
    )

    assert seen["earliest"] == "-2d"


def test_errors_overtaken_by_a_success_are_labelled_resolved():
    """Sending the hop history is what made stale advice reachable.

    On the first Gemini run of S14 the app answered a question about six
    historical failures with "Suggested Action: Extend material 6099.801.262 to
    plant 5550" -- for a Transfer whose seventh attempt had already succeeded.
    The advice was also ungrounded: `catalog_matches` was empty, because catalog
    matching runs on the *latest* description, which is a success. Leaving the
    reader to infer "resolved" from hop ordering was not enough.
    """
    hop_error = _record("ERROR", "6099.801.262 Packaging material doesn't exist in plant 5550").hops[0]
    hop_ok = _record("SUCCESS", "Succesfuly created the PI F00SC01107FB131512").hops[0]
    record = TransferRecord(
        message_id="MSG1",
        message_type="PackITPackagingSpecification",
        ps_id=hop_error.ps_id,
        dir_key=None,
        target_system="SAPP790110",
        hops=[hop_error, hop_error, hop_ok],
    )
    result = StatusResult(primary_records=[record], dependent_objects=None, catalog_matches=[])

    outcome = harness._summarize_status_result(result, _DEFAULT_PARAMS)["found"]["outcomes"][0]

    assert outcome["status"] == "SUCCESS"
    assert outcome["earlier_errors_resolved"] == 2


def test_a_still_failing_transfer_is_not_labelled_resolved():
    """The flag must mean what it says -- a Transfer that is still in ERROR has
    resolved nothing, and remediation there is exactly what is wanted."""
    record = _record("ERROR", "SNR13 not found/ Mark for deletion")
    result = StatusResult(primary_records=[record], dependent_objects=None, catalog_matches=[])

    outcome = harness._summarize_status_result(result, _DEFAULT_PARAMS)["found"]["outcomes"][0]

    assert "earlier_errors_resolved" not in outcome


def _resolved_result() -> StatusResult:
    """Six failures then a success -- current_status SUCCESS, so
    `_has_ungrounded_fix_claim` does not fire."""
    hop_error = _record("ERROR", "6099.801.262 Packaging material doesn't exist in plant 5550").hops[0]
    hop_ok = _record("SUCCESS", "Succesfuly created the PI F00SC01107FB131512").hops[0]
    record = TransferRecord(
        message_id="MSG1", message_type="PackITPackagingSpecification", ps_id=hop_error.ps_id,
        dir_key=None, target_system="SAPP870110", hops=[hop_error, hop_ok],
    )
    return StatusResult(primary_records=[record], dependent_objects=None, catalog_matches=[])


def test_remediation_for_an_already_resolved_error_is_removed():
    """Measured twice on live S14 runs: the model answered a question about
    historical failures with "Solution: Extend packaging material 6099.801.262
    to plant 5550" -- for a problem the next attempt had already resolved, with
    no catalog match behind it, formatted exactly like a documented answer.

    A skill.md rule and a payload flag were both ignored, so this is enforced
    here instead."""
    answer = (
        "Here are the error logs for SAPP870110:\n\n"
        "2 Aug 2026: 6099.801.262 Packaging material doesn't exist in plant 5550\n"
        "3 Aug 2026: 6099.801.262 Packaging material doesn't exist in plant 5550\n"
        "Cause & Suggested Action\n"
        "Cause: The plant view has not been created in plant 5550.\n"
        "Solution: Extend packaging material 6099.801.262 to plant 5550."
    )

    cleaned = harness._enforce_grounding(answer, _resolved_result(), _DEFAULT_PARAMS)

    assert "Extend packaging material" not in cleaned
    assert "Suggested Action" not in cleaned
    # The part that answered the question survives intact.
    assert "6099.801.262 Packaging material doesn't exist in plant 5550" in cleaned
    assert "2 Aug 2026" in cleaned and "3 Aug 2026" in cleaned
    assert "nothing outstanding to fix" in cleaned


def test_a_documented_fix_is_left_alone():
    """When the catalog *does* back the advice, it is the answer -- stripping
    it would be the opposite failure."""
    hop_error = _record("ERROR", "SNR13 not found/ Mark for deletion").hops[0]
    hop_ok = _record("SUCCESS", "created").hops[0]
    record = TransferRecord(
        message_id="MSG1", message_type="PackITPackagingSpecification", ps_id=hop_error.ps_id,
        dir_key=None, target_system="SAPP870110", hops=[hop_error, hop_ok],
    )
    result = StatusResult(
        primary_records=[record], dependent_objects=None,
        catalog_matches=[CatalogMatch(2, "Target Error", "Plant", "summary", "Create the missing number.")],
    )

    answer = "It failed once then succeeded.\nSuggested Action: Create the missing number."
    assert harness._enforce_grounding(answer, result, _DEFAULT_PARAMS) == answer


def test_an_answer_with_no_remediation_block_is_untouched():
    answer = "It failed twice with 6099.801.262 on 2 and 3 Aug, then succeeded on 4 Aug."
    assert harness._enforce_grounding(answer, _resolved_result(), _DEFAULT_PARAMS) == answer
