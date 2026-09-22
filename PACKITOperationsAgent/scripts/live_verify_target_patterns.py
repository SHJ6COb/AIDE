"""Live end-to-end verification of the target_system fix + the new
skill.md guidance, through the real harness (real Gemini + real Splunk).
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


class InMemoryStore:
    def __init__(self):
        self.messages: dict = {}

    def get_history(self, cid):
        return list(self.messages.get(cid, []))

    def append_message(self, cid, role, content):
        self.messages.setdefault(cid, []).append(Message(role=role, content=content))


CASES = [
    ("poe-known-ps", "what's the status of PS 00000000040001501942 on target system SAPPOE0110?"),
    ("p1m-target", "show me PackITPackagingSpecification transfers to SAPP1M0110 in the last 30 days"),
    ("unexpected-target", "why isn't PS 00000000040001498023 showing up on SAPP1M0110?"),
]


def main() -> None:
    config = AgentConfig.from_env()
    llm = GeminiClient(config)

    for case_id, query in CASES:
        store = InMemoryStore()
        try:
            answer = harness.run_query(f"live-{case_id}", query, config=config, llm=llm, store=store)
            print(f"--- {case_id}: {query!r} ---")
            print("primary_records found:", len(answer.primary_records))
            print("ANSWER:", answer.plain_language_answer)
            print()
        except Exception as e:
            print(f"--- {case_id}: {query!r} --- EXCEPTION: {type(e).__name__}: {e}")
            print()


if __name__ == "__main__":
    main()
