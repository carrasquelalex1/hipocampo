# Guía del Dockerfile

## Vista General
Este documento explica cómo contenerizar el Servidor MCP de Hipocampo usando Docker.

## Archivos

| Archivo | Propósito |
|---------|-----------|
| `Dockerfile` | Archivo principal de construcción para contenerización |
| `docker-entrypoint.sh` | Script de inicialización (configura PostgreSQL, inicia servidor) |
| `docker-compose.yml` | Archivo de conveniencia para desarrollo/testing local |
| `Dockerfile.simple` | Versión mínima sin PostgreSQL (para PG externo) |

## Propósito
El Dockerfile se proporciona principalmente para satisfacer el requisito de Glama para listar servidores MCP. Glama necesita un Dockerfile para la verificación automatizada.

## Seguridad

### Variables de Entorno
El Dockerfile establece variables de entorno con **valores dummy**:

```dockerfile
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy
ENV DB_PASSWORD=hipocampo_pass
```

**NO son credenciales reales.** Por qué esto es seguro:

1. **Acceso diferido**: Estas variables solo se acceden al ejecutar herramientas MCP específicas que requieren embeddings (como `search_hipocampo`), que llama a `_generar_embedding()`.
2. **Sin ejecución durante verificación**: La verificación automatizada de Glama solo usa solicitudes de introspección MCP (`initialize` y `list_tools`). **No se ejecuta ninguna herramienta**, por lo que no se hace ninguna llamada a APIs reales.
3. **Valores dummy fallan elegantemente**: Si accidentalmente se ejecutara una herramienta, las claves dummy fallarían durante la llamada a la API, sin exponer nada.

### Despliegue en Producción
Para uso real, sobrescribe estas variables de forma segura:
- Docker secrets (`docker secret create`)
- Kubernetes secrets
- Gestión de secrets específica de plataforma (AWS ECS, GCP, etc.)
- Archivos `.env` externos (nunca versionados en git)

## Uso

### Construir
```bash
docker build -t hipocampo-mcp .
```

### Ejecutar con Docker Compose (Desarrollo)
```bash
docker-compose up
```

### Ejecutar directamente
```bash
docker run -p 8001:8001 \
  -e DB_PASSWORD=tu_password \
  -e NVIDIA_API_KEY=tu_key \
  hipocampo-mcp
```

### Verificar Introspección MCP
Prueba que el servidor responde a solicitudes MCP:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | docker run -i hipocampo-mcp
```

Respuesta esperada (truncada):
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{...},"serverInfo":{"name":"hipocampo","version":"1.27.2"}}}
```

## Explicación de Estadísticas de Lenguaje
GitHub Linguist detecta la siguiente composición de lenguajes:
- **Python 98.1%**: Código principal de la aplicación
- **Shell 1.6%**: `docker-entrypoint.sh` (script de inicialización)
- **Dockerfile 0.3%**: Este archivo Dockerfile

El porcentaje de Shell es **normal y esperado** en proyectos con soporte Docker. Representa solo la lógica de inicialización necesaria para arrancar PostgreSQL y el servidor dentro del contenedor.

## Estado de Verificación

| Verificación | Estado |
|-------------|--------|
| El servidor inicia | ✅ Verificado |
| Respuesta MCP initialize | ✅ Verificado |
| Respuesta MCP list_tools | ✅ Verificado |
| Modo SSE (puerto 8001) | ✅ Verificado |
| Verificación automatizada Glama | ✅ Satisfecho |

## Relacionados
- [README.md](../README.md) — Documentación principal del proyecto
- [docker-entrypoint.sh](../docker-entrypoint.sh) — Script de entrada
- [esquema.sql](../esquema.sql) — Esquema de base de datos
