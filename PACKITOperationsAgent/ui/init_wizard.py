"""Interactive `packit-agent init` setup wizard -- writes/updates the
project's `.env` file so a fresh `git clone` can go from zero to a running
app without hand-editing environment variables. See README.md.

Deliberately plain `input()`/`getpass()` prompts, no CLI framework
dependency -- this runs exactly once per machine, not a hot path.

The LLM section is the part worth reading: it asks which backend to use
(Bosch Model Farm vs. a personal subscription), collects a key, offers real
model names (fetched live from the vendor for personal keys -- see
`app/core/model_catalog.py` for why they aren't hardcoded), and then makes
one actual call to prove the combination works before the colleague ever
reaches the chat UI. A failed check loops back to the key/model prompts
rather than writing a `.env` that's already known to be broken.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from pathlib import Path

from app.core import model_catalog
from app.core.config import AgentConfig
from app.core.llm_client import ANTHROPIC, GEMINI, MODEL_FARM, OPENAI, quick_check

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

# (label, deployment, model) -- deployment is the URL path segment, model is
# the request body's "model" field; ModelFarmClient needs both (see
# app/core/llm_client.py). Only models reachable through the
# `openai/deployments/{deployment}/chat/completions` shape are listed here --
# that's the only shape ModelFarmClient speaks today.
#
# Unlike the personal-vendor path below, this list stays hardcoded: the Model
# Farm gateway exposes no model-catalog endpoint to query, and its deployment
# names aren't derivable from the model names (note the dashes-for-dots and
# the "askbosch-prod-farm-" prefixes). The confirmed-available tags reflect
# this project's own Developer-tier subscription (2026-08-06); a colleague on
# an Enterprise subscription may have more than what's marked confirmed --
# the quick check below is what settles it, per-machine. See
# scripts/model_farm_probe_*.py.
_MODEL_FARM_MODELS = [
    ("gpt-4o-mini (confirmed available on Developer-tier subscriptions)", "askbosch-prod-farm-openai-gpt-4o-mini-2024-07-18", "gpt-4o-mini"),
    ("gpt-5-nano (confirmed available on Developer-tier subscriptions)", "gpt-5-nano-2025-08-07", "gpt-5-nano-2025-08-07"),
    ("gpt-5 (needs Enterprise subscription)", "gpt-5-2025-08-07", "gpt-5-2025-08-07"),
    ("gpt-4.1 (needs Enterprise subscription)", "askbosch-prod-farm-openai-gpt-41-2025-04-14", "gpt-4.1"),
    ("gemini-2.5-flash (needs Enterprise subscription)", "google-gemini-2-5-flash", "gemini-2.5-flash"),
    ("gemini-2.5-pro (needs Enterprise subscription)", "google-gemini-2-5-pro", "gemini-2.5-pro"),
    ("Custom -- enter deployment + model manually", None, None),
]

_PERSONAL_VENDORS = [
    (GEMINI, "Google Gemini", "https://aistudio.google.com/apikey"),
    (OPENAI, "OpenAI", "https://platform.openai.com/api-keys"),
    (ANTHROPIC, "Anthropic (Claude)", "https://console.anthropic.com/settings/keys"),
]

_MODEL_MENU_LIMIT = 15
"""How many fetched model names to show. OpenAI's catalog in particular runs
to dozens of entries; a wall of them is worse than a short list plus the
always-present manual-entry option."""


@dataclass
class _LLMSettings:
    """The LLM half of the .env, as chosen in this run. One flat record
    rather than a pile of locals, because the quick-check retry loop needs to
    hand a whole candidate configuration to `AgentConfig` and possibly
    discard it."""

    provider: str
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    openai_api_key: str = ""
    openai_model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    model_farm_api_key: str = ""
    model_farm_deployment: str = "askbosch-prod-farm-openai-gpt-4o-mini-2024-07-18"
    model_farm_model: str = "gpt-4o-mini"


def _read_existing_env(path: Path) -> dict[str, str]:
    """Best-effort parse of an existing `.env`, used only to pre-fill
    defaults on re-run -- not a general-purpose dotenv parser."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _prompt(label: str, *, default: str | None = None, secret: bool = False, required: bool = False) -> str:
    suffix = f" [{'*' * min(len(default), 8)}]" if secret and default else (f" [{default}]" if default else "")
    while True:
        raw = getpass.getpass(f"{label}{suffix}: ") if secret else input(f"{label}{suffix}: ")
        value = raw.strip() or (default or "")
        if value or not required:
            return value
        print("  This value is required.")


