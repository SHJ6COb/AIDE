"""Runtime configuration, loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    llm_provider: str
    splunk_base_url: str
    splunk_api_token: str
    splunk_index: str
    splunk_sourcetype: str
    splunk_verify_ssl: bool
    splunk_search_timeout_seconds: int
    splunk_auth_header: str
    additional_routing_auth_header: str
    gemini_api_key: str
    gemini_model: str
    gemini_timeout_seconds: int
    issue_report_email: str
    additional_routing_url: str
    additional_routing_api_token: str
    model_farm_api_key: str
    model_farm_base_url: str
    model_farm_deployment: str
    model_farm_model: str
    model_farm_timeout_seconds: int
    openai_api_key: str
    openai_model: str
    openai_timeout_seconds: int
    anthropic_api_key: str
    anthropic_model: str
    anthropic_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "AgentConfig":
        config = cls(
            # "model_farm" (default, preserves existing behavior for any
            # .env predating this field), or one of the personal-API-key
            # vendors "gemini"/"openai"/"anthropic" -- see
            # `ui/init_wizard.py`'s interactive setup and
            # `llm_client.build_llm_client`, which is the only thing that
            # reads this value.
            llm_provider=os.environ.get("LLM_PROVIDER", "model_farm"),
            splunk_base_url=os.environ["SPLUNK_BASE_URL"],
            splunk_api_token=os.environ["SPLUNK_API_TOKEN"],
            splunk_index=os.environ.get("SPLUNK_INDEX", "pdbb"),
            splunk_sourcetype=os.environ.get("SPLUNK_SOURCETYPE", "Native"),
            splunk_verify_ssl=os.environ.get("SPLUNK_VERIFY_SSL", "true").lower() == "true",
            splunk_search_timeout_seconds=int(os.environ.get("SPLUNK_SEARCH_TIMEOUT_SECONDS", "60")),
            # The gateway authenticates with a bare header carrying the token
            # -- not Bearer, not Basic. The header *name* differs between the
            # two APIs by casing alone ("KeyID" for Splunk, "KeyId" for
            # Additional Routing), which was confirmed live and is easy to get
            # wrong; both are configurable so a gateway-side rename is an .env
            # edit rather than a code change, but neither is something a
            # colleague should have to know -- `packit-agent init` pre-fills
            # them.
            splunk_auth_header=os.environ.get("SPLUNK_AUTH_HEADER", "KeyID"),
            additional_routing_auth_header=os.environ.get("ADDITIONAL_ROUTING_AUTH_HEADER", "KeyId"),
            # First LLM provider -- see components/harness's LLMClient Protocol; a
            # Bosch-provisioned Azure/Vertex-backed client is a planned later swap,
            # not a design constraint on this dataclass. Default confirmed live
            # against the real API: pinned "gemini-2.5-*" models 404 ("no longer
            # available to new users") on this API key despite still appearing in
            # the models.list() catalog -- "-latest" aliases work and stay current
            # without needing a code change when a pinned version is retired.
            # Optional, not required: only one provider is ever selected, so
            # demanding every provider's key would make a Model-Farm-only
            # colleague's .env fail to load over a Gemini key they'll never
            # use. `_require_selected_provider_key` below enforces the one
            # that actually matters.
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
            # Caught live via QA testing: with no bound at all, an identical
            # proxy failure took anywhere from 0.09s to 34s depending on
            # where in the corporate proxy chain it was rejected -- an
            # explicit timeout makes "the LLM is unavailable" a predictable,
            # bounded failure instead of an arbitrary-feeling one. Default
            # has headroom above normal observed latency (a few seconds).
            gemini_timeout_seconds=int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "20")),
            # Where "Report Issue" mailto: drafts are addressed -- see
            # ARCHITECTURE.md's UI section and ADR discussion (mailto, not
            # SMTP, for the MVP).
            issue_report_email=os.environ["ISSUE_REPORT_EMAIL"],
            # Additional Routing plan API -- a separate data source from
            # Splunk, confirmed live against the real Bosch gateway, see
            # docs/components/routing-plan/TECHNICAL_SPEC.md. A different
            # token from SPLUNK_API_TOKEN despite the similar KeyId-header
            # mechanism.
            additional_routing_url=os.environ["ADDITIONAL_ROUTING_URL"],
            additional_routing_api_token=os.environ["ADDITIONAL_ROUTING_API_TOKEN"],
            # Bosch Model Farm -- an internal Azure-OpenAI-compatible gateway
            # fronting several providers (including Gemini) under a Bosch-
            # provisioned subscription key, replacing the personal Gemini API
            # key GeminiClient uses. See modelFarm/ (Docupedia export) for the
            # full spec -- ModelFarmClient follows its "Python OpenAI SDK for
            # Gemini" example. Deployment names use dashes for dots
            # ("google-gemini-3-5-flash"); the request body's own "model"
            # field uses dots ("gemini-3.5-flash") and is mandatory for
            # Gemini specifically (confirmed by that example's own
            # annotation -- unlike Azure-native OpenAI models, where it's
            # ignored).
            model_farm_api_key=os.environ.get("MODEL_FARM_API_KEY", ""),
            model_farm_base_url=os.environ.get("MODEL_FARM_BASE_URL", "https://aoai-farm.bosch-temp.com/api"),
            # Confirmed live (2026-08-06) via a 7-vendor parallel accessibility
            # sweep: this project's Model Farm subscription is Developer-tier,
            # which only grants access to a handful of starred models (see
            # Model Endpoint Reference's own note) -- Gemini, Claude, DeepSeek,
            # Llama, Mistral, and z.AI all returned a clean gateway-level 401
            # ("invalid subscription key... active subscription") across every
            # model tried, while gpt-4o-mini-2024-07-18 and gpt-5-nano-2025-08-07
            # both returned real 200s. gpt-4o-mini chosen as the default over
            # gpt-5-nano as the more capable of the two confirmed-entitled
            # models. Re-run scripts/model_farm_probe_*.py if the subscription
            # is ever upgraded to Enterprise -- Gemini (this app's original
            # target) would very likely become available then.
            model_farm_deployment=os.environ.get("MODEL_FARM_DEPLOYMENT", "askbosch-prod-farm-openai-gpt-4o-mini-2024-07-18"),
            model_farm_model=os.environ.get("MODEL_FARM_MODEL", "gpt-4o-mini"),
            model_farm_timeout_seconds=int(os.environ.get("MODEL_FARM_TIMEOUT_SECONDS", "20")),
            # Personal-subscription vendors, for colleagues without a Model
            # Farm subscription (see ui/init_wizard.py's vendor choice).
            # Deliberately no default model name for either: unlike Gemini,
            # neither vendor publishes a stable "-latest" alias, so any
            # default here would be a pinned name that silently goes stale --
            # `packit-agent init` fetches the live catalog instead (see
            # app/core/model_catalog.py).
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get("OPENAI_MODEL", ""),
            openai_timeout_seconds=int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "20")),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", ""),
            anthropic_timeout_seconds=int(os.environ.get("ANTHROPIC_TIMEOUT_SECONDS", "20")),
        )
        config._require_selected_provider_key()
        return config

    _PROVIDER_KEY_FIELDS = {
        "model_farm": ("model_farm_api_key", "MODEL_FARM_API_KEY"),
        "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
        "openai": ("openai_api_key", "OPENAI_API_KEY"),
        "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    }

    def _require_selected_provider_key(self) -> None:
        """Fail fast, with the fix in the message, if the provider named by
        `LLM_PROVIDER` has no key -- the one case the per-field `.get`
        defaults above would otherwise let through to a confusing 401 on the
        colleague's first question instead of at startup."""
        field = self._PROVIDER_KEY_FIELDS.get(self.llm_provider)
        if field is None:
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider!r} is not a known provider "
                f"({', '.join(self._PROVIDER_KEY_FIELDS)}). Re-run `packit-agent init`."
            )
        attribute, env_name = field
        if not getattr(self, attribute):
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider!r} is selected but {env_name} is empty. "
                "Re-run `packit-agent init` to set it."
            )
