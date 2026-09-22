"""Throwaway probe: which Anthropic Claude deployments are reachable
through Bosch's Model Farm gateway (Vertex-style rawPredict passthrough)
with the current MODEL_FARM_API_KEY.

Not part of the pytest suite. Does not modify app/, ui/, or .env.
Never prints the API key.
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["MODEL_FARM_API_KEY"]
BASE_URL = os.environ.get("MODEL_FARM_BASE_URL", "https://aoai-farm.bosch-temp.com/api").rstrip("/")

MODEL_IDS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5@20251101",
    "claude-opus-4-1@20250805",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5@20250929",
    "claude-sonnet-4@20250514",
    "claude-haiku-4-5@20251001",
    "claude-opus-5",
    "claude-3-5-haiku@20241022",
]

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "genaiplatform-farm-subscription-key": API_KEY,
    "Content-Type": "application/json",
}


def probe(model_id: str, retries: int = 3) -> tuple[str, str]:
    url = f"{BASE_URL}/google/v1/publishers/anthropic/models/{model_id}:rawPredict"
    body = {
        "anthropic_version": "vertex-2023-10-16",
        "messages": [{"role": "user", "content": "Say Hello!"}],
        "max_tokens": 50,
    }
    resp = None
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=HEADERS, json=body, timeout=30)
            break
        except requests.RequestException as exc:
            last_exc = exc
            resp = None
    if resp is None:
        return "EXC", f"{type(last_exc).__name__}: {last_exc}"

    status = str(resp.status_code)
    if resp.status_code == 200:
        return status, "OK"

    code = ""
    msg = ""
    try:
        payload = resp.json()
        if isinstance(payload, list) and payload:
            payload = payload[0]
        err = payload.get("error", payload) if isinstance(payload, dict) else {}
        if isinstance(err, dict):
            msg = str(err.get("message", ""))[:200]
            code = str(err.get("code", err.get("status", "")))
    except Exception:
        pass
    if not msg:
        msg = resp.text[:200].replace("\n", " ")

    return status, f"{code} {msg}".strip()


def main() -> None:
    results = []
    for model_id in MODEL_IDS:
        status, reason = probe(model_id)
        results.append((model_id, status, reason))
        print(f"{model_id:30s} {status:5s} {reason}", flush=True)

    ok_count = sum(1 for _, status, _ in results if status == "200")
    print(f"\n{ok_count} of {len(MODEL_IDS)} returned HTTP 200")


if __name__ == "__main__":
    sys.exit(main() or 0)
