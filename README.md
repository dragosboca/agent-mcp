# agent-mcp

An MCP (Model Context Protocol) facade server that exposes high-level tools backed by autonomous agent loops. This project acts as a bridge between client applications and multiple downstream MCP servers, using Claude to intelligently delegate tasks as natural-language instructions.

## Overview

`agent-mcp` is a meta-MCP server that:

1. **Aggregates multiple MCP servers** - Connects to any number of downstream MCP servers
2. **Exposes unified tools** - Each downstream server becomes a single high-level tool
3. **Powers tools with agents** - When a tool is invoked, an autonomous Claude agent runs to fulfill the instruction using the downstream server's capabilities
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
│  Tool 1: server-a   ├──→ Agent Loop ─→ Anthropic Claude
│  Tool 2: server-b   ├──→ Agent Loop ─→ Anthropic Claude
│  Tool 3: server-c   ├──→ Agent Loop ─→ Anthropic Claude
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
- API keys for services you want to use:
  - Anthropic API key (required)
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
model: claude-sonnet-4-20250514
max_tokens: 8096
max_iterations: 20

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

- **Agent settings** - Model, max tokens, iteration limits
- **Downstream servers** - MCP servers to aggregate
  - Transport type (stdio, http)
  - How to launch them (command + args)
  - Environment variables (supports `${VAR}` substitution)

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

1. **Initialization** - `agent-mcp` loads `config.yaml` and connects to all downstream MCP servers
2. **Tool Registration** - Each downstream server becomes a tool with its configured name
3. **Request Handling** - When a tool is invoked with a natural-language instruction:
   - `agent-mcp` spawns an autonomous Claude agent
   - The agent loads all tools from the downstream server
   - Claude reads the instruction and decides which tools to call
   - The agent handles tool calls, errors, and retries
   - Results are returned to the client
4. **Cleanup** - MCP connections are cleaned up on shutdown

## Project Structure

```
agent-mcp/
├── README.md                 # This file
├── .gitignore              # Git exclusions
├── .mcp.json.example       # Template for .mcp.json
├── config.yaml             # Downstream server configuration
├── pyproject.toml          # Python project metadata
├── uv.lock                 # Locked dependencies
└── src/
    └── agent_mcp/
        ├── __init__.py
        ├── server.py       # MCP server entrypoint
        ├── agent.py        # Agent loop logic
        ├── mcp_client.py   # Downstream MCP client management
        └── config.py       # Configuration loading and parsing
```

### Module Overview

- **server.py** - FastMCP server implementation, handles MCP protocol
- **agent.py** - Core agent loop that runs Claude with tools from downstream servers
- **mcp_client.py** - Manages connections to downstream MCP servers (stdio, http)
- **config.py** - YAML parsing, environment variable substitution, validation

## Development

### Running Tests

```bash
uv run python -m pytest tests/
```

### Running Linting/Type Checking

```bash
uv run ruff check src/
uv run mypy src/
```

### Code Style

- Python 3.10+
- Async-first (asyncio)
- Type hints throughout
- Minimal dependencies

## Limitations & Future Work

- Only supports stdio and http transports (websocket coming soon)
- Single-threaded agent loop (can be queued if needed)
- No caching of tool schemas (reloaded on every call)
- Error messages are agent-generated (could be inconsistent)

## Contributing

Contributions welcome! Areas of interest:

- Support for websocket transport
- Tool schema caching for performance
- Better error recovery strategies
- Additional test coverage

## License

MIT

## Acknowledgments

Built with:
- [anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)
- [mcp-python](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP](https://github.com/modelcontextprotocol/python-sdk/tree/main/src/mcp/server/fastmcp)
