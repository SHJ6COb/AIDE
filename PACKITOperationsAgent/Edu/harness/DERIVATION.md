# Derivation rules for the knowledge topics

A proposal: which of the eleven topics should be `always`, which should load on
demand, what backs each predicate, where the two large topics should be cut, and
what the always-loaded budget becomes.

Companion to [`BOUNDARIES.md`](BOUNDARIES.md), which establishes the domain line
this proposal keys off. Nothing here is implemented — this file is a draft, and
no existing file has been changed.

Inferences are marked **[inference]**. Byte counts are of `Topic.text` (the body
after front matter), which is what `load_all()` concatenates; measured
2026-08-08.

---

## 0. The thing to say first

**Editing `loads_when` reduces nothing.** `knowledge.load_all()` concatenates
every topic unconditionally (`knowledge.py:117-123`), and it is the only
function `harness.py` calls (`harness.py:306`). A topic marked
`has_multiple_hops` is delivered on every turn exactly as one marked `always` is.
Until selection is wired, changing a front-matter value is a change to a
comment.

That is the deliberate state, and `knowledge.py`'s docstring says so. This
document therefore has two halves that must not be confused: **§5 is the
proposal** (what each `loads_when` should say), and **§6 is what it would take
to make any of it true**.

---

## 1. Where the 74 KB came from

The growth is measurable against `git`. Baseline commit `5fcf131` already had
the eleven-file split, so the two states are directly comparable.

| Topic | `5fcf131` | today | Δ |
|---|---|---|---|
| `packaging-specification.md` | 4,855 | 35,284 | **+30,429** |
| `determination-record.md` | 6,454 | 21,738 | **+15,284** |
| `splunk-payload.md` | *(did not exist)* | 8,451 | +8,451 |
| `replication-flow.md` | 5,923 | 6,691 | +768 |
| `identifiers.md` | 4,096 | 4,117 | +21 |
| `ps-structure.md` | 3,176 | *(deleted — folded into `packaging-specification.md`)* | — |
| the six on-demand topics | 28,469 | 34,769 | +6,300 |

Always-loaded, at baseline: determination-record + identifiers +
packaging-specification + replication-flow = **21,328 bytes**. Today, with
`splunk-payload.md` added: **73,340 bytes** of body text.

Two topics account for **45,713 of the 52,012-byte growth in the always set —
88%.**

### 1.1 The single most important fact in this section

`ps-structure.md` declared `loads_when: mentions_structure`. It was folded into
`packaging-specification.md`, which declares `always`. **3,176 bytes of
explicitly on-demand content was reclassified as always-loaded by a merge**, and
the material that grew around it inherited the same classification.

The evidence that this was a merge and not a rewrite is still visible in the
file: `packaging-specification.md` refers to `ps-structure.md` twice as though
it were a separate document that disagrees with it —

> line 375: *"That contradicts `ps-structure.md`'s 'populated levels are
> contiguous starting from Level 1 (no gaps)'"*
>
> line 579: *"**`ps-structure.md` is wrong here.** It states the marker is
> `ZIDENTIFIER = 'P'`."*

— and no such file exists. Both are dangling references to the file this one
absorbed.

Consequently `mentions_structure` is now declared in `KNOWN_PREDICATES`
(`knowledge.py:52`) and used by **zero topics**. It is an orphan.

**So the split proposed below is not a new idea.** It restores a seam this
project already drew, and lost.

---

## 2. Two families of predicate, currently conflated

`KNOWN_PREDICATES`' docstring makes one claim about all eight: *"Each names
state the pipeline already computes for another reason."* That is true of five
of them and not of three, and the naming already gives it away — `has_*` versus
`mentions_*` / `is_*`.

The distinction is not cosmetic, because the two families are available at
different moments:

| Family | Evaluated against | Available on COMPOSE (`harness.py:1096`) | Available on EXPLAIN (`harness.py:1058`) |
|---|---|---|---|
| **Result predicates** (`has_*`) | `StatusResult` + `SearchParams` | **yes** | **no** — `params is None` by construction on that branch |
| **Question predicates** (`mentions_*`, `is_*`) | the user's message / `SearchParams` | yes | yes |

