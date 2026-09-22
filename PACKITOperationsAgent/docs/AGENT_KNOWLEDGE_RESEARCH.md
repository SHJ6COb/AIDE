# Building and Organising Knowledge for AI Agents

**A literature review against a two-part hypothesis.**
Date of research: 2026-08-07. Every claim below is tagged with the URL it came from. Findings are graded **CONSENSUS**, **SINGLE SOURCE**, or **CONTESTED**.

---

## 0. The hypothesis and the verdict

### The hypothesis under test

> Knowledge for an agent divides in two.
> (a) **Product/domain knowledge** — global reference, always authoritative, true regardless of what task is being done.
> (b) **Task knowledge** — the procedure for one specific task.
> Keep them in separate places.

### Verdict: **directionally right, materially incomplete.**

**The split is real and has a 30-year intellectual ancestor.** Anderson's ACT theory represents *declarative knowledge* in units called "chunks" and *procedural knowledge* in units called "production rules", and states that "Production rules embody procedural knowledge, and their conditions and actions are defined in terms of declarative structures" (Anderson, J. R. (1996), *ACT: A Simple Theory of Complex Cognition*, American Psychologist 51(4), 355–365 — https://acs.ist.psu.edu/misc/dirk-files/Papers/ACT-R_GeneralReviews/AC%20A%20simple%20theory%20of%20complex%20cognition.htm). The hypothesis is, essentially, the declarative/procedural distinction applied to agent context. **Grade: CONSENSUS** that the distinction exists as a knowledge-representation primitive (cognitive science + the Diátaxis documentation framework, below, arrive at it independently).

