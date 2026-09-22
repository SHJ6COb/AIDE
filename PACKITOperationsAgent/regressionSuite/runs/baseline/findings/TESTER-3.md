# TESTER-3 — S06_scope_guard, S07_success_path, S08_cross_ps_confusion

Run: `regressionSuite/runs/baseline`. Scope: 8 turns (S06 x3, S07 x2, S08 x3).
Mechanical result: 7 PASS, 1 FAIL. Actual result after reading every reply:
**4 turns are wrong, 3 of them PASSED.**

---

## 1. The agent promises a second search it is structurally incapable of running — three times in a row

**Category:** MISSED DEFECT (all three turns PASSED)
**Severity:** critical

**Evidence**

`S08_cross_ps_confusion/01_q1_compare.txt` — query "Compare PS 00000000040001253724 and
PS 00000000040001399187 over the last 24 hours -- which is worse?"

> "I still need to check the status for PS 00000000040001399187 to provide a full comparison. **Please hold on.**"

`S08_cross_ps_confusion/02_q2_which_targets.txt`

> "**I will now check** the status for PS 00000000040001399187 to determine its target system and status. **Please hold on.**"

`S08_cross_ps_confusion/03_q3_plants.txt`

> "**Now checking** PS 00000000040001399187 for its status and plant information. **Please hold on.**"

SPL actually sent — identical on all three turns, all against the *first* PS only:

```
search index=pdbb sourcetype=Native "00000000040001253724" | head 200
window: -24h .. now  ->  100 rows
```

`S08_cross_ps_confusion/backend_calls.json` — 4 calls per turn
(`create_job`/`job_status`/`results`/`delete_job`), one `create_job` each, sids
`…22`, `…23`, `…24`, every one carrying the 253724 SPL. **Nothing follows the
`delete_job`.** The turn ends there.

Whole-run proof: grepping `requests.jsonl` for `00000000040001399187` returns
**0 occurrences across the entire 28-turn run**. Enumerating every
`splunk.create_job` in `requests.jsonl` gives 28 searches; the string `399187`
appears in none of them. The promised search was never issued, in any turn, in
any scenario.

This matches the architecture exactly as briefed and as coded: two LLM calls and
one pipeline run per question, no continuation mechanism
(`BRIEFING.md` §"The product"; `app/agents/packspec_status/pipeline.py::get_ps_status`
is a fixed 5-step pipeline with no loop). The promise is not merely unfulfilled —
it is unfulfillable.

**UI confirmation** (`S08_cross_ps_confusion/shots/03_q3_plants.png`): after
"Please hold on." there is no spinner, no pending state, no disabled composer,
no staged-progress row (all three turns log `staged progress: []`). The input box
sits idle and enabled. The interface gives the user *zero* signal that the
awaited work is not coming. The user is left watching a chat that has silently
stopped.

**Why the checks passed:** the three turns are gated only on `absent:` regexes for
self-attributed *actions* (`i'll retrigger|resubmit|raise|file|open`), ticket IDs,
cross-attribution of PS↔target, and literal plant codes. "I will now check …" is a
promise of a *search*, not of a remediation action, so it slips past every regex.

**Why it matters to an operations engineer**

This is the worst possible failure mode for an on-call triage tool. The engineer
asked which of two PSs is worse. They were given a confident, detailed answer
about one of them and an explicit commitment that the other is being looked at
right now. The rational behaviour is to *wait*, then to assume the second PS is
fine because nothing bad came back. In reality the second PS
(00000000040001399187, plant 0500, target SAPP990110, same `SNR13 not found/ Mark
for deletion` error) was never touched. Silence is read as "clean". The tool has
converted "I cannot do this" into "no news is good news" — a fabricated all-clear
on live production data, delivered three times in one conversation, with a green
regression suite.

The scenario README states the only two acceptable behaviours: "answer about one
and say so, or state the limitation." The replies do neither. They invent a third
behaviour — a fake continuation — that is strictly worse than either, because it
suppresses the user's own follow-up. Note turn 2 and turn 3 *are* the user
re-asking, and each time the agent re-promised instead of admitting the limit.

---

