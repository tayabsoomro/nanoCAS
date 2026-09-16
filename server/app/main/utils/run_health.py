"""Run-health monitoring: live sequencing QC + instrument-level alerting.

Three cooperating pieces:

:class:`SequencingSummaryTracker`
    Incrementally tails MinKNOW's ``sequencing_summary.txt`` (or the CSV
    variant). Each call to :meth:`update` reads only the bytes appended
    since the previous call, so a multi-gigabyte summary from a 72 h run
    costs O(new rows) per poll instead of a full re-parse. Aggregates are
    kept as histograms and per-minute buckets rather than raw lists so
    memory stays flat for the life of a run.

:class:`RunHealthRules`
    A small rules engine with hysteresis. Each rule is evaluated against
    the latest snapshot; a rule *fires* once its condition has held for
    ``consecutiveChecks`` evaluations and *recovers* as soon as it
    stops holding, after which it may fire again. Rules cover the
    "instrument" failure modes nanoCAS cares about: run never started,
    data production stalled, read quality collapsed, pores dying, low
    pass rate, short reads, and a flow cell that is bad from the start.

:class:`RunHealthMonitor`
    A daemon thread (one per monitored project) that ties the two
    together: locates the summary file, tails it, watches the output
    directory for new data files, optionally asks MinKNOW for the live
    acquisition state, evaluates the rules, records alerts and pushes a
    ``run_health_update`` socket event.
"""

from __future__ import annotations

import bisect
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from .alerts import (SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING,
                     SOURCE_RUN_HEALTH, AlertLog, Notifier, emit_alert, safe_emit)
from .constants import DATA_EXTENSIONS, MINKNOW_SUBDIRS

logger = logging.getLogger('nanocas')

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_RUN_HEALTH_CONFIG: dict = {
    'enabled': True,
    # Minutes after "Start Monitoring" with no data at all before the
    # "run not started" alert fires.
    'runStartTimeoutMin': 15,
    # Minutes without any new data file / summary rows before "stalled".
    'stallTimeoutMin': 30,
    # Rolling-window read-quality floor (median mean_qscore).
    'minMedianQ': 9.0,
    # Per-read pass/fail cut-off. Used for the histogram colouring and for
    # pass-rate when the summary has no `passes_filtering` column.
    # MinKNOW HAC default is Q7 (older chemistries) / Q9 (R10.4 kits);
    # SUP models tend to use Q10.
    'qScoreThreshold': 7.0,
    # Minimum fraction (%) of reads in the window that pass.
    'minPassRate': 50.0,
    # Fire when the number of channels that produced a read in the last
    # `poreWindowMin` minutes drops below this % of the run's peak.
    'minActivePoresPct': 50.0,
    # Fire when fewer than this % of the flow cell's channels have
    # produced a read recently (catches a flow cell that is bad from the
    # very start, where "peak" is meaningless).
    'minActiveChannelsPct': 10.0,
    # Median read length floor (bp); 0 disables.
    'minMedianReadLength': 0,
    # Rolling window size in reads for Q / length / pass-rate stats.
    'windowReads': 2000,
    # Time window (run minutes) for the "active channel" count.
    'poreWindowMin': 10,
    # Minimum reads in the window before quality rules are evaluated.
    'minWindowReads': 200,
    # How many consecutive evaluations a condition must hold before the
    # rule fires (suppresses single-poll flicker).
    'consecutiveChecks': 2,
    # Seconds between monitor evaluations.
    'checkIntervalSec': 30,
}

