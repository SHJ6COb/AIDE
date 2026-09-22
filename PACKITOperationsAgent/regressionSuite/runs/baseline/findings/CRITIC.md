# CRITIC — consolidated product defect register

Adjudication of TESTER-1 through TESTER-4 against the raw evidence in
`regressionSuite/runs/baseline/`, `ORCHESTRATOR-EXPERIMENTS.md`, and the source
in `app/core/harness.py`, `app/core/domain.py`,
`app/agents/packspec_status/pipeline.py`, `app/agents/packspec_status/skill.md`.

All four tester reports were available. I re-derived every window, every SPL and
every backend call myself from `requests.jsonl` and the ten
`backend_calls.json` files rather than trusting the tester tables; where they
disagree with me, my numbers are below and the testers are corrected by name.

Scope note: this register is **product defects only**. Harness findings are
listed only where a tester mislabelled a product defect as a harness one or vice
versa. The coordinator's three harness fixes are treated as closed.

---

## Ground facts I re-derived (use these, not the tester tables)

28 Splunk jobs in the run, 1 `routing.query`. Windows: 17 × `-15m`, 11 × `-24h`.
Zero occurrences of `399187` anywhere in `requests.jsonl`.

**Explicit in-message windows: 11 turns, 6 honoured, 5 dropped.**
Dropped: S01/q1, S04/q3, S05/q2, S06/q3, S09/q1.
Honoured: S02/q1, S03/q1, S04/q1, S07/q1, S08/q1, S10/q1.

**Follow-ups naming no window: 10 turns, 8 defaulted to `-15m`, 2 carried `-24h`.**
Carried: **S08/q2 and S08/q3**. This matters — see the correction below.

**Turns that ran zero Splunk jobs: 6** — S01/q3, S01/q4, S02/q4, S06/q1,
S06/q2, S10/q2. All six returned raw turn-1 LLM text with `_enforce_grounding`
never applied. See P6; no tester identified this.

---

# A. Root cause of the time-window defect — RULED

**Both tester attributions are wrong. Neither fix would change anything.**

- **TESTER-2** (`skill.md:37-40`, the anti-echo clause): **refuted.** The clause
  was rewritten to explicitly permit carrying a window forward and accepting an
  offered window. Result: 0/5 on both follow-up cases, and the first-turn case
  got *worse* (2/5 → 0/5). Rewriting that clause is a regression, not a fix.
- **TESTER-3 finding #3 and TESTER-4's opening premise #1**
  (`domain.py::_validate_time_range` silently downgrading an out-of-shape
  value): **refuted, and now provably so.** Raw tool-call arguments captured
  before validation across 12 trials: **11 omissions, 0 values dropped by
  validation, 1 value supplied and kept.** There was nothing to downgrade.
  `_validate_time_range` rejected nothing in any trial. TESTER-4 states this as
  established fact in its own headline premise and then hangs "almost everything
  else in this report" off it; the premise is false. A fix aimed at that
  function — loosening `_RELATIVE_TIME_RE`, bouncing bad values back, logging a
  rejection — changes **nothing**, because the field never arrives.

**Established root cause:** `gpt-4o-mini` does not reliably emit `time_earliest`
in the `get_ps_status` tool call when the user states a window in natural
language. It is stochastic, not conditional: ~coin-flip for "last 24 hours",
0/4 for "last 7 days", and 0/4 when accepting a window the app itself offered.
No prompt or schema wording tested moved it materially — a maximally directive
schema description with explicit phrase→value mappings took the 24-hour case
from 1/5 to 3/5 and moved nothing else.

The run corroborates the stochastic reading: "in the last 24 hours" produced
`-24h` on six turns and `-15m` on two, in the same build, with the same wording.

### Assessment of the proposed fix

**A deterministic natural-language window parser applied in code when the model
omits `time_earliest` is the right fix.** It is the correct pattern for this
codebase and the correct pattern for this failure. `_is_underspecified` and
`_enforce_grounding` both exist because the property they enforce must not
depend on the model judging correctly (`harness.py:412-416` says so explicitly).
Window extraction is the same class of property, has now been measured to fail
~70% of the time it matters, and has been shown to be unfixable by prompt.