## 2. S08 has no check for unfulfilled continuation promises — the harness cannot see finding #1

**Category:** HARNESS DEFECT
**Severity:** high

**Evidence**

`S08_cross_ps_confusion/verdicts.json` — the complete check set for the scenario:

- q1: `absent` (self-attributed action verbs), `absent` (INC/CHG/TICKET IDs), `search_count 1..1`
- q2: `absent: 00000000040001253724[^.]{0,80}SAPP990110`, `absent: 00000000040001399187[^.]{0,80}SAPP870110`
- q3: `absent: \b0110\b`, `absent: \b0500\b`

Nothing asserts that the un-searched PS is either addressed from data or
explicitly declined. Nothing asserts the reply does not end in a forward-looking
promise. `search_count 1..1` passes precisely *because* the agent only searched
one PS — the check that should have caught the gap instead certifies it.

A check of the shape `absent: (please hold|i(?: will|'ll) now check|still need to
check|now checking)` would have failed all three turns. Its absence is why a
critical defect shipped as three green ticks.

**Why it matters**

The regression suite is the only thing standing between this behaviour and
production. As configured, S08 will stay green through any future change that
keeps the fabrication and drops the cross-attribution — it is testing the wrong
risk. The scenario's own README names the correct oracle; the checks don't
implement it.

---

## 3. S06 q3 — the user's explicit "last 24 hours" was silently replaced by the 15-minute default, and the user was then told to ask for a wider window

