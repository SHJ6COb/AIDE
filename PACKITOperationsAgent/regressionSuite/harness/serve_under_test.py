"""Launch the real app and the frozen backends side by side, in one process.

Nothing about the app is stubbed here: `ui.server.create_app` is constructed
exactly as `packit-agent` constructs it, with the real `AgentConfig` and the
real configured LLM client. The only differences are three environment values
-- the two backend base URLs and a scratch database -- so that the data behind
every answer is frozen while every line of app code between the browser and the
LLM still runs for real.

Run directly:  python -m regressionSuite.harness.serve_under_test
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

APP_PORT = 8010
BACKEND_PORT = 8099
RUN_DIR = _PROJECT_ROOT / "regressionSuite" / ".run"


def configure_environment() -> None:
    """Point the app at the frozen backends without touching `.env`."""
    load_dotenv(_PROJECT_ROOT / ".env", override=True)
    os.environ["SPLUNK_BASE_URL"] = f"http://127.0.0.1:{BACKEND_PORT}/pdmi/splunk"
    os.environ["ADDITIONAL_ROUTING_URL"] = f"http://127.0.0.1:{BACKEND_PORT}/services/P/ROUTINGPLAN"
    os.environ["SPLUNK_VERIFY_SSL"] = "false"
    # Both clients use `trust_env=True`, so without this the corporate proxy
    # would swallow the localhost backend calls. The proxy variables themselves
    # must stay set -- the LLM call is a real outbound request that needs them.
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"


def build_servers(*, log_path: Path):
    from app.core.config import AgentConfig
    from app.core.llm_client import build_llm_client
    from app.core.storage import SqliteConversationStore
    from regressionSuite.harness import fake_backends
    from ui.server import create_app

    backend_app = fake_backends.create_app(log_path=log_path)

    config = AgentConfig.from_env()
    llm = build_llm_client(config)
    # A scratch database per run, so the suite never mixes into (or grows) the
    # developer's own packit_agent.db.
    store = SqliteConversationStore(RUN_DIR / "regression.db")
    app = create_app(config, llm, store)
    return backend_app, app, config


def serve(*, log_path: Path | None = None) -> tuple[threading.Thread, threading.Thread]:
    """Start both servers on daemon threads and return once they accept traffic."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log_path = log_path or (RUN_DIR / "requests.jsonl")
    backend_app, app, _ = build_servers(log_path=log_path)

    def run(target, port: int) -> None:
        uvicorn.run(target, host="127.0.0.1", port=port, log_level="warning")

    backend_thread = threading.Thread(target=run, args=(backend_app, BACKEND_PORT), daemon=True)
    app_thread = threading.Thread(target=run, args=(app, APP_PORT), daemon=True)
    backend_thread.start()
    app_thread.start()
    return backend_thread, app_thread


def wait_until_ready(timeout_s: float = 60.0) -> None:
    import time

    import httpx

    deadline = time.time() + timeout_s
    checks = [f"http://127.0.0.1:{BACKEND_PORT}/__meta", f"http://127.0.0.1:{APP_PORT}/api/conversations"]
    with httpx.Client(trust_env=False, timeout=5.0) as client:
        for url in checks:
            while time.time() < deadline:
                try:
                    if client.get(url).status_code < 500:
                        break
                except httpx.HTTPError:
                    time.sleep(0.3)
            else:
                raise TimeoutError(f"{url} never became ready")


if __name__ == "__main__":
    configure_environment()
    serve()
    wait_until_ready()
    print(f"app:      http://127.0.0.1:{APP_PORT}/")
    print(f"backends: http://127.0.0.1:{BACKEND_PORT}/__meta")
    threading.Event().wait()
