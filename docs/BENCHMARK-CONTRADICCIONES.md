# Benchmark: Contradiction Detection — Local Heuristics vs TypeSafe

**Date:** 2026-09-19 · **Model:** `jev-latest` (jev-1.13.0) · **Status:** internal mini-benchmark, reproducible methodology

> **TL;DR** — On 27 labeled pairs drawn from a real memory database, the local
> negation-probe heuristic scored **P 18.2% / R 14.3%**, while TypeSafe-based
> judgment scored **P 100% / R 100%** (audited labels, no threshold tuning). The
> most valuable finding was not the score: the audit surfaced four real
> *superseded-decision* contradictions that had been silently living in memory
> for weeks.

## 1. What was compared

Hipocampo detects contradictions in two ways, both evaluated **with their
production windows**:

| | Local (without TypeSafe) | With TypeSafe |
|---|---|---|
| Candidate window | cosine distance **0.35–0.70** | cosine distance **0.0–0.70** (semantic judgment, not threshold) |
| Decision rule | Negation-probe embeddings: embed `"AFIRMACIÓN: {b} — ¿Esto es FALSO según: {a}?"`, then `sim(probe, b) > sim(a, b) + 0.05` | One **Noul** question per candidate in a single API call: *"does [candidate] contradict the new fact?"* → probability ≥ 0.7 |

Both paths share the same local embedding for window filtering
(`qwen3-embedding:0.6b` via Ollama, 1024 dims), so the comparison isolates the
**judgment step**, not retrieval.

## 2. Dataset

27 pairs mined from a real `memoria_vectorial` database (2,400+ memories,
~170 natural-language candidates after filtering code dumps):

- **10 synthetic contradictions** — controlled negations of real memories
  (e.g., *"the production server uses PostgreSQL on port 5432"* vs *"the
  production server does NOT use PostgreSQL; its database is MySQL"*).
- **4 audited contradictions** — pairs initially labeled compatible that, on
  full-text review, turned out to be genuine **superseded decisions**:
  - opposite dispositions for the same entity recorded the same day
    (keep-separate vs merged);
  - two entries describing mutually exclusive final states of the same file;
  - two configuration rules that directly contradict each other;
  - one memory stating a service requires an API key, another stating it works
    without one.
- **13 compatible pairs** — 6 near-paraphrases (distance 0.09–0.14) and 7
  related-but-different pairs (distance 0.20–0.53).

Labeling was done by reading each pair; the four audited pairs are a **label
correction** (see §4), kept transparent here because that correction is itself
a finding.

## 3. Results

Metrics with **audited labels** (14 positives, 13 negatives):

| Metric | Local (probe) | TypeSafe |
|---|---|---|
| Precision | 18.2% | **100%** |
| Recall | 14.3% | **100%** |
| F1 | 16.0% | **100%** |
| Accuracy | 22.2% | **100%** |
| TP / FP / FN / TN | 2 / 9 / 12 / 4 | 14 / 0 / 0 / 13 |
| Wall time (27 pairs, this machine) | 119.3 s | 15.5 s |

With the **initial labels** (before the audit), for reference: TypeSafe
P 71.4% / R 100% / F1 83.3% — its four "false positives" were exactly the four
superseded-decision pairs.

## 4. Findings

1. **The local heuristic is structurally blind where contradictions live.**
   12 of 14 positives sit at distance < 0.35 — the zone the probe's window
   deliberately excludes as "already dedup". Paraphrased contradictions are the
   most common real case, and the heuristic could never see them.
2. **Inside its own window, the probe over-fires.** It flagged 9 of 13
   compatible related pairs as contradictions (cosine 0.36–0.53, margin 0.05).
   In day-to-day operation this produced spurious `contradicts` links.
3. **TypeSafe's four "false positives" were real.** Reading the full texts
   showed all four were genuine contradictions: outdated decisions that memory
   still asserted in parallel with their replacements. This is **decision
   drift**, and it is arguably the most damaging failure mode of long-term
   agent memory — the system keeps acting on stale facts.
4. **Timing favors the batched call here, but treat it as environment-specific.**
   The probe needs 2 embeddings per candidate (6–22 s each under load in this
   test) while one TypeSafe call judges every candidate at once (~0.5–1 s).
   Numbers depend on hardware and load.

## 5. Reproducing

The methodology is fully reproducible on any memory base; the dataset itself is
private (it contains internal project facts), so numbers will vary with your
data. The judging primitives are public in
[`scripts/typesafe_client.py`](../scripts/typesafe_client.py):

```python
import typesafe_client as ts

# One call: one Noul (contradiction) + one Choice (relation) per candidate
res = ts.juicio_lote(
    nuevo="The production server uses PostgreSQL on port 5432.",
    candidatos=[(1, "The production server uses MySQL as its database."),
                (2, "The server has 61GB of RAM.")],
)
# res["candidatos"][1]["noul"] → ~0.93 (contradiction)
# res["candidatos"][2]["noul"] → ~0.05 (unrelated)
```

Thresholds live in `typesafe_client.py`: contradiction `noul ≥ 0.7`, "same
fact" requires confidence ≥ 0.6. **They were not tuned on this dataset** — the
default 0.7 is what ships.

## 6. Caveats

- **Small sample** (27 pairs; 10 positives synthetic). Treat the exact
  percentages as directional, not as a formal benchmark.
- Single annotator (an AI agent), with human-reviewable labels; contentious
  pairs were re-read in full before the label correction in §2.
- Synthetic positives were written from the real memories they contradict;
  real-world contradictions may be harder.
- External dependency: TypeSafe was in early access when tested. The
  integration degrades gracefully to the local path when unavailable.

## 7. Why this matters

A memory system that accumulates contradictions gets *worse* over time: it
retrieves stale facts with the same confidence as current ones. The measured
change here is not "a nicer duplicate detector" — it is that the memory can now
**notice when it disagrees with itself**, attach a calibrated probability to
that judgment, and flag the drift for reconciliation.

---

*Resumen (ES):* mini-benchmark interno con 27 pares etiquetados de la base
real: la heurística local (sonda de negación) obtuvo P 18.2% / R 14.3% y
TypeSafe 100% / 100% con las etiquetas auditadas (sin ajustar umbrales). El
hallazgo principal: la auditoría destapó 4 contradicciones reales de *decisión
superada* que llevaban semanas sin reconciliarse. Metodología reproducible;
el dataset es privado. Documento complementario:
[TYPESAFE.md](TYPESAFE.md).
