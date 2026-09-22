---
concept: dependent-objects
summary: Dependent Objects: where they can exist at all (xOE only), and how each kind links back to its PS.
loads_when: has_dependent_objects
---

**Dependent Object**:
A sub-object of a PS that's replicated to Target Systems as its own separate Transfer (own Message ID, own Message Type), rather than embedded in the PS's own payload. Two kinds: Document Info Record and Packaging Cockpit Master Data. Blocking: the Target System won't process a PS's own `PackITPackagingSpecification` Transfer until that PS's Dependent Object Transfers have been processed — so a PS's true Replication Status can't be explained without also checking its Dependent Objects' status.
**Where they exist at all — confirmed 2026-08-06.** Dependent Object and DIR triggers are sent **only to the xOE system line** (POE/QOE, i.e. the Target System whose 2-character system code is `OE`). Every other Target System receives the `PackITPackagingSpecification` trigger alone. So the same observation means opposite things depending on the target — a missing Dependent Object at POE is a genuine finding, and anywhere else it means nothing at all, because none was ever sent.

**The four trigger rules — confirmed 2026-08-07.** These are not symmetrical, and the asymmetry is what makes them diagnostic:
1. **A Packaging Cockpit Master Data trigger can exist alone.**
2. **A DIR trigger can exist alone** (an explicit trigger — see Document Info Record).
3. **A PS trigger always carries a Cockpit Master Data trigger.**
4. **A PS trigger may or may not carry a DIR trigger.**
Read backwards: a PS trigger at POE with no Cockpit Master Data alongside it is a real finding. A Cockpit Master Data or DIR trigger found *on its own* is not evidence of PS activity at all and must never be reported as such — it is a master-data change or a document being attached.

**One envelope for all dependent master data — confirmed 2026-08-07.** There is no separate trigger per kind of master data. Every independent master-data structure — SNR13, label data, Workstep, plant data, packaging material, country of origin, brand — travels inside the *same* `PackITPackagingCockpitMasterData` payload, and a change to any one of them fires that payload with **the changed structure(s) populated and the rest empty**. Confirmed against a real capture: `SNR13_TANGO`, `SNR10_MATERIAL`, `PACKAGING_MATERIAL` and `PLANT_DATA` populated while `LABELDATA`, `WORKSTEP`, `COO_DATA`, `BSPD_DATA`, `BPNF_DATA` and `GSCRIPT` came through empty. More than one structure can be populated in a single trigger, so this is "whatever changed", not "exactly one thing".
_Reading which structures a trigger actually carries_: `OBJECTKEY` uses `*` in a dimension whose structure is not the subject of the trigger (`LBLNM: "*"`, `WORKSTEP_ID: "*"` on the capture above, matching their empty structures). But the key is **not** a reliable index of the body — the same capture names `SNR13_LABELDATA: "F00BV04379"` in the key while carrying an empty `SNR13_LABELDATA` structure. Inspect the body, not the key, to know what arrived.

**Telling an implicit trigger from an explicit one — confirmed 2026-08-07, and this is the practical test:**

| | implicit (rode along with a PS activation) | explicit (standalone master-data change) |
|---|---|---|
| `PS_ID` | a real PS, e.g. `00000000040000374679` | **empty string** |
| `SEQNO` | a real record, e.g. `00002` | **`00000`** |
| unused dimensions | `*` | `""` |
| body | every structure the PS holds | only the structure that changed |

Real explicit example (`splunkExamples/example8`): `PS_ID ""`, `SEQNO "00000"`, every dimension empty but `SNR10_MATERIAL: "8905501403"`, and the body carrying `SNR10_MATERIAL` alone. So `*` and `""` are **not** synonyms — `*` means "this PS holds none of these", `""` means "this trigger is not about a PS at all".
**Consequence worth relying on**: a standalone trigger carries no PS ID, so a PS-ID search cannot return master-data noise. A *material* search can.

**Cockpit's TOPICSTRING carries Brand and Packaging Index** — `ESR/Native/PackITPackagingCockpitMasterData/{SourceSystem}/{BRAND}/{PACKINDEX}`, confirmed across 1,020 distinct topic strings in 30 days. Brand is `_` when absent, otherwise a real code (`BAA`, `BMW`, `MB`, `POM`, `VWW`); the last segment is the SNR13's Packaging Index, verified against the key (`…/_/U50` carries `SNR13_MATERIAL "H105111503U50"` = SNR10 `H105111503` + `U50`). Both are `_` on a trigger with no SNR13 at all. An earlier entry describing these as contentless placeholders was wrong.

**Cockpit goes to exactly one target, at scale.** In 30 days its only hosts are `CPI_SAPPD70110_SAPPOE0110_CONSUMING` (39,313), `CPI_SAPPD70110_SAPPOE0110` (39,032) and `SOLACE` (39,032) — one target, `SAPPOE0110`, with no exceptions, confirming the xOE-only rule at scale. Note the absence of a bare `SAPPOE0110_CONSUMING` host: **Cockpit Master Data is never Retriggered.**

**Workstep**: a real dependent object in PACKIT — it owns Document Info Records the same way a PS does (see Document Info Record for the `L01`/`LEOR` link) — but it is **not its own Message Type**. It replicates inside Packaging Cockpit Master Data, which is why `WORKSTEP_ID` is one of that payload's `OBJECTKEY` dimensions. The set of Message Types remains three.
**How they link back to the PS — and the two kinds do it differently.** Message ID can never be used for this, being per trigger per Message Type.
- **Packaging Cockpit Master Data** carries the business object key in its own `OBJECTKEY`: `PS_ID`, `ZACTCOUNTER` and `SEQNO`, alongside its own dimensions (`SNR13_MATERIAL`, `SNR13_LABELDATA`, `SNR10_MATERIAL`, `PACKAGING_MATERIAL`, `PLANT_DATA`, `LBLNM`, `WORKSTEP_ID`). Confirmed from a real capture. It therefore names an individual Determination Record.
- **A DIR does not.** Its `OBJECTKEY` is purely the document's own key (Type + Number + Part + Version); the PS reference lives in a link array in the *body*, and carries no `SEQNO` at all — see Document Info Record. It names the PS and a scope, never one Determination Record.
So "the Dependent Object's OBJECTKEY points at the business object" is true of Cockpit Master Data only, and generalising it to DIR is a mistake.

**Packaging Cockpit Master Data**:
A Dependent Object accumulating reference/master data needed to render a PS's labels and descriptions (material master data, packaging material descriptions in multiple languages, plant master data), published under Message Type `PackITPackagingCockpitMasterData`. Confirmed real: this includes a label-specific SNR13 reference (technical: `SNR13_LABELDATA`) accumulated as its own piece of master data, distinct from the material's own SNR13 (`SNR13_MATERIAL`) — the two happened to match in the one example seen so far, but they're separate fields for a reason (not yet confirmed when/why they'd diverge). Also includes Country of Origin (technical: `COUNTRY`), confirmed real, as another piece of accumulated master data. See Cockpit data model for where this payload is ultimately stored and rendered (POE, powering the PXG Fiori app) — that's a distinct concept from this Dependent Object/payload itself.
