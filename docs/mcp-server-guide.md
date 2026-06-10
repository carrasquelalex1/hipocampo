# Hipocampo MCP Server — Guía de Configuración

## Descripción

Servidor MCP (Model Context Protocol) que expone el sistema de búsqueda Hipocampo como endpoint HTTP. Permite consultar memorias técnicas y de perfil desde cualquier agente AI compatible con MCP.

## Requisitos

- Python 3.13+
- Flask (`pip3 install flask`)

## Instalación

```bash
# 1. Crear el servidor Flask
cp hipocampo_mcp_server.py /home/tu_usuario/hipocampo_mcp_server.py

# 2. Instalar dependencia
pip3 install flask

# 3. Configurar servicio systemd (opcional pero recomendado)
cp hipocampo-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable hipocampo-mcp.service
systemctl --user start hipocampo-mcp.service
```

## Endpoints

### GET /search

Busca en la memoria dual del Hipocampo (técnica + perfil).

**Parámetros:**
- `query` (string, requerido) — Término de búsqueda

**Ejemplo:**
```bash
curl "http://localhost:8001/search?query=proyecto+contable"
```

**Respuesta:**
```json
{
  "output": "Resultados formateados con scores, fuente y contenido"
}
```

**Códigos de error:**
- `400` — Falta el parámetro `query`
- `500` — Error interno en el script de búsqueda

## Configuración con OpenCode

Agrega en `~/.config/opencode/opencode.json`:

```json
{
  "mcpServers": {
    "hipocampo": {
      "command": "python3",
      "args": ["/home/tu_usuario/hipocampo_mcp_server.py"]
    }
  }
}
```

## Notas

- El puerto por defecto es `8000`. Si está ocupado, cambiar en el archivo `.py`.
- El backend actual usa `hipocampo_search.py` (BIRE v3.6). Para usar el SSC search (v3.7), reemplazar la ruta en `subprocess.run` por `hipocampo_ssc_search.py`.

## Archivos

| Archivo | Propósito |
|---|---|
| `hipocampo_mcp_server.py` | Servidor Flask que expone el endpoint `/search` |
| `hipocampo-mcp.service` | Unidad systemd para gestión automática |
