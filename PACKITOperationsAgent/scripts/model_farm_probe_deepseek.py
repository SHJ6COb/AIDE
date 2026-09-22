"""Throwaway probe: which DeepSeek models are reachable through Bosch's
Model Farm gateway with the current MODEL_FARM_API_KEY?

Tests two endpoint families:
  1) Azure OpenAI-compatible chat/completions, for two candidate deployment
     names.
  2) Vertex AI OpenAI-compatible endpoint (via the `openai` SDK) for
     deepseek-r1-0528-maas.

Never prints the API key. Not part of the app; safe to delete after use.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ["MODEL_FARM_BASE_URL"].rstrip("/")
API_KEY = os.environ["MODEL_FARM_API_KEY"]

SUB_KEY_HEADER = "genaiplatform-farm-subscription-key"

results: list[dict] = []


def record(model: str, family: str, status: str, reason: str = "") -> None:
    results.append({"model": model, "family": family, "status": status, "reason": reason})


def probe_azure(deployment_name: str) -> None:
    url = f"{BASE_URL}/openai/deployments/{deployment_name}/chat/completions"
    params = {"api-version": "2025-04-01-preview"}
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        SUB_KEY_HEADER: API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "model": deployment_name,
        "messages": [{"role": "user", "content": "Say Hello!"}],
    }
    try:
        resp = httpx.post(url, params=params, headers=headers, json=body, timeout=30.0)
        if resp.status_code == 200:
            record(deployment_name, "Azure OpenAI", "200 OK")
        else:
            reason = ""
            try:
                data = resp.json()
                err = data.get("error", data)
                reason = (err.get("message") if isinstance(err, dict) else str(err)) or resp.text[:200]
            except Exception:
                reason = resp.text[:200]
            record(deployment_name, "Azure OpenAI", str(resp.status_code), reason)
    except httpx.HTTPError as exc:
        record(deployment_name, "Azure OpenAI", "EXCEPTION", f"{type(exc).__name__}: {exc}")


def probe_vertex() -> None:
    from openai import OpenAI, APIStatusError

    model_id = "deepseek-ai/deepseek-r1-0528-maas"
    client = OpenAI(
        api_key=API_KEY,
        base_url=f"{BASE_URL}/google/v1/endpoints/deepseek-r1-0528-maas/openapi",
        default_headers={
            "genaiplatform-farm-google-location": "us-central1",
            SUB_KEY_HEADER: API_KEY,
        },
    )
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "Say Hello!"}],
        )
        if resp.choices:
            record(model_id, "Vertex AI (openai SDK)", "200 OK")
        else:
            record(model_id, "Vertex AI (openai SDK)", "200 OK (no choices)", "empty choices list")
    except APIStatusError as exc:
        reason = ""
        try:
            body = exc.response.json()
            err = body.get("error", body)
            reason = (err.get("message") if isinstance(err, dict) else str(err)) or exc.response.text[:200]
        except Exception:
            reason = str(exc)[:200]
        record(model_id, "Vertex AI (openai SDK)", str(exc.status_code), reason)
    except Exception as exc:
        record(model_id, "Vertex AI (openai SDK)", "EXCEPTION", f"{type(exc).__name__}: {exc}")


def main() -> None:
    probe_azure("deepseek-v4-pro-2026-04-23")
    probe_azure("deepseek-v4-flash-2026-04-23")
    probe_vertex()

    print(f"\n{'Model':<35} {'Endpoint family':<24} {'Status':<12} Reason")
    print("-" * 110)
    accessible = 0
    for r in results:
        if r["status"] == "200 OK":
            accessible += 1
        print(f"{r['model']:<35} {r['family']:<24} {r['status']:<12} {r['reason']}")

    print(f"\n{accessible} of {len(results)} accessible")


if __name__ == "__main__":
    main()
