#!/home/usuario/.gemini/mcp_venv/bin/python3
"""hipocampo_autotag.py v1.0 — Auto-tagging con reglas de clasificación.

Asigna tags y categorías automáticamente basados en el contenido del summary
usando reglas de clasificación por palabras clave. Reemplaza la tarea manual
de etiquetar cada item en memory_items.

Uso:
    from hipocampo_autotag import auto_tag, auto_categorize

    tags = auto_tag("La esposa del usuario se llama Gaudi")
    # → ["familia"]

    cat = auto_categorize("El usuario está casado con Gaudi")
    # → "relationships"
"""

import re

# ─── REGLAS DE TAGS ──────────────────────────────────────────────────────────

TAG_RULES = [
    (r'\b(esposa|esposo|casad[ao]|matrimonio|cónyuge|conyuge|pareja|novi[ao])\b', ['familia']),
    (r'\b(herman[ao]|hermanas?|cuñad[ao]|suegr[ao]|tí[ao]|prim[ao]|abuel[ao]|niet[ao])\b', ['familia']),
    (r'\b(hij[oa]s?|hijos?|bebé|bebe|niñ[oa]s?)\b', ['familia']),
    (r'\b(madre|padre|mamá|papá|mama|papa)\b', ['familia']),
    (r'\b(familia|familiar|familiares|parientes?)\b', ['familia']),
    (r'\b(planta[sz]?|medicinal|medicinales|hierba[sz]?|herbal|curativa|tisana|infusi[oó]n)\b', ['plantas_medicinales']),
    (r'\b(malojillo|or[eé]gano|manzanilla|jengibre|canela|toronjil|albahaca|romero)\b', ['plantas_medicinales']),
    (r'\b(t[eé]|infusi[oó]n)\b', ['plantas_medicinales']),
    (r'\b(azul|rojo|verde|amarillo|blanco|negro|gris|marr[oó]n|naranja|rosado|violeta|celeste|dorado|plateado)\b', ['colores']),
    (r'\b(color|colores|tono|tonalidad|sombre|matiz)\b', ['colores']),
    (r'\b(pintur[oa]|brocha|rodillo|pared|paredes|pintar)\b', ['hogar', 'mantenimiento']),
    (r'\b(linux|ubuntu|debian|bash|terminal|servidor|vps|docker|nginx|apache|ssh)\b', ['servidores', 'linux']),
    (r'\b(python|javascript|typescript|php|java|rust|golang|ruby|swift|kotlin)\b', ['programacion']),
    (r'\b(base de datos|postgres|mysql|sqlite|mongodb|redis|sql|query)\b', ['programacion']),
    (r'\b(proyecto|app|aplicación|sistema|software|código|codigo|repositorio|github)\b', ['programacion']),
    (r'\b(telegram|bot|bots|chatbot|mensaje)\b', ['programacion', 'telegram']),
    (r'\b(inversi[oó]n|ahorro|bol[íi]var|d[óo]lar|divisa|cripto|bitcoin|cuenta|banco)\b', ['finanzas', 'ahorros']),
    (r'\b(receta|cocina|cocinar|comida|plato|almuerzo|cena|desayuno)\b', ['cocina']),
    (r'\b(música|musica|canciones|canción|banda|artista|género|playlist)\b', ['entretenimiento']),
    (r'\b(pelicula|película|serie|netflix|youtube|video|vhdl)\b', ['entretenimiento']),
    (r'\b(gym|gimnasio|ejercicio|entrenar|pesas|caminar|correr|salud)\b', ['salud', 'fitness']),
    (r'\b(departamento|casa|vivienda|alquiler|renta|mudanza|cuarto|habitación)\b', ['hogar']),
    (r'\b(meta|objetivo|aspiración|quiero|llegar a ser|plan a futuro)\b', ['metas']),
]

# ─── REGLAS DE CATEGORÍA ─────────────────────────────────────────────────────

