import json
import logging
import os
import gzip
import tempfile
import uuid
import subprocess
import glob
import pysam

from typing import NoReturn

from flask import request, abort, jsonify, make_response
from werkzeug.utils import secure_filename
from . import main
from .utils import LinuxNotification
from .utils.directory_scanner import scan_directory, parse_summary_combined

try:
    from eventlet import tpool
except ImportError:
    tpool = None

logger = logging.getLogger('nanocas')

NANOCAS_DIR = os.path.join(os.path.expanduser('~'), '.nanocas')
CACHE_PATH = os.path.join(os.path.expanduser('~'), '.nanocas/.cache')

# Cache of parsed sequencing-summary results, keyed by absolute file path.
# Entry: {'size': int, 'mtime_ns': int, 'data': dict}. Invalidated whenever
# the file's size or mtime changes — so a live, growing summary file will
# still re-parse, but back-to-back polls within the same write window reuse
# the result and avoid burning seconds of CSV parsing.
_RUN_HEALTH_CACHE: dict[str, dict] = {}

@main.route('/version', methods=['GET'])
def version():
    return json.dumps({"version": "v0.0.2", "name": "nanocas PoC"})

@main.route('/check_database_status', methods=['GET'])
def check_database_status():
    nanocas_path = _validated_project_path(request.args.get('projectId'))
    mmi_files = glob.glob(os.path.join(nanocas_path, 'database', '*.mmi'))
    is_ready = len(mmi_files) > 0
    return jsonify({'is_ready': is_ready})

def get_nanocas_cache_path():
    return os.path.join(NANOCAS_DIR, '.cache')

def write_to_cache(uid, minION_location, uid_dir):
    entry = f"{uid}\t{minION_location}\t{uid_dir}\n"
    with open(get_nanocas_cache_path(), 'a+') as cache_fs:
        cache_fs.write(entry)

@main.route('/get_uid', methods=["POST"])
def get_uid():
    minION_location = request.form.get('minION')
    if not minION_location:
        abort(400, description="minION location not provided.")

    cache_path = get_nanocas_cache_path()
    uid = str(uuid.uuid4())

    if os.path.exists(cache_path):
        with open(cache_path, 'r') as cache_fs:
            lines = cache_fs.readlines()
            for line in lines:
                parts = line.strip().split('\t')
                if len(parts) >= 2 and parts[1] == minION_location:
                    return jsonify({'uid': parts[0]})  # Return existing UID

    uid_dir = os.path.join(NANOCAS_DIR, uid)
    write_to_cache(uid, minION_location, uid_dir)

    return jsonify({'uid': uid})

@main.route('/get_all_analyses', methods=['GET'])
def get_all_analyses():
    if request.method == "GET":
        data = []
        validate_cache()
        with open(CACHE_PATH, 'r') as cache_fs:
            for line in cache_fs:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                projectId, minion_dir, nanocas_dir = parts[0], parts[1], parts[2]
                data.append({
                    "id"         : projectId,
                    "minion_dir" : minion_dir,
                    "nanocas_dir": nanocas_dir,
                })

        return json.dumps({
            'status': 200,
            'data'  : data
        })

@main.route('/delete_analyses', methods=['POST'])
def delete_analyses():
    if request.method == "GET":
        return "Unexpected request method. Expected a GET request."

    # Get Post Data
    uid = request.form['uid']
    found = False
    with open(CACHE_PATH, 'r+') as cache_fs:
        filtered_lines = []
        for line in cache_fs:
            if uid not in line:
                filtered_lines.append(line)
            else:
                logger.debug(f"Debug: Removed id {uid} from cache")
                found = True
        cache_fs.seek(0)
        cache_fs.write("".join(filtered_lines))
        cache_fs.truncate()

    # delete the nanocas directory for the uid
    uid_dir = os.path.join(os.path.expanduser('~'), '.nanocas/' + uid)
    if os.path.exists(uid_dir):
        subprocess.call(['rm', '-rf', uid_dir])
    
    return json.dumps({
        'status': 200,
        'found' : found
    })

