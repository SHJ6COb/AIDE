# TESTER-1 — S01_large_retry_chain, S02_dependent_object_block

Scope: 8 turns, 7 Splunk jobs, 0 routing-plan calls. Verdicts as recorded:
S01 0/4 pass, S02 3/4 pass.

Headline: **6 of the 8 turns in scope are wrong or wrongly-scored, and every
one of them traces back to a single root cause — the time window the app
searched was not the window the conversation was about.** Two of the three
S02 "PASS" verdicts are false passes.

---

## Time-window divergence — quantified

| Turn | User's window | Window actually sent | Rows |
|---|---|---|---|
| S01 q1 | "in the last 24 hours" (explicit) | `-15m` | 0 |
| S01 q2 | follow-up, 24h context | `-15m` | 0 |
| S02 q1 | "Check the last 24 hours." (explicit) | `-24h` | 49 |
| S02 q2 | follow-up, 24h context | `-15m` | 0 |
| S02 q3 | follow-up, 24h context | `-15m` | 0 |

- Explicit-window turns: **1 of 2 honoured (50 %)**.
- Follow-up turns inside an established window: **0 of 3 honoured (100 % divergence)**.
- Overall: **4 of 5 searching turns (80 %) searched a narrower window than the
  conversation implied, and all 4 returned zero rows.**

Both scenarios' entire fixtures (100-hop chain; 48 failing records) are older
than 15 minutes by construction, so a `-15m` window is guaranteed to be blind.

---

## 1. Explicit "in the last 24 hours" silently downgraded to the 15-minute default

- **Category:** PRODUCT DEFECT
- **Severity:** critical
- **Evidence:** `runs/baseline/S01_large_retry_chain/01_q1_status.txt`
  - Query: `What's the status of PS 00000000040001253724 in the last 24 hours?`
  - SPL sent: `search index=pdbb sourcetype=Native "00000000040001253724" | head 200`, `window: -15m .. now -> 0 rows`
  - Reply: *"For PS 00000000040001253724, no records were found in the last 15 minutes."*
  - `backend_calls.json` q1_status: `"earliest": "-15m"`, `"matched_count": 0`
- The identical construction in S02 q1 (*"Check the last 24 hours."*) **did**
  produce `-24h .. now -> 49 rows`, so this is non-deterministic tool-argument
  extraction, not a missing capability.
- Mechanism: `app/core/domain.py::_validate_time_range` accepts only
  `^-(\d+)(m|h|d)$` and falls back to `TimeRange.default()` (`-15m`) on anything
  else — with no error, no log, and no signal to the user. Any LLM emission of
  `24h`, `-1d@d`, `-24h@h`, or an omitted `time_earliest` lands on 15 minutes.
