import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from hipocampo_autotag import (
    auto_tag,
    auto_categorize,
    auto_tag_full,
    TAG_RULES,
    CATEGORY_RULES,
)


class TestAutoTag:
    def test_tag_familia_esposa(self):
        assert "familia" in auto_tag("La esposa del usuario se llama Maria")

    def test_tag_familia_hijo(self):
        assert "familia" in auto_tag("El hijo del usuario tiene 5 años")

    def test_tag_familia_madre(self):
        assert "familia" in auto_tag("La madre del usuario")

    def test_tag_plantas_medicinales(self):
        tags = auto_tag("El usuario planta malojillo y orégano")
        assert "plantas_medicinales" in tags

    def test_tag_plantas_te(self):
        tags = auto_tag("Le gusta el té de manzanilla")
        assert "plantas_medicinales" in tags

    def test_tag_colores(self):
        assert "colores" in auto_tag("Le gusta el color azul rey")

    def test_tag_programacion_python(self):
        assert "programacion" in auto_tag("Proyecto en Python con PostgreSQL")

    def test_tag_servidores_linux(self):
        tags = auto_tag("Servidor Ubuntu con Docker")
        assert "servidores" in tags
        assert "linux" in tags

    def test_tag_finanzas(self):
        tags = auto_tag("Inversión en dólares y ahorro")
        assert "finanzas" in tags
        assert "ahorros" in tags

    def test_tag_cocina(self):
        assert "cocina" in auto_tag("Receta de cocina para el almuerzo")

    def test_tag_entretenimiento(self):
        assert "entretenimiento" in auto_tag("Película en Netflix")

    def test_tag_salud(self):
        assert "salud" in auto_tag("Ejercicio en el gym")

    def test_tag_hogar(self):
        assert "hogar" in auto_tag("Pintar la pared del departamento")

    def test_tag_metas(self):
        assert "metas" in auto_tag("Mi meta es aprender a programar")

    def test_empty_summary(self):
        assert auto_tag("") == []

    def test_none_summary(self):
        assert auto_tag(None) == []

    def test_multiples_tags(self):
        tags = auto_tag("El usuario programa Python en Ubuntu con Docker")
        assert "programacion" in tags
        assert "servidores" in tags
        assert "linux" in tags

    def test_todas_las_reglas_tienen_pattern_valido(self):
        import re

        for pattern, _ in TAG_RULES:
            assert re.compile(pattern), f"Patrón inválido: {pattern}"

    def test_no_falsos_positivos(self):
        tags = auto_tag("El usuario fue a la playa")
        assert tags == []  # no debería matchear nada


class TestAutoCategorize:
    def test_categoria_relationships(self):
        assert auto_categorize("La esposa del usuario") == "relationships"

    def test_categoria_work_life(self):
        assert auto_categorize("Proyecto de software en Python") == "work_life"

    def test_categoria_personal_info(self):
        assert auto_categorize("El usuario se llama Alexander") == "personal_info"

    def test_categoria_preferences(self):
        assert auto_categorize("Le gusta el color azul") == "preferences"

    def test_categoria_knowledge(self):
        assert auto_categorize("Aprendió sobre plantas medicinales") == "knowledge"

    def test_categoria_habits(self):
        assert auto_categorize("Cada mañana hace ejercicio") == "habits"

    def test_categoria_goals(self):
        assert auto_categorize("Su meta es ahorrar dinero") == "goals"

    def test_categoria_activities(self):
        assert auto_categorize("Jugar fútbol los fines de semana") == "activities"

    def test_categoria_experiences(self):
        assert auto_categorize("Cuando era niño vivía en Caracas") == "experiences"

    def test_categoria_opinions(self):
        assert auto_categorize("Opina que la tecnología avanza") == "opinions"

    def test_default_category(self):
        assert auto_categorize("El cielo es amplio") == "personal_info"

    def test_empty_summary(self):
        assert auto_categorize("") == "personal_info"

    def test_todas_las_reglas_tienen_pattern_valido(self):
        import re

        for pattern, _ in CATEGORY_RULES:
            assert re.compile(pattern), f"Patrón inválido: {pattern}"


class TestAutoTagFull:
    def test_profile_type_relationships(self):
        result = auto_tag_full("La esposa del usuario")
        assert result["memory_type"] == "profile"
        assert "familia" in result["tags"]
        assert result["category"] == "relationships"

    def test_profile_type_preferences(self):
        result = auto_tag_full("Le gusta el color azul")
        assert result["memory_type"] == "profile"

    def test_event_type_default(self):
        result = auto_tag_full("El usuario completó una tarea de trabajo")
        assert result["memory_type"] == "event"
        assert result["category"] in ("personal_info", "work_life")

    def test_memory_type_forzado(self):
        result = auto_tag_full("Dato técnico", memory_type="decision")
        assert result["memory_type"] == "decision"
