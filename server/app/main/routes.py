"""HTTP API. All project-scoped endpoints take ``projectId`` (query
string) or ``uid`` (form) and validate it through ``project_store``
before touching the filesystem."""

from __future__ import annotations

import glob
import gzip
import json
import logging
import os
import subprocess
import tempfile
from typing import NoReturn

import pysam
from flask import abort, jsonify, make_response, request
from werkzeug.utils import secure_filename

from . import main
from .utils import project_store
from .utils.LinuxNotification import LinuxNotification
from .utils.alerts import AlertLog, Notifier
from .utils.directory_scanner import scan_directory
from .utils.run_health import (DEFAULT_RUN_HEALTH_CONFIG, RULE_DESCRIPTIONS,
                               find_sequencing_summary, normalise_config,
                               standalone_snapshot, summary_search_dirs)
from .utils.sms import twilio_configured

logger = logging.getLogger('nanocas')

VERSION = "0.3.0"

NANOCAS_DIR = project_store.NANOCAS_DIR
CACHE_PATH = project_store.CACHE_PATH

FASTA_EXTENSIONS = ('.fasta', '.fa', '.fna', '.fasta.gz', '.fa.gz', '.fna.gz')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _abort_json(status: int, message: str) -> NoReturn:
    """Abort with a JSON body so every error has the same ``{"error": …}`` shape."""
    abort(make_response(jsonify({'error': message}), status))


def _validated_project_path(project_id: str | None, must_exist: bool = True) -> str:
    """Validate a ``projectId`` and return its absolute directory, aborting
    the request with a JSON error on anything suspicious. See LOGBOOK 4.8."""
    if not project_id:
        _abort_json(400, 'projectId is required')
    try:
        path = project_store.project_dir(project_id)
    except ValueError:
        _abort_json(400, 'Invalid project ID')
    if must_exist and not os.path.isdir(path):
        _abort_json(404, 'Project not found')
    return path


def _listener_for(project_id: str):
    """The live listener bundle (observer/handler/monitor) if monitoring."""
    from .events import get_listener
    return get_listener(project_id)


def _is_safe_path(base_dir, target_path):
    real_base = os.path.realpath(base_dir)
    real_target = os.path.realpath(target_path)
    return real_target.startswith(real_base + os.sep) or real_target == real_base


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@main.route('/version', methods=['GET'])
def version():
    return jsonify({"version": VERSION, "name": "nanoCAS"})


@main.route('/health', methods=['GET'])
def health():
    """Liveness + dependency check for deployment probes and the UI."""
    import shutil
    tools = {name: shutil.which(name) is not None for name in ('minimap2', 'samtools')}
    return jsonify({
        'status': 'ok' if all(tools.values()) else 'degraded',
        'version': VERSION,
        'tools': tools,
        'twilio_configured': twilio_configured(),
        'workspace': NANOCAS_DIR,
    })


# ---------------------------------------------------------------------------
# Project registry
# ---------------------------------------------------------------------------

@main.route('/check_database_status', methods=['GET'])
def check_database_status():
    nanocas_path = _validated_project_path(request.args.get('projectId'))
    mmi_files = glob.glob(os.path.join(nanocas_path, 'database', '*.mmi'))
    return jsonify({'is_ready': len(mmi_files) > 0})


@main.route('/get_uid', methods=["POST"])
def get_uid():
    """Mint a fresh project id.

    The previous implementation returned the *existing* id when the same
    sequencer directory had been used before, and project creation then
    wiped that directory, so setting up a second analysis on the same
    run silently destroyed the first one. Every project now gets its own
    id; the same directory may be watched by several projects.
    """
    minion_location = request.form.get('minION')
    if not minion_location:
        _abort_json(400, "minION location not provided.")
    uid = project_store.new_project_id()
    project_store.append_cache(uid, minion_location, os.path.join(NANOCAS_DIR, uid))
    return jsonify({'uid': uid})


@main.route('/get_all_analyses', methods=['GET'])
def get_all_analyses():
    from .events import list_running
    running = set(list_running())
    data = project_store.list_projects()
    for entry in data:
        entry['monitoring'] = entry['id'] in running
    return jsonify({'status': 200, 'data': data})


