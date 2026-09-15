"""Incremental sequencing-summary tracker + run-health rules engine."""

import os
import time

import pytest

from app.main.utils.run_health import (DEFAULT_RUN_HEALTH_CONFIG,
                                       RunHealthMonitor, RunHealthRules,
                                       SequencingSummaryTracker,
                                       find_sequencing_summary, infer_flow_cell,
                                       latest_data_file, normalise_config)

HEADER = 'filename\tread_id\trun_id\tchannel\tmux\tstart_time\tduration\tpasses_filtering\tsequence_length_template\tmean_qscore_template\tend_reason\n'


def _row(i, *, channel=1, t=0.0, q=12.0, length=1000, passed=True, reason='signal_positive'):
    return f'f{i}.fastq\tread{i}\trun\t{channel}\t1\t{t}\t1.0\t{"TRUE" if passed else "FALSE"}\t{length}\t{q}\t{reason}\n'


def _write(path, rows, header=True):
    with open(path, 'a') as fh:
        if header:
            fh.write(HEADER)
        fh.writelines(rows)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

def test_tracker_incremental_parse(tmp_path):
    path = tmp_path / 'sequencing_summary.txt'
    _write(path, [_row(i, channel=i % 5 + 1, t=i * 10.0, q=10 + i % 3, length=500 + i) for i in range(20)])
    tr = SequencingSummaryTracker(str(path), window_reads=100)
    assert tr.update() == 20
    assert tr.total_reads == 20
    assert tr.update() == 0  # nothing new
    # Append more rows including a partial trailing line that must be
    # held back until it is complete.
    with open(path, 'a') as fh:
        fh.write(_row(20, t=300.0))
        fh.write('partial\tline')
    assert tr.update() == 1
    with open(path, 'a') as fh:
        fh.write('\tmore\t1\t1\t400\t1\tTRUE\t100\t9.0\tx\n')
    tr.update()
    assert tr.total_reads == 22
    assert tr.parse_errors == 0


def test_tracker_stats_and_snapshot(tmp_path):
    path = tmp_path / 'sequencing_summary.txt'
    rows = [_row(i, channel=(i % 100) + 1, t=i * 1.0, q=7 + (i % 10), length=1000 + 100 * (i % 7),
                 passed=(i % 10) >= 2) for i in range(500)]
    _write(path, rows)
    tr = SequencingSummaryTracker(str(path), window_reads=200)
    tr.update()
    snap = tr.snapshot(q_threshold=7.0, pore_window_min=10)
    assert snap['totals']['reads'] == 500
    assert snap['totals']['has_pass_column'] is True
    assert snap['totals']['pass_reads'] == 400
    assert sum(snap['q_hist']) == 500
    assert sum(snap['len_hist']['counts']) == 500
    assert snap['pores']['flow_cell_type'] == 'Flongle'  # max channel 100 <= 126
    assert snap['pores']['total_channels'] == 126
    assert snap['pores']['channels_seen'] == 100
    w = snap['window']
    assert w['reads'] == 200
    assert 7 <= w['median_q'] <= 16
    assert w['pass_rate'] == 80.0
    assert w['n50'] > 0
    assert snap['median_q_over_time']
    assert snap['throughput'][0]['reads'] > 0
    assert snap['totals']['end_reasons'] == {'signal_positive': 500}


def test_tracker_resets_when_file_shrinks(tmp_path):
    path = tmp_path / 'sequencing_summary.txt'
    _write(path, [_row(i) for i in range(10)])
    tr = SequencingSummaryTracker(str(path))
    tr.update()
    assert tr.total_reads == 10
    path.write_text(HEADER + _row(0))
    tr.update()
    assert tr.total_reads == 1


def test_tracker_csv_and_missing_columns(tmp_path):
    path = tmp_path / 'sequencing_summary.csv'
    path.write_text('read_id,channel,start_time,sequence_length,mean_qscore\n'
                    'r1,5,1.0,800,11.5\nr2,6,2.0,900,8.0\n')
    tr = SequencingSummaryTracker(str(path))
    assert tr.update() == 2
    snap = tr.snapshot(q_threshold=9.0, pore_window_min=10)
    assert snap['totals']['has_pass_column'] is False
    # Without passes_filtering, pass/fail is derived from the Q threshold.
    assert snap['totals']['pass_reads'] == 1
    assert snap['window']['pass_rate'] == 50.0


