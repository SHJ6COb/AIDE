# packspec-status agent — Technical Specification

See [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md) for the overall harness pattern this agent runs inside. This document covers what's specific to this one agent.

## Strict Input/Output Context

**Input Context** (`SearchParams`, `app/core/domain.py`) — two tiers. The dashboard this agent's data comes from only exposes 7 filters (Time Range, PS ID, Target System, Pack Usage, Plant, Status, Message Type), but a user can reasonably ask about any field that actually appears in a payload — confirmed full-text-searchable regardless of whether it's a dashboard filter (the live Postman test in Phase 0 searched on a bare Message Type name and a bare PS ID, neither an "extracted field"). So:

**Tier 1 — validated core fields**, each either `null` or passing a fixed enum/pattern check before use; the LLM's tool-call arguments are never trusted blindly:

| Field | Type | Notes |
|---|---|---|
| `ps_id` | `str \| None` | pattern-checked (numeric, zero-padded per real examples) |
| `plant` | `str \| None` | pattern-checked (`WERKS`) |
| `supplier` | `str \| None` | pattern-checked |
| `customer_index` | `str \| None` | pattern-checked (`PACKINDEX`) |
| `matnr` | `str \| None` | pattern-checked material number |
| `document_number` | `str \| None` | pattern-checked, `DocumentInfoRecord` only |
| `determination_type` | `DeterminationType \| None` | enum: `SHIP, RCPT, ZFER, STOC, PALE, DOLL` |
| `message_type` | `MessageType \| None` | enum: `PackITPackagingSpecification, DocumentInfoRecord, PackITPackagingCockpitMasterData` |
| `usage` | `str \| None` | enum: `R, A1, A2, A3, A4` (`ABRVW`) |
| `sales_channel` | `str \| None` | validated against known values (`OE`, `IAM/OES`, ...) — `PACK_USAGE` field |
| `time_range` | `TimeRange` | resolved to concrete `earliest`/`latest` Splunk time strings before any API call, capped (e.g. 30 days max). Defaults to **last 15 minutes** when the user doesn't specify a window — no clarification round-trip; if nothing's found, the no-match answer offers to widen the window |

An out-of-enum or unparseable value from the LLM is never silently passed to Splunk — but it's also never bounced back to the LLM in a retry loop. It's treated as `None`, `get_ps_status` runs with whatever valid fields remain, and if that isn't enough to identify anything, the single resulting answer honestly says so and asks the user for the missing piece (the same no-match path used when a search legitimately finds nothing). No internal "fix your own arguments" round trip — see the token-minimization principle in [`ARCHITECTURE.md`](../../ARCHITECTURE.md).

**Tier 2 — guarded free-text overflow** (`additional_terms: list[str]`): anything the user mentions that doesn't map to a Tier-1 field (brand, activated-by username, an error-text fragment). Not dropped — refusing it would cripple the agent for anything not in Tier 1, and the dashboard itself proves free text is a valid way to query this data. But every term passes a strict guardrail before use (see `components/splunk-client/TECHNICAL_SPEC.md`'s SPL construction guardrails): character allowlist, length cap, and outright rejection (not escaping) of anything containing a pipe or other SPL-special character. `build_spl(params) -> str` is a pure, fully unit-testable function, including negative tests for rejected terms.

**Output Context** (`AgentAnswer`, `app/agents/packspec_status/pipeline.py` + `app/core/harness.py`): `{query, interpreted_params: SearchParams, primary_records: list[TransferRecord], dependent_objects: DependentObjectsView | None, catalog_matches: list[CatalogMatch], plain_language_answer: str}`. This is the only shape the UI ever sees.

`catalog_matches` is a **list**, not one-or-`None` — revised from the original single-`CatalogMatch` design. A single error description can legitimately match more than one actionable catalog row at once (confirmed real, see `components/catalog/TECHNICAL_SPEC.md`); rather than have code silently guess which one is "the" answer, `match_catalog` returns every actionable match and the skill's answer-composition rules (`skill.md`) present all of them, letting the end user judge. Purely informational rows (`HINT`/`No action required`) are filtered out before this list is built — they were never a candidate fix.

`get_ps_status` itself returns a narrower `StatusResult` (`primary_records`, `dependent_objects`, `catalog_matches` — no `query`/`interpreted_params`/`plain_language_answer`, since those are the harness's job, not the deterministic pipeline's). The harness wraps `StatusResult` into the full `AgentAnswer` once the LLM composes `plain_language_answer` in its second turn.