@main.route('/get_analysis_info', methods=['GET'])
def get_analysis_info():
    if request.method == 'GET':
        uid = request.args.get('uid')

        # get minion and nanocas location
        nanocas_path = ""
        validate_cache()
        with open(CACHE_PATH, 'r') as cache_fs:
            found = False
            for line in cache_fs:
                entry = line.split("\t")
                entry_id = entry[0]
                entry_nanocas_path = entry[2].rstrip()
                if uid == entry_id:
                    nanocas_path = entry_nanocas_path
                    found = True
                    break

        if not found:
            return json.dumps({'status': 404, 'message': "Couldn't find the analysis data with UID: " + str(uid)})
        else:
            alert_cfg_file = os.path.join(nanocas_path, 'alertinfo.cfg')
            alert_cfg_obj = json.load(open(alert_cfg_file))

            return json.dumps({
                'status': 200,
                'data'  : alert_cfg_obj
            })

    else:
        return "Unexpected request method. Expected a GET request."

@main.route('/get_default_nanopore_path', methods=['GET'])
def get_default_nanopore_path():
    default_path = os.path.join(NANOCAS_DIR, 'nanopore_data')
    os.makedirs(default_path, exist_ok=True)
    return jsonify({'path': default_path})

FASTA_EXTENSIONS = ('.fasta', '.fa', '.fna', '.fasta.gz', '.fa.gz', '.fna.gz')

@main.route('/upload_reference', methods=['POST'])
def upload_reference():
    """Upload a reference genome (FASTA) to the nanopore data directory."""
    target_dir = request.form.get('target_dir', '')
    if not target_dir:
        target_dir = os.path.join(NANOCAS_DIR, 'nanopore_data')
    os.makedirs(target_dir, exist_ok=True)
    uploaded = []
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files provided'}), 400
    for file in files:
        if not file.filename or not file.filename.lower().endswith(FASTA_EXTENSIONS):
            logger.warning(f"Skipped non-FASTA file: {file.filename}")
            continue
        # `secure_filename` strips path components AND dangerous chars
        # (slashes, control chars, unicode tricks). The previous
        # `os.path.basename` only stripped slashes. Returns '' for inputs
        # like '..' or '.', so we re-check before saving.
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

@main.route('/validate_locations', methods=['POST', 'GET'])
def validate_locations():
    if (request.method == 'POST'):
        minION_location = request.form['minION']
        nanocas_location = os.path.join(os.path.expanduser('~'), '.nanocas/')

        logger.debug("minION_location = " + minION_location)

        # Auto-create nanocas working directory if it doesn't exist
        os.makedirs(nanocas_location, exist_ok=True)
        os.chmod(nanocas_location, mode=0o755)

        # Auto-create the minION data directory if it doesn't exist.
        # This allows the app to work in any environment (Replit, cloud, local)
        # without requiring the user to manually pre-create directories.
        if not os.path.exists(minION_location):
            try:
                os.makedirs(minION_location, exist_ok=True)
                logger.info(f"Auto-created minION directory: {minION_location}")
            except Exception as e:
                logger.error(f"Could not create minION directory {minION_location}: {e}")
                return json.dumps({"code": 1, "message": f"Cannot create minION directory: {e}"})

        return json.dumps({"code": 0, "message": "SUCCESS"})
    else:
        return "N/A"

@main.route('/get_coverage', methods=['GET'])
def get_coverage():
    nanocas_path = _validated_project_path(request.args.get('projectId'))
    coverage_file = os.path.join(nanocas_path, 'coverage.csv')
    if not os.path.exists(coverage_file):
        return jsonify({'error': 'Coverage file not found'}), 404

    alert_cfg_file = os.path.join(nanocas_path, 'alertinfo.cfg')
    try:
        with open(alert_cfg_file, 'r') as f:
            alert_cfg = json.load(f)
        ref_to_name = {q['header']: q['name'] for q in alert_cfg['queries']}
    except Exception as e:
        logger.error(f"Error loading alert config: {e}")
        ref_to_name = {}

    try:
        with open(coverage_file, 'r') as f:
            lines = f.readlines()[1:]  # Skip header
        data = []
        for line in lines:
            timestamp, ref, depth, breadth, read_count = line.strip().split(',')
            name = ref_to_name.get(ref, ref)  # Map reference to alert sequence name
            data.append({
                'timestamp': timestamp,
                'reference': name,
                'depth': float(depth),
                'breadth': float(breadth),
                'read_count': int(read_count)
            })
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error reading coverage file: {e}")
        return jsonify({'error': 'Error processing coverage data'}), 500

