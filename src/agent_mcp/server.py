from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agent_mcp.agent import run_agent
from agent_mcp.config import AppConfig, ServerConfig, load_config


def _setup_logging(debug: bool) -> None:
    """Configure logging. With --debug, log DEBUG to ~/.agent-mcp/agent-mcp.log."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Always log INFO+ to stderr (stdout is reserved for MCP JSON-RPC)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    )
    root.addHandler(stderr_handler)

    if debug:
        log_dir = Path.home() / ".agent-mcp"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "agent-mcp.log"
        file_handler = logging.FileHandler(log_file, mode="w")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        root.addHandler(file_handler)
        print(f"Debug logging to {log_file}", file=sys.stderr)


logger = logging.getLogger(__name__)


def _make_handler(
    server_config: ServerConfig,
    app_config: AppConfig,
):
    """Create a tool handler closure for a given server config."""
    async def handler(instruction: str) -> str:
        logger.debug(f"[{server_config.name}] Handler called: {instruction[:200]}")
        try:
            result = await run_agent(
                server_config,
                app_config,
                instruction,
            )
            logger.debug(f"[{server_config.name}] Handler done, result length={len(result)}")
            return result
        except Exception:
            logger.exception(f"[{server_config.name}] Handler crashed")
            raise
    return handler


def _reauth(server_names: list[str], token_dir: Path) -> None:
    """Delete cached OAuth tokens for the given servers and exit."""
    if not server_names:
        # List all cached tokens
        if token_dir.exists():
            files = sorted(token_dir.glob("*.json"))
            if files:
                print("Cached OAuth tokens:")
                for f in files:
                    print(f"  {f.stem}")
            else:
                print("No cached OAuth tokens.")
        else:
            print("No cached OAuth tokens.")
        return

    for name in server_names:
        token_file = token_dir / f"{name}.json"
        if token_file.exists():
            token_file.unlink()
            print(f"Cleared OAuth tokens for '{name}'.")
        else:
            print(f"No cached tokens for '{name}'.")


def main() -> None:
    debug = "--debug" in sys.argv
    if debug:
        sys.argv.remove("--debug")

    _setup_logging(debug)

    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    config = load_config(str(config_path))

    # Handle --reauth before starting the MCP server
    if len(sys.argv) >= 2 and sys.argv[1] == "--reauth":
        _reauth(sys.argv[2:], Path(config.token_dir))
        return

    @asynccontextmanager
    async def managed_lifespan(_server: FastMCP) -> AsyncIterator[None]:
        logger.info(
            f"agent-mcp started with {len(config.servers)} server(s): "
            f"{[s.name for s in config.servers]}"
        )
        yield None

    mcp = FastMCP("agent-mcp", lifespan=managed_lifespan)

    # Register a tool for each downstream server
    for server_config in config.servers:
        handler = _make_handler(server_config, config)
        mcp.add_tool(
            handler,
            name=server_config.name,
            description=server_config.description,
        )
        logger.info(f"Registered tool: {server_config.name}")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
