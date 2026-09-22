"""Throwaway probe: which Google Gemini models are actually reachable through
Bosch's Model Farm gateway with the current MODEL_FARM_API_KEY.

Tries endpoint family A (Azure-OpenAI-compatible, via `openai` SDK) for each
candidate model/deployment. For any model that fails via A, falls back to
endpoint family B (Vertex publisher endpoint, raw HTTPS via httpx).

Never prints the API key. Not part of the pytest suite; safe to delete.
"""

import os
import sys

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

KEY = os.environ["MODEL_FARM_API_KEY"]
BASE_URL = os.environ.get("MODEL_FARM_BASE_URL", "https://aoai-farm.bosch-temp.com/api").rstrip("/")

HEADERS = {"genaiplatform-farm-subscription-key": KEY}

# (label, deployment, model_body)
CANDIDATES = [
    ("gemini-2.5-flash", "google-gemini-2-5-flash", "gemini-2.5-flash"),
    ("gemini-3.1-flash-lite", "google-gemini-3-1-flash-lite", "gemini-3.1-flash-lite"),
    ("gemini-3.5-flash", "google-gemini-3-5-flash", "gemini-3.5-flash"),
    ("gemini-2.5-pro", "google-gemini-2-5-pro", "gemini-2.5-pro"),
    ("gemini-2.5-flash-lite", "google-gemini-2-5-flash-lite", "gemini-2.5-flash-lite"),
    ("gemini-2.0-flash-lite", "google-gemini-2-0-flash-lite", "gemini-2.0-flash-lite"),
]

# extra deployment-name variants to try for 3.5-flash if the primary 404s
FLASH_35_VARIANTS = [
    ("google-gemini-3.5-flash", "gemini-3.5-flash"),
    ("google-gemini-3-5-flash-001", "gemini-3.5-flash"),
    ("google-gemini-3-5-flash-latest", "gemini-3.5-flash"),
]

results = []  # list of dicts: model, family, status, reason


def try_family_a(label: str, deployment: str, model_body: str):
    client = OpenAI(
        api_key=KEY,
        base_url=f"{BASE_URL}/openai/deployments/{deployment}",
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
            "family": "A (deployment=" + deployment + ")",
            "status": "200 OK" if ok else "200 (empty content)",
            "reason": "" if ok else "response had no text content",
            "success": ok,
        }
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        status_str = str(status) if status else type(e).__name__
        reason = str(e)
        # trim overly long reasons
        if len(reason) > 200:
            reason = reason[:200] + "..."
        return {
            "model": label,
            "family": "A (deployment=" + deployment + ")",
            "status": status_str,
            "reason": reason,
            "success": False,
        }


def try_family_b(label: str, model_id: str):
    url = f"{BASE_URL}/google/v1/publishers/google/models/{model_id}:generateContent"
    headers = {
        "Authorization": f"Bearer {KEY}",
        "genaiplatform-farm-subscription-key": KEY,
        "Content-Type": "application/json",
    }
    body = {"contents": [{"role": "user", "parts": [{"text": "Say Hello!"}]}]}
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=headers, json=body)
        ok = resp.status_code == 200
        reason = ""
        if not ok:
            reason = resp.text[:200]
        return {
            "model": label,
            "family": "B (publisher, model=" + model_id + ")",
            "status": str(resp.status_code),
            "reason": reason,
            "success": ok,
        }
    except Exception as e:
        return {
            "model": label,
            "family": "B (publisher, model=" + model_id + ")",
            "status": type(e).__name__,
            "reason": str(e)[:200],
            "success": False,
        }


def main():
    # sanity check first
    print("=== Sanity check: gemini-2.5-flash via family A ===", file=sys.stderr)
    sanity = try_family_a(*CANDIDATES[0])
    results.append(sanity)
    print(sanity, file=sys.stderr)
    if not sanity["success"]:
        print("WARNING: sanity check failed -- auth/network may be broken. Continuing anyway.", file=sys.stderr)

    for label, deployment, model_body in CANDIDATES[1:]:
        print(f"=== Trying {label} via family A ===", file=sys.stderr)
        r = try_family_a(label, deployment, model_body)
        results.append(r)
        print(r, file=sys.stderr)

        if not r["success"] and label == "gemini-3.5-flash":
            for variant_dep, variant_model in FLASH_35_VARIANTS:
                print(f"=== Trying {label} variant deployment={variant_dep} via family A ===", file=sys.stderr)
                rv = try_family_a(label + " (variant)", variant_dep, variant_model)
                results.append(rv)
                print(rv, file=sys.stderr)
                if rv["success"]:
                    break

        if not r["success"] and label in ("gemini-3.5-flash", "gemini-3.1-flash-lite"):
            print(f"=== Falling back to family B for {label} ===", file=sys.stderr)
            rb = try_family_b(label, model_body)
            results.append(rb)
            print(rb, file=sys.stderr)

    # print final table
    print("\n\n=== RESULTS TABLE ===")
    header = f"{'Model':<28} {'Family':<40} {'Status':<10} {'Reason'}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['model']:<28} {r['family']:<40} {r['status']:<10} {r['reason']}")

    success_count = len({r["model"].replace(" (variant)", "") for r in results if r["success"]})
    total_count = len(CANDIDATES)
    print(f"\nSUMMARY: {success_count} of {total_count} accessible")


if __name__ == "__main__":
    main()
