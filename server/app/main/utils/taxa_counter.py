"""Cumulative per-target read counts for taxonomic classifiers.

The alignment path keeps per-position depth in ``CoverageAccumulator``;
taxonomic classifiers only yield read counts, which are accumulated here
and persisted to ``taxa_state.json`` next to the coverage state.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger('nanocas')


class TaxaCounter:
    def __init__(self, state_dir: str):
        self.path = os.path.join(state_dir, 'taxa_state.json')
        self.counts: dict[str, int] = {}
        self.total_reads = 0
        self.unclassified = 0
        self.batches = 0
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as fh:
                data = json.load(fh)
            self.counts = {k: int(v) for k, v in data.get('counts', {}).items()}
            self.total_reads = int(data.get('total_reads', 0))
            self.unclassified = int(data.get('unclassified', 0))
            self.batches = int(data.get('batches', 0))
        except (OSError, ValueError) as exc:
            logger.warning(f'Could not load {self.path}: {exc}')

    def save(self) -> None:
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump({'counts': self.counts, 'total_reads': self.total_reads,
                       'unclassified': self.unclassified, 'batches': self.batches}, fh)
        os.replace(tmp, self.path)

    def update(self, read_counts: dict[str, int], total_reads: int, unclassified: int,
               targets: list[str] | None = None) -> None:
        """Add one batch. Only ``targets`` (canonical keys) are retained to
        keep the state small; pass None to keep everything."""
        keys = set(targets) if targets is not None else set(read_counts)
        for key in keys:
            self.counts[key] = self.counts.get(key, 0) + int(read_counts.get(key, 0))
        self.total_reads += int(total_reads)
        self.unclassified += int(unclassified)
        self.batches += 1

    def stats(self, key: str) -> tuple[int, float]:
        reads = self.counts.get(key, 0)
        fraction = (reads / self.total_reads * 100.0) if self.total_reads else 0.0
        return reads, fraction
