---
concept: packaging-specification
summary: The Packaging Specification as the planner builds it — PS Group, header, content, levels, elements — and which of its fields reach the wire.
loads_when: always
---

# Packaging Specification

A **Packaging Specification** is a standard SAP EWM object (`/SCWM/PACKSPEC`). PACKIT does
not define it — it wraps it, through the custom transaction `Z0MP_PACKSPEC`. It is created
in the source system **PD7** (S/4, **client 011**), and it is what a planner builds when
they define how a product is packed.

It is not the thing that replicates. A Packaging Specification reaches a target system only
as cargo of an approved **Determination Record**, which is the unit that travels and the
unit that fails.

## Terms

**PACKIT**:
The product built on SAP S/4 that supports Packaging activities. Wraps SAP EWM's Packaging Specification object model (`/SCWM/*`) via a custom transaction, `Z0MP_PACKSPEC`, on top of the standard `/SCWM/PACKSPEC`.

**Packaging Specification (PS)**:
The SAP EWM object (`/SCWM/PACKSPEC` data model) a Packaging Planner creates to define how a product is packaged, in the Source System. Structured as one PS header with a Content node (product details) and up to 4 Levels, whose count is fixed by PS Group. Distinct from the CS03 BOM later created from it in a Target System — related by data lineage, not identity.
_Avoid_: Product Packaging Specification. (Note: "BOM" alone is ambiguous — it may mean the genuinely separate downstream CS03 BOM, so don't use it for PS itself.)

**Packspec Status**:
A header-level field on the PS itself (technical: `HEADER.STATUS`) indicating whether the PS is usable at all. A **letter** code. Confirmed real values: **`N`** = NEW, just created, no Determination Record approved and released yet — replicates nothing at all; **`A`** = Active, the normal state, and a PS should ordinarily only replicate once it reaches it; **`DL`** = deletion indicator (PS deletion trigger, distinct from any intermediate state).
_Avoid_: Reading the numeric code in TOPICSTRING as this field — see below.

**The numeric status in TOPICSTRING is not Packspec Status** — corrected 2026-08-08.
The numeric-style code in the TOPICSTRING status segment (`…/SHIP/3980/35/No`) is the **Determination Record's Workflow Status**, a different field on a different object. `35` and `37` are Workflow Status values — *Waiting for SNR13 creation in VitAA* and *Waiting for VitAA feedback* — and belong to the Determination Record, not to the packaging specification. See the determination-record topic for the full twelve-value enum.
The two fields **correlate**, which is why they were previously recorded as one: a PS goes Active when its Determination Record is Accepted. Observed pairings — `HEADER.STATUS = A` with topic status `60` (Accepted), and `HEADER.STATUS = N` with topic status `35`. That is a relationship between two objects, not two encodings of one field.
This also fits the structure: every other business segment of a PS TOPICSTRING (`DETTYPE`, `WERKS`, `PACK_USAGE`) is a **Determination Record** field, so the status segment being one too is consistent rather than surprising.
_Superseded_: an earlier version of this entry asserted the two were "confirmed to be the same underlying concept", and attributed `35`/`37` to the PS as intermediate IAM/OES statuses. The user confirmed on 2026-08-08 that `35`/`37` are Workflow Status values linked to the Determination Record. The TOPICSTRING attribution above is the reading that follows, and is **not itself separately confirmed**.

**Change Number**:
A field (technical: `AENNR`) on a PS indicating which revision of the packaging rule a record reflects. `00000001` is the Active revision. A **Create Second Version** (see Determination Record for the lifecycle) writes a *new* database record at `00000002` in the Source System while the revision is being worked on.
**On the normal replication path it is a constant.** A Transfer to a real Target System carries the *Active* revision, so `00000001` — across every such capture in this repo: 1,381 occurrences of `"00000001"` plus the numeric `1` form. On that path it discriminates nothing between payloads and must not be surfaced as if it did.
**But `00000002` is real on the wire, on exactly one path — confirmed 2026-08-07.** A VITAA/PT0-bound Transfer replicates the PS **before** it is Active (see PT0), so it is the only path on which a not-yet-Active revision reaches the wire. Confirmed against a real capture of PS `00000000040001498023` in `tests/fixtures/multi_target_fanout_page.xml`, which holds both halves of its lifecycle five days apart:

| | host | `HEADER.STATUS` | TOPICSTRING status | `AENNR` | `ZACTCOUNTER` |
|---|---|---|---|---|---|
| 2026-07-30 | `CPI_SAPPD70110_SAPPT00110_CONSUMING` (PT0) | `N` | `35` | **`00000002`** | **empty** |
| 2026-08-04 | `…SAPPOE0110_CONSUMING`, `…SAPP990110_CONSUMING` | `A` | `60` | `00000001` | `1` |

So the pairing is diagnostic: **`AENNR 00000002` together with an empty Activation Counter means "not yet activated"**, and is the normal appearance of a PS sitting at the PT0 approval step — not a fault, and not a superseded revision. Once activated, the revision becomes `00000001` and the Activation Counter starts at `1`.
_History_: an earlier version of this entry asserted the `00000002`/PT0 link as confirmed; it was withdrawn on 2026-08-06 as unevidenced after a search that covered only `splunkExamples/` and missed the fixture above. The original claim was correct and is restored here with the capture attached.
Present consistently across a PS's `OBJECTKEY`, header, Content nodes, Levels, and Elements (same value throughout one payload). A DIR's link back to its PS carries the same value under the name `activationStatusIndicator`.
_Avoid_: Confusing with Activation Counter (`ZACTCOUNTER`) — that's a source-provided ordering key for same-key conflict resolution at the Target (see Activation Counter), this counts PS revisions; unrelated concepts that happen to both be numeric counters on a PS.

**PS Group**:
A single header-level field (technical: `PS_GROUP`) classifying a PS into one of 6 values — **PS1**–**PS4** (1–4 Levels respectively; standard product packaging, each independently resolved via its own Determination Record), **PSTU** (always 1 Level; *not* for actual product packaging — tracks order-accumulated MWEG/returnable packaging material, resolved via its own Determination Record; confirmed real via Determination Type `KIT`), and **PSTV** (always 4 technical Levels; has no Determination Records of its own at all — integrated into a PS1–PS4 via the Content node's PSTV Number, see PSTV integration below). Not a name for an individual Level. **Chosen first, and it binds the Level count** — see below.
_Avoid_: Using "PS1"/"PS2"/etc. as if they were names of individual Level nodes — they're not.

## How one comes into existence

**1 — Choose the PS Group.** This is the planner's first act, before anything exists. Six
values in a dropdown: `PS1` `PS2` `PS3` `PS4` `PSTU` `PSTV`. The values come from
customization (SPRO, EWM).

The choice **binds the level count exactly** — `PS2` means two levels, not "up to two".
A planner cannot select `PS4` and populate three. Verified across every capture holding a
PS: `PS1`→1 level, `PS2`→2, `PS3`→3.

> So `PS_GROUP` disagreeing with the populated level count is a **data fault**, not a
> normal variation.

**2 — Press enter. The system generates the Packspec ID.** The planner never types it.
The screen shows it unpadded (`40001367167`); the payload carries it zero-padded to 20
(`00000000040001367167`).

**3 — Screen 2 opens** with the node tree: **Header**, **Content** (holding Product), and
one **Level** per the PS Group, each with **Element** children.

## The header

### What the planner sets

| On screen | Field | Notes |
|---|---|---|
| PS Group | `PS_GROUP` | six values, from customization; binds level count |
| Transp. Device | `ZTRANSDEV` | dropdown — `BEH Container`, `PAL` seen |
| Freight Mode | `ZFRMOD` | a **Workstep** of type `FMOD` — 8 values |
| Lettering Order 1–4 | `ZLABINSTR`, `…2`, `…3`, `…4` | a **Workstep** of type `LEOR` — 339 values |
| Dynamic stacking factor | `ZSTFAC` | an **enum, not a count** — see below |
| Reason Code | `ZZSTAFA_REASON` | asked when the stacking factor is changed. **Never reaches the wire** |
| Std. Packaging Ind | `ZSTDPACKIND` | flag, `X` |
| Pref. Packspec | *(mapping unconfirmed — `ZPREFBOM`?)* | checkbox, never populated in any capture |

### What the system sets

`PS_ID`, `PS_H_GUID`, `AENNR` (Change Number), `STATUS` (Packspec Status), `ACTIVATE_TIME`,
`ACTIVATED_BY`, `ZACTCOUNTER` (Activation Counter), and `LEVEL_SET` — which travels in
lockstep with `PS_GROUP` (`PS2`/`LS2`) and whose separate purpose is not established.

`ACTIVATED_BY` holds **both** a batch user (`UC4CPIC`) and real people (`JLS2SI`), so it
does not distinguish automated from manual activation on its own.

### Lettering Order and Freight Mode are the same kind of object

Both are **Worksteps** — one master object (`WS01`), maintained in the *Workstep Overview*
transaction, distinguished by `WSType`:

| `WSType` | Description | Example |
|---|---|---|
| `LEOR` | Lettering Order | `1000000599` = BEKW |
| `FMOD` | Appropriate Freight Mode | `1000000022` = Truck |

The header stores a workstep reference, unpadded on screen (`1000000026`) and zero-padded
to 20 in the payload (`00000000001000000025`). A workstep carries its own documents flag,
set on some and not others.

### Two traps

**The stacking factor is an enum.** The screen label is *"Dynamic stacking factor for
identic load unit"* and the value reads `1 = stack of 2 (1+1)`. Reporting `ZSTFAC = 1` as
*one unit* inverts the meaning — it means two.

**The Activation Counter carries a leading space** — `' 3'`, not `'3'`.

### Fields that never carry a value

In no capture in this repo: `BAND_UP_REL`, `BAND_DN_REL`, `BAND_UP_REL_MU`,
`BAND_DN_REL_MU`, `MINIMUM_QUAN`, `ROUNDING_GOAL`, `DOC_EXIST`, `ZPREFBOM`, `ZSIZEGRAD`,
`PS_DESCRIPTION`, `ICON`. Absence of evidence — the fields exist in the structure.

## Org. Data tab

Despite the name, this tab holds **no organisational assignment** — no plant, no sales
organisation, no site. It is classification plus administrative history.

| Field | Example |
|---|---|
| Packspec Group | `PS2 Packspec with two Levels` |
| Level Set | `LS2 Level Set 2` |
| Created by / on | `JLS2SI` · 27.10.2021 |
| Changed by / on | *(empty — this PS has never been changed)* |
| Activated by / at | `JLS2SI` · 27.10.2021 14:59:33 |
| Activ. Counter | `1` |
| Logical system | `SAP0PD7011` |

> **A Packaging Specification has no plant.** Plant enters only through the Determination
> Record, which is keyed on it. So a PS is plant-independent: the same packaging rule
> serves every plant that a Determination Record assigns it to. Any question of the form
> *"which plant is this PS for"* is malformed — it has to be asked of a Determination
> Record.

The group's own description confirms the naming: `PS2` is literally *"Packspec with two
Levels"*.

**`LEVEL_SET` — deliberately out of scope.** It is a separate selectable classification
(`LS2 Level Set 2`) that moves in lockstep with `PS_GROUP` across every capture. Its
purpose was not pursued, by decision rather than oversight: an agent should not reason
from it or surface it.

### Logical system names decode

`SAP0PD7011` is `SAP0` + **PD7** + **011** — system and client. The workstep screens show
`SAP0QD7011`, the same client on the quality system. That is where client `011` is visible
in the data rather than asserted.

## Documents tab

Documents are **Document Info Records** — separate master data, registered as a dependent
and not pursued here. What belongs to this topic is how a PS links to one.

The grid carries **Type · Document Number · Vs · Part · Document Description · File Name**.
Worked example on PS `40000303210`:

| Type | Number | Vs | Part | Description | File |
|---|---|---|---|---|---|
| PAC | 1325014 | 00 | `CHA` | C_0280218134_18Z_8160_0 | CHANGELOG_….PDF |
| PAC | 1428374 | 00 | `FRE` | F_0280218134_18Z_8160_0 | FREETEXT_….PNG |

`DOCUMENT_PART` values seen: `CHA` (changelog), `FRE` (freetext), `ARC`, `000`. Document
numbers are 7 digits on screen and zero-padded to 25 in the payload.

### Linking a document scopes it — and the scope does not travel

*Add Document Link* opens a dialog headed **Optional Document Keys**:

- **Packaging Ix.**, **Plant**, **Supplier** — all optional
- **PDS Relevance** — **mandatory**, one of: *Not relevant for PDS*, *Part Picture*,
  *Inner Packaging Picture*, *Outer Packaging Picture*, *Shipping Unit Picture*,
  *Appendix*. Every picture option is restricted to JPEG/JPG/PNG.

The three optional keys are **Determination Record keys** — packaging index, plant and
supplier are exactly what a DR is keyed on. So a document can be attached to one DR
context rather than to the packaging specification as a whole.

> **None of that scoping reaches the wire.** `DOCUMENT_LINKS` in the payload carries only
> four fields — `DOCUMENT_NUMBER`, `DOCUMENT_PART`, `DOCUMENT_VERSION`, `DOCUMENT_TYPE`.
> No plant, no supplier, no packaging index, and no PDS relevance. An agent reading Splunk
> can see *that* a document is linked but not *which context it applies to*, and cannot
> tell a part picture from an appendix.

That makes document scoping a third confirmed source-only concept, alongside
`ZZSTAFA_REASON` and `No. of Layers`.

### A PS only ever links to its own system's documents

**A packaging specification cannot link to a document originating outside PD7.** So the
four-part key the PS carries (`DOCUMENT_NUMBER` + `PART` + `VERSION` + `TYPE`) is
sufficient to identify it, and `document-info-record.md`'s caveat — that dropping
`SYSTEMID` is *"an assumption rather than a confirmed equivalence"* — **can be retired**
for PS document links.

The reason the Splunk index looks dangerous is different, and worth stating separately:

> **`DocumentInfoRecord` is a universal message type.** Every system in the landscape
> publishes DIRs. `PackITPackagingSpecification` and `PackITPackagingCockpitMasterData` are
> PACKIT's own and appear from `SAPPD70110` only.

So the DIR index carries a large majority of documents that have nothing to do with PACKIT
— not because a PS might reference them, but because they simply share the message type. A
DIR search must be scoped to the source system for that reason alone. The corpus already
records the 92% noise figure; this is why it exists.

## Archived Versions

**When a second version is approved, the previously active version is deleted.** It does
not survive as structured data. It is rendered to PDF through a purpose-built SAP Adobe
form, a Document Info Record is created, and the PDF is attached to it.

> **The consequence is a hard limit on what any agent can answer.** *"What did this PS look
> like before the change?"* is not a data question — the old field values are gone. Only a
> rendered document remains. An agent can name the archive document; it cannot read the
> previous target quantity out of it, diff two versions, or say which field changed.

**Archives are per Determination Record, not per PS.** The document description encodes it:

```
40001356007-DR#00001-arch_vers# 1-DEL
└─ PS ID ──┘ └─ DR seq ┘ └ archive ┘ └ deleted
```

The Archived Versions tab on PS `40001356007` shows three such documents, covering
`DR#00001` and `DR#00002`.

| Type | `DPt` | Meaning |
|---|---|---|
| `PAC` | `100` | archived version |

### Document part codes, and what is known of them

| Part | Meaning | Source |
|---|---|---|
| `FRE` | freetext | Documents tab |
| `CHA` | changelog | Documents tab |
| `100` | archived version | Archived Versions tab |
| `ARC` | **unexplained** — appears twice in captures | payload only |
| `000` | **unexplained** — appears once | payload only |

`ARC` is not the archive code, despite the name — archives use `100`.

> **Archive documents do not replicate** — confirmed by the domain owner, 2026-08-08. They
> exist only in the source system. Part `100` appears in no capture in this repo, which is
> consistent but proves nothing on its own: none of the captured packaging specifications
> has an archived version, so the absence would look identical either way. The confirmation
> is what settles it.

### A parsing trap in the captures themselves

Field values in these captures sometimes arrive wrapped in Splunk highlight markup —
`<sg h='1'>PackITPackagingSpecification</sg>`, `<sg h='1'>00000000040000434427</sg>`.
That is search-result decoration, not data. Anything reading a capture must strip it, or
it will compare a wrapped value against a bare one and find no match.

## What the wire carries, and what it does not

**The payload carries the current state. It carries almost nothing about how that state
came about.** Four independent confirmations, each found separately:

| Source-only | What is lost |
|---|---|
| `ZZSTAFA_REASON` | *why* the stacking factor was changed. The factor replicates; the reason never does |
| `No. of Layers` | the derived layer count — though it is recoverable as Target Qty ÷ Layer Qty |
| Document scoping | which plant, supplier or packaging index a document link applies to, and its PDS relevance |
| Archive documents | **confirmed** — archived versions do not replicate. Part `100` never reaches a target |

And beyond those, the sharpest case of all: **a superseded version's field values do not
exist anywhere**, in source or on the wire. They were rendered to PDF and deleted.

### Why this matters more than any individual field

An agent reading Splunk alone can answer *what is true now* with confidence. It cannot
answer:

- *why* a value was set the way it was
- *what it used to be*
- *which context* a linked document belongs to
- *what changed* between two versions

Those are not gaps in the capture — a more complete Splunk search will never close them,
because the information was never published. They are the boundary of what replication
carries.

**This is what the PD7 pull is for.** When a question falls into one of the four categories
above, no amount of searching Splunk will help, and offering to read the source system is
the only honest next step rather than a fallback for when the search came back empty.

## Content node

The Content node is mostly a **projection of the product master**. Only three fields are
editable; everything else is display-only, fetched behind the *Display Product Master*
button.

| On screen | Field | Notes |
|---|---|---|
| Material-SNR10 | `MATNR` / `ZMATNR` | the product — the planner's one real input |
| Relative Expiry Date | `ZRELDATE` (+ `ZRELDATE_UNIT`) | a **period in MONTHS**, not a date |
| PSTV Number | `SUB_PS_ID` / `SUB_PS_GUID` | sits under a section headed **"Kit Packspec"** |

Display-only, from the product master: Quantity, Length, Width, Height, Gross Weight,
Volume, Material Type, Cross-plant Status, and Term code (`ZTERMC`). `Cont. Seq. No.` is
system-assigned.

**A PS has exactly one Content.** `CONTENTS` is an array and `Cont. Seq. No.` is a sequence
number, but the count is always one — verified across 28 arrays in every capture in the
repo, each holding a single entry numbered `1`. So one PS covers one product, and
`CONTENTS[0]` is *the* content rather than *a* content. More than one entry would be a data
fault.

**This explains the duplicate pairs.** `MATNR`/`ZMATNR` and `MAKTX`/`ZMAKTX` hold identical
values because the planner enters only the SNR10 and the system fetches the rest — they are
one fact, not two.

**The total quantity is not here.** `QUAN` is `1.0` in every capture and is not editable, so
the quantity a planner plans for is the `TRGQTY` chain on the levels, not a Content field.
`ZTOT_QUAN_C` carries the calculated grand total (`128.0` = the outermost level's
`TOTAL_QUAN`).

**"Relative Expiry Date" is a duration, not a date.** Expressed in months. An agent reading
`ZRELDATE` as an absolute date would be wrong.

### PSTV integration, worked

Host PS `40000303210` (product `0280.218.134`, AIR-MASS SENSOR) references PSTV
`6099014599` in its **PSTV Number** field. What that produces:

```
host 40000303210                          PSTV 6099014599
  Content                                   Content
    Product      192  0280.218.134            Product  16  6099.014.599
    6099014599        ← the PSTV
  Level 1                                   Level 1
    VERP   16  6000.851.835                   MWEG  16  6099.515.010
    VHIB   16  6099.944.002                   MWEG  16  6099.610.040
    VERP  192  6099.801.028                 Level 2   (empty)
    MWEG   16  6099.515.010  ←──────┐       Level 3   (empty)
    MWEG   16  6099.610.040  ←──────┤       Level 4
  Level 2                           │         MWEG   1  6099.100.500
    VHIB 10,000 6099.900.150        │         MWEG   1  6099.113.500
    VHIB    1  6000.138.359         │
    VERP    1  6099.816.874         │
    MWEG    1  6099.100.500  ←──────┘
    MWEG    1  6099.113.500
```

**The PSTV's elements are injected into the host's levels.** Every `MWEG` element on the
host comes from the PSTV — same material numbers, same quantities. PSTV Level 1 lands in
host Level 1; PSTV Level 4 lands in host Level 2. That is what the `ZKIT` flag marks.

**The PSTV appears inside the host's Content**, as a sibling of Product — which is why
`SUB_PS_ID` sits on the Content node.

**A PSTV's Packspec ID is its own material number.** `6099014599` is both the PS ID and the
product on its Content node (`6099.014.599`).

**A PSTV has no Determination Records — and the UI does not offer them.** Its Determination
tab carries only Print PDS / Label Preview / Label Data; the six type buttons
(`SHIP` `ZFER` `RCPT` `STOC` `PALE` `DOLL`) present on a normal PS are absent.

> **A PSTV's levels are tier slots, and they can have gaps.** This PSTV populates Level 1
> and Level 4 with Levels 2 and 3 **empty**. Contiguity — "populated levels run from Level
> 1 with no gaps" — holds for PS1–PS4, where the group fixes the count exactly. It does
> **not** hold for a PSTV, whose four levels are positions to fill as needed rather than a
> count to meet. *(A retired version of this corpus stated contiguity without that
> exception.)*

### PSTV integration — the rules, from source

Taken from the integration logic in `z0mp_cl_packspec_model`, so these are the system's
actual rules rather than inference from captures.

**Three gates before integration is allowed:**

1. The referenced PS must have PS Group **`PSTV`**. Anything else is an error.
2. The host must have **no Determination Record of type `STOC`, `PALE`, `DOLL` or `RCPT`**.
   PSTV integration is incompatible with the repackaging types and with goods receipt —
   only `SHIP` and `ZFER` remain.
3. The host must have **at least one Determination Record with Sales Channel `OE`**
   (`pack_usage = 'OE'`). Note this is Sales Channel, not Usage — the field SAP named
   `PACK_USAGE`.

**A PSTV has technical levels and logical levels, and only the logical ones matter.**

- **Technical levels** — always four. That is the PSTV template, unconditionally.
- **Logical levels** — those that actually carry elements, found by scanning the four.

Integration keys on the *logical* levels. The source says so directly — *"every PSTV PS has
always four levels, we determine the actual PSTV levels from elements & element group ID"*.

This is why the worked example shows Levels 2 and 3 empty: an empty technical level is the
normal appearance of a PSTV, not a gap and not a fault. Reading a PSTV's four levels as
four packaging tiers would be wrong; two of them usually hold nothing.

Only **one or two** logical levels are handled in the integration logic. Three or four
falls through a `WHEN OTHERS` that does nothing, and the `LT2` branch of the counting loop
is commented out — so a PSTV whose only logical level is Level 2 is counted but matched by
nothing. **Whether either case can arise in practice is not established.**

**Where the PSTV lands depends on both its own level types and the host's PS Group:**

| PSTV contributes | Host group | Lands on host |
|---|---|---|
| `LT1` only | PS2, PS3, PS4 | Level 1 — *"regardless of PS group"*. Host PS1 is an error |
| `LT4` only | PS1 → `LT1M`, PS2 → `LT2M`, PS3 → `LT3M`, PS4 → `LT4` | the **last level of that group** |
| `LT1` + `LT3` | PS3 | levels 1 and 2. Hosts PS1/PS2 are an error |
| `LT1` + `LT3` | PS4 | levels 1 and 3 |
| `LT1` + `LT4` | PS2 → levels 1 and 2; PS3 → 1 and 3; PS4 → 1 and 4 | Host PS1 is an error |

So the mapping is **neither purely positional nor a fixed tier** — it is a lookup on
(PSTV level types, host PS Group). The worked example is the `LT1`+`LT4` into PS2 row:
PSTV Level 1 → host Level 1, PSTV Level 4 → host Level 2.

**Quantities are rewritten on integration.** Every host level *not* receiving PSTV content
has its target, rounding and minimum quantity forced to **`1`**. On the levels that do
receive it, the host level's target quantity is **overridden by the PSTV level's** — except
where the host is PS1, which only defaults to 1 if empty. The UI then disables editing that
level's target quantity.

**The PSTV is always read at its active version**, whatever version the host is on.

### `LEVEL_TYPE` encodes position *and* whether the level is outermost

The source's level-type constants are `LT1`, `LT1M`, `LT2`, `LT2M`, `LT3`, `LT3M`, `LT4`.
The **`M` suffix marks the last level of the packaging specification** — a PS1's only level
is `LT1M`, a PS2's second is `LT2M`, a PS3's third is `LT3M`. PS4's fourth is plain `LT4`,
with no `M`.

Confirmed in captures for PS2 (`01:LT1  02:LT2M`); the other groups come from the source
constants only, as no capture in this repo holds them.

This is why Level Type is display-only on the screen: it follows from the level's position
and the PS Group, and is not a planner choice.

### The stacking factor enum, decoded

Three values now seen: `0 = not stackable`, `1 = stack of 2 (1+1)`, `2 = stack of 3 (2+1)`.
So `ZSTFAC` = *n* means a stack of *n*+1. The PSTV above is `0`; the host is `2`.

### A third thing called "kit"

The corpus already separates two: the `ZKIT` flag on an Element (inherited from an
integrated PSTV) and the `KIT` Determination Type (PSTU, returnable material). The screen
adds a third name for the first of those — the PSTV Number field lives under **"Kit
Packspec"**. Three names, two concepts.

**Why `SUB_PS_ID` is empty everywhere** is now clear: it is editable and real, but no
captured PS integrates a PSTV. The corpus's claim stands; the evidence simply isn't in this
repo.

## Level node

Same shape as Content: a projection of a master record plus a few inputs. Content projects
the **product** master; a Level projects the **packaging material**.

The evidence is direct — `LENGTH 544.0 · WIDTH 380.0 · HEIGHT 213.0` against
`HU_MAT_TEXT = "Mould, expanded plastic - 544X380X213"`. The level's dimensions *are* the
material's dimensions, restated as numbers.

### Entered vs calculated

| On screen | Field | |
|---|---|---|
| Target Qty | `TRGQTY` | **entered** |
| Total Qty | `TOTAL_QUAN` | calculated — cumulative product, `TRGQTY`(N) × `TOTAL_QUAN`(N−1) |
| Layer Qty | `PC_PER_LAYER` | **entered** — `0` in every capture in this repo |
| No. of Layers | *(does not travel)* | calculated |
| Level Seq. No. | `LEVEL_SEQ` | system |
| Level Type | `LEVEL_TYPE` | **display-only** — `LT1`, `LT2M`; not a planner choice |

Fetched from the packaging material: `HU_MAT_TEXT`, `HU_MATID`, `LENGTH`/`WIDTH`/`HEIGHT`,
`UNIT_LWH`. `ZMAINPACKMATNR` holds the material number itself.

`LT_DESCRIPTION` is only ever `"Level 1"` / `"Level 2"` — generic. The meaningful
description is the material's.

### Layers

**Layer Qty × No. of Layers = Target Qty.** The planner enters how many fit in one layer;
the system divides.

| | Target Qty | Layer Qty | No. of Layers | |
|---|---|---|---|---|
| PS1 Level 2 | 12 | 2 | 6 | 2 × 6 = 12 |
| PS2 Level 2 | 40 | 5 | 8 | 5 × 8 = 40 |

**Level 1 always shows `0` for both.** Layers describe how inner units are arranged on an
outer carrier, so the innermost level has no arrangement to describe.

**Only Layer Qty travels.** `PC_PER_LAYER` is the sole layer field in the payload, and
`No. of Layers` has no field at all — it is calculated on screen and lost at publish, like
`ZZSTAFA_REASON`. An agent can still recover it by dividing.

**In this repo `PC_PER_LAYER` is `0` on every level of every capture**, so no captured PS
records a layer arrangement — even where the geometry implies one. On `example1`, a
544×380 mould tiles into a 1200×800 pallet 2 across by 2 deep, giving 4 per layer against
a Target Qty of 8, i.e. 2 layers; the stack (2 × 213 + 150 = 576 mm) sits inside
`MAX_HEIGHT` 1000. On `example10` the same arithmetic gives 5 layers and 1030 mm against
`MAX_HEIGHT` 1050 — twenty millimetres of headroom, where six layers would overshoot. So
`MAX_HEIGHT` is a real constraint the arrangement respects, not a fetched decoration.

> Whether Layer Qty is optional because the tiling is implicit, or is entered precisely
> when the arrangement is *not* the obvious tiling, is **not established**.

### Reading the numbers

Quantities are displayed in European format: **`.` is the thousands separator, `,` is the
decimal.** `Total Qty: 48.000` is forty-eight thousand, not forty-eight.

| | Target Qty | Total Qty | |
|---|---|---|---|
| PS1 Level 1 | 4.000 | 4.000 | 4,000 |
| PS1 Level 2 | 12 | 48.000 | 12 × 4,000 = 48,000 |
| PS2 Level 1 | 300 | 300 | |
| PS2 Level 2 | 40 | 12.000 | 40 × 300 = 12,000 |

Both confirm the cumulative product. Misreading the separator changes an answer by three
orders of magnitude.

### Weight and volume live on another tab

The Level screen has three tabs: **Assigned Elements**, **Weight, Vol. & Dim.**, **Text**.

That explains a pattern the payload alone made look like corruption: the weight and volume
*units* are populated (`UNIT_GW = G`, `UNIT_GV = CDM`) while every corresponding *value* is
empty — `G_WEIGHT`, `N_WEIGHT`, `T_WEIGHT`, `G_VOLUME`, `N_VOLUME`, `T_VOLUME`, and all
capacity fields. Units without quantities on every level in every capture. The tab exists;
nobody in this corpus has filled it.

### Elements are managed from the Level screen

The **Assigned Elements** grid is where Element rows are created, with a *Display Pack.Mat.*
button mirroring Content's *Display Product Master*. Its columns include **Main Packaging
Material** as a **dropdown** — a blank row shows `2 Auxiliary Packaging M…`, so it is a
classification, not a material number.

That bears on the open `ZIDENTIFIER` question: the corpus says `'P'` marks the Main
Packaging Material, captures hold only `S`, `T`, `U`, and the screen shows a numbered
enum. Still unresolved.

Grid columns also include **Workstep I…** and **Label layout** — the element-level
`ZWORKSTEP` and `ZLABELLAYOUT` that are empty in every capture. They are real, editable, and
unused here.

### Element Group

`EG_ID` (20-digit) and `ELEMENTGROUP` (GUID) sit on the Level. Both Workstep screens carry a
field *"No. Used in EG"*, so Element Groups are referenceable objects that worksteps attach
to — a likely home for the element-level workstep. Registered as a dependent.

## Element node

Elements are the packaging materials at a level, managed in the **Assigned Elements** grid
on the Level screen. A level has one or more.

### The Main Packaging Material marker is `HURELEVANT`, not `ZIDENTIFIER`

The screen column is a dropdown reading **`1 Main Packaging Material`** or
**`2 Auxiliary Packaging Material`**. That maps to `HURELEVANT`, whose only values in the
captures are `1` and `2`.

**Exactly one element per level carries `HURELEVANT = 1`** — verified on all four levels
across two captures, including levels holding three, four and five elements. So the rule
"every Level has exactly one Main Packaging Material" is true, and this is the field that
expresses it.

> **The marker is not `ZIDENTIFIER`.** A retired version of this corpus stated that
> `ZIDENTIFIER = 'P'` marks the Main Packaging Material. Across every capture
> `ZIDENTIFIER` holds only empty, `S`, `T`, `U` — never `P` — and its values do not
> correlate with which element is the main one. Wrong field and wrong value; the marker is
> `HURELEVANT`, above. What `ZIDENTIFIER` does mean is unestablished.

| | Elements | `HURELEVANT` |
|---|---|---|
| example1 L01 | 3 | `1,2,2` |
| example1 L02 | 5 | `1,2,2,2,2` |
| example10 L01 | 4 | `2,1,2,2` |
| example10 L02 | 5 | `2,1,2,2,2` |

A worked case from the screens: PS1 Level 1 holds two elements — a Plastic Bag marked
*2 Auxiliary* and a Corrugated box marked *1 Main*.

### Other element fields

`ELEMENT_TYPE` — `VERP`, `VHIB`, `MWEG`. `ZPACKMATNR` holds the packaging material number,
shown on screen dotted (`6000.115.774`) and stored plain (`6000115774`). `ZOWNERSHIP`
carries `Property Bosch` or `Universal Packaging Mean`.

**Never populated in any capture:** `ZWORKSTEP`, `ZWORKSTEPGUID`, `Z_WS_DOC_EXISTS`,
`ZLABELLAYOUT` — all four are real, editable columns in the grid (*Workstep ID*,
*Label layout*), unused throughout this corpus.

---

**Derived from**

- `splunkExamples/example1–10`, `tests/fixtures/multi_target_fanout_page.xml` — all field
  names, values, populated/empty status, and the `PS_GROUP`↔level-count binding (8/8).
- `Edu/edu_ps/*.png` — screen layout, field labels, the six PS Group values, the eight
  Freight Modes, the 339 Lettering Orders, `WSType` meanings, and client `011` (visible in
  logical system `SAP0QD7011`).
- User, 2026-08-08 — PS Group chosen first from a dropdown; PS ID generated on enter;
  `TRGQTY` entered per level with the total calculated; `ZZSTAFA_REASON` prompted on a
  stacking-factor change.

**Verified** — every field-level claim was re-read from the captures rather than carried
from a summary. **Not verified:** the `Pref. Packspec`→`ZPREFBOM` mapping; the purpose of
`LEVEL_SET`; whether `PSTU`/`PSTV` bind level counts as the corpus states, since neither
appears in any capture. The screenshots are from **QD7**, the quality system, not PD7.

**Acceptance question** — A planner wants a four-level packaging specification but has
already created it as `PS2`. What are their options, and what would you check to confirm
the current state?
