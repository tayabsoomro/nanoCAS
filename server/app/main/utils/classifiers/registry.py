"""Classifier registry + user plug-in discovery."""

from __future__ import annotations

import importlib.util
import inspect
import logging
import os

from .base import Classifier
from .centrifuge import CentrifugeClassifier
from .kraken2 import Kraken2Classifier
from .minimap2 import Minimap2Classifier

logger = logging.getLogger('nanocas')

DEFAULT_CLASSIFIER = 'minimap2'
PLUGIN_DIR = os.path.join(os.path.expanduser('~'), '.nanocas', 'plugins')

_BUILTIN: dict[str, type[Classifier]] = {
    Minimap2Classifier.name: Minimap2Classifier,
    Kraken2Classifier.name: Kraken2Classifier,
    CentrifugeClassifier.name: CentrifugeClassifier,
}
_plugins: dict[str, type[Classifier]] = {}
_plugins_loaded_from: str | None = None


def load_plugins(plugin_dir: str | None = None, force: bool = False) -> dict[str, type[Classifier]]:
    """Import every ``*.py`` in the plug-in directory and register each
    :class:`Classifier` subclass found. Errors in one file never break the
    others; they are logged and the file is skipped."""
    global _plugins_loaded_from
    plugin_dir = plugin_dir or os.getenv('NANOCAS_PLUGIN_DIR') or PLUGIN_DIR
    if _plugins_loaded_from == plugin_dir and not force:
        return _plugins
    _plugins.clear()
    _plugins_loaded_from = plugin_dir
    if not os.path.isdir(plugin_dir):
        return _plugins
    for fname in sorted(os.listdir(plugin_dir)):
        if not fname.endswith('.py') or fname.startswith('_'):
            continue
        path = os.path.join(plugin_dir, fname)
        try:
            spec = importlib.util.spec_from_file_location(f'nanocas_plugin_{fname[:-3]}', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            logger.error(f'Could not load classifier plug-in {path}: {exc}')
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Classifier) and obj is not Classifier and not inspect.isabstract(obj):
                if not obj.name or obj.name == 'abstract':
                    logger.error(f'Plug-in class {obj.__name__} in {fname} has no `name`; skipped')
                    continue
                if obj.name in _BUILTIN:
                    logger.warning(f'Plug-in {fname} redefines built-in classifier {obj.name}; ignored')
                    continue
                _plugins[obj.name] = obj
                logger.info(f'Registered classifier plug-in {obj.name} from {fname}')
    return _plugins


def all_classifiers() -> dict[str, type[Classifier]]:
    merged = dict(_BUILTIN)
    merged.update(load_plugins())
    return merged


def get_classifier(name: str | None) -> Classifier:
    name = name or DEFAULT_CLASSIFIER
    cls = all_classifiers().get(name)
    if cls is None:
        raise ValueError(f'Unknown classifier {name!r}; available: {", ".join(all_classifiers())}')
    return cls()


def describe_classifiers() -> list[dict]:
    out = []
    for name, cls in all_classifiers().items():
        info = cls().describe()
        info['builtin'] = name in _BUILTIN
        out.append(info)
    return out
