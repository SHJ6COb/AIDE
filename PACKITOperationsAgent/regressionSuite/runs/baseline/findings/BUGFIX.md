# BUGFIX — what was changed, and what the re-run shows

Scope: the four product defects assigned from `ORCHESTRATOR-EXPERIMENTS.md`
and `CRITIC.md` (P5, P3, P1, P4 in the critic's numbering). No suite code,
scenario or expectation was touched — the suite was only re-run, into
`regressionSuite/runs/postfix/`.

**Headline:** `python -m pytest` → **190 passed**, no pre-existing failures.
Regression run → **22/28 turns passed** (baseline 15/28, on since-corrected
expectations). Splunk windows across the 28 jobs:

| run | `-15m` | `-24h` | `-7d` | `-1d` | jobs returning 0 rows |
|---|---|---|---|---|---|
| baseline | 17 | 11 | 0 | 0 | 20 / 28 |
| postfix | **1** | 22 | 4 | 1 | **11 / 28** |

The single `-15m` is S05/q1, the one turn where the user names no window and
`-15m` is correct. `search_window` checks: **19 of 20 pass** (see D1 below
for the twentieth).

---

## D1 — the app searched a window the user did not ask for

**Changed**

- New `app/core/time_window.py`: `parse_time_window(text)` and
  `find_time_windows(text)`. Recognises "last/past/previous N
  minutes|hours|days|weeks|months|years", the singular forms ("the last
  hour", "past week", "this week"), and "today". Returns `None` — never a
  guess — for anything else ("yesterday", "since Tuesday", "the last 200
  records"), and for a message naming two different windows.
- `harness._window_from_user_messages(history)`: most recent **user**
  message first, assistant prose never read. This is skill.md's anti-echo
  rule expressed in code (the rule exists because a window was once lifted
  from an example phrase in `_not_found_answer`'s own text), while still
  letting a window carry forward, including when the user accepts one the
  app offered ("Try the last 7 days then." is the *user* stating a window).
- `harness._run_query_body`: only when the raw
  `turn1.tool_calls[0].arguments` has no `time_earliest` is the parsed
  value injected — as a raw argument, **before** `parse_search_params`, so
  Tier 1 validation and the `TimeRange.MAX_DAYS` cap still apply. A value
  the model did supply is never overridden.
- `_validate_time_range` was **not** touched: the experiments show it
  dropped a supplied value 0 times in 12 trials.

**The `m` trap** (flagged by the critic, and real). Splunk's relative-time
`m` is *minutes*. A generic "number + unit initial" rule turns "the last 3
months" into a **three-minute** search — this defect, reintroduced by its
own fix, and green in any test that only asserts a value came back. Every
unit coarser than an hour is therefore converted to days
(`weeks×7`, `months×30`, `years×365`) and capped downstream at 30 days.
Covered by `test_months_and_years_are_converted_to_days_never_to_splunk_minutes`
and `test_out_of_range_windows_still_go_through_the_max_days_cap`.

**Before / after**

| turn | baseline | postfix |
|---|---|---|
| S01/q1 "in the last 24 hours" | `-15m`, 0 rows, FAIL (SNR13, SAPP870110, "error" all missing) | `-24h`, 100 rows, PASS |
| S01/q2 follow-up, no window named | `-15m`, 0 rows, FAIL (`\b(100\|99)\b`) | `-24h`, 100 rows, PASS — "there were a total of 100 processing attempts" |
| S05/q2 "Try the last 7 days then." | `-15m`, 0 rows, FAIL | `-7d`, 100 rows, PASS |
| S06/q3 "in the last 24 hours" | `-15m`, 0 rows, FAIL | `-24h`, 100 rows, PASS |
| S09/q1 "in the last 7 days" | `-15m`, FAIL (`7 days`) | `-7d`, PASS |
| S05/q1 no window named | `-15m` | `-15m` (unchanged — correct) |

**The one `search_window` FAIL, and it is not a wrong search.** S10/q1
searched `-1d`, because the model *did* supply `time_earliest` this time and
supplied `-1d`. `-1d` and `-24h` are the same 24 hours; the search returned
the correct 1 row and the answer is right. The judge compares the string, so
it reports FAIL. Per instruction the parser never overrides a model-supplied
value, so this is the intended precedence, not a defect. (The critic's
suggested precedence — parser wins over the model when both fire — would
also normalise this; it was not adopted because the task specified
"never override a value the model did supply". Flagging the divergence
rather than silently choosing.)

**Known trade-off.** The scan back through user messages is unbounded, so a
window stated at turn 1 holds for the whole conversation unless the user
names another. That is deliberate for windows (widening never fabricates,
and the cap still applies) but is *not* the same rule skill.md sets for
entity references, which must not reach back more than 1-2 turns. The
inherited window is disclosed by `_not_found_answer` via `describe()` on
empty results; on non-empty results disclosure is still left to the model.

## D2 — the answer claimed a window that was not searched

**Changed** — `harness._claimed_time_windows` / `_correct_stated_time_window`,
wired into `_enforce_grounding` in the same shape as the existing checks. A
window phrase in the answer that disagrees with `params.time_range.earliest`
is treated as a claim only when a past-tense search cue precedes it
("searched", "found", "no records"…) and no suggestion cue does ("try",
"wider", "e.g."…) — `_not_found_answer` itself ends by *suggesting* "in the
last 7 days", and the model legitimately paraphrases that. Cues are matched
on word boundaries: as substrings, "could" inside **could**n't and "try"
inside re**try** both suppressed the real S05/q2 claim (found while writing
the test, not in review).

When the claim is present: empty result set → `_not_found_answer` (which
states the true window and what to do next); non-empty → the false phrase is
replaced in place with `params.time_range.describe()`, leaving the rest of
an otherwise-grounded answer intact.

This is deliberately independent of `_has_missing_not_found_acknowledgement`,
which returns `False` at the first not-found marker and leaves everything
after it unguarded — the mechanism by which "I still couldn't find any
records …, **even when searched in the last 7 days**" reached the user in
S05/q2 while `time_range_searched` said 15 minutes.

**Evidence.** As predicted, D1 *masks* this in the regression run: S05/q2 now
searches `-7d`, so the claim it made in baseline is no longer false and the
check has nothing to fire on. The fix is verified by unit test against the
verbatim baseline sentence
(`test_enforce_grounding_replaces_a_not_found_answer_that_claims_the_wrong_window`),
plus the in-place correction and the two false-positive cases
(a suggested wider window, and `_not_found_answer`'s own text, both left
byte-identical).

## D3 — the routing fallback bypassed the scope guard

**Changed**

- `is_underspecified` (with `_SELF_SUFFICIENT_FIELDS` / `_IDENTIFYING_FIELDS`)
  moved verbatim from `harness.py` to `app/core/domain.py`, next to
  `SearchParams`; `harness` imports `pipeline`, so the pipeline could not
  import it back without a cycle. Behaviour and docstring unchanged, with one
  added paragraph saying why it lives there now. Call sites updated; its
  seven tests moved from `test_harness.py` to `test_domain.py`.
- `pipeline._check_routing_if_target_missing` now re-checks the broadened
  parameters and fails closed (`return None`) before any search runs, exactly
  like its other three fail-closed branches. `_not_found_answer` then gives
  the honest "isn't something I can check here" caveat.

**Evidence.** Direct unit test with S06/q3's real params
(`target_system=SAPP870110`, `status=ERROR`): `_run_search` is monkeypatched
to raise if called, and it is not called. The companion test proves the
PS-ID-scoped S04 routing path is untouched, and in the postfix run S04/q1
still issues its 2 jobs + 1 routing call and PASSes. No unscoped
`<d:BusinessStatus>ERROR</d:BusinessStatus>` sweep appears anywhere in
`runs/postfix/requests.jsonl` (the only `BusinessStatus` query without a
host filter carries a PS ID).

Note the run can no longer reach this path at all: with D1 fixed, S06/q3
finds records at `-24h`, so the broadening never fires — which is why the
guard is proven by unit test rather than by the run, and why it had to land
with D1 rather than after it.

**P7 (out of scope) is not made harder.** The discarded `broader_records`
behaviour is untouched. The one interaction: when the broadened search is
underspecified there are now no `broader_records` to surface — but that
search must not run at all, so a future P7 fix simply has nothing to reuse
on that branch, and everything to reuse on the S04 branch where it fires.

## D4 — the product promised work it structurally cannot do

**Changed**

- `skill.md`, Turn 2: an explicit rule that there is exactly one search per
  question and it has already happened — never promise a further check, a
  continuation or "hold on"; answer with what this turn returned and say
  plainly that the rest needs a separate question.
- `harness._strip_continuation_promise`, applied at the end of
  `_enforce_grounding` **and** on the no-search branch (where a promise is
  even less fulfillable, and `_enforce_grounding` never runs — see P6). It
  drops only the offending sentence, preserving paragraph breaks, and appends
  a fixed notice. The pattern matches first-person commitments to future work
  only (`i will now check`, `i still need to check`, `now checking`,
  `hold on`) — "Let me know if you need more details!" and
  `_not_found_answer`'s "Try asking again with a wider window" are left
  alone, per the critic's warning; both are covered by tests.

**Evidence, and the honest caveat.** In the postfix run all three S08 turns
are free of promises and PASS, and `399187` is still absent from all 28 jobs
— but that is the *prompt* half working: the code guard never fired, since
no reply contained a promise to strip (the notice text appears nowhere in
`runs/postfix/`). This run therefore does not demonstrate the guard in
production; it demonstrates that the model complied this time. The guard
itself is proven by unit test against the verbatim baseline sentence
("I will now check PS 00000000040001399187 … Please hold on."), which is
precisely why a prompt-only fix was not accepted: the D1 evidence is that
model compliance in this app is not stable across runs.

S08's replies are better but still not fully honest — q1/q2 say "no results
were found for PS …399187" when that PS was never searched. That is inside
P4's family but is a *coverage disclosure* problem
(`_summarize_status_result` carries no "requested vs searched" signal), which
the critic scoped as the architectural half; it was not in this work item.

---

## Not fixed, and not attempted (unchanged from baseline)

- **P6** — the no-search branch still returns model prose with no grounding
  check. It took **8** turns in postfix (6 in baseline): S03/q2, S03/q3 and
  S04/q2 newly join it because the previous turn's answer now contains the
  real data, so the model answers from prose instead of calling the tool.
  S01/q4 is the clearest harm and is unchanged: 0 searches, and "There is no
  documented fix" about an error that *is* catalog row 2.
- **P7, P9, P10, P11, P12** — untouched.
- **Hallucinated plant** — S08/q3 says PS …253724 "is associated with plant
  0780" (ground truth 0110, and the plant never reaches the model). It PASSes
  because the `absent` list names `0110`/`0500`, not another PS's plant.
- The `| head 200` / `max_pages=1` truncation the coordinator is tracking did
  **not** surface here: S01 reported 100 hops against 100 rows, and no
  postfix job hit the 200 cap.

## Postfix failures, judged

| turn | check | judgement |
|---|---|---|
| S10/q1 | `search_window -24h` | app searched `-1d` — the same 24 hours, supplied by the model. Correct search, string-equality FAIL. See D1 |
| S02/q2 | `\b48\b` | window is now right (49 rows at `-24h`); the model answered "15". Model arithmetic over data it was given = P10, not a window defect. Was also FAIL in baseline, for the other reason |
| S03/q2 | `078W` | no-tool-call branch (0 jobs), answered from prior prose = P6 |
| S01/q4 | `create \| missing` | no-tool-call branch (0 jobs) = P6, the critic's headline instance |
| S06/q2 | `narrow \| more specific \| …` | search correctly blocked (0 jobs); the model refused as *off-topic* rather than *too broad*. Wording-level, no code path of mine involved — nothing was stripped (the notice is absent) |
| S10/q2 | `mservicehub \| catalog \| can't \| …` | app refused correctly and named no transaction code; reply says "I can only assist…" / "I don't have the ability", which the alternation does not cover. Wording-level |

Both S06/q2 and S10/q2 passed in baseline and fail on wording here; they are
model variance on turns that behaved correctly, not regressions in the code.

## Files changed

```
app/core/time_window.py                      new — the parser (D1)
app/core/harness.py                          D1 wiring, D2 checks, D4 guard, is_underspecified import
app/core/domain.py                           is_underspecified moved here (D3)
app/agents/packspec_status/pipeline.py       re-check on broadened params (D3)
app/agents/packspec_status/skill.md          one-search-per-question rule (D4)
docs/QUERY_FLOW.md                           kept accurate for all four
tests/test_time_window.py                    new — 8 parser tests
tests/test_harness.py                        +11 tests (D1 wiring, D2, D4); 7 moved out
tests/test_domain.py                         +7 moved tests
tests/test_pipeline.py                       +2 tests (D3)
```