@main.route('/delete_analyses', methods=['POST'])
def delete_analyses():
    uid = request.form.get('uid')
    if not uid and request.is_json:
        uid = (request.get_json(silent=True) or {}).get('uid')
    if not project_store.is_valid_project_id(uid):
        _abort_json(400, 'Invalid project ID')
    from .events import stop_listener
    stop_listener(uid)
    try:
        found = project_store.delete_project(uid)
    except ValueError:
        _abort_json(400, 'Invalid project ID')
    return jsonify({'status': 200, 'found': found})


@main.route('/get_analysis_info', methods=['GET'])
def get_analysis_info():
    uid = request.args.get('uid')
    if not project_store.is_valid_project_id(uid):
        return jsonify({'status': 400, 'message': 'Invalid project ID'}), 400
    cfg = project_store.load_config(uid)
    if cfg is None:
        return jsonify({'status': 404, 'message': f"Couldn't find the analysis data with UID: {uid}"}), 404
    # Never hand the SMTP password back to the browser.
    cfg = _redact_config(cfg)
    cfg['runHealthConfig'] = normalise_config(cfg.get('runHealthConfig'))
    return jsonify({'status': 200, 'data': cfg})


def _redact_config(cfg: dict) -> dict:
    cfg = json.loads(json.dumps(cfg))
    email = (cfg.get('alertNotifConfig') or {}).get('emailConfig') or {}
    if email.get('password'):
        email['password'] = '********'
        email['passwordSet'] = True
    return cfg


@main.route('/get_default_nanopore_path', methods=['GET'])
def get_default_nanopore_path():
    default_path = os.path.join(NANOCAS_DIR, 'nanopore_data')
    os.makedirs(default_path, exist_ok=True)
    return jsonify({'path': default_path})


@main.route('/validate_locations', methods=['POST'])
def validate_locations():
    minion_location = request.form.get('minION', '')
    if not minion_location:
        return jsonify({"code": 1, "message": "Nanopore directory is required."})
    project_store.ensure_workspace()
    # Auto-create the sequencer output directory if it doesn't exist so a
    # project can be prepared before the run is started in MinKNOW.
    if not os.path.exists(minion_location):
        try:
            os.makedirs(minion_location, exist_ok=True)
            logger.info(f"Auto-created minION directory: {minion_location}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Could not create minION directory {minion_location}: {e}")
            return jsonify({"code": 1, "message": f"Cannot create nanopore directory: {e}"})
    elif not os.path.isdir(minion_location):
        return jsonify({"code": 1, "message": "Nanopore location exists but is not a directory."})
    return jsonify({"code": 0, "message": "SUCCESS"})


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

@main.route('/upload_reference', methods=['POST'])
def upload_reference():
    """Upload a reference genome (FASTA) to the nanopore data directory."""
    target_dir = request.form.get('target_dir', '') or os.path.join(NANOCAS_DIR, 'nanopore_data')
    os.makedirs(target_dir, exist_ok=True)
    uploaded = []
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files provided'}), 400
    for file in files:
        if not file.filename or not file.filename.lower().endswith(FASTA_EXTENSIONS):
            logger.warning(f"Skipped non-FASTA file: {file.filename}")
            continue
        safe_name = secure_filename(file.filename)
        if not safe_name:
            logger.warning(f"Rejected unsafe filename: {file.filename!r}")
            continue
        file_path = os.path.join(target_dir, safe_name)
        file.save(file_path)
        uploaded.append(safe_name)
        logger.debug(f"Uploaded FASTA reference file to {file_path}")
    if not uploaded:
        return jsonify({'error': 'No valid FASTA files found (.fasta, .fa, .fna, .fasta.gz, .fa.gz, .fna.gz)'}), 400
    return jsonify({'uploaded': uploaded, 'directory': target_dir})


