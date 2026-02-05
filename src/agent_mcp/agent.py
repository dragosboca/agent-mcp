from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from agent_mcp.config import AppConfig, ServerConfig
from agent_mcp.mcp_client import ConnectionManager

logger = logging.getLogger(__name__)


def _mcp_tools_to_anthropic(tools: list[Any]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic API format."""
    result = []
    for tool in tools:
        result.append({
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        })
    return result


def _tool_result_to_text(result: Any) -> str:
    """Extract text from a CallToolResult."""
    parts = []
    for block in result.content:
        if hasattr(block, "text"):
            parts.append(block.text)
        else:
            parts.append(str(block))
    if result.isError:
        return f"[Tool Error] {' '.join(parts)}"
    return "\n".join(parts)


async def run_agent(
    server_config: ServerConfig,
    app_config: AppConfig,
    connection_manager: ConnectionManager,
    instruction: str,
) -> str:
    """Run a sub-agent loop against a downstream MCP server."""
    try:
        # Get tools from the downstream server
        tools = await connection_manager.list_tools(server_config)
        anthropic_tools = _mcp_tools_to_anthropic(tools)
        logger.info(
            f"[{server_config.name}] Loaded {len(anthropic_tools)} tools, "
            f"running instruction: {instruction[:100]}..."
        )

        client = anthropic.Anthropic()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": instruction},
        ]

        for iteration in range(app_config.max_iterations):
            logger.debug(f"[{server_config.name}] Iteration {iteration + 1}")

            response = client.messages.create(
                model=app_config.model,
                max_tokens=app_config.max_tokens,
                tools=anthropic_tools,
                messages=messages,
            )

            # Append assistant response
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(
                            f"[{server_config.name}] Calling tool: {block.name}"
                        )
                        logger.debug(
                            f"[{server_config.name}] Tool input: "
                            f"{json.dumps(block.input, default=str)[:500]}"
                        )
                        try:
                            result = await connection_manager.call_tool(
                                server_config, block.name, block.input
                            )
                            text = _tool_result_to_text(result)
                        except Exception as e:
                            logger.error(
                                f"[{server_config.name}] Tool call failed: {e}"
                            )
                            text = f"[Error calling tool {block.name}]: {e}"

                        logger.debug(
                            f"[{server_config.name}] Tool result: {text[:500]}"
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": text,
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                # end_turn or max_tokens — extract final text
                text_parts = []
                for block in response.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
                final = "\n".join(text_parts)
                logger.info(
                    f"[{server_config.name}] Agent completed after "
                    f"{iteration + 1} iteration(s)"
                )
                return final

        return f"[{server_config.name}] Agent reached max iterations ({app_config.max_iterations})"

    except Exception as e:
        logger.exception(f"[{server_config.name}] Agent error")
        return f"[{server_config.name}] Error: {e}"
