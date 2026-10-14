"""GFF feature alerts, lab results and the statistics/cohort endpoints."""

import json
import os

import pytest

from app.main.utils import lab_results as lab
from app.main.utils.gff import parse_gff_features, regions_from_selection
from app.main.utils.stats import (cohens_kappa, linear_regression, poisson_detection_probability,
                                  sensitivity_specificity, spearman, t_two_sided_p, wilson_interval)

GFF = """##gff-version 3
chr1\t.\tgene\t100\t500\t.\t+\t.\tID=gene1;Name=abcA;product=ABC transporter
chr1\t.\tCDS\t100\t500\t.\t+\t0\tID=cds1;Parent=gene1
chr1\t.\tgene\t900\t1200\t.\t-\t.\tID=gene2;Name=xyzB
chr2\t.\tgene\t10\t50\t.\t+\t.\tlocus_tag=LT_0001
bad line
##FASTA
>chr1
ACGT
"""


def test_parse_gff_features(tmp_path):
    p = tmp_path / 'a.gff3'
    p.write_text(GFF)
    parsed = parse_gff_features(str(p))
    assert parsed['seqids'] == ['chr1', 'chr2']
    assert parsed['types'] == {'gene': 3, 'CDS': 1}
    assert parsed['features'][0]['id'] == 'gene1' and parsed['features'][0]['product'] == 'ABC transporter'
    assert parsed['features'][3]['id'] == 'LT_0001'
    only = parse_gff_features(str(p), seqids={'chr2'})
    assert [f['seqid'] for f in only['features']] == ['chr2']
    limited = parse_gff_features(str(p), limit=1)
    assert limited['truncated'] is True and len(limited['features']) == 1


def test_regions_from_selection():
    regions = regions_from_selection([
        {'seqid': 'chr1', 'id': 'gene1', 'start': 500, 'end': 100, 'threshold': '4'},
        {'seqid': 'chr1', 'start': 900, 'end': 1200, 'alert_enabled': False},
        {'seqid': 'x', 'start': 'bad', 'end': 2},
    ], default_threshold=2)
    assert regions['chr1'][0] == {'id': 'gene1', 'name': '', 'type': '', 'start': 100, 'end': 500,
                                  'alert_enabled': True, 'threshold': 4.0}
    assert regions['chr1'][1]['alert_enabled'] is False and regions['chr1'][1]['threshold'] == 2.0
    assert 'x' not in regions


def test_region_routes(client, project, tmp_path):
    pid, pdir = project
    gff = tmp_path / 'f.gff'
    gff.write_text(GFF)
    assert client.post('/parse_gff', json={'file_path': str(gff)}).status_code == 400  # outside workspace
    from app.main.utils import project_store
    inside = os.path.join(project_store.NANOCAS_DIR, 'upload_test.gff')
    with open(inside, 'w') as fh:
        fh.write(GFF)
    parsed = client.post('/parse_gff', json={'file_path': inside}).json
    assert parsed['types']['gene'] == 3
    r = client.post('/update_regions', json={'projectId': pid, 'selection': parsed['features'][:2]})
    assert r.json['count'] == 2
    regions = client.get(f'/get_regions?projectId={pid}').json['regions']
    assert regions['chr1'][0]['id'] == 'gene1'
    assert os.path.exists(os.path.join(pdir, 'regions.json'))
    # Layout form with edits round-trips.
    regions['chr1'][0]['threshold'] = 9
    regions['chr1'][0]['alert_enabled'] = False
    r = client.post('/update_regions', json={'projectId': pid, 'regions': regions})
    assert r.json['regions']['chr1'][0]['threshold'] == 9.0 and r.json['regions']['chr1'][0]['alert_enabled'] is False
    os.remove(inside)


def test_filehandler_reloads_regions(project, monkeypatch):
    from app.main.utils.FileHandler import FileHandler
    pid, pdir = project
    h = FileHandler(pdir + os.sep)
    assert h.regions_data == {}
    with open(os.path.join(pdir, 'regions.json'), 'w') as fh:
        json.dump({'chr1': [{'id': 'g', 'start': 1, 'end': 10, 'alert_enabled': True, 'threshold': 1}]}, fh)
    os.utime(os.path.join(pdir, 'regions.json'), (1, 1))  # ensure a different mtime
    h._reload_regions()
    assert 'chr1' in h.regions_data


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def test_wilson_interval():
    p, lo, hi = wilson_interval(0, 10)
    assert p == 0 and lo == 0 and 0 < hi < 0.35
    p, lo, hi = wilson_interval(10, 10)
    assert p == 1 and hi == 1 and 0.65 < lo < 1
    assert all(map(lambda v: v != v, wilson_interval(0, 0)))  # nan