def _save_uploaded_file(label: str, allowed: tuple[str, ...] | None = None):
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    safe_name = secure_filename(file.filename)
    if not safe_name:
        return jsonify({'error': 'Invalid filename'}), 400
    if allowed and not safe_name.lower().endswith(allowed):
        return jsonify({'error': f'{label} file must have one of: {", ".join(allowed)}'}), 400
    project_store.ensure_workspace()
    temp_dir = tempfile.mkdtemp(prefix='upload_', dir=NANOCAS_DIR)
    file_path = os.path.join(temp_dir, safe_name)
    file.save(file_path)
    logger.debug(f"Uploaded {label} file to {file_path}")
    return jsonify({'file_path': file_path})


@main.route('/upload_fasta', methods=['POST'])
def upload_fasta():
    return _save_uploaded_file('FASTA', FASTA_EXTENSIONS)


@main.route('/upload_gff', methods=['POST'])
def upload_gff():
    return _save_uploaded_file('GFF', ('.gff', '.gff3', '.txt'))


@main.route('/parse_fasta_headers', methods=['POST'])
def parse_fasta_headers():
    """Return the canonical reference IDs (first header token) plus the
    full description and sequence length of every record in an uploaded
    FASTA, so the wizard can show a meaningful picker."""
    data = request.json or {}
    file_path = data.get('file_path')
    if not file_path or not os.path.exists(file_path) or not _is_safe_path(NANOCAS_DIR, file_path):
        return jsonify({'error': 'Invalid file path'}), 400
    headers: list[str] = []
    records: list[dict] = []
    try:
        opener = gzip.open if file_path.endswith('.gz') else open
        current: dict | None = None
        with opener(file_path, 'rt') as f:
            for line in f:
                if line.startswith('>'):
                    tokens = line[1:].strip().split(None, 1)
                    if not tokens:
                        continue
                    current = {'id': tokens[0], 'description': tokens[1] if len(tokens) > 1 else '', 'length': 0}
                    headers.append(tokens[0])
                    records.append(current)
                elif current is not None:
                    current['length'] += len(line.strip())
        if not headers:
            return jsonify({'error': 'No FASTA records found in the uploaded file'}), 400
        logger.debug(f"Parsed {len(headers)} headers from {file_path}")
        return jsonify({'headers': headers, 'records': records})
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error parsing FASTA headers: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Coverage + alignments
# ---------------------------------------------------------------------------

def _ref_display_names(cfg: dict | None) -> dict[str, str]:
    """Map canonical reference id -> the user's query name."""
    from .utils.FileHandler import _canonical_ref_id
    names: dict[str, str] = {}
    for q in (cfg or {}).get('queries', []) or []:
        headers = list(q.get('headers') or [])
        if q.get('header'):
            headers.append(q['header'])
        for h in headers:
            key = _canonical_ref_id(h)
            if key:
                names[key] = q.get('name') or key
    return names


@main.route('/get_coverage', methods=['GET'])
def get_coverage():
    nanocas_path = _validated_project_path(request.args.get('projectId'))
    coverage_file = os.path.join(nanocas_path, 'coverage.csv')
    if not os.path.exists(coverage_file):
        return jsonify([])

    names = _ref_display_names(project_store.load_config(request.args.get('projectId')))
    data = []
    try:
        with open(coverage_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('timestamp,'):
                    continue
                parts = line.split(',')
                if len(parts) < 5:
                    continue
                timestamp, ref, depth, breadth, read_count = parts[0], parts[1], parts[2], parts[3], parts[4]
                try:
                    data.append({
                        'timestamp': timestamp,
                        'reference': ref,
                        'name': names.get(ref, ref),
                        'depth': float(depth),
                        'breadth': float(breadth),
                        'read_count': int(float(read_count)),
                    })
                except ValueError:
                    continue
        return jsonify(data)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error reading coverage file: {e}")
        return jsonify({'error': 'Error processing coverage data'}), 500


@main.route('/get_coverage_summary', methods=['GET'])
def get_coverage_summary():
    """Latest per-reference values straight from the accumulator sidecar
    (no CSV scan), with the configured thresholds attached."""
    project_id = request.args.get('projectId')
    nanocas_path = _validated_project_path(project_id)
    cfg = project_store.load_config(project_id) or {}
    names = _ref_display_names(cfg)
    thresholds: dict[str, dict] = {}
    from .utils.FileHandler import _canonical_ref_id
    for q in cfg.get('queries', []) or []:
        for h in list(q.get('headers') or []) + ([q['header']] if q.get('header') else []):
            thresholds[_canonical_ref_id(h)] = q
    latest: dict[str, dict] = {}
    coverage_file = os.path.join(nanocas_path, 'coverage.csv')
    if os.path.exists(coverage_file):
        with open(coverage_file) as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) < 5 or parts[0] == 'timestamp':
                    continue
                try:
                    latest[parts[1]] = {'timestamp': parts[0], 'depth': float(parts[2]),
                                        'breadth': float(parts[3]), 'read_count': int(float(parts[4]))}
                except ValueError:
                    continue
    rows = []
    for ref, vals in latest.items():
        q = thresholds.get(ref, {})
        rows.append({
            'reference': ref,
            'name': names.get(ref, ref),
            **vals,
            'depth_threshold': float(q.get('depth_threshold') or 0) if q.get('alert_on_depth') else None,
            'breadth_threshold': float(q.get('breadth_threshold') or 0) if q.get('alert_on_breadth') else None,
        })
    rows.sort(key=lambda r: (r['reference'] == 'unmapped', r['name']))
    return jsonify({'references': rows})


