#!/usr/bin/env python3
"""hipocampo_embed_sweeper.py — Barredor de embeddings desincronizados.

Auto-reparación (reconciliación) de memoria_vectorial. El estado pendiente vive
en la BD, no en la memoria de ningún proceso — por eso funciona tras un corte
de luz, un apagón o un crash del servicio MCP:

- Candidatos: filas con `embedding IS NULL` (invisibles a la búsqueda vectorial,
  salvo las rebajadas a propósito al tier WARM por hipocampo_budget, que llevan
  `metadatos.warm_since`) o cuyo `md5(left(contenido, MAX_EMBED_CHARS))` no
  coincide con la firma `metadatos.embedding_src_md5` (el contenido con el que
  se generó el embedding actual). Esa firma la escriben
  _finalize_save_bg/_finalize_update_bg al completar cada embedding.
- Repara cada candidato regenerando el embedding con reintentos y la misma
  guarda anti-carrera que save/update (`AND contenido = %s`), y escribe la
  firma nueva en el mismo UPDATE (quitando `warm_since`: la fila vuelve a HOT).
- Ritmo suave (pocos por corrida + pausa) para no arrastrar a Ollama; tope de
  tiempo por corrida; lo que quede, lo retoma la próxima pasada.

Pensado para el timer de systemd `hipocampo-embed-sweeper.timer` (cada 15 min;
`OnBootSec` lo corre también 3 min después de cada arranque — el catch-up tras
un apagón).

Migración de una BD existente (filas con embedding pero sin firma): correr UNA
VEZ `--marcar-al-dia` (asume que los embeddings actuales corresponden al
contenido actual) ANTES de habilitar el timer; si no, el barredor trataría
todas las filas antiguas como pendientes y las re-embebe de a 8 por corrida.

Uso:
    python3 scripts/hipocampo_embed_sweeper.py [--dry-run] [--max-rows N]
    python3 scripts/hipocampo_embed_sweeper.py --marcar-al-dia

Variables de entorno:
    SWEEP_MAX_ROWS        filas por corrida (default 8)
    SWEEP_MAX_SECONDS     tope de tiempo por corrida en segundos (default 600)
    SWEEP_PAUSE_S         pausa entre filas reparadas (default 2.0)
    SWEEP_EMBED_TIMEOUT_S timeout paciente por embedding (default 900)

Sale 0 si pudo trabajar (los pendientes restantes se reportan y los retoma la
próxima corrida); sale 1 solo si no pudo completar la corrida.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import (
    MAX_EMBED_CHARS,
    contenido_firma,
    get_conn,
    get_embedding_with_retries,
    load_config,
)


def _log_stdout(msg):
    print(msg, flush=True)


CANDIDATOS_SQL = """
    SELECT id,
           contenido,
           (embedding IS NULL) AS sin_embedding,
           metadatos->>'embedding_src_md5' AS firma_guardada,
           md5(left(contenido, %s)) AS firma_contenido
    FROM memoria_vectorial
    WHERE contenido IS NOT NULL
      AND ((embedding IS NULL AND metadatos->>'warm_since' IS NULL)
           OR metadatos->>'embedding_src_md5' IS DISTINCT FROM md5(left(contenido, %s)))
      {filtro_ids}
    ORDER BY (embedding IS NULL) DESC, id
    LIMIT %s
"""

PENDIENTES_SQL = """
    SELECT count(*) FROM memoria_vectorial
    WHERE contenido IS NOT NULL
      AND ((embedding IS NULL AND metadatos->>'warm_since' IS NULL)
           OR metadatos->>'embedding_src_md5' IS DISTINCT FROM md5(left(contenido, %s)))
"""

MARCAR_SQL = """
    UPDATE memoria_vectorial
    SET metadatos = COALESCE(metadatos, '{}'::jsonb)
                    || jsonb_build_object('embedding_src_md5', md5(left(contenido, %s)))
    WHERE contenido IS NOT NULL
      AND embedding IS NOT NULL
      AND metadatos->>'embedding_src_md5' IS NULL
