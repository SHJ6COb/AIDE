# PACKIT Operations Agent

A chat app that answers questions about **Packaging Specification data flow** — where a spec is in the PACKIT → PDMI → Target System pipeline, what an error actually means, and whether there's a documented fix.

Ask it things like:

> What's happening with PS 00000000040000054543?
>
> Why did the transfer to SAPP790110 fail?
>
> Is anything blocking PS 00000000040000908526 at plant 0780?

It reads live Splunk data and the internal Docupedia error catalog. It is **read-only** — it never retriggers a transfer, edits a record, or files a ticket. And it never invents a fix: if the error isn't in the catalog, it says so and points you at mServiceHub.

---

## Setup

You need **Python 3.11 or newer** and Git. You do *not* need Node.js — the web UI ships pre-built.

```bash
git clone <repo-url>
cd PACKITOperationsAgent
```

Create a virtual environment so this project's packages stay out of your global Python:

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

Install the app, then run the setup wizard:

```bash
pip install -e .
packit-agent init
```

The wizard walks you through everything and **starts the app when it finishes** — your browser opens at `http://127.0.0.1:8000`. That's it.

After the first time, just run:

```bash
packit-agent
```

> Re-run `packit-agent init` any time you need to change a key, switch models, or switch LLM providers. It pre-fills everything you entered last time — press Enter to keep a value.

---

## What the wizard asks you

### 1. Splunk

The Replication Status data comes from Splunk via the Bosch API gateway. **The only thing you need to supply is your Splunk API token** — the base URL, auth header name, index, and sourcetype are all pre-filled with the confirmed values and rarely change, so press Enter through them.

(They're asked at all so that if the gateway ever renames a header or moves an endpoint, that's an answer to a question rather than a code change. The auth is a plain header carrying the token — not Bearer, not Basic.)

### 2. Additional Routing plan

A separate API that answers "was this Target System even *supposed* to receive this transfer?" Same shape: URL and header name pre-filled, **you supply the token** — a different one from Splunk's.

> Watch the casing if you ever change these by hand: Splunk's header is `KeyID`, Additional Routing's is `KeyId`. Both are confirmed real; neither is a typo.

### 3. LLM backend

This is the interesting choice. Two paths:

**Bosch Model Farm** *(recommended)* — the internal Azure-OpenAI-compatible gateway. Uses a Bosch-provisioned subscription key, so no personal billing and no data leaving Bosch infrastructure. You'll be asked for your Model Farm key and then which model to use. The list marks which models are available on a **Developer-tier** subscription versus which need **Enterprise** — if you pick one you're not entitled to, the quick check below catches it immediately.

**Personal API key** — bring your own subscription from Google Gemini, OpenAI, or Anthropic. You pick the vendor, enter your key, and then the wizard **fetches the live model list from that vendor** using your key, so you're choosing from models that actually exist and that your key can actually reach. (Model names change constantly — a hardcoded list would be wrong within months.)

Either way, the wizard then runs a **quick check**: one tiny real call to the model you picked. If it fails, you get the actual reason — a bad key and a blocked proxy need completely different fixes — and it offers to loop back so you can try another key or model. Nothing is written to disk until you're past this.

### 4. Network

Say yes if you're on a Bosch (BCN) laptop behind the local proxy; the wizard fills in the proxy address for you. Say no if you're off-network.

### 5. Report Issue email

Where the app's "Report Issue" button addresses its `mailto:` drafts — the project owner's address.

Everything lands in a `.env` file in the project folder. **That file holds your API keys and is git-ignored — don't commit it or share it.**

---

## Troubleshooting

**`packit-agent: command not found`** — your virtual environment isn't active. Re-run the activate command from Setup.

**The quick check fails with a 401 or "invalid subscription key"** — the key is wrong, or (on Model Farm) the model you chose needs an Enterprise subscription you don't have. Pick `gpt-4o-mini`, which is available on Developer-tier subscriptions.

**The quick check fails with a proxy or connection error** — you're likely on/off the Bosch network in a way that doesn't match your answer to the Network question. Re-run `packit-agent init` and flip that answer.

**"Couldn't fetch the model list"** — the proxy is blocking the vendor's catalog endpoint. Not fatal: the wizard lets you type the model name in manually, and the app itself may still reach the vendor fine.

**The app starts but the page is blank, and the console says no frontend build was found** — you're missing `ui/frontend/dist/`. It's committed to the repo, so a clean `git pull` should restore it; otherwise see Developing below.

**"LLM_PROVIDER=... is selected but ..._API_KEY is empty"** — a hand-edited `.env`. Re-run `packit-agent init`.

---

## Developing

Run the tests:

```bash
pip install -e ".[dev]"
python -m pytest
```

The UI is React + Vite. It's committed **pre-built** (`ui/frontend/dist/`) so nobody needs Node just to run the app — but if you change the frontend, rebuild and commit the output alongside your source change:

```bash
cd ui/frontend
npm install
npm run build
```

For active frontend work, `npm run dev` gives you the usual Vite dev server; see [ADR-0003](docs/adr/0003-prebuilt-bundle-single-process-launch.md) for why the shipped path deliberately isn't two processes.

### Where things live

| Path | What |
|---|---|
| [`app/agents/packspec_status/knowledge/`](app/agents/packspec_status/knowledge/) | The domain knowledge — **start here**. One file per topic; every term (PS Group, Transfer, TOPICSTRING, Additional Routing) is defined once and marked confirmed-vs-assumed, with a provenance footer saying what it rests on. |
| [`CONTEXT.md`](CONTEXT.md) | The index to those topics — which file holds which term, and when each loads. Holds no definitions of its own, and a test enforces that. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the pieces fit: the LLM-agnostic harness, the one deterministic tool, the grounding rule, the guardrails. |
| [`docs/QUERY_FLOW.md`](docs/QUERY_FLOW.md) | File-and-line walkthrough of what happens between pressing Enter and seeing an answer. |
| [`docs/RESEARCH_PLAYBOOK.md`](docs/RESEARCH_PLAYBOOK.md) | The method behind every "confirmed live" claim in this repo. Read before investigating a new API or unconfirmed field. |
| `app/agents/` | The agents. Today: `packspec_status`. |
| `app/tools/` | Deterministic, unit-tested building blocks — Splunk client, transform, error catalog, routing plan. No LLM judgment inside any of them. |
| `app/core/` | The harness loop, LLM clients, config, storage. |
| `ui/` | CLI entrypoint, FastAPI server, setup wizard, React frontend. |
| `scripts/` | Live verification and QA scripts, run against real data — not part of the app. |

### Adding an LLM provider

Write one class satisfying the `LLMClient` Protocol in [`app/core/llm_client.py`](app/core/llm_client.py), register it in `_CLIENTS`, and add its key/model fields to `AgentConfig`. Nothing else in the codebase knows which provider is live. If the vendor has a model-list endpoint, add a lister to [`app/core/model_catalog.py`](app/core/model_catalog.py) and the setup wizard will offer live model names for it too.
