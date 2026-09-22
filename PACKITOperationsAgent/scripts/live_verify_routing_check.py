"""Live end-to-end verification of the newly-wired Additional Routing tool
flowing through the full harness. Not part of the pytest suite.
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


def main() -> None:
    config = AgentConfig.from_env()
    llm = GeminiClient(config)
    store = Store()
    # 00000000040001498023 is real, known to be on SAPP990110 (R/3) -- asking
    # about SAPP1M0110 instead should trigger the routing check.
    query = "why isn't PS 00000000040001498023 showing up on SAPP1M0110 in the last 30 days?"
    answer = harness.run_query("t1", query, config=config, llm=llm, store=store)
    print("primary_records:", len(answer.primary_records))
    print("ANSWER:", answer.plain_language_answer)


if __name__ == "__main__":
    main()
