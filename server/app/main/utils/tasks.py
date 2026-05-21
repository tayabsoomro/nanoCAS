import os
import shutil
import datetime
import json
import sys
import logging
from pathlib import Path
from Bio import SeqIO
from typing import Callable, Optional

from ..classifiers import get_classifier

logger = logging.getLogger('nanocas')
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


def int_download_database(db_data: dict, nanocas_location: str, queries: list,
                          progress_callback: Optional[Callable] = None):
    """
    Build a classifier index from the user's query sequences.

    The classifier itself is pluggable (LOGBOOK section 4.3); whichever
    one is named in `alertinfo.cfg['classifier']` (default "minimap2")
    gets resolved here and asked to `build_index()`. The path it writes
    is then stored back in `alertinfo.cfg['indexPath']` so FileHandler
    can find it without globbing for a specific extension.

    Args:
        db_data: Contains 'minion', 'projectId', 'device'.
        nanocas_location: Path to the project working directory.
        queries: List of query dicts with 'file', 'header', and optional 'headers'.
        progress_callback: Optional fn(percent: int, message: str) called for progress updates.

    Returns:
        dict on success, str error code on failure.
    """

    def update_progress(percent, message):
        logger.debug(f"Progress: {percent}% — {message}")
        if progress_callback:
            try:
                progress_callback(percent, message)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

    minion = db_data.get('minion')
    project_id = db_data.get('projectId')
    device = db_data.get('device')
    database_dir = os.path.join(nanocas_location, 'database')
    os.makedirs(database_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    input_sequences_path = os.path.join(database_dir, f"{timestamp}.fa")
    alertinfo_cfg_path = os.path.join(nanocas_location, 'alertinfo.cfg')

    try:
        # Load alertinfo.cfg written by the socket event handler
        try:
            with open(alertinfo_cfg_path, 'r') as f:
                alertinfo_cfg = json.load(f)
            logger.debug(f"Loaded alertinfo.cfg for project {project_id}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load alertinfo.cfg: {e}")
            return "ER_ALERTINFO"

        update_progress(5, "Preparing sequence files…")

        # Extract the selected sequences from uploaded FASTA files
        written_count = 0
        try:
            with open(input_sequences_path, 'w') as out_fasta:
                for i, query in enumerate(queries):
                    file_path = query.get('file', '')
                    # Support single header or multiple headers
                    raw_headers = query.get('headers') or []
                    single_header = query.get('header')
                    if single_header and single_header not in raw_headers:
                        raw_headers.append(single_header)
                    # ALL means every sequence in the file
                    use_all = 'ALL' in raw_headers or not raw_headers

                    if not file_path or not os.path.exists(file_path):
                        logger.warning(f"FASTA file not found: {file_path} — skipping query {i+1}")
                        continue

                    logger.debug(f"Processing query {i+1}/{len(queries)}: {file_path} headers={raw_headers}")

                    try:
                        for record in SeqIO.parse(file_path, "fasta"):
                            if use_all or record.id in raw_headers:
                                SeqIO.write(record, out_fasta, "fasta")
                                written_count += 1
                                logger.debug(f"Wrote record '{record.id}' to {input_sequences_path}")
                    except Exception as e:
                        logger.error(f"Failed to parse FASTA {file_path}: {e}")

                    update_progress(int(5 + (i + 1) / len(queries) * 45),
                                    f"Processed query {i+1}/{len(queries)}")

        except Exception as e:
            logger.error(f"Failed to write combined FASTA: {e}")
            return "ER_INPUTFILE"

        if written_count == 0:
            logger.error("No sequences written — cannot build index")
            return "ER_NO_SEQUENCES"

        # Resolve the configured classifier (default: minimap2). The
        # `classifier` field in alertinfo.cfg is optional so older
        # projects keep working unchanged.
        classifier_name = alertinfo_cfg.get('classifier', 'minimap2')
        try:
            classifier = get_classifier(classifier_name)
        except ValueError as e:
            logger.error(f"Unknown classifier in alertinfo.cfg: {e}")
            return "ER_CLASSIFIER_UNKNOWN"
        if not classifier.is_available():
            logger.error(
                f"Classifier {classifier_name!r} is registered but its "
                f"underlying binary isn't installed on PATH."
            )
            return "ER_CLASSIFIER_UNAVAILABLE"

        # Persist device + classifier name back to alertinfo.cfg.
        # Writing classifier here (even if it was already there)
        # canonicalises the value the rest of the pipeline reads.
        alertinfo_cfg['device'] = device
        alertinfo_cfg['classifier'] = classifier.name
        try:
            with open(alertinfo_cfg_path, 'w') as f:
                json.dump(alertinfo_cfg, f)
        except Exception as e:
            logger.error(f"Failed to update alertinfo.cfg: {e}")
            return "ER_ALERTINFO_WRITE"

        # Build the index via the classifier plug-in. The classifier
        # owns its own progress messaging; we just forward the
        # callback through. Errors get logged at the classifier and
        # re-raised, so any exception here is fatal to this build.
        update_progress(55, f"Building the {classifier.display_name} index…")
        try:
            db_index_path = classifier.build_index(
                fasta_paths=[Path(input_sequences_path)],
                output_dir=Path(database_dir),
                progress_callback=update_progress,
            )
        except FileNotFoundError:
            logger.error(f"{classifier.name} binary not found on PATH")
            return "ER_CLASSIFIER_NOTFOUND"
        except Exception as e:
            logger.error(f"{classifier.name} index build failed: {e}", exc_info=True)
            return "ER_INDEX_BUILD"
        logger.debug(f"{classifier.name} index built at {db_index_path}")

        # Store the index path so FileHandler doesn't have to guess
        # at an extension. Past versions globbed for *.mmi, which
        # broke the moment a non-minimap2 plug-in produced a different
        # file shape.
        alertinfo_cfg['indexPath'] = str(db_index_path)
        try:
            with open(alertinfo_cfg_path, 'w') as f:
                json.dump(alertinfo_cfg, f)
        except Exception as e:
            logger.error(f"Failed to write indexPath to alertinfo.cfg: {e}")
            return "ER_ALERTINFO_WRITE"

        # Initialise coverage.csv
        coverage_file = os.path.join(nanocas_location, 'coverage.csv')
        try:
            with open(coverage_file, 'w') as f:
                f.write("timestamp,reference,depth,breadth,read_count\n")
            logger.debug(f"Created coverage file at {coverage_file}")
        except Exception as e:
            logger.error(f"Failed to create coverage.csv: {e}")
            return "ER_COVERAGE"

        update_progress(100, "Database built successfully.")
        logger.info(f"Database build completed for project {project_id}")
        return {
            "minion": minion,
            "nanocas_location": nanocas_location,
            "device": device,
        }

    finally:
        # Clean up temp FASTA upload directories
        for query in queries:
            file_path = query.get('file', '')
            if not file_path:
                continue
            temp_dir = os.path.dirname(file_path)
            if temp_dir and os.path.isdir(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Removed temp directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Could not remove temp directory {temp_dir}: {e}")
