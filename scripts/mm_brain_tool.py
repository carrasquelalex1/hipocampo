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
import psycopg2
from pgvector.psycopg2 import register_vector
from openai import OpenAI
from lxml import etree as ET
from dotenv import load_dotenv

# --- CONFIGURACIÓN (desde entorno) ---
load_dotenv()
BRAIN_PATH = os.getenv('BRAIN_PATH', os.path.expanduser('~/.gemini/brain/knowledge_base.mm'))
CACHE_PATH = os.getenv('CACHE_PATH', os.path.expanduser('~/.gemini/brain/.mm_cache.json'))
DB_NAME = os.getenv('DB_NAME', 'hipocampo_db')
DB_USER = os.getenv('DB_USER', 'alex')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_HOST = os.getenv('DB_HOST', '/var/run/postgresql')

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
)

def get_node_embedding(text):
    """Genera embedding usando NVIDIA API (1024 dimensiones)"""
    try:
        resp = client.embeddings.create(
            input=text,
            model="nvidia/nv-embedqa-e5-v5",
            encoding_format="float",
            extra_body={"input_type": "query"},
        )
        return resp.data[0].embedding
    except Exception as e:
        print(f"DEBUG: Error Embedding: {e}")
        return None

def save_to_vector_db(content, metadata, code_snippet=None):
    """Inserta el nuevo nodo en el Hipocampo Digital (PostgreSQL) con soporte para codigo"""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST
        )
        register_vector(conn)
        cur = conn.cursor()
        
        vector = get_node_embedding(content)
        if vector:
            cur.execute(
                "INSERT INTO memoria_vectorial (contenido, metadatos, embedding, code_snippet) VALUES (%s, %s, %s, %s)",
                (content, json.dumps(metadata), vector, code_snippet)
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
            with open(CACHE_PATH, 'r') as f:
                return json.load(f)
        except: return {}
    return {}

def save_cache(cache):
    with open(CACHE_PATH, 'w') as f:
        json.dump(cache, f)

def get_node_by_path(root, path_query):
    parts = path_query.split('/')
    current_context = [root]
    for part in parts:
        next_context = []
        for ctx in current_context:
            matches = ctx.xpath(f".//node[contains(@TEXT, '{part}')] | .//node[@ID='{part}']")
            next_context.extend(matches)
        if not next_context: return None
        current_context = next_context
    return current_context[0] if current_context else None

def update_mm(parent_query, new_node_text, color=None, link=None, note=None, code=None, node_type=None):
    start_time = time.time()
    cache = load_cache()
    
    try:
        with open(BRAIN_PATH, 'rb+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            parser = ET.XMLParser(remove_blank_text=False, recover=True)
            tree = ET.parse(f, parser)
            root = tree.getroot()
            
            parent = None
            if parent_query in cache:
                parent_id = cache[parent_query]
                results = root.xpath(f"//node[@ID='{parent_id}']")
                if results: parent = results[0]
            
            if parent is None:
                parent = get_node_by_path(root, parent_query)
                if parent is not None:
                    cache[parent_query] = parent.get('ID')
            
            if parent is None:
                return f"Error: No se encontró '{parent_query}'."
            
            # Crear Nuevo Nodo XML
            new_id = f"ID_{int(time.time() * 1000)}_{os.urandom(2).hex()}"
            new_node = ET.SubElement(parent, 'node', TEXT=new_node_text, ID=new_id)
            if color: new_node.set('COLOR', color)
            if link: new_node.set('LINK', link)
            new_node.set('CREATED', str(int(time.time() * 1000)))
            
            if note:
                note_el = ET.SubElement(new_node, 'richcontent', TYPE="NOTE")
                html_body = ET.fromstring(f"<html><body><p>{note}</p></body></html>")
                note_el.append(html_body)

            # Añadir icono si es una preferencia
            if node_type == "Preferencia":
                ET.SubElement(new_node, 'icon', BUILTIN="flag")

            # Guardado Atómico XML
            f.seek(0)
            f.truncate()
            tree.write(f, encoding='UTF-8', xml_declaration=True, pretty_print=True)
            save_cache(cache)
            
            # --- MIELINIZACIÓN AUTOMÁTICA (v6.1) ---
            path_context = f"{parent_query} > {new_node_text}"
            metadata = {
                "id": new_id,
                "path": path_context,
                "source": "knowledge_base.mm",
                "type": node_type if node_type else "brain_node_v6"
            }
            content_to_vectorize = f"[{path_context}]"
            if note: content_to_vectorize += f"\nNota: {note}"
            
            vector_status = "🧠 v6.1 OK" if save_to_vector_db(content_to_vectorize, metadata, code) else "⚠️ Solo XML"
            
            elapsed = round((time.time() - start_time) * 1000, 2)
            return f"🚀 v6.1 OK: '{new_node_text}' [{vector_status}] en {elapsed}ms (Path: {parent_query})"

    except Exception as e:
        return f"CRITICAL: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: mm_brain_tool.py <query/path> <text> [color] [link] [note] [--code <code>] [--type <node_type>]")
        sys.exit(1)
    
    p_query = sys.argv[1]
    n_text = sys.argv[2]
    
    # Parseo de argumentos mejorado
    args = sys.argv[3:]
    n_color = args.pop(0) if args and not args[0].startswith('--') else None
    n_link = args.pop(0) if args and not args[0].startswith('--') else None
    n_note = args.pop(0) if args and not args[0].startswith('--') else None
    
    code_val = None
    if "--code" in args:
        idx = args.index("--code")
        if idx + 1 < len(args):
            code_val = args[idx + 1]

    type_val = None
    if "--type" in args:
        idx = args.index("--type")
        if idx + 1 < len(args):
            type_val = args[idx + 1]

    print(update_mm(p_query, n_text, color=n_color, link=n_link, note=n_note, code=code_val, node_type=type_val))
