# Agent briefing — PACKIT Operations Agent regression run `baseline`

Read this before analysing anything. It is the shared context for every agent
in the workflow.

## The product

A read-only chat app answering questions about Packaging Specification data
flow. Architecture (see `docs/ARCHITECTURE.md`, `docs/adr/0001-*`):

1. **LLM turn 1** parses the user's question into a `get_ps_status` tool call.
   Arguments are validated in `app/core/domain.py::parse_search_params` —
   anything out-of-shape is silently dropped to `None`, never bounced back.
2. **One deterministic pipeline run** (`app/agents/packspec_status/pipeline.py`):
   Splunk search → transform/group → dependent-object branch → catalog match →
   optional Additional Routing check. No LLM inside it.
3. **LLM turn 2** composes prose from a condensed summary of the result.
4. `app/core/harness.py::_enforce_grounding` overrides the prose in code if it
   claims a fix with no catalog match, or fails to acknowledge an empty result.

Exactly two LLM calls per question. **One tool call per question — no
continuation, no second search after the answer is composed.**

## What turn 2 actually receives

`harness._summarize_status_result` sends only:

```
primary_records[] : message_type, target_system, ps_id, status, description, hop_count
dependent_objects : same shape, split into DIR / cockpit lists
catalog_matches[] : seq_nr, error_category, responsible, summary, solution
time_range_searched   (e.g. "the last 15 minutes")
routing_check     : plant, determination_type, configured_target_systems,
                    requested_target_system, requested_target_was_configured
```

**Plant, determination type, usage, timestamps and message IDs are NOT sent.**
A specific plant code or determination type in a reply, absent a routing_check
and absent that text in a description, is therefore *fabricated*.

Between turns, only user questions and final assistant prose persist. The data
block does not. Every follow-up must re-derive its tool arguments from prose.

## The frozen backends

Splunk and Additional Routing are replayed from `regressionSuite/harness/`
over real HTTP; the app, its HTTP clients and the LLM all run for real. The
corpus is time-shifted so its newest event always sits 20 minutes before the
run — so the app's default 15-minute window always returns zero rows, and
`-24h`/`-7d` always return everything.

## Ground truth — the frozen corpus (257 events → 55 TransferRecords)

| PS | target(s) | plant | det | status | description | records | hops |
|---|---|---|---|---|---|---|---|
| 00000000040001253724 | SAPP870110 | 0110 | SHIP | ERROR | `SNR13 not found/ Mark for deletion` | 1 | **100** |
| 00000000040001399187 | SAPP990110 | 0500 | SHIP | ERROR | `SNR13 not found/ Mark for deletion` | 1 | 100 |
| 00000000040001497551 | SAPPOE0110 | 929P | SHIP | ERROR | `Cockpit master data dependent object still in progress` | **48** | 1–2 |
| 00000000040000434427 | SAPP720110 **and** SAPPOE0110 | 0780 | SHIP | ERROR | `T141 Bom item status Invalid for material 6000.409.798 in plant 0780` / `…in plant 078W\nCockpit Data Model Updated` | 2 | 1 |
| 00000000040000681411 | SAPPOE0110 | 1810 | SHIP | ERROR | `SNR13 Plant Status Invalid` | 1 | 1 |
| 00000000040001399043 | SAPP810110 | 8160 | RCPT | ERROR | `Error while saving the Det rule: F00C2G8057BA18740…` | 1 | 1 |
| 00000000040000588527 | SAPPOE0110 | — | — | **SUCCESS** | `MARA / MARM data has been updated in database succesfully` | 1 | 3 |

Catalog matches (verified against `db/docupediaContext/error_catalog.yaml`):

- `SNR13 not found/ Mark for deletion` → row **2**, Target Error, responsible Plant.
  Solution: *"Create the missing number, or remove the deletion flag (also check
  valid x-plant and plant status). If the deletion flag is correct, delete the
  Determination Record (and consider the PackSpec) and inform the PST Team via
  mServiceHub."*
- `T141 Bom item status Invalid…` → row **15**, Target Error, Plant.
  Solution: *"Change the packaging material's plant status to 40 (valid)…"*
- `Cockpit master data dependent object still in progress` → row **57**, Source
  Error. Solution: *"Check entries in TC Z0MP_BUS_ERR_LOG and correct the source
  error on PD7. If no entries exist for the PS, raise a ticket with mServiceHub
  (Service+: PACKIT-S4)…"* Row 57 also triggers the dependent-object branch.
- `Error while saving the Det rule…` → rows **31** (Technical) and **24** (Target).
- SUCCESS records are never catalog-matched — `catalog_matches` is empty, so any
  quoted fix on a SUCCESS record is invented.

Routing plan (frozen): plant `0110`/`SHIP` → `SAPP870110` **only**.

## Where the evidence is

`regressionSuite/runs/baseline/`

- `<scenario>/NN_<query>.txt` — query, what it probes, **verbatim reply**,
  verdict, and the **SPL actually sent** with its window and row count
- `<scenario>/shots/NN_*.png` — full-page screenshot after each turn
- `<scenario>/backend_calls.json` — every backend call that turn caused
- `summary.json` — 15/28 turns passed, 13 failed
- `requests.jsonl` — the whole run's backend traffic

`regressionSuite/scenarios.py` holds each turn's expectations and a `probes`
field explaining the failure mode it was built to expose.

## Rules for your analysis

1. **Evidence or it didn't happen.** Every finding cites a file, a quoted reply
   fragment, and where relevant the SPL that was actually sent. The SPL log is
   the ground truth about what the app did; the prose is the claim under test.
2. **Separate three categories, explicitly:**
   - **PRODUCT DEFECT** — the app did something wrong.
   - **HARNESS DEFECT** — the expectation/regex was wrong and the app was fine
     (a false FAIL). These matter: they corrupt the signal.
   - **MISSED DEFECT** — a check *passed* but the reply is wrong anyway. Read
     every reply, not only the failing ones.
3. **A failed check is not automatically a bug**, and a passed check is not
   automatically correct. Judge the reply against the ground truth above.
4. Rank by user impact for an operations engineer trusting this tool in
   production. A confidently wrong answer outranks a clumsy one.
5. Do not fix anything. Report only.