The EXPLAIN branch is reached only when the model made no tool call at all. It
receives `history` and nothing else. **No result predicate can ever be true
there.** This is exactly the asymmetry `knowledge.py`'s docstring anticipated —
*"code-selected loading for the status path (where the pipeline knows what it
found), or retrieval for the 'how does this work' path (where the question is
the only signal there is)"* — and it is the single biggest constraint on any
derivation rule.

**[inference]** The rot argument in that docstring applies unevenly across the
two families. A result predicate cannot rot silently: `superseded_count` and
`dependent_objects` are load-bearing for the status answer, so if they break the
answer breaks first and loudly. A question predicate has no such backstop — if
`mentions_documents` stops matching, the only symptom is a slightly worse
answer, weeks later. That argues for backing every question predicate with at
least one result-side signal wherever one exists, which §4 does.

---

## 3. Audit: what actually backs each predicate today

| Predicate | Declared by | Backing state | Where it is computed | Verdict |
|---|---|---|---|---|
| `always` | 5 topics | — | — | trivially available |
| `has_superseded_activations` | `activation-counter` | `StatusResult.superseded_count > 0` | `pipeline.select_live_activations`, already in the summary as `superseded_transfer_count` | **solid.** Result predicate, load-bearing elsewhere |
| `has_dependent_objects` | `dependent-objects` | `StatusResult.dependent_objects is not None` | `pipeline._lookup_dependent_objects`; `None` is itself meaningful (xOE rule) | **solid.** Same |
| `has_multiple_hops` | `triggers-and-hops` | `len(record.hops) > 1` for any record; also `len(primary_records) > 1` | `transform.group_transfers`; surfaced as `hops_at_target` and `transfers` | **solid**, with a caveat — the topic covers Re-publish (many *Transfers*) as well as Retrigger (many *hops*), so the predicate as named is narrower than the topic |
| `has_target_system` | `target-systems` | `params.target_system` or `record.target_system` | `transform._derive_target_system`; in `_SUBJECT_FIELDS` | **solid.** Note `record.target_system` is non-`None` on essentially every PS record, so as a *result* predicate this is nearly always true — it only discriminates as a *question* predicate (`params.target_system is not None`) |
| `mentions_documents` | `document-info-record` | question-side as named. Real signals exist: `params.document_number`, `params.message_type == DOCUMENT_INFO_RECORD`, non-empty `record.document_link_keys`, non-empty `dependent_objects.document_info_records` | `_SUBJECT_FIELDS` carries `ps_document_links`; `DependentObjectsView.linked_document_keys` | **needs re-backing** — the state exists, the predicate name does not reference it |
| `is_routing_question` | `routing` | question-side as named. Real signals: `StatusResult.routing_check is not None`; `target_system == "SAPPT00110"`; `sales_channel in {"IAM", "OES"}`; `change_number == "00000002"` with empty activation counter | `pipeline._check_routing_if_target_missing`; `_SUBJECT_FIELDS` | **needs re-backing.** `routing_check` alone is far narrower than the topic — it fires only when a target was named *and* nothing was found there |
| `mentions_structure` | **nobody** | — | — | **orphaned** (see §1.1). Question-side by nature: `ps_group` is on every record, so it cannot discriminate |

Two things follow.

**The five `has_*` predicates are in good shape and should not be touched.** Each
names state the pipeline computes because the answer needs it.

**Nothing in the pipeline can distinguish a structure question from a status
question.** Levels, elements, quantities and the PSTV are not extracted at all —
`transform.py` reads `HEADER.STATUS`, `PS_GROUP`, `AENNR`, `DOCUMENT_LINKS` and
the `OBJECTKEY` fields, and stops. So `mentions_structure` will always be a
question predicate. That is a legitimate category, not a defect; it just needs to
be labelled as one so nobody expects the status answer to break when it rots.

---

## 4. Proposed predicate vocabulary

Keep all eight. Change none of their names — renaming would churn every topic
file for no behavioural gain. Instead, **document the two families explicitly in
`KNOWN_PREDICATES`' docstring**, and define each predicate's evaluation in one
place so a question predicate is backed by result state wherever result state
exists.

Proposed definitions, as they would be evaluated on the COMPOSE path:

