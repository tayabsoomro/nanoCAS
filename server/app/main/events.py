from flask import session
from flask_socketio import emit
from .. import socketio

from threading import Thread

import os
import shutil
import subprocess
from time import sleep

from .utils.FileHandler import FileHandler
from .utils.tasks import int_download_database
from .utils import LinuxNotification
from .utils.directory_scanner import parse_sequencing_summary, get_pore_health

from watchdog.observers import Observer

import json
import logging

logger = logging.getLogger('nanocas')

# Global dictionary to store observers by project ID
observers = {}


# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def run_fastq_watcher(app_loc, minion_loc):
    logger.debug(f"Starting file watcher on {app_loc}")
    event_handler = FileHandler(app_loc)
    observer = Observer()
    observer.schedule(event_handler, path=minion_loc, recursive=False)
    observer.start()
    try:
        while True:
            sleep(1)
    except Exception:
        observer.stop()


# ---------------------------------------------------------------------------
# SOCKET EVENTS
# ---------------------------------------------------------------------------

@socketio.on('connect', namespace="/analysis")
def analysis_connected():
    logger.debug("Unused analysis connection made.")


@socketio.on('disconnect', namespace="/analysis")
def analysis_disconnected():
    nanocas_loc = session.get('nanocas_location', '')
    if nanocas_loc:
        busy_file = os.path.join(nanocas_loc, 'analysis_busy')
        try:
            os.remove(busy_file)
        except FileNotFoundError:
            pass
    logger.debug("Disconnect from analysis connection.")


@socketio.on('remove_analysis')
def remove_analysis(data):
    project_id = data['projectId']
    nanocas_location = os.path.join(os.path.expanduser('~'), '.nanocas', project_id)

    if os.path.exists(nanocas_location):
        shutil.rmtree(nanocas_location)
        cache_path = os.path.join(os.path.expanduser('~'), '.nanocas', '.cache')
        if os.path.exists(cache_path):
            with open(cache_path, 'r+') as cache_fs:
                lines = cache_fs.readlines()
                cache_fs.seek(0)
                for line in lines:
                    if project_id not in line:
                        cache_fs.write(line)
                cache_fs.truncate()
        emit('analysis_removed', {'success': True, 'message': 'Analysis removed successfully'})
    else:
        emit('analysis_removed', {'success': False, 'message': 'Analysis not found'})


@socketio.on('start_fastq_file_listener')
def start_fastq_file_listener(data):
    project_id = data['projectId']
    nanocas_location = os.path.join(os.path.expanduser('~'), '.nanocas', project_id) + os.sep
    minion_location = data['minion_location']

    if project_id not in observers:
        try:
            event_handler = FileHandler(nanocas_location)
            thread = Thread(target=event_handler.process_existing_files, args=(minion_location,))
            thread.daemon = True
            thread.start()
            observer = Observer()
            observer.schedule(event_handler, path=minion_location, recursive=False)
            observer.start()
            observers[project_id] = observer
            emit('fastq_file_listener_started', {'projectId': project_id})
            logger.debug(f"Started file listener for project {project_id}")
        except Exception as e:
            emit('fastq_file_listener_error', {'projectId': project_id, 'error': str(e)})
            logger.error(f"Error starting file listener for project {project_id}: {e}")
    else:
        emit('fastq_file_listener_already_running', {'projectId': project_id})


@socketio.on('stop_fastq_file_listener')
def stop_fastq_file_listener(data):
    project_id = data['projectId']
    if project_id in observers:
        try:
            observer = observers[project_id]
            observer.stop()
            observer.join()
            del observers[project_id]
            emit('fastq_file_listener_stopped', {'projectId': project_id})
        except Exception as e:
            emit('fastq_file_listener_error', {'projectId': project_id, 'error': str(e)})
    else:
        emit('fastq_file_listener_not_running', {'projectId': project_id})


@socketio.on('check_fastq_file_listener')
def check_fastq_file_listener(data):
    project_id = data['projectId']
    is_running = project_id in observers
    emit('fastq_file_listener_status', {'projectId': project_id, 'is_running': is_running})


# ---------------------------------------------------------------------------
# DATABASE CREATION — runs in a background thread to avoid blocking the
# socket event loop.  Progress is reported via socketio.emit so the client
# receives live updates without needing Celery or Redis.
# ---------------------------------------------------------------------------

