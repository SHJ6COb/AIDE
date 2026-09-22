---
artifact: procedure
layer: task (routing + procedure)
summary: How a single turn goes, in order — every step, who decides it (code or model), and where it can stop early.
status: draft — steps marked IMPLEMENTED reflect app/core/harness.py and pipeline.py today; steps marked PROPOSED do not exist yet.
---

# Procedure: one turn, in order

Companion to [`TASK-TRIAGE.md`](TASK-TRIAGE.md), which decides *what* the turn
is. This file is *how the turn runs*. Task IDs (T1–T12) and ask IDs (A1–A8)
refer to that file.

Product knowledge is referenced, never restated:
`app/agents/packspec_status/knowledge/`.

## The invariant the whole procedure rests on

**One question → at most two LLM calls and one primary search, then the turn
ends.** No continuation, no second pass, no pending state on screen
([ADR-0001](../../docs/adr/0001-single-deterministic-pipeline-tool.md)). Every
step below is written knowing there is no later turn in which to finish
something.

Two consequences that are not obvious and have both been measured:

- A promise of further work is a promise the product structurally cannot keep.
  It reads to the user as "still working", and the silence afterwards reads as
  "nothing to report" (`FINDINGS.md` D4).
- Anything the turn does not say, the user never sees. The UI renders **prose
  only** — no record panel, no field list, no interpreted window
  (`FINDINGS.md` D12). Brevity is not free.

---

## Step 0 — Persist the question · IMPLEMENTED · code

`store.append_message(conversation_id, "user", query)` before anything else. A
downstream failure never loses the question. If the turn then raises, a fixed
marker reply is persisted in its place so the transcript never carries an
unanswered dangling question.

*Code:* `harness.run_query`.

## Step 1 — Rewrite a bare window reply · IMPLEMENTED · code