CATEGORY_RULES = [
    (r'\b(espos[ao]|casad[ao]|herman[ao]|cuñad[ao]|hij[oa]s?|madre|padre|familia|parientes?|suegr[ao]|tí[ao]|abuel[oa]|novi[ao]|pareja|primo)\b', 'relationships'),
    (r'\b(gusta|gustan|gustaba|favorit[oa]|prefiere|preferida|encanta|feliz|amo|amor|quiero mucho)\b', 'preferences'),
    (r'\b(planta[sz]?|medicinal|hierba[sz]?|t[eé]|infusi[oó]n|malojillo|or[eé]gano|romero|albahaca|manzanilla)\b', 'knowledge'),
    (r'\b(color|colores|azul|rojo|verde|amarillo|tono|pintur[oa])\b', 'preferences'),
    (r'\b(proyecto|trabajo|empleo|oficina|cliente|empresa|negocio|startup)\b', 'work_life'),
    (r'\b(código|codigo|programar|desarrollar|sistema|software|app|bot|script)\b', 'work_life'),
    (r'\b(nombre|llama|llaman|edad|años|años|vive|ubicación|dirección|naci[oó])\b', 'personal_info'),
    (r'\b(rutina|acostumbra|siempre|diario|cada día|mañana|tarde|noche)\b', 'habits'),
    (r'\b(meta|objetivo|aspira|sueño|quiero lograr|plan para)\b', 'goals'),
    (r'\b(aprend[ií]|estudi[oó]|sabe|conoce|le[íi]do|investig[uú]|curso|leer|lectura)\b', 'knowledge'),
    (r'\b(pienso|creo|opina|opinión|parece|considero|para m[íi])\b', 'opinions'),
    (r'\b(hobby|actividad|tiempo libre|fines de semana|descanso|ocio|jugar)\b', 'activities'),
    (r'\b(experiencia|recuerda|pasado|cuando era|antes|anteriormente|viv[ií])\b', 'experiences'),
    (r'\b(gym|gimnasio|ejercicio|deporte|entrenar|pesas|caminar|correr|fútbol|futbol|beisbol|béisbol)\b', 'activities'),
    (r'\b(música|música|canciones|tocar|cantar|piano|guitarra|instrumento)\b', 'activities'),
    (r'\b(inversi[oó]n|ahorro|ahorros|bol[íi]var|d[óo]lar|divisa|banco|cuenta|presupuesto)\b', 'goals'),
]

DEFAULT_CATEGORY = 'personal_info'


def auto_tag(summary: str) -> list:
    """Asigna tags automáticamente basados en el contenido del summary.

    Args:
        summary: Texto del resumen a clasificar.

    Returns:
        Lista de tags únicos en orden de relevancia.
    """
    if not summary:
        return []

    text_lower = summary.lower()
    matched_tags = set()

    for pattern, tags in TAG_RULES:
        if re.search(pattern, text_lower):
            matched_tags.update(tags)

    return sorted(matched_tags)


def auto_categorize(summary: str) -> str:
    """Determina la categoría más probable para un summary.

    Args:
        summary: Texto del resumen a clasificar.

    Returns:
        Nombre de la categoría (de memory_categories).
    """
    if not summary:
        return DEFAULT_CATEGORY

    text_lower = summary.lower()

    for pattern, category in CATEGORY_RULES:
        if re.search(pattern, text_lower):
            return category

    return DEFAULT_CATEGORY


def auto_tag_full(summary: str, memory_type: str = None) -> dict:
    """Clasificación completa: tags + categoría + tipo de memoria sugerido.

    Args:
        summary: Texto del resumen.
        memory_type: Tipo forzado (profile/event/decision) o None para auto-detectar.

    Returns:
        Dict con 'tags', 'category', 'memory_type'.
    """
    tags = auto_tag(summary)
    category = auto_categorize(summary)

    # Auto-detectar memory_type si no se especificó
    if memory_type is None:
        rel_cats = {'relationships', 'personal_info'}
        if category in rel_cats:
            memory_type = 'profile'
        elif category in {'goals', 'opinions', 'preferences'}:
            memory_type = 'profile'
        else:
            memory_type = 'event'

    return {
        'tags': tags,
        'category': category,
        'memory_type': memory_type,
    }


if __name__ == "__main__":
    import sys

    test_summaries = [
        "La esposa del usuario se llama Gaudi Concepción Puente Godoy",
        "El usuario está casado con Gaudi",
        "El hijo del usuario se llama Gabriel Alexander",
        "Haydee es la cuñada del usuario, es interesada",
        "Al usuario le gusta el color azul rey",
        "El usuario planta malojillo y orégano orejón",
        "El usuario trabaja en un proyecto de software con Python y PostgreSQL",
        "El usuario hace ejercicio en las mañanas",
        "Alexander José Carrasquel Burgos se llama el usuario",
    ]

    if len(sys.argv) > 1:
        test_summaries = [sys.argv[1]]

    print("=" * 60)
    print("🤖 Hipocampo Auto-Tag v1.0")
    print("=" * 60)
    for s in test_summaries:
        result = auto_tag_full(s)
        print(f"\n📝 {s}")
        print(f"   🏷️  Tags: {result['tags']}")
        print(f"   📂 Categoría: {result['category']}")
        print(f"   🧠 Tipo: {result['memory_type']}")
