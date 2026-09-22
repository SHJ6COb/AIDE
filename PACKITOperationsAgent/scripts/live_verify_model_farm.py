"""Live verification of ModelFarmClient against the real Bosch Model Farm
gateway: a plain call, then a tool-calling call (the harness's actual
dependency). Not part of the pytest suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.core.config import AgentConfig
from app.core.llm_client import ModelFarmClient, Message, ToolSchema


def main() -> None:
    config = AgentConfig.from_env()
    client = ModelFarmClient(config)

    print("--- plain call ---")
    response = client.generate([Message(role="user", content="Say hello in exactly 3 words.")], tools=[], system_instruction="You are a helpful assistant.")
    print("text:", response.text)
    print("tool_calls:", response.tool_calls)

    print("\n--- tool-calling call ---")
    tool = ToolSchema(
        name="get_weather",
        description="Get the current weather for a city.",
        parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    )
    response2 = client.generate(
        [Message(role="user", content="What's the weather in Stuttgart?")],
        tools=[tool],
        system_instruction="Use the get_weather tool whenever the user asks about weather.",
    )
    print("text:", response2.text)
    print("tool_calls:", response2.tool_calls)


if __name__ == "__main__":
    main()
