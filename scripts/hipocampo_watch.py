#!/usr/bin/env python3
"""hipocampo_watch.py — Auto-reindexer for watched directories.

Called by systemd timer every 10 minutes. Scans configured project paths
and re-indexes changed files using the existing incremental indexer.

Config: ~/.hipocampo/watch_config.json
State:  ~/.hipocampo/data/watch_state.json
Logs:   ~/.hipocampo/logs/watch.log
"""

import os
import sys
import json
import logging
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, ".."))

HIPPO_DIR = Path.home() / ".hipocampo"
CONFIG_PATH = HIPPO_DIR / "watch_config.json"
STATE_PATH = HIPPO_DIR / "data" / "watch_state.json"
LOG_DIR = HIPPO_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "watch.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("hipocampo_watch")


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {"paths": [], "interval_minutes": 10}


def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def compute_path_hash(path):
    """Quick hash of a directory based on file mtimes and sizes."""
    import hashlib

    h = hashlib.md5()
    try:
        for entry in sorted(Path(path).rglob("*")):
            if entry.is_file() and not entry.name.startswith("."):
                stat = entry.stat()
                h.update(f"{entry}|{stat.st_size}|{stat.st_mtime}".encode())
    except Exception:
        pass
    return h.hexdigest()


def run():
    config = load_config()
    paths = config.get("paths", [])
    if not paths:
        logger.info("No paths configured in watch_config.json")
        return

    state = load_state()
    changed = 0

    for path in paths:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            logger.warning("Path not found, skipping: %s", path)
            continue

        path_hash = compute_path_hash(path)
        last_hash = state.get(path)

        if path_hash == last_hash:
            continue

        logger.info("Changes detected in %s, reindexing...", path)
        try:
            import hipocampo_index_project as indexer

            stats = indexer.index_project(path)
            logger.info("Indexed %s: %s", path, stats)
            changed += 1
        except Exception as e:
            logger.error("Failed to index %s: %s", path, e)

        state[path] = path_hash

    save_state(state)

    if changed:
        logger.info("Watch scan complete: %d/%d paths updated", changed, len(paths))
    else:
        logger.debug("Watch scan complete: no changes in %d paths", len(paths))


if __name__ == "__main__":
    run()
