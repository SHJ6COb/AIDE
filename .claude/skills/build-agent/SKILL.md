---
name: build-agent
description: Build an AI agent that answers accurately — its knowledge, its wiring, and its harness. Works on a new project or an established one.
disable-model-invocation: true
---

Induct the agent the way you would induct a new colleague: teach it the product, teach
it the job, then supervise it until it can be trusted. This skill covers all three.

**Prose persuades; code enforces.** For every rule you write, ask: would a wrong outcome
cause a wrong decision, and would it do harm that cannot be taken back? A
yes to either puts the rule in the harness, and the written version survives only to
explain why the harness does what it does. The second question earns its place because
some harms — a disclosure, a figure that has left the building — land outside the answer
entirely and are never undone by a better one.

You are the scribe. Structure is yours to derive; meaning is the user's to give.

**Every turn, in every phase** — state your reading, name where you are least confident,
ask **one** question, stop. File the answer before asking the next. Do everything the
evidence can settle before you stop; the one question is for what only the user can
answer. A phase needing several such answers takes several turns, and that is its
expected shape rather than a failure to finish.

## Survey first

Read everything that already exists before spending the user's attention: source, prior
prompts, docs, sample payloads, logs, exported records. Above all, transcripts of the
agent answering **wrongly** — a wrong answer marks exactly where knowledge is missing,
which nothing else does as precisely.

Survey what the user handed over, plus whatever that material references. Where it
points at sources beyond reach — a repository, a ticket queue, a system you cannot open
— name them and ask, rather than treating the handed-over subset as the whole.

Then write two lists: what you derived, and what you could not. The derived list is the
**reading** you state at the top of your first turn; the could-not list is the interview
queue and belongs in `OPEN-QUESTIONS.md`, which is created before you first hand back,
alongside the index. The turn's one **question** is drawn from the second list.

**The interview covers the second list only.** In a new project the first list is empty
and the interview covers everything; established projects start with most of the
structure already in hand. The loop below is the same either way.

**On a first session the artifact request is turn one, and it is that turn's one
question.** Name what would help most, ranked. An empty project directory settles nothing
about what the user holds in a ticket queue, an inbox, or their head, so ask before
concluding — and everything else waits its turn in `OPEN-QUESTIONS.md`. Once they confirm
there is nothing, probe with concrete scenarios instead, and record there that the session
ran without evidence.

**On a resumed session** — a corpus already exists — open on the highest-value entry in
`OPEN-QUESTIONS.md` instead, building that queue from your survey if no one has yet.
Re-asking for artifacts every session spends the user's turn on something they have
already answered.

## The index

`INDEX.md` is what the agent loads every turn, and the ledger a later session resumes
from. **Create it before you first hand back to the user**, whatever phase you have
reached — from inside a session you cannot tell whether the user will answer or walk
away, so the first stop is the trigger rather than the last. Refresh it at every stop
after that.

It starts mostly empty, and carries at least these sections:

- **Concepts** — a row per concept: file, status, what it was derived from, its
  acceptance question, and whether that question passes. Useful statuses include `named
  only`, `written`, `verified`, `disputed — unsafe to cite`; a question not yet put to a
  running agent is `not run`. **Name every concept here even while its file is unwritten
  or unloaded**, so the agent knows a thing exists without holding it. Otherwise absence
  and non-existence look identical, and it will confidently deny things that are true.
  Only concepts get rows — an index like `GLOSSARY.md` is a destination, not a concept.
  On a first session the table is legitimately empty; say so in words, since a reader
  cannot tell an empty table from an undiscovered domain.
- **Stopped at, resume here** — the open question, and what the next session does first.
- **Payload contract** — filled in Phase 2. Until then say so, so silence is not
  mistaken for a decision already taken.
- **Routing** — a one-line state summary, filled in Phase 2. The task table and the
  ask-triggers themselves live in `ROUTING.md`.
- **Guardrail classification** — filled in Phase 3.

## Phase 1 — Teach the product

One **focal concept** per session, in its own file. Anything surfacing outside it —
volunteered by the user or found in the artifacts — gets one line in the right
destination, then return to the thread: depth on the focal concept, capture-only on
spill. Where the spill belongs to a concept that has no file yet, name that concept in
`OPEN-QUESTIONS.md` rather than opening a file you will not fill this session.

**Choosing it:** take the concept the wrong answers cluster around — a summary of what
the agent got wrong serves, when the transcripts themselves are gone. With no wrong
answers to go on, take the one the most other concepts lean on: the term that keeps
appearing inside the explanation of everything else. With nothing to read at all, the
first concept is the user's to name — once they confirm there is nothing to hand over,
ask which question this agent will face most often, and start with the concept that
question is about. Narrow beats broad: a concept
you can finish this session is worth more than the important one left half-written.

**Write what you derived, and mark what you inferred.** Structure taken from artifacts
goes into the file straight away; meaning you have guessed at goes into the same file
under an explicit unverified note, so the user corrects a draft rather than filling a
blank page. What survives their correction loses the note.

Destinations, created when they first have something to hold:

