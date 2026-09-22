---
concept: document-info-record
summary: Document Info Records: the three link scopes, when a DIR triggers, and which direction of the PS-DIR link to trust.
loads_when: mentions_documents
---

**Document Info Record (DIR)**:
A Dependent Object carrying a document (e.g. a packaging instruction PDF) attached to a PS, published under Message Type `DocumentInfoRecord`. Keyed by Document Type + Document Number + Document Part + Document Version, distinct from the PS's own key. Optional: a PS with no linked documents is entirely normal, so a missing DIR is not on its own a problem.
**Payload shape — confirmed 2026-08-06 from a real capture.** A DIR does **not** follow the PS envelope. Where a PS or Cockpit Master Data payload is `{"SINGLEMESSAGES":[{SINGLEMESSAGEHEADER, SINGLEMESSAGEBODY}]}`, a consumed DIR is `{SINGLEMESSAGEHEADER, DocumentMessageRoot}` — no array wrapper, no `SINGLEMESSAGEBODY`, and its master node sitting *beside* the header rather than beneath a body. It also uses camelCase rather than SAP ALL-CAPS. Pre-consumption it takes a third shape again (`{COLLECTIVEMESSAGE, SINGLEMESSAGES[]}`, ALL-CAPS, PS link under `OBJECTLINKSPACKITPACKSPEC`), so a DIR has three payload shapes across its stages while a PS has one.
**Its master node is the document itself** — carrying the document's own identity, attributes (`status`, `validityStart`, `deletionIndicator`, responsible department), its content (`hasDocumentClass`, `hasDocumentDescription` per language, `hasDocumentFileSAP`), a possible parent document, and then a set of *link arrays* pointing outward. Nothing is nested beneath a DIR; a DIR only points.
**Uniqueness**: `OBJECTKEY` is five parts — `SYSTEMID` + Document Type + Number + Part + Version — while the PS's `DOCUMENT_LINKS` and this codebase's DIR key both use the four non-system parts. That is safe only while one Source System is in play, and is an assumption rather than a confirmed equivalence. Version and Part are part of identity: `…/000/00` and `…/000/01` are two different objects.
**A DIR is always linked from within a Packspec, and at link time a scope is chosen — confirmed 2026-08-06.** Linking happens during PS creation, Change or Extend, and the person linking picks one of three scopes:
1. **to the PS** — applies to *every* Determination Record of that PS (universal);
2. **to a plant + Customer Index combination**;
3. **to a plant + supplier combination**.
So the PS→DIR relationship is not one edge but a *rule* about which Determination Records a document applies to. A consequence worth stating plainly: **"does this PS have a linked DIR" is underspecified** in the same way "PS X is stuck" is — the answer can differ per Determination Record, so the question is really about a Determination Record.

**When a DIR triggers — the two trigger categories, confirmed 2026-08-06.**
- **Implicit** — activating a Determination Record fires the PS trigger, which in turn implicitly fires the DIR triggers for the documents applying to that record (its own scoped ones plus the universal ones) *and* the Packaging Cockpit Master Data trigger. An Extend behaves identically, since it too activates a Determination Record.
- **Explicit** — on an Active PS, Change → add only a document fires a DIR trigger with **no PS trigger**.
A DIR is never created outside a Packspec context, but it is certainly published outside a PS publish. So a DIR seen alone in Splunk is an explicit trigger and implies no PS activity at that moment.

**A DIR can link to a Workstep instead of a PS — confirmed 2026-08-07 against real captures of both.** Document Type discriminates which link the DIR carries, and this is now **observed, not inferred**.

| Document Type | populated | empty | capture |
|---|---|---|---|
| `PAC` | `OBJECTLINKSPACKITPACKSPEC` | `OBJECTLINKSWORKSTEP` | `splunkExamples/example9` |
| `L01` | `OBJECTLINKSWORKSTEP` | `OBJECTLINKSPACKITPACKSPEC` | `splunkExamples/example7` |

`L01` documents link to a **Workstep**, whose type is `LEOR` (Lettering order). Both use the same linking machinery, so a DIR is not exclusively a PS attachment — and Document Type tells you which link to read without scanning every array.
Document Part varies independently of this and is **not** a discriminator: `PAC` appears with `FRE` and `000`, `L01` with `000` and `LEM`.