```
always                      → True
has_superseded_activations  → result.superseded_count > 0
has_dependent_objects       → result.dependent_objects is not None
has_multiple_hops           → any(len(r.hops) > 1 for r in records) or len(records) > 1
has_target_system           → params.target_system is not None
                              or len({r.target_system for r in records}) > 1
mentions_documents          → params.document_number is not None
                              or params.message_type is DOCUMENT_INFO_RECORD
                              or any(r.document_link_keys for r in records)
                              or result.dependent_objects is not None
is_routing_question         → result.routing_check is not None
                              or params.target_system == "SAPPT00110"
                              or params.sales_channel in {"IAM", "OES"}
                              or any(r.sales_channel in {"IAM", "OES"} for r in records)
mentions_structure          → question-side only (see §6.3)
```

**One new predicate is proposed**, `mentions_approval`, for the Determination
Record's approval half (§5.2). It is a hybrid: primarily question-side, but with
a genuine result-side signal that is already extracted —

```
mentions_approval           → any(r.packspec_status == "N" for r in records)
                              or any(r.change_number == "00000002" for r in records)
                              or question-side match
```

`ps_packspec_status` and `ps_change_number` are both in `harness._SUBJECT_FIELDS`
and both reach the model today. `HEADER.STATUS = N` means *no Determination
Record approved and released yet*, and `AENNR = 00000002` with an empty
activation counter is the PT0 pre-Active signature. Either one means the record
is somewhere in the approval workflow rather than through it — which is exactly
when the approval material earns its place.

**[inference]** This is the weakest predicate in the set, and if the appetite for
a new predicate is zero, the fallback is to leave `determination-record.md`
whole at 20,751 bytes and take only the `packaging-specification.md` split. That
alone gets 73,340 → 47,900, which is most of the benefit.

---

## 5. Per-topic proposal

### 5.1 Topics that need no change

| Topic | Bytes | `loads_when` | Reason |
|---|---|---|---|
| `splunk-payload` | 8,134 | **`always`** | This is the primary working surface. Every status answer is read out of a Splunk record, and this file is what makes the record legible — the three-layer nesting, `host`/`_time`/`source`, the double-escaping, the highlight markup, `_raw`, the `Type='S'`-on-an-ERROR trap. Removing it would not save 8 KB; it would break every answer |
| `identifiers` | 3,922 | **`always`** | 3.9 KB carrying the three things an answer must name to be actionable — SNR13 derivation, the `PACK_USAGE`/`ABRVW` collision, Message ID semantics. FINDINGS D10 is the cost of *not* having identifier discipline in front of the model. Cheapest high-value topic in the set |
| `replication-flow` | 6,441 | **`always`** | Defines Transfer, Message Type, Replication Status and TOPICSTRING — the nouns every answer uses. A Transfer is `(Message ID, Target System)`, not Message ID; without that the fan-out cases are unreadable |
| `activation-counter` | 1,643 | `has_superseded_activations` | Correct already, and cheap. Only relevant when `superseded_count > 0`, which is exactly when the answer must explain why records were dropped |
| `dependent-objects` | 7,029 | `has_dependent_objects` | Correct already. `dependent_objects is None` on every non-xOE target, and `skill.md` instructs the composing turn to say *nothing at all* about them there — so loading 7 KB about them is worse than useless, it is the exact "unasked fact volunteered" shape `skill.md` names as having already produced an invented detail |
| `triggers-and-hops` | 7,847 | `has_multiple_hops` | Correct already. Host shapes, Retrigger vs Re-publish and reprocessing cadence only bear on a chain with more than one hop |
| `target-systems` | 5,724 | `has_target_system` | Correct already, **but** see §3 — evaluate it against `params.target_system`, not `record.target_system`, or it is true on every turn |
| `routing` | 4,216 | `is_routing_question` | Keep the name, widen the backing per §4. As currently conceivable (`routing_check is not None`) it would load on perhaps one turn in twenty, and the PT0/VITAA half of the topic would then never load on the IAM/OES turns that need it |

Small optional trim, named for completeness and **not** recommended as a first
move: `replication-flow.md`'s **Expert View** entry (1,028 bytes) is about
reconciling against the Splunk dashboard, and belongs with `has_multiple_hops`.
It is not worth a separate change on its own.

