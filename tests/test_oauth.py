"""Unit tests for agent_mcp.oauth."""

from __future__ import annotations

import asyncio
import json
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from agent_mcp.oauth import (
    FileTokenStorage,
    OAuthCallbackServer,
    ensure_oauth_token,
)


# ---------------------------------------------------------------------------
# FileTokenStorage
# ---------------------------------------------------------------------------


class TestFileTokenStorage:
    @pytest.fixture()
    def storage(self, tmp_path):
        return FileTokenStorage("testserver", tmp_path)

    @pytest.mark.asyncio
    async def test_get_tokens_empty(self, storage):
        assert await storage.get_tokens() is None

    @pytest.mark.asyncio
    async def test_set_and_get_tokens(self, storage):
        token = OAuthToken(access_token="abc123", token_type="Bearer")
        await storage.set_tokens(token)
        loaded = await storage.get_tokens()
        assert loaded is not None
        assert loaded.access_token == "abc123"
        assert loaded.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_file_permissions(self, storage, tmp_path):
        token = OAuthToken(access_token="secret", token_type="Bearer")
        await storage.set_tokens(token)
        token_file = tmp_path / "testserver.json"
        mode = token_file.stat().st_mode & 0o777
        assert mode == 0o600

    @pytest.mark.asyncio
    async def test_get_tokens_corrupted_file(self, storage, tmp_path):
        token_file = tmp_path / "testserver.json"
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text("not valid json {{{")
        assert await storage.get_tokens() is None

    @pytest.mark.asyncio
    async def test_get_client_info_empty(self, storage):
        assert await storage.get_client_info() is None

    @pytest.mark.asyncio
    async def test_set_and_get_client_info(self, storage):
        info = OAuthClientInformationFull(
            client_id="cid",
            client_secret="csec",
            redirect_uris=["http://localhost/cb"],
        )
        await storage.set_client_info(info)
        loaded = await storage.get_client_info()
        assert loaded is not None
        assert loaded.client_id == "cid"
        assert loaded.client_secret == "csec"

    @pytest.mark.asyncio
    async def test_tokens_and_client_info_coexist(self, storage):
        token = OAuthToken(access_token="tok", token_type="Bearer")
        info = OAuthClientInformationFull(
            client_id="cid",
            redirect_uris=["http://localhost/cb"],
        )
        await storage.set_tokens(token)
        await storage.set_client_info(info)
        assert (await storage.get_tokens()).access_token == "tok"
        assert (await storage.get_client_info()).client_id == "cid"

    @pytest.mark.asyncio
    async def test_get_client_info_corrupted(self, storage, tmp_path):
        token_file = tmp_path / "testserver.json"
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(json.dumps({"client_info": "not a dict"}))
        assert await storage.get_client_info() is None


# ---------------------------------------------------------------------------
# OAuthCallbackServer
# ---------------------------------------------------------------------------


class TestOAuthCallbackServer:
    @pytest.mark.asyncio
    async def test_captures_code_and_state(self):
        loop = asyncio.get_running_loop()
        server = OAuthCallbackServer(loop)
        server.start()
        try:
            port = server.port
            assert port > 0
            assert server.redirect_uri == f"http://127.0.0.1:{port}/callback"

            # Simulate browser redirect
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{port}/callback?code=AUTHCODE&state=STATE123"
                )
            assert resp.status_code == 200
            assert "Authentication Successful" in resp.text

            code, state = await asyncio.wait_for(server.wait_for_callback(), timeout=2)
            assert code == "AUTHCODE"
            assert state == "STATE123"
        finally:
            server.stop()

    @pytest.mark.asyncio
    async def test_captures_code_without_state(self):
        loop = asyncio.get_running_loop()
        server = OAuthCallbackServer(loop)
        server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{server.port}/callback?code=CODE_ONLY"
                )
            assert resp.status_code == 200

            code, state = await asyncio.wait_for(server.wait_for_callback(), timeout=2)
            assert code == "CODE_ONLY"
            assert state is None
        finally:
            server.stop()

    @pytest.mark.asyncio
    async def test_error_response(self):
        loop = asyncio.get_running_loop()
        server = OAuthCallbackServer(loop)
        server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{server.port}/callback?error=access_denied"
                )
            assert resp.status_code == 400
            assert "Authentication Failed" in resp.text

            with pytest.raises(RuntimeError, match="OAuth error: access_denied"):
                await asyncio.wait_for(server.wait_for_callback(), timeout=2)
        finally:
            server.stop()

    @pytest.mark.asyncio
    async def test_missing_code(self):
        loop = asyncio.get_running_loop()
        server = OAuthCallbackServer(loop)
        server.start()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{server.port}/callback?foo=bar"
                )
            assert resp.status_code == 400
            assert "Missing code" in resp.text
        finally:
            server.stop()


# ---------------------------------------------------------------------------
# ensure_oauth_token
# ---------------------------------------------------------------------------


class TestEnsureOAuthToken:
    @pytest.mark.asyncio
    async def test_returns_cached_token(self, tmp_path):
        token_file = tmp_path / "myserver.json"
        token_file.write_text(json.dumps({
            "tokens": {"access_token": "cached_tok", "token_type": "Bearer"},
        }))

        result = await ensure_oauth_token("myserver", "https://example.com/mcp", tmp_path)
        assert result == "cached_tok"

    @pytest.mark.asyncio
    async def test_runs_oauth_flow_when_no_cache(self, tmp_path, monkeypatch):
        # When the preflight client.post() is called, simulate the provider
        # persisting a token (which is what happens after a real OAuth flow)
        async def fake_post(url):
            token_file = tmp_path / "newserver.json"
            token_file.write_text(json.dumps({
                "tokens": {"access_token": "fresh_tok", "token_type": "Bearer"},
            }))
            return MagicMock(status_code=200)

        mock_client = AsyncMock()
        mock_client.post = fake_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("agent_mcp.oauth.httpx.AsyncClient", lambda **kwargs: mock_client)
        monkeypatch.setattr("agent_mcp.oauth.webbrowser.open", lambda url: None)

        result = await ensure_oauth_token("newserver", "https://example.com/mcp", tmp_path)
        assert result == "fresh_tok"

    @pytest.mark.asyncio
    async def test_raises_when_no_token_after_flow(self, tmp_path, monkeypatch):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr("agent_mcp.oauth.httpx.AsyncClient", lambda **kwargs: mock_client)
        monkeypatch.setattr("agent_mcp.oauth.webbrowser.open", lambda url: None)

        with pytest.raises(RuntimeError, match="no token was stored"):
            await ensure_oauth_token("empty", "https://example.com/mcp", tmp_path)
