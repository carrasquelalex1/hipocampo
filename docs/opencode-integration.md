# Hipocampo + OpenCode: Guía de Integración MCP

## 📌 Caso de Uso: Solución de Problemas de Conexión MCP

Este documento detalla cómo integrar **Hipocampo MCP Server** con **OpenCode**, incluyendo soluciones a problemas comunes como:
- El servidor MCP no se mantiene en ejecución.
- Errores de ruta en scripts o variables de entorno.
- Configuración incorrecta en `opencode.jsonc`.

---

## 🔍 Problema Inicial

Al configurar Hipocampo MCP con OpenCode, el servidor:
1. **No se iniciaba automáticamente** con OpenCode.
2. **Se cerraba inmediatamente** al ejecutarse en modo `stdio` (por falta de cliente MCP conectado).
3. **Tenía rutas incorrectas** en la configuración de OpenCode (`/home/usuario/hipocampo_mcp_server.py` vs `/home/usuario/hipocampo/scripts/hipocampo_mcp_server.py`).

---

## ✅ Solución Paso a Paso

### 1️⃣ Verificar Requisitos Previos

Asegúrate de que:
- **PostgreSQL 17** esté instalado con las extensiones `vector` y `pg_trgm`.
- La base de datos `hipocampo_db` exista y tenga las tablas `memoria_vectorial` y `memory_items`.
- **Python 3.13+** y las dependencias de `requirements.txt` estén instaladas.

```bash
# Verificar extensiones de PostgreSQL
psql -d hipocampo_db -c "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');"

# Verificar tablas
psql -d hipocampo_db -c "SELECT tablename FROM pg_tables WHERE tablename IN ('memoria_vectorial', 'memory_items');"
```

---

### 2️⃣ Configurar Variables de Entorno

El servidor MCP requiere las siguientes variables de entorno. Puedes definirlas en:
- Un archivo `.env` en el directorio del proyecto.
- Directamente en el sistema (para el usuario que ejecuta OpenCode).

#### Ejemplo de `.env` (mínimo para MCP):
```env
# === PostgreSQL (conexión local por socket Unix) ===
DB_NAME=hipocampo_db
DB_USER=tu_usuario_postgres
DB_PASSWORD=  # Dejar vacío si usas autenticación por socket
DB_HOST=/var/run/postgresql

# === API NVIDIA (para embeddings con nv-embedqa-e5-v5) ===
# === API NVIDIA (para embeddings) ===
NVIDIA_API_KEY=nvapi-TuClaveAqui
```

> ⚠️ **Nota:** Si usas **NVIDIA NIM** para embeddings (recomendado), la `NVIDIA_API_KEY` es **obligatoria**.

---

### 3️⃣ Configurar OpenCode para Hipocampo MCP

Edita el archivo de configuración de OpenCode (`~/.config/opencode/opencode.jsonc`) y agrega la sección `mcp`:

```jsonc
{
  "mcp": {
    "hipocampo": {
      "type": "local",
      "command": ["/home/usuario/tu_venv/bin/python3", "/home/usuario/hipocampo_mcp_server.py"],
      "enabled": true,
      "timeout": 120000
    }
  }
}
```

#### Ajustes Clave:
- **`command`**: Debe apuntar al **script copiado** en la raíz del home (ej. `/home/usuario/hipocampo_mcp_server.py`).
- **`timeout`**: Aumentado a `120000` (2 minutos) para evitar cortes en búsquedas complejas.
- **`enabled`**: `true` para activar el servidor al iniciar OpenCode.

---

### 4️⃣ Preparar el Script del Servidor MCP

El script `scripts/hipocampo_mcp_server.py` usa rutas **relativas** para buscar scripts auxiliares. Para que funcione con OpenCode, copia el script a la raíz del directorio de usuario:

```bash
# Copiar el script a la raíz del usuario
cp hipocampo/scripts/hipocampo_mcp_server.py hipocampo_mcp_server.py

# Crear enlaces simbólicos para scripts auxiliares (en la raíz)
ln -sf "$PWD/hipocampo/scripts/hipocampo_search.py" hipocampo_search.py
ln -sf "$PWD/hipocampo/scripts/hipocampo_health.py" hipocampo_health.py
ln -sf "$PWD/hipocampo/scripts/hipocampo_stats.py" hipocampo_stats.py
ln -sf "$PWD/hipocampo/scripts/hipocampo_dedup.py" hipocampo_dedup.py
ln -sf "$PWD/hipocampo/scripts/hipocampo_checkpoint.py" hipocampo_checkpoint.py
```

#### Alternativa: Usar Rutas Absolutas
Si prefieres no usar enlaces simbólicos, edita el script copiado y reemplaza:
```python
# Antes (rutas dinámicas)
SEARCH_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hipocampo_search.py")
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

# Después (rutas absolutas)
   SEARCH_SCRIPT = "/home/usuario/.gemini/scripts/hipocampo_search.py"
   ENV_PATH = "/home/usuario/.env"
```

---

### 5️⃣ Probar el Servidor MCP Manualmente

Antes de reiniciar OpenCode, verifica que el servidor funcione:

```bash
# Iniciar el servidor en modo stdio (para OpenCode)
/home/usuario/tu_venv/bin/python3 /home/usuario/hipocampo_mcp_server.py
```

Si el servidor **no muestra errores**, está listo para ser usado por OpenCode.

> 🔹 **Nota:** En modo `stdio`, el servidor **no mostrará salida** hasta que un cliente MCP (como OpenCode) se conecte.

