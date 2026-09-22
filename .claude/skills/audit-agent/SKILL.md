---
name: audit-agent
description: Audit and repair an agent that already exists — extract knowledge buried in prompts, reconcile a corpus against code that has moved, and diagnose wrong answers to the layer that caused them.
disable-model-invocation: true
---

Building an agent's knowledge is one job; keeping it true is another. This skill is the
second. It assumes something already exists — a prompt, a corpus, a running agent — and
its output is a repair with evidence that the repair worked.

**A reference file that has quietly gone out of date is more dangerous than a missing
one**, because it gets cited with full confidence and nothing about it looks suspicious.
Finding those is the point.

Where nothing is written down yet — no prompt, no corpus, no agent — the work is a build
rather than an audit. A fused prompt with no corpus is still this skill's work: the
knowledge exists, it is only in the wrong shape.

## Start from a trigger

Audits are triggered, never exhaustive. "Check the whole corpus" produces a slog that
gets abandoned midway, leaving statuses that claim more than was verified — worse than
never starting. Take an entry point from below and finish it:

| Trigger | Scope |
|---|---|
| **A wrong answer** | diagnose that one failure to its layer |
| **A change in the code** | re-check only the files whose provenance touches the changed paths |
| **A named concept** | that file and the concepts it references |
| **A fused prompt** | extract it, whole or by named section |

State which trigger you are running before you begin.

## Diagnose a wrong answer to its layer

Work the layers in this order, cheapest to disprove first, and **name the layer before
proposing any change.** The cheapest story is always "the knowledge file is missing
something", so that is what gets written — and when the real cause sat elsewhere, the
file grows and the bug survives.

1. **Payload** — was the fact in front of the model at all? Read what was actually sent,
   rather than what the corpus contains. A fact held in memory but excluded from the
   payload produces a confident denial, which reads exactly like missing knowledge.
   A capture holding no instructions and no loaded corpus is either partial or evidence
   of a second fault. Where the artifacts cannot settle which, name the fault you have
   proven and record the other as unresolved rather than stalling on it.
2. **Corpus** — is it written down, and does the file carrying it stand alone?
3. **Routing** — was this treated as the right task? A misroute executes correctly on a
   wrong premise, so the answer looks competent and addresses something else.
4. **Guard** — should something have caught this before it reached the user, and why did
   it stay quiet?
5. **None of these** — the model saw everything it needed and still erred. This outcome
   must stay reachable: it points at the harness, and a rule that only ever lived in
   prose is the usual reason.

Repair at the layer you named. An unresolved *second fault* never blocks a proven one —
record it and carry on. A question of **which source governs** is a different thing, and
that one stops the repair whatever layer it appears at.

- **Layer 1** — change what the payload carries. A code fix by construction: the fact
  existed and assembly dropped it. Set the new fidelity and cap in code as well, since
  "send everything" trades this failure for a context-rot one. Where nothing in evidence
  implies a cap, set one, say it is your number rather than a derived one, and put the
  real value to the user. Where the assembly code is out of reach, write the change into
  `REPAIR-<subject>.md`, name the processing stage it belongs to as precisely as the
  evidence allows, raise the exact location as an open question, and mark the repair
  unmade.
- **Layer 2** — rewrite the file from the evidence, and refresh its provenance. Where the
  cited sources contradict each other, the direction of the repair is undetermined: mark
  the file unsafe to cite, record both readings, and put the question of which governs to
  the user. A rewrite in the wrong direction is the original failure again, wearing fresh
  provenance.
- **Layer 3** — correct the route, and give the ambiguous case an "ask" outcome.
- **Layers 4 and 5** — the fix is code. A rule that matters enough to be wrong about
  belongs where it executes, with the written version kept to explain why.

## Reconcile drift

Read each affected file's **Derived from** footer and go back to those sources. A
code-change trigger reaches this first, but drift surfaces under any trigger and these
outcomes apply wherever it does. Record the outcome, whichever it is:

- **Still true** — refresh the footer date and move on.
- **Stale** — rewrite the claim from what the source now says, and note what changed.
- **Unverifiable** — the source moved or vanished. Mark it pending a real capture rather
  than leaving it to read as established fact.
