---
concept: determination-record
summary: The Determination Record: the packaging rule assigned to a customer/supplier at a plant for a movement type. The unit a user actually asks about, and the unit that replicates.
loads_when: always
---

# Determination Record

## Terms

**Determination Record**:
The lookup/routing rule, created after a PS exists, that maps a real-world transaction context to the PS that should apply. Keyed by Determination Type + Material (SNR10) + Plant + Usage + (Customer Index, for outbound, or Supplier, for inbound). Decouples "which PS exists" (defined by the planner) from "which PS applies right now" (resolved automatically at transaction time). Goes through an approval workflow, tracked by Workflow Status. **One PS can be assigned to many Determination Records** — confirmed real: a PS for a given Material (SNR10) can serve multiple Customer Index/Supplier + Plant combinations, each with up to 5 Usages (Regular + up to 4 Alternatives). Technical field `SEQNO` on a Transfer's `OBJECTKEY` distinguishes which specific Determination Record (of potentially several for the same PS) that Transfer concerns. **Confirmed 2026-08-06: it is a stable ID**, each new Determination Record taking the next available sequence number from the Source System — not an assignment-order counter that can shift, so a `SEQNO` keeps meaning the same record for that record's life.
**Assigning an existing PS to a further Plant/Customer Index/Supplier is an Extend**: it creates a *new* Determination Record with a new `SEQNO`, while the PS structure — and therefore its Activation Counter — is untouched. So "PS X is stuck" can be true of one Determination Record and false of every other one on the same PS, and a status answer that names only the PS is ambiguous about which.
**The Determination Record is what an End User actually has in hand — confirmed 2026-08-06.** Nobody asks "what is PS X doing"; they arrive with a context — product, customer or supplier, plant, Usage, Determination Type — and the real question is *how do I pack this*. The answer is an approved and released packaging rule, and `PS_ID` is that rule's identifier. Answer from the Determination Record first, and reach the PS only through it.

**Determination Type**:
The category of business transaction a Determination Record resolves a PS for. Known values: SHIP (outbound shipping), RCPT (goods receipt), ZFER (internal shipping/transfer), STOC (repacking to stock), PALE (repacking to pallet), DOLL (repacking to dolly), KIT (confirmed real, live — assigned to PS Group PSTU, tracking order-accumulated MWEG/returnable packaging material rather than actual product packaging).

**Customer Index**:
A code identifying a specific customer on an outbound (SHIP-type) Determination Record, playing the same structural role that Supplier plays on an inbound (RCPT-type) Determination Record.
_Avoid_: Index, Packaging Index Number, PACKINDEX

**Usage**:
Identifies which of up to 5 independently-valid ways a product can be packed for a given Customer Index/Supplier + Plant combination: Regular, or Alternative 1 through Alternative 4. All can coexist with no runtime precedence between them, but creation is sequential: Alternative N cannot be created until Alternative N-1 (or Regular, for Alternative 1) already exists.
**Technical field `ABRVW`** — confirmed 2026-08-06, real values seen: `R` (Regular) and `A1` (Alternative 1). Carried on the Determination Record and on `OBJECTKEY`, so it is part of the business object's identity.
_Avoid_: Don't confuse with Sales Channel — an unrelated field which SAP confusingly named `PACK_USAGE`.

**Workflow Status**:
The approval state of a Determination Record — **a code with a short description, one field carrying both**, not a business status and a technical code as two separate things. Twelve values, tied to a Workflow ID; the full enum and the two approval paths are below.
_Avoid_: Status code (see the correction below — it is not a separate field)

**Suggested Action**:
Plain-language guidance the agent gives an end user about what to do next regarding a Determination Record's Workflow Status (e.g. who it's awaiting approval from, or what to fix after a rejection). Informational only — **the agent is read-only and never performs the action itself**; a human still acts in PACKIT/SAP.

