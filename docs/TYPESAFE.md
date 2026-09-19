# Optional: TypeSafe (System One) Integration

Hipocampo can optionally delegate semantic **judgments** — not text generation — to
[TypeSafe](https://docs.typesafe.ai/). TypeSafe's `jev` model answers typed questions
(*Choice / Score / Noul*) with calibrated probabilities, and many questions can be
batched into a single parallel call with sub-second latency.

> **Requirements**: a TypeSafe API key (early access). Without a key the
> integration stays dormant — Hipocampo keeps working with its local heuristics
> until you enable it.

Why it is worth enabling once you have access:

- **Calibrated probabilities** instead of embedding thresholds — the model
  returns a `noul`/`confidence` value your code can gate on.
- **One batched call** judges every candidate: a post-save contradiction audit
  (3 candidates) or a dedup group costs a single sub-second request.
- **Finds contradictions between close paraphrases** (cosine distance < 0.35)
  that the local probe's window cannot see, because the judgment is semantic.
- **Gates destructive merges**: `dedup(merge=True)` only merges groups TypeSafe
  confirms as the *same fact*; everything else is skipped and logged.

This integration upgrades three decision points that otherwise rely on embedding
heuristics. It is **opt-in and safe by default**: when disabled or unreachable,
Hipocampo falls back to its local methods — saves and searches never block.

## What it changes

| Code path | Without TypeSafe | With TypeSafe |
|---|---|---|
| `_detectar_contradicciones()` (`hipocampo_mcp_server.py`) | Negation-probe embeddings: 2 embeddings per candidate + heuristic margin | One **Noul** per candidate in a single API call → calibrated contradiction probability (threshold `0.7`) |
| `_check_dedup_semantic()` (`hipocampo_mcp_server.py`) | Cosine `> 0.9` warns "duplicate" | Same embedding proposes the candidate, then a **Choice** (*mismo / relacionado / distinto*) confirms before warning |
| `full_dedup_merge()` (`hipocampo_dedup.py`) | Merges every group above the cosine threshold (destructive) | `_typesafe_confirma_grupo()` confirms each group first — unconfirmed groups are skipped |

Additional details:

- When TypeSafe is active, contradiction search uses a **wider candidate window**
  (cosine distance `0.0–0.70` instead of `0.35–0.70`), because the judgment is
  semantic rather than threshold-based. This catches contradictions between close
  paraphrases of the same fact, which typically fall in the dedup zone.
- The memory itself is always excluded from candidates (`exclude_id`).
- Post-save audit is bounded: `max_probes=3` (one API call).
- On TypeSafe failure mid-audit, the fallback probe runs with the **original
  narrow window**, preserving the previous behavior exactly.

## Configuration

Add to `~/.hipocampo/.env` (loaded by the systemd service):

```bash
HIPOCAMPO_TYPESAFE=1
```

The API key is read from (in order):

1. `TYPESAFE_API_KEY` environment variable.
2. Key file — `TYPESAFE_KEY_FILE` or default `~/.config/typesafe/api_key`.

Other optional variables:

| Variable | Default | Purpose |
|---|---|---|
| `TYPESAFE_API_URL` | `https://api.typesafe.ai/v1/systemone` | API endpoint |
| `TYPESAFE_MODEL` | `jev-latest` | Model id |
| `TYPESAFE_TIMEOUT` | `10` | HTTP timeout (seconds) |
| `HIPOCAMPO_TYPESAFE` | *(unset)* | `1`/`true`/`yes`/`on` enables the integration |

Thresholds live in `scripts/typesafe_client.py`:
`UMBRAL_CONTRADICCION = 0.7`, `MIN_CONF_MISMO_HECHO = 0.6`.

## Files

- `scripts/typesafe_client.py` — minimal stdlib client (no dependencies):
  `enabled()`, `ask()`, `contradicciones_batch()`, `relacion()`, `mismo_hecho()`.
  Never raises to the caller; returns `None` on any failure.
- `scripts/hipocampo_mcp_server.py` — imports it optionally (`_ts`), wires it into
  contradiction detection and semantic dedup.
- `scripts/hipocampo_dedup.py` — merge gate for semantic groups.

## Verification

```bash
set -a; source ~/.hipocampo/.env; set +a
cd scripts
python3 - <<'EOF'
import typesafe_client as ts
print("enabled:", ts.enabled())
print(ts.contradicciones_batch(
    "The production server uses PostgreSQL on port 5432.",
    [(1, "The production server uses MySQL as its database."),
     (2, "The server has 61GB of RAM.")],
))
EOF
```

Expected: `{1: 0.9xx}` (only the contradiction). With `HIPOCAMPO_TYPESAFE=0`,
`enabled()` returns `False` and all code paths use the local heuristics.

## Privacy

Judge calls send the compared memory texts to TypeSafe's API — the same trust model
as the configured LLM compression endpoint. Disable the flag to keep all memory
content local.