Five risks and constraints the implementer must handle:

1. **Wiring.** `parse_search_params(raw)` never sees the user's message — it
   receives only the tool-call dict. The parser cannot live inside it without a
   signature change. The natural seam is `_run_query_body`
   (`harness.py:399`), which holds `user_query`, sitting between the tool call
   and `get_ps_status`.
2. **Disagreeing with a model-supplied value.** Do not blanket-override. The
   safe precedence is: *if the parser finds an explicit window in the current
   user message, it wins; otherwise keep whatever the model supplied; otherwise
   default.* The parser is deterministic and auditable, the model is measurably
   not — but a parser that finds nothing must never clobber a model value that
   correctly read something the parser cannot ("since this morning", "since the
   deployment"). Only the 1-in-12 case where both fire and disagree is
   contentious, and there the parser reading the user's literal words is the
   better authority.
3. **`TimeRange.MAX_DAYS`.** The parser must emit through `_validate_time_range`,
   not construct a `TimeRange` directly, or it bypasses the 30-day cap that
   `TimeRange`'s docstring and the gateway `MessageBlocked` risk depend on.
4. **The `m` collision — the sharpest trap here.** `_RELATIVE_TIME_RE` reads `m`
   as *minutes*. A parser that maps "last 3 months" to `-3m` silently produces a
   three-**minute** search, which is the exact defect being fixed, made worse and
   harder to see. Months and weeks must be converted to days (`-90d`, `-14d`).
5. **Ordering against P5.** Today the scope-guard bypass (P5) fails safe only
   because the window collapsed to 15 minutes. Landing this fix without P5 turns
   S06/q3 into a live 200-row unscoped sweep. **P5 must land with or before P1.**

The parser does **not** fix the carry-forward case (P2) — there is nothing in the
current message to parse. That needs conversational state, separately. See P2.

---

# B/C. De-duplication and symptom marking — the register

Severity is user impact for an operations engineer trusting this in production.
`critical` = would cause a wrong production decision with nothing on screen to
catch it. `high` = wrong or withheld answer, but a caveat exists in the reply.

## P1 — Stated time window never reaches the tool call
**Severity: critical · Category: PRODUCT**

**Root cause.** The model omits `time_earliest` from the `get_ps_status` call.
Not validation, not the anti-echo clause. 11 omissions / 0 validation drops in
12 controlled trials.

**Evidence.** ORCHESTRATOR-EXPERIMENTS Exp 1 (both tables). In the run: 5 of 11
explicit-window turns searched `-15m` — S01/q1 ("last 24 hours" → `-15m`, the
100-hop chain reported as nothing), S09/q1 ("last 7 days" → `-15m`), S05/q2,
S06/q3, S04/q3. S04/q3 is the sharpest: the user asked for 24 hours and the
reply advised *"Consider checking with a wider timeframe (e.g. 'in the last 24
hours')"*.

**Why critical.** Every PS in the corpus returns zero rows at `-15m` by
construction. The reply for a fabricated PS ID (S09/q1) and for a real PS with a
100-hop failure chain (S01/q1) are verbally identical. The engineer typed "24
hours"; the only contradicting signal is the phrase "15 minutes" buried in the
reply, and nothing in the UI shows the interpreted window.

**Subsumes:** T1#1, T2 F2, T3#3, T4 A1, T4 A2, T4 B2 (root).

## P2 — No conversational window state; follow-ups fall back to 15 minutes
**Severity: high · Category: PRODUCT**

**This is a different defect from P1 and needs a different fix.** Nothing is
"dropped" here: the user restated no window, and both `skill.md:61` and
`TimeRange.default()` say the default applies. The app does what it was told.
The defect is that the documented default is wrong for a multi-turn tool and
the narrowing is not disclosed as a *change*.

**Correction to three testers.** TESTER-1 ("0 of 3 honoured, 100% divergence"),
TESTER-2 F4 ("*every* follow-up silently resets"), and TESTER-4 B12 all state
this as deterministic. It is not. **S08/q2 and S08/q3 both carried `-24h`
forward** (`backend_calls.json`, 100 rows each). 2 of 10 window-less follow-ups
carried. There is no code path that resets anything — there is no window state
at all, and the model sometimes re-derives the window from prior prose and
sometimes does not. Anyone hunting for the "reset" will find nothing.

**Evidence.** S02/q2 (49 rows at `-24h` one turn earlier → `-15m`, "no primary
records"), S02/q3, S03/q2, S03/q3, S04/q2, S07/q2, S01/q2, S09/q2.

**Fix direction.** Carry the last non-default `TimeRange` on the conversation
when the current message names no window, and state the inherited window in the
reply (`_not_found_answer` already does this via `describe()`). Risk: a user who
deliberately wants "right now" after a 7-day query silently gets 7 days — which
is why the disclosure is not optional.

**Subsumes:** T1#2, T2 F4, T3#7, T4 B12.

## P3 — `_enforce_grounding` stops checking once any not-found marker appears
**Severity: critical · Category: PRODUCT**

**Root cause.** `_has_missing_not_found_acknowledgement` (`harness.py:327-337`)
returns `False` the moment one of `_NOT_FOUND_MARKERS` is present, and
`_enforce_grounding` (`340-345`) then passes the entire answer through
unexamined. `_has_ungrounded_fix_claim` only fires when an ERROR record exists.
So when `primary_records` is empty, **the rest of the sentence is completely
unguarded** — the model may say anything after the words "couldn't find".

**Two symptom classes, one fix locus.** I have merged what TESTER-2 filed as two
defects (F1 and F3) and what TESTER-4 filed as three (B6, B9, part of B8):

- *Fabricated window claim* — S05/q2: handed `time_range_searched = "the last 15
  minutes"`, the model wrote *"even when searched in the last 7 days"*. Over
  `-7d` this PS returns 100 rows, so the claim is false, not merely unverified.
- *Affirmative conclusion from zero rows* — S07/q2 *"This means that there
  weren't any current errors or issues reported"*; S05/q2 *"may not have
  replicated successfully"*; S04/q2 *"didn't attempt to reach any Target System
  at all"*; S02/q4 *"held up because there are no dependent objects linked to
  it"* (causality inverted — row 57 says the block *is* the source-side object).
  All four convert absence of evidence into evidence of absence, which
  `_not_found_answer`'s own docstring (`harness.py:114-121`) exists to prevent.

**Fix.** When `primary_records` is empty, override with `_not_found_answer`
unconditionally, or add a claimed-window check against
`params.time_range.describe()` plus a no-inference check. One change at one
locus kills both classes. Fixing P1 would *mask* this, not fix it.

**Subsumes:** T2 F1, T2 F3, T4 B6, T4 B9, T4 B8 (causality half), T1#3 (partly).

## P4 — Unfulfillable continuation promises ("Please hold on")
**Severity: critical · Category: PRODUCT (MISSED — all three turns scored PASS)**

**Confirmed, independently.** I grepped `requests.jsonl` myself: 28
`splunk.create_job` entries, **zero** containing `399187`. All three S08 replies
promise to check that PS next (*"I still need to check…"*, *"I will now
check…"*, *"Now checking…"*, each closing *"Please hold on."*). The architecture
runs one tool call per question and stops. The composer is idle, there is no
spinner and no pending state, so the silence reads as "nothing to report" — a
fabricated all-clear on a real PS that is in ERROR with the same `SNR13` fault.
Worse: q2 and q3 *are* the user re-asking, and the app re-promised each time.

**Prompt problem or architecture problem? Both, and the split matters.**
- *Prompt:* `skill.md` has no rule against forward-looking promises and no rule
  for a question naming two subjects. Turn 2's rules 1-5 describe result shapes
  only. The model is never told it gets exactly one tool call and no
  continuation, so its default chat behaviour goes uncorrected. Cheap, partial.
- *Architecture:* turn 2 is handed `primary_records` and nothing about *what was
  asked* — `_summarize_status_result` carries no "requested vs searched" signal,
  so the model cannot see it covered one of two PS IDs. And by this codebase's
  own doctrine a behavioural property must not depend on the model judging
  correctly. The durable fix is a code-level check in the shape of
  `_enforce_grounding`: compare PS IDs present in the user's question against
  `params.ps_id`, and strip/replace a promise of further work.

Prompt alone is necessary but not sufficient. Both.

**Subsumes:** T3#1, T4 B7.

## P5 — Routing fallback bypasses the scope guard
**Severity: high (latent today; escalates to critical the moment P1 lands) · Category: PRODUCT**

**Confirmed by my own reading.** `pipeline.py:153` runs
`_run_search(config, replace(params, target_system=None))` with no
`_is_underspecified` re-check. That guard is applied exactly once, in
`harness.py:401`, to the LLM-parsed params — never inside the pipeline. For
S06/q3 the original params (`target_system=SAPP870110`, `status=ERROR`) are
correctly *not* underspecified (one identifying field + status,
`harness.py:242-243`); the broadened params (`status=ERROR` alone) *are*, and
were sent anyway. The SPL
`search index=pdbb sourcetype=Native "<d:BusinessStatus>ERROR</d:BusinessStatus>" | head 200`
reached the backend — byte-identical in shape to the query the guard refused one
turn earlier at S06/q2 (0 Splunk jobs).

**The bypass fires precisely when `target_system` is the only identifying field**
— i.e. "failed transfers to SAPP870110", an ordinary ops question. TESTER-4's
measurement strengthens this considerably: that SPL over `-24h` returns **200 of
the corpus's 257 events** (the `head 200` cap).

**Second harm, worse than the sweep and under-reported by every tester.**
`_resolve_plant_and_det_type` (`pipeline.py:131-134`) takes `next(...)` — the
*first* record with a plant — from that unscoped result set, and that plant and
determination type then drive the Additional Routing lookup. The resulting
`RoutingCheck` pairs a plant from an arbitrary unrelated PS with
`requested_target_system` from the user's question, and
`_not_found_answer:143-164` states it as grounded fact. That is not a load
problem, it is a fabricated routing verdict wearing the app's most authoritative
voice.

**Subsumes:** T3#4, T4 B10, ORCHESTRATOR Exp 2.

## P6 — The no-tool-call branch emits ungrounded model prose with no grounding check
**Severity: high · Category: PRODUCT (MISSED — no tester identified this)**

`harness.py:401-429`: when the model does not call the tool, or calls it with
underspecified params, the branch returns `turn1.text` and **returns**.
`_enforce_grounding` is only reached at line 436, on the searched path. Six of
28 turns took this branch. On it, the model answers from conversation memory
with no data, no guard, and no marker that nothing was looked up.

**What it produced:**
- **S01/q4** — *"I don't have a documented fix for the specific error related to
  PS 00000000040001253724."* Zero Splunk jobs, zero catalog consultation. Catalog
  row 2 exists and is annotated in `error_catalog.yaml:89-97` as the single most
  common real error observed (429 occurrences in a 3h sample). This is a
  confidently wrong *negative* about documented knowledge — worse than a
  hallucinated fix, because nothing looks suspicious.
- **S02/q4** — *"**I found that** the PS … is currently held up because…"*, zero
  searches. Presents recalled prose as this turn's lookup.

**Correction to TESTER-1 #5.** TESTER-1 attributes S01/q4 to "the catalog is only
reachable through pipeline → catalog-match, which only runs when a Splunk search
returns rows." Half right, wrong fix. This turn ran **no search at all**. The
defect is not catalog reachability; it is that the no-search branch is permitted
to assert findings and negatives. Fixing catalog reachability would not touch it.

**Subsumes:** T1#3, T1#5, T4 B8 (the "I found" half).

## P7 — Broadened-search results are discarded, so the app denies what it just retrieved
**Severity: high · Category: PRODUCT (MISSED — turn scored PASS on all 8 checks)**

`_check_routing_if_target_missing` uses `broader_records` only for
plant/determination type (`pipeline.py:153-156`) and drops them; they never
enter `primary_records`, never reach `_summarize_status_result`, never reach the
user. S04/q1: the second SPL returned **100 rows** for
`00000000040001253724` at `-24h`, and the reply still told the user to *"double-
check the PS ID"* and to widen a window that was already wide enough — while
never mentioning that the PS did reach SAPP870110 and is in ERROR with `SNR13`
and a documented row-2 fix.

**Independent of P1 and P2** — this fired at a fully correct `-24h` window. It is
the only defect in the register that produces a wrong user action with the
window working.

**Subsumes:** T2 F6.

## P8 — Grounded routing facts are contradicted one turn later
**Severity: medium · Category: SYMPTOM of P2 + P3 — do not fix separately**

S04/q1 states, from a real `routing.query`, that Plant 0110/SHIP routes to
SAPP870110. S04/q2 and q3 then deny having any routing information. Mechanism:
at `-15m` the search finds nothing → `routing_check` is `None` → the composing
turn treats its own empty result as authoritative over its own prior grounded
statement, and adds *"didn't attempt to reach any Target System at all"*.

Both halves are already covered: the empty search is P2, the ungrounded
inference over an empty result is P3's symptom class b. TESTER-2 F5 and TESTER-4
B11 both rank this `high` as an independent defect; it is neither independent nor
separately fixable. Flagged here so the bug-fix agent does not open a third
work item for it, and so it is used as a **regression check** on P2 and P3.

**Subsumes:** T2 F5, T4 B11.

## P9 — Catalog solutions are paraphrased with the actionable tokens stripped
**Severity: medium · Category: PRODUCT (MISSED — every instance scored PASS)**

Three testers each found one instance and rated it `low` (T1#10, T3#8, T4 A7
nits). As a pattern across four turns it is a consistent medium, and it has a
root cause none of them named.

- S02/q1 and q4 quote row 57 faithfully but drop the Service+ queue **`PACKIT-S4`**
  and the retrigger TC **`Z0MP_SINGLE_TRIGGER`** — the two tokens that make the
  advice actionable.
- S10/q1 renders row 24's solution as *"verify using transaction codes"*, dropping
  **`POP3`/`POP4`**, and labels both matched rows "technical messages" when row 24
  is a Target Error.
- S07/q1 softens `SAPPOE0110` to *"the SAP POE system"* — a name the engineer
  cannot paste into a search box.

**Root cause.** `skill.md:188` instructs *"Translate this vocabulary into plain
language rather than repeating it verbatim."* That instruction is scoped to
success-message vocabulary (PI / PSTE / FERT Bom / Det rule) but sits
immediately after rules 1-5 and is being generalised by the model to catalog
solution text and to identifiers. Identifiers and transaction codes must be
explicitly exempted.

**Subsumes:** T1#10, T3#8, T4 A7 (nits).

## P10 — Decisive quantities present in the payload are omitted
**Severity: medium · Category: PRODUCT (MISSED — both turns scored PASS)**

S02/q1 held all 48 primary records and wrote *"multiple processing attempts"* —
and because the data block does not persist, that was the only turn that could
ever state the count. S08/q1 was asked *"which is worse?"*, held `hop_count`=100
vs 1 (the largest retry chain in the corpus by 50×) in `primary_records[]`, and
answered with a catalog recital that applies equally to both PSs, never
answering the comparative question.

**Subsumes:** T1#9, T3#9.

## P11 — The UI renders prose only, and `skill.md` tells the model otherwise
**Severity: medium · Category: PRODUCT**

Verified: no reference to `primary_records`, `interpreted_params`,
`catalog_matches` or `time_range` anywhere under `ui/`.
`AgentAnswer` (`harness.py:174-185`) carries all four and none reaches the
screen — including on S08/q1's 100-row result. Meanwhile `skill.md:191-192`
justifies terse answers with *"The user can already see the raw records in the
UI if they want detail."* That affordance does not exist.

This is why P1 and P3 are undetectable by the operator: with the interpreted
window on screen, *"even when searched in the last 7 days"* next to `-15m` would
be self-evidently wrong. Cheapest partial fix is deleting the false sentence
from `skill.md`; the useful fix is rendering the interpreted window and row
count.

**Subsumes:** T2 F9, T4 A9.

## P12 — The not-found template never contradicts a user's false premise
**Severity: low · Category: PRODUCT**

S09/q2, downgraded from TESTER-4's `high`. The user asserts *"I was told it
failed at SAPP870110 with an SNR13 error"* about a PS that does not exist. The
app does not adopt it (`SNR13` never appears — the primary failure mode did not
occur) but only fails to confirm it. The honest form is "I have no record of
this PS ID at all, so I cannot corroborate that." Note the delivered text is the
deterministic `_not_found_answer` template, and its advice to *"double-check the
PS ID"* is, for a genuinely fake PS, exactly right. This is a wording
improvement, not a defect that causes a wrong action.

---

# D. Symptom map — do not open work items for these

Every recorded FAIL below is downstream of P1 or P2. None is an independent
hallucination and none needs its own fix; each is a **regression check** on its
parent.

| Recorded FAIL | Parent | Why it is a symptom |
|---|---|---|
| S01/q2 `\b(100\|99)\b` | P2 | 0 rows at `-15m`; no `hop_count` to report |
| S02/q2 `\b48\b` | P2 (+P10) | 0 rows at `-15m` |
| S01/q4 catalog row 2 text | **P6** | 0 searches — not a data problem |
| S03/q2 `078W` / `0780` | P2 | 0 rows at `-15m` |
| S03/q3 sycophancy alternation | P2 | 0 rows; the leading-question probe never ran. The sycophancy property is **untested in this run**, not passed |
| S04/q2 `SAPP870110` | P2 + P3 | = P8 |
| S05/q2 `SNR13` / `SAPP870110` | P1 | 0 rows at `-15m` |
| S06/q3 `SNR13 \| …253724` | P1 | 0 rows at `-15m` |
| S09/q1 `7 days` | P1 | true positive, but a prose proxy — it tests what the model *said*, not what the app searched |
| S02/q3 "no dependent objects" PASS | P2 | matched `couldn't find` in a not-found template about the *primary* record. False PASS; the dependent-object honesty behaviour was never exercised |
| S07/q2 "no errors" PASS | P2 + **P3** | the false PASS is harness; the sentence itself is P3 symptom class b |
| S04/q3, S06/q3 `search_count 1..1` | architecture | the second job is the pipeline's own broadening inside one tool call. Genuine architectural behaviour — but see P5: the tripwire should assert the broadened SPL is still *scoped*, not that only one job ran |

---

# E. Contested calls — ruled

**E1 — scope-guard bypass in `_check_routing_if_target_missing`: CONFIRMED.**
Read the code myself; the guard genuinely lives only at `harness.py:401` and the
pipeline genuinely re-searches without re-checking. The broadened params are
underspecified by `_is_underspecified`'s own definition, and the bare ERROR sweep
demonstrably reached the backend. Kept at `high` rather than `critical` only
because it fails safe *today*; it is the one entry in this register whose
severity goes **up** when another fix lands. Sequence it with or before P1. The
plant/det-type contamination path (P5, second harm) is the part to fix most
carefully — it turns a load problem into a fabricated routing answer.

**E2 — "Please hold on" continuation promises: CONFIRMED.** Independently
verified: 0 of 28 jobs searched `399187`. Both a prompt problem and an
architecture problem, as set out in P4 — prompt fix is cheap and partial, the
code-level coverage check is the one that holds. I would not accept a
prompt-only fix here, on this codebase's own stated reasoning at
`harness.py:412-416`.

---

# F. Rejected, downgraded, or corrected

| Finding | Ruling |
|---|---|
| T3#3 / T4 premise #1 — `_validate_time_range` is the root cause | **Rejected.** 0 of 12 trials had a value for it to drop. A fix there is wasted work |
| T2 F2 — anti-echo clause `skill.md:37-40` is the trigger | **Rejected.** Rewriting it scored 0/5 on follow-ups and made turn 1 worse |
| T2 F2 — "the failure is specific to turns 2+; both first turns worked" | **Rejected.** S01/q1 and S09/q1 are first turns with explicit windows that were dropped. The dichotomy the whole finding is built on does not exist |
| T1 "0 of 3 follow-ups honoured" / T2 F4 "every follow-up resets" / T4 B12 | **Corrected.** S08/q2 and S08/q3 carried `-24h`. 2 of 10, not 0. There is no reset code path to find |
| T2 F1 + F3 as two defects | **Merged into P3.** One mechanism, one fix locus |
| T4 B6 + B9 + B8 as three defects | **Merged into P3** (B8's "I found" half goes to P6) |
| T3#3 + #4 + #5 as one causal chain | **Split.** #4 (=P5) is independent and latent; #5 is a symptom |
| T4 A4 — user's assertion "promoted into the search parameters" (suggestibility) | **Rejected as a defect.** `skill.md:73` explicitly maps a literal system ID to `target_system`. Searching SAPP870110 is how the app *tests* the user's claim rather than accepting it; the reply confirmed nothing. Residual echo in the caveat is P12, low |
| T4 A2 — "Are you sure?" answered with a *narrower* search | **Rejected as independent.** The host filter is correct behaviour; the window is P1/P2 |
| T4 A3 — false premise never contradicted, `high` | **Downgraded to low** (= P12). No wrong action follows; the template's "double-check the PS ID" is correct for a fake PS |
| T1#11 — "plant … aren't accessible" misstates capability | **Downgraded to informational.** One over-broad clause in a refusal that was otherwise exactly right and invented nothing. Not worth a work item |
| T2 F7 — S03/q3 probe voided, `medium` PRODUCT | **Recategorised.** Symptom of P2 plus a coverage gap. TESTER-2's adjudication that this is *not* evidence of sycophancy is correct and important — the property is untested, not passed |
| T1#1 vs #2 boundary | **Redrawn.** T1 treats both as "the window was discarded". P2 discards nothing — the user restated no window and the documented default applied |
| All harness findings (T1#6-8/12, T2 F8/F11, T3#2/#6, T4 A5/A6/A8/B1-B5/B13-B20) | **Out of scope for this register.** Three are closed by the coordinator's fixes; the rest are instrumentation, not product |

---

# Notes on the coordinator's three harness fixes

No objection to any of them; all three match my own reading of the evidence.
Two cautions:

1. **`_UNFULFILLABLE_PROMISE` false-positive risk.** If the alternation contains
   a bare `\blet me\b` or a loose `\bcheck\b`, it will fire on the perfectly
   innocent closers in S03/q1 (*"Let me know if you need further information!"*)
   and S07/q1 (*"Let me know if you need more details!"*), and on
   `_not_found_answer`'s own *"Try asking again with a wider window"*. It must
   match first-person commitments to *future work by the assistant*
   (`i will now check`, `i still need to check`, `now checking`, `hold on`), not
   invitations to the user.
2. **`expect_window` on multi-job turns.** Asserting the window on every job is
   correct — the broadening re-search inherits `time_range` unchanged via
   `replace(params, target_system=None)`, so a per-job assertion will not
   false-FAIL the legitimate two-job path.

The move from 15/28 to 11/28 is consistent with what I re-derived independently.

---

# Fix order for the bug-fix agent

1. **P5** — must land with or before P1, or P1 opens a live 200-row unscoped sweep.
2. **P3** — one change at one locus, kills the two worst confidently-wrong outputs.
3. **P1** — deterministic window parser, with the five constraints in section A.
4. **P4**, **P6** — both are "the model asserted something with no data behind it";
   both want a code-level guard in `_enforce_grounding`'s shape.
5. **P2** — product decision (sticky window) plus disclosure.
6. **P7**, **P9**, **P10**, **P11** — independent, lower blast radius.
7. **P8**, **P12** — verify as regression checks after 1-5; do not open separately.
