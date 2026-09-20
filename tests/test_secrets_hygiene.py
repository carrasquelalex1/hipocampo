"""Higiene de secretos: sin claves en el repo, permisos estrictos fuera de él.

No lee ni imprime valores — solo patrones y metadatos de archivos.
"""

import os
import re
import stat
import subprocess

REPO = os.path.join(os.path.dirname(__file__), "..")
# Prefijos + 8+ caracteres secretos (los placeholders tipo <tu-clave> no matchean).
KEY_PATTERNS = [r"nvapi-[A-Za-z0-9]{8,}", r"\bsk-[A-Za-z0-9]{8,}", r"\bhf_[A-Za-z0-9]{8,}", r"Bearer [A-Za-z0-9]{8,}"]


def _tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, timeout=30
        ).stdout.splitlines()
        return [f for f in out if f and not f.startswith("tests/test_secrets")]
    except Exception:
        return []


class TestNoSecretsInRepo:
    def test_env_example_sin_claves(self):
        path = os.path.join(REPO, ".env.example")
        assert os.path.isfile(path)
        with open(path) as f:
            texto = f.read()
        for pat in KEY_PATTERNS:
            assert not re.search(pat, texto), f"patrón de clave en .env.example: {pat}"

    def test_env_no_trackeado(self):
        tracked = _tracked_files()
        assert ".env" not in tracked
        assert not any(t.endswith("/.env") for t in tracked)

    def test_archivos_trackeados_sin_claves(self):
        for rel in _tracked_files():
            if not rel.endswith((".py", ".md", ".json", ".example", ".sql", ".sh")):
                continue
            with open(os.path.join(REPO, rel), errors="replace") as f:
                texto = f.read()
            for pat in KEY_PATTERNS:
                assert not re.search(pat, texto), f"{rel}: patrón {pat}"


class TestPermisosFueraDelRepo:
    def _check_600(self, path):
        if not os.path.isfile(path):
            return
        modo = stat.S_IMODE(os.stat(path).st_mode)
        assert modo == 0o600, f"{path} con permisos {oct(modo)}, se espera 0o600"

    def test_env_local_600(self):
        self._check_600(os.path.expanduser("~/.hipocampo/.env"))

    def test_typesafe_key_600(self):
        self._check_600(os.path.expanduser("~/.config/typesafe/api_key"))
