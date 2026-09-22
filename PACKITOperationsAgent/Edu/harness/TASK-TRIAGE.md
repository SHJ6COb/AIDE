---
artifact: task-triage
layer: task (routing + procedure)
summary: Which task a request is, what that task needs to run, and the points at which the agent must ask instead of answering.
status: draft — encodes today's behaviour plus the intended PD7 hop; every row marked EVIDENCED or INFERRED.
---

# Task triage

## Why this file is not called `routing.md`

`app/agents/packspec_status/knowledge/routing.md` already exists and is
**message routing**: the Additional Routing plan, PT0/VITAA, why a Transfer
reached (or never reached) a target system. That is product knowledge about
*replication* — it stays true whatever the agent is doing, so it passes the
filing test and already has a home.

This file is **task triage**: deciding which kind of request is in front of the
agent, and whether it can be answered at all. It is true only because of what
*this agent* does. The two would be indistinguishable under one name, and the
collision is not hypothetical — "routing" appears in `pipeline.RoutingCheck`,
`app/tools/routing_plan.py` and `regressionSuite/harness/routing_fixture.py`,
all of them the *message* sense. "Triage" carries the right connotation too:
the first decision is not "what is the answer", it is "what is this, and can I
safely take it".

Nothing here restates product knowledge. Where a task depends on a domain fact,
it cites the topic file that owns it.

---

## 1. The triage decision, in one shape

Every turn resolves to exactly one of three outcomes:

| Outcome | Meaning |
|---|---|
| **ANSWER** | a task in §2 was identified and its payload is complete — run it |
| **ASK** | a task was identified but a precondition failed, or two tasks are equally plausible — put one question back to the user and stop |
| **DECLINE** | the request is outside what this agent does at all (§2, T8/T9) |

**A forced guess between two plausible tasks is the most expensive failure
available**, because every downstream step then executes correctly on a wrong
premise and the answer reads as confident. This is measured, not asserted:
`FINDINGS.md` D4 is the canonical case — the agent answered a two-PS comparison
by reporting a search outcome for a PS that appears in **zero** of the run's SPL
queries. The reply was indistinguishable from a genuine empty result, and the PS
was really in ERROR. Ask cost is one clarifying question; wrong-premise cost is
an engineer acting on a fabrication.

---

## 2. The task table

Drawn from `regressionSuite/scenarios.py` (28 adjudicated turns over 14
scenarios, each with a `fixture_basis` tying it to real captured data),
`skill.md`'s own branch structure, the live-session questions recorded in S11's,
S13's and S14's `fixture_basis`, and the branch points in
`app/core/harness.py`. Every row is labelled with its evidence.

Payload column: what the task needs before it can run. `SearchParams` fields
are the tool's (`harness._GET_PS_STATUS_TOOL`); result fields are what
`harness._summarize_status_result` hands the composing turn.

