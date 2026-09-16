"""Sequencer simulator, demo projects and the simulation API."""

import gzip
import os
import shutil

import pytest

from app.main.utils import project_store, simulator
from app.main.utils.simulator import SCENARIOS, SimulatedRun, _Script, build_demo_references

HAS_TOOLS = shutil.which('minimap2') is not None and shutil.which('samtools') is not None
needs_tools = pytest.mark.skipif(not HAS_TOOLS, reason='minimap2 and samtools required')


def test_references_are_deterministic():
    a = build_demo_references()
    b = build_demo_references()
    assert a == b
    assert {k: len(v) for k, v in a.items()} == {'Host_control': 60000, 'Contaminant_X': 30000, 'Pathogen_Y': 20000}


@pytest.mark.parametrize('scenario', list(SCENARIOS))
def test_scripts_are_consistent(scenario):
    script = _Script(scenario, total_batches=40)
    for b in range(40):
        comp = script.composition(b)
        assert abs(sum(comp.values()) - 1.0) < 1e-9
        assert all(v >= 0 for v in comp.values())
        assert 3 <= script.q_mean(b) <= 13
    if scenario == 'contamination':
        assert script.composition(0)['contaminant'] == 0
        assert script.composition(39)['contaminant'] == pytest.approx(0.2)
    if scenario == 'flowcell_failure':
        import random
        assert script.active_channels(39, random.Random(1)) < script.active_channels(0, random.Random(1)) / 5
        assert script.q_mean(39) < 7
    if scenario == 'not_started':
        assert not any(script.writes_batch(b) for b in range(40))
    if scenario == 'stalled':
        assert script.writes_batch(0) and not script.writes_batch(39)


def test_write_batch_produces_fastq_and_summary(tmp_path):
    refs = build_demo_references()
    sim = SimulatedRun('p', str(tmp_path), refs, 'contamination', interval_sec=0, reads_per_batch=50,
                       total_batches=10, seed=1, emit=False)
    p0 = sim.write_batch(0)
    p1 = sim.write_batch(9)
    assert p0 and p1 and p0.endswith('.fastq.gz')
    with gzip.open(p1, 'rt') as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 50 * 4
    assert lines[0].startswith('@') and lines[2] == '+'
    assert len(lines[1]) == len(lines[3])
    summary = open(sim.summary_path).read().splitlines()
    assert summary[0].split('\t')[:4] == ['filename_fastq', 'read_id', 'run_id', 'channel']
    assert len(summary) == 1 + 100
    assert sim.batches_written == 2 and sim.reads_written == 100
    assert sim.sim_time > 0
    # No temp files left behind.
    assert not [f for f in os.listdir(tmp_path) if f.endswith('.tmp')]


def test_not_started_writes_nothing(tmp_path):
    sim = SimulatedRun('p', str(tmp_path), build_demo_references(), 'not_started', interval_sec=0,
                       total_batches=3, emit=False)
    assert sim.write_batch(0) is None
    assert os.listdir(tmp_path) == []


def test_scenarios_endpoint(client):
    body = client.get('/simulation/scenarios').json
    assert body['default'] == 'contamination'
    assert {s['id'] for s in body['scenarios']} == set(SCENARIOS)


def test_simulation_start_rejects_bad_input(client, project):
    pid, _ = project
    assert client.post('/simulation/start', json={'projectId': pid, 'scenario': 'bogus'}).status_code == 400
    assert client.post('/simulation/start', json={'projectId': '../x'}).status_code == 400
    assert client.get(f'/simulation/status?projectId={pid}').json == {'active': False, 'status': None}