**Packaging Planner**:
The internal role that creates and maintains Packaging Specifications.

**End User**:
An internal staff member (e.g. packaging engineer, brand/product manager, supply chain ops) who queries the agent about spec status. Excludes external parties such as vendors or co-packers.
_Avoid_: User, customer

---

A **Determination Record** is the assignment of a packaging rule to a customer or supplier,
at a plant, for a kind of movement. It is created after a Packaging Specification exists,
goes through an approval workflow, and — once approved — is **the thing that replicates**.

Answer from the Determination Record first, and reach the Packaging Specification through
it.

## The wire agrees

The payload nests the packaging specification *inside* the determination record:

```
SINGLEMESSAGEBODY
  └─ DETERMINATION          ← the Determination Record
       ├─ its key fields
       ├─ DOCUMENT_LINKS
       └─ HEADER            ← the Packaging Specification
            ├─ CONTENTS
            └─ LEVELS → LEVEL_ELEMENTS
```

So a Transfer does not carry "a PS with some routing attached". It carries a Determination
Record whose cargo is a PS. Any question about status, failure or destination is a question
about a Determination Record.

## The key

| Meaning | Field | Values seen |
|---|---|---|
| which record, for this PS | `SEQNO` | `00001`, `00002` |
| kind of movement | `DETTYPE` | `SHIP`, `RCPT` |
| product | `MATNR` (SNR10) | `0273011047`, `0265025049`, `F00SC01107` |
| customer | `PACKINDEX` | `211`, `B7L` |
| supplier | `SUPPLIER` | `0000131512` |
| plant | `WERKS` | `0780`, `3980`, `5550` |
| usage | `ABRVW` | `R`, `A1` |

**Which party field is populated is decided by the Determination Type**, and an empty pair
is meaningful rather than missing:

| `DETTYPE` | `PACKINDEX` | `SUPPLIER` |
|---|---|---|
| `SHIP` — outbound to a customer | **set** | empty |
| `RCPT` — inbound from a supplier | empty | **set** |
| `STOC` / `PALE` / `DOLL` — repackaging | empty | empty |

Verified on every PS capture in the repo: five `SHIP` records all carrying `PACKINDEX` with
`SUPPLIER` blank, two `RCPT` records the reverse. The repackaging case is from the user and
has no capture.

`PACKINDEX` is a **3-character alphanumeric** code (`211`, `B7L`, `0MN`, `9MU`) — anything
treating it as a number will mangle it. In DIR captures the same slots hold `___` and
`__________`, which are **placeholders, not values**.

`MATNR_SNR13` is **derivable** — it is `MATNR` + `PACKINDEX`. Confirmed on
`0265025049`+`B7L`, `0273011047`+`211`, and `F00SC01107` with no index, where SNR13 equals
SNR10.

### Fields carried but not explained

Present on the `DETERMINATION` node, values observed, meaning **deferred by decision** on
2026-08-08 — not unknown, not unasked: `INBOUNDKEY` (`F`), `VSZTP` (`4`), `BRAND` (`MOT`,
`ZF`), `COUNTRY_ID` (`DE`, `MX`), `VALIDITY_TZONE` (`CET`), and `ORIGINAL_INDEX` (never
populated). An agent should not reason from them.

## Determination Types

| Code | Movement |
|---|---|
| `SHIP` | outbound shipping — to a customer |
| `RCPT` | goods receipt — from a supplier |
| `ZFER` | internal shipping / transfer |
| `STOC` | repacking to stock |
| `PALE` | repacking to pallet |
| `DOLL` | repacking to dolly |
| `KIT` | PSTU only — order-accumulated returnable material, not product packaging |

The six non-`KIT` types appear as **buttons on the Packaging Specification screen**, so a
Determination Record is created from inside the packspec transaction rather than
separately.

## Usage

Which of up to five valid ways a product may be packed for one customer/supplier + plant
combination: **Regular**, or **Alternative 1–4**. Technical field `ABRVW`, values `R` and
`A1`.