**But the best-established framework in this space splits four ways, not two.** Diátaxis identifies "four distinct needs, and four corresponding forms of documentation" — tutorials, how-to guides, reference, explanation — arranged on two axes, action-vs-cognition and acquisition-vs-application (https://diataxis.fr/ and https://diataxis.fr/compass/). The hypothesis's (a) maps onto **reference**; (b) maps onto **how-to guides**. It has **no slot for explanation** (the *why*, needed when a procedure must be adapted rather than followed) and **no slot for tutorials** (onboarding a fresh agent/operator into an unfamiliar domain). Diátaxis is explicit that reference must "Describe and only describe" and be "wholly authoritative" with "no doubt or ambiguity" (https://diataxis.fr/reference/), and that how-to guides must contain "action and only action" with "no digression, explanation, teaching" (https://diataxis.fr/how-to-guides/). So the *separation* instinct is strongly corroborated; the *arity* is not. **Grade: SINGLE SOURCE** for the four-way arity specifically (Diátaxis is one framework, albeit a widely adopted one); **CONSENSUS** for the underlying "keep procedure and reference apart, and link rather than duplicate".

### What published practice adds that the two-way split misses

Six layers appear across independent vendors and papers. None of them is (a) or (b):

| Missing layer | Why it is not optional | Strongest evidence |
|---|---|---|
| **1. A routing/selection layer** — metadata whose only job is to make the *right* knowledge get picked | Selection is the dominant failure mode once you have more than a handful of tasks. Tool-selection accuracy collapses as the candidate set grows; RAG-MCP reports 13.62% → 43.13% by retrieving over tool descriptions first | https://arxiv.org/abs/2505.03275 ; https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices |
| **2. A progressive-disclosure / loading policy** — *when* each piece enters context, not just where it lives | More context is actively harmful, not merely wasteful. GPT-3.5-Turbo scored 53.8% with the answer mid-context vs 56.1% closed-book — i.e. *worse than having no documents at all* | https://ar5iv.labs.arxiv.org/html/2307.03172 ; https://www.trychroma.com/research/context-rot |
| **3. A verification/guardrail layer** — checks that run as code, outside the model | Prompt-stated rules are followed unreliably: best model on AgentIF hits 59.8 CSR / 27.2 ISR against real agentic system prompts averaging 11.9 constraints | https://arxiv.org/html/2505.16944v1 ; https://openai.github.io/openai-agents-python/guardrails/ |
| **4. A grounding/attribution contract** — answers must be traceable to a source, and that must be *measured* | AIS, RAGAS faithfulness, TruLens groundedness, Azure groundedness detection and Vertex grounding metadata all independently formalise the same requirement | https://aclanthology.org/2023.cl-4.2/ ; https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/ ; https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/groundedness |
| **5. Memory/state** — durable knowledge the agent *writes*, not just reads | Anthropic reports memory + context editing improving complex agentic search by 39% and cutting token use 84% on a 100-turn eval | https://claude.com/blog/context-management ; https://arxiv.org/abs/2310.08560 |
| **6. An abstention policy** — an explicit "answer nothing" branch | Hallucination is argued to be an *incentive* artefact: models are "optimized to be good test-takers, and guessing when uncertain improves test performance" | https://arxiv.org/abs/2509.04664 ; https://arxiv.org/abs/2311.09677 |

### Where the literature actively contradicts the hypothesis

1. **"Always authoritative, true regardless of task" is not achievable as a single blob.** Anthropic's Skills guidance recommends splitting reference *by domain* precisely so that irrelevant reference never loads: `reference/finance.md`, `reference/sales.md`, `reference/product.md`, so that "sales.md and product.md files remain on the filesystem, consuming zero context tokens until needed" (https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices). Global-and-always-loaded is the anti-pattern. **CONSENSUS** (Anthropic + LangChain + the context-rot evidence).
2. **"Two places" understates the granularity needed.** LangChain's taxonomy is four *operations* — write, select, compress, isolate — over three *types* of context — instructions, knowledge, tools (https://www.langchain.com/blog/context-engineering-for-agents). Tools are a third kind of knowledge that neither (a) nor (b) covers cleanly.
3. **Separation alone does not prevent drift; a linking rule does.** Diátaxis's operative instruction for how-to guides is to "link to" reference rather than duplicate it (https://diataxis.fr/how-to-guides/). The hypothesis says *separate*; the literature says *separate and cross-reference, never copy*.

---

## 1. ACCURATE ROUTING — selecting the right task, procedure, tool or skill

### 1.1 The routing pattern itself

Anthropic defines **routing** as a workflow that "classifies an input and directs it to a specialized followup task", and says it "works well for complex tasks where there are distinct categories that are better handled separately", with classification done "through LLMs or algorithmic methods". Stated benefit: separation of concerns and per-category prompt optimisation (https://www.anthropic.com/engineering/building-effective-agents).

Anthropic's multi-agent system applies the same idea to delegation: an orchestrator must give each subagent "an objective, an output format, guidance on the tools and sources to use, and clear task boundaries". Vague delegation ("research the semiconductor shortage") produced duplicated work across subagents (https://www.anthropic.com/engineering/multi-agent-research-system).

**Grade: CONSENSUS** that routing-by-classification is a first-class architectural pattern (Anthropic pattern catalogue + LangChain's "isolate" bucket + OpenAI Agents SDK handoffs all instantiate it).

### 1.2 Intent classification vs LLM-as-router vs embedding/semantic routing

- **Embedding/semantic routing** pre-encodes example utterances per intent and routes by nearest neighbour, avoiding an LLM call entirely.
- **LLM-as-router** classifies at runtime with a model call.
- Published measurement: *When to Reason: Semantic Router for vLLM* (Wang et al., 2025-10-09) reports +10.2 percentage points on MMLU-Pro, −47.1% latency and −48.5% token consumption versus direct inference, by classifying "queries based on their reasoning requirements and selectively appl[ying] reasoning only when beneficial" (https://arxiv.org/abs/2510.08731).

**Grade: SINGLE SOURCE** on the head-to-head "which router type is better". I found one strong quantified result for semantic routing on a *reasoning-effort* decision; I did **not** find a controlled, peer-reviewed comparison of embedding-routing vs LLM-routing vs fine-tuned intent classifier on *task/skill* selection. Treat vendor blog claims that one dominates as unproven.

### 1.3 How descriptions must be written for selection to work

Anthropic's Agent Skills docs are the most operational primary source (https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices):

- Only `name` + `description` are preloaded at startup; SKILL.md is read only when the skill becomes relevant. So **the description is the entire routing signal**.
- "The description is critical for skill selection: Claude uses it to choose the right Skill from potentially 100+ available Skills."
- Must include **both what it does and when to use it**. Good: `Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.` Bad: `Helps with documents`.
- **Always third person.** "The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems."
- Hard limits: `name` ≤ 64 chars, lowercase/numbers/hyphens; `description` ≤ 1,024 chars.
- Naming should be consistent, preferably gerund form (`processing-pdfs`), avoiding `helper`, `utils`, `tools`.

For *tools* specifically, Anthropic advises writing descriptions "as if onboarding a new team member", using unambiguous parameter names (`user_id` not `user`), and namespacing by service and resource (`asana_search`, `asana_projects_search`). They report that "even small refinements to tool descriptions can yield dramatic improvements" and that prefix- vs suffix-based namespacing had "non-trivial effects" on eval performance (https://www.anthropic.com/engineering/writing-tools-for-agents).

**Grade: CONSENSUS** that description quality is the primary lever (Anthropic ×2 independently, plus the empirical papers below, plus OpenAI's structured-tool guidance).

### 1.4 Empirical evidence that selection degrades

- **Overlap is the killer, and Anthropic states the test explicitly**: "If a human engineer can't definitively say which tool should be used in a given situation, an AI agent can't be expected to do better." Named failure mode: "Bloated tool sets that cover too much functionality or lead to ambiguous decision points about which tool to use" (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). Also: "Too many tools or overlapping tools can also distract agents from pursuing efficient strategies" (https://www.anthropic.com/engineering/writing-tools-for-agents).
- **Retrieving over tool descriptions triples accuracy.** RAG-MCP (Gan & Sun, 2025-05-06) reports tool selection accuracy rising from a 13.62% baseline to 43.13% while cutting prompt tokens by more than 50% (https://arxiv.org/abs/2505.03275).
- **Adaptive shortlists beat fixed ones.** *How Many Tools Should an LLM Agent See? A Chance-Corrected Answer* (Repantis et al., 2026-05-23) reports 90.3% vs 90.8% coverage on BFCL (370 tools) while showing 7 tools on average instead of 50; and with Claude Sonnet 4.6, selection accuracy 93.1% vs 87.1% against always-showing-5, widening to 76.8% vs 60.9% on medium-difficulty queries (https://arxiv.org/abs/2605.24660).
- **Tool preferences are manipulable by description text alone.** *Tool Preferences in Agentic LLMs are Unreliable* (Faghih et al., 2025) finds LLMs "rely entirely on the text descriptions of tools to decide which ones to use — a process that is surprisingly fragile", with edited descriptions receiving "over 10 times more usage from GPT-4.1 and Qwen2.5-7B than tools with original descriptions", across 17 models (https://arxiv.org/abs/2505.18135).
- **Context confusion**: Breunig's taxonomy cites the Berkeley Function-Calling Leaderboard showing "every model performs worse when provided with more than one tool", and a GeoEngine case where quantized Llama 3.1 8b failed with 46 tools available but succeeded with 19 — despite the 16k window being sufficient, i.e. **not a length problem** (https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html).

**Grade on "more tools ⇒ worse selection": CONSENSUS** — Anthropic (vendor), RAG-MCP (paper), chance-corrected tool-count paper (paper), BFCL-derived observation all agree.
**Grade on the specific numbers: SINGLE SOURCE each.** They come from different benchmarks with different tool universes and are not directly comparable. Do not average them.

### 1.5 Misrouting failure modes catalogued

MAST (Cemri et al., 2025, 1600+ annotated traces across 7 MAS frameworks, κ = 0.88 inter-annotator agreement) gives a measured distribution (https://arxiv.org/abs/2503.13657 ; https://arxiv.org/html/2503.13657v3):

- **System Design Issues — 44.3%**: disobey task specification 11.8%, disobey role specification 1.5%, step repetition 15.7%, loss of conversation history 2.8%, unaware of termination conditions 12.4%
- **Inter-Agent Misalignment — 32.15%**: conversation reset 2.2%, fail to ask for clarification 6.8%, **task derailment 7.4%**, information withholding 0.85%, ignored other agent's input 1.9%, reasoning-action mismatch 13.2%
- **Task Verification — 23.5%**: premature termination 6.2%, no/incomplete verification 8.2%, incorrect verification 9.1%

Headline: "failures stem from system design issues, not just LLM limitations or simple prompt following". **Grade: SINGLE SOURCE** but unusually strong (largest annotated corpus I found, high agreement).

---

## 2. BOUNDARY LEAKS — stopping knowledge bleeding between tasks/domains and drifting out of sync

### 2.1 Diátaxis: the separation rules, stated as rules

Diátaxis (https://diataxis.fr/) solves "problems related to documentation *content* (what to write), *style* (how to write it) and *architecture* (how to organise it)" by keeping four forms structurally distinct. The compass (https://diataxis.fr/compass/) asks two questions — does it inform **action or cognition**, does it serve **acquisition or application** — producing:

| | Acquisition | Application |
|---|---|---|
| **Action** | Tutorials | How-to guides |
| **Cognition** | Explanation | Reference |

Operative rules that transfer directly to agent knowledge:

- **Reference** (https://diataxis.fr/reference/): "Describe and only describe." Must be "austere", with "neutrality, objectivity, factuality". Must be "wholly authoritative" with "no doubt or ambiguity". Its structure should "mirror the structure of the product", "similar to how a map corresponds to the territory it represents". It should **link to** how-to guides, explanation and tutorials rather than absorb them.
- **How-to guides** (https://diataxis.fr/how-to-guides/): "action and only action"; "no digression, explanation, teaching"; **link to** reference material rather than duplicating it. And crucially: "How-to guides are wholly distinct from tutorials. They are often confused, but the user needs that they serve are quite different."

**This is the single-source-of-truth mechanism**: duplication is prevented not by discipline but by a structural rule that one form may only *reference* another. **Grade: SINGLE SOURCE** (Diátaxis is one framework) but **CONSENSUS-adjacent** — Anthropic's Skills guidance independently reaches the same architecture, telling authors to keep SKILL.md as "an overview that points Claude to detailed materials as needed, like a table of contents in an onboarding guide", with reference material in separate files linked one level deep (https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).

### 2.2 Why duplicated instructions drift — and what drift costs

The strongest primary evidence is OpenAI's GPT-5 prompting guide (https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide):

> "poorly-constructed prompts containing contradictory or vague instructions can be more damaging to GPT-5 than to other models, as it expends reasoning tokens searching for a way to reconcile the contradictions rather than picking one instruction at random."

Their worked example (CareFlow Assistant) contains two contradiction pairs — "Never schedule an appointment without explicit patient consent" against "auto-assign the earliest same-day slot without contacting the patient"; and "Always look up the patient profile before taking any other actions" against "escalate as EMERGENCY and direct the patient to call 911 immediately before any scheduling step". Their fix is to resolve the *hierarchy* explicitly, not to add more emphasis.

This is the mechanism by which duplication becomes a live defect: two copies of a fact, updated at different times, become two conflicting instructions, and the model burns reasoning trying to satisfy both.

**Grade: CONSENSUS** that contradictory instructions degrade behaviour — OpenAI (vendor), Breunig's "context clash" mode, and Anthropic's "right altitude" guidance against "hardcoding complex, brittle logic in their prompts" (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) converge.
**Grade: SINGLE SOURCE** on the specific claim that reasoning models are *more* harmed than non-reasoning models (OpenAI only).

### 2.3 Context contamination — the four named failure modes

Breunig's taxonomy (https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html), which LangChain adopts (https://www.langchain.com/blog/context-engineering-for-agents):

1. **Context poisoning** — "When a hallucination or other error makes it into the context, where it is repeatedly referenced." Cited evidence: the Gemini 2.5 technical report on Pokémon gameplay, where "many parts of the context (goals, summary) are 'poisoned' with misinformation", causing pursuit of impossible objectives.
2. **Context distraction** — "When a context grows so long that the model over-focuses on the context, neglecting what it learned during training." Cited: beyond ~100k tokens the Gemini agent "showed a tendency toward favoring repeating actions"; a Databricks study showed Llama 3.1 405b correctness declining around 32k tokens.
3. **Context confusion** — "When superfluous content in the context is used by the model to generate a low-quality response." (BFCL / GeoEngine evidence above.)
4. **Context clash** — "When you accrue new information and tools in your context that conflicts with other information in the context."

For (4) the underlying study is real and quantified: *LLMs Get Lost In Multi-Turn Conversation* (Laban, Hayashi, Zhou, Neville, 2025-05-09) finds "all the top open- and closed-weight LLMs we test exhibit significantly lower performance in multi-turn conversations than single-turn, with an average drop of 39% across six generation tasks", decomposing into "a minor loss in aptitude and a significant increase in unreliability"; models "make assumptions in early turns and prematurely attempt to generate final solutions, on which they overly rely" (https://arxiv.org/abs/2505.06120). Breunig reports OpenAI o3 dropping from 98.1 to 64.1 on the sharded setting.

**Grade: the 39% figure — SINGLE SOURCE (but a well-specified simulation study).** **The taxonomy itself — SINGLE SOURCE** (one practitioner's naming) **that has been widely adopted**; do not cite it as peer-reviewed.

### 2.4 Cross-agent/cross-skill interference

MAST §1.5 above quantifies it: 32.15% of observed multi-agent failures are inter-agent misalignment, including task derailment (7.4%) and information withholding (0.85%) (https://arxiv.org/abs/2503.13657).

Anthropic's stated countermeasure is **context isolation**: sub-agents "handle focused tasks with clean context windows", each returning "only a condensed, distilled summary of its work (often 1,000-2,000 tokens)", achieving "clear separation of concerns" (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). Cost: multi-agent systems consume roughly **15×** the tokens of chat, versus ~4× for single agents; benefit on their internal eval: Opus 4 lead + Sonnet 4 subagents "outperformed single-agent Claude Opus 4 by 90.2%" (https://www.anthropic.com/engineering/multi-agent-research-system).

**Grade: CONTESTED.** Anthropic reports a large win from isolation; MAST reports that multi-agent systems fail for structural reasons ~32% of the time in exactly the coordination seam that isolation creates. Both can be true — isolation helps *when* delegation contracts are explicit — but a team should not read "isolate into subagents" as unconditionally beneficial.

---

## 3. PULLING THE RIGHT SUBSET — getting only what this task needs into context

### 3.1 Context engineering as the framing

Anthropic defines context engineering as "curating and maintaining the optimal set of tokens (information) during LLM inference", distinct from prompt engineering because "context engineering is iterative and the curation phase happens each time we decide what to pass to the model" (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

Their mechanistic claim: "as the number of tokens in the context window increases, the model's ability to accurately recall information from that context decreases" — context rot — rooted in transformers' n² pairwise attention and in training distributions where "shorter sequences are typically more common than longer ones".

### 3.2 Harm from too much context — the hard evidence

**Lost in the Middle** (Liu et al., TACL; https://ar5iv.labs.arxiv.org/html/2307.03172). Multi-document QA, GPT-3.5-Turbo, 20 documents:

| Position of the relevant document | Accuracy |
|---|---|
| Position 1 (start) | **75.8%** |
| Position 10 (middle) | **53.8%** |
| Position 20 (end) | **63.2%** |

Baselines: **closed-book 56.1%** (no documents at all), **oracle 88.3%** (only the answer document). The decisive fact for agent design: **at position 10 the model scores 53.8%, below the 56.1% it gets with no retrieved documents at all.** Adding correct-but-badly-placed context made it worse than adding nothing. The paper's own summary: "performance is often highest when relevant information occurs at the beginning or end of the input context, and significantly degrades when models must access relevant information in the middle of long contexts, even for explicitly long-context models."

**Context Rot** (Chroma technical report, 18 models: Claude Opus 4 / Sonnet 4 / Sonnet 3.7 / 3.5 / Haiku 3.5, o3, GPT-4.1 + mini/nano, GPT-4o, GPT-4 Turbo, GPT-3.5 Turbo, Gemini 2.5 Pro/Flash, Gemini 2.0 Flash, Qwen3-235B/32B/8B — https://www.trychroma.com/research/context-rot):

- Performance degrades with input length **even on deliberately trivial tasks** (replicating a word sequence, 25 → 10,000 words). GPT-4.1 showed a 2.55% refusal rate; Qwen3-8B produced nonsensical output beyond 5,000 words.
- Lower semantic similarity between needle and question "increases the rate of performance degradation" as input lengthens.
- **A single distractor** measurably reduced performance versus a needle-only baseline, and distractors were non-uniform — some hurt far more than others.
- LongMemEval: focused prompts (~300 tokens) "vastly outperformed" full prompts (~113k tokens).
- Counter-intuitive: models "perform worse when the haystack preserves a logical flow of ideas"; shuffled haystacks improved performance across all 18 models.

**Grade: CONSENSUS, and this is the best-evidenced claim in the whole review.** Independent academic (Liu et al.), independent lab (Chroma, 18 models across 4 vendors), and vendor (Anthropic) all agree that more context is not monotonically better and can be net-negative.

### 3.3 Progressive disclosure — the concrete design

Anthropic's Agent Skills implement a tiered load (https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills ; https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices):

- **Level 1** — `name` + `description` of *every* installed skill preloaded into the system prompt.
- **Level 2** — the SKILL.md body, read only when the skill is judged relevant.
- **Level 3+** — bundled files "which Claude can choose to navigate and discover only as needed".
- **Scripts** are *executed*, not read: "Only the script's output consumes tokens."

Consequences stated in the docs:
- "The context window is a public good."
- Keep SKILL.md body **under 500 lines**; split beyond that.
- **Keep references one level deep from SKILL.md** — deeper nesting causes Claude to preview with `head -100` and get incomplete information.
- Reference files over 100 lines should carry a table of contents at the top, so partial reads still reveal scope.
- Organise reference **by domain** so irrelevant domains never load (the `reference/finance.md` / `sales.md` / `product.md` pattern).
- "Bundle comprehensive resources: include complete API docs, extensive examples, large datasets; no context penalty until accessed."
- Because the agent has a filesystem, "the amount of context that can be bundled into a skill is effectively unbounded".

**Grade: SINGLE SOURCE** (Anthropic) for the specific mechanism and the 500-line/one-level numbers. **CONSENSUS** for the underlying principle — LangChain's "select" bucket describes the same move generically (https://www.langchain.com/blog/context-engineering-for-agents).

### 3.4 Just-in-time vs preloading

Anthropic: rather than pre-loading, use "lightweight identifiers (file paths, stored queries, web links, etc.) and use these references to dynamically load data into context at runtime using tools", explicitly analogised to human use of "file systems, inboxes, and bookmarks". They state the cost honestly: **"Runtime exploration is slower than retrieving pre-computed data."** (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

Counterweight from the same vendor: for knowledge bases **under ~200,000 tokens (~500 pages)**, Anthropic recommends skipping RAG entirely and putting the whole corpus in the prompt, with prompt caching cutting cost up to 90% (https://www.anthropic.com/news/contextual-retrieval).

**Grade: CONTESTED — and usefully so.** The same vendor gives opposite advice at different corpus sizes. The reconciling rule is a size/latency threshold, not a principle.

### 3.5 Retrieval design and chunking

Anthropic's **Contextual Retrieval** (https://www.anthropic.com/news/contextual-retrieval) prepends a 50–100 token, Claude-generated, chunk-specific context string to each chunk before embedding and BM25 indexing. Measured on top-20 retrieval failure rate:

| Configuration | Failure rate | Reduction |
|---|---|---|
| Baseline embeddings | 5.7% | — |
| + Contextual Embeddings | 3.7% | 35% |
| + Contextual Embeddings + Contextual BM25 | 2.9% | 49% |
| + Reranking | 1.9% | **67%** |

Also: "chunk size, chunk boundary, and chunk overlap can affect retrieval performance"; retrieving 20 chunks outperformed 5 or 10; one-time preprocessing cost ≈ $1.02 per million document tokens.

OpenAI's accuracy guide splits the failure surface the same way — retrieval failure (wrong/excessive context) vs LLM failure (mishandles correct context) — and warns that RAG can *hurt*: in their Icelandic case study adding RAG to a fine-tuned model dropped BLEU from 87 to 83, because "additional context will not necessarily help the model" once the task is learned (https://developers.openai.com/api/docs/guides/optimizing-llm-accuracy).

The foundational result: Lewis et al. (NeurIPS 2020) report that "RAG models generate more specific, diverse and factual language than a state-of-the-art parametric-only seq2seq baseline" (https://arxiv.org/abs/2005.11401).

**Grade: CONSENSUS** that retrieval quality dominates generation quality in RAG systems (Anthropic + OpenAI + Barnett et al. + TruLens all say so). **SINGLE SOURCE** for the 35/49/67% figures.

### 3.6 Compaction, note-taking, memory

- **Compaction**: summarise history near the limit and reinitialise. Anthropic's caveat: "overly aggressive compaction can result in the loss of subtle but critical context" (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
- **Structured note-taking**: notes persisted outside the window and pulled back later; the Pokémon agent tracks e.g. "for the last 1,234 steps I've been training my Pokémon in Route 1, Pikachu has gained 8 levels toward the target of 10."
- **Memory tool + context editing** (https://claude.com/blog/context-management): context editing "removes stale content while preserving the conversation flow"; the memory tool gives file-based storage outside the window. Reported internal evals: **memory + context editing = +39%** on complex multi-step agentic search; **context editing alone = +29%**; on a 100-turn web search eval, context editing "reduc[ed] token consumption by 84%" while completing workflows that would otherwise fail.
- **MemGPT / Letta** (Packer et al., 2023; https://arxiv.org/abs/2310.08560) is the academic ancestor: an OS-inspired hierarchy managing "different memory tiers in order to effectively provide extended context within the LLM's limited context window", with self-directed paging between main and external context. Demonstrated on document analysis beyond the window and multi-session chat.
- **LangChain's four operations** — write (scratchpads, memories), select (retrieval, incl. "RAG over tool descriptions… improve tool selection accuracy by 3-fold"), compress (summarisation, Claude Code auto-compact at 95% of the window; trimming), isolate (multi-agent, sandboxes, state schemas) (https://www.langchain.com/blog/context-engineering-for-agents).

**Grade: CONSENSUS** that an explicit external-memory tier is required for long-horizon agents (Anthropic vendor + MemGPT paper + LangChain framework). **SINGLE SOURCE** and vendor-internal for the 39%/29%/84% numbers — these are not independently reproduced.

---

## 4. AVOIDING PLAUSIBLE RESPONSES — stopping confident, well-formed, ungrounded answers

### 4.1 Why ungrounded answers happen at all

*Why Language Models Hallucinate* (Kalai, Nachum, Vempala, Zhang, 2025-09-04; https://arxiv.org/abs/2509.04664) argues that "the training and evaluation procedures reward guessing over acknowledging uncertainty", that hallucinations are fundamentally binary-classification errors arising from statistical pressure in pretraining, and that "language models are optimized to be good test-takers, and guessing when uncertain improves test performance". Their proposed fix is socio-technical: change how *existing dominant benchmarks score*, ending the "epidemic of penalizing uncertain responses".

**Grade: SINGLE SOURCE** (one paper, from one vendor's researchers) but load-bearing: it reframes hallucination as an *incentive design* problem, which implies your own evals must reward abstention or you will train the behaviour back in.

### 4.2 The attribution standard

Rashkin et al., *Measuring Attribution in Natural Language Generation Models*, Computational Linguistics 49(4), 2023 (https://aclanthology.org/2023.cl-4.2/ ; https://arxiv.org/abs/2112.12870) defines **AIS — Attributable to Identified Sources**: NLG output pertaining to the external world must be verifiable against an independent, provided source. They give a two-stage annotation pipeline, validate it across conversational QA, summarisation and table-to-text, and release guidelines and data (https://github.com/google-research-datasets/AIS).

This is the definitional anchor everything else operationalises.

### 4.3 Measuring groundedness in practice

- **RAGAS faithfulness** (https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/): decompose the response into claims, check each against retrieved context, score = supported claims / total claims, range 0–1. RAGAS also defines answer relevancy, context precision, context recall.
- **TruLens RAG Triad** (https://www.trulens.org/getting_started/core_concepts/rag_triad/): *context relevance* (did retrieval fetch the right chunks), *groundedness* (is the answer supported by them — again by decomposing into claims and verifying each), *answer relevance* (does it address the question). The claim: "By reaching satisfactory evaluations for this triad, we can make a nuanced statement about our application's correctness; our application is verified to be hallucination free up to the limit of its knowledge base."
- **FActScore** (Min et al., 2023; https://arxiv.org/abs/2305.14251): decompose generation into **atomic facts**, score the percentage supported by a reliable source. Their automated estimator has "less than a 2% error rate" vs human annotation. Headline result: **ChatGPT "only achieves 58%"** factual precision on their biography task.

**Grade: CONSENSUS.** Three independent implementations (RAGAS, TruLens, FActScore) plus the AIS definition all converge on exactly the same algorithm: **decompose the answer into atomic claims, verify each claim against the source, report the supported fraction.** If you build one verification mechanism, build this one.

### 4.4 Vendor products that enforce grounding

- **Google Vertex AI grounding** (https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/overview): anchors responses to external sources — Google Search grounding, or grounding on your own data (RAG, Agent Search, custom search APIs, Elasticsearch, Exa, Parallel). Returns structured **grounding metadata: citations** (references to sources used) and **support scores** (how well sources support each claim).
- **Azure AI Content Safety — groundedness detection** (https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/groundedness): "Ungroundedness refers to instances where LLMs produce information that is non-factual or inaccurate from what was present in the source materials." Two modes — **Non-Reasoning** (fast binary grounded/ungrounded, for online use) and **Reasoning** (explains which segments are ungrounded, for debugging). Domains: Medical / Generic. Tasks: Summarization / QnA. Optional **groundedness correction (preview)** returns a `correctedText` field: e.g. text "The interest rate is 5%" against source "As of July 2024, the interest rate is 4.5%" returns the corrected "The interest rate is 4.5%". Limitations: **English only**, region-limited, rate-limited.
- **OpenAI** frames it as context vs behaviour optimisation, recommends assigning business cost to failure modes (their worked example yields an **81.5% break-even accuracy** threshold), and building graceful failure — clarification prompts, second attempts, human escalation by confidence (https://developers.openai.com/api/docs/guides/optimizing-llm-accuracy).

**Grade: CONSENSUS** across Google, Microsoft and OpenAI that grounding must be (i) source-anchored, (ii) checked *after* generation as a separate step, and (iii) surfaced as citations/scores rather than assumed.

### 4.5 Abstention and calibrated refusal

- **Do Large Language Models Know What They Don't Know?** (Yin et al., ACL Findings 2023; https://arxiv.org/abs/2305.18153): the **SelfAware** benchmark of unanswerable questions across five categories with answerable counterparts, evaluated on 20 LLMs. Finding: LLMs have "an intrinsic capacity for self-knowledge", improvable via in-context learning and instruction tuning, but there remains "a considerable gap between the capabilities of these models and human proficiency in recognizing the limits of their knowledge".
- **R-Tuning** (Zhang et al., 2023/2024; https://arxiv.org/abs/2311.09677): refusal-aware instruction tuning. Standard instruction tuning "forces models to complete sentences" even without the knowledge; R-Tuning identifies the gap between parametric knowledge and tuning data, builds refusal-aware training data, and teaches the model to "refrain from responding to questions beyond its parametric knowledge". Reported: refusal generalises out-of-domain as a transferable skill, and calibration improves.
- **Know Your Limits: A Survey of Abstention in LLMs** (Wen et al., TACL 2024; https://arxiv.org/abs/2407.18418): organises abstention along three perspectives — **the query**, **the model**, **human values**. Open question flagged: whether abstention is a **meta-capability applicable across tasks and domains** rather than task-specific.
- Empirical support that abstention is a real behavioural dial: Chroma's LongMemEval run observed Claude Opus 4 "frequently abstaining when encountering ambiguity", and GPT-4.1 showing a 2.55% refusal rate on the repeated-words task (https://www.trychroma.com/research/context-rot).

**Grade: CONSENSUS** that abstention is a trainable/promptable capability and that models are currently under-calibrated. **CONTESTED / OPEN** whether it generalises across domains — the survey itself lists this as unresolved.

### 4.6 The seven RAG failure points

Barnett et al., 2024 (https://arxiv.org/abs/2401.05856 ; https://ar5iv.labs.arxiv.org/html/2401.05856), from three case studies across research, education and biomedical domains:

| # | Failure point | Description (paper's wording) |
|---|---|---|
| FP1 | **Missing content** | "asking a question that cannot be answered from the available documents" |
| FP2 | **Missed the top-ranked documents** | "The answer to the question is in the document but did not rank highly enough to be returned" |
| FP3 | **Not in context — consolidation strategy** | "Documents with the answer were retrieved… but did not make it into the context for generating an answer" |
| FP4 | **Not extracted** | "the answer is present in the context, but the large language model failed to extract out the correct answer" — typically from noise or contradictory information |
| FP5 | **Wrong format** | "the large language model ignored the instruction" to produce a table/list |
| FP6 | **Incorrect specificity** | answer "is not specific enough or is too specific to address the user's need" |
| FP7 | **Incomplete** | "not incorrect but miss some of the information even though that information was in the context" |

Two lessons the authors call out: **"validation of a RAG system is only feasible during operation"**, and **"the robustness of a RAG system evolves rather than [being] designed in at the start."** They also recommend metadata to improve retrieval and continuous runtime monitoring.

**Grade: SINGLE SOURCE** (one paper, three case studies) but corroborated piecewise: FP4 by Lost in the Middle and Context Rot; FP5 by structured outputs; FP2/FP3 by Contextual Retrieval.

### 4.7 Why a prompt-enforced rule is weaker than a programmatic one

This is the sharpest practical question and the evidence is good but two-sided.

**For the "programmatic wins" position:**

1. **Models follow prompt constraints poorly at agentic scale.** AgentIF (Qi et al., 2025; https://arxiv.org/abs/2505.16944 ; https://arxiv.org/html/2505.16944v1): 707 human-annotated instructions from 50 real applications, averaging **1,723 words and 11.9 constraints each**. Best results: **o1-mini CSR 59.8 / ISR 27.2**; GPT-4o CSR 58.5 / ISR 35.1; Claude 3.5 Sonnet CSR 56.6 / ISR 36.9. Worst constraint class: **tool constraints at 26.9 CSR** for the best model, against 80.8 for "vanilla" constraints; condition constraints ~60% vs 82–87% vanilla. Tool + condition constraints "account for approximately 42.6% of real-world applications". Read plainly: **a rule written into a long agentic system prompt is satisfied roughly a quarter to two-thirds of the time depending on its type**.
2. **MAST**: "disobey task specification" is 11.8% of all observed multi-agent failures; "no or incomplete verification" 8.2% and "incorrect verification" 9.1% (https://arxiv.org/html/2503.13657v3). Failures "require structural redesigns beyond superficial fixes".
3. **Constrained decoding makes format compliance a non-issue.** OpenAI's Structured Outputs constrains generation rather than validating afterwards, and makes refusals machine-detectable via a dedicated `refusal` field rather than shoehorning a refusal into the schema (https://developers.openai.com/api/docs/guides/structured-outputs).
4. **Runtime guardrails are model-independent and interpretable.** NeMo Guardrails (Rebedea et al., EMNLP 2023 Demo; https://arxiv.org/abs/2310.10501): programmable rails at a dialogue-management-style runtime, where guardrails are "user-defined, independent of the underlying LLM, and interpretable" — explicitly contrasted with alignment baked in at training time.
5. **Guardrail SDKs make the enforcement point explicit.** OpenAI Agents SDK (https://openai.github.io/openai-agents-python/guardrails/): input and output guardrails with **tripwires** that "immediately rais[e] an InputGuardrailTripwireTriggered or OutputGuardrailTripwireTriggered exception and halt agent execution". Blocking mode runs the guardrail *before* the agent so that "the agent never executes, preventing token consumption and tool execution". Guardrails AI (https://www.guardrailsai.com/docs) composes **validators** into **Input and Output Guards** that "intercept LLM data flows, catching problems before they propagate downstream".
6. **Anthropic tells authors to hand fragile steps to code, not prose.** In Skills: use **low freedom** (a specific script, no parameters) when "operations are fragile and error-prone" / "consistency is critical"; and "Prefer scripts for deterministic operations: write `validate_form.py` rather than asking Claude to generate validation code". They also prescribe the **plan-validate-execute** pattern — have the agent write a plan file, validate it with a script, *then* execute — because "validation finds problems before changes are applied" and "scripts provide objective verification" (https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).

**Against — the important counter-evidence:**

*Let Me Speak Freely?* (Tam et al., EMNLP 2024; https://arxiv.org/abs/2408.02442 ; https://ar5iv.labs.arxiv.org/html/2408.02442) finds "a significant decline in LLMs reasoning abilities under format restrictions", and that "stricter format constraints generally lead to greater performance degradation in reasoning tasks":

| Model | GSM8K text | GSM8K JSON-with-schema |
|---|---|---|
| Claude-3-Haiku | 86.51% | **23.44%** |
| GPT-3.5-Turbo | 75.99% | 49.25% |
| LLaMA-3-8B | 75.13% | 48.90% |
| Gemini-1.5-Flash | 89.33% | 89.21% (no material change) |

But the same paper finds the **opposite** on classification: on DDXPlus, Gemini-1.5-Flash 41.59% → 60.36% (+18.77) and GPT-3.5-Turbo 44.07% → 55.51% (+11.44), because "constraining possible answers resulted in reducing errors in answer selection".

And OpenAI's own docs are explicit that constrained decoding buys **shape, not truth**: "Structured Outputs can still contain mistakes… try adjusting your instructions, providing examples in the system instructions, or splitting tasks into simpler subtasks" (https://developers.openai.com/api/docs/guides/structured-outputs).

**Grade: CONSENSUS** that a rule which *can* be checked in code should be checked in code rather than merely asserted in a prompt — six independent sources (AgentIF, MAST, OpenAI SDK, NeMo, Guardrails AI, Anthropic Skills) converge.
**Grade: CONTESTED** on *where* to apply the constraint. Constraining the **reasoning path** (forcing JSON while the model reasons) can be severely harmful — up to a 63-point drop for Claude-3-Haiku on GSM8K. Constraining the **final selection or output shape** helps. The reconciling rule the sources support: let the model reason freely, then constrain/validate the artefact.
**Grade: CONTESTED/UNVERIFIED** on the widely-repeated "100% with Structured Outputs vs <40% with prompting" figure. **I could not fetch the OpenAI announcement post** — https://openai.com/index/introducing-structured-outputs-in-the-api/ returned **HTTP 403**. I saw the figure only in secondary sources via search. Do not cite it as verified.

---

## 5. Synthesis — the rules and steps the sources actually agree on

### 5.1 The layer model the literature supports (replaces the two-way split)

```
L0  ROUTING METADATA      name + description per skill/tool. Always loaded. Tiny. Its only job
                          is selection. Must state WHAT and WHEN. Third person. No overlap.
L1  TASK PROCEDURE        one task, ordered steps, action only, no explanation. Links out to L2.
L2  DOMAIN REFERENCE      authoritative facts, split BY DOMAIN into separate files. Describe only.
                          Loaded on demand, never wholesale.
L3  EXPLANATION           the why/rationale. Separate again. Needed to adapt a procedure, not run it.
L4  DETERMINISTIC CODE    validators, scripts, guardrails. Every rule that CAN be checked in code IS.
L5  MEMORY / STATE        written by the agent, persisted outside the window, re-loaded selectively.
L6  VERIFICATION          post-hoc groundedness/attribution check + abstention branch.
```

L0, L3, L4, L5 and L6 are all absent from the two-way hypothesis. L1 ≈ Diátaxis how-to; L2 ≈ Diátaxis reference.

### 5.2 Rules (each backed above)

1. **Separate procedure from reference, and link — never copy.** How-to = "action and only action"; reference = "describe and only describe"; each links to the other. (diataxis.fr/how-to-guides, /reference) — duplication is how you get the contradictory-instruction failure OpenAI documents.
2. **Split reference by domain, not into one global blob.** `reference/finance.md`, `reference/sales.md`, … so that irrelevant domains cost zero tokens. (Anthropic Skills best practices)
3. **Treat the selection metadata as a first-class artefact.** It is the only thing always in context and the only thing routing sees. State what and when; third person; ≤1,024 chars; no two descriptions may overlap. The human test: if a competent human can't say which one applies, the agent can't either. (Anthropic writing-tools + Skills)
4. **Keep the candidate set small and dynamic.** Retrieve over tool/skill descriptions rather than listing everything. Evidence: 13.62% → 43.13% (RAG-MCP); 7 tools shown instead of 50 at equal coverage, 93.1% vs 87.1% selection accuracy (chance-corrected tool-count paper).
5. **Never preload what you can load on demand.** Level 1 metadata → level 2 body → level 3 files → scripts executed not read. SKILL.md under 500 lines; references one level deep; TOC on any reference file over 100 lines. (Anthropic Skills best practices)
6. **Assume added context can make things worse, and measure it.** 53.8% mid-context vs 56.1% closed-book (Liu et al.). A single distractor measurably hurts (Chroma). Focused ~300-token prompts beat ~113k-token full prompts on LongMemEval.
7. **Below ~200k tokens of corpus, consider skipping retrieval entirely** and caching the whole thing. (Anthropic contextual-retrieval) — this genuinely contradicts rule 5 at small scale; pick by measurement.
8. **Improve retrieval before improving prompts.** Contextual embeddings + BM25 + reranking took top-20 failure from 5.7% → 1.9%. OpenAI: separate retrieval failures from LLM failures before tuning either.
9. **Give the agent an external memory tier for anything long-horizon,** and prune stale tool results. (+39% agentic search, −84% tokens on a 100-turn eval; MemGPT for the architecture.)
10. **Isolate sub-tasks into their own context windows — but write explicit delegation contracts.** Objective, output format, tools/sources, task boundaries. Isolation without contracts produces the 32.15% inter-agent misalignment class in MAST, and duplicated subagent work in Anthropic's own account. Budget ~15× tokens.
11. **Every rule that can be verified in code must be verified in code, not asserted in prose.** Best model on AgentIF satisfies only 26.9% of tool constraints stated in the prompt. Use plan → validate → execute with a real validator script.
12. **Constrain the artefact, not the reasoning.** Let the model reason in free text, then constrain/validate the output. Forcing schema during reasoning cost Claude-3-Haiku 63 points on GSM8K; the same constraint *helped* classification by 11–19 points.
13. **Require attribution and measure it with claim decomposition.** Split answer into atomic claims → verify each against source → report supported fraction. This exact algorithm is independently reinvented by RAGAS, TruLens and FActScore, and defined by AIS.
14. **Build an explicit abstention branch and reward it in your evals.** If your eval scores only correctness, you are training guessing back in (Kalai et al.). Add unanswerable questions (SelfAware-style) to the eval set.
15. **Validate in operation, not only offline.** "Validation of a RAG system is only feasible during operation"; "robustness… evolves rather than [is] designed in at the start" (Barnett et al.). NIST AI RMF makes valid-and-reliable "a necessary condition of trustworthiness… the base for other trustworthiness characteristics" (https://airc.nist.gov/AI_RMF_Knowledge_Base/AI_RMF/Foundational_Information/3-sec-characteristics).

### 5.3 Steps a team can follow

1. **Write the evals first.** Anthropic: "Create evaluations BEFORE writing extensive documentation… This ensures your Skill solves real problems rather than documenting imagined ones." Their loop: identify gaps by running with no skill → build ≥3 scenarios → measure baseline → write minimal instructions → iterate. Include unanswerable/out-of-scope cases from day one.
2. **Enumerate tasks. One procedure file per task.** Action only. Explicit ordered steps; use a copyable checklist for multi-step work.
3. **Enumerate domains. One reference file per domain.** Authoritative, austere, structured to mirror the product. Facts live here once.
4. **Write the routing metadata last, then de-conflict it.** For every pair of skills/tools, ask a colleague which one applies to a borderline request. Any hesitation = rewrite both descriptions or merge them.
5. **Draw the loading policy explicitly.** What is always in context (L0 only)? What loads on trigger (L1)? What loads on reference (L2/L3)? What is only ever executed (L4)? Anything you cannot place is probably duplication.
6. **Move every checkable rule into a validator script** and wire it as plan → validate → execute. Prefer blocking guardrails where cost matters.
7. **Add the grounding check as a separate post-generation step** — claim decomposition against sources, with citations surfaced. Use a vendor detector (Azure groundedness detection, Vertex grounding metadata) or an OSS metric (RAGAS faithfulness, TruLens groundedness) rather than trusting the generator.
8. **Instrument in production.** Log which skill was selected, what was loaded, retrieval hit/miss, groundedness score, abstention rate. Barnett et al.'s core finding is that these systems can only be validated live.
9. **Re-run the loop on observed failures, not imagined ones.** Anthropic's Claude-A/Claude-B pattern: one instance authors the knowledge, a fresh instance uses it, you observe *where the fresh instance goes wrong* and take that back to the author.

---

## 6. Still open / could not confirm

- **Could not fetch (HTTP 403): the OpenAI Structured Outputs announcement** (https://openai.com/index/introducing-structured-outputs-in-the-api/). The commonly cited "100% vs <40% / 35.8%" schema-following figure is therefore **unverified against the primary source** here. I saw it only in search snippets and third-party blogs.
- **Could not extract from PDF: NIST AI 100-1** (https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf) — binary content was not parseable. I used the NIST AI RMF Knowledge Base HTML instead, which is authoritative but is a different rendering. **ISO/IEC 42001 was not consulted at all** — I found no free primary text and did not want to paraphrase from memory.
- **No controlled comparison found** of embedding/semantic routing vs LLM-as-router vs fine-tuned intent classifier, measured on *skill/procedure selection* (as opposed to model selection or reasoning-effort selection). The one quantified router result I have (vLLM semantic router, +10.2pp MMLU-Pro) is about *whether to reason*, not *which task to run*.
- **The "43% → 2% as tools go 4 → 51" BFCL figure** surfaced in search results but I could **not** trace it to a primary BFCL publication. Excluded from the findings above. Treat as unverified.
- **Whether abstention generalises across domains** is explicitly listed as open by the abstention survey itself (https://arxiv.org/abs/2407.18418). Do not assume a refusal-tuned model refuses correctly in your domain.
- **Anthropic's memory/context-editing numbers (+39%, +29%, −84%) are vendor-internal** and I found no independent replication.
- **Anthropic's 90.2% multi-agent improvement** is likewise internal-eval only, and sits uneasily beside MAST's finding that ~32% of multi-agent failures are coordination-seam failures. Unresolved.
- **Diátaxis has no empirical study attached** that I could find. It is a widely adopted design framework, not a measured result. Its rules are well-argued, not proven.
- **FActScore's claims about entity rarity** could not be confirmed from the abstract page; I did not fetch the full paper body.
- **I found no source that names the exact two-way "product knowledge vs task knowledge" split** in agent-engineering terms. The closest published equivalents are Diátaxis reference/how-to and ACT-R declarative/procedural. If a vendor has published that exact framing, I did not find it.
- **The Diátaxis `/needs/` page returned 404**; the separation argument above is drawn from `/`, `/compass/`, `/how-to-guides/` and `/reference/`.
- **Breunig's four-failure-mode taxonomy is a practitioner blog post**, not peer-reviewed. Its underlying citations (Gemini 2.5 report, the Laban et al. multi-turn study, BFCL) are real; the taxonomy naming is his.

---

## 7. Sources

### Vendor primary documentation
1. Anthropic — *Effective context engineering for AI agents* — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
2. Anthropic — *Building effective agents* (routing, orchestrator-workers, ACI) — https://www.anthropic.com/engineering/building-effective-agents
3. Anthropic — *Equipping agents for the real world with Agent Skills* (progressive disclosure) — https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
4. Anthropic — *Writing tools for agents* — https://www.anthropic.com/engineering/writing-tools-for-agents
5. Anthropic — *How we built our multi-agent research system* — https://www.anthropic.com/engineering/multi-agent-research-system
6. Anthropic — *Introducing Contextual Retrieval* — https://www.anthropic.com/news/contextual-retrieval
7. Anthropic / Claude — *Context management: context editing and the memory tool* — https://claude.com/blog/context-management
8. Anthropic — *Skill authoring best practices* — https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
9. OpenAI — *Optimizing LLM accuracy* — https://developers.openai.com/api/docs/guides/optimizing-llm-accuracy
10. OpenAI — *Structured Outputs* guide — https://developers.openai.com/api/docs/guides/structured-outputs
11. OpenAI — *GPT-5 prompting guide* (contradictory instructions) — https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
12. OpenAI — *Agents SDK: Guardrails* — https://openai.github.io/openai-agents-python/guardrails/
13. Google Cloud — *Vertex AI grounding overview* — https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/overview
14. Microsoft — *Groundedness detection in Azure AI Content Safety* — https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/groundedness
15. LangChain — *Context engineering for agents* (write/select/compress/isolate) — https://www.langchain.com/blog/context-engineering-for-agents
16. Guardrails AI — documentation — https://www.guardrailsai.com/docs
17. RAGAS — *Faithfulness* metric — https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/
18. TruLens — *The RAG Triad* — https://www.trulens.org/getting_started/core_concepts/rag_triad/

### Frameworks and standards
19. Diátaxis — home — https://diataxis.fr/
20. Diátaxis — *The compass* — https://diataxis.fr/compass/
21. Diátaxis — *How-to guides* — https://diataxis.fr/how-to-guides/
22. Diátaxis — *Reference* — https://diataxis.fr/reference/
23. NIST — *AI RMF: Characteristics of trustworthy AI systems* — https://airc.nist.gov/AI_RMF_Knowledge_Base/AI_RMF/Foundational_Information/3-sec-characteristics
24. Anderson, J. R. (1996), *ACT: A Simple Theory of Complex Cognition*, American Psychologist 51(4) 355–365 — https://acs.ist.psu.edu/misc/dirk-files/Papers/ACT-R_GeneralReviews/AC%20A%20simple%20theory%20of%20complex%20cognition.htm

### Papers
25. Lewis et al. (2020) — *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, NeurIPS — https://arxiv.org/abs/2005.11401
26. Liu et al. (2023) — *Lost in the Middle: How Language Models Use Long Contexts*, TACL — https://arxiv.org/abs/2307.03172 ; full text https://ar5iv.labs.arxiv.org/html/2307.03172
27. Barnett et al. (2024) — *Seven Failure Points When Engineering a Retrieval Augmented Generation System* — https://arxiv.org/abs/2401.05856 ; full text https://ar5iv.labs.arxiv.org/html/2401.05856
28. Rashkin et al. (2023) — *Measuring Attribution in Natural Language Generation Models* (AIS), Computational Linguistics 49(4) — https://aclanthology.org/2023.cl-4.2/ ; https://arxiv.org/abs/2112.12870 ; data https://github.com/google-research-datasets/AIS
29. Min et al. (2023) — *FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation* — https://arxiv.org/abs/2305.14251
30. Kalai, Nachum, Vempala, Zhang (2025) — *Why Language Models Hallucinate* — https://arxiv.org/abs/2509.04664
31. Yin et al. (2023) — *Do Large Language Models Know What They Don't Know?* (SelfAware), ACL Findings — https://arxiv.org/abs/2305.18153
32. Zhang et al. (2023/2024) — *R-Tuning: Instructing Large Language Models to Say 'I Don't Know'* — https://arxiv.org/abs/2311.09677
33. Wen et al. (2024) — *Know Your Limits: A Survey of Abstention in Large Language Models*, TACL — https://arxiv.org/abs/2407.18418
34. Rebedea et al. (2023) — *NeMo Guardrails: A Toolkit for Controllable and Safe LLM Applications with Programmable Rails*, EMNLP Demo — https://arxiv.org/abs/2310.10501
35. Tam et al. (2024) — *Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of Large Language Models*, EMNLP — https://arxiv.org/abs/2408.02442 ; full text https://ar5iv.labs.arxiv.org/html/2408.02442
36. Packer et al. (2023) — *MemGPT: Towards LLMs as Operating Systems* — https://arxiv.org/abs/2310.08560
37. Cemri et al. (2025) — *Why Do Multi-Agent LLM Systems Fail?* (MAST) — https://arxiv.org/abs/2503.13657 ; full text https://arxiv.org/html/2503.13657v3
38. Laban, Hayashi, Zhou, Neville (2025) — *LLMs Get Lost In Multi-Turn Conversation* — https://arxiv.org/abs/2505.06120
39. Qi et al. (2025) — *AgentIF: Benchmarking Instruction Following of Large Language Models in Agentic Scenarios* — https://arxiv.org/abs/2505.16944 ; full text https://arxiv.org/html/2505.16944v1
40. Gan & Sun (2025) — *RAG-MCP: Mitigating Prompt Bloat in LLM Tool Selection via Retrieval-Augmented Generation* — https://arxiv.org/abs/2505.03275
41. Faghih et al. (2025) — *Tool Preferences in Agentic LLMs are Unreliable* — https://arxiv.org/abs/2505.18135
42. Repantis et al. (2026) — *How Many Tools Should an LLM Agent See? A Chance-Corrected Answer* — https://arxiv.org/abs/2605.24660
43. Wang et al. (2025) — *When to Reason: Semantic Router for vLLM* — https://arxiv.org/abs/2510.08731

### Independent lab / practitioner
44. Chroma Research — *Context Rot: How Increasing Input Tokens Impacts LLM Performance* (18 models) — https://www.trychroma.com/research/context-rot
45. Drew Breunig — *How Long Contexts Fail* (context poisoning / distraction / confusion / clash) — https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html

### Attempted and failed
- OpenAI — *Introducing Structured Outputs in the API* — https://openai.com/index/introducing-structured-outputs-in-the-api/ — **HTTP 403, not read**
- NIST AI 100-1 PDF — https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf — **binary not parseable**
- Diátaxis — https://diataxis.fr/needs/ — **HTTP 404**