@main.route('/index_devices', methods=['GET'])
def index_devices():
    if request.method == 'GET':
        devices = []
        indexed_devices = LinuxNotification.index_devices()
        if indexed_devices:
            for device in indexed_devices:
                if device.state not in ["STATE_HARDWARE_REMOVED", "STATE_HARDWARE_ERROR", "STATE_SOFTWARE_ERROR"]:
                    devices.append(device.name)
                    LinuxNotification.send_notification(device.name, "Device discovered by nanocas", severity=1)
        # Always return a valid JSON response
        return json.dumps(devices)
    # Explicitly return an empty list if not GET (should not happen)
    return json.dumps([])

def _save_uploaded_file(label: str):
    """Common path for /upload_fasta and /upload_gff.

    `tempfile.mkdtemp(dir=NANOCAS_DIR)` already guarantees the *parent*
    directory is inside NANOCAS_DIR, but the previous code joined the
    raw `file.filename` underneath it — meaning a malicious filename
    like `../../etc/passwd` would have escaped that random temp dir.
    `secure_filename` strips path components and dangerous chars. See
    LOGBOOK §4.8.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    safe_name = secure_filename(file.filename)
    if not safe_name:
        return jsonify({'error': 'Invalid filename'}), 400
    temp_dir = tempfile.mkdtemp(dir=NANOCAS_DIR)
    file_path = os.path.join(temp_dir, safe_name)
    file.save(file_path)
    logger.debug(f"Uploaded {label} file to {file_path}")
    return jsonify({'file_path': file_path})


@main.route('/upload_fasta', methods=['POST'])
def upload_fasta():
    return _save_uploaded_file('FASTA')


@main.route('/upload_gff', methods=['POST'])
def upload_gff():
    return _save_uploaded_file('GFF')

@main.route('/parse_fasta_headers', methods=['POST'])
def parse_fasta_headers():
    data = request.json
    file_path = data.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'Invalid file path'}), 400
    headers = []
    try:
        if file_path.endswith('.gz'):
            with gzip.open(file_path, 'rt') as f:
                for line in f:
                    if line.startswith('>'):
                        headers.append(line[1:].strip())
        else:
            with open(file_path, 'r') as f:
                for line in f:
                    if line.startswith('>'):
                        headers.append(line[1:].strip())
        logger.debug(f"Parsed {len(headers)} headers from {file_path}")
        return jsonify(headers)
    except Exception as e:
        logger.error(f"Error parsing FASTA headers: {e}")
        return jsonify({'error': str(e)}), 500

def parse_gff(gff_path, sequence_id):
    regions = []
    try:
        with open(gff_path, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    fields = line.strip().split('\t')
                    if len(fields) >= 5 and fields[0] == sequence_id:
                        start = int(fields[3])
                        end = int(fields[4])
                        attributes = fields[8] if len(fields) > 8 else ""
                        region_id = None
                        for attr in attributes.split(';'):
                            if attr.startswith('ID='):
                                region_id = attr[3:]
                                break
                        regions.append({'start': start, 'end': end, 'id': region_id})
    except Exception as e:
        logger.error(f"Error parsing GFF file {gff_path}: {e}")
    return regions

def _ensure_merged_bam(nanocas_path: str) -> str | None:
    """Build (or refresh) `<nanocas_path>/merged.bam` from the per-FASTQ
    sorted BAMs under `minimap2/runs/`, returning the merged path on
    success or None if there's nothing to merge yet.

    Since LOGBOOK section 4.1 the per-FASTQ BAMs are kept on disk
    instead of being merged-and-deleted on every batch, so the merge
    cost is paid only when the user opens the alignment viewer rather
    than on every single FASTQ. Cached against `merge_manifest.json`:
    if the set of input BAMs hasn't changed since the last merge, the
    existing `merged.bam` is reused.

    The `legacy_pre_v9.bam` input (renamed from the old cumulative
    merged.bam during one-shot migration) is included alongside the
    new per-FASTQ BAMs so historical alignments don't disappear from
    the viewer after upgrade.

    Safety against partial writes: samtools sort writes its output via
    a temp file + atomic rename, so a glob of `*_sorted.bam` only ever
    sees fully-written, sorted BAMs. We don't need an external lock.
    """
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
        except Exception as e:
            logger.warning(f"Could not read merge manifest {manifest_path}: {e}")
    if cached_inputs == inputs and os.path.exists(merged_bam) and os.path.exists(merged_bam + '.bai'):
        return merged_bam

    try:
        subprocess.run(['samtools', 'merge', '-f', merged_bam, *inputs], check=True)
        subprocess.run(['samtools', 'index', merged_bam], check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"samtools merge/index failed for {nanocas_path}: {e}")
        return None

    try:
        with open(manifest_path, 'w') as f:
            json.dump({'inputs': inputs}, f)
    except Exception as e:
        logger.warning(f"Could not write merge manifest {manifest_path}: {e}")

    return merged_bam


@main.route('/get_alignments', methods=['GET'])
def get_alignments():
    nanocas_path = _validated_project_path(request.args.get('projectId'))
    reference = request.args.get('reference')
    if not reference:
        return jsonify({'error': 'reference is required'}), 400

    # The merged BAM is built lazily — paying the merge cost here means
    # the per-FASTQ hot path stays O(reads in this batch).
    merged_bam = _ensure_merged_bam(nanocas_path)
    if not merged_bam:
        return jsonify({'error': 'No alignments available yet'}), 404

    try:
        with pysam.AlignmentFile(merged_bam, "rb") as bam:
            if reference not in bam.references:
                return jsonify({'error': 'Reference not found in BAM file'}), 404
            ref_length = bam.lengths[bam.references.index(reference)]
            alignments = []
            for alignment in bam.fetch(reference):
                if not alignment.is_unmapped:
                    alignments.append({
                        'start': alignment.reference_start,
                        'end': alignment.reference_end,
                        'strand': '-' if alignment.is_reverse else '+',
                    })

        # Load and parse GFF file if present
        alert_cfg_file = os.path.join(nanocas_path, 'alertinfo.cfg')
        regions = []
        with open(alert_cfg_file, 'r') as f:
            alert_cfg = json.load(f)
            gff_file = alert_cfg.get('gff_file')
            if gff_file and os.path.exists(gff_file):
                regions = parse_gff(gff_file, reference)
                for region in regions:
                    count = sum(1 for aln in alignments if aln['start'] < region['end'] and aln['end'] > region['start'])
                    region['read_count'] = count

        return jsonify({'ref_length': ref_length, 'alignments': alignments, 'regions': regions})
    except Exception as e:
        logger.error(f"Error getting alignments: {e}", exc_info=True)
        return jsonify({'error': 'Error processing BAM file'}), 500

def validate_cache(cache_path=CACHE_PATH):
    if not os.path.isfile(cache_path):
        if not os.path.isdir(NANOCAS_DIR):
            os.mkdir(NANOCAS_DIR)
        open(CACHE_PATH, 'a').close()
        logger.warning(f"No cache found! Generated empty cache file...")
    pass


def _is_safe_path(base_dir, target_path):
    real_base = os.path.realpath(base_dir)
    real_target = os.path.realpath(target_path)
    return real_target.startswith(real_base + os.sep) or real_target == real_base


def _abort_json(status: int, message: str) -> NoReturn:
    """Abort the request with a JSON-formatted error body.

    Flask's default `abort(400)` returns HTML, which forces every caller
    to either build the response by hand or live with a content-type
    mismatch. This helper wraps abort() with a jsonify'd response so
    every error route returns the same `{"error": "..."}` shape.
    """
    abort(make_response(jsonify({'error': message}), status))


def _validated_project_path(project_id: str | None) -> str:
    """Validate a `projectId` query parameter and return the absolute
    on-disk project directory.

    Aborts the request with a JSON error response if the project id is
    missing, contains traversal sequences, escapes NANOCAS_DIR, or
    doesn't exist on disk. Three previously-vulnerable endpoints
    (`/check_database_status`, `/get_coverage`, `/get_alignments`)
    accepted `projectId` straight off the wire and joined it into a path
    without guards — see LOGBOOK §4.8.

    The redundant explicit `os.sep` / `..` checks are intentional
    defence-in-depth: `_is_safe_path` would catch them via realpath, but
    the cheap string check rejects the obvious cases without touching
    the filesystem at all.
    """
    if not project_id:
        _abort_json(400, 'projectId is required')
    if os.sep in project_id or '..' in project_id:
        _abort_json(400, 'Invalid project ID')
    nanocas_path = os.path.join(NANOCAS_DIR, project_id)
    if not _is_safe_path(NANOCAS_DIR, nanocas_path):
        _abort_json(400, 'Invalid project ID')
    if not os.path.isdir(nanocas_path):
        _abort_json(404, 'Project not found')
    return nanocas_path


@main.route('/scan_directory', methods=['POST'])
def scan_dir_endpoint():
    data = request.json
    directory = data.get('directory', '')
    if not directory:
        return jsonify({'error': 'directory is required'}), 400
    home_dir = os.path.expanduser('~')
    real_dir = os.path.realpath(directory)
    if not real_dir.startswith(home_dir):
        return jsonify({'error': 'Access denied: directory must be within home directory'}), 403
    result = scan_directory(real_dir)
    return jsonify(result)


@main.route('/run_health', methods=['GET'])
def run_health():
    nanocas_path = _validated_project_path(request.args.get('projectId'))

    alert_cfg_path = os.path.join(nanocas_path, 'alertinfo.cfg')
    minion_dir = None
    try:
        with open(alert_cfg_path, 'r') as f:
            cfg = json.load(f)
            minion_dir = cfg.get('minion', '')
    except Exception:
        pass

    summary_path = None
    search_dirs = [nanocas_path]
    if minion_dir and os.path.isdir(minion_dir):
        search_dirs.append(minion_dir)
        parent = os.path.dirname(minion_dir.rstrip('/'))
        if parent and os.path.isdir(parent):
            search_dirs.append(parent)

    for search_dir in search_dirs:
        for root, dirs, files in os.walk(search_dir):
            for fname in files:
                if 'sequencing_summary' in fname.lower() and (fname.endswith('.txt') or fname.endswith('.csv')):
                    summary_path = os.path.join(root, fname)
                    break
            if summary_path:
                break
        if summary_path:
            break

    if not summary_path:
        return jsonify({'error': 'No sequencing summary file found'}), 404

    try:
        st = os.stat(summary_path)
    except OSError as e:
        logger.warning(f"Could not stat sequencing summary {summary_path}: {e}")
        return jsonify({'error': 'Could not access sequencing summary file'}), 500

    cached = _RUN_HEALTH_CACHE.get(summary_path)
    if cached and cached['size'] == st.st_size and cached['mtime_ns'] == st.st_mtime_ns:
        return jsonify(cached['data'])

    # The parser is CPU + disk bound. Without tpool, parsing a multi-GB
    # sequencing_summary blocks the eventlet hub for the full duration of
    # the read — meaning every other request (including the socket.io
    # polling that keeps the Coverage chart live) stalls. tpool runs the
    # function on a native thread and yields the greenlet, so concurrent
    # requests keep flowing.
    if tpool is not None:
        data = tpool.execute(parse_summary_combined, summary_path)
    else:
        data = parse_summary_combined(summary_path)

    _RUN_HEALTH_CACHE[summary_path] = {
        'size': st.st_size,
        'mtime_ns': st.st_mtime_ns,
        'data': data,
    }

    return jsonify(data)


@main.route('/get_processing_status', methods=['GET'])
def get_processing_status():
    """Return how many input files (FASTQ/BAM) have been processed for this
    project and the most-recent filename.

    The source of truth is `processed_files.txt` (one absolute path per
    line), which `FileHandler._record_processed` appends to. Live updates
    arrive via the `file_progress_update` socket event; this endpoint exists
    so the frontend can hydrate the indicator on first mount.
    """
    nanocas_path = _validated_project_path(request.args.get('projectId'))

    processed_files_path = os.path.join(nanocas_path, 'processed_files.txt')
    if not os.path.exists(processed_files_path):
        return jsonify({
            'files_processed': 0,
            'last_file': None,
            'last_file_full_path': None,
        })

    try:
        with open(processed_files_path, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
    except OSError as e:
        logger.warning(f"Could not read {processed_files_path}: {e}")
        return jsonify({'error': 'Could not read processed_files.txt'}), 500

    last = lines[-1] if lines else None
    return jsonify({
        'files_processed': len(lines),
        'last_file': os.path.basename(last) if last else None,
        'last_file_full_path': last,
    })