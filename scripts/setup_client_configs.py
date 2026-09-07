#!/usr/bin/env python3
"""Registrador automático de clientes MCP para Hipocampo.

Detecta clientes instalados (OpenCode, Claude Desktop, Gemini CLI/Antigravity,
Cursor, VS Code, Windsurf) y añade la configuración de Hipocampo a cada uno
de forma idempotente.

Modos de conexión:
  - OpenCode:        REMOTE HTTP (el instalador levanta el servicio en un puerto)
  - Claude Desktop / Gemini CLI / Cursor / Windsurf: STDIO (comando + args del venv)
  - VS Code:         STDIO con formato "servers" (nuevo formato de VS Code)

Uso:
    python3 setup_client_configs.py --install-dir DIR --port 8001 [--unattended=true]
    python3 setup_client_configs.py --list-only --install-dir DIR
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HOME = Path.home()


def _backup(path: Path):
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak_hipocampo")
        shutil.copy2(path, bak)
        print(f"   (backup: {bak})")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def detect_clients() -> dict:
    """Devuelve {cliente: ruta_config} para los clientes presentes."""
    clients = {}

    # OpenCode (JSON o JSONC en ~/.config/opencode/)
    for name in ("opencode.json", "opencode.jsonc"):
        p = HOME / ".config" / "opencode" / name
        if p.exists():
            clients["opencode"] = p
            break

    # Claude Desktop
    claude = HOME / ".config" / "Claude" / "claude_desktop_config.json"
    if claude.exists():
        clients["claude"] = claude
    else:
        claude_mac = HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if claude_mac.exists():
            clients["claude"] = claude_mac

    # Gemini CLI / Antigravity CLI (comparten ~/.gemini/settings.json con clave "mcpServers")
    gemini = HOME / ".gemini" / "settings.json"
    if gemini.exists():
        clients["gemini"] = gemini  # Cubre Gemini CLI y Antigravity CLI

    # Cursor
    cursor = HOME / ".cursor" / "mcp.json"
    if cursor.exists():
        clients["cursor"] = cursor

    # VS Code (~/.vscode/mcp.json con clave "servers")
    vscode = HOME / ".vscode" / "mcp.json"
    if vscode.exists():
        clients["vscode"] = vscode

    # Windsurf (~/.codeium/windsurf/mcp_config.json con clave "mcpServers")
    windsurf = HOME / ".codeium" / "windsurf" / "mcp_config.json"
    if windsurf.exists():
        clients["windsurf"] = windsurf

    return clients


def register_opencode(cfg_path: Path, install_dir: str, port: int):
    """OpenCode: MCP remoto HTTP contra el servicio systemd."""
    data = _load_json(cfg_path)
    data.setdefault("mcp", {})
    data["mcp"]["hipocampo"] = {
        "type": "remote",
        "url": f"http://localhost:{port}/mcp",
        "enabled": True,
        "timeout": 120000,
    }
    _save_json(cfg_path, data)
    return f"remote http://localhost:{port}/mcp"


def register_stdio_client(cfg_path: Path, install_dir: str, client: str):
    """Claude Desktop / Gemini CLI / Cursor / Windsurf: MCP stdio con el venv."""
    venv_py = os.path.join(install_dir, ".venv", "bin", "python")
    server_py = os.path.join(install_dir, "scripts", "hipocampo_mcp_server.py")

    if not os.path.exists(venv_py) or not os.path.exists(server_py):
        return "SKIP (venv o servidor no encontrados)"

    data = _load_json(cfg_path)
    key = "servers" if client == "vscode" else "mcpServers"
    servers = data.setdefault(key, {})
    servers["hipocampo"] = {
        "command": venv_py,
        "args": [server_py],
        "env": {"ENV_PATH": os.path.join(install_dir, ".env")},
    }
    if client == "vscode":
        # VS Code: cada servidor también necesita "type": "stdio"
        servers["hipocampo"]["type"] = "stdio"
    _save_json(cfg_path, data)
    return f"stdio {server_py}"


def main():
    parser = argparse.ArgumentParser(description="Registro de clientes MCP para Hipocampo")
    parser.add_argument("--install-dir", required=False, default=os.path.expanduser("~/.local/share/hipocampo"))
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--unattended", default="false", help="true/false")
    parser.add_argument("--list-only", action="store_true", help="Solo listar clientes detectados")
    args = parser.parse_args()

    clients = detect_clients()

    if not clients:
        print("ℹ️  No se detectó ningún cliente MCP instalado (OpenCode/Claude/Gemini/Cursor/VS Code/Windsurf).")
        print("   Configura manualmente según docs/INSTALL.md")
        return 0

    if args.list_only:
        print(", ".join(sorted(clients)))
        return 0

    if args.unattended.lower() in ("true", "1", "yes"):
        print("   (modo --unattended, sin preguntas)")
    print(f"🔍 Clientes detectados: {', '.join(sorted(clients))}")

    for name, path in sorted(clients.items()):
        try:
            if name == "opencode":
                detail = register_opencode(path, args.install_dir, args.port)
            else:
                detail = register_stdio_client(path, args.install_dir, name)
            print(f"  ✅ {name}: {detail}")
        except Exception as e:
            print(f"  ❌ {name}: {e}")

    print("ℹ️  Reinicia los clientes para que carguen la nueva configuración.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
