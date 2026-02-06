"""End-to-end tests for OAuth authentication against real MCP servers.

These tests require a valid cached OAuth token in ~/.agent-mcp/tokens/.
They hit the real Todoist MCP server and verify the full flow works.

Skip with: pytest -m "not e2e"
Run only:  pytest -m e2e
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_mcp.config import DEFAULT_TOKEN_DIR
from agent_mcp.oauth import FileTokenStorage, ensure_oauth_token

TODOIST_URL = "https://ai.todoist.net/mcp"
TOKEN_DIR = Path(DEFAULT_TOKEN_DIR)
TOKEN_FILE = TOKEN_DIR / "todoist.json"


def _has_cached_token() -> bool:
    if not TOKEN_FILE.exists():
        return False
    try:
        data = json.loads(TOKEN_FILE.read_text())
        return bool(data.get("tokens", {}).get("access_token"))
    except Exception:
        return False


skip_no_token = pytest.mark.skipif(
    not _has_cached_token(),
    reason="No cached Todoist OAuth token (run OAuth flow first)",
)

e2e = pytest.mark.e2e


@e2e
@skip_no_token
class TestEnsureOAuthTokenCachedPath:
    """Test ensure_oauth_token with a real cached token."""

    @pytest.mark.asyncio
    async def test_returns_cached_token(self):
        token = await ensure_oauth_token("todoist", TODOIST_URL, TOKEN_DIR)
        assert isinstance(token, str)
        assert len(token) > 10

    @pytest.mark.asyncio
    async def test_cached_token_is_valid(self):
        """Verify the cached token is accepted by Todoist."""
        token = await ensure_oauth_token("todoist", TODOIST_URL, TOKEN_DIR)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TODOIST_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1"},
                    },
                },
            )
            assert resp.status_code == 200


@e2e
@skip_no_token
class TestRawHttpWithToken:
    """Verify the static-header approach works at the HTTP level."""

    @pytest.mark.asyncio
    async def test_unauthenticated_gets_401(self):
        async with httpx.AsyncClient() as client:
            resp = await client.post(TODOIST_URL)
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_gets_200(self):
        storage = FileTokenStorage("todoist", TOKEN_DIR)
        token = await storage.get_tokens()
        assert token is not None

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TODOIST_URL,
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1"},
                    },
                },
            )
            assert resp.status_code == 200
