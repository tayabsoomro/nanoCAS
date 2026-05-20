"""Lock-related regression tests for FileHandler.

The original LOGBOOK section 3 bug: `_mark_alert_as_sent` acquired
`sent_alerts_lock` and then called `_save_sent_alerts` which tried to
re-acquire the SAME non-reentrant `threading.Lock`. The watchdog
dispatcher hung on the very first alert, silently freezing all FASTQ
processing for the rest of the run.

This test forces the call path that previously deadlocked and watches
it on a thread with a wall-clock timeout. If the deadlock comes back,
the test fails in ~2 seconds instead of hanging CI forever.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.main.utils.FileHandler import FileHandler


@pytest.fixture
def minimal_project_dir(tmp_path: Path) -> Path:
    """A bare-bones project workspace with the files FileHandler insists
    on at construction time. Skips the actual run / database setup."""
    (tmp_path / 'alertinfo.cfg').write_text(json.dumps({
        'fileType': 'FASTQ',
        'queries': [],
        'projectId': 'test-project',
    }))
    return tmp_path


def test_mark_alert_as_sent_does_not_deadlock(minimal_project_dir):
    """Two consecutive `_mark_alert_as_sent` calls must return within a
    couple of seconds. Pre-LOGBOOK-section-3 they deadlocked forever."""
    handler = FileHandler(str(minimal_project_dir))

    done = threading.Event()
    error: list[BaseException] = []

    def run():
        try:
            handler._mark_alert_as_sent('ref1_depth', {'value': 100.0})
            handler._mark_alert_as_sent('ref2_breadth', {'value': 50.0})
            done.set()
        except BaseException as exc:  # noqa: BLE001 — we want to surface any exit reason
            error.append(exc)
            done.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    finished = done.wait(timeout=3.0)

    assert finished, "_mark_alert_as_sent did not return within 3s — likely deadlocked"
    assert not error, f"_mark_alert_as_sent raised: {error[0]!r}"

    # State actually persisted to disk.
    with open(minimal_project_dir / 'sent_alerts.json') as f:
        saved = json.load(f)
    assert 'ref1_depth' in saved
    assert 'ref2_breadth' in saved
    assert saved['ref1_depth']['info']['value'] == 100.0


def test_check_if_alert_sent_round_trips(minimal_project_dir):
    """Sanity: _check_if_alert_sent reflects what _mark_alert_as_sent wrote."""
    handler = FileHandler(str(minimal_project_dir))
    assert handler._check_if_alert_sent('nope') is False
    handler._mark_alert_as_sent('ref_depth', {'value': 42})
    assert handler._check_if_alert_sent('ref_depth') is True
    assert handler._check_if_alert_sent('other_ref_depth') is False