All coexist with no runtime precedence between them, but **creation is sequential** —
Alternative 2 cannot exist before Alternative 1.

> Not to be confused with **Sales Channel**, which SAP named `PACK_USAGE`. The word "usage"
> appears in the technical name of one and the business name of the other, pointing at
> different things. `PACK_USAGE` and `LABEL_SALESCHANL` (`OE`, `OES`) are **identical in
> every capture in this repo**, though the corpus holds that they are separable.

## Label fields point at master data

A Determination Record carries `DET_LABEL_CONTROL` (`YKLT`) and `DET_LABEL_FORMAT`
(`YF02`). **Label is separate master data** — these are references into it, not values to
interpret, and the label object itself is a dependent that this topic does not open.

Labelling runs across both topics and is worth seeing as one thing rather than several
stray fields: the PS header's four **Lettering Orders** (worksteps of type `LEOR`), the
element grid's **Label layout** column, the Determination Record screen's **Label Preview**
and **Label Data** buttons, and these two fields.

### Dependent register

Master objects and configuration reached from these topics, named and deliberately not
pursued. Each needs its own topic eventually; none should be reasoned about from a passing
reference here.

| Dependent | Reached from |
|---|---|
| **Label** | `DET_LABEL_CONTROL`, `DET_LABEL_FORMAT`, `ZLABELLAYOUT`, Lettering Order |
| **Workstep** (`WS01`) | Lettering Order (`LEOR`), Freight Mode (`FMOD`) |
| **Document Info Record** | `DOCUMENT_LINKS`, the Documents tab |
| **Packaging material** | `ZPACKMATNR`, `ZMAINPACKMATNR` |
| **Product master** | the Content node projects it |
| **Element Group** | `EG_ID`, and worksteps' *No. Used in EG* |
| **Customization** (SPRO/EWM) | PS Group values, Transport Device values |
| **PD7 OData service** | the pre-publish stage — a routing concern |

## Validity gates publication

`VALID_FROM` is not documentation. **An approved Determination Record does not publish
until its validity has begun.**

Every dated capture confirms the direction — the record reached Solace only after its
`VALID_FROM` had passed:

| | `VALID_FROM` | published |
|---|---|---|
| example1 | 2025-10-31 | 2026-08-03 |
| example10 | 2025-11-26 | 2026-07-29 |
| multi_target_fanout | 2026-07-23 | 2026-07-30 |

**A future-dated Determination Record produces nothing in Splunk at all** — not an error,
not a pending event, nothing. So silence in the log is a legitimate state, and the record
may be perfectly healthy and simply not due yet.

`VALID_TO` is **out of scope** — by decision, not oversight. Note only that it carries two
different "no end" sentinels, `2999-12-31` and `9999-12-31`.

## Workflow Status

The approval state of a Determination Record. **A code with a description — one field, not
two.**

| Code | Description | |
|---|---|---|
| `05` | Request Created | |
| `10` | New | |
| `20` | In Progress | |
| `30` | Internally Approved | approved here, but not yet the end |
| `35` | Waiting for SNR13 creation in VitAA | |
| `37` | Waiting for VitAA feedback | |
| `40` | Rejected | |
| `45` | Rejected by VitAA | |
| `50` | **Deleted** | where a rolled-back record lands |
| `60` | **Accepted** | the only status that publishes |
| `65` | Affected relations still in review | |
| `70` | Affected relations still in VitAA review | |

### The approval path branches on Sales Channel

Both routes have **two gates**, and they share the second one.

```
                        20  In Progress
                              │
            OE ───────────────┴─────────────── IAM/OES (MA)
             │                                      │
   30  Internally Approved                35  handed to VitAA —
       = PLANT approval                       SNR13 not yet created there
             │                                      │
             │                              37  SNR13 available —
             │                                  awaiting VitAA feedback
             │                                      │
             │                              [70 if siblings pending]
             │                                      │
             └──────────────┬───────────────────────┘
                            │
                   RECIPIENT approval
                            │
                   [65 if siblings pending]
                            │
                       60  Accepted
```

