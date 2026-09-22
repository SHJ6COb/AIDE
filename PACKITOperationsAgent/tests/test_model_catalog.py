import httpx
import pytest

from app.core import model_catalog
from app.core.model_catalog import ModelCatalogError, list_models


def _stub_get(monkeypatch, pages):
    """Stub httpx.get with a queue of JSON payloads, recording the requests
    made -- lets the pagination and auth assertions below run without any
    network access."""
    calls = []
    queue = list(pages)

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(200, json=queue.pop(0), request=httpx.Request("GET", url))

    monkeypatch.setattr(model_catalog.httpx, "get", fake_get)
    return calls


def test_gemini_strips_namespace_prefix_and_filters_by_generation_method(monkeypatch):
    """Gemini's catalog carries embedding-only models alongside chat ones and
    namespaces every id -- both have to be handled or the wizard offers model
    names that fail on first use."""
    _stub_get(
        monkeypatch,
        [
            {
                "models": [
                    {"name": "models/gemini-flash-latest", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                ]
            }
        ],
    )
    assert list_models("gemini", "key") == ["gemini-flash-latest"]


def test_gemini_follows_pagination(monkeypatch):
    _stub_get(
        monkeypatch,
        [
            {"models": [{"name": "models/gemini-b", "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "t"},
            {"models": [{"name": "models/gemini-a", "supportedGenerationMethods": ["generateContent"]}]},
        ],
    )
    assert list_models("gemini", "key") == ["gemini-b", "gemini-a"]


def test_openai_uses_bearer_auth_and_filters_non_chat_models(monkeypatch):
    calls = _stub_get(
        monkeypatch,
        [{"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "dall-e-3"}]}],
    )
    assert list_models("openai", "sk-test") == ["gpt-4o"]
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_anthropic_uses_x_api_key_and_version_header(monkeypatch):
    """Confirmed API contract: Anthropic authenticates with x-api-key plus a
    mandatory anthropic-version -- not the Bearer token OpenAI uses."""
    calls = _stub_get(monkeypatch, [{"data": [{"id": "claude-sonnet-4-5"}], "has_more": False}])
    assert list_models("anthropic", "sk-ant-test") == ["claude-sonnet-4-5"]
    assert calls[0]["headers"]["x-api-key"] == "sk-ant-test"
    assert calls[0]["headers"]["anthropic-version"] == "2023-06-01"


def test_anthropic_follows_pagination_by_last_id(monkeypatch):
    calls = _stub_get(
        monkeypatch,
        [
            {"data": [{"id": "claude-b"}], "has_more": True},
            {"data": [{"id": "claude-a"}], "has_more": False},
        ],
    )
    assert list_models("anthropic", "key") == ["claude-b", "claude-a"]
    assert calls[1]["params"]["after_id"] == "claude-b"


def test_results_are_deduplicated_and_sorted_newest_looking_first(monkeypatch):
    _stub_get(monkeypatch, [{"data": [{"id": "gpt-4o"}, {"id": "gpt-5"}, {"id": "gpt-4o"}]}])
    assert list_models("openai", "key") == ["gpt-5", "gpt-4o"]


def test_mainline_chat_family_outranks_off_mainline_models(monkeypatch):
    """Caught live (2026-08-06) against a real Gemini key: plain
    reverse-alphabetical ordering led the picker with music and
    image-generation models, burying every gemini-* chat model. Off-mainline
    families that genuinely do work (gemma-*) are ranked below rather than
    filtered out."""
    _stub_get(
        monkeypatch,
        [
            {
                "models": [
                    {"name": "models/gemma-4-31b-it", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-flash-latest", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
                ]
            }
        ],
    )
    assert list_models("gemini", "key") == ["gemini-flash-latest", "gemini-3.5-flash", "gemma-4-31b-it"]


def test_other_modality_models_are_filtered_out(monkeypatch):
    """Same live catalog carried music (lyria), image (nano-banana), and
    robotics models -- none can serve a chat/tool-calling agent."""
    _stub_get(
        monkeypatch,
        [
            {
                "models": [
                    {"name": "models/lyria-3-pro-preview", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/nano-banana-pro-preview", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-robotics-er-2-preview", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-flash-latest", "supportedGenerationMethods": ["generateContent"]},
                ]
            }
        ],
    )
    assert list_models("gemini", "key") == ["gemini-flash-latest"]


def test_http_error_status_is_reported_not_swallowed(monkeypatch):
    """The status code is the whole diagnostic value mid-setup: 401 means
    re-enter the key, anything else usually means the network."""

    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(401, json={"error": "bad key"}, request=request)

    monkeypatch.setattr(model_catalog.httpx, "get", fake_get)
    with pytest.raises(ModelCatalogError, match="HTTP 401"):
        list_models("openai", "bad-key")


def test_network_failure_becomes_model_catalog_error(monkeypatch):
    """A blocked corporate proxy is the expected failure here -- it has to
    arrive as the recoverable error the wizard falls back from, not an
    arbitrary httpx exception escaping into the setup flow."""

    def fake_get(url, **kwargs):
        raise httpx.ConnectError("proxy refused")

    monkeypatch.setattr(model_catalog.httpx, "get", fake_get)
    with pytest.raises(ModelCatalogError, match="couldn't reach"):
        list_models("openai", "key")


def test_empty_catalog_is_an_error_not_an_empty_menu(monkeypatch):
    _stub_get(monkeypatch, [{"data": []}])
    with pytest.raises(ModelCatalogError, match="no chat-capable models"):
        list_models("openai", "key")


def test_unknown_vendor_rejected():
    with pytest.raises(ModelCatalogError, match="no model catalog"):
        list_models("mistral", "key")
