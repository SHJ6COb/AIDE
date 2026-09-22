"""Stand-in Splunk + Additional Routing endpoints, served over real HTTP.

The app is not modified, monkey-patched, or mocked at the Python level for this
suite -- it makes its real four-call async Splunk flow and its real
`Request-Filter` routing call over the network, just at a localhost base URL.
That keeps `splunk_client.py` and `routing_plan.py` genuinely under test
(job lifecycle, pagination, the `<sid>` extraction, the sentinel check) rather
than stubbed out of the picture.

Every request is logged to `requests.jsonl`, so a scenario's answer can be
traced back to the exact SPL the app built for it -- which is how a
"hallucinated result" is told apart from "the search really did return that".
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response

from . import corpus, routing_fixture

RESULT_PAGE_SIZE = 200


class Recorder:
    """Append-only request log, safe to write from the server's threads."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("", encoding="utf-8")

    def record(self, entry: dict) -> None:
        entry["at"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")


def create_app(*, log_path: Path) -> FastAPI:
    app = FastAPI(title="PackIT regression fake backends")
    recorder = Recorder(log_path)
    events = corpus.load_events()
    jobs: dict[str, dict] = {}
    counter = {"n": 0}
    lock = threading.Lock()

    app.state.recorder = recorder
    app.state.event_count = len(events)

    @app.post("/pdmi/splunk/services/search/jobs")
    async def create_job(request: Request):
        form = await request.form()
        spl = str(form.get("search", ""))
        earliest = str(form.get("earliest_time", ""))
        latest = str(form.get("latest_time", "now"))
        with lock:
            counter["n"] += 1
            sid = f"{time.time():.6f}.{counter['n']}"
        try:
            matched = corpus.search(events, spl, earliest, latest)
            error = None
        except corpus.CorpusError as exc:
            # An SPL shape this emulator doesn't model: fail the job the way
            # Splunk would rather than silently returning zero rows, which
            # would masquerade as a legitimate "not found" answer.
            matched, error = [], str(exc)
        jobs[sid] = {"spl": spl, "earliest": earliest, "latest": latest, "matched": matched, "error": error}
        recorder.record(
            {
                "api": "splunk.create_job",
                "sid": sid,
                "spl": spl,
                "earliest": earliest,
                "latest": latest,
                "matched_count": len(matched),
                "emulator_error": error,
            }
        )
        return Response(
            content=f'<?xml version="1.0" encoding="UTF-8"?>\n<response><sid>{sid}</sid></response>',
            media_type="text/xml",
        )

    @app.get("/pdmi/splunk/services/search/jobs/{sid}")
    def job_status(sid: str):
        job = jobs.get(sid)
        if job is None:
            return Response(content="<response><messages/></response>", media_type="text/xml", status_code=404)
        if job["error"]:
            body = f'<entry><content><s:dict xmlns:s="http://dev.splunk.com/ns/rest"><s:key name="isFailed">1</s:key></s:dict></content></entry>'
        else:
            body = (
                '<entry><content><s:dict xmlns:s="http://dev.splunk.com/ns/rest">'
                '<s:key name="dispatchState">DONE</s:key>'
                f'<s:key name="eventCount">{len(job["matched"])}</s:key>'
                '<s:key name="isFailed">0</s:key>'
                "</s:dict></content></entry>"
            )
        recorder.record({"api": "splunk.job_status", "sid": sid, "failed": bool(job["error"])})
        return Response(content=f'<?xml version="1.0" encoding="UTF-8"?>\n<feed>{body}</feed>', media_type="text/xml")

    @app.get("/pdmi/splunk/services/search/v2/jobs/{sid}/results")
    def job_results(sid: str, count: int = RESULT_PAGE_SIZE, offset: int = 0):
        job = jobs.get(sid)
        if job is None:
            return Response(content="<results/>", media_type="text/xml", status_code=404)
        if count == 0 or count > RESULT_PAGE_SIZE:
            # The confirmed real gateway behaviour the client is built to avoid.
            recorder.record({"api": "splunk.results", "sid": sid, "blocked": True, "count": count})
            return Response(
                content='<soapenv:Fault xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
                "<faultstring>MessageBlocked</faultstring></soapenv:Fault>",
                media_type="text/xml",
            )
        page = job["matched"][offset : offset + count]
        recorder.record({"api": "splunk.results", "sid": sid, "offset": offset, "count": count, "returned": len(page)})
        return Response(content=corpus.to_results_xml(page), media_type="text/xml")

    @app.delete("/pdmi/splunk/services/search/jobs/{sid}")
    def delete_job(sid: str):
        jobs.pop(sid, None)
        recorder.record({"api": "splunk.delete_job", "sid": sid})
        return Response(content="<response/>", media_type="text/xml")

    @app.get("/services/P/ROUTINGPLAN")
    def routing_plan(request: Request):
        request_filter = request.headers.get("Request-Filter", "")
        status, body = routing_fixture.respond(request_filter)
        recorder.record(
            {
                "api": "routing.query",
                "request_filter": request_filter,
                "status": status,
                "body_preview": body[:200],
                "entry_count": None if not body.startswith("[") else len(json.loads(body)),
            }
        )
        media_type = "text/plain" if body == routing_fixture.NOT_REGISTERED_SENTINEL else "application/json"
        return Response(content=body, status_code=status, media_type=media_type)

    @app.get("/__meta")
    def meta():
        return {"events": len(events), "jobs_open": len(jobs)}

    return app
