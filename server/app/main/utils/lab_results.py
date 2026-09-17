"""Lab results (qPCR Ct values) per project and the statistics that relate
them to what nanopore detected.

A *lab result* is one row: target (reference id or taxon key), sample id,
assay name, Ct (None for a negative), result ('positive' / 'negative' /
'inconclusive'), date, notes. Stored as ``lab_results.json`` in the
project directory.

`correlation()` joins them with the project's latest coverage rows and the
time-to-detection derived from ``coverage.csv``; `cohort()` does the same
across every project and adds positivity rates, concordance with qPCR
and a pooled log10(RPM) vs Ct regression. The RPM-vs-Ct relationship is the
standard way metagenomic read yield is compared with qPCR: each Ct is one
doubling of template, so log10(RPM) is expected to fall linearly with Ct
(slope about -0.30 per cycle at 100 % efficiency).
"""

from __future__ import annotations

import json
import math
import os
import threading
import uuid
from datetime import datetime

from . import project_store
from .stats import (ct_for_expected_reads, linear_regression, log10_rpm, median,
                    poisson_detection_probability, sensitivity_specificity, spearman, wilson_interval)

FILENAME = 'lab_results.json'
RESULT_VALUES = ('positive', 'negative', 'inconclusive')
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _path(project_id: str) -> str:
    return os.path.join(project_store.project_dir(project_id), FILENAME)


