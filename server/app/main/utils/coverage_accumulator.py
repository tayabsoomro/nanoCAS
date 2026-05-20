"""Rolling per-position depth accumulator persisted to disk.

Replaces the O(n^2) cumulative-BAM merge pipeline (LOGBOOK section 4.1)
for the *coverage-computation* half of FileHandler. Each new FASTQ
batch's BAM is read exactly once, its per-base depth is added into
uint32 numpy arrays keyed by reference name, and the accumulator is
persisted to disk via an atomic write. Reading the cumulative state for
stats is then O(ref_length) per reference (essentially free for the
small genomes nanoCAS targets) instead of O(total reads ever seen).

The alignment-viewer code path still needs a single merged + indexed
BAM (for pysam.fetch); that's handled by a separate `_ensure_merged_bam`
helper in routes.py which is invoked only when /get_alignments is
actually called, so the merge cost is no longer paid on every batch.

Storage layout under <project>/:
    coverage_state.npz   - numpy archive, one `depth__<ref>` uint32
                           array per reference seen so far.
    coverage_state.json  - sidecar with per-reference ref_length and
                           read_count, plus the global unmapped count.

Memory budget (uint32 = 4 bytes / position):
    1 Mb genome   ->   4 MB
    10 x 5 Mb     -> 200 MB
    1 x 3 Gb       ->  12 GB  (too big without sparse representation;
                              flagged as a follow-up, out of scope for
                              the current pathogen-detection use case).
"""

import json
import logging
import os
import numpy as np

logger = logging.getLogger('nanocas')

_DEPTH_DTYPE = np.uint32  # 4 bytes / position; max ~4 billion coverage
_DEPTH_KEY_PREFIX = 'depth__'


