"""Throwaway probe: which OpenAI GPT/o-series deployments are reachable
through Bosch's Model Farm gateway with the current MODEL_FARM_API_KEY.

Not part of the pytest suite. Does not modify app/, ui/, or .env.
Never prints the API key.
"""

import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["MODEL_FARM_API_KEY"]
BASE_URL = os.environ.get("MODEL_FARM_BASE_URL", "https://aoai-farm.bosch-temp.com/api").rstrip("/")
API_VERSION = "2025-04-01-preview"

DEPLOYMENTS = [
    "gpt-5-2025-08-07",
    "gpt-5-mini-2025-08-07",
    "gpt-5-nano-2025-08-07",
    "gpt-5.2-2025-12-11",
    "gpt-5.4-2026-03-05",
    "gpt-5.4-mini-2026-03-17",
    "gpt-5.4-nano-2026-03-17",
    "gpt-5.5-2026-04-24",
    "gpt-5.6-sol-2026-07-09",
    "gpt-5.6-terra-2026-07-09",
    "gpt-5.6-luna-2026-07-09",
    "askbosch-prod-farm-openai-gpt-41-2025-04-14",
    "askbosch-prod-farm-openai-gpt-41-mini-2025-04-14",
    "askbosch-prod-farm-openai-gpt-41-nano-2025-04-14",
    "askbosch-prod-farm-openai-gpt-4o-2024-11-20",
    "askbosch-prod-farm-openai-gpt-4o-mini-2024-07-18",
    "askbosch-prod-farm-openai-o4-mini-2025-04-16",
    "o3-2025-04-16",
    "askbosch-prod-farm-openai-o3-mini-2025-01-31",  # catalog: DEPRECATED
    "askbosch-prod-farm-openai-o1-2024-12-17",  # catalog: DEPRECATED
]

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "genaiplatform-farm-subscription-key": API_KEY,
    "Content-Type": "application/json",
}


def probe(deployment: str, retries: int = 5) -> tuple[str, str]:
    url = f"{BASE_URL}/openai/deployments/{deployment}/chat/completions"
    body = {
        "model": deployment,
        "messages": [{"role": "user", "content": "Say Hello!"}],
    }
    resp = None
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=HEADERS, params={"api-version": API_VERSION}, json=body, timeout=30)
            break
        except requests.RequestException as exc:
            last_exc = exc
            resp = None
            time.sleep(1.5)
    if resp is None:
        return "EXC", f"{type(last_exc).__name__}: {last_exc}"

    status = str(resp.status_code)
    if resp.status_code == 200:
        return status, "OK"

    code = ""
    msg = ""
    try:
        payload = resp.json()
        err = payload.get("error", payload) if isinstance(payload, dict) else {}
        if isinstance(err, dict):
            msg = str(err.get("message", ""))[:200]
            code = str(err.get("code", ""))
    except Exception:
        pass
    if not msg:
        msg = resp.text[:200].replace("\n", " ")

    if resp.status_code == 400 and any(
        kw in msg.lower() for kw in ["unsupported", "not supported", "unrecognized", "temperature", "parameter"]
    ):
        return status, f"REACHABLE (rejected request shape): {code} {msg}"

    return status, f"{code} {msg}".strip()


def main() -> None:
    results = []
    for dep in DEPLOYMENTS:
        status, reason = probe(dep)
        results.append((dep, status, reason))
        print(f"{dep:55s} {status:5s} {reason}", flush=True)

    accessible = sum(
        1 for _, status, reason in results if status == "200" or reason.startswith("REACHABLE")
    )
    print(f"\n{accessible} of {len(DEPLOYMENTS)} accessible")


if __name__ == "__main__":
    sys.exit(main() or 0)
