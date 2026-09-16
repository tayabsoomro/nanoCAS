"""Classifier plug-in layer: registry, plug-in discovery, report parsers,
and taxonomic classifiers exercised through fake executables."""

import json
import os
import shutil
import stat

import pytest

from app.main.utils.classifiers import (DEFAULT_CLASSIFIER, describe_classifiers, get_classifier,
                                        load_plugins)
from app.main.utils.classifiers.centrifuge import parse_centrifuge_report
from app.main.utils.classifiers.kraken2 import parse_kraken_report

KREPORT = """ 10.00\t100\t100\tU\t0\tunclassified
 90.00\t900\t0\tR\t1\troot
 60.00\t600\t10\tD\t2\t  Bacteria
 50.00\t500\t500\tS\t562\t    Escherichia coli
 30.00\t300\t300\tS\t1280\t    Staphylococcus aureus
"""

CREPORT = """name\ttaxID\ttaxRank\tgenomeSize\tnumReads\tnumUniqueReads\tabundance
Escherichia coli\t562\tspecies\t4600000\t500\t480\t0.6
Staphylococcus aureus\t1280\tspecies\t2800000\t300\t290\t0.4
"""


def test_registry_lists_builtins():
    names = {c['name'] for c in describe_classifiers()}
    assert {'minimap2', 'kraken2', 'centrifuge'} <= names
    assert get_classifier(None).name == DEFAULT_CLASSIFIER
    with pytest.raises(ValueError):
        get_classifier('nope')