### 5.2 `determination-record.md` — split, seam at the approval workflow

**Current: 20,751 bytes, `always`.**

The file holds two things. One is *what a Determination Record is and how to
read one off the wire* — needed on every turn, because the payload nests
`HEADER` inside `DETERMINATION` and every status question is a question about a
Determination Record. The other is *the PD7 approval workflow* — twelve Workflow
Statuses, two approval paths, sibling waits, rejection rollback, Extend versus
Revise. `skill.md` says the agent **never checks Workflow Status**, and nothing
in `transform.py` extracts it.

The seam falls at the `## Workflow Status` heading, with two exceptions carried
back across it.

**Core → `always` (~11,449 bytes)**

| Section | Lines | Bytes | Why it stays |
|---|---|---|---|
| `## Terms` | 9–41 | 4,407 | eight term definitions the index depends on; also the `SEQNO`-is-stable and *"PS X is stuck is ambiguous"* rules |
| intro + `## The wire agrees` | 42–68 | 941 | the `DETERMINATION`→`HEADER` nesting. Load-bearing for reading any payload |
| `## The key` | 69–108 | 1,717 | `DETTYPE`→party-field invariant, `MATNR_SNR13 = MATNR + PACKINDEX`, the `PACKINDEX`-is-alphanumeric trap, the `___` placeholders. Every one of these is read off the wire on a normal turn |
| `## Determination Types` | 109–124 | 554 | the enum `skill.md` maps business language onto |
| `## Usage` | 125–138 | 681 | the Sales Channel warning. Small and high-value |
| `## Validity gates publication` | 167–187 | 820 | *a future-dated record produces nothing in Splunk at all.* This is the most common honest explanation of a not-found result |
| Workflow Status **enum table only** | 193–207 | 656 | carried back across the seam: `60`, `35` and `37` appear in `TOPICSTRING` and are named in `splunk-payload.md`. Without the table those numbers are unreadable |
| `## Three states in which an approved record does not replicate` | 316–329 | 743 | carried back across the seam: the three invisible states are the answer to *"approved, and nothing arrived"* |
| `## What the wire does not carry` | 369–379 | 530 | the boundary statement itself |
| provenance footer | — | ~400 | rewritten for the smaller file |

**Remainder → `mentions_approval` (~8,676 bytes)** — `## Label fields point at
master data` and its dependent register (1,430); the approval-path branch
diagram and the `35`/`37` distinction (2,914); the sibling waits `65`/`70`
(1,813); *"Against the existing corpus"* (573); `## Lifecycle`, Extend vs Revise
and rejection rollback (1,946).

Everything in that remainder is PD7-side. None of it is observable in Splunk —
the file says so itself: *"the pre-publish stage is invisible to Splunk by
construction."*

### 5.3 `packaging-specification.md` — split three ways

**Current: 34,092 bytes, `always`.** The largest single item in the always set,
and by the domain owner's framing largely the far side of the PD7 boundary.

**Core → `always` (~8,980 bytes)**

| Section | Lines | Bytes | Why it stays |
|---|---|---|---|
| intro | 7–17 | 534 | *a PS is not the thing that replicates* — the sentence that orders PS against Determination Record |
| `**PACKIT**`, `**Packaging Specification (PS)**` | 20–26 | 789 | term definitions the index requires |
| `**Packspec Status**` | 27–36 | 2,031 | `ps_packspec_status` reaches the model on every turn. Includes the 2026-08-08 correction separating it from Workflow Status — the highest-value disambiguation in the corpus (see BOUNDARIES §4.1) |
| `**Change Number**` | 37–51 | 2,494 | `ps_change_number` reaches the model on every turn, and `00000002` + empty counter is the PT0 pre-Active signature. `transform.py:177-185` documents this field by pointing at exactly this entry |
| `**PS Group**` | 52–55 | 824 | `ps_group` reaches the model on every turn |
| *"A Packaging Specification has no plant"* callout | 143–147 | 360 | pulled out of the Org. Data tab. Plant enters only through the Determination Record; FINDINGS D9 is a fabricated plant code, and this is the sentence that says the question is malformed |
| `## What the wire carries, and what it does not` | 269–300 | 1,601 | the four confirmed instances and the *"this is what the PD7 pull is for"* conclusion. The abstention rule, and it must be present when abstention is needed |
| provenance footer | — | ~350 | rewritten |

