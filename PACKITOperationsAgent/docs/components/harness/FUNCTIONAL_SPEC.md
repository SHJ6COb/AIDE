# harness — Functional Specification

## Purpose

The generic engine that lets any agent (starting with `packspec-status`, with more to follow) answer a natural-language question by combining an LLM's language understanding with a documented, deterministic procedure ("skill") and a set of reliable tools it's allowed to call. It's what makes the agent's behavior consistent and inspectable rather than an unconstrained free-form LLM conversation.

## Why LLM-agnostic

The project currently has access to a Gemini API key, not Anthropic — and the requirement is that the solution not depend on any one LLM vendor. The harness is the one place that talks to "an LLM"; everywhere else in the codebase is written against that abstraction, not a specific vendor's SDK.