"""


def _reparar_fila(cur, row_id, contenido, sin_embedding, embed_fn, timeout_s):
    """Regenera el embedding de una fila y escribe la firma. Devuelve (estado, detalle)."""
    try:
        embedding = embed_fn(contenido, timeout_s=timeout_s)
    except Exception as e:
        return "error", f"embedding falló: {e}"
    if embedding is None:
        return "error", "embedding no disponible"
    # El failover de modelo puede devolver tuple: psycopg2 adapta tuple como
    # record y (record)::vector falla con CannotCoerce — coerciona a list SIEMPRE.
    embedding = list(embedding)

    firma = contenido_firma(contenido)
    try:
        cur.execute(
            """
            UPDATE memoria_vectorial
            SET embedding = %s::vector(1024),
                metadatos = (COALESCE(metadatos, '{}'::jsonb)
                             || jsonb_build_object('embedding_src_md5', %s)) - 'warm_since'
            WHERE id = %s AND contenido = %s
            """,
            (embedding, firma, row_id, contenido),
        )
    except Exception as e:
        # Aislar errores por fila (p. ej. dimensión inesperada): rollback y seguir
        # con las demás — una fila problemática no debe abortar toda la corrida.
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return "error", f"UPDATE falló: {e}"
    if cur.rowcount:
        return "reparado", "sin embedding" if sin_embedding else "firma desactualizada"
    return "saltado", "el contenido cambió durante el barrido"


def barrer(
    max_rows=None,
    max_seconds=None,
    pause_s=None,
    timeout_s=None,
    embed_fn=None,
    ids=None,
    dry_run=False,
    log=None,
):
    """Una pasada del barredor. Devuelve el resumen (dict).

    *ids* restringe la pasada a ciertos ids (pruebas / reparación puntual).
    *embed_fn* permite inyectar el generador de embeddings en pruebas.
    """
    if log is None:
        log = _log_stdout
    max_rows = int(max_rows if max_rows is not None else os.getenv("SWEEP_MAX_ROWS", "8"))
    max_seconds = float(max_seconds if max_seconds is not None else os.getenv("SWEEP_MAX_SECONDS", "600"))
    pause_s = float(pause_s if pause_s is not None else os.getenv("SWEEP_PAUSE_S", "2"))
    timeout_s = float(timeout_s if timeout_s is not None else os.getenv("SWEEP_EMBED_TIMEOUT_S", "900"))
    embed_fn = embed_fn or get_embedding_with_retries

    resumen = {"revisados": 0, "reparados": 0, "saltados": 0, "errores": 0, "pendientes": None, "motivo_fin": "ok"}
    t0 = time.monotonic()

    filtro_ids = "AND id = ANY(%s)" if ids else ""
    if ids:
        params = (MAX_EMBED_CHARS, MAX_EMBED_CHARS, list(ids), max_rows)
    else:
        params = (MAX_EMBED_CHARS, MAX_EMBED_CHARS, max_rows)

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(CANDIDATOS_SQL.format(filtro_ids=filtro_ids), params)
        candidatos = cur.fetchall()
        log(f"🧹 Barrido de embeddings: {len(candidatos)} candidato(s) (tope {max_rows}/corrida)")
        for row_id, contenido, sin_embedding, firma_guardada, firma_contenido in candidatos:
            if time.monotonic() - t0 > max_seconds:
                resumen["motivo_fin"] = "tope de tiempo alcanzado — quedan pendientes para la próxima corrida"
                break
            resumen["revisados"] += 1
            if dry_run:
                log(
                    f"   · [dry-run] id={row_id} sin_embedding={sin_embedding} "
                    f"firma_guardada={firma_guardada} firma_contenido={firma_contenido}"
                )
                continue
            estado, detalle = _reparar_fila(cur, row_id, contenido, sin_embedding, embed_fn, timeout_s)
            if estado == "reparado":
                resumen["reparados"] += 1
                log(f"   ✅ id={row_id} reparado — {detalle}")
            elif estado == "saltado":
                resumen["saltados"] += 1
                log(f"   ⏭️ id={row_id} saltado — {detalle}")
            else:
                resumen["errores"] += 1
                log(f"   ⚠️ id={row_id} error — {detalle}")
            conn.commit()
            time.sleep(pause_s)

        cur.execute(PENDIENTES_SQL, (MAX_EMBED_CHARS,))
        resumen["pendientes"] = cur.fetchone()[0]
        cur.close()
    finally:
        conn.close()

    dt = time.monotonic() - t0
    log(
        "🧹 Resumen: revisados={revisados} reparados={reparados} saltados={saltados} "
        "errores={errores} pendientes={pendientes} tiempo={dt:.1f}s — {motivo_fin}".format(dt=dt, **resumen)
    )
    return resumen


def marcar_al_dia(log=None):
    """Marca como 'al día' las filas que tienen embedding pero no firma (migración).

    Asume que su embedding actual corresponde al contenido actual — solo tiene
    sentido UNA VEZ, al migrar una BD existente a esta versión.
    """
    if log is None:
        log = _log_stdout
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(MARCAR_SQL, (MAX_EMBED_CHARS,))
        n = cur.rowcount
        conn.commit()
        cur.close()
    finally:
        conn.close()
    log(
        f"✅ Firma embedding_src_md5: {n} fila(s) marcadas como al día "
        "(se asume que su embedding corresponde al contenido actual)"
    )
    return n


def main():
    parser = argparse.ArgumentParser(description="Barredor de embeddings desincronizados del Hipocampo")
    parser.add_argument("--dry-run", action="store_true", help="solo listar candidatos, sin reparar")
    parser.add_argument("--max-rows", type=int, default=None, help="filas máximas en esta corrida")
    parser.add_argument(
        "--marcar-al-dia",
        action="store_true",
        help="migración (una vez): marca con firma las filas que ya tienen embedding (asume que están al día)",
    )
    args = parser.parse_args()

    load_config()
    try:
        if args.marcar_al_dia:
            marcar_al_dia()
        else:
            barrer(max_rows=args.max_rows, dry_run=args.dry_run)
    except Exception as e:
        print(f"❌ Barredor: no se pudo completar la corrida: {e}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
