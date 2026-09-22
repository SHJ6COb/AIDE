"""Throwaway probe: which Mistral AI models are actually reachable through
Bosch's Model Farm gateway with the current MODEL_FARM_API_KEY.

Tests two endpoint shapes:
  1) Vertex AI publisher endpoint (rawPredict) for chat models
     mistral-small-2503 and codestral-2.
  2) OCR-capable models (mistral-ocr-2505 via the same publisher endpoint,
     mistral-document-ai-2512 via /providers/mistral/azure/ocr) using a
     deliberately invalid/minimal base64 "document" payload -- the goal is
     only to distinguish "reachable but content rejected" (proves access)
     from 401/403/404 (proves no access), not to get a real OCR result.

Not part of the pytest suite; safe to delete. Never prints the API key.
Does not modify app/, ui/, or .env.
"""

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

KEY = os.environ["MODEL_FARM_API_KEY"]
BASE_URL = os.environ.get("MODEL_FARM_BASE_URL", "https://aoai-farm.bosch-temp.com/api").rstrip("/")

HEADERS = {
    "Authorization": f"Bearer {KEY}",
    "genaiplatform-farm-subscription-key": KEY,
    "Content-Type": "application/json",
}

TINY_INVALID_PDF_DATA_URL = "data:application/pdf;base64,dGVzdA=="


def classify(status_code: int, body_text: str) -> str:
    """Classify an HTTP outcome into accessible / reachable-but-rejected / inaccessible."""
    if status_code == 200:
        return "ACCESSIBLE (200 OK)"
    if status_code in (401, 403):
        return f"INACCESSIBLE (auth error {status_code})"
    if status_code == 404:
        return f"INACCESSIBLE (not found {status_code})"
    if status_code == 400:
        lowered = body_text.lower()
        # A 400 that complains about the document/content itself (rather than
        # an unknown model/route) indicates the model endpoint IS reachable.
        content_hints = [
            "base64", "document", "pdf", "decode", "invalid document",
            "corrupt", "could not", "unable to", "content", "payload",
        ]
        model_not_found_hints = ["model not found", "unknown model", "does not exist", "not supported"]
        if any(h in lowered for h in model_not_found_hints):
            return f"INACCESSIBLE (400, model rejected: {body_text[:150]})"
        if any(h in lowered for h in content_hints):
            return "REACHABLE (400, content/document rejected -- model IS accessible)"
        return f"UNCLEAR (400): {body_text[:150]}"
    return f"UNCLEAR ({status_code}): {body_text[:150]}"


def probe(label: str, url: str, body: dict, retries: int = 2):
    resp = None
    last_exc = None
    for _ in range(retries):
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(url, headers=HEADERS, json=body)
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            resp = None
    if resp is None:
        result = {
            "model": label,
            "status": type(last_exc).__name__,
            "verdict": f"EXCEPTION: {last_exc}",
        }
        print(result, file=sys.stderr)
        return result

    body_text = resp.text or ""
    verdict = classify(resp.status_code, body_text)
    result = {"model": label, "status": str(resp.status_code), "verdict": verdict}
    print(f"=== {label} ===\nURL: {url}\nStatus: {resp.status_code}\nBody (first 300 chars): {body_text[:300]}\n", file=sys.stderr)
    return result


def main():
    results = []

    # 1) Chat models via Vertex publisher rawPredict
    for model_id in ["mistral-small-2503", "codestral-2"]:
        url = f"{BASE_URL}/google/v1/publishers/mistralai/models/{model_id}:rawPredict"
        body = {"model": model_id, "messages": [{"role": "user", "content": "Say Hello!"}]}
        results.append(probe(model_id, url, body))

    # 2a) mistral-ocr-2505 via the same publisher endpoint, invalid doc payload
    url_ocr = f"{BASE_URL}/google/v1/publishers/mistralai/models/mistral-ocr-2505:rawPredict"
    body_ocr = {
        "model": "mistral-ocr-2505",
        "document": {"type": "document_url", "document_url": TINY_INVALID_PDF_DATA_URL},
        "include_image_base64": False,
    }
    results.append(probe("mistral-ocr-2505", url_ocr, body_ocr))

    # 2b) mistral-document-ai-2512 via dedicated OCR provider endpoint
    url_docai = f"{BASE_URL}/providers/mistral/azure/ocr"
    body_docai = {
        "model": "mistral-document-ai-2512",
        "document": {"type": "document_url", "document_url": TINY_INVALID_PDF_DATA_URL},
        "include_image_base64": False,
    }
    results.append(probe("mistral-document-ai-2512", url_docai, body_docai))

    print("\n\n=== RESULTS TABLE ===")
    header = f"{'Model':<26} {'HTTP Status':<12} {'Verdict'}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['model']:<26} {r['status']:<12} {r['verdict']}")


if __name__ == "__main__":
    main()
