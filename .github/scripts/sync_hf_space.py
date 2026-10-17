#!/usr/bin/env python3
"""Sincroniza este repo con el Space de Hugging Face vía la API del hub.

HF rechaza los `git push` con archivos binarios ("use xet"); la API del hub
(create_commit) sí los acepta. Este script reemplaza el `git push` del workflow
deploy-hf-spaces.yml: sube todos los archivos versionados (git ls-files) y
borra del Space los que ya no existen en el repo (espejo).

Uso: HF_TOKEN=... python3 .github/scripts/sync_hf_space.py
"""

from __future__ import annotations

import os
import subprocess
import sys

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

REPO_ID = "alexbell1/hipocampo-mcp"
REPO_TYPE = "space"
KEEP = {".gitattributes"}  # lo gestiona el propio HF; no borrar


def main() -> int:
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("ERROR: falta HF_TOKEN en el entorno", file=sys.stderr)
        return 2

    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    if not tracked:
        print(
            "ERROR: git ls-files no devolvió archivos (¿no estás en la raíz del repo?)",
            file=sys.stderr,
        )
        return 2

    api = HfApi(token=token)
    remote = set(api.list_repo_files(REPO_ID, repo_type=REPO_TYPE))
    local = set(tracked)
    to_delete = sorted((remote - local) - KEEP)

    print(f"archivos: remotos={len(remote)} locales={len(local)} a_borrar={len(to_delete)}")
    if to_delete:
        preview = ", ".join(to_delete[:30])
        if len(to_delete) > 30:
            preview += " ..."
        print(f"a_borrar: {preview}")

    operations = [CommitOperationDelete(path_in_repo=p) for p in to_delete]
    operations += [CommitOperationAdd(path_in_repo=f, path_or_fileobj=f) for f in tracked]

    commit = api.create_commit(
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
        operations=operations,
        commit_message="Sync desde GitHub (carrasquelalex1/hipocampo)",
    )
    print(f"OK: commit {commit.oid[:9]} | operaciones: {len(operations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