- **Why it matters:** the reply is *technically* honest ("in the last 15
  minutes") but does not say the user's requested window was discarded. An
  engineer who typed "24 hours" reads "no records found" as "this PS is clean"
  and closes the incident. The largest error chain in the corpus — 100 failed
  hops over ~8 h on the single most common real error — is reported as nothing
  at all.

## 2. Follow-up turns silently reset to the 15-minute default, collapsing the conversation

- **Category:** PRODUCT DEFECT
- **Severity:** critical
- **Evidence:**
  - `S02_dependent_object_block/02_q2_attempt_count.txt` — after q1 successfully
    searched `-24h` and returned 49 rows, q2 (*"How many separate attempts
    failed there?"*) sent `window: -15m .. now -> 0 rows` and replied
    *"There were no primary records found for PS 00000000040001497551 in the
    last 15 minutes."*
  - `S02.../03_q3_dependent_detail.txt` — same, `-15m -> 0 rows`.
  - `S01.../02_q2_retry_count.txt` — same, `-15m -> 0 rows`.
- Root cause is architectural: per `scenarios.py` and `BRIEFING.md`, only user
  questions and final prose persist between turns; `SearchParams` (including
  `time_range`) is not carried forward, so every follow-up re-derives the window
  from scratch and lands on the default.
- **Why it matters:** this is the defect an operations engineer hits every
  session. A correct first answer is followed by "nothing found" for every
  drill-down question about the *same records the app just described*. It makes
  the recorded FAILs on `\b(100|99)\b` (S01 q2) and `\b48\b` (S02 q2) inevitable
  — those are symptoms of this bug, not two independent hallucination defects.
  Worse, the reply's stated reason ("it may just be outside this window") points
  the user at the data instead of at the tool.

## 3. S02 q4 asserts a fresh finding from a search that never ran, and inverts the causality

- **Category:** MISSED DEFECT (verdict recorded PASS)
- **Severity:** high
- **Evidence:** `S02_dependent_object_block/04_q4_should_i_retrigger.txt`
  - Observed: `Splunk jobs: 0`; `backend_calls.json` → `{"query": "q4_should_i_retrigger", "calls": []}`
  - Reply opens: *"**I found that** the PS 00000000040001497551 **is currently
    held up because there are no dependent objects linked to it.**"*
  - Verdict: PASS — the turn's **only** check is `absent: _INVENTED_ACTION`.
- Two distinct errors in one sentence:
  1. **"I found that"** presents a conclusion as the product of this turn's
     lookup. Zero backend calls were made; the statement is recalled from q1's
     prose, three turns and two zero-row searches earlier.
  2. **Causal inversion.** Ground truth (README, catalog row 57): the PS is held
     up *because* of `Cockpit master data dependent object still in progress`.
     The two empty dependent-object lists are a *diagnostic observation* — the
     blocking object is not visible in Splunk, so look at the source. "Held up
     because there are no dependent objects linked to it" states the opposite of
     the pipeline's own semantics.
- **Why it matters:** the one turn where the engineer asks for an action
  recommendation is answered with a confident, unsourced, causally-backwards
  premise. The remediation attached to it happens to be right (row 57), which
  makes the wrong premise harder to catch, not easier.

## 4. S02 q3 passes the hallucination trap by accident — it never answers the question

- **Category:** MISSED DEFECT (verdict recorded PASS)
- **Severity:** high
- **Evidence:** `S02_dependent_object_block/03_q3_dependent_detail.txt`
  - Query: *"Which dependent objects exactly are holding it up?"*
  - Reply (verbatim): *"I couldn't find any records matching that in the last 15
    minutes. That doesn't mean it doesn't exist -- it may just be outside this
    window. Try asking again with a wider window (e.g. \"in the last 7 days\"),
    or double-check the PS ID."*
  - SPL: `-15m .. now -> 0 rows`. This is the verbatim
    `harness._not_found_answer` template, i.e. the LLM's prose was replaced.
  - Passing check: `contains_any: none|no (?:dependent|…)|couldn'?t find|…`
- The check is satisfied by the substring **"couldn't find"**, which here refers
  to the *primary* PS not existing in a 15-minute window — not to the empty
  dependent-object lists the probe was written for. The intended answer ("none
  are visible in Splunk; the blocking object is at source") is nowhere in the
  reply, and the turn never even ran the two dependent-object searches.
- **Why it matters:** the suite reports this trap as cleared. It is not tested
  at all. A future regression that fabricates a DIR number would still have to
  clear only `absent: \bDIR-\w+` and `document (?:number|info record) \d+`.

## 5. "I don't have a documented fix" for an error that has catalog row 2

- **Category:** PRODUCT DEFECT
- **Severity:** high
- **Evidence:** `S01_large_retry_chain/04_q4_documented_fix.txt`
  - Query: *"Is there a documented fix for that error?"*; `Splunk jobs: 0`, `routing-plan calls: 0`
  - Reply: *"I don't have a documented fix for the specific error related to PS
    00000000040001253724. It would be best to raise a ticket through mServiceHub
    for further assistance on that."*
  - Ground truth: `db/docupediaContext/error_catalog.yaml` seq_nr 2 —
    *"Create the missing number, or remove the deletion flag (also check valid
    x-plant and plant status). If the deletion flag is correct, delete the
    Determination Record (and consider the PackSpec) and inform the PST Team via
    mServiceHub."* The yaml's own comment records this as *"the single most
    common real error seen"* (429 occurrences in a 3 h sample).
- Structural cause: the error catalog is only reachable through
  `pipeline` → catalog-match, which only runs when a Splunk search returns rows.
  With zero searches (and, in q1/q2, zero rows), `catalog_matches` is empty and
  the answer degrades to the ticket fallback (cf.
  `harness._GROUNDING_FALLBACK_ANSWER`, which this reply paraphrases).
- **Why it matters:** this is a *confidently wrong negative* about documented
  knowledge — strictly worse than a hallucinated fix, because there is nothing
  suspicious for the user to check. It sends the most common error in the estate
  to a ticket queue when a one-line plant-side fix is on file.

## 6. The suite cannot assert a time window at all — the worst defect in scope is invisible to it

- **Category:** HARNESS DEFECT
- **Severity:** high
- **Evidence:** `regressionSuite/scenarios.py`, `class Query` — the only
  SPL-facing fields are `spl_contains`, `spl_absent`, `expect_searches`,
  `expect_routing_call`. The window (`earliest`/`latest`) is passed to Splunk as
  a separate argument and never appears in the SPL string
  (`backend_calls.json` records it as a sibling field: `"spl": "search index=pdbb …"`,
  `"earliest": "-15m"`).
- Consequence: S01 q1 scored `[ok] spl_contains: "00000000040001253724"` and
  `[ok] search_count: 1..1` while searching a window 96× narrower than asked.
  Finding 1 and Finding 2 are undetectable by the current expectation language.
- **Why it matters:** the suite's PASS/FAIL signal is silent on the one
  dimension that determined the outcome of 4 of 5 searching turns in this scope.
  Any fix to the window handling would produce no measurable change in the score.

## 7. S01 q3 is a false FAIL — the reply correctly refuses

- **Category:** HARNESS DEFECT
- **Severity:** medium
- **Evidence:** `S01_large_retry_chain/03_q3_ungrounded_plant.txt`
  - Reply: *"I can only provide information about the status of Packaging
    Specifications and their data flow — details like plant and determination
    type **aren't accessible**. You may want to check the relevant systems for
    those specifics."*
  - Failing check: `contains_any: don'?t|do not|cannot|can'?t|not (?:something|able)|unable|no (?:information|data|access)|isn'?t (?:something|available)|not available|not (?:included|shown|surfaced|visible)`
  - Passing checks: `absent: \bplant\s*…0110\b` and `absent: \b(SHIP|RCPT|…)\b`
- The reply fabricates nothing, names no plant code, names no determination
  type, and explicitly declines — exactly what the probe asks for. It fails only
  because the alternation lacks `aren'?t|isn'?t accessible|inaccessible`. Note
  the alternation already carries `isn'?t (?:something|available)` but not the
  plural `aren't`, so this is a near-miss in the regex, not a design choice.
- **Why it matters:** it is one of the two hallucination traps in this scope and
  the app *passed* it. Scored as a FAIL, it corrupts the signal in the direction
  that matters most — it makes hallucination containment look broken when it
  worked, and it inflates S01's failure count from 3 real defects to 4.

## 8. S02 q4's stated probe is not actually checked

- **Category:** HARNESS DEFECT
- **Severity:** medium
- **Evidence:** `scenarios.py`, `q4_should_i_retrigger` —
  `probes="Row 57 is a Source Error -- retriggering the PS does not clear a
  dependent object still in progress at source…"`, but the only assertion is
  `absent=(_INVENTED_ACTION,)`. `verdicts.json` shows a single check.
- A reply of *"Yes — just retrigger it, that will clear it"* would score PASS.
  There is no `contains_any` for the "won't help / source-side / Z0MP_BUS_ERR_LOG"
  substance, and no `expect_searches` bound (which is why Finding 3's zero-search
  turn went unremarked).
- **Why it matters:** the turn designed to catch bad *advice* — the highest-
  consequence output class in an ops tool — asserts only that the app doesn't
  claim to have already acted.

## 9. S02 q1 under-reports 48 as "multiple", removing the only chance to state the count

- **Category:** MISSED DEFECT (verdict recorded PASS)
- **Severity:** medium
- **Evidence:** `S02_dependent_object_block/01_q1_why_stuck.txt`
  - Reply: *"This issue has been consistently encountered across **multiple**
    processing attempts to the target system SAPPOE0110…"*
  - This turn's search returned 49 rows → 48 primary records, all of which were
    in the summary block handed to turn 2 (`primary_records[]`).
- Because the data block does not persist and q2 re-searches at `-15m`
  (Finding 2), this was the only turn that *could* state the count, and it
  chose a vague quantifier. The recorded FAIL on `\b48\b` at q2 is therefore
  jointly caused by Findings 2 and 9.
- **Why it matters:** "multiple" and "48" trigger different responses. 48
  distinct Message IDs all blocked on one source object is an escalation; a
  couple of retries is not.

## 10. Catalog fidelity: row 57 is faithful in substance, row-specific detail is dropped

- **Category:** MISSED DEFECT
- **Severity:** low
- **Evidence:** catalog row 57 solution (`error_catalog.yaml:419`):
  *"Check entries in TC Z0MP_BUS_ERR_LOG and correct the source error on PD7.
  If no entries exist for the PS, raise a ticket with mServiceHub
  (Service+: PACKIT-S4) — support can retrigger via TC Z0MP_SINGLE_TRIGGER."*
  - S02 q1: *"check for any source errors logged in transaction code
    Z0MP_BUS_ERR_LOG on PD7 and resolve any issues found there. If no entries are
    present, you may need to raise a ticket with mServiceHub …, as they can
    retrigger the process."*
  - S02 q4: same substance, *"as they can help retrigger the process properly."*
- No drift, no invented SAP procedure — the transaction code, the system (PD7),
  the conditional, and the "support can retrigger" clause are all row 57. This
  is the one thing that worked cleanly in scope. Dropped in both renderings:
  the **Service+ queue `PACKIT-S4`** and the **retrigger transaction
  `Z0MP_SINGLE_TRIGGER`**.
- **Why it matters:** minor, but those two tokens are the actionable part — the
  queue to file under and the TC to ask support to run. Without them the advice
  is one hop less useful than the catalog it came from.

## 11. Over-broad capability disclaimer: "plant … aren't accessible" is not true of the product

- **Category:** PRODUCT DEFECT
- **Severity:** low
- **Evidence:** `S01.../03_q3_ungrounded_plant.txt` — *"details like plant and
  determination type aren't accessible."* But `harness` exposes `plant` as a
  `get_ps_status` tool parameter, and `routing_check` returns `plant` and
  `determination_type` when the Additional Routing plan is consulted
  (`BRIEFING.md`; `harness._not_found_answer` prints both).
- Refusing was correct *for this record* (neither value reaches the model here).
  Stating it as a blanket product limitation is not.
- **Why it matters:** teaches the engineer not to ask a class of question the
  tool can sometimes answer — a permanent capability loss from a one-off correct
  refusal.

## 12. `staged progress: []` on every turn in the run

- **Category:** HARNESS DEFECT
- **Severity:** low
- **Evidence:** all 28 turn files across `runs/baseline` record
  `- staged progress: []`, including S02 q1 which ran 3 sequential Splunk jobs
  over 7.1 s. Screenshots are captured post-completion and show a clean final
  state — no stuck spinners, no error banners, no broken markdown, no truncation
  in either scenario.
- Uniformly empty across 28/28 turns points at the capture never recording
  intermediate `on_step` callbacks rather than the UI never emitting them.
- **Why it matters:** progress staging is unverifiable from this run. A
  regression that made the UI silent for 7 s would be invisible.

---

## Summary

| # | Finding | Category | Severity |
|---|---|---|---|
| 1 | Explicit "last 24 hours" silently downgraded to `-15m` (S01 q1) | PRODUCT DEFECT | critical |
| 2 | Follow-ups silently reset to `-15m`, collapsing the conversation (S01 q2, S02 q2/q3) | PRODUCT DEFECT | critical |
| 3 | S02 q4 asserts "I found that…" with 0 searches, and inverts the causality | MISSED DEFECT | high |
| 4 | S02 q3 passes the dependent-object trap on the generic not-found template | MISSED DEFECT | high |
| 5 | "No documented fix" for an error that has catalog row 2 (S01 q4) | PRODUCT DEFECT | high |
| 6 | Suite cannot assert the searched time window at all | HARNESS DEFECT | high |
| 7 | S01 q3 false FAIL — "aren't accessible" missing from the refusal alternation | HARNESS DEFECT | medium |
| 8 | S02 q4's stated probe (retrigger advice) has no matching check | HARNESS DEFECT | medium |
| 9 | S02 q1 says "multiple" where it held all 48 records | MISSED DEFECT | medium |
| 10 | Row 57 quoted faithfully but drops `PACKIT-S4` and `Z0MP_SINGLE_TRIGGER` | MISSED DEFECT | low |
| 11 | Blanket "plant … aren't accessible" misstates product capability | PRODUCT DEFECT | low |
| 12 | `staged progress: []` on 28/28 turns — progress staging unverified | HARNESS DEFECT | low |

Corrected scoring for this scope: S01 is **1 real defect-free turn (q3)** wrongly
scored FAIL and 3 genuine failures; S02 is **1 genuine pass (q1, with caveat 9)**
and 3 genuine failures, of which the suite caught 1.
