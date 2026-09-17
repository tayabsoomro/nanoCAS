"""Socket.IO event handlers + the per-project listener registry.

A *listener* is the bundle of live objects that exist while a project is
being monitored: the watchdog ``Observer`` on the sequencer output
directory, the ``FileHandler`` that processes each new batch, and the
``RunHealthMonitor`` thread that evaluates instrument-level rules.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading

from flask import request as flask_request
from flask_socketio import emit
from watchdog.observers import Observer

from .. import socketio
from .utils import project_store
from .utils.FileHandler import FileHandler
from .utils.LinuxNotification import LinuxNotification
from .utils.alerts import SEVERITY_INFO, SOURCE_SYSTEM, AlertLog, Notifier, emit_alert
from .utils.gff import regions_from_selection
from .utils.run_health import RunHealthMonitor, normalise_config
from .utils.tasks import int_download_database

logger = logging.getLogger('nanocas')

# project_id -> {'observer': Observer, 'handler': FileHandler, 'monitor': RunHealthMonitor}
_listeners: dict[str, dict] = {}
_listeners_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Listener registry (also used by routes.py)
# ---------------------------------------------------------------------------

def get_listener(project_id: str) -> dict | None:
    with _listeners_lock:
        return _listeners.get(project_id)


def list_running() -> list[str]:
    with _listeners_lock:
        return list(_listeners.keys())


def start_listener(project_id: str, minion_location: str) -> dict:
    """Create and start the observer + monitor for ``project_id``. Raises
    on any failure (caller reports it to the client)."""
    project_dir = project_store.project_dir(project_id)
    if not os.path.isdir(project_dir):
        raise FileNotFoundError(f'Project {project_id} does not exist')
    if not minion_location:
        raise ValueError('minion_location is required')
    os.makedirs(minion_location, exist_ok=True)

    with _listeners_lock:
        if project_id in _listeners:
            return _listeners[project_id]

        handler = FileHandler(project_dir + os.sep)
        cfg = handler.config
        observer = Observer()
        observer.schedule(handler, path=minion_location, recursive=False)
        observer.start()

        monitor = RunHealthMonitor(
            project_id, project_dir, minion_location,
            cfg.get('runHealthConfig') or {},
            alert_log=handler.alert_log, notifier=handler.notifier,
            device=cfg.get('device') or None, file_handler=handler,
        )
        monitor.start()

        catchup = threading.Thread(target=handler.process_existing_files, args=(minion_location,),
                                   daemon=True, name=f'nanocas-catchup-{project_id[:8]}')
        catchup.start()

        bundle = {'observer': observer, 'handler': handler, 'monitor': monitor, 'catchup': catchup,
                  'minion_location': minion_location}
        _listeners[project_id] = bundle

    record = handler.alert_log.append('monitoring_started', SEVERITY_INFO,
                                      f'Monitoring started on {minion_location}',
                                      source=SOURCE_SYSTEM, project_id=project_id)
    emit_alert(record)
    logger.info(f"Started file listener for project {project_id} on {minion_location}")
    return bundle


def stop_listener(project_id: str) -> bool:
    with _listeners_lock:
        bundle = _listeners.pop(project_id, None)
    if not bundle:
        return False
    try:
        bundle['observer'].stop()
        bundle['observer'].join(timeout=10)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Observer for {project_id} did not stop cleanly: {exc}")
    try:
        bundle['monitor'].stop(join=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Monitor for {project_id} did not stop cleanly: {exc}")
    try:
        record = bundle['handler'].alert_log.append('monitoring_stopped', SEVERITY_INFO, 'Monitoring stopped',
                                                    source=SOURCE_SYSTEM, project_id=project_id)
        emit_alert(record)
    except Exception:  # noqa: BLE001
        pass
    logger.info(f"Stopped file listener for project {project_id}")
    return True


# ---------------------------------------------------------------------------
# Socket events
# ---------------------------------------------------------------------------

@socketio.on('remove_analysis')
def remove_analysis(data):
    project_id = (data or {}).get('projectId')
    if not project_store.is_valid_project_id(project_id):
        emit('analysis_removed', {'success': False, 'message': 'Invalid project id'})
        return
    stop_listener(project_id)
    try:
        found = project_store.delete_project(project_id)
    except ValueError:
        emit('analysis_removed', {'success': False, 'message': 'Invalid project id'})
        return
    if found:
        emit('analysis_removed', {'success': True, 'projectId': project_id, 'message': 'Analysis removed successfully'})
    else:
        emit('analysis_removed', {'success': False, 'projectId': project_id, 'message': 'Analysis not found'})


@socketio.on('start_fastq_file_listener')
def start_fastq_file_listener(data):
    project_id = (data or {}).get('projectId')
    minion_location = (data or {}).get('minion_location')
    if not project_store.is_valid_project_id(project_id):
        emit('fastq_file_listener_error', {'projectId': project_id, 'error': 'Invalid project id'})
        return
    if get_listener(project_id):
        emit('fastq_file_listener_already_running', {'projectId': project_id})
        return
    if not minion_location:
        cfg = project_store.load_config(project_id) or {}
        minion_location = cfg.get('minion')
    try:
        start_listener(project_id, minion_location)
        emit('fastq_file_listener_started', {'projectId': project_id})
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error starting file listener for project {project_id}: {e}", exc_info=True)
        emit('fastq_file_listener_error', {'projectId': project_id, 'error': str(e)})


@socketio.on('stop_fastq_file_listener')
def stop_fastq_file_listener(data):
    project_id = (data or {}).get('projectId')
    if stop_listener(project_id):
        emit('fastq_file_listener_stopped', {'projectId': project_id})
    else:
        emit('fastq_file_listener_not_running', {'projectId': project_id})


@socketio.on('check_fastq_file_listener')
def check_fastq_file_listener(data):
    project_id = (data or {}).get('projectId')
    emit('fastq_file_listener_status', {'projectId': project_id, 'is_running': get_listener(project_id) is not None})


@socketio.on('test_notification')
def test_notification_event(data):
    """Wizard-time notification test over the socket (mirrors the HTTP
    endpoint so the summary page can use whichever is convenient)."""
    cfg = {'device': (data or {}).get('device', ''), 'alertNotifConfig': (data or {}).get('alertNotifConfig') or {}}
    notifier = Notifier(cfg)
    results = notifier.send_test() if notifier.channels() else {}
    emit('test_notification_result', {'results': results, 'channels': notifier.channels()})


# ---------------------------------------------------------------------------
# Project creation / database build
# ---------------------------------------------------------------------------

def _build_database_task(dbinfo, nanocas_location, queries, sid):
    """Background thread: build the minimap2 index and emit progress to the client."""
    project_id = dbinfo.get('projectId')

    def progress_callback(percent, message):
        socketio.emit('download_database_status',
                      {'projectId': project_id, 'percent_done': percent, 'status_message': message}, to=sid)

    try:
        result = int_download_database(db_data=dbinfo, nanocas_location=nanocas_location,
                                       queries=queries, progress_callback=progress_callback)
        if isinstance(result, dict):
            logger.info(f"Database built for project {project_id}")
            AlertLog(nanocas_location).append('project_created', SEVERITY_INFO,
                                              'Project created and reference index built',
                                              source=SOURCE_SYSTEM, project_id=project_id)
            socketio.emit('download_database_complete', {'success': True, 'projectId': project_id}, to=sid)
        else:
            error_code = result or 'UNKNOWN'
            logger.error(f"Database build failed with code: {error_code}")
            if error_code.startswith('ER_INDEX:'):
                message = error_code.split(':', 1)[1]
            else:
                message = _ERROR_MESSAGES.get(error_code, error_code)
            socketio.emit('download_database_complete',
                          {'success': False, 'error': error_code, 'message': message, 'projectId': project_id}, to=sid)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Unhandled error during database build: {e}", exc_info=True)
        socketio.emit('download_database_complete',
                      {'success': False, 'error': str(e), 'message': str(e), 'projectId': project_id}, to=sid)


_ERROR_MESSAGES = {
    'ER_ALERTINFO': 'The project configuration could not be read.',
    'ER_INPUTFILE': 'The uploaded FASTA files could not be combined.',
    'ER_NO_SEQUENCES': 'None of the selected sequences were found in the uploaded FASTA files.',
    'ER_ALERTINFO_WRITE': 'The project configuration could not be saved.',
    'ER_MINIMAP2': 'minimap2 failed while building the index (see database/building_index.txt).',
    'ER_MINIMAP2_NOTFOUND': 'minimap2 is not installed or not on PATH.',
    'ER_MINIMAP2_UNKNOWN': 'Unexpected error while running minimap2.',
    'ER_COVERAGE': 'coverage.csv could not be initialised.',
    'ER_CLASSIFIER_UNKNOWN': 'The selected classifier is not installed as a plug-in on this server.',
    'ER_CLASSIFIER_UNAVAILABLE': 'The selected classifier\'s executable is not on PATH on this server.',
}


@socketio.on('download_database', namespace="/")
def download_database(dbinfo):
    sid = flask_request.sid
    dbinfo = dict(dbinfo or {})
    project_id = dbinfo.get("projectId")
    if not project_store.is_valid_project_id(project_id):
        emit('download_database_complete', {'success': False, 'error': 'Missing or invalid projectId',
                                            'message': 'Missing or invalid projectId'})
        return
    if not dbinfo.get('queries'):
        emit('download_database_complete', {'success': False, 'error': 'ER_NO_SEQUENCES',
                                            'message': 'At least one alert sequence is required.', 'projectId': project_id})
        return

    device = dbinfo.get("device", "") or ""
    dbinfo["fileType"] = (dbinfo.get("fileType") or "FASTQ").upper()
    dbinfo["device"] = device
    dbinfo["createdAt"] = project_store.now_iso()
    dbinfo["runHealthConfig"] = normalise_config(dbinfo.get("runHealthConfig"))
    classifier_cfg = dbinfo.get("classifier") or {}
    dbinfo["classifier"] = {'name': classifier_cfg.get('name') or 'minimap2',
                            'database': classifier_cfg.get('database') or None}
    region_selection = dbinfo.pop("regions", None)
    nanocas_location = project_store.project_dir(project_id) + os.sep

    # (Re)create the project directory. A running listener on this id
    # (only possible when re-creating) must be stopped first.
    stop_listener(project_id)
    if os.path.exists(nanocas_location):
        shutil.rmtree(nanocas_location)
    os.makedirs(nanocas_location, exist_ok=True)
    if not project_store.find_cache_entry(project_id):
        project_store.append_cache(project_id, dbinfo.get('minion', ''), nanocas_location.rstrip(os.sep))

    # Move the GFF file from the temp upload directory into the project dir
    gff_file_temp = dbinfo.get("gff_file")
    if gff_file_temp and os.path.exists(gff_file_temp):
        gff_file_final = os.path.join(nanocas_location, 'gff_file.gff')
        shutil.move(gff_file_temp, gff_file_final)
        dbinfo["gff_file"] = gff_file_final
        temp_dir = os.path.dirname(gff_file_temp)
        try:
            if os.path.isdir(temp_dir) and temp_dir != nanocas_location.rstrip(os.sep):
                shutil.rmtree(temp_dir)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not remove GFF temp dir {temp_dir}: {e}")
    elif gff_file_temp:
        logger.warning(f"GFF file {gff_file_temp} not found; skipping.")
        dbinfo["gff_file"] = None

    with open(os.path.join(nanocas_location, 'alertinfo.cfg'), 'w') as f:
        json.dump(dbinfo, f, indent=2)
    logger.debug(f"Wrote alertinfo.cfg for project {project_id}")

    # GFF features the user chose to alert on -> regions.json
    if region_selection:
        regions = regions_from_selection(region_selection)
        with open(os.path.join(nanocas_location, 'regions.json'), 'w') as f:
            json.dump(regions, f, indent=2)
        logger.debug(f"Wrote {sum(len(v) for v in regions.values())} alert region(s) for project {project_id}")

    if device:
        try:
            LinuxNotification.send_notification(
                device, f"nanoCAS project {dbinfo.get('projectName') or project_id} is being set up.", severity=1)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Device notification failed: {e}")

    os.makedirs(os.path.join(nanocas_location, 'database'), exist_ok=True)
    os.makedirs(os.path.join(nanocas_location, 'minimap2', 'runs'), exist_ok=True)

    emit('download_database_status', {'projectId': project_id, 'percent_done': 0,
                                      'status_message': 'Starting database build…'})
    socketio.start_background_task(_build_database_task, dbinfo, nanocas_location, dbinfo.get("queries", []), sid)
    logger.debug(f"Database build task started for project {project_id}")


# ---------------------------------------------------------------------------
# Logger hook
# ---------------------------------------------------------------------------

@socketio.on('log')
def log(msg, lvl='INFO'):
    level = getattr(logging, str(lvl).upper(), logging.INFO)
    logger.log(level, f"[client] {msg}")