- **Ask the source** — the source is a person, reachable but not by you. Mark it
  unconfirmed and put the question to the user, rather than carrying it forward on the
  strength of its original capture. This blocks the *claim*, not the audit: finish
  everything else, and leave the file citable where the rest stands on its own.

Record the outcome **per source**, not per file — one file can be stale against its code
and unverifiable against a document. Two sources giving mutually exclusive readings is the
contradiction case above, and that stops the repair.

**Establish whether the code is truth before reconciling against it.** On shipped work the
corpus must match the code. On work that has not shipped, the code may be the aspiration
and the corpus the current reality — unimplemented functions and unreachable branches are
the tell. Ask which, rather than assuming the newer artifact wins.

A file with no provenance footer cannot be reconciled. Give it one from whatever you can
confirm now, and record the rest as unverified.

## Extract knowledge buried in a prompt

A large prompt usually holds product knowledge, procedure, and guardrails fused
together. Separating them is a **rewrite, not a move** — lifted fragments stay
imperative and task-coupled, which is prompt shaped, not reference shaped.

Each fragment faces two tests:

- **Filing test** — a fact that stays true on a different task is product knowledge and
  moves to `knowledge/<concept>.md`; a fact true only because of what this task is doing
  is procedure and stays.
- **Standalone test** — rewrite it for someone who was not in the conversation and has
  not read the prompt. What survives goes in the file.

A guardrail is usually both at once: the fact it rests on ("depot users see item and RMA
data only") files as product knowledge, while the rule it drives ("never disclose the
address to a depot user") stays. Write each in its own voice rather than choosing.

A fragment that passes neither goes to `OPEN-QUESTIONS.md`. Where an unsettled fragment
decides what a file claims, write the file with that claim marked pending rather than
picking a reading, and put the question near the top of what you ask. Finish the
extraction before asking: a fused prompt is one artifact, and stopping half-way through
leaves it half-separated, which is worse than either end state.

Give every extracted fact provenance pointing back at the prompt it came from, plus a
**verification status**: a prompt records what someone asserted, not what the system
does, so an extracted file is unverified until reconciled against code. Write an
acceptance question into each new file as you go.

What remains in the prompt is procedure and the rules themselves, and it should be
shorter. The split moves *facts* out, not rules — so a rule whose underlying fact now
lives in `knowledge/` is the guardrail case above, not duplication.

## Close every audit

- **Re-run the acceptance questions** of every concept the audit implicated, whether or
  not its file changed — a repair that has not been re-verified is an edit, and a layer-1
  fault leaves the file untouched while making its question worth running for the first
  time. **Only a run against the agent counts as a pass.** Reading an answer back out of a
  file you have just written proves nothing, and a file holding two disputed readings has
  no single answer to read at all; in either case record the question **unrun**, with the
  reason. Where drift invalidated the question itself, rewrite it and say that what passed
  before is not what runs now.
- **Where the audit found a wrongness, add it to `EVALS.md`** — the question; the answer,
  either the one that came back or, where nothing came back, the one the faulty corpus was
  primed to produce labelled *reconstructed*; the layer; and what a right answer contains.
  Where the repair is blocked and the right answer is precisely what is unknown, record
  what a right answer must **account for** under either reading, and mark the answer
  pending. An extraction finds no wrongness, so it writes no eval.
- **Sample more than once** wherever the agent can be run. Where it cannot, say so
  plainly rather than recording a verification that did not happen.
- **Update `INDEX.md`** with what this audit established: the layer named where there was
  one, the repair made or the reason it is blocked, and any refreshed provenance. An audit
  that ended in a diagnosis records the diagnosis — claiming a repair that did not happen
  is the failure this skill exists to catch.

Create `OPEN-QUESTIONS.md` and `EVALS.md` when an audit first has something to put in
them.

**An incidental fault found while diagnosing** — a stale provenance path, a missing
footer, a file with no acceptance question — gets one line in `OPEN-QUESTIONS.md` and no
more. Finish the trigger you started; the note is what makes the next audit cheap.

Each audit should leave the suite stronger than it found it. That is the only part of
this work that compounds.
continue