def _build_database_task(dbinfo, nanocas_location, queries, sid):
    """Background thread: build the minimap2 index and emit progress to the client."""

    def progress_callback(percent, message):
        socketio.emit(
            'download_database_status',
            {'percent_done': percent, 'status_message': message},
            to=sid
        )

    try:
        result = int_download_database(
            db_data=dbinfo,
            nanocas_location=nanocas_location,
            queries=queries,
            progress_callback=progress_callback,
        )

        if isinstance(result, dict):
            logger.info(f"Database built for project {dbinfo.get('projectId')}")
            socketio.emit(
                'download_database_complete',
                {'success': True, 'projectId': dbinfo.get('projectId')},
                to=sid
            )
        else:
            error_code = result or 'UNKNOWN'
            logger.error(f"Database build failed with code: {error_code}")
            socketio.emit(
                'download_database_complete',
                {'success': False, 'error': error_code, 'projectId': dbinfo.get('projectId')},
                to=sid
            )
    except Exception as e:
        logger.error(f"Unhandled error during database build: {e}", exc_info=True)
        socketio.emit(
            'download_database_complete',
            {'success': False, 'error': str(e), 'projectId': dbinfo.get('projectId')},
            to=sid
        )


@socketio.on('download_database', namespace="/")
def download_database(dbinfo):
    from flask import request as flask_request
    sid = flask_request.sid

    project_id = dbinfo.get("projectId")
    if not project_id:
        emit('download_database_complete', {'success': False, 'error': 'Missing projectId'})
        return

    device = dbinfo.get("device", "")
    file_type = dbinfo.get("fileType", "FASTQ")
    nanocas_location = os.path.join(os.path.expanduser('~'), '.nanocas', project_id) + os.sep

    # (Re)create the project directory
    if os.path.exists(nanocas_location):
        shutil.rmtree(nanocas_location)
    os.makedirs(nanocas_location, exist_ok=True)

    # Move the GFF file from the temp upload directory into the project dir
    gff_file_temp = dbinfo.get("gff_file")
    if gff_file_temp and os.path.exists(gff_file_temp):
        gff_file_final = os.path.join(nanocas_location, 'gff_file.gff')
        shutil.move(gff_file_temp, gff_file_final)
        dbinfo["gff_file"] = gff_file_final
        logger.debug(f"Moved GFF file → {gff_file_final}")
        # Clean up temp dir
        temp_dir = os.path.dirname(gff_file_temp)
        try:
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Could not remove GFF temp dir {temp_dir}: {e}")
    elif gff_file_temp:
        logger.warning(f"GFF file {gff_file_temp} not found; skipping.")

    dbinfo["fileType"] = file_type

    # Write alertinfo.cfg immediately so the background task can read it
    alertinfo_path = os.path.join(nanocas_location, 'alertinfo.cfg')
    with open(alertinfo_path, 'w') as f:
        json.dump(dbinfo, f)
    logger.debug(f"Wrote alertinfo.cfg for project {project_id}")

    # Notify the device if one is configured
    if device:
        try:
            alert_str = (
                f"nanoCAS database is being built for project {project_id}. "
                f"You can view the analysis at /analysis/{project_id}"
            )
            LinuxNotification.send_notification(device, alert_str, severity=1)
        except Exception as e:
            logger.warning(f"Device notification failed: {e}")

    # Create required subdirectories
    os.makedirs(os.path.join(nanocas_location, 'database'), mode=0o777, exist_ok=True)
    os.makedirs(os.path.join(nanocas_location, 'minimap2', 'runs'), mode=0o777, exist_ok=True)

    queries = dbinfo.get("queries", [])

    # Acknowledge immediately so the client knows the build has started
    emit('download_database_status', {'percent_done': 0, 'status_message': 'Starting database build…'})

    # Run the heavy work in a background thread
    thread = Thread(
        target=_build_database_task,
        args=(dbinfo, nanocas_location, queries, sid),
        daemon=True,
    )
    thread.start()
    logger.debug(f"Database build thread started for project {project_id}")


# ---------------------------------------------------------------------------
# LOGGER HOOKS
# ---------------------------------------------------------------------------

@socketio.on('log')
def log(msg, lvl):
    lvl_upper = str(lvl).upper()
    if lvl_upper == "INFO":
        logger.info(msg)
    elif lvl_upper == "DEBUG":
        logger.debug(msg)
    elif lvl_upper == "WARNING":
        logger.warning(msg)
    elif lvl_upper == "ERROR":
        logger.error(msg)
    elif lvl_upper == "CRITICAL":
        logger.critical(msg)
