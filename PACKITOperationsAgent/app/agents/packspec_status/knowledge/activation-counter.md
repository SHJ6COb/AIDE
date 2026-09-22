---
concept: activation-counter
summary: The Activation Counter, and why an error on a superseded one is obsolete rather than live.
loads_when: has_superseded_activations
---

**Activation Counter**:
A source-provided ordering key carried with a Transfer's payload — `ZACTCOUNTER` (single Z) on a PS's own `HEADER` and `OBJECTKEY`, `ZZACTCOUNTER` (double Z) on a DIR's link back to its parent PS (`OBJECTLINKSPACKITPACKSPEC`), not a transcription error, both are genuinely real field names in different structures — not something the Target System generates or increments itself. **It counts activations of the PS structure: create + activate gives 1, each subsequent change + activate increments it.** An Extend leaves it untouched (nothing about the structure changed — see Determination Record), and so do a Re-publish and a Retrigger. Its purpose: the Target processes the newest activation, so when two triggers for the same key are both still unprocessed the Target keeps the higher counter and discards the other, and a late-arriving older change can't silently overwrite a newer one already in flight.
**Consequence for reading a status: an error carried by a superseded Activation Counter is obsolete** — it describes a version of the PS that has since been replaced, and reporting it as live sends someone to fix something that no longer exists.
_Avoid_: Confusing with "PS activation" (Packspec Status reaching 60/Active, see Packspec Status) — same word, unrelated concept. Confusing with Change Number (`AENNR`), which counts PS revisions.
_Corrected 2026-08-06_: the Retrigger entry previously stated this counter "increases with each attempt". It does not — measured constant across all 100 target attempts of PS 00000000040001253724 and all 49 events of PS 00000000040001497551, both at `2` throughout.
