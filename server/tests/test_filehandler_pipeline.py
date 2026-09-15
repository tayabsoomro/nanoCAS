"""FileHandler behaviour that doesn't need minimap2: dispatch filtering,
failure bookkeeping, coverage/alert evaluation on a real BAM."""

import json
import os

import pysam

from app.main.utils.FileHandler import FileHandler
from app.main.utils.alerts import AlertLog


def _project(tmp_path, **cfg_overrides):
    cfg = {
        'projectId': 'p1', 'fileType': 'FASTQ',
        'queries': [{'name': 'Target', 'header': 'chr1', 'depth_threshold': '0.05', 'alert_on_depth': True,
                     'breadth_threshold': '5', 'alert_on_breadth': True}],
        'alertNotifConfig': {},
    }
    cfg.update(cfg_overrides)
    (tmp_path / 'alertinfo.cfg').write_text(json.dumps(cfg))
    return tmp_path


def _bam(path, reads=((100, 10), (200, 20), (300, 40)), ref_len=1000, secondary=0):
    header = {'HD': {'VN': '1.6', 'SO': 'coordinate'}, 'SQ': [{'LN': ref_len, 'SN': 'chr1'}]}
    with pysam.AlignmentFile(str(path), 'wb', header=header) as bam:
        for i, (start, length) in enumerate(reads):
            a = pysam.AlignedSegment()
            a.query_name = f'read{i}'
            a.query_sequence = 'A' * length
            a.flag = 0
            a.reference_id = 0
            a.reference_start = start
            a.mapping_quality = 60
            a.cigar = ((0, length),)
            # Deliberately LOW base qualities: pysam's default
            # quality_threshold=15 would have dropped every base.
            a.query_qualities = pysam.qualitystring_to_array('#' * length)
            bam.write(a)
            for _ in range(secondary):
                s = pysam.AlignedSegment()
                s.query_name = a.query_name
                s.flag = 256
                s.reference_id = 0
                s.reference_start = start + 5
                s.mapping_quality = 0
                s.cigar = ((0, length),)
                bam.write(s)
    pysam.index(str(path))
    return path


def test_dispatch_ignores_non_matching_and_hidden_files(tmp_path):
    h = FileHandler(str(_project(tmp_path)))
    assert h._matches_type('/x/a.fastq.gz') and h._matches_type('/x/a.FQ')
    assert not h._matches_type('/x/a.bam') and not h._matches_type('/x/a.fasta')
    h._handle_path(str(tmp_path / 'notes.txt'))
    assert not h.in_progress_files and not h.processed_files


def test_failed_batch_not_marked_processed(tmp_path, monkeypatch):
    h = FileHandler(str(_project(tmp_path)))
    monkeypatch.setattr(h, 'process_fastq_file', lambda *a, **k: False)
    f = tmp_path / 'batch.fastq'
    f.write_text('@r\nACGT\n+\nIIII\n')
    h._handle_path(str(f), wait_stable=False)
    assert str(f) not in h.processed_files
    assert str(f) in h.failed_files
    assert json.load(open(tmp_path / 'failed_files.json'))
    assert not os.path.exists(tmp_path / 'processed_files.txt')
    # A failed file is not retried within the session.
    calls = []
    monkeypatch.setattr(h, 'process_fastq_file', lambda *a, **k: calls.append(1) or True)
    h._handle_path(str(f), wait_stable=False)
    assert calls == []
    # The failure raised a system alert.
    assert AlertLog(str(tmp_path)).read()[0]['type'] == 'batch_failed'


def test_successful_batch_recorded_once(tmp_path, monkeypatch):
    h = FileHandler(str(_project(tmp_path)))
    calls = []
    monkeypatch.setattr(h, 'process_fastq_file', lambda *a, **k: calls.append(1) or True)
    f = tmp_path / 'batch.fastq'
    f.write_text('@r\nACGT\n+\nIIII\n')
    h._handle_path(str(f), wait_stable=False)
    h._handle_path(str(f), wait_stable=False)
    assert calls == [1]
    assert open(tmp_path / 'processed_files.txt').read().strip() == str(f)


def test_coverage_counts_low_quality_bases_and_primary_reads_only(tmp_path):
    h = FileHandler(str(_project(tmp_path)))
    bam = _bam(tmp_path / 'b_sorted.bam', secondary=2)
    assert h.calculate_and_record_coverage(str(bam), '2026-01-01 00:00:00') is True
    depth, breadth, reads = h.coverage_acc.stats('chr1')
    assert reads == 3  # secondaries excluded
    assert depth == 70 / 1000  # low-quality bases still count
    assert abs(breadth - 7.0) < 1e-9
    rows = open(tmp_path / 'coverage.csv').read().splitlines()
    assert rows[0] == 'timestamp,reference,depth,breadth,read_count'
    assert rows[1].startswith('2026-01-01 00:00:00,chr1,0.07')
    assert rows[2].split(',')[1] == 'unmapped'


def test_alerts_fire_once_and_are_logged(tmp_path, monkeypatch):
    h = FileHandler(str(_project(tmp_path)))
    sent = []
    monkeypatch.setattr(h.notifier, 'send', lambda *a, **k: sent.append(a[1]))
    bam1 = _bam(tmp_path / 'b1_sorted.bam')
    bam2 = _bam(tmp_path / 'b2_sorted.bam')
    h.calculate_and_record_coverage(str(bam1))
    h.calculate_and_record_coverage(str(bam2))
    types = sorted(r['type'] for r in AlertLog(str(tmp_path)).read())
    assert types == ['breadth', 'depth']  # once each, not once per batch
    assert len(sent) == 2
    assert h._check_if_alert_sent('chr1_depth') and h._check_if_alert_sent('chr1_breadth')
    assert 'Target (chr1)' in sent[0]


def test_region_alert_dedup(tmp_path, monkeypatch):
    p = _project(tmp_path)
    (p / 'regions.json').write_text(json.dumps({'chr1': [
        {'id': 'geneA', 'start': 101, 'end': 110, 'alert_enabled': True, 'threshold': 0.5},
        {'id': 'geneB', 'start': 900, 'end': 950, 'alert_enabled': True, 'threshold': 0.5},
    ]}))
    h = FileHandler(str(p))
    monkeypatch.setattr(h.notifier, 'send', lambda *a, **k: None)
    bam = _bam(tmp_path / 'b_sorted.bam')
    h.calculate_and_record_coverage(str(bam))
    h.calculate_and_record_coverage(str(bam))
    region_alerts = [r for r in AlertLog(str(tmp_path)).read() if r['type'] == 'region_depth']
    assert len(region_alerts) == 1 and region_alerts[0]['details']['region_id'] == 'geneA'


def test_missing_index_raises_single_alert(tmp_path, monkeypatch):
    h = FileHandler(str(_project(tmp_path)))
    monkeypatch.setattr(h.notifier, 'send', lambda *a, **k: None)
    assert h.process_fastq_file(str(tmp_path / 'x.fastq')) is False
    assert h.process_fastq_file(str(tmp_path / 'y.fastq')) is False
    assert [r['type'] for r in AlertLog(str(tmp_path)).read()] == ['index_missing']


def test_status_and_existing_files(tmp_path):
    h = FileHandler(str(_project(tmp_path)))
    d = tmp_path / 'minion'
    d.mkdir()
    (d / 'a.fastq').write_text('x')
    (d / 'b.bam').write_text('x')
    (d / '.hidden.fastq').write_text('x')
    assert h.get_existing_files(str(d)) == [str(d / 'a.fastq')]
    assert h.status()['files_processed'] == 0
