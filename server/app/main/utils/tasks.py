"""Project index build (runs in a background thread from events.py)."""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Callable, Optional

from .classifiers import DEFAULT_CLASSIFIER, get_classifier

logger = logging.getLogger('nanocas')

INDEX_MANIFEST = 'index.json'


def write_index_manifest(database_dir: str, classifier_name: str, index_path: str, targets: list[str]) -> str:
    os.makedirs(database_dir, exist_ok=True)
    manifest = os.path.join(database_dir, INDEX_MANIFEST)
    with open(manifest, 'w') as fh:
        json.dump({'classifier': classifier_name, 'index_path': index_path, 'targets': targets}, fh, indent=2)
    return manifest


def read_index_manifest(database_dir: str) -> dict | None:
    manifest = os.path.join(database_dir, INDEX_MANIFEST)
    if not os.path.exists(manifest):
        return None
    try:
        with open(manifest) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def int_download_database(db_data: dict, nanocas_location: str, queries: list,
                          progress_callback: Optional[Callable] = None):
    """Build the classifier index for a project.

    Returns a dict on success or an ``ER_*`` code string on failure (the
    socket handler maps codes to messages). ``db_data['classifier']`` is
    ``{'name': ..., 'database': ...}``; when absent minimap2 is used.
    """

    def update_progress(percent, message):
        logger.debug(f"Progress: {percent}% - {message}")
        if progress_callback:
            try:
                progress_callback(percent, message)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Progress callback failed: {e}")

    project_id = db_data.get('projectId')
    database_dir = os.path.join(nanocas_location, 'database')
    os.makedirs(database_dir, exist_ok=True)
    alertinfo_cfg_path = os.path.join(nanocas_location, 'alertinfo.cfg')

    classifier_cfg = db_data.get('classifier') or {}
    classifier_name = classifier_cfg.get('name') or DEFAULT_CLASSIFIER
    try:
        classifier = get_classifier(classifier_name)
    except ValueError as exc:
        logger.error(str(exc))
        return 'ER_CLASSIFIER_UNKNOWN'
    ok, reason = classifier.available()
    if not ok:
        logger.error(f'Classifier {classifier_name} unavailable: {reason}')
        return 'ER_CLASSIFIER_UNAVAILABLE'

    try:
        try:
            with open(alertinfo_cfg_path, 'r') as f:
                alertinfo_cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load alertinfo.cfg: {e}")
            return "ER_ALERTINFO"

        update_progress(5, "Preparing references…")
        headers: list[str] = []
        for query in queries:
            headers.extend(h for h in (query.get('headers') or []) if h)
            if query.get('header') and query['header'] not in headers:
                headers.append(query['header'])

        if classifier.reference_input == 'database':
            references = [classifier_cfg.get('database') or '']
        else:
            references = []
            for query in queries:
                path = query.get('file', '')
                if path and path not in references:
                    references.append(path)
            if not references:
                logger.error("No reference FASTA files supplied")
                return "ER_NO_SEQUENCES"

        try:
            index_path = classifier.build_index(references, headers, database_dir, progress=update_progress)
        except RuntimeError as exc:
            logger.error(f"Index build failed: {exc}")
            alertinfo_cfg['indexError'] = str(exc)
            with open(alertinfo_cfg_path, 'w') as f:
                json.dump(alertinfo_cfg, f, indent=2)
            return f"ER_INDEX:{exc}"

        write_index_manifest(database_dir, classifier_name, index_path,
                             [classifier.canonical_target(h) for h in headers])

        alertinfo_cfg['device'] = db_data.get('device', '')
        alertinfo_cfg['classifier'] = {'name': classifier_name, 'database': classifier_cfg.get('database'),
                                       'kind': classifier.kind, 'label': classifier.label}
        # Store the canonical key each target is reported under so the UI and
        # the statistics never have to re-derive tool-specific normalisation.
        for q in alertinfo_cfg.get('queries', []) or []:
            head = q.get('header') or ((q.get('headers') or [None])[0])
            if head:
                q['key'] = classifier.canonical_target(head)
        alertinfo_cfg.pop('indexError', None)
        try:
            with open(alertinfo_cfg_path, 'w') as f:
                json.dump(alertinfo_cfg, f, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to update alertinfo.cfg: {e}")
            return "ER_ALERTINFO_WRITE"

        coverage_file = os.path.join(nanocas_location, 'coverage.csv')
        try:
            with open(coverage_file, 'w') as f:
                f.write("timestamp,reference,depth,breadth,read_count,fraction\n")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to create coverage.csv: {e}")
            return "ER_COVERAGE"

        update_progress(100, "Database built successfully.")
        logger.info(f"Database build completed for project {project_id} ({classifier_name})")
        return {"nanocas_location": nanocas_location, "classifier": classifier_name, "index_path": index_path}

    finally:
        # Clean up temp FASTA upload directories (wizard uploads land in
        # mkdtemp dirs under the workspace). Database paths are never touched.
        if classifier.reference_input != 'database':
            for query in queries:
                file_path = query.get('file', '')
                if not file_path:
                    continue
                temp_dir = os.path.dirname(file_path)
                if temp_dir and os.path.isdir(temp_dir) and os.path.basename(temp_dir).startswith(('upload_', 'demo_', 'tmp')):
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"Could not remove temp directory {temp_dir}: {e}")
