"""Live model-name lookup, per personal-subscription vendor.

Model names change often enough that hardcoding a list in the setup wizard
guarantees it goes stale -- confirmed the hard way in this project already
(see `config.py`'s `gemini_model` note: pinned `gemini-2.5-*` names started
404-ing on a working key while still appearing in the catalog). So
`packit-agent init` asks the vendor, with the key the colleague just
entered, what models that key can actually see.

Deliberately its own module rather than part of `llm_client.py`: this is a
setup-time HTTP call against a *catalog* endpoint, not part of the runtime
`LLMClient` Protocol -- nothing in the query path imports this.

Every call is best-effort by design. A corporate proxy sitting between the
laptop and the vendor is the normal case here, not the exception (see
`LLMUnavailableError`'s own docstring), so `ModelCatalogError` is an
expected outcome the wizard recovers from by letting the colleague type a
model name manually -- never a reason to fail setup.
"""

from __future__ import annotations

import httpx

GEMINI = "gemini"
OPENAI = "openai"
ANTHROPIC = "anthropic"

_PAGE_LIMIT = 5
"""Cap on pagination follow-through. All three catalogs fit well inside
this; the cap exists so a malformed/looping `nextPageToken` can't hang the
setup wizard indefinitely."""

_TIMEOUT_SECONDS = 15

_NON_CHAT_MARKERS = (
    # Text-adjacent but not chat completion
    "embedding", "embed", "moderation", "rerank", "aqa",
    # Other modalities entirely -- speech, image, video, music
    "whisper", "tts", "dall-e", "audio", "image", "imagen", "transcribe",
    "realtime", "veo", "lyria", "banana", "sora",
    # Task-specific models that can't serve a general question-answering agent
    "robotics", "computer-use", "search",
)
"""Substrings marking a model that can't serve this agent's chat/tool-calling
path. Purely a *display* filter for the wizard's menu -- these catalogs
return speech, image, video, music, and embedding models right alongside the
chat ones, and offering those as choices would produce a config that fails at
first query. Confirmed live (2026-08-06) against a real Gemini key: an
unfiltered list led with music and image-generation models. Never
authoritative -- the wizard always also offers manual entry, so a model
wrongly filtered here is still reachable."""

_PREFERRED_PREFIXES = {
    GEMINI: ("gemini-",),
    OPENAI: ("gpt-", "o1", "o3", "o4"),
    ANTHROPIC: ("claude-",),
}
"""Each vendor's mainline chat family, floated to the top of the picker.

Filtering alone isn't enough to make the menu useful: a vendor's catalog also
carries genuinely chat-capable but off-mainline families (Gemini's `gemma-*`
open-weight models, for one) that shouldn't outrank the model a colleague
actually came for. Ranking rather than filtering, because those models do
work -- they just aren't the default answer."""


class ModelCatalogError(Exception):
    """The vendor's model-list endpoint couldn't be reached or understood.
    Expected and recoverable -- the wizard falls back to manual entry."""


def _is_chat_capable(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def _get(url: str, *, headers: dict[str, str] | None = None, params: dict[str, str] | None = None) -> dict:
    try:
        response = httpx.get(
            url,
            headers=headers or {},
            params=params or {},
            # trust_env so the corporate proxy in the colleague's environment
            # (HTTP_PROXY/HTTPS_PROXY, which `packit-agent init` writes itself)
            # is honored -- same as splunk_client/routing_plan do.
            trust_env=True,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        # Status code is the single most useful thing to show a colleague
        # mid-setup: 401/403 means the key is wrong (re-enter it), anything
        # else usually means the network, not them.
        raise ModelCatalogError(f"the vendor returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ModelCatalogError(f"couldn't reach the vendor ({type(exc).__name__})") from exc
    except ValueError as exc:  # non-JSON body
        raise ModelCatalogError("the vendor returned a response that wasn't JSON") from exc


def _list_gemini(api_key: str) -> list[str]:
    """Gemini's catalog reports, per model, which generation methods it
    supports -- filter on `generateContent` rather than guessing from the
    name, since the same catalog also carries embedding-only models. IDs come
    back namespaced (`models/gemini-flash-latest`); the API key field
    elsewhere in this codebase expects the bare name, so strip the prefix.
    """
    models: list[str] = []
    page_token: str | None = None
    for _ in range(_PAGE_LIMIT):
        params = {"key": api_key, "pageSize": "200"}
        if page_token:
            params["pageToken"] = page_token
        payload = _get("https://generativelanguage.googleapis.com/v1beta/models", params=params)
        for entry in payload.get("models") or []:
            name = (entry.get("name") or "").removeprefix("models/")
            if name and "generateContent" in (entry.get("supportedGenerationMethods") or []):
                models.append(name)
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return models


def _list_openai(api_key: str) -> list[str]:
    """OpenAI's `/v1/models` is a single unpaginated list with no capability
    metadata at all -- unlike Gemini's, it says nothing about which models
    can chat -- so `_NON_CHAT_MARKERS` is the only available filter here."""
    payload = _get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    return [entry["id"] for entry in payload.get("data") or [] if entry.get("id")]


def _list_anthropic(api_key: str) -> list[str]:
    """Anthropic's catalog is chat models only, so no capability filtering is
    needed. Auth is the `x-api-key` header plus a mandatory `anthropic-version`
    -- not a Bearer token."""
    models: list[str] = []
    after_id: str | None = None
    for _ in range(_PAGE_LIMIT):
        params = {"limit": "100"}
        if after_id:
            params["after_id"] = after_id
        payload = _get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            params=params,
        )
        entries = payload.get("data") or []
        models.extend(entry["id"] for entry in entries if entry.get("id"))
        if not payload.get("has_more") or not entries:
            break
        after_id = entries[-1].get("id")
    return models


_LISTERS = {GEMINI: _list_gemini, OPENAI: _list_openai, ANTHROPIC: _list_anthropic}


def list_models(vendor: str, api_key: str) -> list[str]:
    """Ask `vendor` which models `api_key` can use, newest-looking first.

    Raises `ModelCatalogError` on any failure -- callers are expected to
    recover (manual entry), not abort.
    """
    lister = _LISTERS.get(vendor)
    if lister is None:
        raise ModelCatalogError(f"no model catalog is implemented for vendor {vendor!r}")
    models = [model for model in lister(api_key) if _is_chat_capable(model)]
    if not models:
        raise ModelCatalogError("the vendor returned no chat-capable models for this key")
    return _ordered_for_display(vendor, set(models))


def _ordered_for_display(vendor: str, models: set[str]) -> list[str]:
    """Mainline chat family first, then reverse-alphabetically within each
    group -- which floats higher version numbers and `-latest` aliases to the
    top. Purely a display convenience for the wizard's menu, not a claim
    about model quality."""
    prefixes = _PREFERRED_PREFIXES.get(vendor, ())
    mainline = sorted((m for m in models if m.lower().startswith(prefixes)), reverse=True)
    rest = sorted((m for m in models if not m.lower().startswith(prefixes)), reverse=True)
    return mainline + rest
