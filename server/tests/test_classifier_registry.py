"""Unit tests for the classifier registry.

These tests are pure-Python — no minimap2 binary required. They cover
the contract of `register`, `get_classifier`, and `available_classifiers`
so the protocol's wiring stays honest as more plug-ins are added.

For end-to-end coverage of the actual minimap2 alignment path, see
`test_minimap2_classifier.py` (which is `pytest.mark.skipif`-gated on
the binary being present).
"""

from __future__ import annotations

import pytest

from app.main.classifiers import (
    Classifier,
    available_classifiers,
    get_classifier,
    register,
)
from app.main.classifiers import registry as registry_module


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot and restore the registry around every test so the
    fakes we register here can't leak into other tests (or vice versa)."""
    snapshot = dict(registry_module._REGISTRY)
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(snapshot)


class _FakeClassifier(Classifier):
    """Minimal concrete subclass for registry-only tests. No real
    alignment logic — calling align/build_index raises."""

    name = "_fake"
    display_name = "Fake classifier (testing only)"

    def is_available(self) -> bool:
        return True

    def build_index(self, fasta_paths, output_dir, progress_callback=None):
        raise NotImplementedError("Test fake")

    def align(self, fastq_path, index_path, output_dir, output_basename):
        raise NotImplementedError("Test fake")


def test_minimap2_is_registered_at_import():
    # The package's __init__.py imports the minimap2 module as a side
    # effect to trigger @register. If the registration ever quietly
    # breaks this test fails loudly instead of silently dropping the
    # built-in plug-in.
    names = {entry['name'] for entry in available_classifiers()}
    assert 'minimap2' in names


def test_register_decorator_returns_class():
    decorated = register(_FakeClassifier)
    assert decorated is _FakeClassifier
    assert '_fake' in {entry['name'] for entry in available_classifiers()}


def test_register_rejects_empty_name():
    class _NoName(Classifier):
        name = ""
        display_name = "no name"
        def is_available(self): return True
        def build_index(self, *a, **k): ...
        def align(self, *a, **k): ...
    with pytest.raises(ValueError, match="non-empty `name`"):
        register(_NoName)


def test_register_rejects_duplicate_name():
    register(_FakeClassifier)
    class _Collision(Classifier):
        name = "_fake"  # same as _FakeClassifier
        display_name = "collision"
        def is_available(self): return True
        def build_index(self, *a, **k): ...
        def align(self, *a, **k): ...
    with pytest.raises(ValueError, match="already registered"):
        register(_Collision)


def test_get_classifier_returns_fresh_instance():
    register(_FakeClassifier)
    a = get_classifier('_fake')
    b = get_classifier('_fake')
    assert isinstance(a, _FakeClassifier)
    assert isinstance(b, _FakeClassifier)
    assert a is not b  # fresh instances each call


def test_get_classifier_unknown_name_raises_with_listing():
    with pytest.raises(ValueError) as exc:
        get_classifier('not-a-real-classifier')
    assert "not-a-real-classifier" in str(exc.value)
    # The error message should include the available list so config
    # typos surface clearly instead of getting silently swallowed.
    assert "Available:" in str(exc.value)


def test_available_classifiers_reports_unavailable_cleanly():
    class _Broken(Classifier):
        name = "_broken"
        display_name = "broken"
        def is_available(self): raise RuntimeError("simulated boom")
        def build_index(self, *a, **k): ...
        def align(self, *a, **k): ...
    register(_Broken)
    entry = next(e for e in available_classifiers() if e['name'] == '_broken')
    # A misbehaving plug-in must not break the listing for everyone
    # else — it just shows up as unavailable.
    assert entry['available'] is False
