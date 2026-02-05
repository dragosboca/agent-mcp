from __future__ import annotations

import logging
import sys
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from agent_mcp.config import ServerConfig

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages lazy, persistent connections to downstream MCP servers."""

    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}

    async def _connect_stdio(self, config: ServerConfig) -> ClientSession:
        assert config.command is not None
        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env or None,
        )
        read, write = await self._exit_stack.enter_async_context(
            stdio_client(params, errlog=sys.stderr)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        return session

    async def _connect_http(self, config: ServerConfig) -> ClientSession:
        assert config.url is not None
        client = httpx.AsyncClient(headers=config.headers)
        await self._exit_stack.enter_async_context(client)
        read, write, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(config.url, http_client=client)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        return session

    async def connect(self, config: ServerConfig) -> ClientSession:
        """Lazily connect to a server. Returns cached session if already connected."""
        if config.name in self._sessions:
            return self._sessions[config.name]

        logger.info(f"Connecting to {config.name} ({config.transport})...")
        if config.transport == "stdio":
            session = await self._connect_stdio(config)
        elif config.transport == "http":
            session = await self._connect_http(config)
        else:
            raise ValueError(f"Unknown transport: {config.transport}")

        self._sessions[config.name] = session
        logger.info(f"Connected to {config.name}")
        return session

    async def list_tools(self, config: ServerConfig) -> list[Any]:
        """List tools from a downstream server."""
        session = await self.connect(config)
        result = await session.list_tools()
        return list(result.tools)

    async def call_tool(self, config: ServerConfig, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool on a downstream server."""
        session = await self.connect(config)
        result = await session.call_tool(name, arguments)
        return result

    async def cleanup(self) -> None:
        """Close all connections."""
        logger.info("Closing all MCP connections...")
        await self._exit_stack.aclose()
        self._sessions.clear()
