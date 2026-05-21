"""Pluggable read classifier protocol.

LOGBOOK section 4.3 — `FileHandler` previously hard-coded minimap2 as an
inline shell pipeline. This package introduces a `Classifier` ABC and a
small registry so additional classifiers (BWA, Kraken2, Centrifuge, ...)
can be added without touching FileHandler at all. The minimap2
implementation moves into `minimap2.py` as the first plug-in — the
behavioural baseline.

Quick start (writing a new classifier):
    from .base import Classifier
    from .registry import register

    @register
    class MyClassifier(Classifier):
        name = "myclassifier"
        display_name = "My Classifier"

        def is_available(self):
            ...    # `which mybinary` etc.

        def build_index(self, fasta_paths, output_dir, progress_callback=None):
            ...    # one-time index build at project creation

        def align(self, fastq_path, index_path, output_dir, output_basename):
            ...    # per-FASTQ hot path; must return a sorted+indexed BAM

Then add `from . import myclassifier  # noqa: F401` to this file so the
side-effect import triggers `@register` at app startup.
"""

from .base import Classifier
from .registry import register, get_classifier, available_classifiers

# Side-effect import: triggers `@register` for each bundled plug-in so
# the registry is populated at the moment any caller imports this
# package. New plug-ins must be listed here to be discoverable.
from . import minimap2  # noqa: F401

__all__ = [
    'Classifier',
    'register',
    'get_classifier',
    'available_classifiers',
]
