"""Regression tests for FASTA header → reference-ID normalization.

LOGBOOK §4.17: NCBI-style FASTA headers like
`>NC_000913.3 Escherichia coli K-12 substr. MG1655`
round-trip through samtools as just `NC_000913.3`, but the original
nanoCAS wizard saved the full descriptive line into alertinfo.cfg, so
`header_to_query[ref]` would silently miss when the alert path looked
up `bam.references[0]`. These tests pin the normalization down at both
ends (server-side parser + FileHandler lookup).
"""

from __future__ import annotations

import json

import pytest

from app.main.utils.FileHandler import FileHandler, _canonical_ref_id


@pytest.mark.parametrize("raw,expected", [
    ("NC_000913.3", "NC_000913.3"),
    ("NC_000913.3 Escherichia coli K-12", "NC_000913.3"),
    ("chr1", "chr1"),
    ("  leading spaces  ", "leading"),
    ("", ""),
    (None, ""),
    ("\t\t", ""),
    ("only_one_token", "only_one_token"),
])
def test_canonical_ref_id_strips_to_first_token(raw, expected):
    assert _canonical_ref_id(raw) == expected


def test_filehandler_lookup_normalizes_legacy_full_headers(tmp_path):
    """A project whose alertinfo.cfg was written before the wizard
    tokenized headers (i.e. `header` is the full descriptive line)
    must still match against `bam.references[0]` (the canonical first
    token). Without normalization the alert was silently dropped — see
    LOGBOOK §4.17."""
    cfg = {
        'fileType': 'FASTQ',
        'projectId': 'test-norm',
        'queries': [{
            'name': 'E. coli K-12',
            # Full descriptive header as the wizard used to save it.
            'header': 'NC_000913.3 Escherichia coli K-12 substr. MG1655, complete genome',
            'depth_threshold': '5',
            'alert_on_depth': True,
        }],
    }
    (tmp_path / 'alertinfo.cfg').write_text(json.dumps(cfg))
    handler = FileHandler(str(tmp_path))

    # The lookup key the alert path uses is exactly what bam.references
    # would return — `NC_000913.3` — and it must hit the query.
    assert 'NC_000913.3' in handler.header_to_query
    assert handler.header_to_query['NC_000913.3']['name'] == 'E. coli K-12'

    # And the original full header is NOT a key (we collapsed it).
    full = 'NC_000913.3 Escherichia coli K-12 substr. MG1655, complete genome'
    assert full not in handler.header_to_query