| Sales Channel | Gate 1 | Gate 2 |
|---|---|---|
| `OE` | Internal — **plant** approval (`30`) | recipient approval |
| `IAM`/`OES` (also called MA) | **VitAA** approval at PT0 (`35`→`37`) | recipient approval |

**`OE` never goes near VitAA.** It moves `20` → `30` on plant approval, then to recipient
approval. The four VitAA statuses simply never arise.

**`35` and `37` are two distinct waits inside the VitAA gate**, and the difference is
whether the SNR13 exists yet:

- **`35`** — the PS has been handed to VitAA, but the **SNR13 it carries does not yet exist
  in VitAA**. Waiting for that SNR13 to be created in the VitAA application at PT0.
- **`37`** — the PS has been handed to VitAA, **the SNR13 is available**, and it is now
  waiting for VitAA's feedback or approval.

So `35` is waiting on data, `37` is waiting on a decision. An agent that reports both as
"waiting for VitAA" loses the only actionable difference between them.

**`30` means plant approval specifically.** "Internally Approved" is not a general-purpose
approved state — it is the OE path's first gate, and a record sitting there still has
recipient approval ahead of it.

> **Who the recipient is, is not known.** Asked of the domain owner on 2026-08-08; the
> answer was not available. Candidates considered and none confirmed: the **customer** on a
> `SHIP` record and the **supplier** on an `RCPT` (which would make "recipient" a role that
> changes with Determination Type); the **receiving plant**, given `30` is already plant
> approval; or the organisation owning the **target system** that consumes the rule.
>
> This matters because recipient approval is the last gate before `60`, so it is the state
> most often reported. An agent should say *"waiting for recipient approval"* and **not**
> name who — naming a party here would be invention.

### The sibling waits belong to a scenario, not to every record

`65` and `70` are the same idea at different gates — one record is through, others on the
same PS are not:

| | Gate |
|---|---|
| `70` | affected relations still in **VitAA** review |
| `65` | affected relations still in **recipient** review |

> **They arise only in the PS change (Revise) scenario.** Create and Extend never produce
> them, because an extending record's stakeholders had no prior dependency on the PS. So
> seeing `65` or `70` is itself evidence that a packaging rule was revised — not created,
> not extended.

### What this settles

**The sibling wait has a code.** `65` and `70` — *"affected relations still in review"* —
are the revise fan-out seen from one record's side: this record is done, others on the same
PS are not. So the state is observable in the source system, even though it produces
nothing in Splunk.

**Rejection rollback lands at `50`.** When one record rejects and every sibling approval is
revoked, `Deleted` is the status they take. Reading `50` as a deliberate deletion is the
mistake to avoid — it is far more often the consequence of somebody else's rejection.

**There are two rejection paths** — `40` Rejected and `45` Rejected by VitAA — and two
review-wait paths, `65` and `70`. VitAA duplicates the ordinary path rather than replacing
it.

**`30` is not the finish line.** *Internally Approved* precedes the VitAA stages and
`60 Accepted`. A record at `30` is approved and will not publish.

> **VitAA appears in four of the twelve statuses** — `35`, `37`, `45`, `70`. The corpus
> knows it only as *"the specific trigger that sends a PS to PT0"*, which is plainly
> incomplete: it is a participant in the approval workflow with its own waits and its own
> rejection. Registered as a dependent.

### Against the existing corpus

`determination-record.md` records these as **two** concepts — *Workflow Status* as a
business outcome (*"e.g. Accepted, Rejected, pending"*) and *Status code* as a separate
*"numeric, internal SAP workflow-step code (e.g. 40, 50, ZZ)"* underlying it.

