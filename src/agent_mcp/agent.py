from __future__ import annotations

import logging
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from google.genai import types
from mcp import StdioServerParameters

from agent_mcp.config import AppConfig, ServerConfig

logger = logging.getLogger(__name__)


async def _resolve_http_headers(
    server_config: ServerConfig,
    app_config: AppConfig,
) -> dict[str, str]:
    """Build HTTP headers for a streamable-HTTP MCP connection.

    If auth == "oauth", fetch a token via ensure_oauth_token (reuses oauth.py).
    Otherwise return the static headers from config.
    """
    if server_config.auth == "oauth":
        from agent_mcp.oauth import ensure_oauth_token

        token_dir = Path(app_config.token_dir)
        assert server_config.url is not None
        token = await ensure_oauth_token(
            server_config.name, server_config.url, token_dir
        )
        return {"Authorization": f"Bearer {token}"}
    return dict(server_config.headers)


async def _build_toolset(
    server_config: ServerConfig,
    app_config: AppConfig,
) -> McpToolset:
    """Create an McpToolset for the given server config."""
    if server_config.transport == "stdio":
        assert server_config.command is not None
        return McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=server_config.command,
                    args=server_config.args,
                    env=server_config.env or None,
                ),
            ),
        )
    elif server_config.transport == "http":
        assert server_config.url is not None
        headers = await _resolve_http_headers(server_config, app_config)
        return McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=server_config.url,
                headers=headers,
            ),
        )
    else:
        raise ValueError(f"Unknown transport: {server_config.transport}")


async def run_agent(
    server_config: ServerConfig,
    app_config: AppConfig,
    instruction: str,
) -> str:
    """Run a sub-agent loop against a downstream MCP server using Google ADK."""
    toolset = await _build_toolset(server_config, app_config)

    try:
        agent = LlmAgent(
            model=LiteLlm(model=app_config.model),
            name=server_config.name,
            instruction="You are a helpful assistant. Use the available tools to fulfill the user's request.",
            tools=[toolset],
        )

        session_service = InMemorySessionService()
        runner = Runner(
            agent=agent,
            app_name="agent-mcp",
            session_service=session_service,
        )

        session = await session_service.create_session(
            app_name="agent-mcp",
            user_id="agent-mcp",
        )

        content = types.Content(
            role="user",
            parts=[types.Part(text=instruction)],
        )

        logger.info(
            f"[{server_config.name}] Running instruction: {instruction[:100]}..."
        )

        final_text = ""
        async for event in runner.run_async(
            user_id="agent-mcp",
            session_id=session.id,
            new_message=content,
            run_config=RunConfig(max_llm_calls=app_config.max_llm_calls),
        ):
            if event.is_final_response():
                if event.content and event.content.parts:
                    final_text = "\n".join(
                        part.text for part in event.content.parts if part.text
                    )
                break

        logger.info(f"[{server_config.name}] Agent completed")
        return final_text

    except Exception as e:
        logger.exception(f"[{server_config.name}] Agent error")
        return f"[{server_config.name}] Error: {e}"
    finally:
        await toolset.close()
