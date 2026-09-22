"""One-off live check: does searching for the exact `<d:BusinessStatus>...`
XML tag (instead of a bare word) eliminate the false-positive matches found
when bare-text-searching "SUCCESS"? See conversation history / ARCHITECTURE.md
Guardrails discussion. Not part of the pytest suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import httpx

from app.core.config import AgentConfig
from app.tools import splunk_client, splunk_xml_parser
from app.tools.transform import UnrecognizedPayloadShape, parse_hop

config = AgentConfig.from_env()
spl = f'search index={config.splunk_index} sourcetype={config.splunk_sourcetype} "<d:BusinessStatus>SUCCESS</d:BusinessStatus>" | head 200'
print("SPL:", spl)

with httpx.Client(verify=config.splunk_verify_ssl, trust_env=True, timeout=config.splunk_search_timeout_seconds) as client:
    sid = splunk_client._start_job(client, config, spl, "-3h", "now")
    splunk_client._poll_until_done(client, config, sid)
    page = splunk_client._fetch_results_page(client, config, sid, offset=0, count=200)
    splunk_client._delete_job(client, config, sid)

raw = splunk_xml_parser.parse_results(page)
print("total raw results:", len(raw))

status_counts: dict = {}
false_positives = 0
for r in raw:
    try:
        hop = parse_hop(r)
    except UnrecognizedPayloadShape:
        continue
    status_counts[hop.business_status] = status_counts.get(hop.business_status, 0) + 1
    if hop.business_status != "SUCCESS":
        false_positives += 1

print("status breakdown:", status_counts)
print("false positives:", false_positives)
