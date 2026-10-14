"""Pytest entry point for the server-side suite.

Inserts ``server/`` onto sys.path so tests can import ``app.*`` without
an editable install, and redirects the nanoCAS workspace (``~/.nanocas``)
to a per-session temporary directory so the suite never touches a real
user's projects.

Run from the repo root with:
    pytest server/tests/
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

# Must happen before `app` is imported anywhere: project_store resolves
# NANOCAS_DIR from HOME at import time.
_WORKSPACE_HOME = tempfile.mkdtemp(prefix='nanocas-test-home-')
os.environ['HOME'] = _WORKSPACE_HOME
os.environ.setdefault('NANOCAS_LOG_LEVEL', 'WARNING')


@pytest.fixture(scope='session')
def flask_app():
    from app import create_app
    app = create_app(debug=False)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def project(tmp_path):
    """Create a registered project directory with a minimal config and
    return ``(project_id, project_dir)``."""
    from app.main.utils import project_store
    pid = project_store.new_project_id()
    pdir = project_store.project_dir(pid)
    os.makedirs(os.path.join(pdir, 'database'), exist_ok=True)
    cfg = {
        'projectId': pid,
        'projectName': 'Test project',
        'fileType': 'FASTQ',
        'minion': str(tmp_path / 'minion'),
        'queries': [{'name': 'E. coli', 'header': 'chr1', 'headers': ['chr1'],
                     'depth_threshold': '2', 'alert_on_depth': True,
                     'breadth_threshold': '50', 'alert_on_breadth': True}],
        'alertNotifConfig': {'enableEmail': False, 'enableSMS': False},
    }
    project_store.save_config(pid, cfg)
    project_store.append_cache(pid, cfg['minion'], pdir)
    os.makedirs(cfg['minion'], exist_ok=True)
    yield pid, pdir
    project_store.delete_project(pid)
