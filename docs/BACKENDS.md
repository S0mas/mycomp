# LLM Backends — Setup & Usage

mycomp uses a pluggable backend architecture. The system never imports a specific
LLM SDK directly — all calls go through the `LLMBackend` protocol defined in
`aicompany/llm_backend.py`.

## Quick Start

```bash
# Set the backend (default: anthropic)
export AICOMPANY_LLM_BACKEND=anthropic   # or: openai, fake

# Set the model
export AICOMPANY_MODEL=claude-sonnet-4-6  # any model the backend supports

# Run
python main.py init
python main.py new-project requirements.md
```

---

## Available Backends

### 1. Anthropic (default)

Direct access to Claude via the Anthropic SDK.

**Setup:**
```bash
pip install anthropic
export AICOMPANY_LLM_BACKEND=anthropic
export AICOMPANY_MODEL=claude-sonnet-4-6      # or claude-haiku-4, etc.
export ANTHROPIC_API_KEY=sk-ant-...
```

**When to use:** Production with Claude models. Best quality for code generation.

---

### 2. OpenAI-compatible

Works with **any provider** that exposes the OpenAI chat completions API. No SDK
dependency — uses Python's built-in `urllib`.

**Setup — OpenAI:**
```bash
export AICOMPANY_LLM_BACKEND=openai
export AICOMPANY_MODEL=gpt-4o
export OPENAI_API_KEY=sk-...
```

**Setup — Ollama (local):**
```bash
# Start Ollama first: ollama serve
export AICOMPANY_LLM_BACKEND=openai
export AICOMPANY_MODEL=llama3
export OPENAI_API_KEY=none
export OPENAI_BASE_URL=http://localhost:11434/v1
```

**Setup — LM Studio (local):**
```bash
# Start LM Studio server first
export AICOMPANY_LLM_BACKEND=openai
export AICOMPANY_MODEL=local-model
export OPENAI_API_KEY=none
export OPENAI_BASE_URL=http://localhost:1234/v1
```

**Setup — vLLM / LiteLLM / LocalAI:**
```bash
export AICOMPANY_LLM_BACKEND=openai
export AICOMPANY_MODEL=your-model-name
export OPENAI_API_KEY=your-key-or-none
export OPENAI_BASE_URL=http://your-server:port/v1
```

**Environment variables:**
| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | API key, or `none` for local providers |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | Base URL for the API |
| `AICOMPANY_MODEL` | No | `claude-sonnet-4-6` | Model name the provider understands |

---

### 3. Fake (testing / CI)

Returns canned responses without any network calls. Zero cost, zero latency,
zero config.

**Setup:**
```bash
export AICOMPANY_LLM_BACKEND=fake
# No API key needed. No model needed.
```

**When to use:**
- CI/CD pipelines
- Development without API costs
- Testing the full flow end-to-end
- Demos

The fake backend pattern-matches on system prompts to return appropriate canned
responses (evaluation scores, CTO plans, HR teams, etc.).

---

## Adding a New Backend

1. Create `aicompany/backends/my_backend.py`:

```python
from aicompany.llm_backend import register_backend


class MyBackend:
    """Must implement the LLMBackend protocol."""

    def __init__(self) -> None:
        # Read config from env vars, validate, create client
        pass

    def call(self, system: str, user: str, max_tokens: int, model: str) -> str:
        # Send system + user messages, return response text
        ...


register_backend("my_backend", MyBackend)
```

2. Import it in `aicompany/backends/__init__.py`:
```python
try:
    from . import my_backend  # noqa: F401
except ImportError:
    pass  # SDK not installed — skip silently
```

3. Use it:
```bash
export AICOMPANY_LLM_BACKEND=my_backend
```

**Requirements for a backend:**
- Must implement `call(system: str, user: str, max_tokens: int, model: str) -> str`
- Must call `register_backend("name", MyClass)` at module level
- Must raise `EnvironmentError` in `__init__` if required config is missing
- Should wrap provider errors in `RuntimeError` with clear messages

---

## Backend Selection Flow

```
AICOMPANY_LLM_BACKEND env var
        │
        ▼
┌─────────────────┐
│ backends/__init__│  imports all backend modules
│                 │  each calls register_backend()
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ create_backend() │  looks up name in registry
│                 │  instantiates the class
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ llm.py _call()  │  calls backend.call(system, user, max_tokens, model)
│                 │  all business logic unchanged
└─────────────────┘
```

---

## MCP Server (required for `run`)

Project execution requires an MCP server. Agents use it to write files, read existing
code, and run commands during task execution. Without it, `python main.py run` raises
a `RuntimeError`.

### Required tool interface

Any server set in `AICOMPANY_MCP_SERVERS` **must** expose these four tools:

| Tool | Signature | Behaviour |
|---|---|---|
| `write_file` | `(path: str, content: str) -> str` | Write content to path relative to workspace root. Creates parent dirs. Returns confirmation. |
| `read_file` | `(path: str) -> str` | Read file at path. Returns content or error string. |
| `list_directory` | `(path: str = ".") -> str` | List entries at path. Returns newline-separated names. |
| `run_command` | `(command: str) -> str` | Run shell command. Returns combined stdout+stderr. |

Optional tools (used when available):
- `run_tests(pattern: str = "")` — run the project test suite
- `get_project_status()` — git status + recent commits

### Built-in server

The repo ships `aicompany/mcp_server.py` with all required + optional tools,
scoped to the project root with path-traversal protection.

```bash
# Start server + cloudflare quick tunnel (prints public URL)
./scripts/start_mcp.sh

# Then set:
export AICOMPANY_MCP_SERVERS='[{"type":"url","url":"https://<tunnel>.trycloudflare.com/mcp","name":"mycomp"}]'
```

### Implementing a custom MCP server

Any FastMCP-compatible server that exposes the four required tools will work.
See `aicompany/backends/fake_mcp_server.py` for a minimal reference implementation
(in-process, workspace-scoped, used in tests).

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "my-server",
    host="127.0.0.1",
    port=8000,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

@mcp.tool()
def write_file(path: str, content: str) -> str: ...

@mcp.tool()
def read_file(path: str) -> str: ...

@mcp.tool()
def list_directory(path: str = ".") -> str: ...

@mcp.tool()
def run_command(command: str) -> str: ...

mcp.run(transport="streamable-http")
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `KeyError: Unknown LLM backend` | Check `AICOMPANY_LLM_BACKEND` spelling. Run with `fake` to test. |
| `EnvironmentError: API key not set` | Set the appropriate key for your backend. |
| `ImportError` on startup | Install the SDK: `pip install anthropic` or `pip install openai` |
| Bad model responses | Ensure `AICOMPANY_MODEL` is a model your provider actually serves. |
| Local provider connection refused | Ensure Ollama/LM Studio/vLLM is running and `OPENAI_BASE_URL` is correct. |
