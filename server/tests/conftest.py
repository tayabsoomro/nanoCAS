"""Pytest entry point for the server-side suite.

Inserts the `server/` directory onto sys.path so tests can do
`from app.main.utils.coverage_accumulator import CoverageAccumulator`
without needing the package installed in editable mode. The server side
isn't a `pip install -e .`-able package today (LOGBOOK section 4.18 —
the pyproject is at the repo root, not under server/), so we paper over
that with a path hack for now. When the packaging is cleaned up, this
file can shrink to just the imports the suite needs.

Run from the repo root with:
    pytest server/tests/                 # all
    pytest server/tests/test_x.py        # one file
"""

import sys
from pathlib import Path

# server/conftest.py would be picked up automatically, but rootdir resolution
# is brittle when pytest is invoked from different working directories. Doing
# the path manipulation explicitly here makes the suite location-independent.
_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))
