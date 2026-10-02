import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from band import Agent, Emit, configure_logging
from band.adapters import OpencodeAdapter, OpencodeAdapterConfig
from band.config import load_agent_config


logger = logging.getLogger(__name__)

ROLES = ("architect", "builder", "breaker", "verifier")

PROVIDER_ID = "opencode"
DEFAULT_MODEL_ID = "mimo-v2.6-flash-free"

# Optional per-role model overrides.
# Example:
# MODEL_BY_ROLE = {
#     "architect": "mimo-v2.6-flash-free",
#     "builder": "big-pickle",
# }
MODEL_BY_ROLE = {}


def load_mandate(role: str) -> str:
    base_dir = Path(__file__).parent

    mandate_path = base_dir / "factory" / role / "mandate.md"
    protocol_path = base_dir / "factory" / "protocol.md"

    mandate = mandate_path.read_text(encoding="utf-8")
    protocol = protocol_path.read_text(encoding="utf-8")

    return mandate + "\n\n" + protocol


async def main(role: str):
    load_dotenv()
    configure_logging(root_level="INFO")

    agent_id, api_key = load_agent_config(role)

    model_id = MODEL_BY_ROLE.get(
        role,
        DEFAULT_MODEL_ID,
    )

    adapter = OpencodeAdapter(
        config=OpencodeAdapterConfig(
        base_url="http://127.0.0.1:4097",              directory=os.getcwd(),

            provider_id=PROVIDER_ID,
            model_id=model_id,

            approval_mode="auto_accept",

            custom_section=load_mandate(role),
        ),
        emit={
            Emit.TOOL_CALLS,
            Emit.TASK_EVENTS,
        },
    )

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv(
            "BAND_WS_URL",
            "wss://app.band.ai/api/v1/socket/websocket",
        ),
        rest_url=os.getenv(
            "BAND_REST_URL",
            "https://app.band.ai",
        ),
    )

    logger.info(
        "Starting factory role=%s model=%s/%s",
        role,
        PROVIDER_ID,
        model_id,
    )

    await agent.run()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ROLES:
        print(
            "usage: python agent.py "
            "<" + "|".join(ROLES) + ">"
        )
        sys.exit(2)

    asyncio.run(main(sys.argv[1]))