@needs_tools
def test_create_demo_project_with_history(client):
    cfg = simulator.create_demo_project(scenario='contamination', seed_history=True, history_batches=8)
    pid = cfg['projectId']
    try:
        assert cfg['demo'] is True and cfg['demoScenario'] == 'contamination'
        pdir = project_store.project_dir(pid)
        assert os.path.exists(os.path.join(pdir, 'demo_reference.fasta'))
        assert any(f.endswith('.mmi') for f in os.listdir(os.path.join(pdir, 'database')))
        cov = client.get(f'/get_coverage?projectId={pid}').json
        refs = {r['reference'] for r in cov}
        assert refs == {'Host_control', 'Contaminant_X', 'Pathogen_Y', 'unmapped'}
        assert len({r['timestamp'] for r in cov}) == 8
        # Host coverage climbs; contaminant appears late; alerts are dated inside the replayed window.
        host = [r for r in cov if r['reference'] == 'Host_control']
        assert host[-1]['depth'] > host[0]['depth'] > 0
        alerts = client.get(f'/get_alerts?projectId={pid}').json['alerts']
        assert alerts[-1]['type'] == 'project_created'
        assert alerts[-1]['timestamp'] < alerts[0]['timestamp']
        rows = client.get('/get_all_analyses').json['data']
        me = next(r for r in rows if r['id'] == pid)
        assert me['demo'] is True and me['name'].startswith('Demo:')
        rh = client.get(f'/run_health?projectId={pid}').json
        assert rh['totals']['reads'] == 8 * 200
        assert rh['pores']['flow_cell_type'] == 'MinION / GridION'
    finally:
        project_store.delete_project(pid)


@needs_tools
def test_live_simulation_via_api(client):
    r = client.post('/demo/create', json={'scenario': 'clean'})
    assert r.status_code == 200, r.json
    pid = r.json['projectId']
    try:
        r = client.post('/simulation/start', json={'projectId': pid, 'scenario': 'contamination',
                                                   'interval_sec': 1, 'reads_per_batch': 40, 'total_batches': 3})
        assert r.status_code == 200, r.json
        assert r.json['monitoring_started'] is True
        assert r.json['status']['running'] is True
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            st = client.get(f'/simulation/status?projectId={pid}').json
            if st['status']['batches_written'] == 3 and not st['active']:
                break
            time.sleep(0.5)
        assert st['status']['batches_written'] == 3
        deadline = time.time() + 30
        while time.time() < deadline:
            ps = client.get(f'/get_processing_status?projectId={pid}').json
            if ps['files_processed'] == 3:
                break
            time.sleep(0.5)
        assert ps['files_processed'] == 3, ps
        # Starting again while stopped is fine; a second concurrent start is rejected.
        assert client.post('/simulation/stop', json={'projectId': pid}).json['stopped'] is False
        r = client.post('/simulation/start', json={'projectId': pid, 'scenario': 'clean', 'interval_sec': 60,
                                                   'total_batches': 5, 'reads_per_batch': 20})
        assert r.status_code == 200
        assert client.post('/simulation/start', json={'projectId': pid}).status_code == 400
        assert client.post('/simulation/stop', json={'projectId': pid}).json['stopped'] is True
        # Reset clears derived state.
        assert client.post('/simulation/reset', json={'projectId': pid}).json['reset'] is True
        assert client.get(f'/get_processing_status?projectId={pid}').json['files_processed'] == 0
    finally:
        from app.main.events import stop_listener
        simulator.stop_simulation(pid)
        stop_listener(pid)
        project_store.delete_project(pid)


