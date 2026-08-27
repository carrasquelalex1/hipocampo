#!/usr/bin/env python3
"""hipocampo_index_project.py — RAG de código fuente v1.0

Indexa archivos de proyecto (PHP, JS, TS, PY, SQL, HTML, CSS, JSON, YAML)
como recuerdos con embedding en memoria_vectorial.

Cada archivo se divide en chunks significativos (funciones, clases, bloques)
y se almacena con metadatos: file_path, language, line_start, line_end.

Estrategia:
  - Primera corrida: indexa todo
  - Corridas subsiguientes: solo archivos modificados (mtime)
  - Archivos eliminados: se marcan como obsoletos

Uso:
    python3 scripts/hipocampo_index_project.py /ruta/al/proyecto [--force] [--ext .php .js]

Requiere: tree_sitter (opcional, mejora chunking)
"""

import os
import json
import sys
import hashlib
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, get_embedding, load_config

load_config()

EXTS_CODE = {
    ".php": "php",
    ".js": "javascript",
    ".ts": "typescript",
    ".py": "python",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".sh": "bash",
    ".env": "env",
}

EXCLUDED_DIRS = {
    "node_modules",
    "vendor",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    ".eggs",
    "dist",
    "build",
    ".next",
    "cache",
    "logs",
    "tmp",
    ".sass-cache",
    "bower_components",
    ".idea",
    ".vscode",
    "coverage",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

MAX_CHUNK_LINES = 200
MIN_CHUNK_LINES = 3


def walk_project(path: str) -> list[dict]:
    """Walk project directory and return file metadata."""
    files = []
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        print(f"❌ No existe el directorio: {path}")
        return files
    for root, dirs, filenames in os.walk(path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in EXTS_CODE:
                continue
            fpath = os.path.join(root, fname)
            try:
                stat = os.stat(fpath)
                files.append(
                    {
                        "path": fpath,
                        "rel_path": os.path.relpath(fpath, path),
                        "ext": ext,
                        "language": EXTS_CODE[ext],
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
            except OSError:
                continue
    files.sort(key=lambda f: f["path"])
    return files


def chunk_file(filepath: str, language: str) -> list[dict]:
    """Split a file into meaningful chunks.

    Uses simple heuristics: split by function/class definitions
    for structured languages, or by line blocks for others.
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return [{"error": str(e)}]

    if not lines:
        return []

    chunks = []
    lang = language

    if lang in ("php", "python", "javascript", "typescript"):
        chunks = _chunk_by_structure(lines, lang)
    else:
        chunks = _chunk_by_blocks(lines)

    # Enrich with metadata
    result = []
    for c in chunks:
        text = "".join(c["lines"])
        text_stripped = text.strip()
        if not text_stripped or len(text_stripped) < 20:
            continue
        if len(text_stripped) > 50000:
            text_stripped = text_stripped[:50000]

        content_hash = hashlib.md5(text_stripped.encode()).hexdigest()
        result.append(
            {
                "content": text_stripped,
                "hash": content_hash,
                "line_start": c["start"],
                "line_end": c["end"],
                "chunk_type": c.get("type", "block"),
            }
        )

    return result


def _chunk_by_structure(lines: list[str], lang: str) -> list[dict]:
    """Split by function/class/method definitions."""
    patterns = {
        "php": [r"^\s*(function|class|interface|trait|enum)\s"],
        "python": [r"^\s*(def |class |async def )"],
        "javascript": [r"^\s*(function |class |const .* = .*=>|async function)"],
        "typescript": [r"^\s*(function |class |interface |type |const .* = .*=>|async function)"],
    }
    import re

    pats = patterns.get(lang, [])
    if not pats:
        return _chunk_by_blocks(lines)

    compiled = [re.compile(p) for p in pats]
    chunks = []
    current_start = 0
    total = len(lines)

    for i, line in enumerate(lines):
        # Check if this line starts a definition (detect by pattern match)
        is_def = any(p.match(line) for p in compiled)
        if is_def and i > current_start:
            # Close previous chunk
            c_lines = lines[current_start:i]
            if len(c_lines) >= MIN_CHUNK_LINES:
                chunks.append(
                    {
                        "lines": c_lines,
                        "start": current_start + 1,
                        "end": i,
                        "type": "block",
                    }
                )
            current_start = i

    # Last chunk
    remaining = lines[current_start:]
    if len(remaining) >= MIN_CHUNK_LINES:
        chunks.append(
            {
                "lines": remaining,
                "start": current_start + 1,
                "end": total,
                "type": "block",
            }
        )
    elif chunks:
        # Append small tail to last chunk
        chunks[-1]["lines"].extend(remaining)
        chunks[-1]["end"] = total

    return chunks


def _chunk_by_blocks(lines: list[str]) -> list[dict]:
    """Split by logical blocks: group non-empty lines, split at >200 lines."""
    chunks = []
    total = len(lines)
    for i in range(0, total, MAX_CHUNK_LINES):
        block = lines[i : i + MAX_CHUNK_LINES]
        chunks.append(
            {
                "lines": block,
                "start": i + 1,
                "end": min(i + MAX_CHUNK_LINES, total),
                "type": "block",
            }
        )
    return chunks


def hash_file(content_hash: str, mtime: float) -> str:
    return hashlib.md5(f"{content_hash}|{mtime}".encode()).hexdigest()


def index_project(project_path: str, force: bool = False) -> dict:
    """Index all code files in project_path into memoria_vectorial."""

    stats = {"scanned": 0, "indexed": 0, "skipped": 0, "errors": 0, "chunks": 0}
    files = walk_project(project_path)
    stats["scanned"] = len(files)

    conn = get_conn()
    cur = conn.cursor()

    # Get existing index markers for this project
    cur.execute(
        """SELECT id, contenido, metadatos::text FROM memoria_vectorial
           WHERE metadatos->>'source' = 'code_index'
           AND metadatos->>'project_path' = %s""",
        (os.path.abspath(project_path),),
    )
    existing = {}
    for row in cur.fetchall():
        meta = json.loads(row[2])
        file_hash = meta.get("file_hash", "")
        existing[meta.get("rel_path", "")] = {
            "id": row[0],
            "file_hash": file_hash,
            "meta": meta,
        }

    project_key = os.path.basename(os.path.abspath(project_path))
    now_iso = datetime.now().isoformat()

    for file_info in files:
        rel_path = file_info["rel_path"]
        fpath = file_info["path"]

        # Check mtime-based skip
        file_content_hash = hashlib.md5(f"{file_info['size']}|{file_info['mtime']}".encode()).hexdigest()
        existing_entry = existing.get(rel_path)
        if existing_entry and existing_entry["file_hash"] == file_content_hash and not force:
            stats["skipped"] += 1
            continue

        # Delete old chunks for this file
        if existing_entry:
            cur.execute(
                "DELETE FROM memoria_vectorial WHERE id = %s",
                (existing_entry["id"],),
            )
            # Remove from existing dict to track deletions
            existing.pop(rel_path, None)

        # Chunk and index
        chunks = chunk_file(fpath, file_info["language"])
        if not chunks:
            continue

        for chunk in chunks:
            if "error" in chunk:
                stats["errors"] += 1
                continue

            content = chunk["content"]
            emb = get_embedding(content[:2000])
            if not emb:
                stats["errors"] += 1
                continue

            metadatos = json.dumps(
                {
                    "source": "code_index",
                    "type": "code_snippet",
                    "project_path": os.path.abspath(project_path),
                    "project_key": project_key,
                    "rel_path": rel_path,
                    "language": file_info["language"],
                    "file_hash": file_content_hash,
                    "line_start": chunk["line_start"],
                    "line_end": chunk["line_end"],
                    "chunk_type": chunk["chunk_type"],
                    "date": str(datetime.now().date()),
                    "nivel": "semantica",
                }
            )

            cur.execute(
                """INSERT INTO memoria_vectorial (contenido, metadatos, embedding)
                   VALUES (%s, %s, %s::vector(1024))""",
                (content, metadatos, emb),
            )
            stats["chunks"] += 1

        stats["indexed"] += 1

    # Mark files that no longer exist
    for rel_path, entry in existing.items():
        if entry["meta"].get("source") == "code_index":
            meta = entry["meta"].copy()
            meta["obsoleted_at"] = now_iso
            meta["status"] = "obsolete"
            cur.execute(
                "UPDATE memoria_vectorial SET metadatos = %s WHERE id = %s",
                (json.dumps(meta), entry["id"]),
            )

    conn.commit()
    cur.close()
    conn.close()

    return stats


def format_stats(stats: dict, project_path: str) -> str:
    return (
        f"📦 Indexación de proyecto: {project_path}\n"
        f"   Archivos escaneados: {stats['scanned']}\n"
        f"   Archivos indexados: {stats['indexed']}\n"
        f"   Chunks creados: {stats['chunks']}\n"
        f"   Saltados (sin cambios): {stats['skipped']}\n"
        f"   Errores: {stats['errors']}"
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Indexar código fuente en Hipocampo")
    parser.add_argument("project_path", help="Ruta del proyecto a indexar")
    parser.add_argument("--force", action="store_true", help="Re-indexar todo aunque no haya cambios")
    args = parser.parse_args()

    print(f"🔍 Escaneando {args.project_path}...")
    stats = index_project(args.project_path, force=args.force)
    print(format_stats(stats, args.project_path))


if __name__ == "__main__":
    main()