def test_minimap2_availability_reports_missing(monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    ok, reason = get_classifier('minimap2').available()
    assert ok is False and 'minimap2' in reason


def test_kraken_report_parser(tmp_path):
    p = tmp_path / 'r.kreport'
    p.write_text(KREPORT)
    by_name, by_taxid, total, unclassified = parse_kraken_report(str(p))
    assert total == 1000 and unclassified == 100
    assert by_name['escherichia coli'] == 500 and by_taxid['562'] == 500
    assert by_name['bacteria'] == 600  # clade count, indentation stripped


def test_centrifuge_report_parser(tmp_path):
    p = tmp_path / 'r.creport'
    p.write_text(CREPORT)
    by_name, by_taxid, classified = parse_centrifuge_report(str(p))
    assert classified == 800 and by_taxid['1280'] == 300 and by_name['escherichia coli'] == 500


def _fake_exe(dirpath, name, body):
    path = dirpath / name
    path.write_text('#!/bin/sh\n' + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_kraken2_classifier_with_fake_executable(tmp_path, monkeypatch):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    # Writes the report to whatever path follows --report.
    _fake_exe(bindir, 'kraken2', '''
while [ $# -gt 0 ]; do case "$1" in --report) shift; REPORT="$1";; --output) shift; OUT="$1";; esac; shift; done
cat > "$REPORT" <<'EOR'
''' + KREPORT + '''EOR
: > "$OUT"
''')
    monkeypatch.setenv('PATH', f"{bindir}:{os.environ['PATH']}")
    db = tmp_path / 'db'
    db.mkdir()
    for f in ('hash.k2d', 'opts.k2d', 'taxo.k2d'):
        (db / f).write_text('x')
    clf = get_classifier('kraken2')
    assert clf.available()[0]
    with pytest.raises(RuntimeError):
        clf.build_index([str(tmp_path / 'notadb')], [], str(tmp_path / 'out'))
    index = clf.build_index([str(db)], ['Escherichia coli'], str(tmp_path / 'out'))
    assert index == str(db)
    reads = tmp_path / 'batch.fastq'
    reads.write_text('@r\nACGT\n+\nIIII\n')
    result = clf.classify(str(reads), index, str(tmp_path / 'work'))
    assert result.bam_path is None
    assert result.total_reads == 1000 and result.unclassified == 100
    assert result.read_counts['escherichia coli'] == 500
    assert result.read_counts['taxid:1280'] == 300
    assert clf.canonical_target('Escherichia coli') == 'escherichia coli'
    assert clf.canonical_target('562') == 'taxid:562'


def test_centrifuge_classifier_with_fake_executable(tmp_path, monkeypatch):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    _fake_exe(bindir, 'centrifuge', '''
while [ $# -gt 0 ]; do case "$1" in --report-file) shift; REPORT="$1";; -S) shift; OUT="$1";; esac; shift; done
cat > "$REPORT" <<'EOR'
''' + CREPORT + '''EOR
: > "$OUT"
''')
    monkeypatch.setenv('PATH', f"{bindir}:{os.environ['PATH']}")
    (tmp_path / 'idx.1.cf').write_text('x')
    clf = get_classifier('centrifuge')
    index = clf.build_index([str(tmp_path / 'idx')], [], str(tmp_path / 'out'))
    reads = tmp_path / 'batch.fastq'
    reads.write_text(''.join('@r%d\nACGT\n+\nIIII\n' % i for i in range(1000)))
    result = clf.classify(str(reads), index, str(tmp_path / 'work'))
    assert result.total_reads == 1000 and result.unclassified == 200
    assert result.read_counts['taxid:562'] == 500


def test_plugin_discovery(tmp_path, monkeypatch):
    plugin_dir = tmp_path / 'plugins'
    plugin_dir.mkdir()
    (plugin_dir / 'my_tool.py').write_text('''
from app.main.utils.classifiers import Classifier, BatchResult

class MyTool(Classifier):
    name = 'mytool'
    label = 'My tool'
    kind = 'taxonomic'
    reference_input = 'database'
    executables = ()

    def build_index(self, references, headers, output_dir, progress=None):
        return references[0]

    def classify(self, input_path, index_path, workdir, *, threads=4):
        return BatchResult(read_counts={'thing': 5}, total_reads=10, unclassified=5)
''')
    (plugin_dir / 'broken.py').write_text('raise RuntimeError("boom")\n')
    (plugin_dir / 'clash.py').write_text('''
from app.main.utils.classifiers import Classifier
class Clash(Classifier):
    name = 'minimap2'
    def build_index(self, *a, **k): return ''
    def classify(self, *a, **k): return None
''')
    monkeypatch.setenv('NANOCAS_PLUGIN_DIR', str(plugin_dir))
    plugins = load_plugins(force=True)
    assert set(plugins) == {'mytool'}  # broken file skipped, clash ignored
    clf = get_classifier('mytool')
    assert clf.describe()['builtin'] is False if 'builtin' in clf.describe() else True
    res = clf.classify('x', 'y', 'z')
    assert res.read_counts == {'thing': 5}
    names = {c['name']: c for c in describe_classifiers()}
    assert names['mytool']['builtin'] is False and names['minimap2']['builtin'] is True
    load_plugins(plugin_dir=str(tmp_path / 'empty'), force=True)


def test_taxonomic_pipeline_end_to_end(tmp_path, monkeypatch):
    """A taxonomic classifier drives read-count / fraction alerts and the
    coverage.csv rows without any BAM."""
    from app.main.utils.FileHandler import FileHandler
    from app.main.utils.alerts import AlertLog
    from app.main.utils.tasks import int_download_database, read_index_manifest

    bindir = tmp_path / 'bin'
    bindir.mkdir()
    _fake_exe(bindir, 'kraken2', '''
while [ $# -gt 0 ]; do case "$1" in --report) shift; REPORT="$1";; --output) shift; OUT="$1";; esac; shift; done
cat > "$REPORT" <<'EOR'
''' + KREPORT + '''EOR
: > "$OUT"
''')
    monkeypatch.setenv('PATH', f"{bindir}:{os.environ['PATH']}")
    db = tmp_path / 'db'
    db.mkdir()
    for f in ('hash.k2d', 'opts.k2d', 'taxo.k2d'):
        (db / f).write_text('x')

    pdir = tmp_path / 'project'
    pdir.mkdir()
    cfg = {
        'projectId': 'tax1', 'fileType': 'FASTQ',
        'classifier': {'name': 'kraken2', 'database': str(db)},
        'queries': [
            {'name': 'E. coli', 'header': 'Escherichia coli', 'headers': ['Escherichia coli'],
             'alert_on_reads': True, 'reads_threshold': '400', 'alert_on_fraction': True, 'fraction_threshold': '40'},
            {'name': 'S. aureus', 'header': '1280', 'headers': ['1280'],
             'alert_on_fraction': True, 'fraction_threshold': '50'},
        ],
        'alertNotifConfig': {},
    }
    (pdir / 'alertinfo.cfg').write_text(json.dumps(cfg))
    result = int_download_database(cfg, str(pdir) + os.sep, cfg['queries'])
    assert isinstance(result, dict) and result['classifier'] == 'kraken2'
    assert read_index_manifest(str(pdir / 'database'))['index_path'] == str(db)

    handler = FileHandler(str(pdir) + os.sep)
    assert handler.classifier.name == 'kraken2' and handler.taxa is not None
    handler.notifier.send = lambda *a, **k: None
    reads = tmp_path / 'b1.fastq'
    reads.write_text('@r\nACGT\n+\nIIII\n')
    assert handler.process_fastq_file(str(reads), '2026-01-01 00:00:00') is True
    rows = [l.split(',') for l in open(pdir / 'coverage.csv').read().splitlines()[1:]]
    by_ref = {r[1]: r for r in rows}
    assert by_ref['escherichia coli'][4] == '500' and float(by_ref['escherichia coli'][5]) == 50.0
    assert by_ref['taxid:1280'][4] == '300'
    assert by_ref['unmapped'][4] == '100'
    types = sorted(a['type'] for a in AlertLog(str(pdir)).read())
    assert types == ['fraction', 'reads']  # E. coli: reads>=400 and fraction>=40; S. aureus 30% < 50
    # Second batch accumulates; no duplicate alerts.
    assert handler.process_fastq_file(str(reads), '2026-01-01 00:05:00') is True
    assert handler.taxa.total_reads == 2000
    assert sorted(a['type'] for a in AlertLog(str(pdir)).read()) == ['fraction', 'reads']