---

### 6️⃣ Reiniciar OpenCode

1. **Detener OpenCode** si está en ejecución.
2. **Iniciar OpenCode** nuevamente:
   ```bash
   opencode
   ```
3. **Verificar que el servidor MCP esté activo**:
   ```bash
   pgrep -f hipocampo_mcp_server
   ```

---

### 7️⃣ Solución de Problemas Comunes

#### ❌ Problema: El servidor MCP se cierra inmediatamente
**Causa:** OpenCode no está conectado al servidor o el script tiene errores.
**Solución:**
- Verifica que el script no tenga errores de sintaxis:
  ```bash
   /home/usuario/tu_venv/bin/python3 -m py_compile /home/usuario/hipocampo_mcp_server.py
  ```
- Revisa los logs de OpenCode:
  ```bash
  tail -f ~/.local/share/opencode/logs/*.log
  ```

#### ❌ Problema: `NVIDIA_API_KEY` no encontrada
**Causa:** El archivo `.env` no está en la ruta esperada o la variable no está definida.
**Solución:**
- Asegúrate de que el archivo `.env` exista (ej. en `~/.env` o `/home/usuario/scripts/.env`) **y contenga** `NVIDIA_API_KEY`.
- O define la variable directamente en el sistema:
  ```bash
  echo 'export NVIDIA_API_KEY="nvapi-TuClaveAqui"' >> ~/.bashrc
  source ~/.bashrc
  ```

#### ❌ Problema: Error de conexión a PostgreSQL
**Causa:** Credenciales incorrectas o el socket de PostgreSQL no está disponible.
**Solución:**
- Verifica que PostgreSQL esté en ejecución:
  ```bash
  sudo systemctl status postgresql
  ```
- Prueba la conexión manualmente:
  ```bash
  psql -d hipocampo_db -U tu_usuario -h /var/run/postgresql -c "SELECT 1;"
  ```

---

## 📝 Configuración Recomendada para `.env`

Para evitar problemas, usa este template (ej. en `~/.env` o `~/.config/hipocampo/.env`):

```env
# === PostgreSQL ===
DB_NAME=hipocampo_db
DB_USER=tu_usuario_postgres
DB_PASSWORD=  # Vacío si usas autenticación por socket
DB_HOST=/var/run/postgresql

# === NVIDIA NIM (Embeddings) ===
NVIDIA_API_KEY=nvapi-TU_CLAVE_AQUI

# === OpenAI (Opcional, para compatibilidad) ===
OPENAI_API_KEY=sk-...
```

---

## 🔧 Configuración Avanzada: Servicio Systemd

Si prefieres que el servidor MCP **siempre esté activo** (independientemente de OpenCode), crea un servicio systemd:

1. **Copia el archivo de servicio**:
   ```bash
   cp hipocampo/scripts/hipocampo-mcp.service ~/.config/systemd/user/
   ```

2. **Edita el archivo** para usar la ruta correcta:
   ```ini
   [Unit]
   Description=Hipocampo MCP Server
   After=network.target

   [Service]
   Type=simple
   ExecStart=/home/usuario/tu_venv/bin/python3 /home/usuario/hipocampo_mcp_server.py --sse 8001
   WorkingDirectory=/home/usuario
   Restart=on-failure
   RestartSec=5
   # No necesita EnvironmentFile: el script carga .env automáticamente con load_dotenv()

   [Install]
   WantedBy=default.target
   ```

3. **Habilita y inicia el servicio**:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now hipocampo-mcp.service
   ```

4. **Verifica el estado**:
   ```bash
   systemctl --user status hipocampo-mcp.service
   ```

---

## 🧪 Prueba de Integración

Para confirmar que todo funciona, ejecuta una búsqueda manual usando el script de búsqueda:

```bash
   /home/usuario/tu_venv/bin/python3 /home/usuario/scripts/hipocampo_search.py "OpenCode MCP"
```

Si ves resultados con scores y referencias a `memoria_vectorial` o `memory_items`, **¡la integración es exitosa!**

---

## 📚 Herramientas MCP Disponibles

Una vez conectado, OpenCode tendrá acceso a las siguientes herramientas:

| Herramienta | Descripción | Parámetros |
|-------------|-------------|------------|
| `search_hipocampo` | Búsqueda híbrida (semántica + léxica) en ambas tablas de memoria. | `query` (string) |
| `quick_hipocampo_search` | Alias corto de `search_hipocampo`. | `query` (string) |
| `save_hipocampo` | Guarda datos técnicos en `memoria_vectorial`. | `content`, `memory_type`, `code`, `categories` |
| `profile_hipocampo` | Guarda datos de perfil en `memory_items`. | `summary`, `extra`, `categories` |

---

## 🔗 Recursos Adicionales

- [Guía del Servidor MCP](mcp-server-guide.md)
- [Documentación de FastMCP](https://github.com/modelcontextprotocol/python-sdk)
- [OpenCode MCP Configuration](https://opencode.ai/docs/mcp)

---

## 📝 Notas Finales

- **Siempre usa rutas absolutas** en configuraciones de producción.
- **Verifica permisos**: Asegúrate de que el usuario que ejecuta OpenCode tenga acceso a los archivos y directorios.
- **Monitorea logs**: Usa `journalctl --user -u hipocampo-mcp.service -f` para servicios systemd.

---

*¿Problemas? Revisa la [sección de solución de problemas](#solución-de-problemas-comunes) o abre un issue en [GitHub](https://github.com/carrasquelalex1/hipocampo/issues).*
