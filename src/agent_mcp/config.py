from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} with the value from os.environ."""

    def _replace(match: re.Match) -> str:
        var = match.group(1)
        resolved = os.environ.get(var, "")
        return resolved

    return re.sub(r"\$\{([^}]+)\}", _replace, value)


def _resolve_recursive(obj: object) -> object:
    """Walk a nested dict/list and resolve env vars in all strings."""
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _resolve_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_recursive(item) for item in obj]
    return obj


@dataclass
class ServerConfig:
    name: str
    description: str
    transport: str  # "stdio" or "http"
    # stdio fields
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # http fields
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    auth: str | None = None


DEFAULT_TOKEN_DIR = str(Path.home() / ".agent-mcp" / "tokens")


@dataclass
class AppConfig:
    model: str = "anthropic/claude-sonnet-4-20250514"
    max_tokens: int = 8096
    max_llm_calls: int = 20
    token_dir: str = DEFAULT_TOKEN_DIR
    servers: list[ServerConfig] = field(default_factory=list)


def load_config(path: str | None = None) -> AppConfig:
    """Load config from YAML. Resolution order: explicit path -> AGENT_MCP_CONFIG env -> ./config.yaml"""
    if path is None:
        path = os.environ.get("AGENT_MCP_CONFIG", "config.yaml")

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    raw = _resolve_recursive(raw)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected config to be a dict, got {type(raw).__name__}")

    servers = []
    for name, srv in raw.get("servers", {}).items():
        servers.append(
            ServerConfig(
                name=name,
                description=srv.get("description", ""),
                transport=srv.get("transport", "stdio"),
                command=srv.get("command"),
                args=srv.get("args", []),
                env=srv.get("env", {}),
                url=srv.get("url"),
                headers=srv.get("headers", {}),
                auth=srv.get("auth"),
            )
        )

    max_llm_calls = raw.get("max_llm_calls") or raw.get("max_iterations", 20)

    return AppConfig(
        model=raw.get("model", "anthropic/claude-sonnet-4-20250514"),
        max_tokens=raw.get("max_tokens", 8096),
        max_llm_calls=max_llm_calls,
        token_dir=str(Path(raw.get("token_dir", DEFAULT_TOKEN_DIR)).expanduser()),
        servers=servers,
    )
