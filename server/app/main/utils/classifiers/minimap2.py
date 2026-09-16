"""minimap2 alignment classifier (the default)."""

from __future__ import annotations

import datetime
import logging
import os
import subprocess

import pysam
from Bio import SeqIO

from .base import BatchResult, Classifier, ProgressCallback, TargetInfo

logger = logging.getLogger('nanocas')


class Minimap2Classifier(Classifier):
    name = 'minimap2'
    label = 'minimap2 (alignment)'
    description = ('Align reads to your reference sequences with minimap2 (map-ont preset). '
                   'Gives depth and breadth of coverage per sequence and per GFF feature.')
    kind = 'alignment'
    reference_input = 'fasta'
    executables = ('minimap2', 'samtools')

    def build_index(self, references, headers, output_dir, progress=None):
        os.makedirs(output_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        combined = os.path.join(output_dir, f'{stamp}.fa')
        index_path = os.path.join(output_dir, f'{stamp}.mmi')
        wanted = {self.canonical_target(h) for h in headers if h and h != 'ALL'}
        use_all = not wanted
        written = 0
        with open(combined, 'w') as out:
            for i, path in enumerate(references):
                if not path or not os.path.exists(path):
                    logger.warning(f'Reference FASTA not found: {path}')
                    continue
                for record in SeqIO.parse(path, 'fasta'):
                    if use_all or record.id in wanted:
                        SeqIO.write(record, out, 'fasta')
                        written += 1
                if progress:
                    progress(int(5 + (i + 1) / max(1, len(references)) * 45), f'Prepared reference {i + 1}/{len(references)}')
        if written == 0:
            raise RuntimeError('None of the selected sequences were found in the uploaded FASTA files.')
        if progress:
            progress(55, 'Building the minimap2 index…')
        log_path = os.path.join(output_dir, 'building_index.txt')
        with open(log_path, 'w') as log:
            try:
                result = subprocess.run(['minimap2', '-x', 'map-ont', '-d', index_path, combined],
                                        stdout=log, stderr=log, timeout=3600)
            except FileNotFoundError:
                raise RuntimeError('minimap2 is not installed or not on PATH.')
        if result.returncode != 0:
            raise RuntimeError(f'minimap2 failed to build the index (see {log_path}).')
        return index_path

    def classify(self, input_path, index_path, workdir, *, threads=4):
        os.makedirs(workdir, exist_ok=True)
        out = os.path.join(workdir, f'{os.path.basename(input_path)}_sorted.bam')
        lower = input_path.lower()
        if lower.endswith('.bam'):
            # External BAM: copy in and index; assumed coordinate-sorted.
            import shutil
            if os.path.abspath(input_path) != os.path.abspath(out):
                shutil.copy(input_path, out)
            self._index(out)
            return self._result(out)
        mm2 = ['minimap2', '-a', '-x', 'map-ont', '-t', str(threads), index_path, input_path]
        sort = ['samtools', 'sort', '-@', str(max(1, threads // 2)), '-o', out, '-']
        try:
            p1 = subprocess.Popen(mm2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p2 = subprocess.Popen(sort, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p1.stdout.close()
            _, sort_err = p2.communicate()
            mm2_err = p1.stderr.read()
            p1.stderr.close()
            p1.wait()
        except FileNotFoundError as exc:
            raise RuntimeError(f'{exc.filename or exc} is not installed or not on PATH.')
        if p1.returncode != 0:
            raise RuntimeError(f'minimap2 failed: {mm2_err.decode(errors="replace").strip()[:500]}')
        if p2.returncode != 0:
            raise RuntimeError(f'samtools sort failed: {sort_err.decode(errors="replace").strip()[:500]}')
        try:
            pysam.quickcheck(out)
        except pysam.utils.SamtoolsError as exc:
            raise RuntimeError(f'produced BAM is invalid: {exc}')
        self._index(out)
        return self._result(out)

    @staticmethod
    def _index(bam_path: str) -> None:
        bai = bam_path + '.bai'
        if os.path.exists(bai) and os.path.getmtime(bai) >= os.path.getmtime(bam_path):
            return
        pysam.index(bam_path)

    @staticmethod
    def _result(bam_path: str) -> BatchResult:
        return BatchResult(bam_path=bam_path)

    def list_targets(self, index_path):
        fasta = os.path.splitext(index_path)[0] + '.fa'
        targets = []
        if os.path.exists(fasta):
            for record in SeqIO.parse(fasta, 'fasta'):
                targets.append(TargetInfo(id=record.id, name=record.id, description=record.description, length=len(record.seq)))
        return targets
