"""Drive the real app in a real browser, one conversation per scenario, and
write everything a reviewer needs into per-scenario folders.

Usage:
    python -m regressionSuite.run_scenarios                 # every scenario
    python -m regressionSuite.run_scenarios S01 S04         # by slug prefix
    python -m regressionSuite.run_scenarios --headed        # watch it happen

Each scenario gets its own conversation, so follow-up turns exercise the real
persisted history rather than a synthetic one. Output per scenario:

    <run>/<slug>/NN_<query>.txt     query, reply, staged progress, verdict
    <run>/<slug>/shots/NN_*.png     full-page screenshot after each turn
    <run>/<slug>/backend_calls.json the SPL and routing calls that turn caused
    <run>/<slug>/verdicts.json      machine-readable adjudication
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from regressionSuite.harness import judge, serve_under_test  # noqa: E402
from regressionSuite.scenarios import SCENARIOS, Query, Scenario  # noqa: E402

RUNS_DIR = _PROJECT_ROOT / "regressionSuite" / "runs"
REPLY_TIMEOUT_S = 240
PLACEHOLDER = "Ask about a packaging specification's replication status..."


class BackendLog:
    """Tail of the fake backends' request log, sliced per turn."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._consumed = 0

    def take_new(self) -> list[dict]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        fresh = lines[self._consumed :]
        self._consumed = len(lines)
        return [json.loads(line) for line in fresh if line.strip()]


def _wait_for_reply(page, prior_bubbles: int, steps: list[str]) -> str:
    """Block until a new assistant bubble or an error banner appears, sampling
    the staged-progress indicator throughout (it is transient, and which stages
    fire is itself evidence about which pipeline branches ran)."""
    deadline = time.time() + REPLY_TIMEOUT_S
    while time.time() < deadline:
        indicator = page.locator("div.animate-pulse")
        if indicator.count():
            try:
                text = indicator.first.locator("xpath=..").inner_text().strip()
                if text and (not steps or steps[-1] != text):
                    steps.append(text)
            except Exception:
                pass
        bubbles = page.locator("div.markdown")
        if bubbles.count() > prior_bubbles:
            return bubbles.nth(bubbles.count() - 1).inner_text()
        banner = page.locator("div.border-red-200")
        if banner.count():
            return "[ERROR BANNER] " + banner.first.inner_text()
        time.sleep(0.25)
    return f"[TIMEOUT after {REPLY_TIMEOUT_S}s -- no reply]"


def _send(page, text: str) -> tuple[str, list[str], float]:
    prior = page.locator("div.markdown").count()
    box = page.get_by_placeholder(PLACEHOLDER)
    box.click()
    box.fill(text)
    steps: list[str] = []
    started = time.time()
    page.get_by_role("button", name="Send").click()
    reply = _wait_for_reply(page, prior, steps)
    return reply, steps, round(time.time() - started, 1)


def _write_turn(folder: Path, index: int, query: Query, reply: str, steps: list[str], elapsed: float, verdict, calls: list[dict], shot: Path) -> None:
    lines = [
        f"# {index:02d} {query.name}",
        "",
        "## Query (as typed into the app)",
        query.text,
        "",
        "## What this turn probes",
        query.probes,
        "",
        "## Reply (verbatim, as rendered in the browser)",
        reply,
        "",
        "## Observed",
        f"- elapsed: {elapsed}s",
        f"- staged progress: {steps}",
        f"- Splunk jobs: {sum(1 for c in calls if c.get('api') == 'splunk.create_job')}",
        f"- routing-plan calls: {sum(1 for c in calls if c.get('api') == 'routing.query')}",
        f"- screenshot: shots/{shot.name}",
        "",
        f"## Verdict: {'PASS' if verdict.passed else 'FAIL'}",
    ]
    for check in verdict.checks:
        mark = "ok  " if check.passed else "FAIL"
        lines.append(f"- [{mark}] {check.kind}: {check.expression}" + (f"  -- {check.detail}" if check.detail else ""))
    for call in calls:
        if call.get("api") == "splunk.create_job":
            lines += ["", "## SPL actually sent", f"    {call['spl']}", f"    window: {call['earliest']} .. {call['latest']}  ->  {call['matched_count']} rows"]
    (folder / f"{index:02d}_{query.name}.txt").write_text("\n".join(lines), encoding="utf-8")


def run_scenario(page, scenario: Scenario, run_dir: Path, log: BackendLog) -> list:
    folder = run_dir / scenario.slug
    shots = folder / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    (folder / "README.txt").write_text(
        f"{scenario.title}\n\nFixture basis (the frozen facts every expectation here rests on):\n{scenario.fixture_basis}\n",
        encoding="utf-8",
    )

    page.get_by_role("button", name="New conversation").click()
    page.wait_for_timeout(600)
    log.take_new()  # discard anything left over from the previous scenario

    verdicts, all_calls = [], []
    for index, query in enumerate(scenario.queries, start=1):
        reply, steps, elapsed = _send(page, query.text)
        calls = log.take_new()
        shot = shots / f"{index:02d}_{query.name}.png"
        page.screenshot(path=str(shot), full_page=True)

        verdict = judge.adjudicate(scenario.slug, query, reply, calls)
        verdicts.append(verdict)
        all_calls.append({"query": query.name, "calls": calls})
        _write_turn(folder, index, query, reply, steps, elapsed, verdict, calls, shot)

        status = "PASS" if verdict.passed else "FAIL"
        print(f"  [{status}] {scenario.slug}/{query.name}  ({elapsed}s)")
        for failure in verdict.failures():
            print(f"         {failure.kind}: {failure.expression}  -- {failure.detail[:160]}")

    (folder / "verdicts.json").write_text(json.dumps([v.to_dict() for v in verdicts], indent=2), encoding="utf-8")
    (folder / "backend_calls.json").write_text(json.dumps(all_calls, indent=2), encoding="utf-8")
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slugs", nargs="*", help="scenario slug prefixes to run (default: all)")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args()

    selected = [s for s in SCENARIOS if not args.slugs or any(s.slug.startswith(p) for p in args.slugs)]
    if not selected:
        print("no scenarios matched")
        return 2

    run_dir = RUNS_DIR / (args.run_name or datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "requests.jsonl"

    serve_under_test.configure_environment()
    serve_under_test.serve(log_path=log_path)
    serve_under_test.wait_until_ready()
    log = BackendLog(log_path)

    print(f"run dir: {run_dir}")
    all_verdicts = []
    console: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda m: console.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: console.append(f"[pageerror] {e}"))
        page.goto(f"http://127.0.0.1:{serve_under_test.APP_PORT}/", wait_until="networkidle")

        for scenario in selected:
            print(f"\n=== {scenario.slug}: {scenario.title}")
            all_verdicts.extend(run_scenario(page, scenario, run_dir, log))

        browser.close()

    summary = {
        "run": run_dir.name,
        "started": datetime.now().isoformat(),
        "scenarios": len(selected),
        "turns": len(all_verdicts),
        "passed": sum(1 for v in all_verdicts if v.passed),
        "failed": sum(1 for v in all_verdicts if not v.passed),
        "failures": [
            {"scenario": v.scenario, "query": v.query, "checks": [asdict(c) for c in v.failures()]}
            for v in all_verdicts
            if not v.passed
        ],
        "browser_console": console,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{summary['passed']}/{summary['turns']} turns passed. Summary: {run_dir / 'summary.json'}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
