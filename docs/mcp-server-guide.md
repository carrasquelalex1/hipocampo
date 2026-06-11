# Hipocampo MCP Server: Configuration & Integration Guide

## Overview

The Hipocampo MCP Server exposes the core dual-memory search and persistence engine as a set of robust tools using the **Model Context Protocol (MCP)**. Built on top of `FastMCP`, it natively integrates with any modern AI agent or IDE that supports MCP (e.g., Claude Desktop, OpenCode, Cursor).

---

## ⚙️ Requirements

* **Python 3.13+**
* `mcp>=1.0.0`
* `openai>=1.0.0`
* `psycopg2-binary>=2.9`

---

## 🚀 Installation & Setup

```bash
# 1. Ensure dependencies are installed
pip3 install -r requirements.txt

# 2. Configure environment variables (ensure .env exists in the project root)
# DB_HOST, DB_USER, DB_NAME, GOOGLE_API_KEY
```

### Running the Server

The server supports two standard MCP transport layers: **Standard I/O (stdio)** and **Server-Sent Events (SSE)**.

**Mode 1: Standard I/O (Default)**
Ideal for local clients running on the same machine (like Claude Desktop).
```bash
python3 scripts/hipocampo_mcp_server.py
```

**Mode 2: SSE (HTTP Transport)**
Ideal for remote clients or web-based agents. Binds to port `8001` by default.
```bash
python3 scripts/hipocampo_mcp_server.py --sse 8001
```

---

## 🛠️ Available MCP Tools

Once connected, your AI agent gains access to the following tools:

1. **`search_hipocampo`**: 
   * **Purpose**: Performs a hybrid semantic/lexical search across both the technical and profile memory layers.
   * **Parameters**: `query` (string)

2. **`quick_hipocampo_search`**:
   * **Purpose**: A shorthand alias for `search_hipocampo`, designed for brevity in prompt contexts.
   * **Parameters**: `query` (string)

3. **`save_hipocampo`**:
   * **Purpose**: Persists technical data, architectural decisions, and project knowledge into the `memoria_vectorial` table. Generates the 768d embedding automatically.
   * **Parameters**: `content` (string), `memory_type` (enum), `code` (string), `categories` (array)

4. **`profile_hipocampo`**:
   * **Purpose**: Saves user-specific profiling data, personal facts, and habits directly to the `memory_items` table.
   * **Parameters**: `summary` (string), `extra` (string), `categories` (array)

---

## 💻 Client Integrations

### Claude Desktop
Add the following configuration to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "hipocampo": {
      "command": "python3",
      "args": ["/absolute/path/to/hipocampo/scripts/hipocampo_mcp_server.py"],
      "timeout": 120000
    }
  }
}
```

### OpenCode / Cursor
Add the following to your `opencode.json` or respective configuration file:

```json
{
  "mcpServers": {
    "hipocampo": {
      "command": "python3",
      "args": ["/absolute/path/to/hipocampo/scripts/hipocampo_mcp_server.py"]
    }
  }
}
```

---

## 🔄 Systemd Service (Linux)

To ensure the server runs continuously in the background (especially useful for SSE mode), a systemd service is included:

```bash
# Copy the unit file
cp scripts/hipocampo-mcp.service ~/.config/systemd/user/

# Enable and start the service
systemctl --user daemon-reload
systemctl --user enable --now hipocampo-mcp.service

# Check status
systemctl --user status hipocampo-mcp.service
```