@main.route('/index_devices', methods=['GET'])
def index_devices():
    """Enumerate MinKNOW flow-cell positions. Read-only: the old version
    pushed a "device discovered" message to every instrument on each
    call, which is a side effect a GET must not have."""
    devices = []
    for device in LinuxNotification.index_devices():
        state = str(getattr(device, 'state', ''))
        if state not in ("STATE_HARDWARE_REMOVED", "STATE_HARDWARE_ERROR", "STATE_SOFTWARE_ERROR"):
            devices.append(device.name)
    return jsonify(devices)


def parse_gff(gff_path, sequence_id):
    regions = []
    try:
        with open(gff_path, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    fields = line.strip().split('\t')
                    if len(fields) >= 5 and fields[0] == sequence_id:
                        try:
                            start = int(fields[3])
                            end = int(fields[4])
                        except ValueError:
                            continue
                        attributes = fields[8] if len(fields) > 8 else ""
                        region_id = None
                        name = None
                        for attr in attributes.split(';'):
                            if attr.startswith('ID='):
                                region_id = attr[3:]
                            elif attr.startswith('Name='):
                                name = attr[5:]
                        regions.append({'start': start, 'end': end, 'id': region_id or name or f'{start}-{end}',
                                        'name': name, 'type': fields[2] if len(fields) > 2 else None})
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error parsing GFF file {gff_path}: {e}")
    return regions


def _ensure_merged_bam(nanocas_path: str) -> str | None:
    """Build (or refresh) ``merged.bam`` from the per-FASTQ sorted BAMs
    under ``minimap2/runs/`` for the alignment viewer. Cached against
    ``merge_manifest.json`` so an unchanged input set is not re-merged."""
    runs_dir = os.path.join(nanocas_path, 'minimap2', 'runs')
    merged_bam = os.path.join(nanocas_path, 'merged.bam')
    manifest_path = os.path.join(nanocas_path, 'merge_manifest.json')
    legacy_bam = os.path.join(nanocas_path, 'legacy_pre_v9.bam')

    inputs: list[str] = []
    if os.path.exists(legacy_bam):
        inputs.append(legacy_bam)
    if os.path.isdir(runs_dir):
        inputs.extend(sorted(glob.glob(os.path.join(runs_dir, '*_sorted.bam'))))
    if not inputs:
        return None

    cached_inputs: list[str] = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                cached_inputs = json.load(f).get('inputs', [])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not read merge manifest {manifest_path}: {e}")
    if cached_inputs == inputs and os.path.exists(merged_bam) and os.path.exists(merged_bam + '.bai'):
        return merged_bam

    tmp_bam = merged_bam + '.tmp.bam'
    try:
        if len(inputs) == 1:
            import shutil
            shutil.copy(inputs[0], tmp_bam)
        else:
            subprocess.run(['samtools', 'merge', '-f', tmp_bam, *inputs], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3600)
        pysam.index(tmp_bam)
        os.replace(tmp_bam, merged_bam)
        os.replace(tmp_bam + '.bai', merged_bam + '.bai')
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.error(f"samtools merge/index failed for {nanocas_path}: {e}")
        for p in (tmp_bam, tmp_bam + '.bai'):
            if os.path.exists(p):
                os.remove(p)
        return None

    try:
        with open(manifest_path, 'w') as f:
            json.dump({'inputs': inputs}, f)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not write merge manifest {manifest_path}: {e}")
    return merged_bam


@main.route('/get_alignments', methods=['GET'])
def get_alignments():
    project_id = request.args.get('projectId')
    nanocas_path = _validated_project_path(project_id)
    reference = request.args.get('reference')
    if not reference:
        return jsonify({'error': 'reference is required'}), 400
    try:
        max_reads = max(1, min(int(request.args.get('max_reads', 5000)), 50000))
    except ValueError:
        max_reads = 5000

    merged_bam = _ensure_merged_bam(nanocas_path)
    if not merged_bam:
        return jsonify({'error': 'No alignments available yet'}), 404

    try:
        with pysam.AlignmentFile(merged_bam, "rb") as bam:
            if reference not in bam.references:
                # Allow the display name as a fallback.
                names = _ref_display_names(project_store.load_config(project_id))
                inverse = {v: k for k, v in names.items()}
                reference = inverse.get(reference, reference)
                if reference not in bam.references:
                    return jsonify({'error': 'Reference not found in BAM file'}), 404
            ref_length = bam.lengths[bam.references.index(reference)]
            alignments = []
            total = 0
            for alignment in bam.fetch(reference):
                if alignment.is_unmapped or alignment.is_secondary or alignment.is_supplementary:
                    continue
                total += 1
                if len(alignments) < max_reads:
                    alignments.append({
                        'start': alignment.reference_start,
                        'end': alignment.reference_end,
                        'strand': '-' if alignment.is_reverse else '+',
                        'mapq': alignment.mapping_quality,
                    })

        cfg = project_store.load_config(project_id) or {}
        regions = []
        gff_file = cfg.get('gff_file')
        if gff_file and os.path.exists(gff_file):
            regions = parse_gff(gff_file, reference)
            for region in regions:
                region['read_count'] = sum(
                    1 for aln in alignments if aln['start'] < region['end'] and aln['end'] > region['start'])

        return jsonify({'reference': reference, 'ref_length': ref_length, 'alignments': alignments,
                        'total_alignments': total, 'truncated': total > len(alignments), 'regions': regions})
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error getting alignments: {e}", exc_info=True)
        return jsonify({'error': 'Error processing BAM file'}), 500


# ---------------------------------------------------------------------------
# Directory scan + run health
# ---------------------------------------------------------------------------

@main.route('/scan_directory', methods=['POST'])
def scan_dir_endpoint():
    data = request.json or {}
    directory = data.get('directory', '')
    if not directory:
        return jsonify({'error': 'directory is required'}), 400
    real_dir = os.path.realpath(os.path.expanduser(directory))
    return jsonify(scan_directory(real_dir))


@main.route('/run_health', methods=['GET'])
def run_health():
    """Run-health snapshot. If the project is being monitored, this is
    the live monitor state (rules included); otherwise a one-shot,
    incrementally-cached parse of the newest sequencing summary."""
    project_id = request.args.get('projectId')
    nanocas_path = _validated_project_path(project_id)
    listener = _listener_for(project_id)
    if listener and listener.get('monitor') is not None:
        snapshot = listener['monitor'].snapshot()
        if snapshot.get('inputs'):
            return jsonify(snapshot)

    cfg = project_store.load_config(project_id) or {}
    summary_path = find_sequencing_summary(summary_search_dirs(nanocas_path, cfg.get('minion')))
    if not summary_path:
        return jsonify({'error': 'No sequencing summary file found', 'monitoring': bool(listener)}), 404
    snapshot = standalone_snapshot(summary_path, cfg.get('runHealthConfig'))
    snapshot['projectId'] = project_id
    return jsonify(snapshot)


@main.route('/run_health_defaults', methods=['GET'])
def run_health_defaults():
    return jsonify({'defaults': DEFAULT_RUN_HEALTH_CONFIG, 'rules': RULE_DESCRIPTIONS})


@main.route('/get_processing_status', methods=['GET'])
def get_processing_status():
    """How many input files have been processed for this project, the
    most recent filename, and whether monitoring is active."""
    project_id = request.args.get('projectId')
    nanocas_path = _validated_project_path(project_id)
    listener = _listener_for(project_id)
    if listener and listener.get('handler') is not None:
        handler = listener['handler']
        st = handler.status()
        last = None
        processed_files_path = os.path.join(nanocas_path, 'processed_files.txt')
        if os.path.exists(processed_files_path):
            with open(processed_files_path, 'rb') as f:
                try:
                    f.seek(-4096, os.SEEK_END)
                except OSError:
                    f.seek(0)
                tail = f.read().decode(errors='replace').strip().splitlines()
                last = tail[-1] if tail else None
        return jsonify({
            'monitoring': True,
            'files_processed': st['files_processed'],
            'files_failed': st['files_failed'],
            'failed_files': st['failed_files'],
            'last_file': os.path.basename(last) if last else None,
            'last_file_full_path': last,
        })

    processed_files_path = os.path.join(nanocas_path, 'processed_files.txt')
    lines: list[str] = []
    if os.path.exists(processed_files_path):
        try:
            with open(processed_files_path, 'r') as f:
                lines = [line.strip() for line in f if line.strip()]
        except OSError as e:
            logger.warning(f"Could not read {processed_files_path}: {e}")
            return jsonify({'error': 'Could not read processed_files.txt'}), 500
    failed: dict = {}
    failed_path = os.path.join(nanocas_path, 'failed_files.json')
    if os.path.exists(failed_path):
        try:
            with open(failed_path) as f:
                failed = json.load(f)
        except (OSError, json.JSONDecodeError):
            failed = {}
    last = lines[-1] if lines else None
    return jsonify({
        'monitoring': False,
        'files_processed': len(lines),
        'files_failed': len(failed),
        'failed_files': failed,
        'last_file': os.path.basename(last) if last else None,
        'last_file_full_path': last,
    })


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@main.route('/get_alerts', methods=['GET'])
def get_alerts():
    project_id = request.args.get('projectId')
    nanocas_path = _validated_project_path(project_id)
    try:
        limit = max(1, min(int(request.args.get('limit', 200)), 2000))
    except ValueError:
        limit = 200
    log = AlertLog(nanocas_path)
    alerts = log.read(limit=limit)
    cfg = project_store.load_config(project_id) or {}
    listener = _listener_for(project_id)
    rules = listener['monitor'].rules.status() if listener and listener.get('monitor') else []
    return jsonify({
        'alerts': alerts,
        'total': log.count(),
        'channels': Notifier(cfg).channels(),
        'rules': rules,
        'monitoring': bool(listener),
    })


@main.route('/test_notification', methods=['POST'])
def test_notification():
    """Send a test message through every configured channel.

    Body (JSON): either ``{"projectId": ...}`` to use a saved project's
    configuration, or ``{"device": ..., "alertNotifConfig": {...}}`` to
    test a configuration from the wizard before the project exists.
    """
    body = request.json or {}
    if body.get('projectId'):
        _validated_project_path(body['projectId'])
        cfg = project_store.load_config(body['projectId']) or {}
        # The browser only ever sees a redacted password; allow the caller
        # to supply the real one but fall back to the stored value.
        supplied = ((body.get('alertNotifConfig') or {}).get('emailConfig') or {}).get('password')
        if supplied and supplied != '********':
            cfg.setdefault('alertNotifConfig', {}).setdefault('emailConfig', {})['password'] = supplied
    else:
        cfg = {'device': body.get('device', ''), 'alertNotifConfig': body.get('alertNotifConfig') or {}}
    notifier = Notifier(cfg, desktop=bool(body.get('desktop', True)))
    channels = notifier.channels()
    if not channels:
        return jsonify({'error': 'No notification channels are enabled for this configuration',
                        'results': {}}), 400
    results = notifier.send_test()
    ok = any(v == 'sent' for v in results.values())
    return jsonify({'ok': ok, 'results': results, 'channels': channels}), (200 if ok else 502)