def test_channels_active_within_uses_run_time(tmp_path):
    path = tmp_path / 'sequencing_summary.txt'
    rows = [_row(i, channel=i + 1, t=float(i * 60)) for i in range(30)]  # one channel per minute
    _write(path, rows)
    tr = SequencingSummaryTracker(str(path))
    tr.update()
    # last_time = 29 min; channels within last 10 min => t >= 19 min => 11 channels
    assert tr.channels_active_within(10) == 11


@pytest.mark.parametrize('max_channel,expected', [
    (0, ('Flongle', 126)), (126, ('Flongle', 126)), (127, ('MinION / GridION', 512)),
    (512, ('MinION / GridION', 512)), (513, ('PromethION', 3000)), (3000, ('PromethION', 3000)),
    (4000, ('Unknown', 4000)),
])
def test_infer_flow_cell(max_channel, expected):
    assert infer_flow_cell(max_channel) == expected


def test_find_summary_prefers_newest_and_bounds_depth(tmp_path):
    old = tmp_path / 'run1' / 'sequencing_summary_a.txt'
    new = tmp_path / 'run2' / 'sequencing_summary_b.txt'
    deep = tmp_path / 'a' / 'b' / 'c' / 'd' / 'e' / 'sequencing_summary_deep.txt'
    for p in (old, new, deep):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(HEADER)
    os.utime(old, (1, 1))
    os.utime(deep, (time.time() + 1000, time.time() + 1000))
    assert find_sequencing_summary([str(tmp_path)], max_depth=3) == str(new)
    assert find_sequencing_summary([str(tmp_path / 'nope')]) is None


def test_latest_data_file_scans_minknow_subdirs(tmp_path):
    (tmp_path / 'fastq_pass').mkdir()
    f1 = tmp_path / 'fastq_pass' / 'a.fastq.gz'
    f2 = tmp_path / 'b.pod5'
    f1.write_text('x')
    f2.write_text('y')
    os.utime(f1, (10, 10))
    os.utime(f2, (20, 20))
    mtime, path, count = latest_data_file(str(tmp_path))
    assert count == 2 and path == str(f2) and mtime == 20
    assert latest_data_file(None) == (None, None, 0)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_normalise_config_coerces_and_guards():
    cfg = normalise_config({'minMedianQ': '8.5', 'checkIntervalSec': '1', 'enabled': 'false',
                            'windowReads': 5, 'bogus': 1})
    assert cfg['minMedianQ'] == 8.5
    assert cfg['checkIntervalSec'] == 5  # floor
    assert cfg['enabled'] is False
    assert cfg['windowReads'] == 50
    assert 'bogus' not in cfg
    assert normalise_config(None) == normalise_config({})
    assert normalise_config(None)['minMedianQ'] == DEFAULT_RUN_HEALTH_CONFIG['minMedianQ']


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _snapshot(**overrides):
    base = {
        'inputs': {'monitor_started': 1000.0, 'data_seen': True, 'last_data_time': 1000.0, 'watch_dir': '/w'},
        'window': {'reads': 500, 'median_q': 12.0, 'pass_rate': 90.0, 'median_length': 2000},
        'pores': {'active_channels': 400, 'total_channels': 512, 'flow_cell_type': 'MinION', 'active_window_min': 10},
        'totals': {'reads': 5000},
        'minknow': None,
    }
    for k, v in overrides.items():
        if isinstance(base.get(k), dict):
            base[k].update(v)
        else:
            base[k] = v
    return base


def _fired_ids(rules, snap, now):
    fired, recovered = rules.evaluate(snap, now)
    return [r.rule_id for r in fired], [r.rule_id for r in recovered]


def test_rule_requires_consecutive_checks_then_recovers():
    rules = RunHealthRules({'consecutiveChecks': 2, 'minMedianQ': 9})
    snap = _snapshot(window={'median_q': 5.0})
    assert _fired_ids(rules, snap, 2000)[0] == []          # first hit: armed only
    assert _fired_ids(rules, snap, 2030)[0] == ['low_median_q']
    assert _fired_ids(rules, snap, 2060)[0] == []          # already active, no re-fire
    ok = _snapshot(window={'median_q': 12.0})
    assert _fired_ids(rules, ok, 2090)[1] == ['low_median_q']  # recovered
    assert _fired_ids(rules, snap, 2120)[0] == []
    assert _fired_ids(rules, snap, 2150)[0] == ['low_median_q']  # can fire again