**Structure and source-side detail → `ps-structure.md`, `mentions_structure`
(~22,484 bytes)** — restoring the file that was folded in:

| Section | Lines | Bytes |
|---|---|---|
| `## How one comes into existence` | 56–74 | 910 |
| `## The header` (planner/system fields, worksteps, the two traps, never-populated fields) | 76–126 | 2,364 |
| `## Org. Data tab` minus the no-plant callout | 128–161 | 1,151 |
| `## Archived Versions` incl. document part codes | 220–267 | 2,088 |
| `## Content node` incl. all PSTV integration | 302–461 | 8,339 |
| `## Level node` incl. layers, quantities, weight/volume | 463–561 | 4,657 |
| `## Element node` | 563–602 | 1,814 |
| provenance footer | 604–625 | 1,161 |

Note this is a **wider remit than the original `ps-structure.md`**: it takes the
header and Org. Data administrative detail and the Archived Versions material as
well as levels and elements. The unifying property is *the PS as the planner
builds it in PD7*, which is what a "how is this structured / what did it look
like before" question is about, and none of it is derivable from a Splunk record.

**Documents tab → appended to `document-info-record.md`, `mentions_documents`
(2,941 bytes)** — `## Documents tab`, the *Linking a document scopes it* section
and *A PS only ever links to its own system's documents* (lines 163–218). These
are about the PS→DIR edge, which is `document-info-record.md`'s subject, and one
of them explicitly retires a caveat that file currently carries. Moving them
puts a claim and its retraction in the same file.

Arithmetic check: 8,633 + 22,484 + 2,941 = 34,058 against a 34,092-byte original;
the 34-byte delta is heading whitespace at the cut points.

---

## 6. The resulting budget

### 6.1 Always-loaded

| Topic | Bytes |
|---|---|
| `splunk-payload` | 8,134 |
| `replication-flow` | 6,441 |
| `identifiers` | 3,922 |
| `determination-record` (core) | ~11,449 |
| `packaging-specification` (core) | ~8,980 |
| **Total** | **~38,926** |

**73,340 → ~38,926 bytes: a 47% cut, ~34.4 KB saved on every COMPOSE and EXPLAIN
turn.** At the ~4 chars/token rule of thumb that is roughly **8,600 tokens per
composing turn**, against a data payload `knowledge.py` measures in the low
hundreds.

Taking only the `packaging-specification.md` split and leaving
`determination-record.md` whole gives **~47,900 bytes**, a 35% cut, with no new
predicate.

### 6.2 What it does *not* do

Selection does not reduce the worst case. A question that trips every predicate
loads the whole corpus, which after splitting is the same ~108 KB it is today —
in fact marginally more, because each new file carries its own front matter and
footer. What changes is the **median** turn, and the fact that an unrelated topic
is absent rather than merely far away.

Estimated per-scenario loads, using the regression corpus's own shapes
**[inference — these are my reading of the scenarios, not measured]**:

| Scenario shape | Predicates true | Loaded |
|---|---|---|
| S01 — PS ID, long retry chain, no target named | + `has_multiple_hops` | ~46.8 KB |
| S04 — named target not found, routing gap | + `has_target_system`, `is_routing_question` | ~48.9 KB |
| S02 — dependent-object block on xOE with declared links | + `has_dependent_objects`, `mentions_documents`, `has_multiple_hops` | ~65 KB |
| A pure "what is a Determination Record" EXPLAIN turn | question-side only | see §6.3 |

### 6.3 The EXPLAIN path is the unsolved half

No result predicate can be true on the EXPLAIN branch (§2). Three options, in
increasing order of work:

1. **Load everything on EXPLAIN.** Honest, changes nothing measurable, and the
   branch is not the common one — 6 of 28 baseline turns took the no-search
   branch, and some of those were underspecified searches rather than domain
   questions. Recommended as the first step, because it makes the COMPOSE saving
   available without needing a retrieval mechanism to work first.
