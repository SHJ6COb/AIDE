"""CLI entrypoint (`packit-agent`, see pyproject.toml): starts the single
FastAPI process (API + pre-built frontend bundle) and opens the default
browser. See ADR-0002 (single-user-per-process) and ADR-0003 (one process,
pre-built bundle, not two dev servers).

`packit-agent init` runs the interactive setup wizard instead (see
`ui/init_wizard.py`) -- everything else here is the "start the server" path.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

import uvicorn
from dotenv import load_dotenv

from app.core.config import AgentConfig
from app.core.llm_client import build_llm_client
from app.core.storage import SqliteConversationStore
from ui.server import FRONTEND_DIST, create_app

HOST = "127.0.0.1"
PORT = 8000


def _run_server() -> None:
    # override=True because `packit-agent init` can hand straight off to this
    # function in the same process (see `main`): whatever the wizard loaded
    # into os.environ while validating an earlier attempt must not win over
    # the .env it just finished writing.
    load_dotenv(override=True)
    config = AgentConfig.from_env()
    llm = build_llm_client(config)
    store = SqliteConversationStore()
    app = create_app(config, llm, store)

    url = f"http://{HOST}:{PORT}/"
    if not FRONTEND_DIST.exists():
        print(f"Note: no frontend build found at {FRONTEND_DIST} -- run `npm run build` in ui/frontend/ first.")
    else:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print(f"PackIT Operations Agent starting at {url}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(prog="packit-agent")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init", help="Interactive setup -- writes .env (Splunk, LLM backend, etc.)")
    # No subcommand -- e.g. bare `packit-agent` -- starts the server, same as
    # before this file gained subcommands. `parse_known_args` rather than
    # `parse_args` so uvicorn/other tooling invoking this entrypoint directly
    # doesn't break on unrecognized args.
    args, _ = parser.parse_known_args(sys.argv[1:])

    if args.command == "init":
        from ui.init_wizard import run_init

        # The wizard ends by asking whether to start the app; saying yes
        # hands straight off here, so a colleague's first run is one command
        # from a fresh clone to a browser tab. Saying no just exits -- see
        # `run_init`'s own docstring.
        if run_init():
            _run_server()
        else:
            print("Run `packit-agent` when you're ready to start the app.")
    else:
        _run_server()


if __name__ == "__main__":
    main()
