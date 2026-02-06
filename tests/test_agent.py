"""Unit tests for agent_mcp.agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_mcp.config import AppConfig, ServerConfig


def _stdio_config() -> ServerConfig:
    return ServerConfig(
        name="test-server",
        description="test",
        transport="stdio",
        command="echo",
        args=["hello"],
    )


def _http_config() -> ServerConfig:
    return ServerConfig(
        name="test-http",
        description="test http",
        transport="http",
        url="https://example.com/mcp",
        headers={"Authorization": "Bearer tok123"},
    )


def _app_config() -> AppConfig:
    return AppConfig()


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_returns_final_text_and_closes_toolset(self):
        """run_agent should return the final text from the ADK runner and close the toolset."""
        mock_toolset = MagicMock()
        mock_toolset.close = AsyncMock()

        # Mock the final event
        mock_part = MagicMock()
        mock_part.text = "Here is the result"
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = MagicMock()
        mock_event.content.parts = [mock_part]

        async def fake_run_async(**kwargs):
            yield mock_event

        mock_runner = MagicMock()
        mock_runner.run_async = fake_run_async

        mock_session = MagicMock()
        mock_session.id = "sess-1"

        mock_session_service = MagicMock()
        mock_session_service.create_session = AsyncMock(return_value=mock_session)

        with (
            patch("agent_mcp.agent._build_toolset", new_callable=AsyncMock, return_value=mock_toolset),
            patch("agent_mcp.agent.LlmAgent"),
            patch("agent_mcp.agent.Runner", return_value=mock_runner),
            patch("agent_mcp.agent.InMemorySessionService", return_value=mock_session_service),
        ):
            from agent_mcp.agent import run_agent

            result = await run_agent(_stdio_config(), _app_config(), "Do something")

        assert result == "Here is the result"
        mock_toolset.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_closes_toolset_on_error(self):
        """Toolset should be closed even when the runner raises."""
        mock_toolset = MagicMock()
        mock_toolset.close = AsyncMock()

        with (
            patch("agent_mcp.agent._build_toolset", new_callable=AsyncMock, return_value=mock_toolset),
            patch("agent_mcp.agent.LlmAgent", side_effect=RuntimeError("boom")),
        ):
            from agent_mcp.agent import run_agent

            result = await run_agent(_stdio_config(), _app_config(), "Do something")

        assert "Error" in result
        mock_toolset.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_string(self):
        """If the final event has no content parts, return empty string."""
        mock_toolset = MagicMock()
        mock_toolset.close = AsyncMock()

        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_event.content = None

        async def fake_run_async(**kwargs):
            yield mock_event

        mock_runner = MagicMock()
        mock_runner.run_async = fake_run_async

        mock_session = MagicMock()
        mock_session.id = "sess-1"

        mock_session_service = MagicMock()
        mock_session_service.create_session = AsyncMock(return_value=mock_session)

        with (
            patch("agent_mcp.agent._build_toolset", new_callable=AsyncMock, return_value=mock_toolset),
            patch("agent_mcp.agent.LlmAgent"),
            patch("agent_mcp.agent.Runner", return_value=mock_runner),
            patch("agent_mcp.agent.InMemorySessionService", return_value=mock_session_service),
        ):
            from agent_mcp.agent import run_agent

            result = await run_agent(_stdio_config(), _app_config(), "Do something")

        assert result == ""
        mock_toolset.close.assert_awaited_once()


class TestBuildToolset:
    @pytest.mark.asyncio
    async def test_stdio_transport(self):
        """_build_toolset creates McpToolset with StdioConnectionParams for stdio transport."""
        with patch("agent_mcp.agent.McpToolset") as MockToolset:
            from agent_mcp.agent import _build_toolset

            await _build_toolset(_stdio_config(), _app_config())

            MockToolset.assert_called_once()
            call_kwargs = MockToolset.call_args[1]
            assert "connection_params" in call_kwargs

    @pytest.mark.asyncio
    async def test_http_transport(self):
        """_build_toolset creates McpToolset with StreamableHTTPConnectionParams for http transport."""
        with (
            patch("agent_mcp.agent.McpToolset") as MockToolset,
            patch("agent_mcp.agent.StreamableHTTPConnectionParams") as MockParams,
        ):
            from agent_mcp.agent import _build_toolset

            await _build_toolset(_http_config(), _app_config())

            MockParams.assert_called_once_with(
                url="https://example.com/mcp",
                headers={"Authorization": "Bearer tok123"},
            )
            MockToolset.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_transport_raises(self):
        """_build_toolset raises ValueError for unknown transport."""
        from agent_mcp.agent import _build_toolset

        config = ServerConfig(name="bad", description="bad", transport="websocket")
        with pytest.raises(ValueError, match="Unknown transport"):
            await _build_toolset(config, _app_config())

    @pytest.mark.asyncio
    async def test_http_oauth_resolves_headers(self):
        """_build_toolset with auth=oauth calls ensure_oauth_token."""
        oauth_config = ServerConfig(
            name="oauth-server",
            description="test",
            transport="http",
            url="https://example.com/mcp",
            auth="oauth",
        )
        with (
            patch("agent_mcp.agent.McpToolset") as MockToolset,
            patch("agent_mcp.agent.StreamableHTTPConnectionParams") as MockParams,
            patch(
                "agent_mcp.oauth.ensure_oauth_token",
                new_callable=AsyncMock,
                return_value="oauth_tok",
            ),
        ):
            from agent_mcp.agent import _build_toolset

            await _build_toolset(oauth_config, _app_config())

            MockParams.assert_called_once_with(
                url="https://example.com/mcp",
                headers={"Authorization": "Bearer oauth_tok"},
            )