| File | Holds |
|---|---|
| `knowledge/<concept>.md` | how one concept actually works — **the default destination** |
| `PROCEDURE.md` | how the task is done |
| `ROUTING.md` | which task a request is, and when to ask instead of answer |
| `GUARDRAILS.md` | rules that must hold, and data the agent must be able to see |
| `BOUNDARIES.md` | where scope stops, and where concepts bleed into each other |
| `GLOSSARY.md` | one line per term plus the words to avoid for it — a disambiguation index; the definitions themselves live in the concept files |
| `REFERENCES.md` | links out to authoritative external sources |
| `OPEN-QUESTIONS.md` | known unknowns, and what would settle each |
| `EVALS.md` | the eval suite — acceptance questions, plus cases from real wrong answers |

**Filing test:** a fact that stays true on a different task is product knowledge; a fact
that is true only because of what this task is doing is procedure. Undecided facts stay
in the focal concept file.

**Every file is standalone.** Write for someone who was not in the conversation. A file
that needs the session to make sense is context rather than reference.

**Close each concept file with a footer** carrying:

- **Derived from** — the paths, capture IDs, or `user, <date>, unverifiable from repo`
  that each claim rests on.
- **Verified** — whether those sources were *checked*, or only cited. Provenance records
  where a sentence came from; it does not record that anyone confirmed it, and a file
  restating someone's assertions reads as reconciled unless it says plainly that nothing
  was checked. Where the user asserts something the code cannot confirm, record it as
  pending a real capture rather than as established fact.
- **Acceptance question** — one question this file alone should answer. Write it now,
  while it is still obvious what the file is for.

Provenance is what makes drift checkable later. A reference file that has quietly gone
out of date is more dangerous than a missing one, because it gets cited with full
confidence.

## Phase 2 — Teach the job

Fill in the `INDEX.md` sections left undecided.

- **The index is always loaded; concept files load on demand.** Attention is finite, and
  a head full of everything answers the immediate question worse. Where the architecture
  makes one model call per turn with no tool loop, "on demand" means the *caller* selects
  before the call: build the seam that takes a concept list, and say plainly that nothing
  yet decides what goes in it.
- **Write the payload contract** — what reaches the model each turn, at what fidelity,
  under what caps — and decide it in code. The agent cannot ask for what it does not
  know is missing, so a thin payload surfaces as a confident wrong answer rather than as
  a question. That is the hardest failure to catch, because nothing about it looks
  suspicious.
- **Give routing an "ask" outcome.** A forced guess between two plausible tasks is the
  most expensive failure available: everything downstream then executes correctly on a
  wrong premise. Log the route taken, so a misroute is visible rather than inferred from
  a strange answer.

## Phase 3 — Apply the harness

- **Classify every rule in `GUARDRAILS.md`** by the principle at the top — code for what
  you cannot afford to have wrong, prose for the rest — and record which each became. The
  file's data requirements are not rules about output; for those, check instead whether
  the payload satisfies them, since a guard cannot inspect what the model was never shown.
  Where a rule is only partly checkable in code, say so and name the half that is missing
  rather than forcing it to one side.
- **A rule classified prose must reach the model.** Prose is enforced by being read, so
  confirm it is in the payload. A prose rule outside the payload is enforced by nothing,
  and that is worse than an unwritten one because it looks handled.
- **Guards edit surgically.** Remove the unsupported claim and keep the part of the
  answer that was correct and asked for. Whole-answer rejection is blunt, and users
  notice. A guard removes; it does not write — so a rule carrying a positive obligation
  (*say* what was searched, *say* it expired) is only half enforceable in code. The guard
  stops the wrong sentence; the right one still rests on the model. Record which half is
  missing rather than calling the rule enforced.
- **Seed `EVALS.md` from the acceptance questions.** Every *written* concept file arrived
  carrying one, so the suite starts with those rather than cold — concepts named but
  unwritten carry none, so add a case per guardrail directly. Only a run against the agent
  counts as a pass; where the agent cannot be run at all, or where reading an answer back
  out of the file that defines it would prove nothing, record the case **unrun** with the
  reason.
- **Freeze the inputs and replay.** One green run of a nondeterministic system is one
  sample; re-run before trusting it.

## Between sessions

Refresh `INDEX.md` at every stop: statuses, new provenance, which acceptance questions
now pass, and what the next session does first.

**Where things sit.** The corpus goes at the working directory root. Where the agent
already has a folder of its own — one holding its prompt or its existing knowledge, not
merely its code — the corpus goes *inside* that folder, so the agent and what it knows
travel together. Where you cannot yet tell, default to the root and record that a later
answer may require moving it: the placement question is rarely worth a turn of its own —
unless code reads the corpus by relative path, in which case placement decides whether it
loads at all.

**Where the code sits.** Phases 2 and 3 change code, so establish early whether that code
is in this repository or somewhere you cannot reach. Where it is out of reach, write the
payload contract and the guardrail classification as specifications, record where each
must be applied, and say plainly that they are unimplemented — a specification recorded
as done is the failure this skill exists to prevent.

A failure in phase 3 returns to phase 1 carrying the wrong answer as fresh evidence.
The phases are meant to be re-entered.
