"""Kraken2 taxonomic classifier."""

from __future__ import annotations

import logging
import os
import subprocess

from .base import BatchResult, Classifier, TargetInfo

logger = logging.getLogger('nanocas')

_REQUIRED_DB_FILES = ('hash.k2d', 'opts.k2d', 'taxo.k2d')


def parse_kraken_report(path: str) -> tuple[dict[str, int], dict[str, int], int, int]:
    """Parse a Kraken2 ``--report`` file.

    Returns ``(clade_counts_by_name, clade_counts_by_taxid, total_reads,
    unclassified)``. Names are stripped of the indentation Kraken2 uses to
    show rank depth and lower-cased for matching.
    """
    by_name: dict[str, int] = {}
    by_taxid: dict[str, int] = {}
    total = 0
    unclassified = 0
    with open(path) as fh:
        for line in fh:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 6:
                continue
            try:
                clade = int(parts[1])
            except ValueError:
                continue
            rank = parts[3].strip()
            taxid = parts[4].strip()
            name = parts[5].strip()
            if rank == 'U':
                unclassified = clade
                total += clade
            elif rank == 'R':
                total += clade
            by_name[name.lower()] = max(by_name.get(name.lower(), 0), clade)
            by_taxid[taxid] = clade
    return by_name, by_taxid, total, unclassified


class Kraken2Classifier(Classifier):
    name = 'kraken2'
    label = 'Kraken2 (taxonomic)'
    description = ('Classify reads against a prebuilt Kraken2 database. Gives read counts and read fractions '
                   'per taxon; depth/breadth do not apply.')
    kind = 'taxonomic'
    reference_input = 'database'
    executables = ('kraken2',)
    database_hint = 'Path to a Kraken2 database directory (contains hash.k2d, opts.k2d, taxo.k2d).'

    def build_index(self, references, headers, output_dir, progress=None):
        if not references or not references[0]:
            raise RuntimeError('A Kraken2 database directory is required.')
        db = os.path.expanduser(references[0])
        missing = [f for f in _REQUIRED_DB_FILES if not os.path.exists(os.path.join(db, f))]
        if missing:
            raise RuntimeError(f'{db} is not a Kraken2 database (missing {", ".join(missing)}).')
        if progress:
            progress(60, 'Kraken2 database validated')
        return db

    def classify(self, input_path, index_path, workdir, *, threads=4):
        os.makedirs(workdir, exist_ok=True)
        base = os.path.join(workdir, os.path.basename(input_path))
        report = base + '.kreport'
        output = base + '.kraken'
        cmd = ['kraken2', '--db', index_path, '--threads', str(threads), '--report', report, '--output', output]
        if input_path.lower().endswith('.gz'):
            cmd.append('--gzip-compressed')
        cmd.append(input_path)
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
        except FileNotFoundError:
            raise RuntimeError('kraken2 is not installed or not on PATH.')
        if proc.returncode != 0:
            raise RuntimeError(f'kraken2 failed: {proc.stderr.decode(errors="replace").strip()[:500]}')
        by_name, by_taxid, total, unclassified = parse_kraken_report(report)
        counts = dict(by_name)
        counts.update({f'taxid:{k}': v for k, v in by_taxid.items()})
        try:
            os.remove(output)  # per-read assignments are large and unused
        except OSError:
            pass
        return BatchResult(read_counts=counts, total_reads=total, unclassified=unclassified,
                           details={'report': report})

    @staticmethod
    def canonical_target(key: str) -> str:
        key = (key or '').strip()
        if key.isdigit():
            return f'taxid:{key}'
        return key.lower()

    def list_targets(self, index_path):
        names = os.path.join(index_path, 'taxonomy', 'names.dmp')
        # Listing an entire taxonomy is not useful in a picker; the UI takes
        # taxon names / taxids typed by the user instead.
        return [TargetInfo(id='', name='', description=f'taxonomy present: {os.path.exists(names)}')] if False else []
