"""Centrifuge taxonomic classifier."""

from __future__ import annotations

import logging
import os
import subprocess

from .base import BatchResult, Classifier

logger = logging.getLogger('nanocas')


def parse_centrifuge_report(path: str) -> tuple[dict[str, int], dict[str, int], int]:
    """Parse ``--report-file`` output: name, taxID, taxRank, genomeSize,
    numReads, numUniqueReads, abundance. Returns (counts_by_name,
    counts_by_taxid, classified_reads)."""
    by_name: dict[str, int] = {}
    by_taxid: dict[str, int] = {}
    classified = 0
    with open(path) as fh:
        header = fh.readline().rstrip('\n').split('\t')
        idx = {h: i for i, h in enumerate(header)}
        for line in fh:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 5:
                continue
            try:
                n = int(parts[idx.get('numReads', 4)])
            except ValueError:
                continue
            name = parts[idx.get('name', 0)].strip().lower()
            taxid = parts[idx.get('taxID', 1)].strip()
            by_name[name] = by_name.get(name, 0) + n
            by_taxid[taxid] = by_taxid.get(taxid, 0) + n
            classified += n
    return by_name, by_taxid, classified


class CentrifugeClassifier(Classifier):
    name = 'centrifuge'
    label = 'Centrifuge (taxonomic)'
    description = ('Classify reads against a prebuilt Centrifuge index. Gives read counts and read fractions '
                   'per taxon; depth/breadth do not apply.')
    kind = 'taxonomic'
    reference_input = 'database'
    executables = ('centrifuge',)
    database_hint = 'Centrifuge index prefix, e.g. /db/p_compressed (files p_compressed.1.cf …).'

    def build_index(self, references, headers, output_dir, progress=None):
        if not references or not references[0]:
            raise RuntimeError('A Centrifuge index prefix is required.')
        prefix = os.path.expanduser(references[0])
        if not os.path.exists(prefix + '.1.cf'):
            raise RuntimeError(f'{prefix}.1.cf not found; give the index prefix without the .N.cf suffix.')
        if progress:
            progress(60, 'Centrifuge index validated')
        return prefix

    def classify(self, input_path, index_path, workdir, *, threads=4):
        os.makedirs(workdir, exist_ok=True)
        base = os.path.join(workdir, os.path.basename(input_path))
        report = base + '.creport'
        output = base + '.centrifuge'
        cmd = ['centrifuge', '-x', index_path, '-U', input_path, '-p', str(threads),
               '--report-file', report, '-S', output]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
        except FileNotFoundError:
            raise RuntimeError('centrifuge is not installed or not on PATH.')
        if proc.returncode != 0:
            raise RuntimeError(f'centrifuge failed: {proc.stderr.decode(errors="replace").strip()[:500]}')
        by_name, by_taxid, classified = parse_centrifuge_report(report)
        total = _count_input_reads(input_path)
        counts = dict(by_name)
        counts.update({f'taxid:{k}': v for k, v in by_taxid.items()})
        try:
            os.remove(output)
        except OSError:
            pass
        return BatchResult(read_counts=counts, total_reads=max(total, classified),
                           unclassified=max(0, total - classified), details={'report': report})

    @staticmethod
    def canonical_target(key: str) -> str:
        key = (key or '').strip()
        if key.isdigit():
            return f'taxid:{key}'
        return key.lower()


def _count_input_reads(path: str) -> int:
    import gzip
    opener = gzip.open if path.lower().endswith('.gz') else open
    n = 0
    try:
        with opener(path, 'rt') as fh:
            for i, _ in enumerate(fh):
                pass
            n = (i + 1) // 4
    except Exception:  # noqa: BLE001
        return 0
    return n