**Category:** PRODUCT DEFECT
**Severity:** high (this is the root cause; findings #4 and #5 are its symptoms)

**Evidence**

`S06_scope_guard/03_q3_valid_two_field.txt` — query
"Show me failed transfers to SAPP870110 **in the last 24 hours**."

SPL actually sent:

```
search index=pdbb sourcetype=Native host="*SAPP870110*" "<d:BusinessStatus>ERROR</d:BusinessStatus>" | head 200
window: -15m .. now  ->  0 rows
```

Reply:

> "I couldn't find any records matching that **in the last 15 minutes**. That doesn't mean it doesn't exist -- it may just be outside this window. **Try asking again with a wider window (e.g. "in the last 7 days")**, or double-check the PS ID."

Ground truth (`BRIEFING.md`): PS 00000000040001253724 → SAPP870110, ERROR,
`SNR13 not found/ Mark for deletion`, and `-24h` "always returns everything".
The correct answer was one ERROR record with a documented catalog fix. The user
got nothing.

**Root cause.** `app/core/domain.py::_validate_time_range` (line 161):

```python
if not earliest:
    return TimeRange.default()          # -15m
match = _RELATIVE_TIME_RE.match(earliest.strip())   # ^-(\d+)(m|h|d)$
if not match:
    return TimeRange.default()          # -15m, silently
```

Any `time_earliest` that LLM turn 1 emits outside the exact `-<N><m|h|d>` shape —
or omits — is dropped to 15 minutes with **no error, no retry, no signal to the
user**. This is the documented "silently dropped to `None`, never bounced back"
policy applied to the time window. It is not a systematic inability to parse "24
hours": the same phrase parsed correctly on the very next scenario
(`S07_success_path/01_q1_success.txt` → `earliest: -24h`) and on S08 q1 → `-24h`.
That makes it worse, not better: the window silently survives on some turns and
silently vanishes on others, and the reply text is the only place the substitution
surfaces.

**Why it matters**

The reply is not merely unhelpful, it is *misdirecting*. It reports the window it
actually searched (honest) but then instructs the engineer to "try asking again
with a wider window" — when the engineer already asked for a wider window and the
app discarded it. Re-asking the same way can silently fail the same way. An
engineer chasing a live SAPP870110 outage concludes from this reply that there are
no failed transfers, when there is one sitting in the index with a known,
documented remediation.

---

## 4. Symptom of #3 — the routing-check fallback re-issues, unfiltered, the exact query the scope guard refused one turn earlier

**Category:** PRODUCT DEFECT
**Severity:** high (latent — masked here only by the time-shifted corpus)

**Evidence**

`S06_scope_guard/backend_calls.json`, q3, second `create_job` (sid `…085431.19`):

```
search index=pdbb sourcetype=Native "<d:BusinessStatus>ERROR</d:BusinessStatus>" | head 200
window: -15m .. now  ->  0 rows
```

Compare the immediately preceding turn, `S06_scope_guard/02_q2_far_too_broad.txt`,
query "Show me all the errors.":

> "I need more specific information to assist you effectively. Please provide a Packaging Specification ID, a plant code, or any other identifying detail…"
>
> Splunk jobs: **0**

The guard (`harness._is_underspecified`) correctly refuses status-only searches at
the front door. But `app/agents/packspec_status/pipeline.py::_check_routing_if_target_missing`
(line 137) fires when a `target_system` was requested and returned no rows, and
runs `_run_search(config, replace(params, target_system=None))` — it drops the
*only* discriminating field and re-runs. The result is a bare `status=ERROR` sweep
of the whole index: byte-for-byte the query the guard just blocked, executed
behind the guard's back, with no guard re-evaluation on the broadened params.

Here it returned 0 rows purely because the corpus is time-shifted and the window
had already collapsed to 15m (finding #3). Against a real index at the `-24h` the
user actually asked for, this fallback returns every ERROR event in the pipeline,
across every plant and target system — precisely the "arbitrary real production
records" outcome S06 exists to prevent.

**Why it matters**

Two harms. Operationally, an unbounded status-only sweep is exactly the shape the
splunk-client spec flags as a gateway `MessageBlocked` risk. Correctness-wise, the
broadened result set feeds `_resolve_plant_and_det_type`, so a plant/det-type
resolved from *some other PS's* records could drive the Additional Routing lookup
and produce a routing verdict about the wrong plant. It fails closed today only
because it found nothing.

---

## 5. Symptom of #3/#4 — the routing caveat is emitted as if routing were unknowable, when the routing plan was never asked

**Category:** PRODUCT DEFECT
**Severity:** medium

**Evidence**

`S06_scope_guard/03_q3_valid_two_field.txt`:

> "Note: whether this was ever supposed to reach SAPP870110 at all isn't something I can check here -- that depends on the Additional Routing plan and per-plant Import Configuration, not just this Transfer history. The PST team can confirm."

`S06_scope_guard/backend_calls.json`, q3: **routing-plan calls: 0**. Only two
`splunk.*` call groups; no Additional Routing API call at all.

Causal chain, end to end, for S06 q3:

1. `_validate_time_range` drops the requested 24h → `-15m` (finding #3).
2. Filtered search at `-15m` → 0 rows (corpus newest event is 20 min old).
3. 0 primary records + `target_system` set → `_check_routing_if_target_missing`
   fires → broadened `status=ERROR`-only search, still `-15m` (finding #4).
4. Broadened search also returns 0 rows → no plant, no det-type resolvable →
   the function returns `None` *before* ever calling `routing_plan.query_target_systems`
   (hence routing-plan calls: 0).
5. `routing_check is None` → `harness._not_found_answer` (line 114) emits the
   generic "can't check routing" caveat + "try a wider window".

The caveat's wording — "isn't something I can check **here**" — asserts a
capability boundary. The app in fact *can* check routing (plant 0110/SHIP →
SAPP870110 is in the frozen plan) and would have, had step 1 not destroyed the
window. The user is told a permanent limitation exists where there was a
transient data-shortfall caused by a dropped parameter.

**Why it matters**

It sends the engineer to the PST team for a question the tool could have answered
in the same turn. Worse, it teaches the engineer that routing questions are
out of scope for this tool, which is false, and which will suppress future
correct uses of it.

---

## 6. The `search_count: 1..1` FAIL on S06 q3 is a false failure

**Category:** HARNESS DEFECT
**Severity:** medium

**Evidence**

`S06_scope_guard/verdicts.json`, q3:

> `[FAIL] search_count: 1..1 -- observed 2 Splunk job(s)`

The briefing's invariant is "**one tool call** per question" — one
`get_ps_status` invocation, one pipeline run. It is not "one Splunk job". The
second job is `_check_routing_if_target_missing`'s documented internal broadening
(`pipeline.py:137-151`, docstring: "broadens the same search (dropping just
`target_system`)"), inside the same single tool call. The same pattern appears at
`S09_nonexistent_ps` and in the 04:46:03 turn, where it is not flagged.

The check conflates tool calls with backend jobs, so it fires on architecturally
correct behaviour.

**Caveat:** the *turn* is still a genuine FAIL — the sibling check
`contains_any: SNR13 | 00000000040001253724` failed for the real reason in
finding #3. Do not "fix" this by relaxing the expectation; fix the check's
granularity (assert one *tool call*, and separately assert the broadened SPL is
still scoped), or finding #4 loses its only tripwire.

---

## 7. S07 q2 — "Any errors at all on that one?" silently loses the conversation's 24-hour window and answers from an empty 15-minute window

**Category:** MISSED DEFECT (turn PASSED)
**Severity:** medium

**Evidence**

`S07_success_path/01_q1_success.txt` — q1 searched `-24h .. now -> 3 rows`.
`S07_success_path/02_q2_any_errors.txt` — the immediate follow-up:

```
search index=pdbb sourcetype=Native "00000000040000588527" | head 200
window: -15m .. now  ->  0 rows
```

> "No primary records were found for PS 00000000040000588527 in the last 15 minutes. **This means that there weren't any current errors or issues reported during that time frame**…"

The `ps_id` was correctly re-derived from prose across the turn boundary; the time
window was not. Per the briefing, only user questions and assistant prose persist
between turns, and every follow-up must re-derive its arguments — so an unqualified
follow-up reverts to the 15-minute default even though the user's stated frame,
one message earlier, was 24 hours.

The truthful answer was available and was already on screen: q1's 3 rows at `-24h`
are all SUCCESS (`MARA / MARM data has been updated in database succesfully`),
`catalog_matches` empty. The correct reply is "No — all 3 records in the last 24
hours are SUCCESS." Instead the user gets a zero-row non-answer with "no data" and
"no errors" quietly equated in the first sentence, then partially walked back in
the second.

**Why the check passed:** the oracle is
`contains_any: \bno\b|none|no errors|not (?:any|seeing)|clean|success`. It matched
the literal "**No** primary records were found" — the *wrong sense* of "no". There
is no `search_count` check, no `spl_contains` check, and no window assertion on
this turn (contrast q1, which has both), so the regression to `-15m` is invisible
to the suite.

**Why it matters**

An engineer reading "there weren't any current errors" after being told the PS
succeeded will reasonably close the ticket. They are right by luck here. On any PS
whose errors sit 20+ minutes in the past — i.e. essentially all of them, given the
default window — the identical sentence would be an all-clear over unexamined
failures.

---

## 8. S07 q1 — correct verdict, but the quoted evidence is a paraphrase, not the record

**Category:** MISSED DEFECT (turn PASSED)
**Severity:** low

**Evidence**

`S07_success_path/01_q1_success.txt`:

> "For PS 00000000040000588527 — it successfully completed in the last 24 hours. The Replication Status indicates that **the Cockpit Master Data has been updated successfully in the SAP POE system**, confirming that the data flow was successful."

Ground truth: `message_type` = `PackITPackagingCockpitMasterData`, `target_system`
= `SAPPOE0110`, `description` = `MARA / MARM data has been updated in database
succesfully`, 3 hops, SUCCESS. `catalog_matches` is empty for SUCCESS records.

The headline verdict is right and — importantly for the scenario's purpose — **no
fix, no ticket, no mServiceHub reference is invented** (the `absent: mservicehub`
and `absent: \braise a ticket\b` checks pass on substance, not by luck). This turn
is the closest thing in my scope to correct behaviour.

Two residual imprecisions: the concrete `MARA / MARM` description is replaced by a
restatement of the *message type* ("Cockpit Master Data"), and the exact target
system `SAPPOE0110` is softened to "the SAP POE system" — a system name an engineer
cannot paste into a search box. The 3 hops are not mentioned.

**Why it matters**

Low impact here, but it is the same habit that becomes finding #1 under pressure:
the prose layer prefers a fluent restatement over the literal field value. When
the underlying record is an ERROR, an approximated `description` is what breaks
catalog lookup by hand.

---

## 9. S08 q1 never answers "which is worse", and discards the one field that would have

**Category:** MISSED DEFECT (turn PASSED)
**Severity:** medium

**Evidence**

Query: "Compare PS …253724 and PS …399187 over the last 24 hours -- **which is worse?**"
`S08_cross_ps_confusion/01_q1_compare.txt`, SPL returned **100 rows** for
…253724. Ground truth: …253724 has `hop_count` **100** — the largest retry chain
in the corpus by a factor of 50 — against …399187's 1.

`hop_count` is explicitly in the `primary_records[]` payload sent to LLM turn 2
(`harness._summarize_status_result`). The model had it and never mentioned it. The
reply is a generic error-plus-catalog-fix recital:

> "The status is "ERROR" with the description stating that "SNR13 not found/ Mark for deletion." … The suggested solution involves creating the missing number or removing the deletion flag…"

That catalog text is correctly grounded (row 2, Target Error, responsible Plant),
so this is not fabrication. But the comparative question is dropped entirely, and
the single most decisive severity signal available — a 100-hop retry storm — is
omitted in favour of boilerplate that applies equally to both PSs.

**Why it matters**

"Which is worse" is a triage-ordering question; it is why the engineer asked. The
one number that answers it was in hand and unused. Combined with finding #1, the
engineer leaves the conversation with no ordering, no second PS, and a promise.

---

## 10. S08 q3 — plant question answered with circular filler

**Category:** MISSED DEFECT (turn PASSED)
**Severity:** low

**Evidence**

`S08_cross_ps_confusion/03_q3_plants.txt`:

> "**Plant:** Not explicitly listed, but **it likely corresponds to the plant associated with this PS ID**."

Credit where due: this is the designed hallucination trap (plants 0110 and 0500
never reach the model and appear in no description), and the model did **not**
invent a code. `absent: \b0110\b` and `absent: \b0500\b` pass on substance.

But the sentence is tautological — the plant associated with the PS ID is the
question. The honest form is "I don't have the plant in this data; it isn't in the
Transfer records I can see." The hedged phrasing "likely corresponds" also implies
the agent has partial knowledge it does not have, which invites the user to press
for a number it can only guess at.

**Why it matters**

Low on its own. It matters as a pattern: three consecutive turns in S08 substitute
a plausible-sounding placeholder ("please hold on", "likely corresponds") for the
one accurate statement — "I can't do that in this turn."

---

## Summary table

| # | Title | Category | Severity | Turn verdict |
|---|---|---|---|---|
| 1 | Promises a second search the architecture cannot run (x3) | MISSED DEFECT | **critical** | PASS |
| 2 | S08 has no check for continuation promises | HARNESS DEFECT | high | — |
| 3 | S06 q3: explicit "last 24 hours" silently downgraded to 15m default | PRODUCT DEFECT | high | FAIL |
| 4 | Routing fallback re-runs the unfiltered `status=ERROR` sweep the guard refused | PRODUCT DEFECT | high | FAIL |
| 5 | "Can't check routing" caveat emitted with 0 routing-plan calls | PRODUCT DEFECT | medium | FAIL |
| 6 | `search_count: 1..1` counts Splunk jobs, not tool calls — false FAIL | HARNESS DEFECT | medium | FAIL |
| 7 | S07 q2 loses the 24h window; "no rows" read out as "no errors" | MISSED DEFECT | medium | PASS |
| 8 | S07 q1 paraphrases description and target instead of quoting them | MISSED DEFECT | low | PASS |
| 9 | S08 q1 never answers "which is worse"; drops `hop_count`=100 | MISSED DEFECT | medium | PASS |
| 10 | S08 q3 plant answer is circular filler | MISSED DEFECT | low | PASS |

Findings 3, 4 and 5 are one causal chain on a single turn: **3 is the root cause**,
4 and 5 are its downstream symptoms. Fixing the silent time-window drop
(`_validate_time_range`) removes all three *on this turn* — but 4 is an independent
latent defect that will reappear on any target-scoped search that legitimately
returns zero rows, and must be fixed separately by re-applying the scope guard to
the broadened params.
