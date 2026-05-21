"""End-to-end integration test for the Minimap2 classifier plug-in.

Requires both `minimap2` and `samtools` on PATH. Auto-skipped if either
is missing so the suite can still run in environments that don't have
the bioinformatics tools installed (e.g. CI containers that haven't
been provisioned with them yet).

The point of this test is to catch regressions in the contract laid
down by `Classifier.align`: the output must be a coordinate-sorted,
**indexed** BAM. This is the very contract whose violation caused
PR #10's "fetch called on bamfile without index" loop.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pysam
import pytest

from app.main.classifiers.minimap2 import Minimap2Classifier


_MINIMAP2_AVAILABLE = bool(shutil.which("minimap2")) and bool(shutil.which("samtools"))
_skip_reason = "minimap2 + samtools must be on PATH for this test"


@pytest.fixture
def synthetic_fasta(tmp_path: Path) -> Path:
    """A tiny synthetic reference FASTA for indexing."""
    p = tmp_path / "ref.fa"
    # ~200 bp of made-up sequence; long enough for minimap2 to index.
    p.write_text(">chr1\n" + ("ACGT" * 50) + "\n")
    return p


@pytest.fixture
def synthetic_fastq(synthetic_fasta: Path, tmp_path: Path) -> Path:
    """A FASTQ containing one perfect read against `synthetic_fasta`."""
    p = tmp_path / "reads.fastq"
    # Use a substring of the reference as the read, so it will map.
    seq = "ACGT" * 25  # 100 bp from the start of chr1
    qual = "I" * len(seq)
    p.write_text(f"@r1\n{seq}\n+\n{qual}\n")
    return p


@pytest.mark.skipif(not _MINIMAP2_AVAILABLE, reason=_skip_reason)
def test_build_index_produces_mmi(synthetic_fasta, tmp_path):
    classifier = Minimap2Classifier()
    out_dir = tmp_path / "db"
    index_path = classifier.build_index(
        fasta_paths=[synthetic_fasta],
        output_dir=out_dir,
    )
    assert index_path.exists()
    assert index_path.suffix == ".mmi"


@pytest.mark.skipif(not _MINIMAP2_AVAILABLE, reason=_skip_reason)
def test_align_produces_sorted_indexed_bam(synthetic_fasta, synthetic_fastq, tmp_path):
    """The whole point of the contract: align() must leave a
    coordinate-sorted BAM AND its .bai sibling. This is what PR #10
    fixed; the test guards against a regression."""
    classifier = Minimap2Classifier()
    out_dir = tmp_path / "runs"
    index_path = classifier.build_index(
        fasta_paths=[synthetic_fasta],
        output_dir=tmp_path / "db",
    )

    bam_path = classifier.align(
        fastq_path=synthetic_fastq,
        index_path=index_path,
        output_dir=out_dir,
        output_basename="batch0",
    )

    # File location matches the contract documented in Classifier.align.
    assert bam_path == out_dir / "batch0_sorted.bam"
    assert bam_path.exists()
    # The `.bai` MUST exist. If it doesn't, pysam.count_coverage would
    # raise "fetch called on bamfile without index" downstream (PR #10).
    assert (bam_path.with_suffix(".bam.bai")).exists()

    # pysam can actually open + count_coverage on it without error —
    # this is the closest we can get to "the accumulator path will work"
    # without spinning up the full FileHandler.
    with pysam.AlignmentFile(str(bam_path), "rb") as bam:
        # chr1 from the FASTA we built the index from.
        assert "chr1" in bam.references
        # Should not raise — the bug we're guarding against would error here.
        cov = bam.count_coverage("chr1")
        assert sum(arr.sum() for arr in cov) > 0  # at least one base covered
