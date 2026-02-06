"""OAuth browser-based authentication for downstream MCP servers.

Provides FileTokenStorage (persists tokens to disk), OAuthCallbackServer
(localhost redirect receiver), and create_oauth_provider() factory that
wires them into an OAuthClientProvider suitable for httpx.AsyncClient(auth=...).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import AnyUrl

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

class FileTokenStorage:
    """Persists OAuth tokens and client registration to a JSON file.

    File permissions: 0o600 (user-only read/write).
    """

    def __init__(self, server_name: str, token_dir: Path) -> None:
        self._path = token_dir / f"{server_name}.json"

    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))
        self._path.chmod(0o600)

    # -- TokenStorage protocol -------------------------------------------------

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._read().get("tokens")
        if raw is None:
            return None
        try:
            return OAuthToken.model_validate(raw)
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = self._read()
        data["tokens"] = tokens.model_dump()
        self._write(data)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._read().get("client_info")
        if raw is None:
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except Exception:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        data = self._read()
        data["client_info"] = client_info.model_dump(mode="json")
        self._write(data)


# ---------------------------------------------------------------------------
# OAuth callback server
# ---------------------------------------------------------------------------

_SUCCESS_HTML = """\
<!DOCTYPE html>
<html><head><title>Authentication Successful</title></head>
<body style="font-family:system-ui;text-align:center;padding:3em">
<h1>&#x2705; Authentication Successful</h1>
<p>You can close this tab and return to the terminal.</p>
</body></html>
"""

_ERROR_HTML = """\
<!DOCTYPE html>
<html><head><title>Authentication Failed</title></head>
<body style="font-family:system-ui;text-align:center;padding:3em">
<h1>&#x274c; Authentication Failed</h1>
<p>{error}</p>
</body></html>
"""


class OAuthCallbackServer:
    """Temporary localhost HTTP server that receives the OAuth redirect.

    Runs in a daemon thread, captures ``?code=...&state=...`` and resolves
    an asyncio.Future so the async caller can await the result.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._future: asyncio.Future[tuple[str, str | None]] = loop.create_future()

        parent = self  # captured by the handler class

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                qs = parse_qs(urlparse(self.path).query)
                code_list = qs.get("code")
                state_list = qs.get("state")
                error_list = qs.get("error")

                if error_list:
                    error_msg = error_list[0]
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(_ERROR_HTML.format(error=error_msg).encode())
                    parent._loop.call_soon_threadsafe(
                        parent._future.set_exception,
                        RuntimeError(f"OAuth error: {error_msg}"),
                    )
                    return

                if not code_list:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(_ERROR_HTML.format(error="Missing code parameter").encode())
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(_SUCCESS_HTML.encode())

                code = code_list[0]
                state = state_list[0] if state_list else None
                parent._loop.call_soon_threadsafe(
                    parent._future.set_result, (code, state)
                )

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                # Silence default stderr logging from BaseHTTPRequestHandler
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/callback"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()

    async def wait_for_callback(self) -> tuple[str, str | None]:
        """Await the authorization code from the redirect."""
        return await self._future


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

async def ensure_oauth_token(server_name: str, server_url: str, token_dir: Path) -> str:
    """Return a valid Bearer access token, running the OAuth flow if needed.

    1. Check FileTokenStorage for a cached token.
    2. If missing, send a preflight POST to trigger a 401, then run the full
       OAuthClientProvider flow (browser redirect, callback, token exchange).
    3. Persist the token and return the access_token string.
    """
    storage = FileTokenStorage(server_name, token_dir)

    # Fast path: reuse cached token
    cached = await storage.get_tokens()
    if cached is not None:
        logger.info(f"Using cached OAuth token for {server_name}")
        return cached.access_token

    # Slow path: full OAuth browser flow
    logger.info(f"No cached token for {server_name}, starting OAuth flow...")
    loop = asyncio.get_running_loop()
    callback_server = OAuthCallbackServer(loop)
    callback_server.start()

    try:
        client_metadata = OAuthClientMetadata(
            redirect_uris=[AnyUrl(callback_server.redirect_uri)],
            client_name=f"agent-mcp ({server_name})",
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )

        async def redirect_handler(authorization_url: str) -> None:
            print(
                f"\nOpening browser for authentication...\n{authorization_url}",
                file=sys.stderr,
            )
            webbrowser.open(authorization_url)

        async def callback_handler() -> tuple[str, str | None]:
            return await callback_server.wait_for_callback()

        provider = OAuthClientProvider(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

        # Preflight: a bare POST triggers a 401 which drives the full
        # OAuthClientProvider discovery → registration → browser → token flow.
        async with httpx.AsyncClient(auth=provider) as client:
            await client.post(server_url)

        # The provider persisted the token via FileTokenStorage.
        token = await storage.get_tokens()
        if token is None:
            raise RuntimeError(f"OAuth flow completed but no token was stored for {server_name}")
        return token.access_token
    finally:
        callback_server.stop()
