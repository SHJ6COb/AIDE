"""Live investigation: pull real Splunk payloads across different Target
Systems to confirm how each one's success/status text differs (R/3 vs POE
vs S/4-EWM P1M). Not part of the pytest suite -- read-only Splunk queries.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.core.config import AgentConfig
from app.core.domain import SearchParams, MessageType, TimeRange
from app.tools import splunk_client, splunk_xml_parser
from app.tools.transform import group_transfers

TARGETS = ["SAPP1M0110", "SAPPOE0110", "SAPP990110", "SAPP790110", "SAPPQ1M0110"]


def dump_for_target(config: AgentConfig, target: str, days: int) -> None:
    params = SearchParams(
        target_system=target,
        message_type=MessageType.PACKAGING_SPECIFICATION,
        time_range=TimeRange(earliest=f"-{days}d"),
    )
    print(f"\n{'=' * 70}\nTARGET={target}  (last {days}d, PackITPackagingSpecification)\n{'=' * 70}")
    try:
        pages = splunk_client.search(config, params, max_pages=1)
    except Exception as e:
        print(f"  SEARCH FAILED: {type(e).__name__}: {e}")
        return
    raw_results = [r for page in pages for r in splunk_xml_parser.parse_results(page)]
    print(f"  raw hop count: {len(raw_results)}")
    records = group_transfers(raw_results)
    print(f"  transfer records: {len(records)}")
    seen_descriptions = set()
    for rec in records[:15]:
        desc = (rec.current_description or "").strip()
        key = (rec.target_system, rec.current_status, desc[:120])
        if key in seen_descriptions:
            continue
        seen_descriptions.add(key)
        print(f"  - target={rec.target_system} status={rec.current_status} msg_type={rec.message_type}")
        print(f"    desc: {desc[:300]!r}")


def main() -> None:
    config = AgentConfig.from_env()
    for target in TARGETS:
        dump_for_target(config, target, days=30)


if __name__ == "__main__":
    main()
