# Dockerfile Guide

## Overview
This document explains how to containerize the Hipocampo MCP Server using Docker.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Main build file for containerization |
| `docker-entrypoint.sh` | Initialization script (sets up PostgreSQL, starts server) |
| `docker-compose.yml` | Convenience file for local development/testing |
| `Dockerfile.simple` | Minimal version without PostgreSQL (for external PG) |

## Purpose
The Dockerfile is provided primarily to satisfy Glama's MCP server listing requirements. Glama needs a Dockerfile for automated verification of MCP servers.

## Security

### Environment Variables
The Dockerfile sets environment variables with **dummy values**:

```dockerfile
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy
ENV DB_PASSWORD=hipocampo_pass
```

**These are NOT real credentials.** Here's why this is safe:

1. **Lazy access**: These variables are only accessed when executing specific MCP tools that require embeddings (like `search_hipocampo`), which calls `_generar_embedding()`.
2. **No execution during verification**: Glama's automated check only calls MCP introspection requests (`initialize` and `list_tools`). **No tools are executed**, so no API calls are made.
3. **Dummy values fail gracefully**: If a tool were accidentally called, the dummy keys would fail during the API call, not expose anything.

### Production Deployments
For real use, override these variables securely:
- Docker secrets (`docker secret create`)
- Kubernetes secrets
- Platform-specific secret management (AWS ECS, GCP, etc.)
- External `.env` files (never committed to git)

## Usage

### Build
```bash
docker build -t hipocampo-mcp .
```

### Run with Docker Compose (Development)
```bash
docker-compose up
```

### Run directly
```bash
docker run -p 8001:8001 \
  -e DB_PASSWORD=your_password \
  -e NVIDIA_API_KEY=your_key \
  hipocampo-mcp
```

### Verify MCP Introspection
Test that the server responds to MCP requests:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | docker run -i hipocampo-mcp
```

Expected response (truncated):
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{...},"serverInfo":{"name":"hipocampo","version":"1.27.2"}}}
```

## Language Statistics Explanation
GitHub Linguist detects the following language breakdown:
- **Python 98.1%**: Core application code
- **Shell 1.6%**: `docker-entrypoint.sh` (initialization script)
- **Dockerfile 0.3%**: This Dockerfile

The Shell percentage is **normal and expected** for projects with Docker support. It represents only the initialization logic needed to start PostgreSQL and the server within the container.

## Verification Status

| Check | Status |
|-------|--------|
| Server starts | ✅ Verified |
| MCP initialize response | ✅ Verified |
| MCP list_tools response | ✅ Verified |
| SSE mode (port 8001) | ✅ Verified |
| Glama automated check | ✅ Satisfied |

## Related
- [README.md](../README.md) — Main project documentation
- [docker-entrypoint.sh](../docker-entrypoint.sh) — Entrypoint script
- [esquema.sql](../esquema.sql) — Database schema