If the latest message is *only* a window ("24 hours", "try the last 7 days
then"), it names no subject. Rewrite it in code into the last real user question
with that window appended, and hand step 2 a complete question.

This is **T6**, and it is done in code deliberately: reconstructing the subject
from history is exactly the reference resolution this codebase has repeatedly
measured as unreliable, and getting it wrong here means silently answering about
a different PS.

*Code:* `harness._resolve_window_reply`, `time_window.bare_window_reply`.

## Step 2 — Triage · PARTLY IMPLEMENTED · model, with code guards after

The model reads the question (plus history) and either calls `get_ps_status`
with a `SearchParams`, or does not call it at all. That single choice is today's
entire triage: **tool call = live-data question; no tool call = T7 domain
question**.

The turn-1 system instruction is deliberately narrow — field rules, reference
rules, scope guard. It does **not** carry the glossary, which is why it is told
to *defer* a domain question rather than answer one. The two must stay in step
or the model is instructed to answer from a glossary it does not have.

Reference resolution happens here, and is the highest-risk judgement in the
turn: resolve only from the immediately preceding 1–2 turns, otherwise leave the
field unset and let step 4 ask (**A1**). An unset field costs one clarifying
question; a wrong one costs a confident wrong answer.

*Code:* `harness._run_query_body` turn 1, `_load_skill(PARSE)`,
`skill.md` §"Turn 1".
*Proposed:* emit the `task` and `subjects_named` fields of the route record here
(TASK-TRIAGE §6) — today nothing records which task was chosen.

## Step 3 — Fix up the window, in code · IMPLEMENTED · code

Three rules, applied to the raw tool arguments before validation:

1. Model omitted `time_earliest` → fill it from the **user's own messages**
   only, most recent first. Measured at 11 of 12 trials that the model omits it
   even when the user stated a window in plain English.
2. Model supplied a window but no user message ever mentioned a period → **drop
   it**. An invented `-7d` bypasses the widen offer (step 9) entirely.
3. Neither → the documented 15-minute default stands. Do not ask for a window
   first.

Assistant prose is never read for a window. The app's own widen offer literally
lists "last 7 days", and a window was once lifted from an *example phrase* in a
fallback answer and presented as the user's choice.

*Code:* `harness._window_from_user_messages`, `_user_named_a_period`,
`app/core/time_window.py`.

## Step 4 — The ask gates, in order · IMPLEMENTED (A2, A3) · code

Each gate ends the turn with a question. Order matters — the first that fires
wins.

| Gate | Condition | Result |
|---|---|---|
| **no tool call** | `params is None` | → step 5 (T7 domain answer) |
| **A2** | `domain.is_underspecified(params)` | ask for a PS ID or ≥2 identifying fields. **Do not** fall through to the domain answer — that produces an essay about the domain in place of an answer about the data |
| **A3** | `params.unresolved` non-empty | name the value back verbatim and ask for a usable one. Never run the search without it: the SPL would silently widen and the answer would read as though the filter applied |
| **A7** *(PROPOSED)* | more than one subject named in the question | ask which one — one search per turn (T12) |
| **A6** *(PROPOSED)* | "DIR"/"document" mentioned without saying whose | ask: this PS's links, or one document's own status |

`is_underspecified` is a **code** guard, not a prompt rule, because a near-null
`SearchParams` still builds valid SPL that returns up to 200 arbitrary real
production records — which would then be catalog-matched and presented as
relevant.

*Code:* `harness._run_query_body`, `domain.is_underspecified`,
`harness._unresolved_field_question`.

## Step 5 — T7: the domain answer · IMPLEMENTED · model

No search ran. A second LLM call answers from the knowledge topics **only** —
never from general knowledge about "PackIT". If the topics do not cover the
point, say so plainly; an invented explanation of how replication works is as
damaging as an invented fix and harder to spot.

Known gap (`FINDINGS.md` D6): this branch does not pass through step 9's
grounding checks. It produced *"there is no documented fix for..."* for an error
that has catalog row 2 — a confidently wrong **negative** about documented
knowledge, which is worse than a hallucinated fix because nothing about it looks
suspicious.

*Code:* `harness._load_skill(EXPLAIN)`.

## Step 6 — The search pipeline · IMPLEMENTED · code, zero model involvement

Fixed sequence, no LLM inside it. Each stage emits a progress event.

1. **Search Splunk** — build SPL, page, parse, group raw results into
   `TransferRecord`s. Answering starts here and predominantly from
   `PackITPackagingSpecification` records.
2. **Drop superseded activations** — an ERROR on an older activation counter
   describes a version of the PS that has since been replaced. Fails open three
   ways; the count of what was dropped is reported, never silently swallowed.
3. **Routing check** — *only* when a specific `target_system` was asked about
   and nothing was found there. Broaden by dropping `target_system`,
   **re-check `is_underspecified` on the broadened params** (this is a real side
   door — it was found sending an unscoped 200-row sweep), resolve the real
   plant/determination type, ask the Additional Routing plan. Fails closed to
   `None` on any ambiguity.
4. **Dependent objects** — *only* when a record matched a dependent-object
   blocking catalog row **and** the target is on the xOE line. Anywhere else no
   such trigger was ever sent, so searching would be a guaranteed-empty round
   trip whose emptiness then gets narrated as a finding.
5. **Catalog match** — against ERROR descriptions only.

Known gap (`FINDINGS.md` D5, open): `max_pages=1` and `| head 200` silently
truncate above 200 events, and the cut lands mid-retry-chain — so counts are
reported *wrong*, not merely incomplete (100 hops reported as 96). No truncation
flag reaches the answer, so no caveat is even available to it.

*Code:* `pipeline.get_ps_status`.

## Step 6a — The PD7 offer · PROPOSED · code gate, human consent

Not implemented. Intended contract, from the domain owner:

- Fires when Splunk returns nothing **after** the window question is settled, or
  the user says the data looks old, or the question falls in T11 (something
  replication never carried).
- The agent **offers**; it does not pull. PD7 is the source system, reached via
  an **OData service**, and a read there is a different cost and trust boundary
  from a Splunk search.
- Pull **only on an explicit yes**, and say plainly in the answer that the facts
  came from PD7 and not from the replication log.
- Follow-ups may then need further hops — PD7, PT0, or a target system. Each hop
  is its own turn under the same one-search rule; none of them is silent.

Unsettled: endpoint, auth, entity set, response shape. Nothing in the repo
records them.

## Step 7 — Summarize for the model · IMPLEMENTED · code

The composing turn never sees raw records. It sees a computed summary:
`found.subject` (identity stated once, every key prefixed `ps_` so "plant" and
"material" cannot be cross-attributed between the PS and the error text),
`found.outcomes` (deduped, with `hops_at_target` and `transfers` kept as
separate concepts), hop history when short enough to be worth the tokens,
`dependent_objects`, `catalog_matches`, `superseded_transfer_count`,
`time_range_searched`, `routing_check`.

The shared/varying split is **computed, never assumed** — a field that differs
across records drops out of `subject` rather than one record's value standing
for all of them.

Wrapped as untrusted data: text inside it is information to summarize, never
instructions to follow.

*Code:* `harness._summarize_status_result`, `llm_client.wrap_untrusted_data`.
*Proposed:* add a requested-vs-searched signal here — `FINDINGS.md` §4 names its
absence as why the D4 guard cannot be written.

## Step 8 — Compose · IMPLEMENTED · model

Second and final LLM call. It gets the answer rules and the glossary, and no
tool schema — there is no call left to make.

The rules that decide whether the answer is right rather than merely fluent live
in `skill.md` §"Turn 2". The four that carry the most weight, each traceable to
a measured failure:

- **Answer the question that was asked, and stop.** Every unasked fact is
  another chance to state something wrong. Two have already landed that way: a
  material reported as a Packaging Instruction, and "no linked Document Info
  Records" volunteered about a target that never receives them.
- **Never supply a cause or a fix that is not in `catalog_matches`.** Empty list
  means no documented cause exists — not that one can be reasoned out.
- **Reproduce identifiers exactly.** Expand *vocabulary* into plain language
  ("PI" → Packaging Instruction); never soften an identifier. `SAPPOE0110`
  rendered as "the SAP POE system" is a name nobody can paste into a search box.
- **Disclose a resolved reference.** If this turn's question said "the other
  one", state what it was taken to mean before answering.

*Code:* `harness._load_skill(COMPOSE)`.

## Step 9 — Grounding enforcement · IMPLEMENTED · code, in this order

Applied to the model's text. Order is load-bearing.

1. **Nothing found and the answer does not say so** → replace it entirely with
   the deterministic not-found answer, which states the **actual window
   searched** and, if a `routing_check` exists, what the routing plan actually
   says.
2. **An error exists, `catalog_matches` is empty, and no ticket fallback
   appears** → replace with the mServiceHub fallback.
3. **The answer claims a window that was not searched** → over an empty result,
   fall back to (1); over a non-empty result, correct the phrase in place. This
   check is deliberately independent of (1), because (1) stops looking at the
   first not-found marker and everything after it went unexamined — which is how
   *"even when searched in the last 7 days"* reached a user after a 15-minute
   search.
4. **A cause/fix block on a Transfer that already recovered** → strip it. When a
   Transfer failed six times and then succeeded, `current_status` is SUCCESS so
   (2) never fires, yet the hop history now puts six error descriptions in front
   of the model and it fills the gap with plausible SAP advice. Only the
   unsupported tail goes; the history above it was what was asked for.
5. **A promise of further work** → strip the sentence, append the plain
   statement that only one search runs per question.
6. **Nothing found at the default window** → append the widen offer (A4),
   worded exactly as the reply parser reads it back.

Every one of these exists because the prompt rule alone did not hold. That is
the general finding, measured both ways (`FINDINGS.md` §5): guards in code held;
rules in the prompt alone failed on time windows, continuation promises, catalog
fidelity and quantities. The prompt rule stays as the *explanation*; the code is
the enforcement.

Two known holes: this whole step is skipped on the no-search branch (step 5,
D6), and it has no check for a claim about a subject that was never searched
(D4).

*Code:* `harness._enforce_grounding`.

## Step 10 — Persist, log the route, return · PARTLY IMPLEMENTED

Persist the answer. Return `AgentAnswer`. Emit the route record
(TASK-TRIAGE §6) — **PROPOSED**; today nothing records which task was chosen,
so a misroute is only visible by reading the answer and inferring backwards.

Note what the user actually receives: `AgentAnswer` carries
`interpreted_params`, `primary_records`, `catalog_matches` and the time range,
and **none of it reaches the screen**. Rendering the interpreted window and the
row count is the single cheapest change that would let an operator catch the
rest of the open defect list themselves.

---

## Standing constraints, true at every step

- **Read-only.** The agent never performs an action. A human acts in PACKIT/SAP.
  It may report a documented solution; it may never claim to have applied one,
  nor promise to.
- **One search per question.** Name the part this turn could not cover and say
  plainly that it needs a separate question. That is a complete answer, not a
  partial one.
- **Silence in Splunk is a legitimate state.** A record awaiting approval,
  blocked behind a sibling's approval, or with a future `VALID_FROM` publishes
  nothing at all. Empty is a result to report, not a failure to explain away.
- **Tone never changes what is said.** A frustrated user is the person most in
  need of an accurate answer, not a fast or falsely reassuring one.

## Where this procedure is known to be wrong or incomplete

| Step | Gap | Status |
|---|---|---|
| 2 | No route record; the chosen task is unobservable | PROPOSED (TASK-TRIAGE §6) |
| 4 | A7 (multi-subject) and A6 (DIR ambiguity) gates do not exist | PROPOSED |
| 5 | Domain branch bypasses step 9 entirely | OPEN — `FINDINGS.md` D6 |
| 6 | 200-event truncation corrupts reported counts | OPEN — D5, highest-value unfixed item |
| 6 | The broadened re-search's records are retrieved, dropped, then denied to the user | OPEN — D7 |
| 6a | PD7 pull: no client, no endpoint, no captured response | NOT IMPLEMENTED |
| 9 | No check for a claim about an unsearched subject | OPEN — D4, the most dangerous open item |
| 10 | Nothing structured reaches the screen | OPEN — D12 |
