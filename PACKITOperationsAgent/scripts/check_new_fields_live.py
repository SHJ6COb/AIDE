"""Live check of the new target_system/status fields and the minimum-
specificity guard, end to end through the real harness against real Gemini
+ real Splunk. Not part of the pytest suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.core.config import AgentConfig
from app.core.llm_client import GeminiClient, Message
from app.core import harness


class InMemoryStore:
    def __init__(self):
        self.messages: dict = {}

    def get_history(self, cid):
        return list(self.messages.get(cid, []))

    def append_message(self, cid, role, content):
        self.messages.setdefault(cid, []).append(Message(role=role, content=content))


CASES = [
    ("target-status", f"what failed transfers went to target system SAPP790110 in the last 7 hours?"),
    ("single-weak-field", "show me OE sales channel transfers"),
    ("plant-plus-status", "show me failed transfers for plant 0580 in the last 7 hours"),
]


def main() -> None:
    config = AgentConfig.from_env()
    llm = GeminiClient(config)

    for case_id, query in CASES:
        store = InMemoryStore()
        called = []
        orig = harness.get_ps_status

        def spy(params, cfg, on_step=None, _orig=orig):
            called.append(params)
            return _orig(params, cfg, on_step=on_step)

        harness.get_ps_status = spy
        try:
            answer = harness.run_query(f"live-{case_id}", query, config=config, llm=llm, store=store)
            print(f"--- {case_id}: {query!r} ---")
            print("called get_ps_status?", bool(called))
            if called:
                print("  params:", called[0])
                print("  primary_records found:", len(answer.primary_records))
            print("ANSWER:", answer.plain_language_answer)
            print()
        except Exception as e:
            print(f"--- {case_id}: {query!r} --- EXCEPTION: {e}")
            print()
        finally:
            harness.get_ps_status = orig


if __name__ == "__main__":
    main()
