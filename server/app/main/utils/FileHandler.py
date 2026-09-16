"""Live FASTQ/BAM ingestion: watchdog handler + coverage/alert pipeline.

One ``FileHandler`` exists per monitored project. It receives filesystem
events from a ``watchdog.Observer`` on the sequencer output directory,
aligns every new FASTQ batch with minimap2 against the project's index,
folds the per-batch depth into the rolling :class:`CoverageAccumulator`,
appends a row per reference to ``coverage.csv`` and evaluates the
coverage alert thresholds.

Alerts are recorded in ``alerts.jsonl`` (see ``alerts.AlertLog``) and
dispatched through ``alerts.Notifier`` on a background thread, so the
watchdog dispatcher is never blocked by SMTP / Twilio / gRPC latency.
"""

from __future__ import annotations

import datetime
import glob
import json
import logging
import os
import shutil
import subprocess
import time
from threading import Lock

import pysam
from watchdog.events import FileSystemEventHandler

from .alerts import (SEVERITY_CRITICAL, SEVERITY_WARNING, SOURCE_COVERAGE,
                     AlertLog, Notifier, emit_alert, safe_emit)
from .constants import BAM_EXTENSIONS, FASTQ_EXTENSIONS
from .coverage_accumulator import CoverageAccumulator

logger = logging.getLogger('nanocas')

__all__ = ['FileHandler', 'FASTQ_EXTENSIONS', 'BAM_EXTENSIONS', '_canonical_ref_id']


def _canonical_ref_id(header: str) -> str:
    """Reduce a FASTA header line to the first whitespace-delimited token.

    pysam exposes references via `bam.references` as just the first token
    (samtools tokenises @SQ SN: this way too), so any code that wants to
    look up `header_to_query[ref]` must use the same canonical form. NCBI
    headers like `>NC_000913.3 Escherichia coli K-12 ...` would otherwise
    silently fail to match.
    """
    return (header or '').split()[0] if (header and header.split()) else ''


def _alignment_threads() -> int:
    """Threads handed to minimap2 / samtools. ``NANOCAS_THREADS`` overrides;
    default is min(4, cores) so a laptop next to a MinION stays usable."""
    try:
        override = int(os.getenv('NANOCAS_THREADS', '0'))
        if override > 0:
            return override
    except ValueError:
        pass
    return max(1, min(4, os.cpu_count() or 1))