class CoverageAccumulator:
    """Per-project, per-reference depth array with atomic on-disk persistence.

    Not thread-safe on its own; callers that touch the accumulator from
    multiple threads must serialize externally. In nanoCAS today only the
    watchdog dispatcher thread mutates it, and only the eventlet hub
    reads the persisted files (via the lazy-merge helper), so the on-disk
    state is the synchronization point.
    """

    def __init__(self, state_dir: str):
        """`state_dir` is the project workspace (typically ~/.nanocas/<id>/)."""
        self.state_dir = state_dir
        self.depth_path = os.path.join(state_dir, 'coverage_state.npz')
        self.meta_path = os.path.join(state_dir, 'coverage_state.json')

        # depth[ref] is a uint32 numpy array of length ref_length.
        self.depth: dict[str, np.ndarray] = {}
        # lengths[ref] is the reference length. Kept separately so the
        # JSON sidecar is enough to know "which refs do we know about"
        # without loading the (potentially big) npz.
        self.lengths: dict[str, int] = {}
        # read_counts[ref] matches the semantics of pysam.AlignmentFile.count(ref):
        # it counts alignments, not unique reads — so secondary / supplementary
        # alignments inflate the number. That matches the old merged-BAM code
        # path; keeping it consistent avoids a behaviour change.
        self.read_counts: dict[str, int] = {}
        self.unmapped_count: int = 0

        self._load()

    # -- persistence ---------------------------------------------------

    def _load(self):
        """Best-effort restore from disk. Missing or corrupt files start fresh."""
        if os.path.exists(self.meta_path):
            try:
                with open(self.meta_path) as f:
                    meta = json.load(f)
                self.lengths = {k: int(v) for k, v in meta.get('lengths', {}).items()}
                self.read_counts = {k: int(v) for k, v in meta.get('read_counts', {}).items()}
                self.unmapped_count = int(meta.get('unmapped_count', 0))
            except Exception as e:
                logger.warning(f"Could not load {self.meta_path}: {e}")

        if os.path.exists(self.depth_path):
            try:
                # allow_pickle=False is intentional — we only ever store
                # plain numpy arrays here, and accepting pickled objects
                # from disk widens the trust surface for no benefit.
                with np.load(self.depth_path, allow_pickle=False) as archive:
                    for key in archive.files:
                        if key.startswith(_DEPTH_KEY_PREFIX):
                            ref = key[len(_DEPTH_KEY_PREFIX):]
                            self.depth[ref] = archive[key].astype(_DEPTH_DTYPE, copy=False)
            except Exception as e:
                logger.warning(f"Could not load {self.depth_path}: {e}")

    def save(self):
        """Persist atomically: write to a .tmp file then rename, so a crash
        mid-write can't corrupt the on-disk state. Both files are touched
        together; if either rename fails the in-memory accumulator is still
        the source of truth until the next successful save.

        Uses `np.savez` (uncompressed) deliberately. `savez_compressed`
        was tempting for the disk-size win but its per-call cost grows
        with the density of non-zero values — which is exactly what
        increases over the lifetime of a sequencing run. The compressed
        save went from 100 ms to 700 ms across 200 synthetic batches,
        re-introducing an O(n)-per-batch shape on the very code path
        this refactor was supposed to fix. Uncompressed save is O(array
        size) and stays flat, at the cost of ~5x more disk space.

        Note: `np.savez` auto-appends `.npz` if the target doesn't
        already end in it, so the tmp path MUST end in `.npz` for
        `os.replace` to find the file numpy actually wrote.
        """
        try:
            arrays = {f'{_DEPTH_KEY_PREFIX}{ref}': arr for ref, arr in self.depth.items()}
            tmp_depth = os.path.join(self.state_dir, '.coverage_state.tmp.npz')
            np.savez(tmp_depth, **arrays)
            os.replace(tmp_depth, self.depth_path)

            tmp_meta = self.meta_path + '.tmp'
            with open(tmp_meta, 'w') as f:
                json.dump({
                    'lengths': self.lengths,
                    'read_counts': self.read_counts,
                    'unmapped_count': self.unmapped_count,
                }, f)
            os.replace(tmp_meta, self.meta_path)
        except Exception as e:
            logger.error(f"Failed to persist coverage state: {e}", exc_info=True)

    # -- mutation ------------------------------------------------------

    def update_from_bam(self, bam):
        """Add coverage from one batch BAM (an open pysam.AlignmentFile)
        to the rolling state. The BAM is expected to be the per-FASTQ
        sorted BAM produced by `process_fastq_file`, NOT a cumulative
        merged one — that's the whole point of this refactor.

        `bam.references` carries the full reference set from the header
        (including refs with zero reads in this batch), so calling this
        on the first batch is sufficient to initialise zero arrays for
        every reference in the minimap2 index.
        """
        for ref in bam.references:
            ref_len = bam.lengths[bam.references.index(ref)]
            if ref not in self.depth:
                self.depth[ref] = np.zeros(ref_len, dtype=_DEPTH_DTYPE)
                self.lengths[ref] = ref_len
                self.read_counts[ref] = 0

            # pysam.count_coverage returns a 4-tuple of arrays (A,C,G,T),
            # each of length ref_length. Sum to get per-position depth.
            cov = bam.count_coverage(ref)
            batch_depth = np.sum(
                [np.asarray(c, dtype=np.uint32) for c in cov],
                axis=0,
                dtype=np.uint32,
            )
            self.depth[ref] += batch_depth.astype(_DEPTH_DTYPE, copy=False)
            self.read_counts[ref] += bam.count(ref)

        self.unmapped_count += getattr(bam, 'unmapped', 0)

    # -- read-only views ----------------------------------------------

    def refs(self) -> list[str]:
        """References with any data accumulated so far."""
        return list(self.depth.keys())

    def length(self, ref: str) -> int:
        return self.lengths.get(ref, 0)

    def depth_array(self, ref: str):
        """Return the per-position depth array for `ref`, or None if unseen.
        Used by the region-alert path to slice a sub-range without
        re-opening any BAM file."""
        return self.depth.get(ref)

    def stats(self, ref: str) -> tuple[float, float, int]:
        """Return (depth_coverage, breadth_coverage_pct, read_count) for `ref`."""
        arr = self.depth.get(ref)
        ref_len = self.lengths.get(ref, 0)
        if arr is None or ref_len == 0:
            return 0.0, 0.0, 0
        total = int(arr.sum())
        depth_cov = total / ref_len
        breadth_cov = int((arr >= 1).sum()) / ref_len * 100
        return depth_cov, breadth_cov, self.read_counts.get(ref, 0)