def _prompt_choice(label: str, options: list[str], *, default_index: int = 0) -> int:
    print(f"\n{label}")
    for i, opt in enumerate(options, start=1):
        marker = " (default)" if i - 1 == default_index else ""
        print(f"  {i}) {opt}{marker}")
    while True:
        raw = input(f"Choice [{default_index + 1}]: ").strip()
        if not raw:
            return default_index
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  Enter a number from 1 to {len(options)}.")


def _prompt_yes_no(label: str, *, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{label} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _choose_model_online(vendor: str, api_key: str, *, current: str) -> str:
    """Offer real model names for `vendor`, fetched with the key just
    entered. Falls back to typing a name when the catalog can't be reached --
    a corporate proxy blocking the vendor is a normal outcome here, and it
    must not be a dead end (the app itself may still reach the vendor through
    a different path, and the colleague may already know the name they want).
    """
    print("\nFetching available models...")
    try:
        models = model_catalog.list_models(vendor, api_key)
    except model_catalog.ModelCatalogError as exc:
        print(f"  Couldn't fetch the model list: {exc}.")
        print("  Enter the model name manually instead (e.g. from the vendor's docs).")
        return _prompt("Model name", default=current or None, required=True)

    shown = models[:_MODEL_MENU_LIMIT]
    labels = [*shown, "Other -- type a model name manually"]
    # Pre-select whatever's already configured, so re-running init to change
    # something else doesn't silently switch models.
    default_index = shown.index(current) if current in shown else 0
    choice = _prompt_choice(
        f"Which model? ({len(models)} available to this key"
        + (f", showing {len(shown)}" if len(models) > len(shown) else "")
        + ")",
        labels,
        default_index=default_index,
    )
    if choice == len(labels) - 1:
        return _prompt("Model name", default=current or None, required=True)
    return shown[choice]


def _collect_model_farm(settings: _LLMSettings) -> None:
    settings.model_farm_api_key = _prompt(
        "Model Farm API key", default=settings.model_farm_api_key, secret=True, required=True
    )
    labels = [label for label, _, _ in _MODEL_FARM_MODELS]
    _, deployment, model = _MODEL_FARM_MODELS[_prompt_choice("Which model?", labels)]
    if deployment is None:
        settings.model_farm_deployment = _prompt("Model Farm deployment name (URL path segment)", required=True)
        settings.model_farm_model = _prompt("Model name (request body field)", required=True)
    else:
        settings.model_farm_deployment, settings.model_farm_model = deployment, model


def _collect_personal(settings: _LLMSettings, vendor: str) -> None:
    label, key_url = next((lbl, url) for key, lbl, url in _PERSONAL_VENDORS if key == vendor)
    print(f"\nGet a {label} API key at: {key_url}")
    if vendor == GEMINI:
        settings.gemini_api_key = _prompt(f"{label} API key", default=settings.gemini_api_key, secret=True, required=True)
        settings.gemini_model = _choose_model_online(vendor, settings.gemini_api_key, current=settings.gemini_model)
    elif vendor == OPENAI:
        settings.openai_api_key = _prompt(f"{label} API key", default=settings.openai_api_key, secret=True, required=True)
        settings.openai_model = _choose_model_online(vendor, settings.openai_api_key, current=settings.openai_model)
    else:
        settings.anthropic_api_key = _prompt(f"{label} API key", default=settings.anthropic_api_key, secret=True, required=True)
        settings.anthropic_model = _choose_model_online(vendor, settings.anthropic_api_key, current=settings.anthropic_model)


def _quick_check_config(settings: _LLMSettings) -> AgentConfig:
    """Build a config carrying only what the quick check reads.

    The Splunk/routing/email fields are placeholders on purpose: `quick_check`
    goes through `build_llm_client`, which touches nothing but
    `llm_provider` and that provider's own key/model/timeout. Constructing
    this in memory is what lets the check run *before* anything is written to
    disk, so a failed attempt never leaves a broken `.env` behind.
    """
    return AgentConfig(
        llm_provider=settings.provider,
        splunk_base_url="",
        splunk_api_token="",
        splunk_index="",
        splunk_sourcetype="",
        splunk_verify_ssl=True,
        splunk_search_timeout_seconds=60,
        splunk_auth_header="",
        additional_routing_auth_header="",
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
        gemini_timeout_seconds=20,
        issue_report_email="",
        additional_routing_url="",
        additional_routing_api_token="",
        model_farm_api_key=settings.model_farm_api_key,
        model_farm_base_url="https://aoai-farm.bosch-temp.com/api",
        model_farm_deployment=settings.model_farm_deployment,
        model_farm_model=settings.model_farm_model,
        model_farm_timeout_seconds=20,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        openai_timeout_seconds=20,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_model=settings.anthropic_model,
        anthropic_timeout_seconds=20,
    )


def _configure_llm(existing: dict[str, str]) -> _LLMSettings:
    """Collect the LLM backend, then prove it works before returning.

    Loops on failure rather than warning and moving on: a wrong key or an
    unentitled model is the single most likely thing to go wrong in this
    setup, it's fully fixable right here, and the alternative is a colleague
    discovering it as an opaque "AI service unavailable" on their first real
    question.
    """
    provider_index = 0 if existing.get("LLM_PROVIDER", MODEL_FARM) == MODEL_FARM else 1
    backend = _prompt_choice(
        "--- LLM backend ---\nHow should the agent talk to an LLM?",
        ["Bosch Model Farm (internal gateway, Bosch-provisioned key)", "Personal API key / subscription"],
        default_index=provider_index,
    )

    settings = _LLMSettings(
        provider=MODEL_FARM,
        gemini_api_key=existing.get("GEMINI_API_KEY", ""),
        gemini_model=existing.get("GEMINI_MODEL", "gemini-flash-latest"),
        openai_api_key=existing.get("OPENAI_API_KEY", ""),
        openai_model=existing.get("OPENAI_MODEL", ""),
        anthropic_api_key=existing.get("ANTHROPIC_API_KEY", ""),
        anthropic_model=existing.get("ANTHROPIC_MODEL", ""),
        model_farm_api_key=existing.get("MODEL_FARM_API_KEY", ""),
        model_farm_deployment=existing.get("MODEL_FARM_DEPLOYMENT", "askbosch-prod-farm-openai-gpt-4o-mini-2024-07-18"),
        model_farm_model=existing.get("MODEL_FARM_MODEL", "gpt-4o-mini"),
    )

    vendor = MODEL_FARM
    if backend == 1:
        previous = existing.get("LLM_PROVIDER", "")
        vendor_keys = [key for key, _, _ in _PERSONAL_VENDORS]
        vendor_index = vendor_keys.index(previous) if previous in vendor_keys else 0
        chosen = _prompt_choice(
            "Which provider?",
            [label for _, label, _ in _PERSONAL_VENDORS],
            default_index=vendor_index,
        )
        vendor = vendor_keys[chosen]
    settings.provider = vendor

    while True:
        if vendor == MODEL_FARM:
            _collect_model_farm(settings)
        else:
            _collect_personal(settings, vendor)

        print("\nChecking that key and model actually work...")
        result = quick_check(_quick_check_config(settings))
        if result.ok:
            print(f"  OK -- the model replied: {result.detail[:80]}")
            return settings

        print(f"  Check failed: {result.detail}")
        if not _prompt_yes_no("Try again with a different key or model?", default=True):
            print("  Continuing anyway -- fix it later by re-running `packit-agent init`.")
            return settings


def _env_lines(settings: _LLMSettings, **fields: str) -> list[str]:
    return [
        "# Generated/updated by `packit-agent init` -- see README.md.",
        "",
        "# Splunk REST API, via the Bosch API gateway. Auth is a plain header",
        "# carrying the token (not Bearer, not Basic) -- named below.",
        f"SPLUNK_BASE_URL={fields['splunk_base_url']}",
        f"SPLUNK_AUTH_HEADER={fields['splunk_auth_header']}",
        f"SPLUNK_API_TOKEN={fields['splunk_api_token']}",
        f"SPLUNK_INDEX={fields['splunk_index']}",
        f"SPLUNK_SOURCETYPE={fields['splunk_sourcetype']}",
        "SPLUNK_VERIFY_SSL=true",
        "SPLUNK_SEARCH_TIMEOUT_SECONDS=60",
        "",
        "# Additional Routing plan API -- separate from Splunk, with its own",
        "# token and its own header name (\"KeyId\" -- note the casing differs",
        "# from Splunk's \"KeyID\" above; both are confirmed real).",
        f"ADDITIONAL_ROUTING_URL={fields['routing_url']}",
        f"ADDITIONAL_ROUTING_AUTH_HEADER={fields['routing_auth_header']}",
        f"ADDITIONAL_ROUTING_API_TOKEN={fields['routing_token']}",
        "",
        "# LLM backend -- \"model_farm\", or a personal key with \"gemini\" /",
        "# \"openai\" / \"anthropic\". Re-run `packit-agent init` to change.",
        f"LLM_PROVIDER={settings.provider}",
        "",
        "# Bosch Model Farm -- internal Azure-OpenAI-compatible LLM gateway.",
        f"MODEL_FARM_API_KEY={settings.model_farm_api_key}",
        "MODEL_FARM_BASE_URL=https://aoai-farm.bosch-temp.com/api",
        f"MODEL_FARM_DEPLOYMENT={settings.model_farm_deployment}",
        f"MODEL_FARM_MODEL={settings.model_farm_model}",
        "MODEL_FARM_TIMEOUT_SECONDS=20",
        "",
        "# Personal API keys -- each used only when LLM_PROVIDER names it.",
        f"GEMINI_API_KEY={settings.gemini_api_key}",
        f"GEMINI_MODEL={settings.gemini_model}",
        "GEMINI_TIMEOUT_SECONDS=20",
        f"OPENAI_API_KEY={settings.openai_api_key}",
        f"OPENAI_MODEL={settings.openai_model}",
        "OPENAI_TIMEOUT_SECONDS=20",
        f"ANTHROPIC_API_KEY={settings.anthropic_api_key}",
        f"ANTHROPIC_MODEL={settings.anthropic_model}",
        "ANTHROPIC_TIMEOUT_SECONDS=20",
        "",
        "# Corporate proxy (Bosch network laptops only -- leave blank off-network).",
        f"HTTP_PROXY={fields['http_proxy']}",
        f"HTTPS_PROXY={fields['http_proxy']}",
        "",
        "# Where \"Report Issue\" mailto: drafts are addressed.",
        f"ISSUE_REPORT_EMAIL={fields['issue_report_email']}",
        "",
    ]


def run_init() -> bool:
    """Run the full wizard and write `.env`. Returns whether the caller
    should go on to start the app (see `ui/cli.py`) -- False if the colleague
    declined, so that re-running init purely to change a setting doesn't
    force a server start."""
    existing = _read_existing_env(_ENV_PATH)
    print("PACKIT Operations Agent -- Setup\n" + "=" * 33)
    print(f"This writes {_ENV_PATH}. Existing values are shown as defaults -- press Enter to keep them.\n")

    # Everything here except the tokens is pre-filled with the confirmed real
    # value and rarely changes -- the intended interaction is Enter, Enter,
    # paste your token. The endpoint/header prompts exist so a gateway-side
    # change is an answer to a question rather than a code edit, not because
    # a colleague is expected to know them.
    print("--- Splunk (Replication Status search) ---")
    splunk_base_url = _prompt("Splunk base URL", default=existing.get("SPLUNK_BASE_URL", "https://ews-esz-emea.api.bosch.com/pdmi/splunk"))
    splunk_auth_header = _prompt("Splunk auth header name", default=existing.get("SPLUNK_AUTH_HEADER", "KeyID"))
    splunk_api_token = _prompt("Splunk API token", default=existing.get("SPLUNK_API_TOKEN", ""), secret=True, required=True)
    splunk_index = _prompt("Splunk index", default=existing.get("SPLUNK_INDEX", "pdbb"))
    splunk_sourcetype = _prompt("Splunk sourcetype", default=existing.get("SPLUNK_SOURCETYPE", "Native"))

    print("\n--- Additional Routing plan ---")
    routing_url = _prompt("Additional Routing URL", default=existing.get("ADDITIONAL_ROUTING_URL", "https://ews-esz-emea.api.bosch.com/services/P/ROUTINGPLAN"))
    # Note the casing: "KeyId" here vs. Splunk's "KeyID" above -- confirmed
    # real, not a typo in either place.
    routing_auth_header = _prompt("Additional Routing auth header name", default=existing.get("ADDITIONAL_ROUTING_AUTH_HEADER", "KeyId"))
    routing_token = _prompt("Additional Routing API token", default=existing.get("ADDITIONAL_ROUTING_API_TOKEN", ""), secret=True, required=True)

    settings = _configure_llm(existing)

    print("\n--- Network ---")
    on_bcn = _prompt_yes_no("On a Bosch network (BCN) laptop, behind the local Px proxy?", default=bool(existing.get("HTTP_PROXY")))
    http_proxy = existing.get("HTTP_PROXY", "http://127.0.0.1:3128") if on_bcn else ""

    print("\n--- Misc ---")
    issue_report_email = _prompt("Email for 'Report Issue' drafts", default=existing.get("ISSUE_REPORT_EMAIL", ""), required=True)

    lines = _env_lines(
        settings,
        splunk_base_url=splunk_base_url,
        splunk_auth_header=splunk_auth_header,
        splunk_api_token=splunk_api_token,
        splunk_index=splunk_index,
        splunk_sourcetype=splunk_sourcetype,
        routing_url=routing_url,
        routing_auth_header=routing_auth_header,
        routing_token=routing_token,
        http_proxy=http_proxy,
        issue_report_email=issue_report_email,
    )
    _ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {_ENV_PATH}.")

    return _prompt_yes_no("\nStart the PackIT Operations Agent now?", default=True)


if __name__ == "__main__":
    run_init()