class FileHandler(FileSystemEventHandler):
    def __init__(self, app_loc: str):
        """
        Initialize the FileHandler with the project workspace location.

        Coverage state lives in a rolling numpy accumulator persisted to
        `coverage_state.npz` + `coverage_state.json` — see
        coverage_accumulator.py and LOGBOOK section 4.1 for the
        background. The legacy `merged.bam` / `merged_stable.bam` files
        are no longer maintained per-batch; a single merged BAM is
        rebuilt on demand by `_ensure_merged_bam` in routes.py when the
        alignment viewer is opened.
        """
        self.app_loc = app_loc
        self.coverage_file = os.path.join(self.app_loc, 'coverage.csv')
        self.runs_dir = os.path.join(self.app_loc, 'minimap2', 'runs')
        self.processed_files_path = os.path.join(self.app_loc, 'processed_files.txt')
        self.failed_files_path = os.path.join(self.app_loc, 'failed_files.json')
        self.processed_files: set[str] = set()
        self.in_progress_files: set[str] = set()
        # Files that failed processing in this session. They are NOT added
        # to processed_files (the previous code did, silently losing the
        # batch forever) so a restart retries them once.
        self.failed_files: dict[str, str] = {}
        self.processed_files_lock = Lock()
        self.coverage_lock = Lock()
        # Track sent alerts to avoid duplicate notifications
        self.sent_alerts_path = os.path.join(self.app_loc, 'sent_alerts.json')
        self.sent_alerts_lock = Lock()
        self.sent_alerts = self._load_sent_alerts()
        # Wall-clock time the last batch finished processing (for the
        # run-health stall detector).
        self.last_processed_time: float | None = None
        # Optional synthetic clock (callable returning datetime) used when a
        # demo run is replayed; None means wall-clock time.
        self.clock = None

        # Load previously processed files if the file exists
        if os.path.exists(self.processed_files_path):
            with open(self.processed_files_path, 'r') as f:
                self.processed_files = set(line for line in f.read().splitlines() if line)

        # Load configuration from alertinfo.cfg
        with open(os.path.join(self.app_loc, 'alertinfo.cfg'), 'r') as f:
            self.config = json.load(f)
        self.project_id = self.config.get('projectId', '')
        self.file_type = (self.config.get('fileType') or 'FASTQ').upper()
        self.alert_log = AlertLog(self.app_loc)
        self.notifier = Notifier(self.config)

        # `header_to_query` keys are FASTA reference IDs as pysam exposes
        # them via `bam.references` — i.e. the first whitespace-delimited
        # token of the FASTA header line. NCBI-style headers like
        # `>NC_000913.3 Escherichia coli K-12 substr. MG1655` round-trip
        # through samtools as just `NC_000913.3`, so we normalise here so
        # the lookup at alert-check time can't miss when alertinfo.cfg
        # was written with a full descriptive header.
        self.header_to_query: dict[str, dict] = {}
        for query in self.config.get("queries", []) or []:
            headers = []
            if query.get("headers"):
                headers.extend(query["headers"])
            if query.get("header"):
                headers.append(query["header"])
            for h in headers:
                key = _canonical_ref_id(h)
                if key:
                    self.header_to_query[key] = query

        # Load regions data
        self.regions_json_path = os.path.join(self.app_loc, 'regions.json')
        self.regions_data = {}
        if os.path.exists(self.regions_json_path):
            try:
                with open(self.regions_json_path, 'r') as f:
                    self.regions_data = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"Could not load regions.json: {exc}")

        # Rolling per-position depth accumulator. Replaces the cumulative
        # merged.bam read pattern that made every batch O(n) and the run
        # O(n^2). See LOGBOOK section 4.1 for the full diagnosis.
        self.coverage_acc = CoverageAccumulator(self.app_loc)
        self._migrate_legacy_merged_bam_if_needed()
        self._repair_unindexed_runs_if_needed()

    # ------------------------------------------------------------------
    # Legacy migration / repair
    # ------------------------------------------------------------------

    def _migrate_legacy_merged_bam_if_needed(self):
        """One-shot bootstrap: if a project predates the accumulator it has
        a `merged.bam` but no `coverage_state.npz`. Seed the accumulator
        from the existing merged.bam, then rename it to
        `legacy_pre_v9.bam` so the lazy-merge code path picks it up
        alongside any newly-arrived per-FASTQ BAMs. Idempotent."""
        legacy_merged = os.path.join(self.app_loc, 'merged.bam')
        legacy_renamed = os.path.join(self.app_loc, 'legacy_pre_v9.bam')
        if os.path.exists(self.coverage_acc.depth_path) or not os.path.exists(legacy_merged):
            return

        logger.info(f"Migrating legacy merged.bam in {self.app_loc} -> coverage accumulator")
        try:
            if not self._ensure_bam_index(legacy_merged):
                return
            with pysam.AlignmentFile(legacy_merged, 'rb') as bam:
                self.coverage_acc.update_from_bam(bam)
            self.coverage_acc.save()
            os.replace(legacy_merged, legacy_renamed)
            if os.path.exists(legacy_merged + '.bai'):
                os.replace(legacy_merged + '.bai', legacy_renamed + '.bai')
            for stale in [
                os.path.join(self.app_loc, 'merged_stable.bam'),
                os.path.join(self.app_loc, 'merged_stable.bam.bai'),
            ]:
                if os.path.exists(stale):
                    os.remove(stale)
            logger.info("Legacy merged.bam migrated successfully")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Legacy migration failed (continuing with empty accumulator): {e}", exc_info=True)

    def _repair_unindexed_runs_if_needed(self):
        """Recover projects affected by the indexing regression that
        shipped briefly in the PR-#9 accumulator rollout: per-FASTQ BAMs
        without a `.bai` never made it into the accumulator. Index them
        and, if the accumulator is still empty, fold them in."""
        if not os.path.isdir(self.runs_dir):
            return

        candidates = []
        for fname in os.listdir(self.runs_dir):
            if not fname.endswith('_sorted.bam'):
                continue
            bam_path = os.path.join(self.runs_dir, fname)
            if os.path.exists(bam_path + '.bai'):
                continue
            candidates.append(bam_path)
        if not candidates:
            return

        is_empty_accumulator = len(self.coverage_acc.refs()) == 0
        logger.info(
            f"Repairing {len(candidates)} un-indexed per-FASTQ BAM(s) in {self.runs_dir} "
            f"(refold into accumulator: {is_empty_accumulator})"
        )
        for bam_path in candidates:
            if not self._ensure_bam_index(bam_path):
                continue
            if is_empty_accumulator:
                try:
                    with pysam.AlignmentFile(bam_path, 'rb') as bam:
                        self.coverage_acc.update_from_bam(bam)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Could not fold {bam_path} into accumulator during repair: {e}")
        if is_empty_accumulator and candidates:
            self.coverage_acc.save()

    # ------------------------------------------------------------------
    # Sent-alert de-duplication
    # ------------------------------------------------------------------

    def _load_sent_alerts(self):
        """Load previously sent alerts from JSON file."""
        if os.path.exists(self.sent_alerts_path):
            try:
                with open(self.sent_alerts_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Could not load sent alerts file, starting fresh")
        return {}

    def _check_if_alert_sent(self, alert_key: str) -> bool:
        """Check if an alert has already been sent for this key."""
        with self.sent_alerts_lock:
            return alert_key in self.sent_alerts

    def _mark_alert_as_sent(self, alert_key: str, alert_info: dict):
        """Mark an alert as sent with timestamp and details, and persist to disk.

        The JSON write happens while the lock is held to keep the in-memory dict
        and the on-disk file in sync. The lock must NOT be re-acquired by any
        helper called from inside this block — threading.Lock is non-reentrant
        and would deadlock the watchdog dispatcher (which then silently stops
        processing further filesystem events).
        """
        with self.sent_alerts_lock:
            self.sent_alerts[alert_key] = {
                'timestamp': datetime.datetime.now().isoformat(),
                'info': alert_info
            }
            tmp = self.sent_alerts_path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(self.sent_alerts, f, indent=2)
            os.replace(tmp, self.sent_alerts_path)

    # ------------------------------------------------------------------
    # watchdog callbacks
    # ------------------------------------------------------------------
    #
    # MinKNOW writes each FASTQ batch to a temp name and renames it into
    # place (-> on_moved), other producers create-then-append
    # (-> on_created / on_modified / on_closed). Deleted events and
    # directory events are ignored: the old on_any_event handler used to
    # forward deletions to _handle_path, which then logged a spurious
    # "file is not stable" error for every removed file.

    def on_created(self, event):
        if not event.is_directory:
            self._handle_path(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle_path(event.src_path)

    def on_closed(self, event):
        if not event.is_directory:
            self._handle_path(event.src_path)

    def on_moved(self, event):
        """Use event.dest_path (the final location): src_path is the temp
        path that no longer exists by the time the event fires."""
        if not event.is_directory:
            self._handle_path(event.dest_path)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _matches_type(self, file_path: str) -> bool:
        lower = file_path.lower()
        if self.file_type == 'FASTQ':
            return lower.endswith(FASTQ_EXTENSIONS)
        if self.file_type == 'BAM':
            return lower.endswith(BAM_EXTENSIONS)
        return False

    def _handle_path(self, file_path: str, *, wait_stable: bool = True, timestamp: str | None = None):
        """Core dispatch: validate, wait for stability, then process one file path.

        Uses in_progress_files to atomically claim the file before the lengthy
        processing starts, preventing TOCTOU races when process_existing_files
        and the watchdog observer run concurrently.
        """
        # Cheap reject before taking the lock: temp files, indexes, etc.
        if not self._matches_type(file_path) or os.path.basename(file_path).startswith('.'):
            return

        # Atomically check-and-claim: skip if already processed or in progress.
        with self.processed_files_lock:
            if (file_path in self.processed_files or file_path in self.in_progress_files
                    or file_path in self.failed_files):
                logger.debug(f"Skipping already processed/in-progress/failed file: {file_path}")
                return
            self.in_progress_files.add(file_path)

        try:
            if wait_stable and not self.wait_for_file_stability(file_path):
                logger.error(f"File {file_path} is not stable, skipping.")
                return

            if timestamp is None:
                mtime = os.path.getmtime(file_path)
                timestamp = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

            if self.file_type == 'FASTQ':
                logger.debug(f"Processing FASTQ file: {file_path} with timestamp {timestamp}")
                ok = self.process_fastq_file(file_path, timestamp)
            else:
                logger.debug(f"Processing BAM file: {file_path} with timestamp {timestamp}")
                ok = self.process_bam_file(file_path, timestamp)

            if ok:
                self._record_processed(file_path)
            else:
                self._record_failed(file_path, 'processing failed (see server log)')

        except Exception as e:  # noqa: BLE001
            logger.error(f"Unhandled error processing {file_path}: {e}", exc_info=True)
            self._record_failed(file_path, str(e))
        finally:
            # Always release the in-progress claim so retries are possible
            with self.processed_files_lock:
                self.in_progress_files.discard(file_path)

    def wait_for_file_stability(self, file_path, timeout=60, interval=1):
        """Ensure the file is fully written by checking if its size stabilizes."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not os.path.exists(file_path):
                logger.error(f"File {file_path} no longer exists.")
                return False
            try:
                size1 = os.path.getsize(file_path)
                time.sleep(interval)
                if not os.path.exists(file_path):
                    logger.error(f"File {file_path} no longer exists.")
                    return False
                size2 = os.path.getsize(file_path)
                if size1 == size2 and size2 > 0:
                    return True
            except OSError as e:
                logger.error(f"Error checking file size for {file_path}: {e}")
                return False
        logger.warning(f"File {file_path} did not stabilize within {timeout} seconds.")
        return False

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def is_bam_valid(self, bam_file):
        """Check if a BAM file is valid using pysam quickcheck."""
        try:
            pysam.quickcheck(bam_file)
            return True
        except pysam.utils.SamtoolsError as e:
            logger.error(f"BAM file {bam_file} is invalid or corrupted: {e}")
            return False

    def _align_fastq(self, src_path: str, index_file: str, sorted_bam_output: str) -> bool:
        """``minimap2 -a`` piped straight into ``samtools sort``.

        No shell: paths with spaces or shell metacharacters are passed as
        argv entries. Both processes get ``-t``/``-@`` threads. Returns
        True when both exit 0 and the output exists.
        """
        threads = _alignment_threads()
        mm2_cmd = ['minimap2', '-a', '-x', 'map-ont', '-t', str(threads), index_file, src_path]
        sort_cmd = ['samtools', 'sort', '-@', str(max(1, threads // 2)), '-o', sorted_bam_output, '-']
        logger.debug(f"Running: {' '.join(mm2_cmd)} | {' '.join(sort_cmd)}")
        try:
            mm2 = subprocess.Popen(mm2_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            sort = subprocess.Popen(sort_cmd, stdin=mm2.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            mm2.stdout.close()  # let minimap2 get SIGPIPE if samtools dies
            sort_out, sort_err = sort.communicate()
            mm2_err = mm2.stderr.read()
            mm2.stderr.close()
            mm2.wait()
        except FileNotFoundError as exc:
            logger.error(f"Alignment tool not found ({exc}). Are minimap2 and samtools on PATH?")
            self._raise_alert('tool_missing', SEVERITY_CRITICAL,
                              f"Cannot align reads: {exc.filename or exc} is not installed or not on PATH.",
                              once_key='tool_missing')
            return False
        if mm2.returncode != 0:
            logger.error(f"minimap2 failed on {src_path} (exit {mm2.returncode}): "
                         f"{mm2_err.decode(errors='replace').strip()}")
            return False
        if sort.returncode != 0:
            logger.error(f"samtools sort failed on {src_path} (exit {sort.returncode}): "
                         f"{sort_err.decode(errors='replace').strip()}")
            return False
        return os.path.exists(sorted_bam_output)

    def process_fastq_file(self, src_path: str, timestamp: str | None = None) -> bool:
        """Align one FASTQ to the project's minimap2 index and fold the
        resulting per-batch coverage into the rolling accumulator.

        The per-FASTQ sorted BAM is kept on disk under `minimap2/runs/`
        AND indexed: pysam's `count_coverage` internally calls `fetch`,
        which requires the index. Per-batch cost is O(reads in batch).
        Returns True on success; a False return means the batch must NOT
        be marked processed.
        """
        index_file = self.get_index_file()
        if not index_file:
            self._raise_alert('index_missing', SEVERITY_CRITICAL,
                              'No minimap2 index (.mmi) found for this project; reads cannot be aligned. '
                              'Re-create the project or check the database build log.',
                              once_key='index_missing')
            return False

        os.makedirs(self.runs_dir, exist_ok=True)
        sorted_bam_output = os.path.join(self.runs_dir, f'{os.path.basename(src_path)}_sorted.bam')
        if not self._align_fastq(src_path, index_file, sorted_bam_output):
            if os.path.exists(sorted_bam_output):
                os.remove(sorted_bam_output)
            return False

        if not self.is_bam_valid(sorted_bam_output):
            logger.error(f"Generated BAM file {sorted_bam_output} is invalid.")
            if os.path.exists(sorted_bam_output):
                os.remove(sorted_bam_output)
            return False

        if not self._ensure_bam_index(sorted_bam_output):
            return False

        return self.calculate_and_record_coverage(sorted_bam_output, timestamp)

    def process_bam_file(self, bam_path: str, timestamp: str | None = None) -> bool:
        """Fold an externally-produced, coordinate-sorted BAM into the
        rolling accumulator. Returns True on success."""
        if not self.is_bam_valid(bam_path):
            logger.error(f"Skipping invalid BAM file: {bam_path}")
            return False
        os.makedirs(self.runs_dir, exist_ok=True)
        target = os.path.join(self.runs_dir, f'{os.path.basename(bam_path)}_sorted.bam')
        if os.path.abspath(bam_path) != os.path.abspath(target):
            shutil.copy(bam_path, target)
            src_bai = bam_path + '.bai'
            if os.path.exists(src_bai):
                shutil.copy(src_bai, target + '.bai')
        if not self._ensure_bam_index(target):
            return False
        return self.calculate_and_record_coverage(target, timestamp)

    def _ensure_bam_index(self, bam_path: str) -> bool:
        """Make sure a `.bai` sibling exists for `bam_path` and is newer
        than the BAM. Returns False on failure."""
        if not os.path.exists(bam_path):
            return False
        bai = bam_path + '.bai'
        if os.path.exists(bai) and os.path.getmtime(bai) >= os.path.getmtime(bam_path):
            return True
        try:
            pysam.index(bam_path)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"samtools index failed for {bam_path}: {e}")
            return False

    def get_index_file(self) -> str | None:
        """Retrieve the database index file (.mmi)."""
        files = sorted(glob.glob(os.path.join(self.app_loc, 'database', '*.mmi')))
        if not files:
            logger.error("No MMI files found in database location")
            return None
        return files[-1]

    # ------------------------------------------------------------------
    # Coverage + alerts
    # ------------------------------------------------------------------

    def calculate_and_record_coverage(self, batch_bam_path: str, timestamp: str | None = None) -> bool:
        """Fold one batch BAM into the rolling accumulator, then append a
        coverage.csv row per reference, evaluate alerts, and notify the UI.
        Returns False if the batch could not be folded in."""
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.coverage_lock:
            try:
                with pysam.AlignmentFile(batch_bam_path, "rb", check_sq=False) as batch_bam:
                    self.coverage_acc.update_from_bam(batch_bam)
                self.coverage_acc.save()
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error folding {batch_bam_path} into coverage accumulator: {e}", exc_info=True)
                return False

            coverage_data = {}
            for ref in self.coverage_acc.refs():
                depth_coverage, breadth_coverage, read_count = self.coverage_acc.stats(ref)
                coverage_data[ref] = {
                    "depth": depth_coverage,
                    "breadth": breadth_coverage,
                    "read_count": read_count,
                }
                logger.debug(
                    f"Reference: {ref}, Depth {depth_coverage:.2f}x, "
                    f"Breadth {breadth_coverage:.2f}%, Reads {read_count}"
                )
                try:
                    self.check_coverage_alerts(ref, depth_coverage, breadth_coverage)
                    self._check_region_alerts(ref)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Alert evaluation failed for {ref}: {e}", exc_info=True)

            coverage_data['unmapped'] = {
                "depth": 0.0,
                "breadth": 0.0,
                "read_count": self.coverage_acc.unmapped_count,
            }

            try:
                write_header = not os.path.exists(self.coverage_file) or os.path.getsize(self.coverage_file) == 0
                with open(self.coverage_file, 'a') as f:
                    if write_header:
                        f.write("timestamp,reference,depth,breadth,read_count\n")
                    for ref, cov in coverage_data.items():
                        f.write(f"{timestamp},{ref},{cov['depth']:.6f},{cov['breadth']:.4f},{cov['read_count']}\n")
            except OSError as e:
                logger.error(f"Could not append to {self.coverage_file}: {e}")
            logger.debug(f"Coverage and read counts recorded at {timestamp}")

        self.last_processed_time = self.clock().timestamp() if self.clock else time.time()
        emit_payload = {
            'projectId': self.project_id,
            'timestamp': timestamp,
            'coverage': coverage_data,
        }
        safe_emit('coverage_update', emit_payload)
        return True

    def _check_region_alerts(self, ref: str):
        """GFF region alerts, de-duplicated per (ref, region) for the run."""
        if ref not in self.regions_data:
            return
        query = self.header_to_query.get(ref)
        default_threshold = float(query.get("depth_threshold", 0) or 0) if query else 0
        depth_arr = self.coverage_acc.depth_array(ref)
        if depth_arr is None:
            return
        for region in self.regions_data[ref]:
            if not region.get('alert_enabled', False):
                continue
            try:
                start = int(region['start'])
                end = int(region['end'])
            except (KeyError, TypeError, ValueError):
                continue
            region_id = region.get('id') or f'{start}-{end}'
            region_length = end - start + 1
            if region_length <= 0:
                continue
            # GFF is 1-based inclusive; numpy is 0-based half-open.
            region_slice = depth_arr[max(start - 1, 0):end]
            region_depth_coverage = float(region_slice.sum()) / region_length
            threshold = float(region.get('threshold', default_threshold) or 0)
            if region_depth_coverage < threshold:
                continue
            alert_key = f"{ref}_region_{region_id}_depth"
            if self._check_if_alert_sent(alert_key):
                continue
            display = query['name'] if query and query.get('name') else ref
            message = (f"Region {region_id} of {display} reached {region_depth_coverage:.2f}x depth "
                       f"(threshold {threshold:g}x)")
            self._raise_alert('region_depth', SEVERITY_CRITICAL, message, details={
                'reference': ref, 'region_id': region_id, 'value': region_depth_coverage,
                'threshold': threshold, 'start': start, 'end': end,
            })
            self._mark_alert_as_sent(alert_key, {
                'type': 'region_depth', 'reference': ref, 'region_id': region_id,
                'value': region_depth_coverage, 'threshold': threshold,
            })

    def check_coverage_alerts(self, ref: str, depth_coverage: float, breadth_coverage: float):
        """Fire the depth / breadth alert for `ref` once per run when the
        configured threshold is reached."""
        query = self.header_to_query.get(ref)
        if not query:
            return
        display = query.get('name') or ref
        if query.get("alert_on_depth", False):
            depth_threshold = float(query.get("depth_threshold", 0) or 0)
            if depth_coverage >= depth_threshold:
                alert_key = f"{ref}_depth"
                if not self._check_if_alert_sent(alert_key):
                    message = (f"{display} ({ref}) reached {depth_coverage:.2f}x depth of coverage "
                               f"(threshold {depth_threshold:g}x)")
                    self._raise_alert('depth', SEVERITY_CRITICAL, message, details={
                        'reference': ref, 'name': display, 'value': depth_coverage,
                        'threshold': depth_threshold, 'breadth': breadth_coverage,
                    })
                    self._mark_alert_as_sent(alert_key, {
                        'type': 'depth', 'reference': ref, 'value': depth_coverage,
                        'threshold': depth_threshold,
                    })
        if query.get("alert_on_breadth", False):
            breadth_threshold = float(query.get("breadth_threshold", 0) or 0)
            if breadth_coverage >= breadth_threshold:
                alert_key = f"{ref}_breadth"
                if not self._check_if_alert_sent(alert_key):
                    message = (f"{display} ({ref}) reached {breadth_coverage:.2f}% breadth of coverage "
                               f"(threshold {breadth_threshold:g}%)")
                    self._raise_alert('breadth', SEVERITY_CRITICAL, message, details={
                        'reference': ref, 'name': display, 'value': breadth_coverage,
                        'threshold': breadth_threshold, 'depth': depth_coverage,
                    })
                    self._mark_alert_as_sent(alert_key, {
                        'type': 'breadth', 'reference': ref, 'value': breadth_coverage,
                        'threshold': breadth_threshold,
                    })

    def _raise_alert(self, alert_type: str, severity: str, message: str, *,
                     details: dict | None = None, once_key: str | None = None):
        """Record + notify + push to the UI. ``once_key`` de-duplicates
        system alerts (e.g. missing tools) for the life of the run."""
        if once_key:
            if self._check_if_alert_sent(once_key):
                return
            self._mark_alert_as_sent(once_key, {'type': alert_type})
        source = SOURCE_COVERAGE if alert_type in ('depth', 'breadth', 'region_depth') else 'system'
        record = self.alert_log.append(alert_type, severity, message, source=source,
                                       details=details, project_id=self.project_id)
        logger.critical(f"ALERT [{alert_type}] {message}")
        self.notifier.send('nanoCAS alert', message, severity=severity)
        emit_alert(record)

    # Backwards-compatible shim for callers that used the old private API.
    def _send_notifications(self, alert_str: str):
        self.notifier.send('nanoCAS alert', alert_str, severity=SEVERITY_WARNING)

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    def _record_processed(self, file_path: str):
        """Mark `file_path` as fully processed: add to in-memory set, append
        to processed_files.txt, release any in-progress claim, and notify
        the UI over Socket.IO."""
        with self.processed_files_lock:
            self.processed_files.add(file_path)
            self.in_progress_files.discard(file_path)
            self.failed_files.pop(file_path, None)
            with open(self.processed_files_path, 'a') as f:
                f.write(file_path + '\n')
            count = len(self.processed_files)
        self._emit_file_progress(count, file_path)

    def _record_failed(self, file_path: str, reason: str):
        with self.processed_files_lock:
            self.failed_files[file_path] = reason
            self.in_progress_files.discard(file_path)
            try:
                tmp = self.failed_files_path + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(self.failed_files, f, indent=2)
                os.replace(tmp, self.failed_files_path)
            except OSError as exc:
                logger.warning(f"Could not persist failed_files.json: {exc}")
            failed = len(self.failed_files)
        logger.error(f"Batch {file_path} failed: {reason} ({failed} failed so far this session)")
        if failed in (1, 5, 20) or failed % 50 == 0:
            self._raise_alert('batch_failed', SEVERITY_WARNING,
                              f"{failed} input file(s) could not be processed; latest: "
                              f"{os.path.basename(file_path)} ({reason}).",
                              details={'file': file_path, 'failed_count': failed})

    def _emit_file_progress(self, count: int, file_path: str):
        payload = {
            'projectId': self.project_id,
            'files_processed': count,
            'files_failed': len(self.failed_files),
            'last_file': os.path.basename(file_path),
            'last_file_full_path': file_path,
        }

        safe_emit('file_progress_update', payload)

    def status(self) -> dict:
        with self.processed_files_lock:
            return {
                'files_processed': len(self.processed_files),
                'files_failed': len(self.failed_files),
                'files_in_progress': len(self.in_progress_files),
                'failed_files': dict(self.failed_files),
                'last_processed_time': self.last_processed_time,
            }

    # ------------------------------------------------------------------
    # Start-up catch-up
    # ------------------------------------------------------------------

    def get_existing_files(self, directory):
        """Existing files of the configured type, oldest first, that haven't
        been processed yet."""
        if not os.path.isdir(directory):
            return []
        try:
            files = [os.path.join(directory, f) for f in os.listdir(directory)
                     if self._matches_type(f) and not f.startswith('.')]
        except OSError as exc:
            logger.error(f"Cannot list {directory}: {exc}")
            return []
        with self.processed_files_lock:
            files = [f for f in files if f not in self.processed_files]
        files.sort(key=lambda x: os.path.getmtime(x))
        return files

    def process_existing_files(self, directory):
        """Process files already present in the directory. Goes through the
        same claim/record path as live events so a batch can't be counted
        twice if the watchdog fires for it at the same time."""
        files = self.get_existing_files(directory)
        if files:
            logger.info(f"Catching up on {len(files)} existing file(s) in {directory}")
        for file in files:
            try:
                mtime = os.path.getmtime(file)
            except OSError:
                continue
            # Files untouched for a minute are complete; newer ones get
            # the normal stability wait.
            settled = (time.time() - mtime) > 60
            timestamp = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            self._handle_path(file, wait_stable=not settled, timestamp=timestamp)