def test_regression_and_p_value():
    reg = linear_regression([20, 24, 28, 32, 36], [4.0, 2.9, 1.7, 0.6, -0.5])
    assert reg['n'] == 5 and reg['slope'] == pytest.approx(-0.2825, abs=0.01)
    assert reg['r'] < -0.99 and reg['p'] < 0.001
    assert linear_regression([1, 1, 1], [1, 2, 3]) is None
    assert linear_regression([1, 2], [1, 2]) is None
    assert abs(t_two_sided_p(0.0, 10) - 1.0) < 1e-9
    assert t_two_sided_p(2.228, 10) == pytest.approx(0.05, abs=0.002)


def test_spearman_kappa_poisson():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert cohens_kappa(10, 0, 0, 10) == 1.0
    assert cohens_kappa(5, 5, 5, 5) == 0.0
    assert poisson_detection_probability(3) == pytest.approx(0.9502, abs=1e-3)
    assert poisson_detection_probability(0) == 0.0
    ss = sensitivity_specificity(8, 1, 2, 9)
    assert ss['sensitivity'] == pytest.approx(0.8) and ss['specificity'] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Lab results + correlation + cohort
# ---------------------------------------------------------------------------

def _coverage(pdir, rows):
    with open(os.path.join(pdir, 'coverage.csv'), 'w') as fh:
        fh.write('timestamp,reference,depth,breadth,read_count,fraction\n')
        for r in rows:
            fh.write(','.join(map(str, r)) + '\n')


def test_lab_results_crud_and_correlation(client, project):
    pid, pdir = project
    _coverage(pdir, [
        ('2026-01-01 00:00:00', 'chr1', 0.5, 10, 50, 5), ('2026-01-01 00:00:00', 'unmapped', 0, 0, 950, 95),
        ('2026-01-01 00:10:00', 'chr1', 3.0, 60, 300, 15), ('2026-01-01 00:10:00', 'unmapped', 0, 0, 1700, 85),
    ])
    assert client.post('/lab_results', json={'projectId': pid, 'target': 'chr1', 'ct': 'abc'}).status_code == 400
    assert client.post('/lab_results', json={'projectId': pid, 'ct': 20}).status_code == 400
    r = client.post('/lab_results', json={'projectId': pid, 'target': 'chr1', 'ct': 24.5, 'sample_id': 'S1'})
    assert r.status_code == 200 and r.json['result']['result'] == 'positive'
    rid = r.json['result']['id']
    r = client.post('/lab_results', json={'projectId': pid, 'target': 'other', 'result': 'negative'})
    assert r.json['result']['ct'] is None
    assert len(client.get(f'/lab_results?projectId={pid}').json['results']) == 2

    corr = client.get(f'/lab_correlation?projectId={pid}').json
    t = corr['targets'][0]
    assert t['reference'] == 'chr1' and t['reads'] == 300 and t['detected'] is True
    assert t['time_to_detection_min'] == pytest.approx(10.0)  # depth 3 >= threshold 2 at the second batch
    assert t['ct'] == 24.5 and t['lab_positive'] is True and t['agreement'] == 'concordant'
    assert corr['regression'] is None  # one point only
    assert len(corr['unmatched_results']) == 1

    assert client.delete('/lab_results', json={'projectId': pid, 'id': rid}).json['deleted'] is True
    assert client.delete('/lab_results', json={'projectId': pid, 'id': rid}).json['deleted'] is False


def test_cohort_across_projects(client):
    from app.main.utils import project_store
    pids = []
    try:
        for i, (reads, ct) in enumerate([(400, 22.0), (100, 26.0), (20, 30.0), (0, None)]):
            pid = project_store.new_project_id()
            pdir = project_store.project_dir(pid)
            os.makedirs(pdir)
            project_store.save_config(pid, {
                'projectId': pid, 'projectName': f'run{i}', 'fileType': 'FASTQ', 'minion': '/x',
                'queries': [{'name': 'Target', 'header': 'tgt', 'alert_on_reads': True, 'reads_threshold': '10'}],
                'createdAt': f'2026-01-0{i + 1}T00:00:00',
            })
            project_store.append_cache(pid, '/x', pdir)
            _coverage(pdir, [('2026-01-01 00:00:00', 'tgt', 0, 0, reads, 0), ('2026-01-01 00:00:00', 'unmapped', 0, 0, 10000 - reads, 0)])
            if ct is not None:
                lab.add_result(pid, {'target': 'tgt', 'ct': ct})
            else:
                lab.add_result(pid, {'target': 'tgt', 'result': 'negative'})
            pids.append(pid)
        body = client.get('/cohort').json
        t = next(x for x in body['targets'] if x['name'] == 'Target')
        assert t['runs'] == 4 and t['nanopore_positive'] == 3
        assert t['positivity'] == pytest.approx(0.75) and t['positivity_ci'][0] < 0.75 < t['positivity_ci'][1]
        assert t['lab_tested'] == 4 and t['lab_positive'] == 3
        assert t['agreement']['tp'] == 3 and t['agreement']['tn'] == 1 and t['agreement']['kappa'] == 1.0
        assert t['regression']['n'] == 3 and t['regression']['slope'] < 0
        assert t['lod_ct'] is not None and t['lod_ct'] > 30
        assert body['projects'] == 4
    finally:
        for pid in pids:
            project_store.delete_project(pid)
