# Boundaries

Where this agent's scope stops, and where the concepts it reasons about bleed
into each other.

Written as a companion to [`DERIVATION.md`](DERIVATION.md), which proposes what
to load and when. This file is the prior question: **what is knowable here at
all**, and which pairs of concepts are close enough that an answer can silently
swap one for the other. Nothing here changes behaviour — it is a map, drawn from
the topic files under `app/agents/packspec_status/knowledge/`, from
`app/core/`, and from `regressionSuite/FINDINGS.md`.

Claims are attributed. Where a statement is my inference from what the repo
holds rather than something the repo asserts, it is marked **[inference]**.

---

## 1. The declared scope

From `app/agents/packspec_status/skill.md` (opening paragraph) and
`docs/agents/packspec-status/FUNCTIONAL_SPEC.md`:

- The subject is **Replication Status** — whether an approved Determination
  Record's payload reached and validated in its Target System(s).
- The agent **never checks Workflow Status** (the SAP approval state).
- The agent is **read-only**. A *Suggested Action* is guidance; a human acts.
- The agent **never supplies a cause or fix that is not in `catalog_matches`**.

Three of those four are enforced somewhere in code. The Workflow Status
exclusion is not — nothing in `transform.py` extracts it, so the exclusion holds
by absence rather than by guard. **[inference]** That is a weaker form of
enforcement than the others: an answer *can* still talk about Workflow Status,
it just has no data to talk about it from, which is precisely the condition
under which invention is most likely (cf. FINDINGS.md D9 — plant "never reaches
the model at all", and a plant code was invented anyway).

---

## 2. The hard boundary: state, not history

This is the established rule, and it is stated independently in two topic files.

> **The payload carries the current state. It carries almost nothing about how
> that state came about.**
> — `knowledge/packaging-specification.md`, §"What the wire carries, and what it
> does not"

> **The payload carries the current state. It carries almost nothing about how
> that state came about, because those things were never published.**
> — `knowledge/splunk-payload.md`, §"What it cannot — and where to go instead"

The two are the same rule in two shapes: one field-shaped (which fields are
source-only), one question-shaped (which questions cannot be answered). Both
are always-loaded today, so the rule is currently paid for twice.

### 2.1 The four confirmed instances

Each was found separately, on its own evidence. `packaging-specification.md`'s
table is the canonical list.

| # | Source-only thing | Technical name | What is lost | Recoverable from the wire? |
|---|---|---|---|---|
| 1 | **Stacking-factor reason** | `ZZSTAFA_REASON` | *why* the stacking factor was changed. The factor itself replicates; the reason never does. Prompted on screen at the moment of change (`Edu/edu_ps`, user 2026-08-08) | **No.** Nothing on the wire encodes intent |
| 2 | **Layer count** | *No. of Layers* — **has no payload field at all** | the derived count of layers | **Partially.** `Target Qty ÷ Layer Qty`. But `PC_PER_LAYER` is `0` on every level of every capture in this repo, so in practice the divisor is missing and the recovery does not run |
| 3 | **Document scoping** | the *Optional Document Keys* dialog: Packaging Ix. / Plant / Supplier / PDS Relevance | which Determination Record context a document link applies to, and whether it is a part picture or an appendix. `DOCUMENT_LINKS` carries only `DOCUMENT_NUMBER`, `DOCUMENT_PART`, `DOCUMENT_VERSION`, `DOCUMENT_TYPE` | **No.** The three optional keys are Determination Record keys; none of the four wire fields is one of them |
| 4 | **Archived versions** | Document Part `100` | the previous version's field values. On approval of a second version the old one is **deleted**, rendered to a PDF, and attached to a DIR | **No** — and the stronger statement holds: the values do not exist in the source either. Only a rendered document remains |

Two riders that belong with the table:

- **Instance 4 is asymmetric.** Whether archive documents replicate at all is
  *not established* — Part `100` appears in no capture in this repo, and none of
  the captured PSs has an archived version. So "archives do not reach a target"
  is asserted in the summary table but the section above it says absence here
  proves nothing either way. Treat the *deletion of the previous version* as
  confirmed and *whether Part 100 replicates* as open.
- **The sharpest case is not in the table.** A superseded version's field values
  exist nowhere — not in source, not on the wire. That is a strictly stronger
  claim than any of the four, and it is what makes "what changed between
  versions" unanswerable rather than merely expensive.

### 2.2 What the boundary implies operationally

`splunk-payload.md` states the five question shapes that fall outside it: *why*
a value is set that way; what it looked like before; what changed between
versions; which context a document applies to; and why nothing arrived at all.

The last is the one that matters most often, and it has three separate causes,
enumerated in `determination-record.md` §"Three states in which an approved
record does not replicate":

| State | Cause | Fault? |
|---|---|---|
| Not yet valid | `VALID_FROM` has not been reached | No — timing |
| Waiting on a sibling | the PS was revised, so *every* Determination Record on it must approve before any publishes | No — process |
| Rolled back | a sibling rejected; every approval on the PS is revoked | Yes |

All three produce **no Splunk event whatsoever**. They are therefore
indistinguishable from each other, and from a too-narrow search, by observation
alone. **Silence in Splunk is a legitimate state**, and this is the single
clearest place where the honest answer is a hop to PD7 rather than a wider
window.

### 2.3 Where the hop goes

`determination-record.md` names the mechanism — an **OData service on PD7** —
and then deliberately does not record when to reach for it or on whose say-so,
registering **PD7 OData service** as a dependent. So the boundary is mapped but
the crossing is not built. Nothing in `app/tools/` talks to PD7; the only
non-Splunk backend wired today is `routing_plan.py`.

**[inference]** This is why the two large topics matter to the loading question
at all. `packaging-specification.md` and `determination-record.md` are, by their
own framing, largely the *far side* of this boundary — the detail you need once
you have already decided Splunk cannot answer. They describe a hop the product
cannot currently make.

---

## 3. The other two boundaries, both enforced in code

The state/history boundary is a property of the domain. Two more are properties
of this application, and unlike the first they *are* guarded.

**The search boundary — `domain.is_underspecified`.** A search runs only with a
`ps_id` or `document_number`, or two identifying fields, or one plus `status`,
or a free-text term. Below that the app refuses rather than sweeping. FINDINGS
D3 is the case that proves the guard is worth having *and* that a guard only
holds where it runs: `pipeline._check_routing_if_target_missing` re-derives
params by dropping `target_system`, and until that fix it sent the broadened
query without re-checking — landing the exact unscoped sweep the guard had
refused one turn earlier.

**The answer boundary — `harness._enforce_grounding`.** Cause and remediation
come from `catalog_matches` or from nowhere. FINDINGS §5 is the general lesson
and it bears directly on how knowledge should be delivered: *guards written in
code held; rules written only in the prompt did not.* Time windows, continuation
promises, catalog fidelity and quantities were governed by `skill.md` alone, and
all four failed (D1, D4, D10, D8).

A glossary is prompt-side by construction. It cannot be guarded, only sized.
That is the whole argument for selective delivery: the only lever available on
prompt-side material is **how much of it is in front of the model**.

---

## 4. Where concepts bleed

Each row is a pair the repo has explicitly had to separate — usually because
they were once conflated in this project's own text or code. The "evidence"
column names where the separation is recorded.

### 4.1 Two status fields, and they are not one field

| | Packspec Status | Workflow Status |
|---|---|---|
| Object | the Packaging Specification | the Determination Record |
| Field | `HEADER.STATUS` | one field carrying code + description |
| Shape | a **letter** — `N`, `A`, `DL` | a **number** — twelve values, `05`…`70` |
| On the wire | yes, extracted as `ps_packspec_status` | only as the numeric segment of `TOPICSTRING` |
| In scope? | yes | **no** — skill.md excludes it |

This is the most consequential bleed in the corpus, and it was corrected on
2026-08-08: the numeric code in `TOPICSTRING` (`…/SHIP/3980/35/No`) is the
*Determination Record's* Workflow Status, not Packspec Status. The two
correlate — a PS goes Active when its Determination Record is Accepted, observed
as `HEADER.STATUS = A` with topic status `60`, and `N` with `35` — which is
exactly why they were recorded as one concept for as long as they were.

**A live inconsistency, reported not fixed.** `app/tools/transform.py:172-175`
still documents `packspec_status` as *"Same concept as TOPICSTRING's numeric
code; see the packaging-specification knowledge topic"* — and the topic it
points at now says the opposite. The extraction itself is correct (it reads
`ps_header["STATUS"]`, transform.py:475); only the docstring is stale. Worth
noting because it is the shape of drift the knowledge split was meant to make
visible: two copies of one fact, corrected in one place.

### 4.2 Two counters on a PS, both numeric

| | Activation Counter | Change Number |
|---|---|---|
| Field | `ZACTCOUNTER` (`ZZACTCOUNTER` on a DIR's link back) | `AENNR` |
| Counts | activations of the PS **structure** | PS **revisions** |
| Extend | untouched | untouched |
| Re-publish / Retrigger | untouched | untouched |
| Normal path value | `1`, `2`, … | constant `00000001` |

`activation-counter.md` carries the explicit `_Avoid_`. Two further traps sit on
top of it: the counter arrives with a **leading space** (`' 3'`), and the pair
`AENNR = 00000002` with an **empty** counter is the PT0 pre-Active signature —
not a fault and not a superseded revision. A 2026-08-06 correction records the
Retrigger entry having once claimed the counter "increases with each attempt";
it does not, measured constant across all 100 attempts of PS
`00000000040001253724`.

### 4.3 Usage vs Sales Channel — SAP's own collision

`ABRVW` is **Usage** (Regular, Alternative 1–4). `PACK_USAGE` is **Sales
Channel** (`OE`, `OES`, `IAM`). The word "usage" is in the business name of one
and the technical name of the other. Splunk's dashboard label "Pack Usage" is
therefore *faithful*, not a mislabel — an earlier version of `identifiers.md`
wrongly called it a Splunk error.

A third field sits next to these and is not either of them: `LABEL_SALESCHANL`.
It is empty on every inbound (RCPT) record while `PACK_USAGE` is populated on
all 254 PS records in the corpus. This codebase read the wrong one until
2026-08-06; the reason it went unnoticed is that on outbound records the two
hold the same value.

`skill.md` pushes the judgement to the model: *"if the user says 'Pack Usage'
you must judge from context which one they actually mean."* **[inference]** That
is a prompt-side rule of exactly the class FINDINGS §5 says does not hold, and
there is no measurement of it in either regression run.

### 4.4 Three things called "retrigger"

| Term | Who acts | Message ID | Host shape | Fix is at |
|---|---|---|---|---|
| **Retrigger** | the Target System reprocesses | **reused** | no `CPI_` prefix | the target |
| **Re-publish** | the Source System re-sends | **new each time** | `CPI_`-prefixed | the source-side blocker |
| **"Retrigger" (PD7)** | a human restarts the **approval workflow** | nothing published yet | not in Splunk at all | PD7 |

The third is called out explicitly in `determination-record.md`: *"'Retrigger'
here means the approval workflow in PD7 … a different thing from the
replication-side Retrigger."* Splunk's own dashboard adds a fourth spelling,
`RETRY`, for the first of them.

The operational consequence is in the summary shape: `hops_at_target` high with
`transfers = 1` is one message the target cannot process; `transfers` high with
`hops_at_target` low is the source re-sending. `harness._summarize_outcome`'s
docstring records that both were once called "attempts", which made two opposite
situations indistinguishable.

### 4.5 Whose plant? Whose material?

The PS's own plant and material, versus the plant and material named inside an
error description, are different values referring to different things.

The worked case: PS `00000000040000434427` is at plant `0780` with material
`0273011047`, while its error reads *"T141 Bom item status Invalid for material
6000.409.798"* — a **packaging** material, at plant `078W`, which the PS itself
never references. Cross-attributing them sends an engineer to the wrong material
at the wrong plant.

`harness._SUBJECT_FIELDS` encodes the separation in the key names: every subject
key is prefixed `ps_` on purpose, so a bare `plant` never sits beside a
description that names a different one.

Two related traps in the same family:

- **A PS has no plant at all.** Plant enters only through the Determination
  Record. *"Which plant is this PS for"* is a malformed question. FINDINGS D9 is
  what this looks like when it goes wrong: a fabricated plant `0780` for a PS
  whose ground truth is `0110` — and plant is a field that never reaches the
  model, so any plant code in that answer is invented by construction.
- **The PI is not the SNR13.** A Packaging Instruction number is
  `SNR13 + two-letter form code + supplier without leading zeros`
  (`F00SC01107FA131512`), and one trigger routinely creates more than one
  differing only in the form code. They share a long prefix, which is exactly
  why truncating one into the other is easy and destructive.

### 4.6 "PS X is stuck" is ambiguous, always

One PS carries many Determination Records — one per Plant / Customer Index or
Supplier combination, each with up to five Usages. An **Extend** creates a new
record with a new `SEQNO` and leaves the PS structure untouched, so a statement
about "the PS" can be true of one record and false of every other.

The wire agrees with this ordering: the payload nests `HEADER` (the PS) *inside*
`DETERMINATION` (the record). A Transfer does not carry a PS with routing
attached; it carries a Determination Record whose cargo is a PS.

`document-info-record.md` extends the same ambiguity to documents: *"does this
PS have a linked DIR"* is underspecified in the same way, because a link is
scoped to the PS universally, or to a plant + Customer Index, or to a plant +
supplier.

### 4.7 Which direction of the PS↔DIR link to trust

`DETERMINATION.DOCUMENT_LINKS` is a **snapshot of what was linked when that PS
trigger was built**. A document attached afterwards fires its own DIR trigger
and the PS is never re-triggered, so the list goes stale until the next
activation. Confirmed in this repo: PS `00000000040000588527`'s trigger declares
three documents while a DIR captured 31 seconds earlier names that same PS,
plant and supplier and is not among them.

So: **DIR → PS is authoritative; PS → DIR is a snapshot.** *"This PS has no
linked documents"* is never a safe sentence. *"The last PS trigger declared
none"* is.

### 4.8 Absent, versus not applicable

`dependent_objects` is `None` and `dependent_objects` present-with-empty-lists
mean opposite things, and the discriminator is the target line.

Dependent Object and DIR triggers are sent **only to the xOE line** (POE/QOE).
Against any other target the lookup cannot match, because nothing was ever sent.
`pipeline._lookup_dependent_objects` returns `None` there, and
`skill.md` instructs the composing turn to say **nothing at all** about
dependent objects in that case — not even an absence.

This is the mechanism behind one of the two invented details `skill.md` names by
name: *"'no linked Document Info Records' volunteered about a target that never
receives them."* An unasked fact was volunteered, and it implied a gap that did
not exist.

### 4.9 Counting the same thing two ways

| Pair | Why they differ |
|---|---|
| **Expert View rows** vs **hop count** | the Expert View deduplicates identical hops. A 4-row Transfer can hold 11 hops — 3 SOLACE, a publish hop, **six** identical Business Errors and a Success. Never reconcile ours against the dashboard's |
| **`error_category`** (catalog) vs **Business/Technical** (dashboard) | *different axes*. Both the daily-cadence and the minutes-cadence cases match the catalog as `Target Error` (rows 2 and 14). The only structural discriminator found is the SAP message code — `/RB9X/PD4P_EAI/109` vs `/009` — and how it maps across the other 61 rows is unconfirmed |
| **Return Message count** vs errors | empty-`Type` entries numbered `000` are padding. Counting them overstates what happened. A `Type='S'` line can sit alongside an `E` while `BusinessStatus` is `ERROR` |
| **rows received** vs **events matching** | `splunk_client.search` defaults to `max_pages=1` and `build_spl` appends `| head 200`. FINDINGS D5, still open: 254 matching, 200 received, and the app reported `hop_count` 96 against a ground truth of 100 |

The last is not a vocabulary bleed but a truncation bug, and it is listed here
because its symptom is identical to one — a count that is wrong without looking
wrong.

### 4.10 Three things called "kit"

The `ZKIT` flag on an Element (inherited from an integrated PSTV); the `KIT`
Determination Type (PSTU, order-accumulated returnable material); and the screen
section headed **"Kit Packspec"** where the PSTV Number field lives. Three names,
two concepts. `routing.md` adds that `KIT` and PT0 are **not** related despite
both being narrow special cases — PT0 is exclusively SHIP + IAM/OES across all
554 routing-plan entries, and `KIT` routes normally.

---

## 5. Boundaries between the topic files themselves

The eleven topics are meant to partition the vocabulary — `tests/test_knowledge.py`
enforces that no term is defined twice, and that `CONTEXT.md` indexes every one.
Term ownership is clean. **Prose ownership is not**, and three seams are worth
naming because they decide what a split can move.

| Seam | Owned by | Also stated in | Note |
|---|---|---|---|
| The state/history rule | `packaging-specification.md` (field-shaped) | `splunk-payload.md` (question-shaped) | the same rule, twice, both always-loaded |
| Highlight-markup / escaping traps | `splunk-payload.md` | `packaging-specification.md` §"A parsing trap in the captures themselves" | a parsing concern sitting inside a domain topic |
| `ZACTCOUNTER` leading space | `activation-counter.md` (the concept) | `splunk-payload.md` and `packaging-specification.md` (the trap) | three copies of one byte-level fact |
| Sales Channel naming trap | `identifiers.md` | `determination-record.md` §Usage | cross-reference, not duplication — acceptable |
| PT0 / VITAA | `routing.md` | `packaging-specification.md` §Change Number, `determination-record.md` §Workflow Status | the PT0 signature is spread across three files |

**[inference]** The first three are duplication that a split should resolve
rather than propagate. The last two are cross-references of the kind
`docs/AGENT_KNOWLEDGE_RESEARCH.md` §0 endorses (*"separate and cross-reference,
never copy"*) and should be left alone.

---

## 6. Outside every boundary, on purpose

Named in the corpus, deliberately not pursued. None should be reasoned from on
the strength of a passing mention.

From `determination-record.md`'s **dependent register**: Label; Workstep
(`WS01`); Document Info Record; packaging material; product master; Element
Group; Customization (SPRO/EWM); **PD7 OData service**. Plus **VitAA**, added
later — it appears in four of the twelve Workflow Statuses and the corpus knows
it only as "the trigger that sends a PS to PT0", which is plainly incomplete.

Declared out of scope by decision rather than oversight: `LEVEL_SET`; `VALID_TO`;
and the `DETERMINATION` fields carried but not explained — `INBOUNDKEY`, `VSZTP`,
`BRAND`, `COUNTRY_ID`, `VALIDITY_TZONE`, `ORIGINAL_INDEX`.

Genuinely unknown, and recorded as such:

- **Who "the recipient" is** in recipient approval. Asked of the domain owner
  2026-08-08; no answer available. This is the last gate before `60`, so it is
  the state most often reported — and `determination-record.md` instructs the
  agent to say *"waiting for recipient approval"* and **not** name who.
- What `ZIDENTIFIER` means (the Main Packaging Material marker is `HURELEVANT`).
- What `PSTE` expands to — only its numbering shape and BOM behaviour are
  confirmed.
- Whether the SAP message code alone determines Business vs Technical class.

---

## 7. Why this bears on delivery

Everything in §4 is a pair of things that look alike. A model composing an
answer picks between them, and the only thing standing behind that choice on the
prompt side is whether the distinguishing text happens to be in context.

That cuts both ways, and it is the tension `DERIVATION.md` has to resolve:

- Text that is **absent** cannot disambiguate. Dropping `identifiers.md` would
  remove the only statement that `PACK_USAGE` is Sales Channel.
- Text that is **present but unrelated** is material to answer from.
  `knowledge.py`'s own docstring makes this argument, and `skill.md` records two
  invented details produced by volunteering an unasked fact.

So the question is not "how little can we load" but **which distinctions are
live on the primary working surface** — the Splunk payload — and which only
become live once a question has already crossed into PD7 territory. §2 is the
line that divides them.

One honest caveat on the evidence. `regressionSuite/FINDINGS.md` documents
invented detail thoroughly (D6, D8, D9, D10) but **traces none of it to
always-loaded glossary text**. D9's plant is invented from a field the model
never receives; D8's count from data it did receive. The claim that unrelated
context is an invitation to mention it is well supported in the literature
(`docs/AGENT_KNOWLEDGE_RESEARCH.md` §0, layer 2 — the context-rot and
lost-in-the-middle results) and by `skill.md`'s two named cases, but it has **not
been measured on this corpus**. Any selective-loading change should be treated as
an untested hypothesis and re-run before its benefit is claimed.
