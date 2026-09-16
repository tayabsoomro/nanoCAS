"""Classifier plug-in interface.

nanoCAS processes each new read batch with a *classifier*: something that
takes a FASTQ (or BAM) file and says which target sequences or taxa the
reads belong to. Two kinds are supported:

``alignment``
    Produces a coordinate-sorted BAM against a reference set (minimap2 is
    the built-in one). nanoCAS then computes depth and breadth of coverage
    per reference and can evaluate GFF region alerts.

``taxonomic``
    Produces per-taxon read counts (Kraken2 and Centrifuge are built in).
    nanoCAS tracks read counts and read fractions per target taxon;
    depth/breadth are not defined for these.

Writing your own
----------------
Drop a Python file into ``~/.nanocas/plugins/`` that subclasses
:class:`Classifier` and implements the abstract methods. It is discovered
by name at start-up (see ``registry.py``). The contract:

* ``build_index`` must be idempotent and return a path that ``classify``
  can use later; for tools with prebuilt databases just validate the path.
* ``classify`` must be side-effect free apart from files it writes under
  ``workdir``; it is called once per batch from the watcher thread.
* Either set ``bam_path`` (alignment kind) or ``read_counts`` (taxonomic
  kind) on the returned :class:`BatchResult`.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

ProgressCallback = Callable[[int, str], None]


@dataclass
class BatchResult:
    """Outcome of classifying one batch."""
    #: coordinate-sorted BAM produced for this batch (alignment classifiers)
    bam_path: str | None = None
    #: reads per canonical target key (taxonomic classifiers); clade counts
    read_counts: dict[str, int] = field(default_factory=dict)
    #: reads in the batch (all, classified or not)
    total_reads: int = 0
    #: reads that hit nothing
    unclassified: int = 0
    #: free-form details (tool version, report path, ...)
    details: dict = field(default_factory=dict)


@dataclass
class TargetInfo:
    """A selectable target the classifier knows about (FASTA record or taxon)."""
    id: str
    name: str = ''
    description: str = ''
    length: int = 0


class Classifier(ABC):
    #: short unique identifier used in project configuration
    name: str = 'abstract'
    #: human-readable label for the UI
    label: str = 'Abstract classifier'
    #: one-line description for the UI
    description: str = ''
    #: 'alignment' or 'taxonomic'
    kind: str = 'alignment'
    #: what the user supplies as the reference: 'fasta' (uploaded files) or
    #: 'database' (path to a prebuilt database on the server)
    reference_input: str = 'fasta'
    #: executables that must be on PATH
    executables: tuple[str, ...] = ()
    #: how the UI should describe the database field (database classifiers)
    database_hint: str = ''

    # -- availability --------------------------------------------------

    def available(self) -> tuple[bool, str]:
        missing = [exe for exe in self.executables if shutil.which(exe) is None]
        if missing:
            return False, f"missing on PATH: {', '.join(missing)}"
        return True, ''

    def describe(self) -> dict:
        ok, reason = self.available()
        return {
            'name': self.name, 'label': self.label, 'description': self.description, 'kind': self.kind,
            'reference_input': self.reference_input, 'executables': list(self.executables),
            'available': ok, 'unavailable_reason': reason, 'database_hint': self.database_hint,
            'metrics': ['depth', 'breadth', 'reads', 'fraction'] if self.kind == 'alignment' else ['reads', 'fraction'],
        }

    # -- contract ------------------------------------------------------

    @abstractmethod
    def build_index(self, references: list[str], headers: list[str], output_dir: str,
                    progress: ProgressCallback | None = None) -> str:
        """Prepare whatever ``classify`` needs and return its path.

        ``references`` are uploaded FASTA paths (alignment kind) or a
        single database path (database kind); ``headers`` are the record
        ids / taxon names the user selected ('ALL' means everything).
        Raise ``RuntimeError`` with a user-readable message on failure.
        """

    @abstractmethod
    def classify(self, input_path: str, index_path: str, workdir: str, *, threads: int = 4) -> BatchResult:
        """Classify one batch file."""

    def list_targets(self, index_path: str) -> list[TargetInfo]:
        """Targets available in a built index (optional)."""
        return []

    @staticmethod
    def canonical_target(key: str) -> str:
        """Normalise a target identifier the way the classifier reports it."""
        return (key or '').strip().split()[0] if (key or '').strip() else ''
