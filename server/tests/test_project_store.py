"""Project registry: id validation, exact-match cache handling, delete."""

import os

import pytest

from app.main.utils import project_store as ps


@pytest.mark.parametrize('bad', ['', None, '..', '../x', 'a/b', 'a\\b', 'x' * 65, ' ', '.hidden'])
def test_invalid_ids_rejected(bad):
    assert ps.is_valid_project_id(bad) is False
    with pytest.raises(ValueError):
        ps.project_dir(bad)


def test_valid_uuid_id():
    pid = ps.new_project_id()
    assert ps.is_valid_project_id(pid)
    assert ps.project_dir(pid) == os.path.join(ps.NANOCAS_DIR, pid)


def test_cache_round_trip_and_exact_match_removal():
    a = ps.new_project_id()
    b = ps.new_project_id()
    ps.append_cache(a, '/data/run1', os.path.join(ps.NANOCAS_DIR, a))
    ps.append_cache(b, f'/data/{a}-lookalike', os.path.join(ps.NANOCAS_DIR, b))
    ids = [r['id'] for r in ps.read_cache()]
    assert a in ids and b in ids
    # Removing `a` must not touch `b`, even though b's minion path
    # contains a's id as a substring (the old code matched substrings).
    assert ps.remove_from_cache(a) is True
    ids = [r['id'] for r in ps.read_cache()]
    assert a not in ids and b in ids
    assert ps.remove_from_cache(a) is False
    ps.remove_from_cache(b)


def test_delete_project_removes_dir_and_row():
    pid = ps.new_project_id()
    pdir = ps.project_dir(pid)
    os.makedirs(pdir)
    ps.append_cache(pid, '/x', pdir)
    assert ps.delete_project(pid) is True
    assert not os.path.exists(pdir)
    assert ps.find_cache_entry(pid) is None


def test_delete_project_refuses_traversal():
    with pytest.raises(ValueError):
        ps.delete_project('..')
    with pytest.raises(ValueError):
        ps.delete_project('../../etc')


def test_list_projects_reads_names(project):
    pid, _ = project
    rows = {p['id']: p for p in ps.list_projects()}
    assert rows[pid]['name'] == 'Test project'
    assert rows[pid]['query_count'] == 1
