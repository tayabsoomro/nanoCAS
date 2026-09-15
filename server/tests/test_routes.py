"""HTTP API behaviour through the Flask test client."""

import io
import json
import os


def test_version_and_health(client):
    assert client.get('/version').json['name'] == 'nanoCAS'
    h = client.get('/health').json
    assert set(h['tools']) == {'minimap2', 'samtools'}


def test_project_id_validation(client):
    for pid in ['..', '../x', 'a/b', '']:
        r = client.get(f'/get_coverage?projectId={pid}')
        assert r.status_code == 400, pid
        assert 'error' in r.json
    assert client.get('/get_coverage?projectId=does-not-exist').status_code == 404


def test_get_uid_is_unique_per_call(client):
    a = client.post('/get_uid', data={'minION': '/same/dir'}).json['uid']
    b = client.post('/get_uid', data={'minION': '/same/dir'}).json['uid']
    assert a != b
    from app.main.utils import project_store
    assert project_store.remove_from_cache(a) and project_store.remove_from_cache(b)


def test_delete_analyses_rejects_traversal(client):
    r = client.post('/delete_analyses', data={'uid': '../../'})
    assert r.status_code == 400


def test_delete_analyses_removes_project(client, project):
    pid, pdir = project
    r = client.post('/delete_analyses', data={'uid': pid})
    assert r.json['found'] is True
    assert not os.path.exists(pdir)


def test_get_all_analyses_lists_project(client, project):
    pid, _ = project
    rows = {p['id']: p for p in client.get('/get_all_analyses').json['data']}
    assert rows[pid]['name'] == 'Test project'
    assert rows[pid]['monitoring'] is False


def test_get_analysis_info_redacts_password(client, project):
    pid, _ = project
    from app.main.utils import project_store
    cfg = project_store.load_config(pid)
    cfg['alertNotifConfig'] = {'enableEmail': True, 'emailConfig': {'sender': 'a@b.c', 'recipient': 'd@e.f',
                                                                    'smtpServer': 's', 'smtpPort': 587,
                                                                    'password': 'hunter2'}}
    project_store.save_config(pid, cfg)
    data = client.get(f'/get_analysis_info?uid={pid}').json['data']
    assert data['alertNotifConfig']['emailConfig']['password'] == '********'
    assert data['alertNotifConfig']['emailConfig']['passwordSet'] is True
    assert data['runHealthConfig']['minMedianQ'] == 9.0


def test_get_coverage_maps_names_and_skips_bad_rows(client, project):
    pid, pdir = project
    with open(os.path.join(pdir, 'coverage.csv'), 'w') as fh:
        fh.write('timestamp,reference,depth,breadth,read_count\n')
        fh.write('2026-01-01 00:00:00,chr1,1.5,20.0,3\n')
        fh.write('garbage\n')
        fh.write('2026-01-01 00:00:00,unmapped,0,0,7\n')
    rows = client.get(f'/get_coverage?projectId={pid}').json
    assert [r['reference'] for r in rows] == ['chr1', 'unmapped']
    assert rows[0]['name'] == 'E. coli'
    assert rows[1]['name'] == 'unmapped'
    summary = client.get(f'/get_coverage_summary?projectId={pid}').json['references']
    assert summary[0]['reference'] == 'chr1' and summary[0]['depth_threshold'] == 2.0
    assert summary[0]['breadth_threshold'] == 50.0


def test_get_coverage_empty_project_returns_list(client, project):
    pid, _ = project
    assert client.get(f'/get_coverage?projectId={pid}').json == []


def test_alerts_endpoint(client, project):
    pid, pdir = project
    from app.main.utils.alerts import AlertLog
    AlertLog(pdir).append('depth', 'critical', 'hello', project_id=pid)
    body = client.get(f'/get_alerts?projectId={pid}').json
    assert body['total'] == 1 and body['alerts'][0]['message'] == 'hello'
    assert 'desktop' in body['channels']


def test_processing_status_without_listener(client, project):
    pid, pdir = project
    with open(os.path.join(pdir, 'processed_files.txt'), 'w') as fh:
        fh.write('/a/b.fastq\n/a/c.fastq\n')
    with open(os.path.join(pdir, 'failed_files.json'), 'w') as fh:
        json.dump({'/a/d.fastq': 'boom'}, fh)
    body = client.get(f'/get_processing_status?projectId={pid}').json
    assert body == {'monitoring': False, 'files_processed': 2, 'files_failed': 1,
                    'failed_files': {'/a/d.fastq': 'boom'}, 'last_file': 'c.fastq',
                    'last_file_full_path': '/a/c.fastq'}


def test_run_health_without_summary_is_404(client, project):
    pid, _ = project
    r = client.get(f'/run_health?projectId={pid}')
    assert r.status_code == 404


def test_run_health_one_shot_parse(client, project):
    pid, pdir = project
    from app.main.utils import project_store
    minion = project_store.load_config(pid)['minion']
    with open(os.path.join(minion, 'sequencing_summary_x.txt'), 'w') as fh:
        fh.write('read_id\tchannel\tstart_time\tsequence_length_template\tmean_qscore_template\n')
        for i in range(30):
            fh.write(f'r{i}\t{i + 1}\t{i}\t1000\t11\n')
    body = client.get(f'/run_health?projectId={pid}').json
    assert body['totals']['reads'] == 30 and body['monitoring'] is False
    assert body['pores']['channels_seen'] == 30


def test_run_health_defaults(client):
    body = client.get('/run_health_defaults').json
    assert 'minMedianQ' in body['defaults'] and 'pore_decline' in body['rules']


def test_upload_fasta_and_parse_headers(client):
    fasta = b'>NC_1 Escherichia coli\nACGT\nACGT\n>chr2\nGG\n'
    r = client.post('/upload_fasta', data={'file': (io.BytesIO(fasta), '../../evil.fasta')},
                    content_type='multipart/form-data')
    assert r.status_code == 200
    path = r.json['file_path']
    assert os.path.basename(path) == 'evil.fasta' and '..' not in path
    parsed = client.post('/parse_fasta_headers', json={'file_path': path}).json
    assert parsed['headers'] == ['NC_1', 'chr2']
    assert parsed['records'][0] == {'id': 'NC_1', 'description': 'Escherichia coli', 'length': 8}
    # Paths outside the workspace are refused.
    assert client.post('/parse_fasta_headers', json={'file_path': '/etc/passwd'}).status_code == 400
    r = client.post('/upload_fasta', data={'file': (io.BytesIO(b'x'), 'notes.txt')},
                    content_type='multipart/form-data')
    assert r.status_code == 400


def test_test_notification_requires_channels(client):
    r = client.post('/test_notification', json={'alertNotifConfig': {}, 'desktop': False})
    assert r.status_code == 400


def test_index_devices_returns_list(client):
    r = client.get('/index_devices')
    assert r.status_code == 200 and isinstance(r.json, list)
