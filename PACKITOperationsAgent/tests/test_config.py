import pytest

from app.core.config import AgentConfig

_MINIMUM_ENV = {
    "SPLUNK_BASE_URL": "https://splunk.example",
    "SPLUNK_API_TOKEN": "splunk-token",
    "ISSUE_REPORT_EMAIL": "owner@example.com",
    "ADDITIONAL_ROUTING_URL": "https://routing.example",
    "ADDITIONAL_ROUTING_API_TOKEN": "routing-token",
}


def _set_env(monkeypatch, **overrides):
    for name in (
        "LLM_PROVIDER", "GEMINI_API_KEY", "MODEL_FARM_API_KEY",
        "OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**_MINIMUM_ENV, **overrides}.items():
        monkeypatch.setenv(name, value)


def test_only_the_selected_providers_key_is_required(monkeypatch):
    """Regression guard for the multi-provider setup: demanding every
    provider's key would make a Model-Farm-only colleague's .env fail to load
    over a Gemini key they will never use."""
    _set_env(monkeypatch, LLM_PROVIDER="model_farm", MODEL_FARM_API_KEY="mf-key")
    config = AgentConfig.from_env()
    assert config.llm_provider == "model_farm"
    assert config.gemini_api_key == ""


def test_missing_key_for_the_selected_provider_fails_fast_with_the_fix(monkeypatch):
    """Without this the .env loads fine and the colleague meets the problem
    as an opaque 401 on their first real question instead of at startup."""
    _set_env(monkeypatch, LLM_PROVIDER="anthropic")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is empty"):
        AgentConfig.from_env()


def test_unknown_provider_is_rejected(monkeypatch):
    _set_env(monkeypatch, LLM_PROVIDER="mistral")
    with pytest.raises(ValueError, match="not a known provider"):
        AgentConfig.from_env()


def test_provider_defaults_to_model_farm_for_env_files_predating_the_field(monkeypatch):
    _set_env(monkeypatch, MODEL_FARM_API_KEY="mf-key")
    assert AgentConfig.from_env().llm_provider == "model_farm"


@pytest.mark.parametrize(
    "provider,key_env,model_env,model",
    [
        ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o"),
        ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-sonnet-4-5"),
    ],
)
def test_personal_vendor_key_and_model_are_read(monkeypatch, provider, key_env, model_env, model):
    _set_env(monkeypatch, LLM_PROVIDER=provider, **{key_env: "personal-key", model_env: model})
    config = AgentConfig.from_env()
    assert getattr(config, f"{provider}_api_key") == "personal-key"
    assert getattr(config, f"{provider}_model") == model


def test_auth_header_names_default_to_the_confirmed_live_casing(monkeypatch):
    """The two APIs' header names differ by casing alone -- "KeyID" for
    Splunk, "KeyId" for Additional Routing -- which is confirmed real and
    invisible at a glance. A default that silently normalized them would
    break one of the two."""
    _set_env(monkeypatch, MODEL_FARM_API_KEY="mf-key")
    config = AgentConfig.from_env()
    assert config.splunk_auth_header == "KeyID"
    assert config.additional_routing_auth_header == "KeyId"


def test_auth_header_names_are_overridable(monkeypatch):
    """So a gateway-side rename is an .env edit, not a code change."""
    _set_env(monkeypatch, MODEL_FARM_API_KEY="mf-key")
    monkeypatch.setenv("SPLUNK_AUTH_HEADER", "X-Api-Key")
    monkeypatch.setenv("ADDITIONAL_ROUTING_AUTH_HEADER", "X-Routing-Key")
    config = AgentConfig.from_env()
    assert config.splunk_auth_header == "X-Api-Key"
    assert config.additional_routing_auth_header == "X-Routing-Key"