2. **Keyword/question predicates.** Deterministic matching over the user's
   message for `mentions_documents`, `mentions_structure`, `mentions_approval`,
   `is_routing_question`. Cheap, inspectable, and rots quietly — which is the
   cost `knowledge.py` warns about, and why it should fail open (§6.4).
3. **Retrieve over `Topic.summary`.** Each topic already declares a one-line
   summary written in exactly the "what it covers and when it applies" form
   `docs/AGENT_KNOWLEDGE_RESEARCH.md` §1.3 identifies as the whole routing
   signal. **`Topic.summary` is parsed, asserted non-empty by
   `tests/test_knowledge.py:40`, and read by nothing in the application.** The
   routing metadata is already built and unused.

### 6.4 Fail-open, in code, not in the prompt

Whatever evaluates the predicates must load **everything** when it cannot decide
— an exception, an empty predicate set, an unparsed question. The asymmetry is
the same one `pipeline.select_live_activations` reasons about: a missing
definition produces a confidently wrong answer with nothing to point at, while a
surplus topic costs tokens. Cheaper to be verbose than to be missing.

---

## 7. What wiring it would actually take

Six changes, none large, one of which has a mechanical cost worth knowing about
up front.

1. **`knowledge.py`** — add `select(predicates: Iterable[str]) -> str` alongside
   `load_all()`. Keep `load_all()`: `tests/test_knowledge.py:83` uses it to
   assert that no topic body was lost in a split, which is precisely the test
   that must survive a split.
2. **A predicate evaluator.** `predicates_from_result(result, params) -> set[str]`
   belongs next to `StatusResult` in `pipeline.py` — it reads only that
   dataclass. `predicates_from_question(history) -> set[str]` belongs in
   `harness.py` or its own module. `always` is unconditional in both.
3. **`harness._load_skill(mode)` gains a selection argument.** This is the
   mechanical cost: **13 tests monkeypatch it with a one-argument lambda** —
   `tests/test_harness.py` at lines 322, 353, 379, 400, 427, 447, 610, 630, 715,
   752, 783, 814 and `tests/test_server.py:36`, all `lambda mode: "test skill
   instructions"`. Every one raises `TypeError` on the new signature. A default
   argument (`selection: frozenset[str] | None = None`, meaning "everything")
   avoids all thirteen edits and preserves the fail-open default in the same
   stroke.
4. **Two call sites.** `harness.py:1096` (COMPOSE) has `status_result` and
   `params` in scope already. `harness.py:1058` (EXPLAIN) has only `history`;
   per §6.3 it should pass nothing at first and take the full glossary.
   `harness.py:981` (PARSE) needs no change — it already receives no glossary,
   and `skill.md`'s turn-1 section is written to match.
5. **`KNOWN_PREDICATES`' docstring** — record the two families (§2) and, for each
   question predicate, name the result-side signal that partially backs it. The
   current text claims all eight are pipeline-backed, which was only ever true of
   five.
6. **`CONTEXT.md` and the tests.** See §8 — the split cannot land without them.

---

## 8. What a split costs, concretely

`tests/test_knowledge.py` enforces four invariants, and a split touches three.

**`test_every_topic_parses_and_declares_a_known_predicate` requires every topic
to define at least one term** — `_terms(topic.body)` must be non-empty, where a
term is `**Name**:` alone on a line.

This is the sharpest constraint on the split, and it is easy to miss. The
structure sections of `packaging-specification.md` contain **no** such heading —
Content, Level and Element use `##`/`###` headings and mid-sentence bold. So a
restored `ps-structure.md` **fails this test as a straight cut**. Three ways out:

- move a genuine term into it (`**PS Group**` is the natural candidate — but it
  reaches the model on every turn as `ps_group`, so moving it costs a
  disambiguation the core needs);
- write term headings for concepts the file already explains without formally
  defining — **Content node**, **Level**, **Element**, **PSTV** — which is
  arguably an improvement, since `CONTEXT.md` would then index them;
- relax the test to allow a topic that defines no term.

**The second is recommended.** The same applies to a `determination-record`
remainder, though less severely: `**Workflow Status**:` is a real term heading
and would move with the approval half — except the enum table stays in core
(§5.2), so the term and its table would separate. Simplest resolution: keep the
`**Workflow Status**:` term *and* the enum table in core, and let the remainder
carry new headings for **Recipient approval** and **Sibling wait**.