| # | Task | Trigger shape | Payload it needs | Evidence |
|---|---|---|---|---|
| **T1** | **Status of a named subject** — what is the current state of this PS / Determination Record | "what's the status of PS X", "what's happening with X", "did X complete" | in: `ps_id` (or ≥2 identifying fields), `time_range`. out: `found.subject`, `found.outcomes[].status/description`, `time_range_searched` | **EVIDENCED** — S01/q1, S03/q1, S05/q1, S07/q1, S10/q1, S11/q1, S12/q1 |
| **T2** | **Diagnose a failure and give the documented fix** — why is this stuck, is there a known fix | "why is X stuck", "what's wrong with X", "is there a documented fix" | as T1, plus `catalog_matches` (**and nothing else may supply a cause or a fix**), plus `dependent_objects` when the block is a dependent object | **EVIDENCED** — S01/q4, S02/q1, S10/q1 |
| **T3** | **Destination check** — did it reach system Y, which targets did it reach, where is it supposed to go | "did X reach SAPP790110", "which target systems did X transfer to", "where should it go instead" | in: `target_system` **plus** a subject; out: `found.outcomes[].target_system`, `routing_check` | **EVIDENCED** — S04/q1–q3, S06/q3, S13/q1–q2, S14/q1 |
| **T4** | **Identity / attribute readout** — object key, plant, determination type, supplier, linked documents | "which plant and det type", "object key details", "any DIR linked to this PS" | out: `found.subject` only — this task needs **no** outcome data and must not recite any | **EVIDENCED** — S01/q3, S08/q3, S11/q2–q3, S14/q3 |
| **T5** | **History and counts** — the hop chain, error logs per hop, how many attempts | "how many processing attempts", "error logs recorded in those hops", "are those two the same error" | out: `outcomes[].hops[]` (present only ≤ `_MAX_HOPS_SERIALIZED`), `hops_at_target` vs `transfers`, `earlier_errors_resolved`, `superseded_transfer_count` | **EVIDENCED** — S01/q2, S02/q2, S03/q2, S14/q2, S14/q4 |
| **T6** | **Widen / re-run over a different window** — a bare window reply, or "try 7 days" | "24 hours", "try the last 7 days then" | in: the *previous* real question + the new window. No new subject resolution — the rewrite is done in code (`harness._resolve_window_reply`) precisely because reference resolution here is unreliable | **EVIDENCED** — S05/q2, S12/q2 |
| **T7** | **Domain explanation** — how does this work, what does X mean | "what's a Determination Record", "how does Additional Routing decide" | no search. Needs the knowledge topics only. **Must not be reached by a failed live-data question** — see A2 | **EVIDENCED** — `skill.md` "Turn 2 (domain mode)"; the misroute is S02/q3 |
| **T8** | **Action request** — should I retrigger, give me the transaction to fix it | "should I just retrigger it", "tell me the steps to fix it yourself" | no search. The agent is **read-only**; a human acts in PACKIT/SAP. Answer from `catalog_matches` if one exists, else mServiceHub — never from general SAP knowledge | **EVIDENCED** — S02/q4, S10/q2 |
| **T9** | **Off-topic** | "what's the capital of France?" | none. One or two sentences of scope statement. **No search may run** — a near-null `SearchParams` still builds valid SPL over real production data | **EVIDENCED** — S06/q1; guard is `domain.is_underspecified` |
| **T10** | **Challenge / false premise** — the user asserts a fact the data does not support | "are you sure? I was told it failed at SAPP870110 with an SNR13 error", "so at least one went through OK, right?" | out: whatever this turn's search returned. The task is to **not adopt the premise** and to say the record does not corroborate it | **EVIDENCED** — S09/q2, S03/q3 |
| **T11** | **Source-system (PD7) pull** — the question is about something replication never carried | "why was the stacking factor changed", "what did it look like before", "what changed between versions", "why has nothing arrived at all" | in: user consent (A5), then a PD7 **OData service** call. **NOT IMPLEMENTED** — no PD7 client exists in `app/tools/` | **INFERRED** from `knowledge/splunk-payload.md`'s cannot-table, `knowledge/packaging-specification.md` ("This is what the PD7 pull is for"), `knowledge/determination-record.md`'s dependent register ("PD7 OData service — the pre-publish stage, a routing concern"), and the domain owner's stated flow. **Confirmed by**: one captured real user question of this shape, or one PD7 OData response body in the repo. Neither exists today. |
| **T12** | **Multi-subject comparison** — two or more PSs in one question | "compare PS A and PS B — which is worse", "which target system is each of them on" | **structurally impossible in one turn**: one tool call per question (ADR-0001). Route to A7, never to T1 | **EVIDENCED** — S08/q1–q3, and `FINDINGS.md` D4 for what happens when it is not |

### Rows deliberately not in this table

- *Message-type-specific lookups* (DIR status by document number, Cockpit Master
  Data) are **not** a separate task. They are T1/T2 with `message_type` and
  `document_number` set. `skill.md` already documents the one trap worth naming,
  and it is a triage trap, so it appears here as **A6**.
- *"Which activation is live"* is not a task; `pipeline.select_live_activations`
  decides it before the composing turn ever sees the records.

---

## 3. The ask outcomes

Each row: what fires it, what to ask, and where the trigger is (or should be)
enforced. **Enforced in code** matters — `FINDINGS.md` §5 is the measured
finding that guards in code held and rules in the prompt alone did not, four
times over (D1, D4, D8, D10).