def test_run_not_started_fires_after_timeout_only_without_data():
    rules = RunHealthRules({'consecutiveChecks': 1, 'runStartTimeoutMin': 15})
    nodata = _snapshot(inputs={'data_seen': False, 'last_data_time': None})
    assert 'run_not_started' not in _fired_ids(rules, nodata, 1000 + 10 * 60)[0]
    assert 'run_not_started' in _fired_ids(rules, nodata, 1000 + 16 * 60)[0]
    # With MinKNOW reporting an acquisition in progress, don't alarm.
    rules2 = RunHealthRules({'consecutiveChecks': 1, 'runStartTimeoutMin': 15})
    processing = _snapshot(inputs={'data_seen': False, 'last_data_time': None},
                           minknow={'acquisition_status': 'PROCESSING'})
    assert 'run_not_started' not in _fired_ids(rules2, processing, 1000 + 60 * 60)[0]


def test_data_stalled():
    rules = RunHealthRules({'consecutiveChecks': 1, 'stallTimeoutMin': 30})
    fresh = _snapshot(inputs={'last_data_time': 5000.0})
    assert 'data_stalled' not in _fired_ids(rules, fresh, 5000 + 10 * 60)[0]
    assert 'data_stalled' in _fired_ids(rules, fresh, 5000 + 31 * 60)[0]


def test_pore_decline_relative_to_peak_and_absolute_floor():
    rules = RunHealthRules({'consecutiveChecks': 1, 'minActivePoresPct': 50, 'minActiveChannelsPct': 10})
    assert _fired_ids(rules, _snapshot(pores={'active_channels': 400}), 1)[0] == []
    assert rules.peak_active_channels == 400
    fired, _ = _fired_ids(rules, _snapshot(pores={'active_channels': 150}), 2)
    assert fired == ['pore_decline']
    fired, _ = _fired_ids(rules, _snapshot(pores={'active_channels': 30}), 3)
    assert fired == ['low_active_channels']  # pore_decline already active


def test_quality_rules_wait_for_enough_reads():
    rules = RunHealthRules({'consecutiveChecks': 1, 'minWindowReads': 200})
    snap = _snapshot(window={'reads': 50, 'median_q': 3.0, 'pass_rate': 1.0})
    fired, _ = _fired_ids(rules, snap, 1)
    assert 'low_median_q' not in fired and 'low_pass_rate' not in fired


def test_short_reads_rule_is_opt_in():
    off = RunHealthRules({'consecutiveChecks': 1})
    assert 'short_reads' not in _fired_ids(off, _snapshot(window={'median_length': 100}), 1)[0]
    on = RunHealthRules({'consecutiveChecks': 1, 'minMedianReadLength': 500})
    assert 'short_reads' in _fired_ids(on, _snapshot(window={'median_length': 100}), 1)[0]


def test_disabled_config_never_fires():
    rules = RunHealthRules({'enabled': False, 'consecutiveChecks': 1})
    snap = _snapshot(window={'median_q': 1.0}, inputs={'data_seen': False, 'last_data_time': None})
    assert rules.evaluate(snap, 10 ** 9) == ([], [])


def test_status_lists_every_rule():
    rules = RunHealthRules({})
    ids = {s['id'] for s in rules.status()}
    assert {'run_not_started', 'data_stalled', 'low_median_q', 'pore_decline',
            'low_active_channels', 'low_pass_rate', 'short_reads'} == ids


# ---------------------------------------------------------------------------
# Monitor (single tick, no thread)
# ---------------------------------------------------------------------------

def test_monitor_tick_records_alert_and_snapshot(tmp_path, monkeypatch):
    from app.main.utils.alerts import AlertLog, Notifier
    minion = tmp_path / 'minion'
    minion.mkdir()
    sent = []
    notifier = Notifier({}, desktop=False)
    monkeypatch.setattr(notifier, 'send', lambda *a, **k: sent.append(a))
    mon = RunHealthMonitor('proj', str(tmp_path), str(minion),
                           {'consecutiveChecks': 1, 'runStartTimeoutMin': 1},
                           alert_log=AlertLog(str(tmp_path)), notifier=notifier)
    mon.started_at = time.time() - 120
    snap = mon.tick()
    assert snap['inputs']['data_seen'] is False
    active = [r['id'] for r in snap['rules'] if r['active']]
    assert active == ['run_not_started']
    assert sent and 'run-health' in sent[0][0]
    logged = AlertLog(str(tmp_path)).read()
    assert logged[0]['type'] == 'run_not_started' and logged[0]['severity'] == 'critical'

    # Data arrives -> recovery is logged.
    (minion / 'batch.fastq').write_text('@r\nACGT\n+\nIIII\n')
    snap = mon.tick()
    assert snap['inputs']['data_seen'] is True
    assert [r for r in snap['rules'] if r['active']] == []
    assert AlertLog(str(tmp_path)).read()[0]['state'] == 'recovered'
    assert mon.snapshot()['inputs']['data_files'] == 1