@needs_tools
def test_demo_project_covers_every_subsystem(client, monkeypatch, tmp_path):
    """A seeded demo must exercise GFF feature alerts, all threshold kinds,
    lab results, simulated instrument status and the demo guide."""
    cfg = simulator.create_demo_project(scenario='contamination', seed_history=True, history_batches=10)
    pid = cfg['projectId']
    try:
        pdir = project_store.project_dir(pid)
        assert cfg['gff_file'] and os.path.exists(cfg['gff_file'])
        regions = client.get(f'/get_regions?projectId={pid}').json['regions']
        assert {r['id'] for r in regions['Contaminant_X']} == {'gene001', 'gene002'}
        assert cfg['classifier']['kind'] == 'alignment'
        assert all(q.get('key') for q in cfg['queries'])
        kinds = {q['name']: [k for k in ('alert_on_depth', 'alert_on_breadth', 'alert_on_reads', 'alert_on_fraction') if q.get(k)]
                 for q in cfg['queries']}
        assert kinds['Contaminant X'] == ['alert_on_depth', 'alert_on_breadth', 'alert_on_fraction']
        assert kinds['Pathogen Y'] == ['alert_on_depth', 'alert_on_reads']
        alerts = client.get(f'/get_alerts?projectId={pid}').json['alerts']
        types = {a['type'] for a in alerts}
        assert {'depth', 'breadth', 'fraction', 'region_depth'} <= types, types
        region_ids = {a['details'].get('region_id') for a in alerts if a['type'] == 'region_depth'}
        assert region_ids == {'gene001', 'gene002'}
        labs = client.get(f'/lab_results?projectId={pid}').json['results']
        assert {r['target'] for r in labs} == {'Contaminant_X', 'Pathogen_Y'}
        rh = client.get(f'/run_health?projectId={pid}').json
        assert rh['totals']['reads'] == 10 * 200
        assert [g['tab'] for g in cfg['demoGuide']][:1] == ['alerts']
        aln = client.get(f'/get_alignments?projectId={pid}&reference=Contaminant_X').json
        assert {r['id'] for r in aln['regions']} >= {'gene001', 'gene002', 'gene003'}
    finally:
        project_store.delete_project(pid)


def test_demo_project_with_plugin_classifier(client, monkeypatch, tmp_path):
    """The example k-mer plug-in runs the taxonomic path end to end with no
    external tools at all."""
    monkeypatch.setenv('NANOCAS_PLUGIN_DIR', str(tmp_path / 'plugins'))
    cfg = simulator.create_demo_project(scenario='contamination', seed_history=True, history_batches=6,
                                        classifier='kmer_demo')
    pid = cfg['projectId']
    try:
        assert (tmp_path / 'plugins' / 'kmer_demo_classifier.py').exists()
        assert cfg['classifier'] == {'name': 'kmer_demo', 'database': None, 'kind': 'taxonomic',
                                     'label': 'Example k-mer classifier (taxonomic)'}
        assert cfg['gff_file'] is None
        cov = client.get(f'/get_coverage?projectId={pid}').json
        last_ts = cov[-1]['timestamp']
        latest = {r['reference']: r for r in cov if r['timestamp'] == last_ts}
        assert latest['Host_control']['read_count'] > 500 and latest['Host_control']['depth'] == 0.0
        assert latest['Contaminant_X']['read_count'] > 0
        assert latest['unmapped']['read_count'] > 0
        assert latest['Host_control']['name'] == 'Host control'
        alerts = {a['type'] for a in client.get(f'/get_alerts?projectId={pid}').json['alerts']}
        assert 'fraction' in alerts or 'reads' in alerts
        assert 'region_depth' not in alerts
        names = {c['name']: c for c in client.get('/classifiers').json['classifiers']}
        assert names['kmer_demo']['builtin'] is False and names['kmer_demo']['available'] is True
        corr = client.get(f'/lab_correlation?projectId={pid}').json
        assert any(t['reference'] == 'Contaminant_X' and t['detected'] for t in corr['targets'])
    finally:
        project_store.delete_project(pid)
        from app.main.utils.classifiers.registry import load_plugins
        load_plugins(plugin_dir=str(tmp_path / 'none'), force=True)


def test_simulated_device_status_follows_scenario(tmp_path):
    refs = build_demo_references()
    sim = SimulatedRun('p', str(tmp_path), refs, 'not_started', interval_sec=0, total_batches=2, emit=False)
    assert sim.device_status()['acquisition_status'] == 'READY'
    sim2 = SimulatedRun('p', str(tmp_path), refs, 'clean', interval_sec=0, total_batches=2, emit=False)
    assert sim2.device_status()['acquisition_status'] == 'PROCESSING'
    assert sim2.device_status()['channel_count'] == 512
