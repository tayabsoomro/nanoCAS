"""Classifier protocol — the abstract base for read-classifier plug-ins.

A `Classifier` is the thing nanoCAS uses to turn a FASTQ batch into a
coordinate-sorted, indexed BAM that the rolling coverage accumulator
can fold into its per-position depth arrays. Today only one
implementation exists (minimap2); the protocol is here so BWA, dorado,
or any other aligner can be dropped in without touching FileHandler.

Two operations a classifier must support:

1. `build_index(fasta_paths, output_dir, progress_callback)` — called
   ONCE at project creation, from `tasks.int_download_database`.
   Builds the search structure from the user's reference FASTA(s) and
   returns the path that should be persisted under
   `<project>/database/`.

2. `align(fastq_path, index_path, output_dir, output_basename)` —
   called on every FASTQ batch the watchdog observer notices. Must
   produce a coordinate-sorted, indexed BAM (i.e. `pysam.fetch` /
   `count_coverage` ready) at a known location so the accumulator can
   pick it up. The hot path; latency matters.

Out of scope for this protocol (yet):
- Taxonomic / k-mer classifiers (Kraken2, Centrifuge). Their natural
  output is per-read taxon assignments, not a BAM, so they need a
  separate protocol — a future `TaxonomicClassifier` ABC. Adding it
  alongside this one is straightforward; the alert path will then
  dispatch on result shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

ProgressCallback = Callable[[int, str], None]
"""Progress sink for long-running index builds. `(percent, message)`."""


class Classifier(ABC):
    """Alignment-producing classifier plug-in.

    Subclasses register themselves with the registry by stacking the
    `@register` decorator above the class definition. The `name`
    class attribute is the string stored in `alertinfo.cfg` and used
    by `registry.get_classifier(name)` to look the class back up.
    """

    name: str = ""  # short identifier, stored in alertinfo.cfg
    display_name: str = ""  # human-readable, for the UI dropdown

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this classifier can actually run on this host.

        Typically a `shutil.which(<binary>)` check. Used by
        `/list_classifiers` so the UI can grey out plug-ins whose
        underlying binary isn't installed.
        """
        ...

    # ------------------------------------------------------------------
    # One-time index build (project creation)
    # ------------------------------------------------------------------

    @abstractmethod
    def build_index(
        self,
        fasta_paths: list[Path],
        output_dir: Path,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        """Build the classifier's index from the supplied FASTA files.

        Called from `tasks.int_download_database` after the user picks
        their query sequences. Returns the absolute path to whatever
        artifact the classifier later wants to be passed back as
        `index_path` to `align()` — typically a single file (e.g. an
        `.mmi`) but could be a directory.

        `progress_callback` is optional; when supplied, the
        implementation should call it as the build progresses so the
        wizard UI can move its progress bar (LOGBOOK section 4.6 — must
        not block).
        """
        ...

    # ------------------------------------------------------------------
    # Per-batch hot path
    # ------------------------------------------------------------------

    @abstractmethod
    def align(
        self,
        fastq_path: Path,
        index_path: Path,
        output_dir: Path,
        output_basename: str,
    ) -> Path:
        """Align a single FASTQ batch and return the path to a
        coordinate-sorted, indexed BAM.

        Contract:
        - Output must be at `output_dir / f"{output_basename}_sorted.bam"`.
        - A `.bai` sibling MUST exist next to the BAM by the time this
          method returns. Without it the rolling-coverage accumulator
          fails — see LOGBOOK section 4.1 / PR #10.
        - Method is invoked from the watchdog dispatcher thread, so
          must be safe to call concurrently with other observers and
          must not raise non-fatal alignment errors (e.g. an empty
          BAM is fine; bad inputs should log + return without
          materialising a half-baked file).
        """
        ...