**Which direction to trust.** `DETERMINATION.DOCUMENT_LINKS` on the PS payload lists linked DIRs by the four-part key, but it is only a **snapshot of what was linked at the moment that PS trigger was built** — a document attached afterwards fires its own trigger and the PS is never re-triggered, so the PS's list stays stale until the next activation. Confirmed real in this repo: PS 00000000040000588527's trigger declares three documents while a DIR captured 31 seconds earlier names that same PS, plant and supplier and is *not* among them. So **DIR → PS is authoritative and PS → DIR is a snapshot**; "this PS has no linked documents" is never a safe sentence, "the last PS trigger declared none" is.
**Its TOPICSTRING — measured across 30 days on 2026-08-07.** Shape:
```
DocumentInfoRecord/V1/REGULAR/{SourceSystem}/{DocumentType}/{_}/{_}/{_}
```
PACKIT's own DIRs (Source System `SAPPD70110`) produce **exactly two** distinct topic strings in 30 days, differing only in Document Type — `…/PAC/_/_/_` (14,916 events) and `…/L01/_/_/_` (3,920). The three trailing slots are never filled for PACKIT, though DIRs from *other* source systems do fill them (e.g. `…/SAPP1M0110/FDA/2170/50608889/MC1`), so they are real slots that PACKIT has nothing to put in. `REGULAR` is constant on every DIR from every source system — it varies with nothing observed.
So a PACKIT DIR topic carries **no plant, no Determination Type, no Sales Channel and no PS** — the very keys Additional Routing is keyed on. How a DIR is routed to the xOE line remains **unexplained by anything confirmed**; the routing-plan API has only ever been queried for `PackITPackagingSpecification`. Do not assume the PS routing rules transfer.

**Two TOPICSTRING levels, and they differ.** `SINGLEMESSAGEHEADER.TOPICSTRING` is coarse — `Native/DocumentInfoRecord/SAPPD70110`, Message Type and Source System only. The business-context string above is its **sibling**, `SINGLEMESSAGES[n].TOPICSTRING`. Reading the first `TOPICSTRING` in a payload therefore gets the wrong one, and makes DIR look as though it has 3 topic strings across the index when the specific level has 1,000.

**Most `DocumentInfoRecord` events in the index are not PACKIT's.** Of 236,405 DIR events in 30 days, **216,554 come from `SAPP1M0110` and 120 from `SAPPT80110`** — document types `TSS`, `TKU`, `PRV`, `DRW`, `BST`, `BV`, with a different body shape carrying no PACKIT link sections at all. Only **18,836 (8%)** are PACKIT's own, from `SAPPD70110`. **A DIR search must be scoped to the Source System** or it is 92% noise.

**A DIR is never observed failing.** Zero `DocumentInfoRecord` events in 30 days carry `<d:BusinessStatus>ERROR</d:BusinessStatus>` — across the whole index, not just PACKIT's. Its hosts are `SOLACE` (236,405), `STCENEMXX0_PUBLISHING` (7,093) and `STCENPSXX0_PUBLISHING` (1,982): **no `_CONSUMING` host exists for DIR at all**, so a DIR's target-side outcome is not visible in this index in the way a PS's is. "No DIR error found" is therefore not evidence that a DIR succeeded.
**The target does not use `DOCUMENT_LINKS` at all.** Downstream the link presentation is built from SAP DMS's object-link structure **DRAD**, populated by the DIR triggers themselves. `DOCUMENT_LINKS` travels alongside the mechanism; it is not the mechanism.

**A DIR does carry its PS — confirmed 2026-08-06 from a real capture** (`screenshots/dependentObjects/DocumentInfoRecord`), correcting an earlier entry here that claimed a published DIR has no PS field and a later one that claimed no DIR payload exists in this repo. Both were wrong. The link array appears under two names either side of the consumption boundary — `SINGLEMESSAGEBODY.OBJECTLINKSPACKITPACKSPEC` pre-consumption, `DocumentMessageRoot.hasPackItPackagingSpecificationLink` in the Atom-wrapped payload — carrying `hasPackagingSpecification` (the PS ID), `activationCounter`, `activationStatusIndicator` (the Change Number), `hasPlant`, `hasSupplier` and `packagingIndexNumber`. Those last three encode **which scope was chosen**, not a copy of some Determination Record's dimensions. Note there is **no `SEQNO`** — a DIR names the PS and the scope, never an individual Determination Record. So a full-text search for a PS ID scoped to Message Type `DocumentInfoRecord` is a *valid and correct* search, not the empty one an earlier rule assumed.
