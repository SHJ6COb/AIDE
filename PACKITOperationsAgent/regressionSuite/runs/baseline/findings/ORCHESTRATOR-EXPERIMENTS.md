# Controlled experiments run by the orchestrator

Direct evidence, gathered outside the Playwright run, about the two findings
that matter most. Both were run against the real configured LLM
(Model Farm, `gpt-4o-mini`) with the real `skill.md` + `CONTEXT.md` system
instruction and the real `_GET_PS_STATUS_TOOL` schema.

## Experiment 1 — where the time-window defect actually lives

Turn-1 argument extraction was called directly, 5 trials per cell, and the
resulting `SearchParams.time_range.earliest` recorded after real
`parse_search_params` validation.

| Case | Expected | CURRENT schema | Reworded schema |
|---|---|---|---|
| First turn, "in the last 24 hours" | `-24h` | **1–2 / 5** | **3 / 5** |
| First turn, "in the last 7 days" | `-7d` | **0 / 5** | **0 / 5** |
| Follow-up, window established one turn earlier | `-24h` | **0 / 5** | **0 / 5** |
| User accepts the window the app itself offered ("Try the last 7 days then.") | `-7d` | **0 / 5** | **0 / 5** |
| No window ever mentioned | `-15m` | 5 / 5 | 5 / 5 |

### What this rules out

**It is not `domain.py::_validate_time_range` dropping a malformed value.**

Two testers independently attributed the defect to that function silently
downgrading an out-of-shape value to the default. The first version of this
experiment could not actually distinguish that from the model omitting the
field, because it recorded `SearchParams.time_range.earliest` — a
*post*-validation value. So it was re-run capturing the **raw tool-call
arguments before validation**:

| Case | trials | model omitted the field | validation dropped a supplied value | supplied and kept |
|---|---|---|---|---|
| First turn, "in the last 7 days" | 4 | 4 | 0 | 0 |
| First turn, "in the last 24 hours" | 4 | 3 | 0 | 1 |
| User accepts the offered window | 4 | 4 | 0 | 0 |
| **total** | **12** | **11** | **0** | **1** |

`time_earliest` was **absent from the tool call in 11 of 12 trials**, and
validation rejected a supplied value **zero times**. `_validate_time_range` is
behaving exactly as specified and is not implicated. Any fix aimed at it would
change nothing.

**It is not the `skill.md` "only the user's own message, this turn" clause.**
That clause was the obvious suspect (it reads as an instruction to discard a
window established in an earlier turn). It was rewritten to explicitly permit
carrying a window forward and to explicitly permit accepting an offered
window, and re-tested: **0/5 on both follow-up cases, and it made the
first-turn case worse (2/5 → 0/5)**. The clause is not the cause.

**Rewording the tool-schema description is not a sufficient fix either.** A
much more directive description — mandatory-when-mentioned, with explicit
phrase→value mappings — moved the 24-hour case from 1/5 to 3/5 and moved
nothing else at all.

### What this establishes

`gpt-4o-mini` does not reliably populate `time_earliest` from natural language,
under any prompt wording tried. The extraction is roughly a coin flip on the
first turn and near-zero on follow-ups. Two independent consequences follow,
and they need separate fixes:

1. **Extraction** must not depend on the model. This codebase already solves
   exactly this class of problem in code rather than prompt — `_is_underspecified`
   and `_enforce_grounding` are both code-level guards written precisely
   *because* they must not depend on the model judging correctly. A
   deterministic natural-language window parser over the user's own message,
   applied when the model omits `time_earliest`, is the same pattern.
2. **The composing turn contradicts the window it was given.** In
   `S05/02_q2_widen` the model was handed `time_range_searched = "the last 15
   minutes"` and wrote *"even when searched in the last 7 days"*. That is a
   fabrication about the product's own behaviour, independent of defect 1 —
   fixing extraction would mask it, not fix it. It needs a code-level check,
   the same shape as `_enforce_grounding`'s existing not-found check.

## Experiment 2 — the routing fallback bypasses the scope guard

`pipeline.py::_check_routing_if_target_missing` broadens a failed target-scoped
search with `replace(params, target_system=None)` and sends it to Splunk
without re-checking `_is_underspecified`. Executed directly against S06 q3's
real parameters:

```
original params  (target_system=SAPP870110, status=ERROR)  underspecified? False
broadened params (target_system=None,       status=ERROR)  underspecified? True   <- sent to Splunk anyway
```

The SPL that actually reached the backend during the run:

```
search index=pdbb sourcetype=Native "<d:BusinessStatus>ERROR</d:BusinessStatus>" | head 200
```

This is byte-identical in shape to the query the guard **refused** one turn
earlier for "Show me all the errors" (S06 q2, 0 Splunk jobs). It returned 0
rows here only because the window had already collapsed to 15 minutes. At the
window the user actually asked for, against the real production index, it is an
unscoped sweep of every ERROR across every plant — exactly the failure mode
`_is_underspecified` was written to prevent, reachable through a side door.

Severity is coupled to defect 1: fixing the time window makes this one *more*
dangerous, not less.

## Experiment 4 — silent truncation at the page cap CORRUPTS counts (new defect)

Not in any tester's or the critic's register. `splunk_client.search` defaults to
`max_pages=1` and `build_spl` appends `| head 200`, so a search matching more
than 200 events is truncated. The pipeline never asks for a second page, and
nothing anywhere signals that truncation happened.

The damage is worse than "some records are missing", because the cut lands
mid-retry-chain. Executed against the frozen corpus at `-24h`, using the exact
SPL the broadened routing re-search produces:

```
events genuinely matching the search : 254
rows the app receives (| head 200)   : 200
silently dropped                     : 54

hop_count the app would then report:
  PS 00000000040001253724 -> 96    (ground truth: 100)
  PS 00000000040001399187 -> 88    (ground truth: 100)
```

So the app does not merely lose 54 events. It reports **wrong counts for the
records it did return**, as plain fact, with no caveat available to the model —
`hop_count` is a bare integer in the summary and carries no "at least" or
"truncated" flag. "How many processing attempts were there?" is a question this
product is explicitly built to answer, and at scale it answers it wrongly.

Reachability is not hypothetical: 254 of the corpus's 257 events match a single
realistic query, and a real PS retried more than 200 times is exactly the kind
of stuck transfer an operations engineer investigates.

Severity: **high**. Independent of every other defect — it needs its own fix
(paginate until short, or propagate a truncation flag into the summary so the
answer can say "at least 200"). Note it interacts with the scope-guard bypass:
that bypass is what generates the broad, >200-row searches in the first place.

## Experiment 3 — the unfulfilled continuation promise

All three `S08` turns end with a promise to search the second PS
(`00000000040001399187`). Across the entire run's backend log:

```
any SPL mentioning 399187 -> False
```

28 Splunk jobs were issued in the run; none searched it. The architecture runs
two LLM calls and one tool call per question and then stops, so the promised
search cannot ever happen. The UI shows no pending state — the composer is
idle and there is no spinner, so silence reads as "nothing to report."
