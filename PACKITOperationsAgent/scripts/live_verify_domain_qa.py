"""Live verification of the new scope-expansion: genuine domain-knowledge
questions should be answered directly from the appended CONTEXT.md
glossary (no tool call), truly unrelated questions should still be
refused, and status-lookup questions should still call the tool as before.
Not part of the pytest suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.core.config import AgentConfig
from app.core.llm_client import GeminiClient, Message
from app.core import harness


class Store:
    def __init__(self):
        self.m = {}

    def get_history(self, cid):
        return list(self.m.get(cid, []))

    def append_message(self, cid, role, content):
        self.m.setdefault(cid, []).append(Message(role=role, content=content))


CASES = [
    ("domain-det-record", "What is a Determination Record?"),
    ("domain-poe-cockpit", "Why would POE show 'Cockpit Data Model Updated' instead of creating a Packaging Instruction?"),
    ("domain-not-covered", "What's the exact SLA in minutes for a Retrigger to fire?"),
    ("off-topic-weather", "What's the weather like today?"),
    ("status-lookup-still-works", "what's the status of PS 00000000040001498023?"),
]


def main() -> None:
    config = AgentConfig.from_env()
    llm = GeminiClient(config)

    for case_id, query in CASES:
        store = Store()
        called = []
        orig = harness.get_ps_status

        def spy(params, cfg, on_step=None, _orig=orig):
            called.append(params)
            return _orig(params, cfg, on_step=on_step)

        harness.get_ps_status = spy
        try:
            answer = harness.run_query(f"t-{case_id}", query, config=config, llm=llm, store=store)
            print(f"--- {case_id}: {query!r} ---")
            print("called tool?", bool(called))
            print("ANSWER:", answer.plain_language_answer)
            print()
        except Exception as e:
            print(f"--- {case_id}: {query!r} --- EXCEPTION: {type(e).__name__}: {e}")
            print()
        finally:
            harness.get_ps_status = orig


if __name__ == "__main__":
    main()