The screen shows **one** field carrying both a code and its short description: `40` *is*
Rejected, `60` *is* Accepted. The "e.g." values in the corpus are that single enum sampled
from both columns and split into two entries. `ZZ` appears nowhere in the twelve and its
status is unknown.

## Three states in which an approved record does not replicate

These are properties of the system, not instructions. All three are invisible in Splunk —
each produces no event at all — so they are indistinguishable from one another, and from a
too-narrow search, by observation alone.

| State | Cause | Is it a fault? |
|---|---|---|
| Not yet valid | `VALID_FROM` has not been reached | No — timing |
| Waiting on a sibling | the PS was revised, so *every* Determination Record on it must approve before any publishes | No — process |
| Rolled back | a sibling rejected; every approval on the PS is revoked and all records go to delete status | Yes |

A record can be fully approved on its own terms and still be blocked by a second state.

## Lifecycle

A packaging rule is created, assigned to a Determination Record, approved, and only then
does the approved record — carrying its packaging specification — flow to the target
systems where the shopfloor uses it.

**Extend** — adding a Determination Record to an already-active PS. Each new record
approves **independently**, because its stakeholders had no prior dependency on that PS.
The PS's Change Number and Activation Counter both stay put.

**Revise** — changing the packaging rule itself. **Every** Determination Record on the PS
must now approve, because every one of them depends on a rule that is about to change. The
fan-out exists to inform existing stakeholders.

So the asymmetry follows one principle: **approval fans out to whoever already depends on
the thing being changed.** Extenders are exempt because they do not yet depend on it — and
once approved they join the set that must approve next time.

A diagnostic falls out of that: **if one record is waiting on another, it is a revision,
not an extension.**

### Rejection is all-or-nothing

If any one record rejects, **every other approval on that PS is rolled back** — including
records already approved — and all are set to delete status. The user then adopts the
change if still wanted and retriggers the workflow.

Two consequences an agent will be asked about directly:

- *"I approved this — why does it show as not approved?"* During a revision, approval is
  not durable. Someone else's rejection revokes it, silently, with no action by the person
  who gave it.
- *"Why is my Determination Record being deleted?"* It is not. Delete status here is
  reached by a path unrelated to deletion — a sibling rejected.

> **"Retrigger" here means the approval workflow in PD7**, restarted before anything
> publishes. It is a different thing from the replication-side Retrigger, which re-sends an
> existing message to a target while reusing its Message ID.

## What the wire does not carry

The pre-publish stage is invisible to Splunk by construction — captures only exist once
something publishes. So the planner's choices, the approval fan-out, the rejection
rollback and a not-yet-valid record are all outside what any Splunk search can reach.

The source system exposes this stage through an **OData service** on PD7. That is a
routing concern — when to reach for it, and on whose say-so — and is deliberately not
recorded here. Registered as a dependent: **PD7 OData service**.

---

**Derived from**

- `splunkExamples/example1–10`, `tests/fixtures/multi_target_fanout_page.xml` — the
  `DETERMINATION` node's fields and values, the `DETTYPE`→party-field invariant, the
  `MATNR_SNR13` derivation, and the `VALID_FROM`-precedes-publication evidence.
- `Edu/edu_ps/PS screen.png` — the six type buttons and the Request WF button.
- User, 2026-08-08 — the planner's flow; Extend vs Revise approval semantics; rejection
  rollback to delete status; `VALID_FROM` gating publication.

**Verified** — field-level claims were read from the captures. **Not verified:** the
repackaging types' empty-party rule (no capture); whether `PACK_USAGE` and
`LABEL_SALESCHANL` ever diverge; the exact `Workflow Status` and `Status code` enums, both
recorded in the existing corpus with "e.g." before their values.

**Acceptance question** — A Determination Record shows as approved, and nothing has
appeared in Splunk. What are the possible explanations, and what would you check first?