def list_results(project_id: str) -> list[dict]:
    path = _path(project_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []


def _save(project_id: str, rows: list[dict]) -> None:
    path = _path(project_id)
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(rows, fh, indent=2)
    os.replace(tmp, path)


def add_result(project_id: str, data: dict) -> dict:
    target = (data.get('target') or '').strip()
    if not target:
        raise ValueError('target is required')
    ct_raw = data.get('ct')
    ct = None
    if ct_raw not in (None, ''):
        try:
            ct = float(ct_raw)
        except (TypeError, ValueError):
            raise ValueError('Ct must be a number')
        if not (0 < ct < 60):
            raise ValueError('Ct must be between 0 and 60')
    result = (data.get('result') or ('positive' if ct is not None else 'negative')).lower()
    if result not in RESULT_VALUES:
        raise ValueError(f'result must be one of {", ".join(RESULT_VALUES)}')
    row = {
        'id': str(uuid.uuid4()),
        'target': target,
        'sample_id': (data.get('sample_id') or '').strip(),
        'assay': (data.get('assay') or 'qPCR').strip(),
        'ct': ct,
        'result': result,
        'date': (data.get('date') or datetime.now().date().isoformat()),
        'notes': (data.get('notes') or '').strip(),
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }
    with _lock:
        rows = list_results(project_id)
        rows.append(row)
        _save(project_id, rows)
    return row


def delete_result(project_id: str, result_id: str) -> bool:
    with _lock:
        rows = list_results(project_id)
        kept = [r for r in rows if r.get('id') != result_id]
        if len(kept) == len(rows):
            return False
        _save(project_id, kept)
    return True


# ---------------------------------------------------------------------------
# Nanopore side: latest metrics + time to detection from coverage.csv
# ---------------------------------------------------------------------------

def read_coverage_rows(project_id: str) -> list[dict]:
    path = os.path.join(project_store.project_dir(project_id), 'coverage.csv')
    rows: list[dict] = []
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            parts = line.strip().split(',')
            if len(parts) < 5 or parts[0] == 'timestamp':
                continue
            try:
                rows.append({
                    'timestamp': parts[0], 'reference': parts[1], 'depth': float(parts[2]),
                    'breadth': float(parts[3]), 'read_count': int(float(parts[4])),
                    'fraction': float(parts[5]) if len(parts) > 5 else None,
                })
            except ValueError:
                continue
    return rows


def _ts(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value.replace(' ', 'T')).timestamp()
    except ValueError:
        return None


def nanopore_metrics(project_id: str, cfg: dict) -> dict[str, dict]:
    """Per configured target: latest reads/fraction/depth/breadth, total
    reads, whether any configured threshold was reached, and minutes from
    the first batch to the first batch at which it was reached."""
    from .FileHandler import _canonical_ref_id
    rows = read_coverage_rows(project_id)
    by_ref: dict[str, list[dict]] = {}
    for r in rows:
        by_ref.setdefault(r['reference'], []).append(r)
    latest_by_ts: dict[str, int] = {}
    for r in rows:
        latest_by_ts[r['timestamp']] = latest_by_ts.get(r['timestamp'], 0) + r['read_count']
    start = min((t for t in (_ts(r['timestamp']) for r in rows) if t), default=None)
    total_reads = 0
    if rows:
        last_ts = rows[-1]['timestamp']
        total_reads = sum(r['read_count'] for r in rows if r['timestamp'] == last_ts)

    out: dict[str, dict] = {}
    classifier_name = (cfg.get('classifier') or {}).get('name', 'minimap2')
    for q in cfg.get('queries', []) or []:
        keys = [q.get('header')] + list(q.get('headers') or [])
        for key in keys:
            if not key:
                continue
            if q.get('key') and key == (q.get('header') or key):
                ref = q['key']
            elif classifier_name in ('kraken2', 'centrifuge'):
                ref = key.strip().lower()
            else:
                ref = _canonical_ref_id(key)
            series = by_ref.get(ref, [])
            latest = series[-1] if series else None
            thresholds = []
            for flag, tkey, metric in (('alert_on_depth', 'depth_threshold', 'depth'),
                                       ('alert_on_breadth', 'breadth_threshold', 'breadth'),
                                       ('alert_on_reads', 'reads_threshold', 'read_count'),
                                       ('alert_on_fraction', 'fraction_threshold', 'fraction')):
                if q.get(flag):
                    try:
                        thresholds.append((metric, float(q.get(tkey) or 0)))
                    except (TypeError, ValueError):
                        pass
            detected_at = None
            for r in series:
                if any((r.get(m) or 0) >= t for m, t in thresholds):
                    detected_at = _ts(r['timestamp'])
                    break
            out[ref] = {
                'reference': ref,
                'name': q.get('name') or ref,
                'reads': latest['read_count'] if latest else 0,
                'fraction': latest['fraction'] if latest and latest['fraction'] is not None else
                            ((latest['read_count'] / total_reads * 100.0) if latest and total_reads else 0.0),
                'depth': latest['depth'] if latest else 0.0,
                'breadth': latest['breadth'] if latest else 0.0,
                'total_reads': total_reads,
                'log10_rpm': log10_rpm(latest['read_count'], total_reads) if latest else None,
                'thresholds': [{'metric': m, 'value': t} for m, t in thresholds],
                'detected': detected_at is not None,
                'time_to_detection_min': ((detected_at - start) / 60.0) if (detected_at and start) else None,
                'batches': len(series),
            }
    return out


# ---------------------------------------------------------------------------
# Project-level correlation
# ---------------------------------------------------------------------------

def correlation(project_id: str) -> dict:
    cfg = project_store.load_config(project_id) or {}
    metrics = nanopore_metrics(project_id, cfg)
    results = list_results(project_id)
    by_target: dict[str, list[dict]] = {}
    for r in results:
        by_target.setdefault(r['target'], []).append(r)

    rows = []
    xs, ys = [], []
    for ref, m in metrics.items():
        labs = by_target.get(ref, [])
        # Use the most recent positive Ct for the scatter (one point per target per project).
        cts = [r['ct'] for r in labs if r.get('ct') is not None]
        ct = cts[-1] if cts else None
        lab_positive = any(r['result'] == 'positive' for r in labs) if labs else None
        row = dict(m)
        row['lab_results'] = labs
        row['ct'] = ct
        row['lab_positive'] = lab_positive
        row['agreement'] = None if lab_positive is None else ('concordant' if lab_positive == m['detected'] else 'discordant')
        rows.append(row)
        if ct is not None and m['log10_rpm'] is not None:
            xs.append(ct)
            ys.append(m['log10_rpm'])
    reg = linear_regression(xs, ys)
    return {
        'projectId': project_id,
        'targets': rows,
        'regression': reg,
        'spearman': spearman(xs, ys),
        'points': [{'ct': x, 'log10_rpm': y} for x, y in zip(xs, ys)],
        'unmatched_results': [r for r in results if r['target'] not in metrics],
    }


# ---------------------------------------------------------------------------
# Cohort: across all projects
# ---------------------------------------------------------------------------

def cohort() -> dict:
    """Summary across every project: per target, how often nanopore and
    qPCR called it positive, their agreement, time-to-detection, and a
    pooled log10(RPM) vs Ct fit with a Ct-based limit of detection."""
    per_target: dict[str, dict] = {}
    runs: list[dict] = []
    for p in project_store.list_projects():
        pid = p['id']
        cfg = project_store.load_config(pid) or {}
        if not cfg:
            continue
        metrics = nanopore_metrics(pid, cfg)
        results = list_results(pid)
        by_target: dict[str, list[dict]] = {}
        for r in results:
            by_target.setdefault(r['target'], []).append(r)
        for ref, m in metrics.items():
            labs = by_target.get(ref, [])
            cts = [r['ct'] for r in labs if r.get('ct') is not None]
            ct = cts[-1] if cts else None
            lab_positive = any(r['result'] == 'positive' for r in labs) if labs else None
            # Group by reference id (case-insensitive) so the same sequence
            # labelled differently in two projects lands in one row.
            key = ref.lower()
            entry = per_target.setdefault(key, {
                'name': m['name'], 'names': {}, 'references': set(), 'runs': 0, 'nanopore_positive': 0,
                'lab_tested': 0, 'lab_positive': 0, 'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0,
                'ttd': [], 'points': [], 'demo_runs': 0,
            })
            entry['references'].add(ref)
            entry['names'][m['name']] = entry['names'].get(m['name'], 0) + 1
            entry['runs'] += 1
            entry['nanopore_positive'] += int(m['detected'])
            entry['demo_runs'] += int(bool(cfg.get('demo')))
            if m['time_to_detection_min'] is not None:
                entry['ttd'].append(m['time_to_detection_min'])
            if lab_positive is not None:
                entry['lab_tested'] += 1
                entry['lab_positive'] += int(lab_positive)
                if lab_positive and m['detected']:
                    entry['tp'] += 1
                elif lab_positive and not m['detected']:
                    entry['fn'] += 1
                elif not lab_positive and m['detected']:
                    entry['fp'] += 1
                else:
                    entry['tn'] += 1
            if ct is not None and m['log10_rpm'] is not None:
                entry['points'].append({'ct': ct, 'log10_rpm': m['log10_rpm'], 'project': p.get('name') or pid,
                                        'reads': m['reads'], 'total_reads': m['total_reads']})
            runs.append({
                'projectId': pid, 'project': p.get('name') or pid[:8], 'demo': bool(cfg.get('demo')),
                'created_at': cfg.get('createdAt'), 'target': key, 'reference': ref,
                'detected': m['detected'], 'reads': m['reads'], 'fraction': m['fraction'],
                'time_to_detection_min': m['time_to_detection_min'], 'ct': ct, 'lab_positive': lab_positive,
            })

    targets = []
    for entry in per_target.values():
        # Most frequently used label wins.
        entry['name'] = max(entry['names'].items(), key=lambda kv: kv[1])[0]
        pos, lo, hi = wilson_interval(entry['nanopore_positive'], entry['runs'])
        lab_pos, lab_lo, lab_hi = wilson_interval(entry['lab_positive'], entry['lab_tested']) if entry['lab_tested'] else (None, None, None)
        agreement = sensitivity_specificity(entry['tp'], entry['fp'], entry['fn'], entry['tn']) if entry['lab_tested'] else None
        pts = entry['points']
        reg = linear_regression([q['ct'] for q in pts], [q['log10_rpm'] for q in pts])
        lod_ct = None
        if reg and pts:
            # Ct at which the fit predicts 3 reads in a run of the median size:
            # P(>=1 read | Poisson(3)) = 95 %, the usual LoD convention.
            med_total = median([q['total_reads'] for q in pts]) or 0
            if med_total > 0:
                target_log_rpm = math.log10(3 / med_total * 1e6)
                lod_ct = ct_for_expected_reads(reg, target_log_rpm)
        targets.append({
            'key': next(iter(entry['references'])).lower(), 'name': entry['name'],
            'references': sorted(entry['references']), 'runs': entry['runs'],
            'demo_runs': entry['demo_runs'],
            'nanopore_positive': entry['nanopore_positive'],
            'positivity': pos if not math.isnan(pos) else None, 'positivity_ci': [lo, hi] if not math.isnan(lo) else None,
            'lab_tested': entry['lab_tested'], 'lab_positive': entry['lab_positive'],
            'lab_positivity': lab_pos, 'lab_positivity_ci': [lab_lo, lab_hi] if lab_lo is not None else None,
            'agreement': agreement,
            'median_time_to_detection_min': median(entry['ttd']),
            'regression': reg, 'points': pts, 'lod_ct': lod_ct,
            'detection_probability_at_3_reads': poisson_detection_probability(3, 1),
        })
    targets.sort(key=lambda t: (-t['runs'], t['name']))
    return {'targets': targets, 'runs': sorted(runs, key=lambda r: r.get('created_at') or '', reverse=True),
            'projects': len({r['projectId'] for r in runs})}
