# agent-mcp

An MCP (Model Context Protocol) facade server that exposes high-level tools backed by autonomous agent loops. This project acts as a bridge between client applications and multiple downstream MCP servers, using an LLM to intelligently delegate tasks as natural-language instructions.

## Overview

`agent-mcp` is a meta-MCP server that:

1. **Aggregates multiple MCP servers** - Connects to any number of downstream MCP servers
2. **Exposes unified tools** - Each downstream server becomes a single high-level tool
3. **Powers tools with agents** - When a tool is invoked, an autonomous agent (powered by [Google ADK](https://github.com/google/adk-python)) runs to fulfill the instruction using the downstream server's capabilities
4. **Handles complexity internally** - Clients stay simple; agents handle tool selection, error recovery, and multi-step operations

## Use Case

Instead of a client needing to:
- Know which MCP server has which tools
- Understand tool parameters and schemas
- Handle tool call sequences and errors

Clients can say:
```
Tool: "my-server"
Input: "Create a task 'Buy groceries' and add it to the Groceries project"
```

And the agent handles the complexity of looking up projects, calling the right tools, and returning results.

## Architecture

```
┌──────────────────┐
│   Client (e.g.   │
│   Claude Code)   │
└────────┬─────────┘
         │ MCP Protocol
         ▼
┌─────────────────────┐
│  agent-mcp Server   │
├─────────────────────┤
│  Tool 1: server-a   ├──→ ADK Agent ─→ LLM (via LiteLLM)
│  Tool 2: server-b   ├──→ ADK Agent ─→ LLM (via LiteLLM)
│  Tool 3: server-c   ├──→ ADK Agent ─→ LLM (via LiteLLM)
│  ...                │
└─────────┬───────────┘
          │
          │ MCP Protocol (stdio/http)
          ▼
    ┌─────────────┐
    │ Downstream  │
    │ MCP Servers │
    └─────────────┘
```

## Installation

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (optional, but recommended)
- API keys for the LLM provider you want to use (e.g. `ANTHROPIC_API_KEY`)
- API tokens for any downstream MCP servers you configure (optional)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/agent-mcp.git
cd agent-mcp
```

2. Install dependencies:
```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

3. Create configuration files:
```bash
# Create .mcp.json from the example
cp .mcp.json.example .mcp.json

# Edit with your API keys and paths
nano .mcp.json
```

4. Configure downstream MCP servers in `config.yaml`:
```yaml
model: anthropic/claude-sonnet-4-20250514
max_tokens: 8096
max_llm_calls: 20

servers:
  my-server:
    description: "Description of what this server does"
    transport: stdio
    command: uv
    args:
      - run
      - --directory
      - /path/to/my-mcp-server
      - my-mcp-server
    env:
      MY_API_TOKEN: ${MY_API_TOKEN}
```

The `model` field uses [LiteLLM format](https://docs.litellm.ai/docs/providers) (`provider/model-name`), so you can use any supported LLM provider.

## Configuration

### .mcp.json

The `.mcp.json` file configures how Claude Code (or other MCP clients) launches `agent-mcp`:

```json
{
  "mcpServers": {
    "agent-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/agent-mcp", "agent-mcp"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key",
        "MY_API_TOKEN": "your-token"
      }
    }
  }
}
```

**Important:** Never commit `.mcp.json` to git. Use `.mcp.json.example` as a template.

### config.yaml

The `config.yaml` file defines:

- **Agent settings** - Model (LiteLLM format), max tokens, LLM call limits
- **Downstream servers** - MCP servers to aggregate
  - Transport type (stdio, http)
  - How to launch them (command + args for stdio, url for http)
  - Environment variables (supports `${VAR}` substitution)
  - Authentication (static headers or OAuth browser flow)

## Usage

### As an MCP Server

Once `agent-mcp` is running, clients connect via MCP and call tools:

```python
# Pseudocode example
response = await client.call_tool("my-server", {
    "instruction": "List all my projects and tasks due today"
})
```

### Running Standalone

```bash
uv run agent-mcp
```

The server listens on stdin/stdout for MCP protocol messages.

### With Claude Code

1. Copy your `.mcp.json` configuration to `~/.config/Claude/claude_desktop_config.json`
2. Restart Claude Code
3. Your configured downstream server tools become available in conversations

## How It Works

1. **Initialization** - `agent-mcp` loads `config.yaml` and registers tools for each downstream server
2. **Tool Registration** - Each downstream server becomes a tool with its configured name
3. **Request Handling** - When a tool is invoked with a natural-language instruction:
   - `agent-mcp` creates an ADK `McpToolset` connected to the downstream server
   - An ADK `LlmAgent` runs with the downstream server's tools
   - The agent reads the instruction and decides which tools to call
   - The agent handles tool calls, errors, and retries
   - Results are returned to the client, and the toolset is closed
4. **Per-invocation lifecycle** - Each tool call gets a fresh MCP connection, avoiding stale connection state

## Project Structure

```
agent-mcp/
├── README.md                 # This file
├── .gitignore              # Git exclusions
├── .mcp.json.example       # Template for .mcp.json
├── config.yaml             # Downstream server configuration
├── pyproject.toml          # Python project metadata
├── uv.lock                 # Locked dependencies
├── src/
│   └── agent_mcp/
│       ├── __init__.py
│       ├── server.py       # MCP server entrypoint
│       ├── agent.py        # ADK agent orchestration
│       ├── oauth.py        # OAuth browser-based authentication
│       └── config.py       # Configuration loading and parsing
└── tests/
    ├── test_agent.py       # Agent unit tests
    ├── test_config.py      # Config parsing tests
    ├── test_oauth.py       # OAuth flow tests
    ├── test_server.py      # Server CLI tests
    └── test_e2e_oauth.py   # End-to-end OAuth tests (require cached tokens)
```

### Module Overview

- **server.py** - FastMCP server implementation, handles MCP protocol
- **agent.py** - ADK-based agent orchestration using `LlmAgent`, `Runner`, and `McpToolset`
- **oauth.py** - OAuth browser-based authentication for downstream MCP servers
- **config.py** - YAML parsing, environment variable substitution, validation

## Development

### Running Tests

```bash
uv run pytest -m "not e2e"
```

### Running End-to-End Tests

E2E tests require cached OAuth tokens (run the OAuth flow manually first):

```bash
uv run pytest -m e2e
```

### Code Style

- Python 3.10+
- Async-first (asyncio)
- Type hints throughout
- Minimal dependencies

## Limitations & Future Work

- Only supports stdio and http transports
- No caching of tool schemas (reloaded on every call)
- Error messages are agent-generated (could be inconsistent)

## Contributing

Contributions welcome! Areas of interest:

- Tool schema caching for performance
- Better error recovery strategies
- Additional test coverage

## License

MIT

## Acknowledgments

Built with:
- [Google ADK](https://github.com/google/adk-python) - Agent Development Kit
- [LiteLLM](https://github.com/BerriAI/litellm) - Multi-provider LLM gateway
- [mcp-python](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP](https://github.com/modelcontextprotocol/python-sdk/tree/main/src/mcp/server/fastmcp)
