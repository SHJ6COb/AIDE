# catalog — Technical Specification

Module: `app/tools/catalog.py`. Exposed as the `match_catalog` tool. Source document: `db/docupediaContext/PackIT (PD7) Interface Error-....pdf`, authored by the project owner, transcribed into `db/docupediaContext/error_catalog.yaml`.

## Structure

The source document is a genuine structured table (~60 rows), not free prose. Each row: Seq. Nr., **Error Category** (renamed from the doc's own overloaded "Message Type" column to avoid colliding with our domain's real Message Type term — values: Target Error / Source Error / Technical Error / HINT / No action required / Retrigger required), an error-text pattern (fixed literal text + placeholders, e.g. `T141 Bom item status Invalid for material 60xxxxxxxx in plant ….`), an EN problem+solution description, and a Responsible party (Plant / Support Team / PST / n.a.). A small number of rows (e.g. seq_nr 7, 34) also carry an optional `context` field — the pattern alone isn't sufficient; the row only applies when specific `SearchParams`/`TransferRecord` fields (plant, determination_type, ...) also match a fixed value. Implemented as a fail-closed check in `match_catalog`: a context key that can't be confirmed (not currently extracted onto `TransferRecord`/`Hop` — e.g. customer_index, sales_channel) excludes the row rather than assuming a match.

## Matching — decided: structured regex, not RAG

Regex/literal matching on each row's fixed-text portions — precise and auditable, since these are stable SAP message texts, not naturally-varying prose. RAG/embedding retrieval was considered and explicitly rejected: the catalog's structure doesn't need it, and it would add complexity without a clear benefit.

```python
def match(error_text: str) -> CatalogMatch | None: ...
```

**Implementation requirement, confirmed necessary by live testing: patterns must be compiled with `re.DOTALL`** (or the equivalent for whatever regex engine is used). A `description` (see `transform`) is newline-joined from multiple `Ret_msgs.Message` values, so a pattern spanning more than one original message (e.g. row 30's `Error while saving the Det rule.*Do not enter packing instructions twice`) relies on `.` matching newlines. Confirmed empirically: without `DOTALL`, this exact pattern fails against real, live, otherwise-clearly-matching text; with it, 91/91 real Technical Error examples matched correctly in one live investigation. This is a one-line implementation detail with an outsized effect — easy to get right once known, a silent correctness bug if missed.

**Multi-match priority — RESOLVED: don't pick one, return all actionable matches.** A single multi-line `description` can contain text matching more than one catalog row (e.g. a real example matched both row 21, "End of processing in API: CSAP_MAT_BOM_MAINTAIN" — a generic log line, itself categorized `Target Error` — and row 32, "Error occured while creating msg condition... Material ... does not exist" — the actually diagnostic row, also `Technical Error`). Note this specific conflict is *not* solvable by an error-category heuristic (both rows are already "actionable" categories) — it's exactly why the resolved design is: `match_catalog(error_text, context=None) -> list[CatalogMatch]` returns **every** actionable-category match (excluding only `HINT`/`No action required`, which were never a candidate fix), rather than code silently picking a "best" one. The end user, who has full context, judges which match is relevant — more consistent with the strict-grounding philosophy than any single-winner heuristic would have been. Implemented in `app/tools/catalog.py`; see `tests/test_catalog.py::test_multiple_real_matches_returned_together_not_first_only` for this exact real example as a regression test.

## Strict fallback — no speculation, ever

If no row matches, the function returns `None`, and the harness/skill is instructed to respond with an honest "no documented fix for this" answer, pointing the user to raise an mServiceHub ticket — mirroring the doc's own stated policy ("If an unknown error comes up which is not understandable, please create a ticket mServiceHub"). The LLM is never permitted to invent a plausible-sounding fix in place of a real match.

## Validated against real examples

Catalog row 15 matches `example1`'s real error text almost verbatim. Row 31 matches the shape of `example3`'s error. Rows 57/58 independently confirm the Dependent-Object-blocking rule used by the `transform` component. Rows 30-32 (Technical Error) matched 91/91 real live examples once `DOTALL` was applied (see above) — this family of patterns is confirmed to work correctly as transcribed, once the implementation detail is right.

## Fixed defect: the SNR13/Business-Error family of rows didn't match real message text

This was a separate, unrelated problem from the `DOTALL` issue above — a genuine content defect in specific rows, confirmed at production scale, not a hypothetical edge case. **Fixed 2026-08-04, in `error_catalog.yaml` (rows seq_nr 1, 2, 3).**

- Real, live, high-volume error texts (`"SNR13 not found/ Mark for deletion"` — 429 occurrences in one 3-hour sample; `"SNR13 Cross Plant Status Invalid"` — 268 occurrences; `"SNR13 Plant Status Invalid"` — 95 occurrences) each failed to match their closest catalog row (seq_nr 2, 1, and 3 respectively).
- The cause: these rows' patterns required literal scaffolding text real messages never include — e.g. row 2's pattern required `STATUS EMPTY` and a `- Z0MM_XMARA` suffix; row 3 required a `FAIL:` prefix and `- Z0MM_XMARC` suffix. The actual `Ret_msgs.Message` field carries a shorter, human-paraphrased variant lacking all of this.
- Scale of impact (before the fix): in one 800-record, 3-hour sample dominated by real production errors, 167 of 168 Business-Error-bucket examples (99%) failed to match anything, almost entirely accounted for by this SNR13 family. Not a rare edge case — it was the majority of real error volume in this environment.
- **The fix**: the `FAIL:` prefix and `Z0MM_XMARA`/`Z0MM_XMARC` suffixes were made optional (not removed outright), so both the short real-world form and the fuller documented form still match — e.g. row 2 is now `SNR1[03]\s*NOT FOUND/?\s*(STATUS EMPTY/?\s*)?MARK FOR DELETION(\s*-\s*Z0MM_XMARA)?`. The distinguishing middle portion of each pattern was left rigid (no added wildcards), so this doesn't introduce new collisions with the more specific rows 4 or 7, which share partially-overlapping keywords.
- **Re-validated after the fix, zero regressions**: re-ran matching (with `DOTALL`) across every dataset gathered during the investigation — 91/91 (24h Technical Error hunt), 195/195, 198/198, 200/200, 200/200 (four pages of the 3-hour sample) — 100% match rate on every non-empty real error description checked, with the three fixed rows now accounting for the bulk of matches in the 3-hour samples.
- Longer-term alternative direction, not applied here: re-key matching on each `ReturnMsg`'s structured `(Id, Number)` pair (e.g. `/RB9X/PD4P_EAI` + `109`) instead of free-text regex — more reliable, but requires building that mapping from real traffic since the source PDF never documented these codes.

## Confidence status

The catalog structure itself is well-understood (read directly from the source PDF). The transcription of all ~60 rows into working regex patterns (`error_catalog.yaml`) is real effort, not yet complete as of this writing — each row's placeholder text (`60xxxxxxxx`, `plant ….`, `XXXXX`) needs converting into an actual regex, hand-checked to avoid over- or under-matching. Live validation has now specifically confirmed: the Technical Error family (rows 30-32) is transcribed correctly and works once `DOTALL` is applied; the SNR13/Business-Error family (rows 1, 2, 3) had scaffolding text that didn't survive to the real `Message` field — now fixed and re-validated at 100% match rate; RETRY-category rows (6, 7) remain unvalidated against any real example despite active searching. The multi-match-priority gap (see above) is still open and unrelated to this fix.
