import os
import subprocess
import shutil
import datetime
import json
import sys
import logging
from Bio import SeqIO
from typing import Callable, Optional

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
    Build a minimap2 index from query sequences.

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
    db_index_path = os.path.join(database_dir, f"{timestamp}.mmi")
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

        # Persist device back to alertinfo.cfg
        alertinfo_cfg['device'] = device
        try:
            with open(alertinfo_cfg_path, 'w') as f:
                json.dump(alertinfo_cfg, f)
        except Exception as e:
            logger.error(f"Failed to update alertinfo.cfg: {e}")
            return "ER_ALERTINFO_WRITE"

        # Build minimap2 index
        update_progress(55, "Building the minimap2 index…")
        index_cmd = ["minimap2", "-x", "map-ont", "-d", db_index_path, input_sequences_path]
        build_log_path = os.path.join(database_dir, 'building_index.txt')
        try:
            with open(build_log_path, 'w') as log_file:
                result = subprocess.run(index_cmd, stdout=log_file, stderr=log_file)
            if result.returncode != 0:
                logger.error(f"minimap2 exited with code {result.returncode}. See {build_log_path}")
                return "ER_MINIMAP2"
            logger.debug(f"minimap2 index built at {db_index_path}")
        except FileNotFoundError:
            logger.error("minimap2 not found — is it installed?")
            return "ER_MINIMAP2_NOTFOUND"
        except Exception as e:
            logger.error(f"Unexpected error running minimap2: {e}")
            return "ER_MINIMAP2_UNKNOWN"

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