**`test_no_term_is_defined_in_two_topics`** — any new term heading must be
genuinely new, not a second copy of one that already exists elsewhere.

**`test_context_index_lists_exactly_what_the_topics_define`** — `CONTEXT.md`
must gain a row per new file and an entry per new term. Its `Loads when` column
becomes the human-readable statement of this proposal, which is a good place for
it to live.

**`test_load_all_carries_the_facts_answers_depend_on`** — asserts six load-bearing
strings survive. `"Packspec Status"` and `"Create Second Version"` both live in
sections this proposal moves; both stay inside `load_all()`'s output, so the test
passes unchanged. It is worth **adding one string per new file** for the same
reason the existing six exist.

Two documentation debts a split should clear while the files are open, both
noted in BOUNDARIES:

- the two dangling `ps-structure.md` references (§1.1) — the file is being
  restored, so they become correct again rather than needing deletion;
- `transform.py:172-175`'s claim that `packspec_status` is the *"same concept as
  TOPICSTRING's numeric code"*, which `packaging-specification.md` corrected on
  2026-08-08 and now contradicts.

---

## 9. Risks, and what could not be determined

**The benefit is unmeasured on this corpus.** `regressionSuite/FINDINGS.md`
documents invented detail thoroughly — D6, D8, D9, D10 — and traces **none of it
to always-loaded glossary text**. D9's fabricated plant comes from a field the
model never receives; D8's fabricated count from data it did. The mechanism
`knowledge.py` describes is well supported in the literature
(`docs/AGENT_KNOWLEDGE_RESEARCH.md` §0, layer 2) and `skill.md` names two
concrete cases of an unasked fact being volunteered — but the specific claim that
*this* glossary caused *this* project's invented detail is a hypothesis, not a
finding. Treat any post-change score as one sample of a nondeterministic system,
per FINDINGS §3's own caveat.

**Selection can only remove; it cannot warn.** Once `dependent-objects.md` is
absent, nothing tells the model it is absent. `skill.md` handles the analogous
case for data (*"if the glossary doesn't cover what's being asked, say plainly
that you don't have documented information"*) — but a model cannot distinguish
"not in the glossary" from "not in the glossary *this turn*". **[inference]** A
one-line manifest of topic names withheld, or simply loading `Topic.summary` for
every unselected topic (~140 bytes each, ~800 bytes for all six), would preserve
the ability to say *"there is documented material on that, ask me directly"*.
That is a cheap addition and I would recommend it.

**A predicate that is nearly always true saves nothing.** `has_target_system`
evaluated against `record.target_system` is true on essentially every PS record.
The proposal fixes this by evaluating against `params.target_system`, but the
same trap is latent in `mentions_documents` — `document_link_keys` is non-empty
on a good share of real PSs, which would pull in 11 KB routinely. **This is not
measured**; the corpus's rate of PSs with declared document links was not
determined here, and it should be before that predicate is trusted.

**Could not be determined:**

- **The token figures the existing docstrings cite cannot be verified.**
  `knowledge.py` says the pre-split `CONTEXT.md` was *"~11,000 tokens"*;
  `harness._load_skill` says *"~12,200 tokens"*. Neither is checkable — every
  version of `CONTEXT.md` in this repo's history is the 2.8 KB index, so the
  48-entry file predates the first commit. All token figures in this document
  are 4-chars-per-token estimates over measured bytes, and should be replaced
  with a real tokenizer count before anything is claimed about cost.
- **Whether `Part 100` archive documents replicate** — no capture holds one, and
  `packaging-specification.md`'s summary table asserts they do not while the
  section above it says absence proves nothing either way. This affects only
  whether the Archived Versions material is *purely* PD7-side or merely mostly
  so; it does not change the placement.
- **The real distribution of predicate hits across production traffic.** The
  per-scenario estimates in §6.2 are read off the regression scenarios' shapes,
  not measured. The cheapest way to settle it is to compute the predicate set on
  every turn and log it *without* acting on it — a read-only instrumentation pass
  that would produce a real histogram before any content is withheld from any
  answer.
