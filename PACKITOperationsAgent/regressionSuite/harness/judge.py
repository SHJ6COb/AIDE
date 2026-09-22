"""Mechanical adjudication of one reply against its expected result set.

Deliberately dumb and fully deterministic: regexes over the reply text, plus
assertions about the SPL the app actually built and how many backend calls it
made. Nothing here asks a model whether an answer "seems right" -- that
judgement is the reviewing agents' job, and it is only trustworthy if it is
arguing with a fixed, reproducible verdict rather than producing one.

A check that passes is not proof the answer is good; a check that fails is
proof something concrete is wrong.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from regressionSuite.scenarios import Query


@dataclass(frozen=True)
class CheckResult:
    kind: str
    expression: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Verdict:
    scenario: str
    query: str
    passed: bool
    checks: list[CheckResult]

    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "query": self.query,
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
        }


def _search(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL) is not None


_WINDOW_RE = re.compile(r"^-(\d+)(m|h|d)$")
_WINDOW_MINUTES = {"m": 1, "h": 60, "d": 1440}


def _same_window(actual: str | None, expected: str) -> bool:
    """Compare windows by duration, not by spelling.

    `-1d` and `-24h` are the same search. The postfix run failed a turn where
    the model supplied `-1d` and the app correctly honoured it, purely because
    the expectation was written as `-24h` -- a false FAIL of exactly the kind
    this suite exists to avoid, and one that would have been read as the
    time-window fix not holding.
    """
    if actual is None:
        return False
    if actual == expected:
        return True
    left, right = _WINDOW_RE.match(actual), _WINDOW_RE.match(expected)
    if not left or not right:
        return False
    return int(left.group(1)) * _WINDOW_MINUTES[left.group(2)] == int(right.group(1)) * _WINDOW_MINUTES[right.group(2)]


def adjudicate(scenario_slug: str, query: Query, reply: str, backend_calls: list[dict]) -> Verdict:
    """Judge one turn. `backend_calls` is this turn's slice of the fake
    backends' request log -- the only reliable evidence of what the app really
    asked for, as opposed to what the prose claims it did."""
    checks: list[CheckResult] = []

    jobs = [c for c in backend_calls if c.get("api") == "splunk.create_job"]
    routing = [c for c in backend_calls if c.get("api") == "routing.query"]
    spl_all = " ".join(job.get("spl", "") for job in jobs)

    for pattern in query.contains_all:
        checks.append(
            CheckResult("contains_all", pattern, _search(pattern, reply), "" if _search(pattern, reply) else "not found in reply")
        )

    for alternatives in query.contains_any:
        hit = any(_search(pattern, reply) for pattern in alternatives)
        checks.append(CheckResult("contains_any", " | ".join(alternatives), hit, "" if hit else "no alternative matched"))

    for pattern in query.absent:
        hit = _search(pattern, reply)
        match = re.search(pattern, reply, re.IGNORECASE | re.DOTALL)
        checks.append(
            CheckResult("absent", pattern, not hit, "" if not hit else f"forbidden match: {match.group(0)[:120]!r}")
        )

    for fragment in query.spl_contains:
        hit = fragment in spl_all
        checks.append(CheckResult("spl_contains", fragment, hit, "" if hit else f"actual SPL: {spl_all[:300]!r}"))

    for fragment in query.spl_absent:
        hit = fragment in spl_all
        checks.append(CheckResult("spl_absent", fragment, not hit, "" if not hit else f"actual SPL: {spl_all[:300]!r}"))

    if query.expect_searches is not None:
        low, high = query.expect_searches
        ok = low <= len(jobs) <= high
        checks.append(
            CheckResult(
                "search_count",
                f"{low}..{high}",
                ok,
                "" if ok else f"observed {len(jobs)} Splunk job(s): {[j.get('spl', '')[:160] for j in jobs]}",
            )
        )

    if query.expect_window is not None and jobs:
        # Deliberately conditional on a search having happened: this check
        # asserts "if you searched, you used the right window". Whether a
        # search should have happened at all is `expect_searches`'s job, and
        # conflating the two would report one defect as two.
        #
        # The first job is the one built from the user's question; any later
        # job in the same turn is the pipeline's own dependent-object or
        # broadened-routing lookup, which inherits the window rather than
        # re-deriving it.
        actual = jobs[0].get("earliest")
        ok = _same_window(actual, query.expect_window)
        checks.append(
            CheckResult(
                "search_window",
                query.expect_window,
                ok,
                "" if ok else f"searched {actual!r} instead -- the user's window was not applied",
            )
        )

    if query.forbid_unsearched_not_found:
        # A negative result is a claim about a search. Asserting one for a PS
        # that never appeared in this turn's SPL is a fabricated search outcome
        # -- quieter than the "Please hold on" promise it replaced in the
        # postfix run, and harder to notice, because "I did not find any
        # records for PS X" reads exactly like a real empty result.
        for ps_id in set(re.findall(r"\b0{6,}\d{8,}\b", reply)):
            if ps_id in spl_all:
                continue
            near = re.search(
                rf"(?:(?:did ?n[o']?t|could ?n[o']?t|no|couldn't) [^.]{{0,60}}\b{ps_id}\b"
                rf"|\b{ps_id}\b[^.]{{0,60}}(?:not found|no records|did ?n[o']?t (?:find|appear)|nothing))",
                reply,
                re.IGNORECASE,
            )
            checks.append(
                CheckResult(
                    "no_unsearched_not_found",
                    ps_id,
                    near is None,
                    "" if near is None else f"claims an empty result for a PS never searched this turn: {near.group(0)[:120]!r}",
                )
            )

    if query.expect_routing_call is not None:
        ok = bool(routing) == query.expect_routing_call
        checks.append(
            CheckResult(
                "routing_call",
                str(query.expect_routing_call),
                ok,
                "" if ok else f"observed {len(routing)} routing call(s)",
            )
        )

    return Verdict(scenario=scenario_slug, query=query.name, passed=all(c.passed for c in checks), checks=checks)
