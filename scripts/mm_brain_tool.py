#!/usr/bin/env python3
# mm_brain_tool.py v6.0 - Nucleo Evolucionado
# Migrado al SDK openai/NVIDIA y soporte para Memoria de Codigo.
#
# CONFIGURACIÓN: usa variables de entorno (ver .env.example)
#   BRAIN_PATH  → ruta al archivo Freeplane XML (default: ~/.gemini/brain/knowledge_base.mm)
#   CACHE_PATH  → ruta al archivo cache (default: ~/.gemini/brain/.mm_cache.json)
#   DB_NAME     → nombre de la base de datos (default: hipocampo_db)
#   DB_USER     → usuario de PostgreSQL (default: postgres)
#   DB_PASSWORD → contraseña de PostgreSQL
#   DB_HOST     → host de PostgreSQL (default: localhost)
#   NVIDIA_API_KEY → API key de NVIDIA

import sys
import os
import time
import json
import fcntl
from pgvector.psycopg2 import register_vector
from lxml import etree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, get_embedding, load_config

# --- CONFIGURACIÓN (desde entorno) ---
load_config()
BRAIN_PATH = os.getenv("BRAIN_PATH", os.path.expanduser("~/.gemini/brain/knowledge_base.mm"))
CACHE_PATH = os.getenv("CACHE_PATH", os.path.expanduser("~/.gemini/brain/.mm_cache.json"))


def get_node_embedding(text):
    """Genera embedding usando NVIDIA API (1024 dimensiones)"""
    try:
        return get_embedding(text)
    except Exception as e:
        print(f"DEBUG: Error Embedding: {e}")
        return None


def save_to_vector_db(content, metadata, code_snippet=None):
    """Inserta el nuevo nodo en el Hipocampo Digital (PostgreSQL) con soporte para codigo"""
    try:
        conn = get_conn()
        register_vector(conn)
        cur = conn.cursor()

        vector = get_node_embedding(content)
        if vector:
            cur.execute(
                "INSERT INTO memoria_vectorial (contenido, metadatos, embedding, code_snippet) VALUES (%s, %s, %s, %s)",
                (content, json.dumps(metadata), vector, code_snippet),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        return False
    except Exception as e:
        print(f"DEBUG: Error en Vector DB: {e}")
        return False


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)


def get_node_by_path(root, path_query):
    parts = path_query.split("/")
    current_context = [root]
    for part in parts:
        next_context = []
        for ctx in current_context:
            matches = ctx.xpath(f".//node[contains(@TEXT, '{part}')] | .//node[@ID='{part}']")
            next_context.extend(matches)
        if not next_context:
            return None
        current_context = next_context
    return current_context[0] if current_context else None


def update_mm(parent_query, new_node_text, color=None, link=None, note=None, code=None, node_type=None):
    start_time = time.time()
    cache = load_cache()

    try:
        with open(BRAIN_PATH, "rb+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            parser = ET.XMLParser(remove_blank_text=False, recover=True)
            tree = ET.parse(f, parser)
            root = tree.getroot()

            parent = None
            if parent_query in cache:
                parent_id = cache[parent_query]
                results = root.xpath(f"//node[@ID='{parent_id}']")
                if results:
                    parent = results[0]

            if parent is None:
                parent = get_node_by_path(root, parent_query)
                if parent is not None:
                    cache[parent_query] = parent.get("ID")

            if parent is None:
                return f"Error: No se encontró '{parent_query}'."

            # Crear Nuevo Nodo XML
            new_id = f"ID_{int(time.time() * 1000)}_{os.urandom(2).hex()}"
            new_node = ET.SubElement(parent, "node", TEXT=new_node_text, ID=new_id)
            if color:
                new_node.set("COLOR", color)
            if link:
                new_node.set("LINK", link)
            new_node.set("CREATED", str(int(time.time() * 1000)))

            if note:
                note_el = ET.SubElement(new_node, "richcontent", TYPE="NOTE")
                html_body = ET.fromstring(f"<html><body><p>{note}</p></body></html>")
                note_el.append(html_body)

            # Añadir icono si es una preferencia
            if node_type == "Preferencia":
                ET.SubElement(new_node, "icon", BUILTIN="flag")

            # Guardado Atómico XML
            f.seek(0)
            f.truncate()
            tree.write(f, encoding="UTF-8", xml_declaration=True, pretty_print=True)
            save_cache(cache)

            # --- MIELINIZACIÓN AUTOMÁTICA (v6.1) ---
            path_context = f"{parent_query} > {new_node_text}"
            metadata = {
                "id": new_id,
                "path": path_context,
                "source": "knowledge_base.mm",
                "type": node_type if node_type else "brain_node_v6",
            }
            content_to_vectorize = f"[{path_context}]"
            if note:
                content_to_vectorize += f"\nNota: {note}"

            vector_status = "🧠 v6.1 OK" if save_to_vector_db(content_to_vectorize, metadata, code) else "⚠️ Solo XML"

            elapsed = round((time.time() - start_time) * 1000, 2)
            return f"🚀 v6.1 OK: '{new_node_text}' [{vector_status}] en {elapsed}ms (Path: {parent_query})"

    except Exception as e:
        return f"CRITICAL: {str(e)}"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Freeplane Mind Map Brain Tool — actualiza mapas mentales")
    parser.add_argument("query", help="Ruta/query del nodo en el mapa mental")
    parser.add_argument("text", help="Texto del nuevo nodo")
    parser.add_argument("--color", help="Color del nodo (ej: azul, #FF0000)")
    parser.add_argument("--link", help="Enlace asociado al nodo")
    parser.add_argument("--note", help="Nota del nodo")
    parser.add_argument("--code", help="Código de agrupación")
    parser.add_argument("--type", help="Tipo de nodo (node_type)")
    args = parser.parse_args()

    print(
        update_mm(
            args.query, args.text, color=args.color, link=args.link, note=args.note, code=args.code, node_type=args.type
        )
    )
