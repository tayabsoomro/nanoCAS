"""Integration tests for the rolling coverage accumulator.

The PR #10 regression — `ValueError: fetch called on bamfile without
index` — happened because the PR #9 smoke test used a duck-typed
FakeBam that returned numpy arrays from `count_coverage` directly,
bypassing pysam's "must be indexed before fetch" precondition. These
tests use a REAL pysam.AlignmentFile against a real on-disk BAM, so
that class of bug can't slip through again.

If you only have time to keep one test in this file: keep
`test_count_coverage_requires_index` — it's the one that would have
caught PR #10.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pysam
import pytest

from app.main.utils.coverage_accumulator import CoverageAccumulator


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _write_synthetic_bam(path: Path, *, ref_name: str = "chr1", ref_len: int = 1000,
                        reads: list[tuple[int, int]] | None = None) -> Path:
    """Write a tiny coordinate-sorted BAM at `path`. Returns the same path.

    `reads` is a list of (start, length) tuples. Each generates one read
    with a simple `<length>M` CIGAR. Defaults to three reads covering
    positions 100-110, 200-220, 300-340.

    Does NOT index. Callers that need an index should call
    `pysam.index(str(path))` afterwards.
    """
    if reads is None:
        reads = [(100, 10), (200, 20), (300, 40)]

    header = {
        'HD': {'VN': '1.6', 'SO': 'coordinate'},
        'SQ': [{'LN': ref_len, 'SN': ref_name}],
    }
    with pysam.AlignmentFile(str(path), 'wb', header=header) as bam:
        for i, (start, length) in enumerate(reads):
            a = pysam.AlignedSegment()
            a.query_name = f'read{i}'
            a.query_sequence = 'A' * length
            a.flag = 0  # primary, mapped, forward
            a.reference_id = 0
            a.reference_start = start
            a.mapping_quality = 60
            a.cigar = ((0, length),)  # length M (match)
            a.query_qualities = pysam.qualitystring_to_array('I' * length)
            bam.write(a)
    return path


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


def test_count_coverage_requires_index(tmp_path):
    """Direct reproduction of the PR #10 regression.

    `pysam.AlignmentFile.count_coverage` internally calls `fetch`, which
    requires a `.bai` next to the BAM. Without it, pysam raises
    `ValueError: fetch called on bamfile without index`. The PR #9 code
    handed un-indexed per-FASTQ BAMs straight to count_coverage, and
    every batch silently failed. This test pins that down so we can't
    regress again.
    """
    bam_path = _write_synthetic_bam(tmp_path / "unindexed.bam")
    # No pysam.index() call here — that's the whole point.
    with pysam.AlignmentFile(str(bam_path), 'rb') as bam:
        with pytest.raises(ValueError, match='without index'):
            bam.count_coverage('chr1')


def test_accumulator_works_on_indexed_bam(tmp_path):
    """Full happy path: index a BAM, fold it into the accumulator,
    verify stats() returns the right depth/breadth/read_count."""
    bam_path = _write_synthetic_bam(tmp_path / "indexed.bam")
    pysam.index(str(bam_path))

    acc = CoverageAccumulator(str(tmp_path))
    with pysam.AlignmentFile(str(bam_path), 'rb') as bam:
        acc.update_from_bam(bam)

    # Reads cover 10 + 20 + 40 = 70 positions, all unique → breadth = 7%.
    # Total depth-sum is 70, ref_len is 1000, so depth_coverage = 0.07.
    depth, breadth, read_count = acc.stats('chr1')
    assert depth == pytest.approx(70 / 1000)
    assert breadth == pytest.approx(7.0)
    assert read_count == 3


def test_accumulator_persists_and_reloads(tmp_path):
    """Two `CoverageAccumulator` instances pointing at the same dir
    should see the same state. Verifies the .npz / .json round-trip."""
    bam_path = _write_synthetic_bam(tmp_path / "batch1.bam")
    pysam.index(str(bam_path))

    acc1 = CoverageAccumulator(str(tmp_path))
    with pysam.AlignmentFile(str(bam_path), 'rb') as bam:
        acc1.update_from_bam(bam)
    acc1.save()

    acc2 = CoverageAccumulator(str(tmp_path))
    assert acc2.stats('chr1') == acc1.stats('chr1')
    assert acc2.length('chr1') == 1000
    assert (acc2.depth_array('chr1') == acc1.depth_array('chr1')).all()


def test_accumulator_accumulates_across_batches(tmp_path):
    """Two batches against the same ref should sum, not replace."""
    bam1 = _write_synthetic_bam(tmp_path / "b1.bam", reads=[(0, 10)])
    bam2 = _write_synthetic_bam(tmp_path / "b2.bam", reads=[(5, 10)])
    pysam.index(str(bam1))
    pysam.index(str(bam2))

    acc = CoverageAccumulator(str(tmp_path))
    for p in [bam1, bam2]:
        with pysam.AlignmentFile(str(p), 'rb') as bam:
            acc.update_from_bam(bam)

    arr = acc.depth_array('chr1')
    # positions 0-4: depth 1 (b1 only); 5-9: depth 2 (both); 10-14: depth 1 (b2 only)
    assert arr is not None
    assert int(arr[0:5].sum()) == 5
    assert int(arr[5:10].sum()) == 10
    assert int(arr[10:15].sum()) == 5
    _, _, read_count = acc.stats('chr1')
    assert read_count == 2


def test_region_slice(tmp_path):
    """The region-alert path slices `depth_array(ref)`. Verify the slice
    semantics match GFF (1-based inclusive) -> numpy (0-based half-open)."""
    bam_path = _write_synthetic_bam(tmp_path / "b.bam", reads=[(99, 10)])  # covers positions 100-109 (1-based)
    pysam.index(str(bam_path))

    acc = CoverageAccumulator(str(tmp_path))
    with pysam.AlignmentFile(str(bam_path), 'rb') as bam:
        acc.update_from_bam(bam)

    arr = acc.depth_array('chr1')
    # GFF region 100..109 inclusive -> numpy slice [99:109]
    region_slice = arr[100 - 1:109]
    assert int(region_slice.sum()) == 10
