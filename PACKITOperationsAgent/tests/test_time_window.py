from app.core.domain import TimeRange, parse_search_params
from app.core.time_window import find_time_windows, parse_time_window


def test_parses_the_exact_phrasings_that_failed_in_the_baseline_regression_run():
    """Regression test: these are the literal messages the `baseline` run
    typed into the app. The model omitted `time_earliest` for all of them
    (11 of 12 controlled trials), so the app searched its default 15 minutes
    and reported "not found" about a window nobody asked for."""
    assert parse_time_window("What's the status of PS 00000000040001253724 in the last 24 hours?") == "-24h"
    assert parse_time_window("What's going on with PS 00000000099999999999 in the last 7 days?") == "-7d"
    assert parse_time_window("Try the last 7 days then.") == "-7d"
    assert parse_time_window("Show me failed transfers to SAPP870110 in the last 24 hours.") == "-24h"


def test_parses_the_documented_phrasings_and_the_general_form():
    assert parse_time_window("anything in the past day?") == "-24h"
    assert parse_time_window("what happened today?") == "-24h"
    assert parse_time_window("errors in the past week") == "-7d"
    assert parse_time_window("errors this week") == "-7d"
    assert parse_time_window("check the last 3 hours") == "-3h"
    assert parse_time_window("check the last 30 minutes") == "-30m"
    assert parse_time_window("over the last 45 mins") == "-45m"
    assert parse_time_window("in the previous 6 days") == "-6d"
    assert parse_time_window("the last hour") == "-1h"


def test_months_and_years_are_converted_to_days_never_to_splunk_minutes():
    """The sharpest trap in this module: Splunk's relative-time `m` is
    *minutes*, so a generic "number + unit initial" mapping would turn "the
    last 3 months" into a three-MINUTE search -- the very defect this parser
    exists to fix, reintroduced by the fix and invisible in a test that only
    checks a value came back."""
    assert parse_time_window("in the last 3 months") == "-90d"
    assert parse_time_window("in the last month") == "-30d"
    assert parse_time_window("in the last 2 weeks") == "-14d"
    assert parse_time_window("in the last year") == "-365d"
    for phrase in ("in the last 3 months", "in the last month", "in the last year"):
        assert not parse_time_window(phrase).endswith("m"), phrase


def test_out_of_range_windows_still_go_through_the_max_days_cap():
    """Emitted as a raw `time_earliest`, never as a constructed TimeRange,
    so `_validate_time_range`'s 30-day cap still applies to it."""
    assert parse_search_params({"time_earliest": parse_time_window("in the last 3 months")}).time_range == TimeRange(
        earliest="-30d", latest="now"
    )


def test_returns_none_when_no_window_is_stated():
    assert parse_time_window("What's the status of PS 00000000040001253724?") is None
    assert parse_time_window("Which plant and determination type is it in?") is None
    assert parse_time_window("How many processing attempts were there for that one?") is None


def test_returns_none_rather_than_guessing_at_anything_unclear():
    """Conservative by design -- a wrong window is the defect, and the
    default is at least stated back to the user by `_not_found_answer`."""
    assert parse_time_window("what failed yesterday?") is None
    assert parse_time_window("anything since Tuesday?") is None
    assert parse_time_window("show me the last 200 records") is None  # a count, not a window
    assert parse_time_window("how many attempts in the last 3 retries?") is None


def test_returns_none_when_one_message_names_two_different_windows():
    assert parse_time_window("not the last hour -- try the last 7 days") is None
    assert parse_time_window("the last 7 days, or the last 7 days again") == "-7d"  # same value twice is unambiguous


def test_find_time_windows_reports_spans_for_in_place_correction():
    mentions = find_time_windows("even when searched in the last 7 days.")
    assert [(m.text, m.earliest) for m in mentions] == [("the last 7 days", "-7d")]
    text = "even when searched in the last 7 days."
    mention = mentions[0]
    assert text[: mention.start] + "the last 15 minutes" + text[mention.end :] == (
        "even when searched in the last 15 minutes."
    )


def test_latest_and_most_recent_are_not_time_periods():
    """They order results; they do not bound them.

    This is the distinction that protects the documented default. "the latest
    successful transfer to target system P87" names no period, so the search
    must run over the default 15 minutes and *offer* to widen -- rather than
    letting the model invent `-7d` and answer a week's worth without ever
    asking, which is what happened live.
    """
    from app.core.time_window import mentions_a_time_period

    assert not mentions_a_time_period("can you provide the latest successful transfer to target system P87")
    assert not mentions_a_time_period("what is the most recent trigger for this PS")
    assert not mentions_a_time_period("status of PS 00000000040001253724")


def test_a_loosely_stated_period_still_counts():
    """`parse_time_window` deliberately refuses to guess at these, but the
    user did raise time -- so a model-supplied window stays trusted here,
    which was the original reason for honouring it."""
    from app.core.time_window import mentions_a_time_period, parse_time_window

    for text in ("what about PS 123 since this morning", "anything over the weekend", "errors from yesterday"):
        assert mentions_a_time_period(text), text
        assert parse_time_window(text) is None, text