## Procedure — `get_ps_status(params) -> StatusResult`, one deterministic pipeline, zero LLM involvement inside it (see [ADR-0001](../../adr/0001-single-deterministic-pipeline-tool.md))

The LLM never sees or drives these steps individually — it calls `get_ps_status` once with `SearchParams` and gets back one already-summarized result. Internally:

1. **Primary search** (`splunk_client.search`): run against the interpreted `SearchParams`, scoped by `message_type` if given, else unscoped across all three. Capped at 200 results per call; paginate via `offset` if more are genuinely needed (see [`components/splunk-client`](../../components/splunk-client/TECHNICAL_SPEC.md) — larger single requests get hard-blocked by the API gateway).
2. **Transform** (`splunk_xml_parser` + `transform`): produces `TransferRecord`(s) grouped by Message ID. Envelope parsing branches on hop stage (plain JSON pre-consumption vs. Atom/OData at the Target-processed hop), not on Message Type — see [`components/transform`](../../components/transform/TECHNICAL_SPEC.md) for the full, corrected shape.
3. **Branch**: if a `TransferRecord` is `PackITPackagingSpecification`-typed AND its status/description matches the dependent-object-blocked pattern (Docupedia catalog rows 57/58) → look up the dependent object(s) to find out *which* is stuck. Otherwise skip — no wasted work.
4. **Catalog match**: if any `TransferRecord`'s status is an error, extract its description text and look it up (`re.DOTALL` required — see [`components/catalog`](../../components/catalog/TECHNICAL_SPEC.md)).
5. **Compose result**: produce the already-summarized `StatusResult` the LLM will turn into `plain_language_answer`, following the strict grounding rule — never include a Suggested Action unless the catalog match returned a real row.

## Confidence status

**`get_ps_status` itself (the full assembled pipeline, `app/agents/packspec_status/pipeline.py`) is now implemented and live-verified end-to-end** against 3 real PS IDs, cross-checked against `screenshots/results/*.png` dashboard captures:
- `00000000040000054543` (Business Error, SNR13 not found, 2 targets) — `primary_records`/`catalog_matches` (seq_nr 2) matched the dashboard exactly.
- `00000000040000908526` (Business Error, Cockpit-blocked) — the dependent-object branch correctly triggered (`on_step` fired "Checking dependent objects..."), `catalog_matches` correctly surfaced row 57; the dependent-object lookup itself came back empty, confirmed to be real data (not a bug) — see `components/transform/TECHNICAL_SPEC.md`'s Dependent Object blocking section.
- `00000000040001498023` (all-Success PT0/VITAA flow, 4 records across 2 message types) — this run caught and fixed a real bug in `transform.py`'s target-derivation (see that spec's "Fixed bug" section); after the fix, every record's status/description matched the dashboard exactly, including a 9-line multi-message success description.

Validated against an extended live Splunk investigation (thousands of real events across multiple time windows, cross-checked against the actual dashboard), not just Phase 0's original single-example Postman test:

- **HIGH, confirmed at scale**: `PackITPackagingSpecification` Business Error path — envelope, description derivation, Target System, Message ID stability, cross-checked byte-for-byte against a real dashboard screenshot.
- **HIGH, confirmed at scale**: Technical Error catalog matching (91/91 real examples, given `DOTALL`).
- **Fixed**: the SNR13/Business-Error catalog family originally failed to match real message text (167/168 failures in one live sample) — a content problem in rows 1, 2, 3, not a matching-strategy problem. Patterns loosened and re-validated at a 100% match rate across every dataset gathered; see `components/catalog`.
- **Still open**: `DocumentInfoRecord`'s error/success signal at its processed stage (no status field seen on the only examples found); RETRY-bucket payload shape for any Message Type (actively searched, not found); the dependent-object-blocking cross-reference hasn't been validated end-to-end in one dataset (the linkage mechanism itself is confirmed correct, just not paired live).

See [`components/transform/TECHNICAL_SPEC.md`](../../components/transform/TECHNICAL_SPEC.md) and [`components/catalog/TECHNICAL_SPEC.md`](../../components/catalog/TECHNICAL_SPEC.md) for the full breakdown.
