# Auto-MeJORA MCP — Implementation Plan

> **Goal:** Hacer que Hipocampo MCP se auto-diagnostique, auto-repare y auto-optimice sin intervención manual.

**Architecture:** 3 fases progresivas: (1) Health check + auto-repair, (2) Performance tuning dinámico, (3) Memory lifecycle management. Cada fase añade herramientas MCP y scripts autónomos.

**Tech Stack:** Python, FastMCP, PostgreSQL 17, pgvector, NVIDIA NIM API, systemd

---

### Fase 1: Autodiagnóstico y Auto-Reparación

**Objetivo:** El servidor MCP verifica su propia salud al iniciar y periódicamente.

**Archivos:**
- Create: `scripts/hipocampo_health.py`
- Modify: `scripts/hipocampo_mcp_server.py`

**Herramientas MCP a añadir:**
- `hipocampo_health` → ejecuta health check completo
- `hipocampo_auto_repair` → intenta reparar problemas detectados

**Health checks:**
1. PostgreSQL conexión (socket Unix)
2. NVIDIA API key presente y funcional (test embedding)
3. Tablas `memoria_vectorial` y `memory_items` existen
4. Permisos de escritura en archivos de log
5. Espacio en disco suficiente (>1GB)
6. Latencia de embedding < 5s

**Auto-repair:**
1. Si PostgreSQL caído → intentar reiniciar servicio
2. Si API key falta → loggear warning con instrucciones
3. Si tablas faltan → ejecutar esquema.sql

---

### Fase 2: Optimización Dinámica

**Objetivo:** Ajustar thresholds y pesos automáticamente según rendimiento real.

**Archivos:**
- Modify: `scripts/hipocampo_mcp_server.py`
- Modify: `scripts/hipocampo_calibrate.py`

**Mejoras:**
- Tool `hipocampo_stats` → muestra métricas de rendimiento
- Auto-ajuste de thresholds SSC basado en latencia promedio
- Programar calibración automática cada 24h
- Logging de latencia por query

---

### Fase 3: Gestión del Ciclo de Vida de la Memoria

**Objetivo:** Mantener la memoria limpia, sin duplicados y bien organizada.

**Archivos:**
- Create: `scripts/hipocampo_dedup.py`
- Modify: `scripts/hipocampo_checkpoint.py`

**Mejoras:**
- Tool `hipocampo_dedup` → detecta y fusiona memorias duplicadas
- Tool `hipocampo_maintenance` → ejecuta ciclo completo (dedup + checkpoint + calibrate)
- Programar mantenimiento automático semanal

---

### Ejecución

Cada tarea se completa en orden. Al finalizar cada fase, se guarda progreso en Hipocampo.
