"""Throwaway probe: which z.AI GLM models are actually reachable through
Bosch's Model Farm gateway with the current MODEL_FARM_API_KEY.

Uses the Vertex AI OpenAI-compatible endpoint (via the `openai` SDK):
  base_url = {MODEL_FARM_BASE_URL}/google/v1/endpoints/{deployment}/openapi

Never prints the API key. Not part of the pytest suite; safe to delete.
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

KEY = os.environ["MODEL_FARM_API_KEY"]
BASE_URL = os.environ.get("MODEL_FARM_BASE_URL", "https://aoai-farm.bosch-temp.com/api").rstrip("/")

HEADERS = {"genaiplatform-farm-subscription-key": KEY}

# (label, deployment, model_body)
CANDIDATES = [
    ("glm-5-maas", "glm-5-maas", "zai-org/glm-5-maas"),
    ("glm-4.7-maas", "glm-4.7-maas", "zai-org/glm-4.7-maas"),
]

results = []  # list of dicts: model, status, reason, success


def try_vertex_openai(label: str, deployment: str, model_body: str):
    client = OpenAI(
        api_key=KEY,
        base_url=f"{BASE_URL}/google/v1/endpoints/{deployment}/openapi",
        default_headers=HEADERS,
    )
    try:
        resp = client.chat.completions.create(
            model=model_body,
            messages=[{"role": "user", "content": "Say Hello!"}],
        )
        text = ""
        try:
            text = resp.choices[0].message.content or ""
        except Exception:
            pass
        ok = bool(text.strip())
        return {
            "model": label,
            "status": "200 OK" if ok else "200 (empty content)",
            "reason": "" if ok else "response had no text content",
            "success": ok,
        }
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        status_str = str(status) if status else type(e).__name__
        reason = str(e)
        if len(reason) > 200:
            reason = reason[:200] + "..."
        return {
            "model": label,
            "status": status_str,
            "reason": reason,
            "success": False,
        }


def main():
    for label, deployment, model_body in CANDIDATES:
        print(f"=== Trying {label} (deployment={deployment}, model={model_body}) ===", file=sys.stderr)
        r = try_vertex_openai(label, deployment, model_body)
        results.append(r)
        print(r, file=sys.stderr)

    print("\n\n=== RESULTS TABLE ===")
    header = f"{'Model':<16} {'Status':<10} {'Reason'}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['model']:<16} {r['status']:<10} {r['reason']}")

    success_count = sum(1 for r in results if r["success"])
    total_count = len(CANDIDATES)
    print(f"\nSUMMARY: {success_count} of {total_count} accessible")


if __name__ == "__main__":
    main()
