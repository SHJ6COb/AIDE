# PACKITOperationsAgent — Architecture

## Mission

A single UI interface that acts as an operations support agent for PACKIT (the SAP S/4-based system supporting Bosch's Packaging activities): it answers internal users' questions about the status of a Packaging Specification's data flow and suggests grounded next steps. The domain knowledge lives as topic files under
[`app/agents/packspec_status/knowledge/`](../app/agents/packspec_status/knowledge/);
[`CONTEXT.md`](../CONTEXT.md) is the index to them, and holds no definitions of its own.

This document covers the first buildable slice of that mission: the `packspec-status` agent, which answers "what's the status of this packaging spec / this error" questions. Full technical detail for each piece lives in its own component/agent spec (linked below) — this document is deliberately short: the cross-cutting decisions, and an index.

## The knowledge layer, and why selection is measured before it is switched on

Domain knowledge is one file per topic under `app/agents/packspec_status/knowledge/`, each
declaring in front matter when it is relevant (`loads_when`), with the vocabulary pinned in
`knowledge.KNOWN_PREDICATES` so a typo fails at import rather than silently matching
nothing. `CONTEXT.md` indexes them; `tests/test_knowledge.py` enforces that the index stays
complete and that no term is defined twice.

**Every topic is still loaded on every turn.** `loads_when` is a declaration of intent, and
`load_all()` returns everything — deliberately, so the split changed no answer when it was
made. The case for withholding a topic rests on a number nobody had: how often each
predicate actually fires on real traffic. `knowledge.firing_predicates()` and
`harness._observe_predicates()` now compute and log that per turn while selecting on
nothing, so the question can be settled by measurement rather than argument.

Two families sit inside that vocabulary, and the difference decides how far each can be
trusted. The `has_*` predicates read state the pipeline already computed for another reason
— superseded activations, hop counts, resolved target systems, dependent objects — which is
what keeps them honest; a predicate nothing else exercises can rot silently. The
question-side ones (`mentions_*`, `is_routing_question`) have no such backing and are
keyword hints only.

## The two-stage status model

A Packaging Specification's status has two independent stages an end user's question can be about:

1. **Workflow Status** — is the Determination Record approved yet, in the Source System (PD7)?
2. **Replication Status** — once approved, did the payload actually reach and validate in the Target System(s)? This is what the `packspec-status` agent (this slice) answers, backed by Splunk (which tracks the PDMI/Solace replication pipeline).

A confirmed third consideration sits underneath Replication Status, not yet handled by this slice: **which Target System(s) a Transfer even routes to at all** is governed by a separate Additional Routing plan (see `knowledge/routing.md`'s **Additional Routing** and [`components/routing-plan`](components/routing-plan/TECHNICAL_SPEC.md)), not by Splunk/the Transfer's own hop history. A PS being Active and successfully triggered doesn't guarantee arrival at any one specific expected destination — "why didn't this reach system X" can be a routing-plan question, unanswerable from Splunk data alone.

A PS also has **Dependent Objects** (`DocumentInfoRecord`, `PackITPackagingCockpitMasterData`) that replicate as their own separate Transfers — and the Target System won't process the master PS transfer until those are done. So a PS's true Replication Status isn't just its own Transfer's outcome.

## Architecture: an LLM-agnostic agent harness with skills + tools

The solution must be **LLM-independent** — only a Gemini API key is available today, not Anthropic — so nothing depends on Claude Code specifically or a hardcoded vendor SDK. Instead this is a small, custom, in-house agent harness that mirrors the pattern Claude-Code/Codex-style agents use:

- **Tools** — deterministic, "100% works" Python functions. Same inputs always produce the same outputs; no LLM judgment inside them. See [`components/splunk-client`](components/splunk-client/TECHNICAL_SPEC.md), [`components/transform`](components/transform/TECHNICAL_SPEC.md), [`components/catalog`](components/catalog/TECHNICAL_SPEC.md). Per [ADR-0001](adr/0001-single-deterministic-pipeline-tool.md), only one composite function (`get_ps_status`) is actually LLM-facing — the rest are internal, independently unit-testable building blocks the LLM never calls directly.
- **Skills** — plain markdown procedure documents (no Claude-Code dependency), one per agent (e.g. `app/agents/packspec_status/skill.md`), loaded into the LLM's prompt for that task: the strict grounding rule and how to parse a query into `SearchParams`.
- **LLM abstraction** — a minimal interface with a `GeminiClient` as the first concrete implementation; swapping providers later means writing one new class, not touching agent logic. See [`components/harness`](components/harness/TECHNICAL_SPEC.md).
- **Harness loop** — conversational (multi-turn, in-memory history), but each query is a fixed two-LLM-turn exchange, not an open-ended tool-calling loop: parse the query into `SearchParams`, run the deterministic pipeline once, then compose the final answer from its already-summarized result. See `components/harness` for the full loop and history-management details.

This corrects an earlier assumption made mid-design (that this would run as a literal Claude Code Skill) — it doesn't; it's a from-scratch harness that borrows the *pattern*, not the mechanism.

## Design principle: minimize LLM token consumption

Every ambiguous design choice defaults toward fewer round trips and smaller payloads, not toward LLM flexibility for its own sake: prefer sensible defaults over a clarification turn, prefer deterministic code summarizing/condensing data before it reaches the LLM over sending raw or verbose payloads, and prefer collapsing mechanical multi-step work into one tool call over letting the LLM orchestrate each step (see [ADR-0001](adr/0001-single-deterministic-pipeline-tool.md)). This governs the harness loop, skill.md content, and every tool's return shape.

## UI: a claude.ai/ChatGPT-style app, single-user-per-process

The UI is a chat-style web app (React + Vite + Tailwind), not a bare CLI — colleagues talk to the agent through a browser, with multi-conversation history (a sidebar, like claude.ai/ChatGPT) and live staged-progress status while `get_ps_status` runs, rather than a silent wait. Two decisions here are hard to reverse and worth their own ADRs: [ADR-0002](adr/0002-single-user-per-process.md) (each colleague runs their own local instance — no shared multi-tenant server for the MVP) and [ADR-0003](adr/0003-prebuilt-bundle-single-process-launch.md) (one CLI command, one process, a pre-built frontend bundle — not two dev servers).

**Staged progress, not token streaming**: the UI shows live status text ("Searching Splunk...", "Checking error catalog...") as `get_ps_status` runs, via an optional `on_step` callback threaded through the pipeline (see `docs/agents/packspec-status/TECHNICAL_SPEC.md`), run in a background thread and forwarded to the browser over Server-Sent Events. No token-by-token streaming of the final answer — the answer itself is a few sentences per the functional spec's own example, so the "watch it type" effect isn't worth the added Gemini-streaming/SSE-incremental-render complexity for this MVP.

**Persistence**: a project-local SQLite database stores both issue/bug reports (see below) and full multi-conversation history — each conversation independently listed, switchable, and resumable after an app restart, matching the claude.ai/ChatGPT sidebar model rather than a single resumable thread.

**Issue reporting**: a "Report Issue" button records the issue to SQLite and opens a `mailto:` draft addressed to the project owner (pre-filled with the query, error, and conversation snippet) — the colleague still clicks Send. No SMTP relay dependency for the MVP; this is the feedback loop for the testing phase.

**Confidence status (2026-08-05)**: the full stack (`ui/cli.py` → `ui/server.py` → `harness.run_query` → `get_ps_status` → real Splunk; SQLite persistence; the pre-built React bundle) is live-verified end-to-end via `python -m ui.cli` against the real FastAPI server — conversation create/list/delete, SSE step events, message persistence, and error surfacing (a real failure mid-query correctly produced a `{"type": "error"}` SSE event and left the DB in an honest partial state, not a crash or a hang) all confirmed against real HTTP requests. The one leg not confirmed live end-to-end through the full app in this pass: an actual successful Gemini response inside `run_query` — the personal API key's calls are currently blocked by a Bosch corporate proxy authentication failure (`401` from `rb-proxy-de.bosch.com:8080`, intermittent, not caused by this code) that appeared partway through the session. Both Gemini turns (function-call parsing and grounded-answer composition) were independently verified live and working correctly *before* the proxy started failing — see `app/core/llm_client.py`'s test coverage and this session's history — so this is an environmental blocker to re-check once proxy access is restored, not an unverified code path.

**Update (2026-08-06)**: the LLM leg is confirmed reachable again, on both backends, via `quick_check` making real calls through `build_llm_client` — the same construction path `run_query` uses. Model Farm (`gpt-4o-mini`) and a personal Gemini key both answered. Gemini's live model catalog also fetched successfully (23 chat-capable models), so the proxy is no longer blocking that vendor either. This confirms client construction, auth, and a real round trip on both providers; it is *not* a re-run of the full two-turn `run_query` path, which remains verified only from the pre-proxy-outage session.

## Guardrails against prompt injection and excessive agency

Per OWASP's Top 10 for LLM Applications (LLM01: Prompt Injection remains the #1 risk; LLM06: Excessive Agency), and Anthropic's own published guidance on defending Claude against indirect prompt injection (untrusted tool-result content, not just the user, can carry adversarial instructions):

- **Excessive Agency is structurally minimized already**: one LLM-callable tool (`get_ps_status`), a fixed two-turn loop (parse, then compose — no open-ended tool-orchestration), read-only, no side effects. This is close to the "least privilege" answer to LLM06 by construction, not by policy.
- **The strict grounding rule is enforced in code, not prompt wording**: `match_catalog` either returns real matched rows or an empty list — the LLM has no fix to invent because there's nothing to invent from unless the code found one first.
- **A programmatic post-generation check** (in `app/core/harness.py`) verifies, after the LLM composes `plain_language_answer`, that it isn't asserting a documented fix when `catalog_matches` is empty — defense-in-depth on top of the prompt instruction, per OWASP's "output filtering" guidance. Cheap (a heuristic check against already-structured data), not a second LLM call.
- **Untrusted-data wrapping**: `app/core/llm_client.py`'s prompt assembly wraps tool-result content (Splunk-derived `description` text, `TransferRecord` data) in explicit delimiters with an accompanying instruction that it's data to summarize, never instructions to follow. `skill.md` content is the only trusted, developer-authored instruction source.
- **Tier 2 free-text already has real input-injection defense**: `build_spl`'s character allowlist, length cap, and outright rejection (not escaping) of SPL-special characters (`components/splunk-client`) — scoped to SPL injection, but the same "validate/reject, don't trust the model to behave" pattern.
- **LLM vendor**: personal Gemini API key for MVP prototyping (real Bosch operational data is acceptable to send, per the project owner's explicit call); migrating to a Bosch-provisioned key routed through Azure or Vertex is a planned follow-up swap behind the existing `LLMClient` Protocol, not an architecture change.

## Strict grounding rule

The agent never states a Suggested Action unless a real match was found in the Docupedia error catalog (see [`components/catalog`](components/catalog/TECHNICAL_SPEC.md)). If there's no documented fix, it says so plainly and points to raising an mServiceHub ticket — mirroring the Docupedia doc's own stated policy for unknown errors. No speculative LLM-invented fixes are ever presented as fact.

## Onboarding: one command from a fresh clone to a running app

Colleagues get the project by pulling from git and running `packit-agent init` (see [`README.md`](../README.md)). The wizard collects the Splunk and Additional Routing tokens, then the LLM backend — either the Bosch Model Farm or a personal key from Gemini/OpenAI/Anthropic — and hands straight off to starting the app.

Three decisions in that flow are worth stating, because each rules out a plausible alternative:

- **Model names for personal keys are fetched live from the vendor, not hardcoded** ([`app/core/model_catalog.py`](../app/core/model_catalog.py)). This project already got burned by pinned names going stale — `gemini-2.5-*` began 404-ing on a working key while still appearing in the catalog. Model Farm is the exception and stays hardcoded: its gateway exposes no catalog endpoint, and its deployment names aren't derivable from the model names. The fetch is best-effort by design — a corporate proxy blocking a vendor's catalog is normal here, so failure falls back to typing a name, never to a dead end.
- **A quick check runs before anything is written to disk** ([`llm_client.quick_check`](../app/core/llm_client.py)). One minimal real call proves the key, model, and network path work together; failure loops back to the key/model prompts. It goes through the same `build_llm_client` the app itself uses, so the check can't pass against a client the runtime wouldn't build. Deliberately, this is the one place that surfaces the *underlying* error rather than `LLMUnavailableError`'s fixed safe message — the audience is the person configuring their own machine, and "invalid api key" versus "proxy refused" are completely different fixes.
- **The built frontend bundle is committed**, not git-ignored. Per [ADR-0003](adr/0003-prebuilt-bundle-single-process-launch.md) colleagues need only Python at runtime; ignoring the build output (as `.gitignore` originally did) would have silently forced every one of them to install Node just to start the app.

## Index

- [`README.md`](../README.md) — colleague-facing setup and troubleshooting. The entry point for anyone who just wants to run the thing.
- [`QUERY_FLOW.md`](QUERY_FLOW.md) — file-and-line walkthrough of exactly what happens between a user pressing Enter and an answer appearing, validated against the standard production-chat-app reference pattern (where this system follows it, and where it deliberately doesn't).
- [`RESEARCH_PLAYBOOK.md`](RESEARCH_PLAYBOOK.md) — the reusable chain-of-thought method behind every "Confirmed live" claim in this repo; read this before empirically investigating a new API or an unconfirmed field.
- [`agents/packspec-status/FUNCTIONAL_SPEC.md`](agents/packspec-status/FUNCTIONAL_SPEC.md) / [`TECHNICAL_SPEC.md`](agents/packspec-status/TECHNICAL_SPEC.md) — the first agent: answers PS status questions.
- [`components/splunk-client/`](components/splunk-client/TECHNICAL_SPEC.md) — SPL construction, oneshot REST search, auth.
- [`components/transform/`](components/transform/TECHNICAL_SPEC.md) — raw payload → structured `TransferRecord`, grouping, status derivation.
- [`components/catalog/`](components/catalog/TECHNICAL_SPEC.md) — Docupedia error catalog matching, strict-grounding fallback.
- [`components/routing-plan/`](components/routing-plan/TECHNICAL_SPEC.md) — Additional Routing plan API: which Target System(s) actually receive a Transfer, separate from Solace/TOPICSTRING subscription. Wired into the pipeline as `RoutingCheck`: when a search scoped to a specific `target_system` comes back empty but the PS exists elsewhere, `get_ps_status` resolves its real Plant/Determination Type and asks the routing plan whether that target was ever configured to receive it — turning a bare "not found" into a grounded "it was never routed there."
- [`components/harness/`](components/harness/TECHNICAL_SPEC.md) — the LLM-agnostic tool-calling loop and skills mechanism.

## Confidence status (honest, updated after an extended live Splunk investigation)

Phase 0's initial Postman testing confirmed the basic REST call mechanics. A subsequent, much deeper investigation — direct REST calls against real production data (15-minute, 4-hour, 3-hour, 24-hour, and 7-day pulls covering thousands of real events) cross-checked against the actual dashboard — resolved most of what Phase 0 left open, and corrected several assumptions that turned out wrong:

- **Resolved**: envelope shape is determined by hop stage (pre-consumption = plain JSON, Target-processed = Atom/OData), not by Message Type as originally assumed — this now explains why `DocumentInfoRecord` looked "different" from the PS type (we simply hadn't seen a DIR at its processed stage yet). See `components/transform`.
- **Resolved**: `DocumentInfoRecord`'s real PS-linkage field and its content-server-style host naming (not Target-System-based at all) — the previously-documented field path was a wrong guess. See `components/transform`.
- **Resolved**: the Technical Error catalog family (rows 30-32) is transcribed correctly and matches real data perfectly (91/91), once `match_catalog` uses `DOTALL`. See `components/catalog`.
- **Fixed**: the SNR13/Business-Error catalog family didn't match real message text (167/168 failures in one live sample) — a content problem in specific rows (1, 2, 3), not a matching-strategy problem. Patterns loosened and re-validated at 100% match rate across every dataset gathered. See `components/catalog`.
- **New confirmed constraint**: the Splunk API gateway hard-blocks unbounded or very large result requests (`MessageBlocked` fault) — 200 rows per call, paginated via `offset`, is the confirmed-safe approach. See `components/splunk-client`.
- **Still open**: how `DocumentInfoRecord` signals error vs. success at its processed stage (no status field observed on the only examples found, both presumably successful); RETRY-bucket (`Retrigger required`) payload shape for any Message Type, despite two dedicated search attempts; the "latest hop wins" grouping rule at the scale of real ~50-100-hop retry chains.
