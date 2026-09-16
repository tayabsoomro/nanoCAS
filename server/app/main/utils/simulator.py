"""Sequencer simulation: run nanoCAS end-to-end without a MinION.

Two things live here.

:func:`create_demo_project`
    Builds a self-contained project: a synthetic reference set (a host /
    background sequence, a contaminant and a pathogen), a minimap2 index,
    alert thresholds and fast run-health settings suited to a live demo.
    With ``seed_history=True`` it also *replays* a whole simulated run
    through the real pipeline (alignment, coverage accumulator, alert
    rules) with a synthetic clock, so the project opens with a complete
    coverage history and alert log, exactly as a finished run would look.

:class:`SimulatedRun`
    A background writer that behaves like MinKNOW: every ``interval_sec``
    it writes one gzipped FASTQ batch into the watched ``fastq_pass``
    directory (temp file + atomic rename) and appends matching rows to a
    ``sequencing_summary`` file. Read composition, read quality and the
    set of "active channels" follow a :data:`SCENARIOS` script, so the
    coverage alerts *and* the run-health rules can be demonstrated:

    ============ =====================================================
    clean        stable run, nothing to report
    contamination foreign DNA appears after a few batches -> depth /
                 breadth alerts on ``Contaminant_X``
    pathogen     a pathogen sequence appears at low abundance
    flowcell_failure pores die and quality collapses -> pore decline,
                 low active channels, low median Q, low pass rate
    stalled      the run stops producing data -> data stalled
    not_started  nothing is ever written -> run not started
    ============ =====================================================

Reads are sampled from the references with nanopore-like substitution and
indel errors; "junk" reads are random sequence and end up unmapped.
"""

from __future__ import annotations

import gzip
import logging
import math
import os
import random
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta

from . import project_store
from .alerts import AlertLog, safe_emit
from .run_health import normalise_config

logger = logging.getLogger('nanocas')

# ---------------------------------------------------------------------------
# Reference set
# ---------------------------------------------------------------------------

DEMO_REFERENCES = (
    # (id, length, description, role)
    ('Host_control', 60000, 'Expected sample DNA (background); no alert', 'host'),
    ('Contaminant_X', 30000, 'Foreign DNA to detect; alert at 5x depth or 50% breadth', 'contaminant'),
    ('Pathogen_Y', 20000, 'Low-abundance pathogen; alert at 3x depth', 'pathogen'),
)

DEMO_QUERIES = [
    {'name': 'Host control', 'header': 'Host_control', 'headers': ['Host_control'],
     'depth_threshold': '', 'alert_on_depth': False, 'breadth_threshold': '', 'alert_on_breadth': False},
    {'name': 'Contaminant X', 'header': 'Contaminant_X', 'headers': ['Contaminant_X'],
     'depth_threshold': '5', 'alert_on_depth': True, 'breadth_threshold': '50', 'alert_on_breadth': True},
    {'name': 'Pathogen Y', 'header': 'Pathogen_Y', 'headers': ['Pathogen_Y'],
     'depth_threshold': '3', 'alert_on_depth': True, 'breadth_threshold': '', 'alert_on_breadth': False},
]

# Run-health settings that make a demo react within a minute or two
# instead of the production defaults (15/30 min timeouts, 30 s checks).
DEMO_RUN_HEALTH_CONFIG = {
    'enabled': True,
    'runStartTimeoutMin': 1,
    'stallTimeoutMin': 1,
    'minMedianQ': 9.0,
    'qScoreThreshold': 9.0,
    'minPassRate': 50.0,
    'minActivePoresPct': 50.0,
    'minActiveChannelsPct': 10.0,
    'minMedianReadLength': 0,
    'windowReads': 400,
    'poreWindowMin': 10,
    'minWindowReads': 100,
    'consecutiveChecks': 1,
    'checkIntervalSec': 5,
}


def random_sequence(length: int, rng: random.Random) -> str:
    return ''.join(rng.choice('ACGT') for _ in range(length))


