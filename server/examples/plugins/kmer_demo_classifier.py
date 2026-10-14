"""Example nanoCAS classifier plug-in: exact k-mer voting, no external tools.

Copy this file to ``~/.nanocas/plugins/`` (the demo does this for you) and
it appears in the wizard as "Example k-mer classifier (taxonomic)". It is
deliberately simple, pure Python, and slow-ish (fine for demo batch
sizes); its purpose is to show the plug-in contract end to end:

* ``build_index`` turns the uploaded FASTA into a k-mer -> record map;
* ``classify`` reads a FASTQ, samples k-mers from each read, and assigns
  the read to the record with the most hits;
* the result is a ``BatchResult`` with per-record read counts, i.e. the
  *taxonomic* kind (read counts and read fractions, no depth/breadth).
"""

from __future__ import annotations

import gzip
import json
import os

from app.main.utils.classifiers import BatchResult, Classifier, TargetInfo

K = 15
STEP = 7           # sample every 7th k-mer of a read
MIN_VOTES = 3      # reads with fewer hits are "unclassified"
_COMP = str.maketrans('ACGT', 'TGCA')


def _revcomp(seq: str) -> str:
    return seq.translate(_COMP)[::-1]


class KmerDemoClassifier(Classifier):
    name = 'kmer_demo'
    label = 'Example k-mer classifier (taxonomic)'
    description = ('Pure-Python exact k-mer voting against the uploaded FASTA. Ships as an example plug-in; '
                   'gives read counts and fractions per record, like a taxonomic classifier.')
    kind = 'taxonomic'
    reference_input = 'fasta'
    executables = ()

    def build_index(self, references, headers, output_dir, progress=None):
        os.makedirs(output_dir, exist_ok=True)
        wanted = {self.canonical_target(h) for h in headers if h and h != 'ALL'}
        index: dict[str, str] = {}
        records: dict[str, dict] = {}
        for path in references:
            if not path or not os.path.exists(path):
                continue
            for rec_id, desc, seq in _read_fasta(path):
                if wanted and rec_id not in wanted:
                    continue
                records[rec_id] = {'description': desc, 'length': len(seq)}
                for strand in (seq, _revcomp(seq)):
                    for i in range(0, len(strand) - K + 1):
                        index.setdefault(strand[i:i + K], rec_id)
        if not records:
            raise RuntimeError('None of the selected records were found in the FASTA.')
        index_path = os.path.join(output_dir, 'kmer_demo_index.json')
        with open(index_path, 'w') as fh:
            json.dump({'k': K, 'records': records, 'kmers': index}, fh)
        if progress:
            progress(90, f'k-mer index built for {len(records)} record(s)')
        return index_path

    def classify(self, input_path, index_path, workdir, *, threads=4):
        with open(index_path) as fh:
            data = json.load(fh)
        kmers: dict[str, str] = data['kmers']
        counts: dict[str, int] = {rec: 0 for rec in data['records']}
        total = unclassified = 0
        opener = gzip.open if input_path.endswith('.gz') else open
        with opener(input_path, 'rt') as fh:
            while True:
                header = fh.readline()
                if not header:
                    break
                seq = fh.readline().strip()
                fh.readline()
                fh.readline()
                total += 1
                votes: dict[str, int] = {}
                for i in range(0, max(0, len(seq) - K + 1), STEP):
                    hit = kmers.get(seq[i:i + K])
                    if hit:
                        votes[hit] = votes.get(hit, 0) + 1
                if votes:
                    best, n = max(votes.items(), key=lambda kv: kv[1])
                    if n >= MIN_VOTES:
                        counts[best] = counts.get(best, 0) + 1
                        continue
                unclassified += 1
        return BatchResult(read_counts=counts, total_reads=total, unclassified=unclassified,
                           details={'index': index_path})

    def list_targets(self, index_path):
        with open(index_path) as fh:
            data = json.load(fh)
        return [TargetInfo(id=r, name=r, description=v['description'], length=v['length'])
                for r, v in data['records'].items()]


def _read_fasta(path):
    opener = gzip.open if path.endswith('.gz') else open
    rec_id, desc, chunks = None, '', []
    with opener(path, 'rt') as fh:
        for line in fh:
            if line.startswith('>'):
                if rec_id:
                    yield rec_id, desc, ''.join(chunks).upper()
                parts = line[1:].strip().split(None, 1)
                rec_id, desc, chunks = parts[0], (parts[1] if len(parts) > 1 else ''), []
            else:
                chunks.append(line.strip())
    if rec_id:
        yield rec_id, desc, ''.join(chunks).upper()
