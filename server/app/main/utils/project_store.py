"""Project registry helpers.

nanoCAS keeps one directory per project under ``~/.nanocas/<projectId>/``
and a small tab-separated index file ``~/.nanocas/.cache`` with one line
per project (``projectId<TAB>minion_dir<TAB>nanocas_dir``).

Every read/write of that index used to be open-coded in routes.py and
events.py with substring matching (``if project_id not in line``), which
could delete the wrong row, and the delete endpoint joined an unvalidated
id straight into ``rm -rf``. All of that now goes through this module:

* ids are validated against a strict pattern before they touch the
  filesystem;
* the index is parsed column-wise and matched on the id column only;
* writes are serialised with a process-wide lock.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime

logger = logging.getLogger('nanocas')

NANOCAS_DIR = os.path.join(os.path.expanduser('~'), '.nanocas')
CACHE_PATH = os.path.join(NANOCAS_DIR, '.cache')

# Project ids are UUID4 strings minted by nanoCAS itself. Anything else
# (path separators, "..", whitespace) is rejected before it can be used
# to build a path. The pattern is deliberately a little wider than a
# UUID so hand-created test projects still work.
_PROJECT_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')

_cache_lock = threading.RLock()


def ensure_workspace() -> str:
    """Create ``~/.nanocas`` and the index file if missing; return the dir."""
    os.makedirs(NANOCAS_DIR, exist_ok=True)
    if not os.path.isfile(CACHE_PATH):
        open(CACHE_PATH, 'a').close()
    return NANOCAS_DIR


def is_valid_project_id(project_id: str | None) -> bool:
    if not project_id or not isinstance(project_id, str):
        return False
    if '..' in project_id:
        return False
    return bool(_PROJECT_ID_RE.match(project_id))


def project_dir(project_id: str) -> str:
    """Absolute project directory for a *validated* id.

    Raises ``ValueError`` for anything that fails ``is_valid_project_id``
    or that resolves outside ``NANOCAS_DIR`` (defence in depth).
    """
    if not is_valid_project_id(project_id):
        raise ValueError(f'Invalid project id: {project_id!r}')
    path = os.path.join(NANOCAS_DIR, project_id)
    real_base = os.path.realpath(NANOCAS_DIR)
    real_path = os.path.realpath(path)
    if real_path != real_base and not real_path.startswith(real_base + os.sep):
        raise ValueError(f'Project id escapes workspace: {project_id!r}')
    return path


def new_project_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Index file
# ---------------------------------------------------------------------------

def read_cache() -> list[dict]:
    """Return the index rows as dicts. Malformed rows are skipped."""
    ensure_workspace()
    rows: list[dict] = []
    with _cache_lock:
        with open(CACHE_PATH, 'r') as fh:
            for line in fh:
                line = line.rstrip('\n')
                if not line.strip():
                    continue
                parts = line.split('\t')
                if len(parts) < 3:
                    continue
                rows.append({
                    'id': parts[0].strip(),
                    'minion_dir': parts[1].strip(),
                    'nanocas_dir': parts[2].strip(),
                })
    return rows


def append_cache(project_id: str, minion_dir: str, nanocas_dir: str) -> None:
    if not is_valid_project_id(project_id):
        raise ValueError(f'Invalid project id: {project_id!r}')
    ensure_workspace()
    with _cache_lock:
        with open(CACHE_PATH, 'a') as fh:
            fh.write(f'{project_id}\t{minion_dir}\t{nanocas_dir}\n')


def remove_from_cache(project_id: str) -> bool:
    """Drop the row whose *id column* equals ``project_id``. Returns True
    if a row was removed."""
    ensure_workspace()
    removed = False
    with _cache_lock:
        with open(CACHE_PATH, 'r') as fh:
            lines = fh.readlines()
        kept = []
        for line in lines:
            parts = line.rstrip('\n').split('\t')
            if parts and parts[0].strip() == project_id:
                removed = True
                continue
            kept.append(line)
        if removed:
            tmp = CACHE_PATH + '.tmp'
            with open(tmp, 'w') as fh:
                fh.writelines(kept)
            os.replace(tmp, CACHE_PATH)
    return removed


def find_cache_entry(project_id: str) -> dict | None:
    for row in read_cache():
        if row['id'] == project_id:
            return row
    return None


# ---------------------------------------------------------------------------
# Per-project config (alertinfo.cfg)
# ---------------------------------------------------------------------------

def config_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), 'alertinfo.cfg')


def load_config(project_id: str) -> dict | None:
    try:
        with open(config_path(project_id), 'r') as fh:
            return json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug(f'Could not load config for {project_id}: {exc}')
        return None


def save_config(project_id: str, config: dict) -> None:
    path = config_path(project_id)
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(config, fh, indent=2)
    os.replace(tmp, path)


def list_projects() -> list[dict]:
    """Index rows enriched with the display fields the UI needs."""
    projects = []
    for row in read_cache():
        entry = dict(row)
        cfg = load_config(row['id']) if is_valid_project_id(row['id']) else None
        entry['name'] = (cfg or {}).get('projectName') or ''
        entry['file_type'] = (cfg or {}).get('fileType', 'FASTQ')
        entry['created_at'] = (cfg or {}).get('createdAt')
        entry['query_count'] = len((cfg or {}).get('queries', []) or [])
        entry['demo'] = bool((cfg or {}).get('demo'))
        entry['demo_scenario'] = (cfg or {}).get('demoScenario')
        entry['exists'] = os.path.isdir(row['nanocas_dir'])
        projects.append(entry)
    projects.sort(key=lambda p: p.get('created_at') or '', reverse=True)
    return projects


def delete_project(project_id: str) -> bool:
    """Remove the project directory and its index row. Returns True if
    either existed. Raises ``ValueError`` on an invalid id."""
    path = project_dir(project_id)
    existed = remove_from_cache(project_id)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        existed = True
    return existed


def now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')