def build_demo_references(seed: int = 42) -> dict[str, str]:
    """Deterministic synthetic reference set (same sequences every time)."""
    rng = random.Random(seed)
    return {ref_id: random_sequence(length, rng) for ref_id, length, _, _ in DEMO_REFERENCES}


def write_fasta(path: str, references: dict[str, str]) -> None:
    descriptions = {r[0]: r[2] for r in DEMO_REFERENCES}
    with open(path, 'w') as fh:
        for ref_id, seq in references.items():
            fh.write(f'>{ref_id} {descriptions.get(ref_id, "")}\n')
            for i in range(0, len(seq), 80):
                fh.write(seq[i:i + 80] + '\n')


def read_fasta(path: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    current = None
    with open(path) as fh:
        for line in fh:
            if line.startswith('>'):
                current = line[1:].split()[0]
                refs[current] = ''
            elif current:
                refs[current] += line.strip()
    return refs


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict] = {
    'clean': {
        'label': 'Clean run',
        'summary': 'A healthy run with only the expected sample DNA. Nothing should alert.',
        'expect': [],
    },
    'contamination': {
        'label': 'Contamination detected',
        'summary': 'Foreign DNA appears after a few batches and climbs to ~20% of reads. '
                   'Depth and breadth alerts fire on Contaminant X.',
        'expect': ['depth', 'breadth'],
    },
    'pathogen': {
        'label': 'Pathogen at low abundance',
        'summary': 'A pathogen sequence appears at ~3% of reads; the depth alert fires once '
                   'enough reads have accumulated.',
        'expect': ['depth'],
    },
    'flowcell_failure': {
        'label': 'Failing flow cell',
        'summary': 'Active pores die off and read quality collapses over the run. '
                   'Pore-decline, low-channel, low-quality and low-pass-rate alerts fire.',
        'expect': ['pore_decline', 'low_active_channels', 'low_median_q', 'low_pass_rate'],
    },
    'stalled': {
        'label': 'Run stalls',
        'summary': 'The sequencer writes a few batches and then stops. The data-stalled alert '
                   'fires after the stall timeout.',
        'expect': ['data_stalled'],
    },
    'not_started': {
        'label': 'Run never starts',
        'summary': 'Monitoring is on but no data ever appears. The run-not-started alert fires '
                   'after the start timeout.',
        'expect': ['run_not_started'],
    },
}

DEFAULT_SCENARIO = 'contamination'


def scenario_list() -> list[dict]:
    return [{'id': k, **v} for k, v in SCENARIOS.items()]


