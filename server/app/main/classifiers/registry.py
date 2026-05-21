"""Classifier registry.

Plug-ins register themselves at import time via the `@register`
class decorator. `get_classifier(name)` returns a fresh instance.
Looking the class up by name (rather than passing the class
through alertinfo.cfg) means the config file stays JSON-friendly.
"""

from __future__ import annotations

import logging
from typing import Type

from .base import Classifier

logger = logging.getLogger('nanocas')

_REGISTRY: dict[str, Type[Classifier]] = {}


def register(cls: Type[Classifier]) -> Type[Classifier]:
    """Class decorator. Add `@register` above any subclass of
    `Classifier` to make it discoverable by name."""
    if not cls.name:
        raise ValueError(
            f"Classifier {cls.__name__} must set a non-empty `name` class attribute"
        )
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        # Re-registration of the same class during hot-reload is fine;
        # a name collision between two different classes is not.
        raise ValueError(
            f"Classifier name {cls.name!r} is already registered by "
            f"{_REGISTRY[cls.name].__name__}"
        )
    _REGISTRY[cls.name] = cls
    logger.debug(f"Registered classifier: {cls.name} ({cls.__name__})")
    return cls


def get_classifier(name: str) -> Classifier:
    """Return a fresh `Classifier` instance for `name`.

    Raises ValueError with a useful "available: [...]" message on
    unknown names so configuration typos surface clearly instead of
    crashing deep in FileHandler.
    """
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown classifier {name!r}. Available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


def available_classifiers() -> list[dict]:
    """List every registered classifier with its availability status.

    The `available` flag reflects whether the underlying binary is
    actually on PATH right now — used by the `/list_classifiers`
    endpoint so the wizard can grey out plug-ins whose dependencies
    aren't installed. The check is cheap (typically a `shutil.which`),
    but isn't free, so callers should treat the result as a snapshot.
    """
    out = []
    for name, cls in sorted(_REGISTRY.items()):
        try:
            available = cls().is_available()
        except Exception as e:  # noqa: BLE001 — a misbehaving plug-in must not break the listing
            logger.warning(f"is_available() raised for {name}: {e}")
            available = False
        out.append({
            'name': name,
            'display_name': cls.display_name or name,
            'available': available,
        })
    return out
