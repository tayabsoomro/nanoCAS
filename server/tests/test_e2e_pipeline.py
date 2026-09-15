"""End-to-end pipeline test with real minimap2 + samtools.

Builds a reference index from a synthetic FASTA, starts the live
listener (watchdog observer + run-health monitor), drops a synthetic
FASTQ into the watched directory and checks that the batch is aligned,
folded into the coverage accumulator, written to coverage.csv, that the
depth alert fires exactly once, and that the alignment viewer's lazy
merge produces a readable BAM.

Skipped automatically when minimap2 / samtools are not on PATH.
"""

import gzip
import json
import os
import random
import shutil
import time

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which('minimap2') is None or shutil.which('samtools') is None,
    reason='minimap2 and samtools are required for the end-to-end test',
)


def _random_seq(n, seed):
    rng = random.Random(seed)
    return ''.join(rng.choice('ACGT') for _ in range(n))


def _write_fastq(path, ref_seq, n_reads, read_len, seed, gz=False):
    rng = random.Random(seed)
    opener = gzip.open if gz else open
    with opener(path, 'wt') as fh:
        for i in range(n_reads):
            start = rng.randint(0, len(ref_seq) - read_len)
            seq = ref_seq[start:start + read_len]
            fh.write(f'@read{i}\n{seq}\n+\n{"5" * read_len}\n')