class _Script:
    """Per-batch parameters for a scenario."""

    def __init__(self, scenario: str, total_batches: int = 40):
        if scenario not in SCENARIOS:
            raise ValueError(f'Unknown scenario {scenario!r}; choose from {", ".join(SCENARIOS)}')
        self.scenario = scenario
        self.total = max(1, total_batches)

    def composition(self, batch: int) -> dict[str, float]:
        """Fractions of reads by source for batch index ``batch`` (0-based)."""
        junk = 0.05
        contaminant = 0.0
        pathogen = 0.0
        if self.scenario == 'contamination':
            ramp_start = max(2, self.total // 8)
            ramp_len = max(3, self.total // 4)
            contaminant = 0.20 * min(1.0, max(0.0, (batch - ramp_start + 1) / ramp_len))
        elif self.scenario == 'pathogen':
            pathogen = 0.03 if batch >= max(2, self.total // 6) else 0.0
        host = max(0.0, 1.0 - junk - contaminant - pathogen)
        return {'host': host, 'contaminant': contaminant, 'pathogen': pathogen, 'junk': junk}

    def q_mean(self, batch: int) -> float:
        if self.scenario == 'flowcell_failure':
            frac = min(1.0, batch / max(1, self.total * 0.7))
            return 13.0 - 7.0 * frac  # 13 -> 6
        return 13.0

    def active_channels(self, batch: int, rng: random.Random) -> int:
        base = 440 + rng.randint(-15, 15)
        if self.scenario == 'flowcell_failure':
            frac = min(1.0, batch / max(1, self.total * 0.8))
            return max(20, int(base * math.exp(-3.2 * frac)))  # 440 -> ~20
        return base

    def writes_batch(self, batch: int) -> bool:
        if self.scenario == 'not_started':
            return False
        if self.scenario == 'stalled':
            return batch < max(3, self.total // 6)
        return True

    def reads_per_batch(self, batch: int, nominal: int) -> int:
        if self.scenario == 'flowcell_failure':
            frac = min(1.0, batch / max(1, self.total * 0.8))
            return max(20, int(nominal * (1 - 0.85 * frac)))
        return nominal


# ---------------------------------------------------------------------------
# Read generation
# ---------------------------------------------------------------------------

def _mutate(seq: str, rng: random.Random, sub: float = 0.04, indel: float = 0.01) -> str:
    out = []
    for base in seq:
        r = rng.random()
        if r < indel / 2:
            continue  # deletion
        if r < indel:
            out.append(rng.choice('ACGT'))  # insertion
        if rng.random() < sub:
            out.append(rng.choice('ACGT'.replace(base, '')))
        else:
            out.append(base)
    return ''.join(out)


def _read_length(rng: random.Random) -> int:
    return int(min(12000, max(300, rng.lognormvariate(math.log(2000), 0.55))))


class SimulatedRun(threading.Thread):
    """Write simulated MinKNOW output for one project.

    Call :meth:`start` for a background live simulation or
    :meth:`write_batch` directly (with ``interval_sec=0``) to generate a
    run synchronously.
    """

    def __init__(self, project_id: str, watch_dir: str, references: dict[str, str], scenario: str, *,
                 interval_sec: float = 5.0, reads_per_batch: int = 200, total_batches: int = 40,
                 time_scale: float = 60.0, seed: int | None = None, run_id: str | None = None,
                 clock_start: float | None = None, emit: bool = True):
        super().__init__(daemon=True, name=f'nanocas-sim-{project_id[:8]}')
        self.project_id = project_id
        self.watch_dir = watch_dir
        self.references = references
        self.scenario = scenario
        self.script = _Script(scenario, total_batches)
        self.interval_sec = max(0.0, float(interval_sec))
        self.reads_per_batch = max(10, int(reads_per_batch))
        self.total_batches = max(1, int(total_batches))
        # Run time advances `time_scale` x faster than wall time so the
        # per-minute run-health series evolves visibly during a demo.
        self.time_scale = max(1.0, float(time_scale))
        self.rng = random.Random(seed)
        self.run_id = run_id or f'sim{self.rng.randint(0, 10**8):08d}'
        self.summary_path = os.path.join(watch_dir, f'sequencing_summary_{self.run_id}.txt')
        self.emit = emit
        self.batches_written = 0
        self.reads_written = 0
        self.sim_time = 0.0
        self.started_at = clock_start or time.time()
        self.finished = False
        self.error: str | None = None
        self._stop_event = threading.Event()
        self._sources = {
            'host': [r[0] for r in DEMO_REFERENCES if r[3] == 'host'],
            'contaminant': [r[0] for r in DEMO_REFERENCES if r[3] == 'contaminant'],
            'pathogen': [r[0] for r in DEMO_REFERENCES if r[3] == 'pathogen'],
        }

    # -- lifecycle -----------------------------------------------------

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        logger.info(f'Simulated run ({self.scenario}) started for {self.project_id} -> {self.watch_dir}')
        try:
            os.makedirs(self.watch_dir, exist_ok=True)
            for batch in range(self.total_batches):
                if self._stop_event.is_set():
                    break
                self.write_batch(batch)
                self._emit_status()
                if self._stop_event.wait(self.interval_sec):
                    break
            self.finished = not self._stop_event.is_set()
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            logger.error(f'Simulated run failed: {exc}', exc_info=True)
        finally:
            self._emit_status(final=True)
            logger.info(f'Simulated run for {self.project_id} ended after {self.batches_written} batch(es)')

    def status(self) -> dict:
        return {
            'projectId': self.project_id,
            'scenario': self.scenario,
            'label': SCENARIOS[self.scenario]['label'],
            'running': self.is_alive() and not self._stop_event.is_set(),
            'finished': self.finished,
            'error': self.error,
            'batches_written': self.batches_written,
            'total_batches': self.total_batches,
            'reads_written': self.reads_written,
            'run_time_seconds': self.sim_time,
            'interval_sec': self.interval_sec,
            'watch_dir': self.watch_dir,
            'expect': SCENARIOS[self.scenario]['expect'],
        }

    def _emit_status(self, final: bool = False) -> None:
        if self.emit:
            payload = self.status()
            payload['final'] = final
            safe_emit('simulation_update', payload)

    # -- batch generation ----------------------------------------------

    def _make_read(self, source: str, q_mean: float) -> tuple[str, str, int, float]:
        """Return (sequence, quality string, length, mean_q)."""
        q = min(20.0, max(3.0, self.rng.gauss(q_mean, 1.5)))
        length = _read_length(self.rng)
        if source == 'junk' or not self._sources.get(source):
            seq = random_sequence(length, self.rng)
        else:
            ref = self.references[self.rng.choice(self._sources[source])]
            length = min(length, len(ref) - 1)
            start = self.rng.randint(0, len(ref) - length)
            seq = ref[start:start + length]
            if self.rng.random() < 0.5:
                seq = seq[::-1].translate(str.maketrans('ACGT', 'TGCA'))
            seq = _mutate(seq, self.rng)
        qual = chr(int(round(q)) + 33) * len(seq)
        return seq, qual, len(seq), q

    def write_batch(self, batch: int, *, wall_time: float | None = None) -> str | None:
        """Write batch ``batch``; returns the FASTQ path or None when the
        scenario produces nothing for this batch."""
        if not self.script.writes_batch(batch):
            self.sim_time += self.interval_sec * self.time_scale if self.interval_sec else 300.0
            return None
        os.makedirs(self.watch_dir, exist_ok=True)
        comp = self.script.composition(batch)
        q_mean = self.script.q_mean(batch)
        n_reads = self.script.reads_per_batch(batch, self.reads_per_batch)
        active = self.script.active_channels(batch, self.rng)
        channels = self.rng.sample(range(1, 513), k=min(512, active))
        batch_span = (self.interval_sec * self.time_scale) if self.interval_sec else 300.0
        fname = f'{self.run_id}_pass_{batch:05d}.fastq.gz'
        final_path = os.path.join(self.watch_dir, fname)
        tmp_path = os.path.join(self.watch_dir, f'.{fname}.tmp')
        summary_rows = []
        with gzip.open(tmp_path, 'wt') as fq:
            for i in range(n_reads):
                source = self.rng.choices(list(comp), weights=list(comp.values()))[0]
                seq, qual, length, q = self._make_read(source, q_mean)
                read_id = f'{self.run_id}-{batch:05d}-{i:04d}'
                fq.write(f'@{read_id} runid={self.run_id} ch={channels[i % len(channels)]}\n{seq}\n+\n{qual}\n')
                start_time = self.sim_time + self.rng.uniform(0, batch_span)
                summary_rows.append(
                    f'{fname}\t{read_id}\t{self.run_id}\t{channels[i % len(channels)]}\t{self.rng.randint(1, 4)}\t'
                    f'{start_time:.3f}\t{length / 400:.3f}\t{"TRUE" if q >= 9 else "FALSE"}\t{start_time:.3f}\t'
                    f'{length}\t{q:.2f}\t{"signal_positive" if q >= 9 else "unblock_mux_change"}\n')
                self.reads_written += 1
        os.replace(tmp_path, final_path)
        write_header = not os.path.exists(self.summary_path)
        with open(self.summary_path, 'a') as sm:
            if write_header:
                sm.write('filename_fastq\tread_id\trun_id\tchannel\tmux\tstart_time\tduration\tpasses_filtering\t'
                         'template_start\tsequence_length_template\tmean_qscore_template\tend_reason\n')
            sm.writelines(summary_rows)
        if wall_time is not None:
            os.utime(final_path, (wall_time, wall_time))
            os.utime(self.summary_path, (wall_time, wall_time))
        self.sim_time += batch_span
        self.batches_written += 1
        return final_path


# ---------------------------------------------------------------------------
# Registry of live simulations
# ---------------------------------------------------------------------------

_SIMS: dict[str, SimulatedRun] = {}
_SIMS_LOCK = threading.Lock()


def get_simulation(project_id: str) -> SimulatedRun | None:
    with _SIMS_LOCK:
        sim = _SIMS.get(project_id)
    return sim


def simulation_status(project_id: str) -> dict | None:
    sim = get_simulation(project_id)
    return sim.status() if sim else None


def list_simulating() -> list[str]:
    with _SIMS_LOCK:
        return [pid for pid, sim in _SIMS.items() if sim.is_alive()]


def start_simulation(project_id: str, scenario: str = DEFAULT_SCENARIO, *, interval_sec: float = 5.0,
                     reads_per_batch: int = 200, total_batches: int = 40, fresh: bool = True) -> SimulatedRun:
    """Start writing a simulated run into the project's watched directory.

    ``fresh=True`` clears previously simulated files from the watched
    directory (and the project's processed-file bookkeeping) so the demo
    starts from zero. Raises ``ValueError`` on bad input.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f'Unknown scenario {scenario!r}')
    cfg = project_store.load_config(project_id)
    if not cfg:
        raise ValueError('Project not found')
    watch_dir = cfg.get('minion')
    if not watch_dir:
        raise ValueError('Project has no watched directory')
    pdir = project_store.project_dir(project_id)
    ref_path = os.path.join(pdir, 'demo_reference.fasta')
    references = read_fasta(ref_path) if os.path.exists(ref_path) else build_demo_references()

    with _SIMS_LOCK:
        existing = _SIMS.get(project_id)
        if existing and existing.is_alive():
            raise ValueError('A simulation is already running for this project')
        if fresh:
            reset_project_run(project_id, watch_dir)
        sim = SimulatedRun(project_id, watch_dir, references, scenario, interval_sec=interval_sec,
                           reads_per_batch=reads_per_batch, total_batches=total_batches)
        _SIMS[project_id] = sim
        sim.start()
    AlertLog(pdir).append('simulation_started', 'info',
                          f"Simulated run started: {SCENARIOS[scenario]['label']}",
                          source='system', details={'scenario': scenario}, project_id=project_id)
    return sim


def stop_simulation(project_id: str) -> bool:
    """Stop (and forget) the project's simulation. Returns True only if a
    simulation was actually running; a finished one is just cleared."""
    with _SIMS_LOCK:
        sim = _SIMS.pop(project_id, None)
    if not sim:
        return False
    was_running = sim.is_alive()
    sim.stop()
    if was_running:
        sim.join(timeout=5)
    return was_running


def reset_project_run(project_id: str, watch_dir: str | None = None) -> None:
    """Remove simulated input files and all derived state so a project can
    be re-run from scratch. Only files produced by the simulator (or the
    project's own state) are touched; a real MinKNOW directory is never
    cleared."""
    pdir = project_store.project_dir(project_id)
    # A running listener must be stopped so it doesn't see half-cleared state.
    from ..events import stop_listener
    was_running = stop_listener(project_id)
    if watch_dir and os.path.isdir(watch_dir) and _is_simulated_dir(pdir, watch_dir):
        for name in os.listdir(watch_dir):
            if name.startswith('sim') or name.startswith('sequencing_summary_sim') or name.startswith('.sim'):
                try:
                    os.remove(os.path.join(watch_dir, name))
                except OSError:
                    pass
    for name in ('coverage.csv', 'coverage_state.npz', 'coverage_state.json', 'processed_files.txt',
                 'failed_files.json', 'sent_alerts.json', 'merged.bam', 'merged.bam.bai', 'merge_manifest.json'):
        p = os.path.join(pdir, name)
        if os.path.exists(p):
            os.remove(p)
    runs = os.path.join(pdir, 'minimap2', 'runs')
    if os.path.isdir(runs):
        shutil.rmtree(runs, ignore_errors=True)
    os.makedirs(runs, exist_ok=True)
    if was_running:
        from ..events import start_listener
        start_listener(project_id, watch_dir or '')


def _is_simulated_dir(pdir: str, watch_dir: str) -> bool:
    real = os.path.realpath(watch_dir)
    return real.startswith(os.path.realpath(pdir) + os.sep) or 'nanocas' in real.lower()


# ---------------------------------------------------------------------------
# Demo projects
# ---------------------------------------------------------------------------

def create_demo_project(*, scenario: str = DEFAULT_SCENARIO, name: str | None = None,
                        seed_history: bool = False, history_batches: int = 36,
                        progress=None) -> dict:
    """Create a ready-to-run demo project and return its config.

    The project watches ``<project>/simulated_run/fastq_pass``; nothing
    outside the nanoCAS workspace is touched.
    """
    from .tasks import int_download_database
    if scenario not in SCENARIOS:
        raise ValueError(f'Unknown scenario {scenario!r}')

    project_id = project_store.new_project_id()
    pdir = project_store.project_dir(project_id)
    watch_dir = os.path.join(pdir, 'simulated_run', 'fastq_pass')
    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(os.path.join(pdir, 'database'), exist_ok=True)
    os.makedirs(os.path.join(pdir, 'minimap2', 'runs'), exist_ok=True)

    references = build_demo_references()
    ref_path = os.path.join(pdir, 'demo_reference.fasta')
    write_fasta(ref_path, references)
    # The index builder deletes the *directory* of each query file after
    # use (it expects wizard uploads in temp dirs), so hand it a copy.
    upload_dir = tempfile.mkdtemp(prefix='demo_', dir=project_store.ensure_workspace())
    upload_copy = os.path.join(upload_dir, 'demo_reference.fasta')
    shutil.copy(ref_path, upload_copy)

    label = SCENARIOS[scenario]['label']
    cfg = {
        'projectId': project_id,
        'projectName': name or (f'Demo: {label}' + (' (completed run)' if seed_history else '')),
        'minion': watch_dir,
        'fileType': 'FASTQ',
        'device': '',
        'gff_file': None,
        'queries': [dict(q, file=upload_copy) for q in DEMO_QUERIES],
        'alertNotifConfig': {'enableEmail': False, 'enableSMS': False},
        'runHealthConfig': normalise_config(DEMO_RUN_HEALTH_CONFIG),
        'demo': True,
        'demoScenario': scenario,
        'createdAt': project_store.now_iso(),
    }
    project_store.save_config(project_id, cfg)
    project_store.append_cache(project_id, watch_dir, pdir)

    result = int_download_database(db_data=cfg, nanocas_location=pdir + os.sep, queries=cfg['queries'],
                                   progress_callback=progress)
    if not isinstance(result, dict):
        project_store.delete_project(project_id)
        raise RuntimeError(f'Could not build the demo reference index ({result}). '
                           'Are minimap2 and samtools installed?')
    # Drop the temp path from the stored queries; it no longer exists.
    cfg = project_store.load_config(project_id) or cfg
    for q in cfg.get('queries', []):
        q['file'] = ref_path
    project_store.save_config(project_id, cfg)

    log = AlertLog(pdir)
    if seed_history:
        # Date the creation record at the start of the replayed run so the
        # alert history reads chronologically.
        start = datetime.now() - timedelta(minutes=history_batches * 5)
        log.clock = lambda s=start: s
        log.append('project_created', 'info', f'Demo project created ({label}); replaying a simulated run',
                   source='system', project_id=project_id)
        log.clock = None
        replay_run(project_id, scenario, batches=history_batches, progress=progress)
        _seed_lab_results(project_id, scenario)
    else:
        log.append('project_created', 'info', f'Demo project created ({label})',
                   source='system', project_id=project_id)
    return project_store.load_config(project_id) or cfg


def replay_run(project_id: str, scenario: str, *, batches: int = 36, interval_minutes: float = 5.0,
               reads_per_batch: int = 200, progress=None) -> dict:
    """Generate a whole simulated run and push it through the real pipeline
    with a synthetic clock, so coverage.csv, the alert log and the
    sequencing summary look like a run that happened over the last
    ``batches * interval_minutes`` minutes."""
    from .FileHandler import FileHandler
    from .run_health import RunHealthMonitor

    cfg = project_store.load_config(project_id)
    if not cfg:
        raise ValueError('Project not found')
    pdir = project_store.project_dir(project_id)
    watch_dir = cfg['minion']
    references = read_fasta(os.path.join(pdir, 'demo_reference.fasta'))

    end_wall = time.time()
    start_wall = end_wall - batches * interval_minutes * 60
    sim = SimulatedRun(project_id, watch_dir, references, scenario, interval_sec=0,
                       reads_per_batch=reads_per_batch, total_batches=batches, seed=7,
                       clock_start=start_wall, emit=False)
    handler = FileHandler(pdir + os.sep)
    handler.notifier.send = lambda *a, **k: None  # no e-mail/SMS while replaying
    monitor = RunHealthMonitor(project_id, pdir, watch_dir, cfg.get('runHealthConfig') or {},
                               alert_log=handler.alert_log, notifier=handler.notifier,
                               file_handler=handler, emit_updates=False)
    monitor.started_at = start_wall
    monitor.notifier.send = lambda *a, **k: None

    fired: list[str] = []
    for b in range(batches):
        wall = start_wall + b * interval_minutes * 60
        stamp = datetime.fromtimestamp(wall)
        handler.clock = lambda s=stamp: s
        handler.alert_log.clock = lambda s=stamp: s
        path = sim.write_batch(b, wall_time=wall)
        if path:
            handler._handle_path(path, wait_stable=False, timestamp=stamp.strftime('%Y-%m-%d %H:%M:%S'))
        snapshot = monitor.tick(now=wall)
        fired = [r['id'] for r in snapshot['rules'] if r['active']]
        if progress:
            progress(int(100 * (b + 1) / batches), f'Replaying batch {b + 1}/{batches}')
    return {'batches': sim.batches_written, 'reads': sim.reads_written, 'active_rules': fired,
            'alerts': handler.alert_log.count()}


def _seed_lab_results(project_id: str, scenario: str) -> None:
    """Plausible confirmatory qPCR results for a replayed demo run, so the
    Lab results tab and the across-runs summary have something to show.
    Ct values follow the usual log-linear yield relationship (about -0.3
    log10 RPM per cycle) with a little noise."""
    from . import lab_results
    rng = random.Random(hash(project_id) & 0xFFFF)
    rows: list[dict] = []
    if scenario == 'contamination':
        rows = [{'target': 'Contaminant_X', 'ct': round(rng.uniform(22.5, 25.5), 1), 'sample_id': 'S-01', 'result': 'positive'},
                {'target': 'Pathogen_Y', 'result': 'negative', 'sample_id': 'S-01'}]
    elif scenario == 'pathogen':
        rows = [{'target': 'Pathogen_Y', 'ct': round(rng.uniform(29.0, 32.0), 1), 'sample_id': 'S-02', 'result': 'positive'},
                {'target': 'Contaminant_X', 'result': 'negative', 'sample_id': 'S-02'}]
    else:
        rows = [{'target': 'Contaminant_X', 'result': 'negative', 'sample_id': 'S-03'},
                {'target': 'Pathogen_Y', 'result': 'negative', 'sample_id': 'S-03'}]
    for row in rows:
        try:
            lab_results.add_result(project_id, dict(row, assay='qPCR (demo)'))
        except ValueError as exc:
            logger.warning(f'Could not seed demo lab result: {exc}')


def list_demo_projects() -> list[dict]:
    return [p for p in project_store.list_projects() if (project_store.load_config(p['id']) or {}).get('demo')]
