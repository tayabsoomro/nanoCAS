"""minimap2 plug-in — the original nanoCAS classifier, now behind the
`Classifier` protocol. Behavioural baseline for everything else.

The pre-PR-C-1 implementation lived inline in FileHandler and tasks.py;
this module is just that code, moved behind the ABC so other classifiers
can replace it without touching FileHandler at all.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from Bio import SeqIO

from .base import Classifier, ProgressCallback
from .registry import register

logger = logging.getLogger('nanocas')


@register
class Minimap2Classifier(Classifier):
    """Long-read alignment via minimap2's `map-ont` preset.

    The hot path is a piped subprocess
    `minimap2 -a | samtools view -b | samtools sort -o`, followed by
    `samtools index`. The `samtools index` step is the contract LOGBOOK
    section 4.1 / PR #10 nailed down — without it, the rolling coverage
    accumulator's `pysam.count_coverage` blows up with "fetch called on
    bamfile without index" and silently drops every batch.
    """

    name = "minimap2"
    display_name = "minimap2 (ONT long reads)"

    def is_available(self) -> bool:
        # Both binaries needed: minimap2 for alignment and samtools
        # for the sort/index half of the pipeline.
        return bool(shutil.which("minimap2")) and bool(shutil.which("samtools"))

    # ------------------------------------------------------------------
    # Index build (project creation)
    # ------------------------------------------------------------------

    def build_index(
        self,
        fasta_paths: list[Path],
        output_dir: Path,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        """Build a `.mmi` index from the supplied FASTA file(s) via
        `minimap2 -d`.

        Per-query record filtering happens upstream in `tasks.py`
        (classifier-agnostic), so by the time we get here `fasta_paths`
        is usually a one-element list pointing at the combined FASTA
        the user actually wants indexed. Multi-input is supported for
        plug-ins that prefer to defer combining to the classifier.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if len(fasta_paths) == 1:
            # Avoid a redundant re-write when tasks.py already produced
            # the combined FASTA — disk I/O isn't free, and the
            # un-modified input is exactly what `minimap2 -d` wants.
            input_fa = Path(fasta_paths[0])
        else:
            input_fa = output_dir / "combined.fa"
            with open(input_fa, "w") as out:
                for p in fasta_paths:
                    for record in SeqIO.parse(str(p), "fasta"):
                        SeqIO.write(record, out, "fasta")

        if progress_callback:
            progress_callback(55, "Building the minimap2 index…")

        index_path = output_dir / f"{input_fa.stem}.mmi"
        build_log = output_dir / "building_index.txt"
        cmd = ["minimap2", "-x", "map-ont", "-d", str(index_path), str(input_fa)]
        try:
            with open(build_log, "w") as log_file:
                result = subprocess.run(cmd, stdout=log_file, stderr=log_file)
        except FileNotFoundError:
            logger.error("minimap2 not found — is it installed?")
            raise
        if result.returncode != 0:
            logger.error(f"minimap2 exited with code {result.returncode}. See {build_log}")
            raise RuntimeError(f"minimap2 index build failed (see {build_log})")
        logger.debug(f"minimap2 index built at {index_path}")
        return index_path

    # ------------------------------------------------------------------
    # Per-batch hot path
    # ------------------------------------------------------------------

    def align(
        self,
        fastq_path: Path,
        index_path: Path,
        output_dir: Path,
        output_basename: str,
    ) -> Path:
        """Align one FASTQ batch, produce a sorted+indexed BAM."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        sorted_bam = output_dir / f"{output_basename}_sorted.bam"

        # Shell pipe matches the original implementation. Two reasons
        # we keep `shell=True` here: (a) chaining three subprocesses
        # with PIPE forwarding is uglier than the one-liner, and
        # (b) the inputs are project-controlled paths under
        # NANOCAS_DIR, not arbitrary user input. LOGBOOK section 4.11
        # tracks switching this to chained Popens with `-t N` for
        # multi-threading; not in this PR.
        cmd = (
            f"minimap2 -a {index_path} {fastq_path} | "
            f"samtools view -b | "
            f"samtools sort -o {sorted_bam}"
        )
        logger.debug(f"Running minimap2 align: {cmd}")
        try:
            subprocess.run(
                cmd,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Error aligning {fastq_path}: {e.stderr.decode(errors='replace')}")
            raise

        # `samtools index` is part of the contract — see LOGBOOK 4.1.
        try:
            subprocess.run(
                ["samtools", "index", str(sorted_bam)], check=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"samtools index failed for {sorted_bam}: {e}")
            raise

        return sorted_bam
