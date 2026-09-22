"""Re-score an existing run against the current expectations, without touching
the app or spending an LLM call.

Two uses. First, when an expectation is corrected, this shows whether the fix
changed the verdict on data already captured — the honest way to tell a real
regression from a regex that was simply too narrow. Second, when a *new* oracle
is added (the baseline run had no check for the time window or for unfulfillable
continuation promises), this proves the new check actually catches the defect on
the run where it was first found by hand.

    python -m regressionSuite.readjudicate runs/baseline
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from regressionSuite.harness import judge  # noqa: E402
from regressionSuite.scenarios import SCENARIOS  # noqa: E402

_REPLY = re.compile(r"## Reply \(verbatim.*?\)\n(.*?)\n\n## Observed", re.DOTALL)


def main() -> int:
    run_dir = _PROJECT_ROOT / "regressionSuite" / (sys.argv[1] if len(sys.argv) > 1 else "runs/baseline")
    if not run_dir.exists():
        print(f"no such run: {run_dir}")
        return 2

    changed, now_pass, now_fail, unchanged = [], 0, 0, 0
    for scenario in SCENARIOS:
        folder = run_dir / scenario.slug
        if not folder.exists():
            continue
        calls_by_query = {c["query"]: c["calls"] for c in json.loads((folder / "backend_calls.json").read_text(encoding="utf-8"))}
        previous = {v["query"]: v["passed"] for v in json.loads((folder / "verdicts.json").read_text(encoding="utf-8"))}

        for index, query in enumerate(scenario.queries, start=1):
            transcript = folder / f"{index:02d}_{query.name}.txt"
            if not transcript.exists():
                continue
            match = _REPLY.search(transcript.read_text(encoding="utf-8"))
            if not match:
                continue
            verdict = judge.adjudicate(scenario.slug, query, match.group(1), calls_by_query.get(query.name, []))
            was, is_now = previous.get(query.name), verdict.passed
            if was == is_now:
                unchanged += 1
                continue
            changed.append((scenario.slug, query.name, was, is_now, verdict))
            if is_now:
                now_pass += 1
            else:
                now_fail += 1

    print(f"re-scored against current expectations: {unchanged} unchanged, {len(changed)} changed\n")
    for slug, name, was, is_now, verdict in changed:
        arrow = "FAIL -> PASS  (was a false FAIL)" if is_now else "PASS -> FAIL  (a defect the old checks missed)"
        print(f"{slug}/{name}: {arrow}")
        for failure in verdict.failures():
            print(f"    {failure.kind}: {failure.expression[:80]}  -- {failure.detail[:120]}")
    print(f"\nfalse FAILs removed: {now_pass}    previously-missed defects now caught: {now_fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