def _wait_for(pred, timeout=60, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return pred()


@pytest.fixture
def e2e_project(tmp_path):
    from app.main.utils import project_store
    from app.main.utils.tasks import int_download_database

    ref_a = _random_seq(20000, seed=1)
    ref_b = _random_seq(15000, seed=2)
    upload_dir = tmp_path / 'upload'
    upload_dir.mkdir()
    fasta = upload_dir / 'refs.fasta'
    fasta.write_text(f'>targetA some description\n{ref_a}\n>targetB\n{ref_b}\n')

    minion = tmp_path / 'fastq_pass'
    minion.mkdir()
    pid = project_store.new_project_id()
    pdir = project_store.project_dir(pid)
    os.makedirs(pdir)
    cfg = {
        'projectId': pid, 'projectName': 'e2e', 'fileType': 'FASTQ', 'minion': str(minion),
        'queries': [
            {'name': 'Target A', 'file': str(fasta), 'header': 'targetA', 'headers': ['targetA'],
             'depth_threshold': '1', 'alert_on_depth': True, 'breadth_threshold': '80', 'alert_on_breadth': True},
            {'name': 'Target B', 'file': str(fasta), 'header': 'targetB', 'headers': ['targetB'],
             'depth_threshold': '1000', 'alert_on_depth': True, 'alert_on_breadth': False},
        ],
        'alertNotifConfig': {},
        'runHealthConfig': {'checkIntervalSec': 5, 'consecutiveChecks': 1, 'runStartTimeoutMin': 60},
    }
    project_store.save_config(pid, cfg)
    project_store.append_cache(pid, str(minion), pdir)

    progress = []
    result = int_download_database(db_data=cfg, nanocas_location=pdir + os.sep, queries=cfg['queries'],
                                   progress_callback=lambda p, m: progress.append((p, m)))
    assert isinstance(result, dict), f'index build failed: {result}'
    assert progress[-1][0] == 100
    assert any(f.endswith('.mmi') for f in os.listdir(os.path.join(pdir, 'database')))

    yield {'pid': pid, 'pdir': pdir, 'minion': minion, 'ref_a': ref_a, 'ref_b': ref_b}

    from app.main.events import stop_listener
    stop_listener(pid)
    project_store.delete_project(pid)


def test_live_listener_processes_fastq_and_alerts(e2e_project, client, monkeypatch):
    from app.main.events import get_listener, start_listener
    from app.main.utils.alerts import AlertLog

    pid, pdir, minion = e2e_project['pid'], e2e_project['pdir'], e2e_project['minion']

    # A file that exists before monitoring starts is caught up on start.
    _write_fastq(minion / 'batch0.fastq', e2e_project['ref_a'], n_reads=40, read_len=2000, seed=10)

    start_listener(pid, str(minion))
    bundle = get_listener(pid)
    assert bundle is not None
    handler = bundle['handler']
    sent = []
    monkeypatch.setattr(handler.notifier, 'send', lambda subject, msg, **kw: sent.append(msg))

    assert _wait_for(lambda: handler.status()['files_processed'] == 1), handler.status()

    # A file that lands while monitoring is live (atomic rename, as MinKNOW does).
    tmp = minion / '.batch1.fastq.gz.tmp'
    _write_fastq(tmp, e2e_project['ref_a'], n_reads=40, read_len=2000, seed=11, gz=True)
    os.replace(tmp, minion / 'batch1.fastq.gz')
    assert _wait_for(lambda: handler.status()['files_processed'] == 2), handler.status()
    assert handler.status()['files_failed'] == 0

    depth, breadth, reads = handler.coverage_acc.stats('targetA')
    assert reads == 80, reads
    assert depth == pytest.approx(80 * 2000 / 20000, rel=0.05)
    assert breadth > 90
    assert handler.coverage_acc.stats('targetB')[2] == 0

    # Depth ≥ 1x and breadth ≥ 80% on targetA -> exactly one alert each,
    # even though two batches crossed the thresholds.
    types = sorted(r['type'] for r in AlertLog(pdir).read() if r['source'] == 'coverage')
    assert types == ['breadth', 'depth'], types
    assert len(sent) == 2

    # HTTP surface reflects the processed state.
    cov = client.get(f'/get_coverage?projectId={pid}').json
    refs = {r['reference'] for r in cov}
    assert refs == {'targetA', 'targetB', 'unmapped'}
    assert any(r['name'] == 'Target A' for r in cov)
    status = client.get(f'/get_processing_status?projectId={pid}').json
    assert status['monitoring'] is True and status['files_processed'] == 2

    aln = client.get(f'/get_alignments?projectId={pid}&reference=targetA').json
    assert aln['ref_length'] == 20000 and aln['total_alignments'] == 80
    # Display name also resolves.
    aln2 = client.get(f'/get_alignments?projectId={pid}&reference=Target%20B').json
    assert aln2['reference'] == 'targetB' and aln2['total_alignments'] == 0

    # Run-health snapshot exists even without a sequencing summary.
    # The monitor refreshes its snapshot every checkIntervalSec (5 s here).
    assert _wait_for(lambda: client.get(f'/run_health?projectId={pid}').json.get('inputs', {}).get('data_files') == 2, timeout=20)
    rh = client.get(f'/run_health?projectId={pid}').json
    assert rh['monitoring'] is True

    alerts = client.get(f'/get_alerts?projectId={pid}').json
    assert alerts['monitoring'] is True
    assert {r['id'] for r in alerts['rules']} >= {'run_not_started', 'data_stalled'}

    # Restart: nothing is reprocessed and the accumulator reloads.
    from app.main.events import stop_listener
    assert stop_listener(pid)
    start_listener(pid, str(minion))
    handler2 = get_listener(pid)['handler']
    time.sleep(2)
    assert handler2.status()['files_processed'] == 2
    assert handler2.coverage_acc.stats('targetA')[2] == 80
    stop_listener(pid)


def test_unaligned_reads_are_counted_as_unmapped(e2e_project):
    from app.main.utils.FileHandler import FileHandler
    pid, pdir, minion = e2e_project['pid'], e2e_project['pdir'], e2e_project['minion']
    handler = FileHandler(pdir + os.sep)
    junk = _random_seq(30000, seed=99)
    _write_fastq(minion / 'junk.fastq', junk, n_reads=20, read_len=1500, seed=12)
    assert handler.process_fastq_file(str(minion / 'junk.fastq'), '2026-01-01 00:00:00') is True
    assert handler.coverage_acc.unmapped_count == 20
    assert handler.coverage_acc.stats('targetA')[2] == 0
    rows = [l for l in open(os.path.join(pdir, 'coverage.csv')) if l.startswith('2026-01-01')]
    assert any(l.split(',')[1] == 'unmapped' and l.strip().endswith(',20') for l in rows)


def test_corrupt_fastq_fails_cleanly(e2e_project):
    from app.main.utils.FileHandler import FileHandler
    pid, pdir, minion = e2e_project['pid'], e2e_project['pdir'], e2e_project['minion']
    handler = FileHandler(pdir + os.sep)
    bad = minion / 'bad.fastq'
    bad.write_text('this is not a fastq\n@x\nACGT\n')
    handler._handle_path(str(bad), wait_stable=False)
    st = handler.status()
    # minimap2 tolerates a lot; whichever way it goes, the file must be
    # accounted for exactly once and never crash the dispatcher.
    assert st['files_processed'] + st['files_failed'] == 1
    assert not os.path.exists(os.path.join(pdir, 'minimap2', 'runs', 'bad.fastq_sorted.bam.tmp'))
