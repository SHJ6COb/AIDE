"""One-off live validation of get_ps_status against real Splunk data, cross-
checked against screenshots/results/*.png dashboard captures. Not part of
the pytest suite -- requires real credentials in .env and network access to
the Bosch gateway. Run manually: python scripts/live_validate_pipeline.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.agents.packspec_status.pipeline import get_ps_status
from app.core.config import AgentConfig
from app.core.domain import SearchParams, TimeRange

CASES = [
    ("00000000040000054543", "Business Error, SNR13 not found -- expect catalog match seq_nr=2"),
    ("00000000040000908526", "Business Error, Cockpit dependent object blocked -- expect dependent_objects populated, seq_nr=57"),
    ("00000000040001498023", "All Success (PT0/VITAA flow) -- expect no error records, no catalog matches"),
]


def main() -> None:
    config = AgentConfig.from_env()
    for ps_id, expectation in CASES:
        print(f"\n{'=' * 70}\nPS ID {ps_id}\nExpectation: {expectation}\n{'=' * 70}")
        params = SearchParams(ps_id=ps_id, time_range=TimeRange(earliest="-7d"))
        steps: list[str] = []
        result = get_ps_status(params, config, on_step=steps.append)
        print("steps:", steps)
        print(f"primary_records: {len(result.primary_records)}")
        for record in result.primary_records:
            print(
                f"  - message_type={record.message_type} target={record.target_system} "
                f"status={record.current_status} hops={len(record.hops)} "
                f"desc={record.current_description!r}"
            )
        print(f"dependent_objects: {result.dependent_objects}")
        if result.dependent_objects:
            print(f"  DIR records: {len(result.dependent_objects.document_info_records)}")
            print(f"  Cockpit records: {len(result.dependent_objects.cockpit_master_data)}")
        print(f"catalog_matches: {[(m.seq_nr, m.error_category) for m in result.catalog_matches]}")


if __name__ == "__main__":
    main()
