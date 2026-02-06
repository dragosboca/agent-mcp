"""Unit tests for agent_mcp.config."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent_mcp.config import ServerConfig, load_config


def _write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p


class TestServerConfigDataclass:
    def test_defaults(self):
        cfg = ServerConfig(name="s", description="d", transport="http")
        assert cfg.auth is None
        assert cfg.headers == {}
        assert cfg.url is None

    def test_auth_field(self):
        cfg = ServerConfig(name="s", description="d", transport="http", auth="oauth")
        assert cfg.auth == "oauth"


class TestLoadConfig:
    def test_parses_auth_field(self, tmp_path):
        p = _write_config(tmp_path, """\
            servers:
              myserver:
                description: test
                transport: http
                url: https://example.com/mcp
                auth: oauth
        """)
        config = load_config(str(p))
        assert len(config.servers) == 1
        assert config.servers[0].auth == "oauth"

    def test_auth_defaults_to_none(self, tmp_path):
        p = _write_config(tmp_path, """\
            servers:
              myserver:
                description: test
                transport: http
                url: https://example.com/mcp
        """)
        config = load_config(str(p))
        assert config.servers[0].auth is None

    def test_parses_headers(self, tmp_path):
        p = _write_config(tmp_path, """\
            servers:
              gh:
                description: github
                transport: http
                url: https://api.github.com/mcp
                headers:
                  Authorization: "Bearer tok123"
        """)
        config = load_config(str(p))
        assert config.servers[0].headers == {"Authorization": "Bearer tok123"}

    def test_env_var_resolution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_TOKEN", "secret123")
        p = _write_config(tmp_path, """\
            servers:
              s:
                description: test
                transport: http
                url: https://example.com
                headers:
                  Authorization: "Bearer ${TEST_TOKEN}"
        """)
        config = load_config(str(p))
        assert config.servers[0].headers["Authorization"] == "Bearer secret123"

    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_multiple_servers(self, tmp_path):
        p = _write_config(tmp_path, """\
            servers:
              a:
                description: first
                transport: http
                url: https://a.com
                auth: oauth
              b:
                description: second
                transport: stdio
                command: echo
        """)
        config = load_config(str(p))
        assert len(config.servers) == 2
        names = {s.name for s in config.servers}
        assert names == {"a", "b"}

    def test_app_config_defaults(self, tmp_path):
        p = _write_config(tmp_path, "servers: {}")
        config = load_config(str(p))
        assert config.model == "anthropic/claude-sonnet-4-20250514"
        assert config.max_tokens == 8096
        assert config.max_llm_calls == 20
        assert config.token_dir.endswith(".agent-mcp/tokens")

    def test_max_iterations_backward_compat(self, tmp_path):
        p = _write_config(tmp_path, """\
            max_iterations: 30
            servers: {}
        """)
        config = load_config(str(p))
        assert config.max_llm_calls == 30

    def test_max_llm_calls_preferred_over_max_iterations(self, tmp_path):
        p = _write_config(tmp_path, """\
            max_llm_calls: 50
            max_iterations: 30
            servers: {}
        """)
        config = load_config(str(p))
        assert config.max_llm_calls == 50

    def test_token_dir_custom(self, tmp_path):
        p = _write_config(tmp_path, """\
            token_dir: /tmp/my-tokens
            servers: {}
        """)
        config = load_config(str(p))
        assert config.token_dir == "/tmp/my-tokens"

    def test_token_dir_tilde_expansion(self, tmp_path):
        p = _write_config(tmp_path, """\
            token_dir: ~/custom-tokens
            servers: {}
        """)
        config = load_config(str(p))
        assert "~" not in config.token_dir
        assert config.token_dir.endswith("/custom-tokens")
