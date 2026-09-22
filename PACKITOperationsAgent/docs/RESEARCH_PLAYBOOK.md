# Research Playbook — empirically investigating an unfamiliar API/field

This is not a spec — it's the reusable *method* behind the specs. Every "Confirmed live" / "Confidence status" section across `CONTEXT.md` and the component specs was produced by repeatedly applying the same small set of moves against real systems (Splunk, the `ROUTINGPLAN` API). The worked example below is the `Request-Filter` investigation (`docs/components/routing-plan/TECHNICAL_SPEC.md`); the chain of thought generalizes to the next unconfirmed area — the next new API, the next undocumented field, `DocumentInfoRecord`'s error signal, `LOGICALCONNECTION`'s real values, whatever comes next.

## The chain of thought, as a checklist

1. **Establish one confirmed baseline call first**, and keep its full, unfiltered result around as ground truth. Nothing that follows is trustworthy without something independent to check it against — every subsequent filtered call in the `ROUTINGPLAN` work was validated by re-deriving its expected count from the already-captured 554-entry full dump, *before* trusting the API's own filtered response.

2. **Vary exactly one dimension per call.** Don't combine two new unknowns in a single experiment — if `WERKS=8150` and `DETTYPE=SHIP` are both untested, test each alone before testing them together, or a surprising combined result can't be attributed to either.

3. **Cross-validate every filtered result against the ground truth, don't just eyeball plausibility.** A filtered response that "looks reasonable" is not confirmation — `{"WERKS":"8150"}` returning 10 entries only became a finding once it was checked to be *exactly* the 10 the full dump independently shows for that Plant. This is what turns "the API responded" into "the API's filtering semantics are understood."
   - **Corollary, learned the hard way on a live system (`components/splunk-client`'s `search=` investigation): when comparing two query formulations head-to-head, pin both calls to the same *fixed, absolute* time window.** A first comparison of `"MessageType"` (bare text) vs. `source="MessageType"` (field filter) used a rolling `-15m`-to-`now` window for each call — the two calls landed a few seconds apart, the window itself moved between them, and the resulting "40-event difference" was mostly just elapsed wall-clock time, not a real finding. Re-running both calls against identical explicit epoch timestamps was what actually isolated the real (much smaller) discrepancy. Any live system with a continuously-growing index/log is a moving target — relative time windows silently break the "vary one dimension" rule from step 2 unless both calls are pinned to the same fixed range.

4. **Deliberately probe boundaries and failure modes, not just happy-path values**, since these are where real gotchas hide:
   - omit each field, one at a time — does it default, get ignored, or error?
   - pass the wildcard token at *every* nesting level, not just the one you've already confirmed — semantics can (and did) differ by nesting level.
   - pass a value guaranteed not to exist (bogus/unregistered) — does it 404, error, or return something structurally different from an empty result?
   - pass a syntactically-plausible but semantically-wrong value: wrong case, a partial/glob pattern, an unrecognized field name entirely.
   - This is exactly the variant list run against `ROUTINGPLAN`: specific-value, nested-field, combined-nested-fields, exact-instance-ID, literal-wildcard-at-nested-level, omitted-mandatory-field, unregistered-value, partial-wildcard, unknown-field-name, wrong-case.

5. **Treat an unexpected raw response as a first-class finding, not noise to work around.** The `AR AGREEMENT NOT REGISTERED` plain-text HTTP-200 body would have been silently swallowed by a script that assumed every 200 response is JSON and moved on. Inspect raw bytes before assuming shape, especially on any call that isn't yet a confirmed-good baseline.

6. **The moment a new experiment contradicts something already written down, fix the contradiction immediately, in the same pass** — don't let a stale claim survive next to a newer, better-evidenced one. (Concretely: the `ROUTINGPLAN` spec's old "Sales Channel `*` throughout... only PT0's entries filter on it" line was corrected the moment `{"ABRVW":"IAM"}` returning zero proved Sales Channel isn't a live filterable field at all — it lives in `TOPICSTRING` instead.)

7. **Write confirmed-from-evidence and inferred/assumed claims in a visibly different register**, and keep an honest "still open" list rather than letting silence imply confirmation. Every spec in this repo carries a `Confidence status` section for exactly this reason — a future reader (human or agent) needs to know which sentences are load-bearing and which are still guesses.

## Why this is written down separately from the specs

The specs (`app/agents/packspec_status/knowledge/*.md`, `docs/components/*/TECHNICAL_SPEC.md`) are the *findings* — what's true about this domain, as currently confirmed. This playbook is the *procedure* that produces findings of that quality — worth reusing verbatim the next time an agent (this one, in a future session, or a different one entirely) needs to nail down an unfamiliar API or an unconfirmed field, without re-deriving the approach from scratch.
