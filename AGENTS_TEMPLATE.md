# AGENTS.md Template — Hipocampo Integration

> Append the relevant sections below into your `AGENTS.md` (OpenCode), `CLAUDE.md` (Claude Code), `.cursorrules` (Cursor), or equivalent to enable full Hipocampo memory capabilities for your AI agent. Pick only what you need — keep your existing instructions.
>
> These are **generic instructions** — no credentials, no paths, no personal data. Safe to copy.

---

## 🧠 Hipocampo — Full Usage Required

Hipocampo is not a sticky note. It is an **external brain** with 22+ MCP tools. **Use all of them, not just save/search.**

### Search & Retrieve
- `search_hipocampo(query)` — Hybrid semantic + lexical search (BIRE v3.7). Use before answering any question about past work, user preferences, or project state.
- `quick_hipocampo_search(query)` — Short alias for rapid queries.
- `preload_context(project_path, k=8)` — At session start, extract project keywords, search relevant memories, return compressed summary.
- `compress_hipocampo(query, k=5, method="hybrid", budget_ratio=1.0)` — Search + compress results before passing to another LLM. Saves 20-50% tokens.
- `search_code(query, language="")` — Vector search in indexed project code. Returns real snippets with file paths.

### Save & Profile
- `save_hipocampo(content, memory_type, code, categories, auto_link=False, nivel="episodica")` — Save to technical memory. Use `auto_link=True` to auto-discover similar memories. Use `nivel="automatica"` for permanent rules.
- `profile_hipocampo(summary, extra, categories)` — Save user personal data (preferences, family, location, etc.) in profile memory.

### Memory Graph — Explore Connections
- `link_hipocampo(source_id, target_id, relation_type, weight)` — Manually link two related memories. Types: `related`, `follow_up`, `part_of`, `references`, `similar`, `chain`.
- `graph_hipocampo(node_id, depth=2)` — Explore the memory graph as a BFS tree from a node. Use `node_id=0` for overview.
- `path_hipocampo(from_id, to_id, max_depth=5)` — Find the shortest path between two memories.

### Hierarchy & Consolidation
- `set_nivel_hipocampo(id, nivel)` — Promote important memories: `episodica` (default) → `semantica` (protected) → `automatica` (permanent, never deleted).
- `consolidate_hipocampo(min_age_days=7, dry_run=True)` — Migrate old episodic memories to semantic level.

### Maintenance (run periodically)
- `hipocampo_health()` — Check system health (PostgreSQL, API, disk, extensions).
- `hipocampo_stats()` — View performance metrics and optimization recommendations.
- `hipocampo_dedup(merge=False)` — Detect and optionally merge duplicate memories.
- `hipocampo_checkpoint(dry_run=True)` — Compress old memories with logarithmic decay.
- `hipocampo_maintenance()` — Full cycle: health → dedup → checkpoint → tune.

### Webhooks (for event-driven agents)
- `watch_hipocampo(pattern, webhook_url)` — Register a webhook that fires on save/update/delete matching a pattern.
- `list_watches()` / `unwatch_hipocampo(id)` — Manage webhooks.

---

## 🔁 Error Learning Cycle

Prevents repeating mistakes across sessions:

```markdown
1. Before running any command, search: `search_hipocampo("error <command> <context>")`
2. If a similar error is found, apply the documented solution and skip the failing attempt
3. If the command fails (exit code != 0, timeout, "error"/"failed" in output):
   - Save to Hipocampo:
     `save_hipocampo(content="Error: {stderr[:500]}. Attempt: {what was tried}. Result: {what happened}.", memory_type="decision", code="error_<hash>", categories=["bugfix", "<language/tool>"])`
```

## 🧬 Error Prevention via Triggers (Proactive)

```markdown
- Before editing code in a known project, search: `search_hipocampo("trigger:<project> trigger:<language> trigger:<tech>")`
- Tag critical errors with contextual triggers and elevate to `nivel="automatica"`
- Automatic rules surface on matching context → error avoided BEFORE it happens
```

## 🛡️ Code Immune System — Regression Protection

```markdown
1. SNAPSHOT: Before editing a fragile file, save what works and how to verify
2. VERIFY: After editing, confirm the verification passes
3. IMMUNIZE: If something broke, save a permanent `automatica` rule capturing cause, symptom, and fix
```

### Fragile files (pre-loaded)
Before touching: `search_hipocampo("trigger:regression trigger:<filename>")`

---

## ⚙️ MCP Server Configuration

Add to your `opencode.json` / `claude.json`:

```json
{
  "mcpServers": {
    "hipocampo": {
      "url": "https://alexbell1-hipocampo-mcp.hf.space/mcp",
      "type": "streamable-http"
    }
  }
}
```

For local usage with persistent storage, see [Quick Start](https://github.com/carrasquelalex1/hipocampo#-quick-start).

---

> 🧠 **Principle:** If you only save and search, you're using 10% of Hipocampo. The graph, hierarchy, compression, consolidation, maintenance, webhooks, and code RAG are what make it a true external brain.
>
> **No credentials. No paths. No personal data.** This template is safe to copy and share.