| # | Ask | Trigger | Where enforced |
|---|---|---|---|
| **A1** | *"Which PS do you mean?"* | A reference ("this PS", "the other one", "that plant") that the immediately preceding 1–2 turns do not resolve to exactly one entity. Never reach further back; a discourse topic ("plant 0580's failures") is not a specific ID within it | `skill.md` turn-1 rules only — **prompt-enforced, no code guard**. Measured failure: a follow-up silently resolved to an unrelated PS ID mentioned three turns earlier |
| **A2** | *"I need a PS ID, or two or more of plant / determination type / message type / target system."* | `domain.is_underspecified(params)` is true: no `ps_id`/`document_number`, no free-text term, and fewer than two identifying fields (or one plus `status`) | **Code** — `harness._run_query_body`. Note the split it enforces: params-present-but-broad → **ask**; no tool call at all → T7. Sending a broad live-data question to T7 produces an essay about the domain in place of an answer (S02/q3) |
| **A3** | *"I couldn't interpret `<value>` as a `<field>`."* | `params.unresolved` non-empty — the user named something that could not become a filter, so the SPL would silently widen | **Code** — `harness._unresolved_field_question`. Names the value back verbatim. Live origin: "target system P87" lost its `host=` clause, searched every system, and confidently named a system the user never asked about (S13) |
| **A4** | *"Widen the search to which? 1 hour / 4 hours / 24 hours / 7 days"* | Zero primary records **and** `time_range == TimeRange.default()` (15 minutes). Silence at 15 minutes is the common case for live data, not an unusual one | **Code** — `harness._append_widen_offer`, worded to exactly what `time_window.bare_window_reply` can read back. The reply is T6 |
| **A5** | *"Splunk has nothing here. Do you want me to read the source system (PD7) directly?"* | (a) nothing found after the window has already been widened; **or** (b) the user says the data looks old/stale; **or** (c) the question falls in `splunk-payload.md`'s cannot-table (T11). **Pull only on an explicit yes** | **NOT IMPLEMENTED** anywhere. INFERRED from the domain owner's stated flow. Must be an ask, not an automatic hop: PD7 is the source system and a read there is a different cost and a different trust boundary from a Splunk search |
| **A6** | *"Do you mean this PS's linked documents, or the status of one specific document?"* | The user says "DIR"/"document" without making clear which. The two need **opposite** params: the PS's own links come from `found.subject.ps_document_links` with `message_type` **unset**; a document's own status needs `message_type=DocumentInfoRecord` + `document_number` | `skill.md` states the mapping but not the ask. A DIR payload carries no PS ID, so guessing wrong guarantees zero results — a silent, confident nothing. **EVIDENCED** by S11 existing at all (the live app could not answer "do we have any DIR linked to this PS?") |
| **A7** | *"I can search one subject per question — shall I take PS A, or PS B?"* | Two or more distinct subjects named in one question (T12) | **NOT IMPLEMENTED.** `FINDINGS.md` §4 names the fix: compare PS IDs in the question against `params.ps_id` and refuse any claim about a PS this turn did not search; `_summarize_status_result` carries no requested-vs-searched signal to do it with. Today the model is free to answer, and did — three times, wrongly |
| **A8** | *"Do you mean Usage (Regular / Alternative), or Sales Channel (OE / OES / IAM)?"* | The user says **"Pack Usage"**. Splunk's own dashboard labels the Sales Channel field "Pack Usage", so the phrase is genuinely two-valued | `skill.md` currently says "you must judge from context". **INFERRED** that this should be an ask instead: the two are different filters over different populations and a wrong pick narrows silently. **Confirmed by**: one captured user turn using the phrase. None in the corpus today — this is a predicted collision, not an observed one |

### The ask that must *not* happen

Do not ask for a time window before searching. If the user gave none, search the
15-minute default, find nothing, and **then** offer widths (A4). This is
explicit in `skill.md` and is why `harness` strips a model-invented
`time_earliest` when no user message mentioned a period — a model free to invent
`-7d` bypasses the offer entirely, which was seen live.

---

## 4. Silence is a state, not a failed search

This is the single most consequential triage fact, and it changes what "nothing
found" is allowed to mean.

