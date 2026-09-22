"""FastAPI backend: SSE query endpoint, conversation CRUD, issue reporting,
pre-built frontend bundle. See docs/components/ui/API_CONTRACT.md and
ADR-0003 (one process, a pre-built static bundle, not two dev servers).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from urllib.parse import quote
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core import harness
from app.core.config import AgentConfig
from app.core.llm_client import LLMClient, LLMUnavailableError
from app.core.storage import SqliteConversationStore

_logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

_ISSUE_BODY_MESSAGE_LIMIT = 10
_MAX_QUERY_LENGTH = 2000
"""Input-hygiene bound, not a full moderation pipeline -- this is an
internal tool for a small, trusted colleague user base, so Gemini's own
built-in safety filtering (see llm_client.py) already covers content risk.
This just bounds cost/latency against a pathologically long paste, the same
spirit as the dashboard's own result-count guardrails."""


class _QueryBody(BaseModel):
    query: str


class _IssueBody(BaseModel):
    conversation_id: str | None = None
    description: str = ""


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _stream_query(
    conversation_id: str, query: str, config: AgentConfig, llm: LLMClient, store: SqliteConversationStore
):
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_step(message: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "step", "message": message})

    def run() -> None:
        try:
            answer = harness.run_query(conversation_id, query, config=config, llm=llm, store=store, on_step=on_step)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "answer", "content": answer.plain_language_answer})
        except LLMUnavailableError as exc:
            # exc's own message is already a fixed, safe, user-facing string
            # -- never str() the underlying cause here. See llm_client.py.
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001 -- deliberately broad: surface any failure to the UI, never hang the stream
            # Confirmed live: interpolating str(exc) here leaked internal
            # infrastructure details (a proxy hostname/port) verbatim into
            # the chat UI. Log the real exception server-side instead.
            _logger.exception("run_query failed for conversation %s", conversation_id)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": "Something went wrong while processing your question. Please try again."},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=run, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            return
        yield _sse(item)


def _build_mailto_url(config: AgentConfig, conversation_id: str | None, description: str, store: SqliteConversationStore) -> str:
    subject = "PackIT Operations Agent -- issue report"
    lines = [description.strip() or "(no description given)", ""]
    if conversation_id:
        lines.append(f"Conversation: {conversation_id}")
        lines.append("")
        recent = store.get_messages(conversation_id)[-_ISSUE_BODY_MESSAGE_LIMIT:]
        for message in recent:
            lines.append(f"[{message.role}] {message.content}")
    body = "\n".join(lines)
    return f"mailto:{config.issue_report_email}?subject={quote(subject)}&body={quote(body)}"


def create_app(config: AgentConfig, llm: LLMClient, store: SqliteConversationStore) -> FastAPI:
    app = FastAPI(title="PackIT Operations Agent")

    @app.get("/api/conversations")
    def list_conversations():
        return [
            {"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in store.list_conversations()
        ]

    @app.post("/api/conversations")
    def create_conversation():
        return {"id": store.create_conversation()}

    @app.get("/api/conversations/{conversation_id}/messages")
    def get_messages(conversation_id: str):
        return [
            {"role": m.role, "content": m.content, "created_at": m.created_at}
            for m in store.get_messages(conversation_id)
        ]

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str):
        store.delete_conversation(conversation_id)

    @app.post("/api/conversations/{conversation_id}/query")
    async def query_conversation(conversation_id: str, body: _QueryBody):
        if not body.query.strip():
            raise HTTPException(status_code=400, detail="query must not be empty")
        if len(body.query) > _MAX_QUERY_LENGTH:
            raise HTTPException(status_code=400, detail=f"query exceeds {_MAX_QUERY_LENGTH} characters")
        return StreamingResponse(
            _stream_query(conversation_id, body.query, config, llm, store), media_type="text/event-stream"
        )

    @app.post("/api/issues")
    def report_issue(body: _IssueBody):
        store.record_issue(body.conversation_id, body.description)
        return {"mailto_url": _build_mailto_url(config, body.conversation_id, body.description, store)}

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app
