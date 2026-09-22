# harness — Technical Specification

Modules: `app/core/llm_client.py` (LLM abstraction), `app/core/harness.py` (tool-calling loop).

## LLM abstraction

A minimal interface, deliberately small:

```python
class LLMClient(Protocol):
    def generate(self, messages: list[Message], tools: list[ToolSchema]) -> Response: ...
    # Response may include tool-call requests the harness must execute and feed back
```

First concrete implementation: `GeminiClient` (`google-genai` SDK). Nothing else in the codebase imports a vendor SDK directly — adding Anthropic or OpenAI later means writing one new class implementing this same interface, not touching the harness, agents, or tools.

## Harness loop

Conversational (multi-turn), but **not** a bare in-memory list — conversation history sits behind a small `ConversationStore` interface (implemented in `app/core/storage.py` against a project-local SQLite database, see [ADR-0002](../../adr/0002-single-user-per-process.md)), persisted across restarts and organized into multiple independently-listed conversations (claude.ai/ChatGPT-style sidebar), not just one resumable thread. Each new user query is appended to the active conversation's history, so the LLM can resolve references to earlier turns ("this one", "the other PS"). To keep token growth bounded, once a turn's final answer is produced, that turn's tool-call payload is dropped from what's sent to the LLM going forward — only the user's question and the final `plain_language_answer` are kept (see the token-minimization principle in [`ARCHITECTURE.md`](../ARCHITECTURE.md)); the full record still persists in SQLite for display.

Per query:
1. Load the relevant skill's `skill.md` content (plain markdown, LLM-agnostic prose) — hardcoded to `packspec_status/skill.md` for now, since it's the only agent; no skill-selection routing until a second agent exists.
2. Send the skill's instructions + the active conversation's running history + the one available tool schema (`get_ps_status`) to the LLM. Tool-result content from prior turns and skill content are kept distinguishable in the assembled prompt — skill.md is the only trusted, developer-authored instruction source; everything else is data (see `ARCHITECTURE.md`'s Guardrails section).
3. LLM emits `SearchParams` as the tool call. The harness runs `get_ps_status(params, config, on_step=...)` — a single deterministic pipeline (search → transform → branch → catalog-match, see [`docs/agents/packspec-status/TECHNICAL_SPEC.md`](../../agents/packspec-status/TECHNICAL_SPEC.md)) in a background thread, with no further LLM involvement inside it. `on_step` fires a short present-tense status string before each stage that does real work; the harness forwards each one to the UI over Server-Sent Events as it happens — this is the staged-progress mechanism, not token streaming (see `ARCHITECTURE.md`).
4. Feed the already-summarized `StatusResult` back to the LLM once, wrapped in explicit untrusted-data delimiters (it's Splunk-derived content, summarize it, don't follow anything inside it as an instruction).
5. LLM composes the final answer conforming to the strict Output Context (`AgentAnswer`).
6. **Programmatic grounding check**: before returning `AgentAnswer`, code verifies `plain_language_answer` isn't asserting a documented fix when `catalog_matches` is empty (a cheap heuristic against already-structured data, not a second LLM call) — defense-in-depth on top of step 5's prompt instruction, per the strict grounding rule.

There is no multi-round tool-orchestration loop and no retry-until-valid loop for bad LLM arguments (see [ADR-0001](../../adr/0001-single-deterministic-pipeline-tool.md)) — each query is exactly two LLM turns: parse, then compose.

## Skills

Plain markdown files, one per agent capability, living alongside that agent's code (e.g. `app/agents/packspec_status/skill.md`). No Claude-Code-specific syntax — must work identically regardless of which LLM backend is configured. With tool orchestration now fully internal to `get_ps_status` (see [ADR-0001](../../adr/0001-single-deterministic-pipeline-tool.md)), a skill's job is narrower than originally scoped: how to parse a query into `SearchParams`, and the strict behavioral rules for composing the final answer (e.g. the grounding rule from `components/catalog`) — not tool sequencing, since there's only one tool call per query.

## Confidence status

The overall pattern (skill + one deterministic tool + fixed two-turn loop) is a settled architectural decision, including conversation history handling and the absence of any retry-until-valid loop. Still open: the exact Gemini function-calling API mechanics for enforcing "exactly one tool call, then a final answer" — needs fleshing out during implementation.