_NUMERIC_KEYS = {k for k, v in DEFAULT_RUN_HEALTH_CONFIG.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def normalise_config(raw: dict | None) -> dict:
    """Merge a (possibly partial / stringly-typed) config dict from
    ``alertinfo.cfg`` with the defaults, coercing numbers."""
    cfg = dict(DEFAULT_RUN_HEALTH_CONFIG)
    for key, value in (raw or {}).items():
        if key not in cfg:
            continue
        if key in _NUMERIC_KEYS:
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            cfg[key] = int(num) if isinstance(DEFAULT_RUN_HEALTH_CONFIG[key], int) else num
        elif isinstance(DEFAULT_RUN_HEALTH_CONFIG[key], bool):
            cfg[key] = bool(value) if not isinstance(value, str) else value.lower() in ('1', 'true', 'yes', 'on')
    # Guard rails so a bad config can't produce a busy loop or a zero window.
    cfg['checkIntervalSec'] = max(5, cfg['checkIntervalSec'])
    cfg['windowReads'] = max(50, cfg['windowReads'])
    cfg['minWindowReads'] = max(10, min(cfg['minWindowReads'], cfg['windowReads']))
    cfg['consecutiveChecks'] = max(1, cfg['consecutiveChecks'])
    cfg['poreWindowMin'] = max(1, cfg['poreWindowMin'])
    return cfg


# ---------------------------------------------------------------------------
# Flow-cell geometry
# ---------------------------------------------------------------------------

FLOW_CELL_TYPES = (
    # (max channel number, label, channel count)
    (126, 'Flongle', 126),
    (512, 'MinION / GridION', 512),
    (3000, 'PromethION', 3000),
)


def infer_flow_cell(max_channel: int) -> tuple[str, int]:
    """Guess the flow-cell family from the highest channel number seen.

    Replaces the hard-coded ``max(len(channels), 512)`` which was wrong for
    Flongle (126 channels) and PromethION (3000 channels per cell).
    """
    for limit, label, channels in FLOW_CELL_TYPES:
        if max_channel <= limit:
            return label, channels
    return 'Unknown', max_channel


# ---------------------------------------------------------------------------
# Incremental sequencing_summary parser
# ---------------------------------------------------------------------------

Q_BIN_COUNT = 61          # floor(Q) bins 0..60
Q_FINE_RES = 0.5          # resolution of the per-bucket histograms used for medians
Q_FINE_BINS = int(60 / Q_FINE_RES) + 1
LENGTH_EDGES = (0, 250, 500, 1000, 2000, 3000, 4000, 5000, 7500, 10000,
                15000, 20000, 30000, 50000, 100000)

_Q_COLUMNS = ('mean_qscore_template', 'mean_qscore', 'quality_score')
_LEN_COLUMNS = ('sequence_length_template', 'sequence_length', 'read_length')
_TIME_COLUMNS = ('start_time', 'template_start')
_PASS_COLUMNS = ('passes_filtering',)
_END_REASON_COLUMNS = ('end_reason',)
_CHANNEL_COLUMNS = ('channel',)

_MAX_SERIES_POINTS = 600


@dataclass
class _Bucket:
    reads: int = 0
    bases: int = 0
    passed: int = 0
    q_hist: list = field(default_factory=lambda: [0] * Q_FINE_BINS)


def _median_from_hist(hist: list[int], resolution: float) -> float | None:
    total = sum(hist)
    if total == 0:
        return None
    half = total / 2.0
    running = 0
    for i, n in enumerate(hist):
        running += n
        if running >= half:
            return round(i * resolution, 2)
    return None


def _median(values: list) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _n50(lengths: list[int]) -> int:
    if not lengths:
        return 0
    s = sorted(lengths, reverse=True)
    total = sum(s)
    running = 0
    for length in s:
        running += length
        if running >= total / 2:
            return int(length)
    return 0


class SequencingSummaryTracker:
    """Tail a ``sequencing_summary`` file and keep streaming statistics.

    ``update()`` is safe to call as often as you like; it returns the
    number of new rows consumed. A file that shrinks (rotated / replaced
    by MinKNOW for a new run) resets the tracker automatically.
    """

    def __init__(self, path: str, *, window_reads: int = 2000, bucket_seconds: int = 60):
        self.path = path
        self.window_reads = max(50, int(window_reads))
        self.bucket_seconds = max(1, int(bucket_seconds))
        self._lock = threading.Lock()
        self.reset()

    # -- state ---------------------------------------------------------

    def reset(self) -> None:
        self._offset = 0
        self._delimiter = '\t'
        self._columns: dict[str, int] | None = None
        self._col_q = self._col_len = self._col_time = self._col_pass = None
        self._col_channel = self._col_end = None
        self.total_reads = 0
        self.total_bases = 0
        self.pass_reads = 0
        self.fail_reads = 0
        self.has_pass_column = False
        self.q_sum = 0.0
        self.q_hist = [0] * Q_BIN_COUNT
        self.len_hist = [0] * len(LENGTH_EDGES)
        self.max_channel = 0
        self.channel_last_time: dict[int, float] = {}
        self.first_time: float | None = None
        self.last_time: float | None = None
        self.buckets: dict[int, _Bucket] = {}
        self.end_reasons: dict[str, int] = {}
        self.window: deque = deque(maxlen=self.window_reads)
        self.parse_errors = 0
        self.file_size = 0
        self.file_mtime = 0.0

    # -- parsing -------------------------------------------------------

    def update(self) -> int:
        with self._lock:
            return self._update_locked()

    def _update_locked(self) -> int:
        if not self.path or not os.path.exists(self.path):
            return 0
        try:
            st = os.stat(self.path)
        except OSError:
            return 0
        if st.st_size < self._offset:
            logger.info(f'{self.path} shrank; assuming a new run and resetting run-health stats')
            self.reset()
        if st.st_size == self._offset:
            self.file_size, self.file_mtime = st.st_size, st.st_mtime
            return 0

        new_rows = 0
        with open(self.path, 'rb') as fh:
            fh.seek(self._offset)
            data = fh.read()
        # Only consume complete lines; MinKNOW appends rows as it goes and
        # we may catch it mid-write.
        cut = data.rfind(b'\n')
        if cut < 0:
            return 0
        chunk = data[:cut + 1]
        self._offset += len(chunk)
        self.file_size, self.file_mtime = st.st_size, st.st_mtime

        for raw in chunk.decode('utf-8', errors='replace').splitlines():
            if not raw:
                continue
            if self._columns is None:
                self._parse_header(raw)
                continue
            if self._ingest_row(raw):
                new_rows += 1
        return new_rows

    def _parse_header(self, line: str) -> None:
        self._delimiter = '\t' if '\t' in line else ','
        names = [c.strip() for c in line.split(self._delimiter)]
        self._columns = {name: i for i, name in enumerate(names)}

        def pick(candidates):
            for c in candidates:
                if c in self._columns:
                    return self._columns[c]
            return None

        self._col_q = pick(_Q_COLUMNS)
        self._col_len = pick(_LEN_COLUMNS)
        self._col_time = pick(_TIME_COLUMNS)
        self._col_pass = pick(_PASS_COLUMNS)
        self._col_channel = pick(_CHANNEL_COLUMNS)
        self._col_end = pick(_END_REASON_COLUMNS)
        self.has_pass_column = self._col_pass is not None

    def _ingest_row(self, line: str) -> bool:
        parts = line.split(self._delimiter)
        try:
            q = float(parts[self._col_q]) if self._col_q is not None else None
            length = int(float(parts[self._col_len])) if self._col_len is not None else None
            t = float(parts[self._col_time]) if self._col_time is not None else None
            channel = int(parts[self._col_channel]) if self._col_channel is not None else None
        except (IndexError, ValueError):
            self.parse_errors += 1
            return False

        passed: bool | None = None
        if self._col_pass is not None and self._col_pass < len(parts):
            passed = parts[self._col_pass].strip().upper() in ('TRUE', '1', 'PASS', 'T')

        self.total_reads += 1
        if length is not None:
            self.total_bases += length
            self.len_hist[bisect.bisect_right(LENGTH_EDGES, length) - 1] += 1
        if q is not None:
            self.q_sum += q
            self.q_hist[min(max(int(q), 0), Q_BIN_COUNT - 1)] += 1
        if passed is True:
            self.pass_reads += 1
        elif passed is False:
            self.fail_reads += 1
        if channel is not None:
            self.max_channel = max(self.max_channel, channel)
            if t is not None:
                prev = self.channel_last_time.get(channel)
                if prev is None or t > prev:
                    self.channel_last_time[channel] = t
            else:
                self.channel_last_time.setdefault(channel, 0.0)
        if t is not None:
            self.first_time = t if self.first_time is None else min(self.first_time, t)
            self.last_time = t if self.last_time is None else max(self.last_time, t)
            bucket = self.buckets.setdefault(int(t // self.bucket_seconds), _Bucket())
            bucket.reads += 1
            bucket.bases += length or 0
            if passed:
                bucket.passed += 1
            if q is not None:
                bucket.q_hist[min(max(int(q / Q_FINE_RES), 0), Q_FINE_BINS - 1)] += 1
        if self._col_end is not None and self._col_end < len(parts):
            reason = parts[self._col_end].strip() or 'unknown'
            self.end_reasons[reason] = self.end_reasons.get(reason, 0) + 1

        self.window.append((t, q, length, channel, passed))
        return True

    # -- derived statistics -------------------------------------------

    def window_stats(self, q_threshold: float) -> dict:
        """Statistics over the most recent ``windowReads`` reads."""
        with self._lock:
            rows = list(self.window)
        qs = [r[1] for r in rows if r[1] is not None]
        lens = [r[2] for r in rows if r[2] is not None]
        channels = {r[3] for r in rows if r[3] is not None}
        times = [r[0] for r in rows if r[0] is not None]
        if self.has_pass_column:
            passed = [r[4] for r in rows if r[4] is not None]
            pass_rate = (sum(1 for p in passed if p) / len(passed) * 100.0) if passed else None
        else:
            pass_rate = (sum(1 for q in qs if q >= q_threshold) / len(qs) * 100.0) if qs else None
        return {
            'reads': len(rows),
            'median_q': _median(qs),
            'mean_q': (sum(qs) / len(qs)) if qs else None,
            'median_length': _median(lens),
            'n50': _n50(lens),
            'pass_rate': round(pass_rate, 1) if pass_rate is not None else None,
            'active_channels': len(channels),
            'span_seconds': (max(times) - min(times)) if len(times) > 1 else 0.0,
        }

    def channels_active_within(self, minutes: float) -> int:
        """Channels that produced a read within the last ``minutes`` of
        *run time* (i.e. relative to the newest ``start_time`` seen)."""
        with self._lock:
            if self.last_time is None:
                return 0
            cutoff = self.last_time - minutes * 60.0
            return sum(1 for t in self.channel_last_time.values() if t >= cutoff)

    def _series(self) -> tuple[list[dict], list[dict]]:
        keys = sorted(self.buckets)
        if not keys:
            return [], []
        # Coarsen to keep the payload bounded for very long runs.
        group = max(1, (len(keys) + _MAX_SERIES_POINTS - 1) // _MAX_SERIES_POINTS)
        median_series: list[dict] = []
        throughput: list[dict] = []
        for i in range(0, len(keys), group):
            chunk = keys[i:i + group]
            reads = sum(self.buckets[k].reads for k in chunk)
            bases = sum(self.buckets[k].bases for k in chunk)
            passed = sum(self.buckets[k].passed for k in chunk)
            hist = [0] * Q_FINE_BINS
            for k in chunk:
                bh = self.buckets[k].q_hist
                for j, n in enumerate(bh):
                    if n:
                        hist[j] += n
            t = chunk[0] * self.bucket_seconds
            med = _median_from_hist(hist, Q_FINE_RES)
            median_series.append({'time': t, 'median_q': med, 'reads': reads})
            throughput.append({'time': t, 'reads': reads, 'bases': bases, 'passed': passed,
                               'seconds': len(chunk) * self.bucket_seconds})
        return median_series, throughput

    def snapshot(self, q_threshold: float = 7.0, pore_window_min: float = 10) -> dict:
        with self._lock:
            median_series, throughput = self._series()
            flow_cell_label, flow_cell_channels = infer_flow_cell(self.max_channel)
            total_reads = self.total_reads
            summary = {
                'path': self.path,
                'size': self.file_size,
                'mtime': self.file_mtime,
                'parse_errors': self.parse_errors,
            }
            totals = {
                'reads': total_reads,
                'bases': self.total_bases,
                'mean_q': round(self.q_sum / total_reads, 2) if total_reads else None,
                'pass_reads': self.pass_reads if self.has_pass_column else sum(self.q_hist[int(q_threshold):]),
                'fail_reads': self.fail_reads if self.has_pass_column else sum(self.q_hist[:int(q_threshold)]),
                'has_pass_column': self.has_pass_column,
                'run_elapsed_seconds': self.last_time,
                'first_read_time': self.first_time,
                'end_reasons': dict(self.end_reasons),
            }
            q_hist = list(self.q_hist)
            len_hist = {'edges': list(LENGTH_EDGES), 'counts': list(self.len_hist)}
            channels_seen = len(self.channel_last_time)
        active_recent = self.channels_active_within(pore_window_min)
        window = self.window_stats(q_threshold)
        pores = {
            'flow_cell_type': flow_cell_label,
            'total_channels': flow_cell_channels,
            'channels_seen': channels_seen,
            'active_channels': active_recent,
            'active_window_min': pore_window_min,
            'occupancy_rate': round(active_recent / flow_cell_channels * 100.0, 1) if flow_cell_channels else 0.0,
            'channel_states': {
                'sequencing': active_recent,
                'unavailable': max(flow_cell_channels - active_recent, 0),
                'other': 0,
            },
        }
        return {
            'summary_file': summary,
            'totals': totals,
            'q_hist': q_hist,
            'len_hist': len_hist,
            'median_q_over_time': median_series,
            'throughput': throughput,
            'window': window,
            'pores': pores,
            'q_threshold': q_threshold,
            # Backwards-compatible aliases used by the previous frontend.
            'total_reads': total_reads,
            'pore_health': pores,
        }


# ---------------------------------------------------------------------------
# Locating inputs
# ---------------------------------------------------------------------------

def find_sequencing_summary(directories: list[str], max_depth: int = 3) -> str | None:
    """Newest ``sequencing_summary*.{txt,csv}`` under any of ``directories``
    (bounded-depth walk, so pointing at ``/data`` doesn't crawl the disk)."""
    best: tuple[float, str] | None = None
    seen: set[str] = set()
    for base in directories:
        if not base or not os.path.isdir(base):
            continue
        base = os.path.realpath(base)
        if base in seen:
            continue
        seen.add(base)
        base_depth = base.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(base):
            if root.count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
            for fname in files:
                lower = fname.lower()
                if 'sequencing_summary' in lower and (lower.endswith('.txt') or lower.endswith('.csv')):
                    path = os.path.join(root, fname)
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        continue
                    if best is None or mtime > best[0]:
                        best = (mtime, path)
    return best[1] if best else None


def summary_search_dirs(project_dir: str, minion_dir: str | None) -> list[str]:
    dirs = [project_dir]
    if minion_dir and os.path.isdir(minion_dir):
        dirs.append(minion_dir)
        parent = os.path.dirname(minion_dir.rstrip(os.sep))
        if parent and os.path.isdir(parent):
            dirs.append(parent)
    return dirs


def latest_data_file(minion_dir: str | None) -> tuple[float | None, str | None, int]:
    """Newest data file (by mtime) directly in ``minion_dir`` or in the
    usual MinKNOW sub-directories. Returns ``(mtime, path, count)``."""
    if not minion_dir or not os.path.isdir(minion_dir):
        return None, None, 0
    candidates = [minion_dir] + [os.path.join(minion_dir, d) for d in MINKNOW_SUBDIRS]
    newest: tuple[float, str] | None = None
    count = 0
    for d in candidates:
        if not os.path.isdir(d):
            continue
        try:
            with os.scandir(d) as it:
                for entry in it:
                    if not entry.is_file() or not entry.name.lower().endswith(DATA_EXTENSIONS):
                        continue
                    count += 1
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    if newest is None or mtime > newest[0]:
                        newest = (mtime, entry.path)
        except OSError:
            continue
    if newest is None:
        return None, None, count
    return newest[0], newest[1], count


# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------

@dataclass
class RuleResult:
    rule_id: str
    active: bool
    severity: str
    message: str
    details: dict = field(default_factory=dict)


RULE_DESCRIPTIONS: dict[str, str] = {
    'run_not_started': 'No sequencing data has appeared since monitoring started',
    'data_stalled': 'The sequencer has stopped producing new data',
    'low_median_q': 'Median read quality in the recent window is below the floor',
    'pore_decline': 'Active channel count has dropped sharply from its peak',
    'low_active_channels': 'Very few flow-cell channels are producing reads',
    'low_pass_rate': 'Too few recent reads pass the quality filter',
    'short_reads': 'Recent reads are shorter than expected',
}


class RunHealthRules:
    """Evaluate the run-health rules with per-rule hysteresis."""

    def __init__(self, config: dict):
        self.config = normalise_config(config)
        self.state: dict[str, dict] = {
            rid: {'active': False, 'consecutive': 0, 'fired_at': None, 'last_message': None}
            for rid in RULE_DESCRIPTIONS
        }
        self.peak_active_channels = 0

    # -- pure evaluation ------------------------------------------------

    def evaluate_conditions(self, snapshot: dict, now: float) -> list[RuleResult]:
        cfg = self.config
        inputs = snapshot.get('inputs') or {}
        window = snapshot.get('window') or {}
        pores = snapshot.get('pores') or {}
        totals = snapshot.get('totals') or {}
        minknow = snapshot.get('minknow') or {}
        results: list[RuleResult] = []

        monitor_started = inputs.get('monitor_started') or now
        data_seen = bool(inputs.get('data_seen'))
        last_data_time = inputs.get('last_data_time')
        minutes_since_start = (now - monitor_started) / 60.0
        acquisition = str(minknow.get('acquisition_status') or '').upper()

        # 1. Run not started -------------------------------------------
        not_started = (not data_seen) and minutes_since_start >= cfg['runStartTimeoutMin']
        if acquisition == 'PROCESSING':
            # MinKNOW says it is acquiring; data will follow (basecalling
            # lag). Don't shout yet.
            not_started = False
        results.append(RuleResult(
            'run_not_started', not_started, SEVERITY_CRITICAL,
            f"No sequencing output has appeared in {inputs.get('watch_dir') or 'the output directory'} "
            f"after {minutes_since_start:.0f} min of monitoring. Check that the run was started in "
            f"MinKNOW and that the output directory is correct."
            + (f" MinKNOW acquisition state: {acquisition}." if acquisition else ''),
            {'minutes_since_start': round(minutes_since_start, 1), 'acquisition_status': acquisition or None},
        ))

        # 2. Data stalled ----------------------------------------------
        stalled = False
        minutes_since_data = None
        if data_seen and last_data_time:
            minutes_since_data = (now - last_data_time) / 60.0
            stalled = minutes_since_data >= cfg['stallTimeoutMin']
            if acquisition and acquisition not in ('PROCESSING', 'STARTING'):
                # Run finished cleanly according to MinKNOW: still worth a
                # notice, but not at warning level.
                pass
        results.append(RuleResult(
            'data_stalled', stalled, SEVERITY_WARNING,
            f"No new sequencing data for {minutes_since_data or 0:.0f} min "
            f"(last data: {inputs.get('last_data_file') or 'sequencing summary'}). "
            f"The run may have finished, paused, or the sequencer may have stopped writing."
            + (f" MinKNOW acquisition state: {acquisition}." if acquisition else ''),
            {'minutes_since_data': round(minutes_since_data, 1) if minutes_since_data is not None else None},
        ))

        enough = (window.get('reads') or 0) >= cfg['minWindowReads']

        # 3. Low median Q ----------------------------------------------
        med_q = window.get('median_q')
        low_q = enough and med_q is not None and med_q < cfg['minMedianQ']
        results.append(RuleResult(
            'low_median_q', low_q, SEVERITY_WARNING,
            f"Median Q-score over the last {window.get('reads', 0)} reads is {med_q if med_q is not None else 'n/a'} "
            f"(floor {cfg['minMedianQ']}). Read quality has degraded; consider checking the library, "
            f"flow cell temperature, or basecalling model.",
            {'median_q': med_q, 'threshold': cfg['minMedianQ'], 'window_reads': window.get('reads')},
        ))

        # 4. Pore decline (relative to peak) -----------------------------
        active = int(pores.get('active_channels') or 0)
        if enough or active > self.peak_active_channels:
            self.peak_active_channels = max(self.peak_active_channels, active)
        peak = self.peak_active_channels
        decline = (peak >= 20 and enough and active < peak * cfg['minActivePoresPct'] / 100.0)
        results.append(RuleResult(
            'pore_decline', decline, SEVERITY_WARNING,
            f"Only {active} channels produced reads in the last {pores.get('active_window_min', 10)} min "
            f"of run time, down from a peak of {peak} ({(active / peak * 100.0) if peak else 0:.0f}% of peak; "
            f"floor {cfg['minActivePoresPct']:.0f}%). Pores may be exhausted or blocked; a mux scan or "
            f"flow-cell wash may help.",
            {'active_channels': active, 'peak_active_channels': peak, 'threshold_pct': cfg['minActivePoresPct']},
        ))

        # 5. Absolute low channel count ---------------------------------
        total_channels = int(pores.get('total_channels') or 0)
        floor_channels = total_channels * cfg['minActiveChannelsPct'] / 100.0
        low_channels = (data_seen and (totals.get('reads') or 0) >= cfg['minWindowReads']
                        and total_channels > 0 and active < floor_channels)
        results.append(RuleResult(
            'low_active_channels', low_channels, SEVERITY_CRITICAL,
            f"Only {active} of {total_channels} channels ({pores.get('flow_cell_type', 'flow cell')}) have "
            f"produced reads recently (floor {cfg['minActiveChannelsPct']:.0f}%). The flow cell may be "
            f"damaged, dried out, or the library may not have loaded.",
            {'active_channels': active, 'total_channels': total_channels, 'threshold_pct': cfg['minActiveChannelsPct']},
        ))

        # 6. Low pass rate ---------------------------------------------
        pass_rate = window.get('pass_rate')
        low_pass = enough and pass_rate is not None and pass_rate < cfg['minPassRate']
        results.append(RuleResult(
            'low_pass_rate', low_pass, SEVERITY_WARNING,
            f"Only {pass_rate if pass_rate is not None else 'n/a'}% of the last {window.get('reads', 0)} reads pass "
            f"the quality filter (floor {cfg['minPassRate']:.0f}%).",
            {'pass_rate': pass_rate, 'threshold': cfg['minPassRate']},
        ))

        # 7. Short reads (opt-in) --------------------------------------
        med_len = window.get('median_length')
        short = (cfg['minMedianReadLength'] > 0 and enough and med_len is not None
                 and med_len < cfg['minMedianReadLength'])
        results.append(RuleResult(
            'short_reads', short, SEVERITY_INFO,
            f"Median read length over the last {window.get('reads', 0)} reads is "
            f"{int(med_len) if med_len else 'n/a'} bp (floor {int(cfg['minMedianReadLength'])} bp).",
            {'median_length': med_len, 'threshold': cfg['minMedianReadLength']},
        ))
        return results

    # -- stateful transitions -------------------------------------------

    def evaluate(self, snapshot: dict, now: float | None = None) -> tuple[list[RuleResult], list[RuleResult]]:
        """Returns ``(fired, recovered)`` transitions for this evaluation."""
        now = now or time.time()
        fired: list[RuleResult] = []
        recovered: list[RuleResult] = []
        if not self.config.get('enabled', True):
            return fired, recovered
        for result in self.evaluate_conditions(snapshot, now):
            st = self.state[result.rule_id]
            if result.active:
                st['consecutive'] += 1
                st['last_message'] = result.message
                if not st['active'] and st['consecutive'] >= self.config['consecutiveChecks']:
                    st['active'] = True
                    st['fired_at'] = now
                    fired.append(result)
            else:
                st['consecutive'] = 0
                if st['active']:
                    st['active'] = False
                    st['fired_at'] = None
                    recovered.append(result)
        return fired, recovered

    def status(self) -> list[dict]:
        return [
            {
                'id': rid,
                'description': RULE_DESCRIPTIONS[rid],
                'active': st['active'],
                'fired_at': st['fired_at'],
                'message': st['last_message'] if st['active'] else None,
            }
            for rid, st in self.state.items()
        ]


# ---------------------------------------------------------------------------
# Monitor thread
# ---------------------------------------------------------------------------

class RunHealthMonitor(threading.Thread):
    """Per-project background evaluator. Start with ``.start()``, stop with
    ``.stop()`` (joins within one interval)."""

    def __init__(self, project_id: str, project_dir: str, minion_dir: str | None, config: dict,
                 *, alert_log: AlertLog | None = None, notifier: Notifier | None = None,
                 device: str | None = None, file_handler=None, emit_updates: bool = True):
        super().__init__(daemon=True, name=f'nanocas-runhealth-{project_id[:8]}')
        self.project_id = project_id
        self.project_dir = project_dir
        self.minion_dir = minion_dir
        self.config = normalise_config(config)
        self.alert_log = alert_log or AlertLog(project_dir)
        self.notifier = notifier or Notifier({})
        self.device = device
        self.file_handler = file_handler
        self.emit_updates = emit_updates
        self.rules = RunHealthRules(self.config)
        self.tracker: SequencingSummaryTracker | None = None
        self.summary_path: str | None = None
        self.started_at = time.time()
        self._stop_event = threading.Event()
        self._snapshot: dict = self._empty_snapshot()
        self._snapshot_lock = threading.Lock()
        self._tick_count = 0
        self._minknow: dict | None = None

    # -- lifecycle -----------------------------------------------------

    def stop(self, join: bool = True) -> None:
        self._stop_event.set()
        if join and self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=self.config['checkIntervalSec'] + 5)

    def run(self) -> None:
        logger.info(f'Run-health monitor started for project {self.project_id} (watching {self.minion_dir})')
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.error(f'Run-health tick failed for {self.project_id}: {exc}', exc_info=True)
            self._stop_event.wait(self.config['checkIntervalSec'])
        logger.info(f'Run-health monitor stopped for project {self.project_id}')

    # -- evaluation ----------------------------------------------------

    def _empty_snapshot(self) -> dict:
        return {
            'projectId': self.project_id,
            'monitoring': True,
            'summary_file': None,
            'totals': {'reads': 0},
            'total_reads': 0,
            'window': {'reads': 0},
            'pores': {'total_channels': 0, 'active_channels': 0},
            'pore_health': {'total_channels': 0, 'active_channels': 0},
            'inputs': {},
            'rules': self.rules.status(),
            'config': self.config,
        }

    def _locate_summary(self) -> None:
        path = find_sequencing_summary(summary_search_dirs(self.project_dir, self.minion_dir))
        if path and path != self.summary_path:
            logger.info(f'Run-health monitor using sequencing summary {path}')
            self.summary_path = path
            self.tracker = SequencingSummaryTracker(path, window_reads=self.config['windowReads'])

    def tick(self, now: float | None = None) -> dict:
        now = now or time.time()
        self._tick_count += 1
        if self.tracker is None or self._tick_count % 10 == 0:
            self._locate_summary()
        if self.tracker is not None:
            self.tracker.update()

        # Poll MinKNOW sparingly; a gRPC round-trip every 2 min is plenty.
        if self.device and (self._minknow is None or self._tick_count % 4 == 1):
            from .LinuxNotification import LinuxNotification
            self._minknow = LinuxNotification.get_device_status(self.device)

        snapshot = self.build_snapshot(now)
        fired, recovered = self.rules.evaluate(snapshot, now)
        snapshot['rules'] = self.rules.status()
        for result in fired:
            record = self.alert_log.append(result.rule_id, result.severity, result.message,
                                           source=SOURCE_RUN_HEALTH, details=result.details,
                                           project_id=self.project_id)
            logger.warning(f'[run-health] {self.project_id}: {result.message}')
            self.notifier.send('nanoCAS run-health alert', result.message, severity=result.severity)
            emit_alert(record)
        for result in recovered:
            record = self.alert_log.append(result.rule_id, SEVERITY_INFO,
                                           f"Recovered: {RULE_DESCRIPTIONS[result.rule_id].lower()} no longer applies.",
                                           source=SOURCE_RUN_HEALTH, details=result.details,
                                           state='recovered', project_id=self.project_id)
            emit_alert(record)
        with self._snapshot_lock:
            self._snapshot = snapshot
        self._emit(snapshot)
        return snapshot

    def build_snapshot(self, now: float) -> dict:
        q_threshold = self.config['qScoreThreshold']
        if self.tracker is not None:
            snapshot = self.tracker.snapshot(q_threshold, self.config['poreWindowMin'])
        else:
            snapshot = self._empty_snapshot()
        latest_mtime, latest_path, file_count = latest_data_file(self.minion_dir)
        summary_mtime = (snapshot.get('summary_file') or {}).get('mtime') or None
        summary_reads = (snapshot.get('totals') or {}).get('reads') or 0
        last_processed = getattr(self.file_handler, 'last_processed_time', None)
        candidates = [t for t in (latest_mtime, summary_mtime if summary_reads else None, last_processed) if t]
        last_data_time = max(candidates) if candidates else None
        snapshot['projectId'] = self.project_id
        snapshot['monitoring'] = True
        snapshot['inputs'] = {
            'watch_dir': self.minion_dir,
            'data_files': file_count,
            'last_data_file': os.path.basename(latest_path) if latest_path else None,
            'last_data_time': last_data_time,
            'data_seen': bool(last_data_time) or summary_reads > 0,
            'monitor_started': self.started_at,
            'files_processed': len(getattr(self.file_handler, 'processed_files', []) or []),
            'files_failed': len(getattr(self.file_handler, 'failed_files', []) or []),
        }
        snapshot['minknow'] = self._minknow
        snapshot['config'] = self.config
        snapshot['evaluated_at'] = now
        return snapshot

    def snapshot(self) -> dict:
        with self._snapshot_lock:
            return dict(self._snapshot)

    def _emit(self, snapshot: dict) -> None:
        if not self.emit_updates:
            return
        safe_emit('run_health_update', {
            'projectId': self.project_id,
            'timestamp': snapshot.get('evaluated_at'),
            'totals': snapshot.get('totals'),
            'window': snapshot.get('window'),
            'pores': snapshot.get('pores'),
            'rules': snapshot.get('rules'),
        })


# ---------------------------------------------------------------------------
# One-shot use (no monitor running)
# ---------------------------------------------------------------------------

_STANDALONE_TRACKERS: dict[str, SequencingSummaryTracker] = {}
_STANDALONE_LOCK = threading.Lock()


def standalone_snapshot(summary_path: str, config: dict | None = None) -> dict:
    """Parse (incrementally, cached per path) a summary file outside of a
    running monitor. Used by ``/run_health`` when monitoring is stopped."""
    cfg = normalise_config(config)
    with _STANDALONE_LOCK:
        tracker = _STANDALONE_TRACKERS.get(summary_path)
        if tracker is None:
            tracker = SequencingSummaryTracker(summary_path, window_reads=cfg['windowReads'])
            _STANDALONE_TRACKERS[summary_path] = tracker
    tracker.update()
    snapshot = tracker.snapshot(cfg['qScoreThreshold'], cfg['poreWindowMin'])
    snapshot['monitoring'] = False
    snapshot['rules'] = []
    snapshot['config'] = cfg
    return snapshot
