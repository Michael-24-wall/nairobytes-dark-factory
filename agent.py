import asyncio
import logging
import os

from dotenv import load_dotenv

from band import Agent, Emit, configure_logging
from band.adapters import OpencodeAdapter, OpencodeAdapterConfig
from band.config import load_agent_config


logger = logging.getLogger(__name__)


async def main():
    load_dotenv()
    configure_logging(root_level="INFO")

    # Load the BAND agent ID and API key from agent_config.yaml
    agent_id, api_key = load_agent_config("builder")

    # Connect BAND to the OpenCode server running locally
    adapter = OpencodeAdapter(
        config=OpencodeAdapterConfig(
            base_url="http://127.0.0.1:4096",
            directory=os.getcwd(),
            custom_section=(
                "You are the Nairobytes Builder agent. "
                "Implement assigned software tasks carefully, "
                "run relevant tests, investigate failures, "
                "and provide clear evidence of your work."
            ),
        ),
        emit={Emit.TOOL_CALLS, Emit.TASK_EVENTS},
    )

    # Connect the adapter to the BAND platform
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

    logger.info("Nairobytes Builder is running!")
    logger.info("BAND -> OpenCode connection ready.")

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())