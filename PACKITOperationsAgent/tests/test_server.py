from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

import app.core.harness as harness
from app.agents.packspec_status.pipeline import StatusResult
from app.core.llm_client import LLMUnavailableError, Response, ToolCall
from app.core.storage import SqliteConversationStore
from app.tools.catalog import CatalogMatch
from app.tools.transform import Hop, TransferRecord
from ui.server import create_app


def _error_record() -> TransferRecord:
    hop = Hop(
        message_id="MSG1", message_type="PackITPackagingSpecification", host="SAPP790110_CONSUMING",
        target_system="SAPP790110", time="2026-08-04T10:00:00", business_status="ERROR",
        description="SNR13 not found/ Mark for deletion", ps_id="00000000040000054543", dir_key=None,
        plant="0580", det_type="SHIP", usage="R", dependent_ps_links=None, envelope="atom",
    )
    return TransferRecord(message_id="MSG1", message_type=hop.message_type, ps_id=hop.ps_id, dir_key=None, target_system=hop.target_system, hops=[hop])


class _FakeLLMClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def generate(self, messages, tools, *, system_instruction):
        return self._responses.pop(0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "_load_skill", lambda mode: "test skill instructions")

    canned_result = StatusResult(
        primary_records=[_error_record()],
        dependent_objects=None,
        catalog_matches=[CatalogMatch(2, "Target Error", "Plant", "material missing", "create or delete the DR")],
    )
    monkeypatch.setattr(harness, "get_ps_status", lambda params, config, on_step=None: canned_result)

    llm = _FakeLLMClient(
        [
            Response(text=None, tool_calls=[ToolCall(name="get_ps_status", arguments={"ps_id": "00000000040000054543"})]),
            Response(text="PS 00000000040000054543 failed. Plant should create or delete the DR.", tool_calls=[]),
        ]
    )
    config = SimpleNamespace(issue_report_email="owner@example.com")
    store = SqliteConversationStore(tmp_path / "test.db")
    app = create_app(config, llm, store)
    return TestClient(app)


def test_create_and_list_conversations(client):
    created = client.post("/api/conversations").json()
    assert "id" in created

    conversations = client.get("/api/conversations").json()
    assert conversations[0]["id"] == created["id"]
    assert conversations[0]["title"] == "New conversation"


def test_query_streams_steps_then_answer_and_persists_messages(client):
    conv_id = client.post("/api/conversations").json()["id"]

    with client.stream(
        "POST", f"/api/conversations/{conv_id}/query", json={"query": "what's the status of PS 00000000040000054543?"}
    ) as response:
        events = [line for line in response.iter_lines() if line.startswith("data: ")]

    assert '"type": "step"' in events[0]
    assert any('"type": "answer"' in e for e in events)
    assert "create or delete the DR" in events[-1]

    messages = client.get(f"/api/conversations/{conv_id}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "create or delete the DR" in messages[1]["content"]


def test_query_rejects_overly_long_body(client):
    conv_id = client.post("/api/conversations").json()["id"]
    response = client.post(f"/api/conversations/{conv_id}/query", json={"query": "x" * 2001})
    assert response.status_code == 400


def test_query_rejects_empty_body(client):
    conv_id = client.post("/api/conversations").json()["id"]
    response = client.post(f"/api/conversations/{conv_id}/query", json={"query": "   "})
    assert response.status_code == 400


def test_delete_conversation(client):
    conv_id = client.post("/api/conversations").json()["id"]
    response = client.delete(f"/api/conversations/{conv_id}")
    assert response.status_code == 204
    assert client.get("/api/conversations").json() == []


def test_report_issue_returns_mailto_with_recipient_and_context(client):
    conv_id = client.post("/api/conversations").json()["id"]
    client.post(f"/api/conversations/{conv_id}/query", json={"query": "test question"})

    response = client.post("/api/issues", json={"conversation_id": conv_id, "description": "the answer seemed off"})
    data = response.json()
    assert data["mailto_url"].startswith("mailto:owner@example.com?")
    decoded = unquote(data["mailto_url"])
    assert "the answer seemed off" in decoded
    assert conv_id in decoded


def test_report_issue_without_conversation_still_works(client):
    response = client.post("/api/issues", json={"description": "general feedback"})
    assert response.status_code == 200
    assert response.json()["mailto_url"].startswith("mailto:owner@example.com?")


def test_query_stream_surfaces_pipeline_errors_as_error_event_without_leaking_internals(client, monkeypatch):
    """Regression test: caught live via QA testing -- the raw exception
    string (including a corporate proxy's internal hostname/port) was
    surfacing verbatim in the chat UI. A generic exception must now produce
    a fixed, safe message -- never str(exc)."""

    def _raise(params, config, on_step=None):
        raise RuntimeError("Splunk gateway blocked at rb-internal-host:8089, token=SECRET123")

    monkeypatch.setattr(harness, "get_ps_status", _raise)
    conv_id = client.post("/api/conversations").json()["id"]

    with client.stream("POST", f"/api/conversations/{conv_id}/query", json={"query": "anything"}) as response:
        events = [line for line in response.iter_lines() if line.startswith("data: ")]

    error_events = [e for e in events if '"type": "error"' in e]
    assert error_events
    assert "SECRET123" not in error_events[0]
    assert "rb-internal-host" not in error_events[0]
    assert "Please try again" in error_events[0]


def test_query_stream_llm_unavailable_error_passes_through_its_own_safe_message(client, monkeypatch):
    def _raise(params, config, on_step=None):
        raise LLMUnavailableError("The AI service is temporarily unavailable. Please try again.")

    monkeypatch.setattr(harness, "get_ps_status", _raise)
    conv_id = client.post("/api/conversations").json()["id"]

    with client.stream("POST", f"/api/conversations/{conv_id}/query", json={"query": "anything"}) as response:
        events = [line for line in response.iter_lines() if line.startswith("data: ")]

    error_events = [e for e in events if '"type": "error"' in e]
    assert error_events
    assert "The AI service is temporarily unavailable" in error_events[0]
