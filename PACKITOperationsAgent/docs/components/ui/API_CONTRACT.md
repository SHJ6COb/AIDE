# UI <-> backend API contract

FastAPI backend (`ui/server.py`), consumed by the React frontend (`ui/frontend/`). See [`ARCHITECTURE.md`](../../ARCHITECTURE.md)'s UI section and [ADR-0002](../../adr/0002-single-user-per-process.md)/[ADR-0003](../../adr/0003-prebuilt-bundle-single-process-launch.md) for why this is a single-process, single-user-per-process design — no auth, no multi-tenant scoping, everything scoped to the one local SQLite DB this process owns.

## `GET /api/conversations`

List all conversations, most recently updated first.

```json
[{"id": "uuid", "title": "PS 400001438900 at plant 0780", "updated_at": "2026-08-05T10:00:00Z"}]
```

`title` is derived server-side from the first user message (truncated), not client-generated.

## `POST /api/conversations`

Create a new, empty conversation. Body: `{}`. Response: `{"id": "uuid"}`.

## `GET /api/conversations/{id}/messages`

Full message history for one conversation, oldest first.

```json
[
  {"role": "user", "content": "what's the status of PS 400001438900?", "created_at": "..."},
  {"role": "assistant", "content": "PS 400001438900 (SHIP, plant 0780) failed with...", "created_at": "..."}
]
```

`content` is the plain-language text only (already-composed markdown-ish prose) — no raw `TransferRecord`/`StatusResult` payload is sent to the frontend; the agent's answer is meant to be self-contained prose per `skill.md`'s composition rules. Render `content` as markdown.

## `DELETE /api/conversations/{id}`

Delete a conversation and its messages. Response: `204 No Content`.

## `POST /api/conversations/{id}/query` — Server-Sent Events

Body: `{"query": "what's the status of PS 400001438900?"}`.

Response: `text/event-stream`. Each event's `data` is a JSON object with a `type` field:

```
data: {"type": "step", "message": "Searching Splunk..."}

data: {"type": "step", "message": "Checking error catalog..."}

data: {"type": "step", "message": "Composing answer..."}

data: {"type": "answer", "content": "PS 400001438900 (SHIP, plant 0780) failed with..."}

```

On failure (Splunk gateway blocked, timeout, LLM error, etc.):

```
data: {"type": "error", "message": "a short, honest, user-facing description of what went wrong"}
```

Exactly one of `answer` or `error` terminates the stream; any number of `step` events precede it (per `get_ps_status`'s `on_step` callback and the harness's own "Composing answer..." step around the LLM's second turn — see `docs/components/harness/TECHNICAL_SPEC.md`). After the stream ends, the frontend should re-fetch `GET /api/conversations/{id}/messages` (simplest correct way to get the persisted, canonical message list) rather than trust its own accumulated SSE state as final.

## `POST /api/issues`

Records an issue report to SQLite and returns a pre-filled `mailto:` link for the frontend to open (`window.location.href = mailto_url`) — the user still has to click Send in their own mail client (see ADR discussion in `ARCHITECTURE.md`; no SMTP dependency for the MVP).

Body:
```json
{"conversation_id": "uuid", "description": "optional free-text from the user about what went wrong"}
```

Response:
```json
{"mailto_url": "mailto:owner@example.com?subject=...&body=..."}
```

The backend includes the conversation's recent messages and any error detail it has in the `mailto_url`'s body, so the user doesn't have to retype context.

## Errors

Any endpoint can return a standard FastAPI error shape (`{"detail": "..."}`) with a 4xx/5xx status. The frontend should show these as a visible error state, never silently swallow them.