A record awaiting approval, blocked behind a sibling's approval, or with a
future `VALID_FROM` **publishes nothing at all** — not an error, not a pending
event, nothing. The mechanism belongs to
`knowledge/determination-record.md` ("Validity gates publication") and
`knowledge/splunk-payload.md`; what belongs here is the consequence for triage:

- An empty result is a legitimate outcome to **report**, never a lookup failure
  to apologise for, and never grounds for inventing a cause.
- The ladder on empty is: state the window searched → A4 (widen) → A5 (offer
  PD7) → stop. Nothing in that ladder guesses at *why*.
- The one thing an empty result must never become is a claim about a subject
  that was never searched (D4).

---

## 5. A routing rule that leaked into product knowledge

`knowledge/splunk-payload.md`'s closing section, **"What it cannot — and where
to go instead"**, is a *task-layer* rule sitting in a product-knowledge file. Its
table maps a question shape to a next step ("no further searching helps — the
source system is the only place it exists"). That is triage: it tells the agent
what to *do*, and it stops being true the moment the agent's job changes.

It is extracted here as **T11 + A5**. The product knowledge underneath it —
which fields are source-only, that a superseded version's values exist nowhere,
that a not-yet-valid record publishes nothing — is genuine and stays in
`splunk-payload.md` and `packaging-specification.md`.

**Action for later, not now:** once T11/A5 are implemented, delete that section's
*prescription* from `splunk-payload.md` (the "where to go instead" half and its
closing paragraph), keeping the "what it cannot answer" facts. Do not delete it
before then, or the behaviour disappears with the text. This file does not modify
it.

---

## 6. Log the route

A misroute is currently only visible by inference — by reading an answer,
noticing it is about the wrong thing, and reconstructing why. `FINDINGS.md` D9
and D4 were both found that way, by hand, after the fact.

Emit one record per turn, alongside the existing `on_step` progress events:

```
route = {
  "conversation_id", "turn",
  "task":            "T1" | ... | "T12" | null,   # null = no task identified
  "outcome":         "ANSWER" | "ASK" | "DECLINE",
  "ask":             "A1" | ... | "A8" | null,
  "subjects_named":  ["00000000040001253724", "00000000040001399187"],  # from the question
  "subject_searched": "00000000040001253724",     # params.ps_id as actually sent
  "window_source":   "user" | "default" | "carried_forward" | "code_rewrite",
  "searches_run":    1,
  "pd7_offered":     false,
  "pd7_pulled":      false,
}
```

Three fields earn their place specifically:

- **`subjects_named` vs `subject_searched`** — the exact D4 signal. Whenever
  these disagree, any claim about the difference is fabricated by construction,
  and the check is mechanical rather than a reading exercise. This is the same
  signal `FINDINGS.md` §4 asks `_summarize_status_result` to carry.
- **`window_source`** — D1 and D11 were both invisible because nothing recorded
  *where* the window came from. `harness` already distinguishes all four cases
  in code; it just does not say so.
- **`task` + `ask`** — makes "the triage chose T7 for a live-data question"
  (S02/q3) a queryable event rather than an anecdote.

The regression suite already reads the SPL log per turn
(`runs/<name>/requests.jsonl`); this record sits beside it, and `scenarios.py`
gains an `expect_task` assertion in the same shape as its existing
`expect_window` and `expect_searches`.

---

## 7. What this artifact does not settle

- **T11/A5 have no implementation and no captured evidence.** The OData service
  on PD7 is named in `knowledge/determination-record.md` as a registered
  dependent, deliberately undocumented there because it is "a routing concern".
  This file is where that concern lands, but it can only state the intended
  contract — not the endpoint, auth, entity set, or what a response looks like.
- **A1 has no code guard**, and `FINDINGS.md` §5 predicts a prompt-only rule
  will not hold. Whether ambiguous-reference detection is codifiable (compare
  entities named in the last two turns against `params`) is open.
- **Whether a window should persist across a conversation** (D11) is an
  unresolved product question, and it decides whether `window_source:
  "carried_forward"` is a normal state or a defect.
- **The task list is drawn from a corpus of 14 scenarios plus a handful of live
  sessions.** It is the best available evidence of what this agent gets asked; it
  is not a survey of real usage. A week of production questions would confirm or
  break the T1–T5 split, which is the split most likely to be wrong.
