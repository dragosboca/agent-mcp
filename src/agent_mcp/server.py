from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agent_mcp.agent import run_agent
from agent_mcp.config import AppConfig, ServerConfig, load_config
from agent_mcp.mcp_client import ConnectionManager

# Log to stderr so stdout stays clean for MCP JSON-RPC
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _make_handler(
    server_config: ServerConfig,
    app_config: AppConfig,
    connection_manager: ConnectionManager,
):
    """Create a tool handler closure for a given server config."""
    async def handler(instruction: str) -> str:
        return await run_agent(
            server_config,
            app_config,
            connection_manager,
            instruction,
        )
    return handler


def main() -> None:
    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    config = load_config(str(config_path))
    connection_manager = ConnectionManager()

    @asynccontextmanager
    async def managed_lifespan(_server: FastMCP) -> AsyncIterator[None]:
        logger.info(
            f"agent-mcp started with {len(config.servers)} server(s): "
            f"{[s.name for s in config.servers]}"
        )
        try:
            yield None
        finally:
            await connection_manager.cleanup()

    mcp = FastMCP("agent-mcp", lifespan=managed_lifespan)

    # Register a tool for each downstream server
    for server_config in config.servers:
        handler = _make_handler(server_config, config, connection_manager)
        mcp.add_tool(
            handler,
            name=server_config.name,
            description=server_config.description,
        )
        logger.info(f"Registered tool: {server_config.name}")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
