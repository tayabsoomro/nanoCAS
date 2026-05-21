import datetime
import json
import logging
import os
import shutil
import subprocess
import time
import glob
import pysam
from threading import Lock
from watchdog.events import FileSystemEventHandler
from app import socketio
from .LinuxNotification import LinuxNotification
from .email import send_email
from .sms import send_sms
from .coverage_accumulator import CoverageAccumulator
from ..classifiers import get_classifier

# Set up logging
logger = logging.getLogger('nanocas')

# Canonical FASTQ extension set, used by both the watchdog dispatch
# (_handle_path) and the startup catch-up loop (get_existing_files /
# process_existing_files). Listed once so the two paths can't drift.
#
# .fasta was previously in this set, which made nanoCAS silently accept
# unquality'd FASTA files as "FASTQ" — minimap2 would happily map them
# but every Run Health metric (Q-score histogram, median-Q trend) would
# be empty or zero, with no surface for the user to notice. If a user
# wants to align FASTA reads they should rename to .fastq deliberately.
FASTQ_EXTENSIONS = ('.fastq', '.fq', '.fastq.gz', '.fq.gz')

# External BAM ingestion path; sorted+indexed BAMs from elsewhere.
BAM_EXTENSIONS = ('.bam',)


def _canonical_ref_id(header: str) -> str:
    """Reduce a FASTA header line to the first whitespace-delimited token.

    pysam exposes references via `bam.references` as just the first token
    (samtools tokenises @SQ SN: this way too), so any code that wants to
    look up `header_to_query[ref]` must use the same canonical form. NCBI
    headers like `>NC_000913.3 Escherichia coli K-12 ...` would otherwise
    silently fail to match.
    """
    return (header or '').split()[0] if (header and header.split()) else ''


class FileHandler(FileSystemEventHandler):
    def __init__(self, app_loc: str):
        """
        Initialize the FileHandler with the application location.

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
        self.processed_files = set()
        self.in_progress_files = set()
        self.processed_files_lock = Lock()  # Lock for thread-safe access to processed files
        # Track sent alerts to avoid duplicate notifications
        self.sent_alerts_path = os.path.join(self.app_loc, 'sent_alerts.json')
        self.sent_alerts_lock = Lock()
        self.sent_alerts = self._load_sent_alerts()

        # Load previously processed files if the file exists
        if os.path.exists(self.processed_files_path):
            with open(self.processed_files_path, 'r') as f:
                self.processed_files = set(f.read().splitlines())

        # Load configuration from alertinfo.cfg
        with open(os.path.join(self.app_loc, 'alertinfo.cfg'), 'r') as f:
            self.config = json.load(f)
        self.file_type = self.config.get('fileType', 'FASTQ')
        # `header_to_query` keys are FASTA reference IDs as pysam exposes
        # them via `bam.references` — i.e. the first whitespace-delimited
        # token of the FASTA header line. NCBI-style headers like
        # `>NC_000913.3 Escherichia coli K-12 substr. MG1655` round-trip
        # through samtools as just `NC_000913.3`, so we normalise here so
        # the lookup at alert-check time can't miss when alertinfo.cfg
        # was written with a full descriptive header.
        self.header_to_query = {}
        for query in self.config.get("queries", []):
            headers = []
            if "headers" in query and query["headers"]:
                headers.extend(query["headers"])
            if "header" in query and query["header"]:
                headers.append(query["header"])
            for h in headers:
                self.header_to_query[_canonical_ref_id(h)] = query

        # Load regions data
        self.regions_json_path = os.path.join(self.app_loc, 'regions.json')
        self.regions_data = {}
        if os.path.exists(self.regions_json_path):
            with open(self.regions_json_path, 'r') as f:
                self.regions_data = json.load(f)

        # Rolling per-position depth accumulator. Replaces the cumulative
        # merged.bam read pattern that made every batch O(n) and the run
        # O(n^2). See LOGBOOK section 4.1 for the full diagnosis.
        self.coverage_acc = CoverageAccumulator(self.app_loc)
        self._migrate_legacy_merged_bam_if_needed()
        self._repair_unindexed_runs_if_needed()

        # Pluggable classifier (LOGBOOK section 4.3). Defaults to
        # minimap2 so projects whose alertinfo.cfg predates this change
        # keep working unchanged. Resolution happens once at startup;
        # the registered class is instantiated and cached on the
        # handler so the per-batch hot path doesn't repeat the lookup.
        classifier_name = self.config.get('classifier', 'minimap2')
        try:
            self.classifier = get_classifier(classifier_name)
            logger.info(f"Using classifier: {self.classifier.name}")
        except ValueError as e:
            logger.error(f"Configured classifier {classifier_name!r} not found, falling back to minimap2: {e}")
            self.classifier = get_classifier('minimap2')

    def _migrate_legacy_merged_bam_if_needed(self):
        """One-shot bootstrap: if a project predates this refactor it has
        a `merged.bam` but no `coverage_state.npz`. Seed the accumulator
        from the existing merged.bam, then rename it to
        `legacy_pre_v9.bam` so the lazy-merge code path picks it up
        alongside any newly-arrived per-FASTQ BAMs.

        Idempotent: subsequent restarts see `coverage_state.npz` present
        and skip the bootstrap.
        """
        legacy_merged = os.path.join(self.app_loc, 'merged.bam')
        legacy_renamed = os.path.join(self.app_loc, 'legacy_pre_v9.bam')
        already_migrated = os.path.exists(self.coverage_acc.depth_path)
        nothing_to_do = not os.path.exists(legacy_merged)
        if already_migrated or nothing_to_do:
            return

        logger.info(f"Migrating legacy merged.bam in {self.app_loc} -> coverage accumulator")
        try:
            with pysam.AlignmentFile(legacy_merged, 'rb') as bam:
                self.coverage_acc.update_from_bam(bam)
            self.coverage_acc.save()
            os.replace(legacy_merged, legacy_renamed)
            # Clean up the stale stable copy + its index; both are gone in the new layout.
            for stale in [
                legacy_merged + '.bai',
                os.path.join(self.app_loc, 'merged_stable.bam'),
                os.path.join(self.app_loc, 'merged_stable.bam.bai'),
            ]:
                if os.path.exists(stale):
                    os.remove(stale)
            logger.info("Legacy merged.bam migrated successfully")
        except Exception as e:
            logger.error(f"Legacy migration failed (continuing with empty accumulator): {e}", exc_info=True)

    def _repair_unindexed_runs_if_needed(self):
        """Recover projects affected by the indexing regression that
        shipped briefly in the PR-#9 accumulator rollout.

        That version produced per-FASTQ sorted BAMs but didn't index
        them, so the accumulator's `pysam.count_coverage` call failed
        on every batch and `coverage_state.npz` stayed empty. The fix
        lives in `process_fastq_file`, but it only helps NEW batches —
        files already aligned into `runs/` would otherwise be stranded.

        On startup, scan `runs/` for any `_sorted.bam` missing a
        `.bai`. For each one: write the index, then fold the BAM into
        the accumulator (idempotent because the accumulator is empty if
        the original processing failed, and the only path that updates
        it later is `_handle_path`, which checks `processed_files.txt`
        and skips already-processed paths).
        """
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

        # Only re-fold into the accumulator if it looks empty (i.e. the
        # regression actually hit). If there's existing state we don't
        # know which BAMs are already counted, and double-counting would
        # silently inflate the depth — better to leave the user's data
        # alone in that case and just index for future operations.
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
                except Exception as e:
                    logger.error(f"Could not fold {bam_path} into accumulator during repair: {e}")
        if is_empty_accumulator and candidates:
            self.coverage_acc.save()

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
            with open(self.sent_alerts_path, 'w') as f:
                json.dump(self.sent_alerts, f, indent=2)

    def on_moved(self, event):
        """Handle file move events.

        Nanopore sequencers (and many other tools) write files to a temp location
        then atomically move them to the output directory.  We must use
        event.dest_path (the final location) — src_path is the temp path that
        no longer exists by the time the event fires.
        """
        self._handle_path(event.dest_path)

    def on_any_event(self, event):
        """Handle file created / modified / deleted events."""
        from watchdog.events import FileMovedEvent
        # Moved events are handled by on_moved; skip them here to avoid double-processing.
        if isinstance(event, FileMovedEvent):
            return
        self._handle_path(event.src_path)

    def _handle_path(self, file_path: str):
        """Core dispatch: validate, wait for stability, then process one file path.

        Uses in_progress_files to atomically claim the file before the lengthy
        processing starts, preventing TOCTOU races when process_existing_files
        and the watchdog observer run concurrently.
        """
        # Atomically check-and-claim: skip if already processed or in progress.
        with self.processed_files_lock:
            if file_path in self.processed_files or file_path in self.in_progress_files:
                logger.debug(f"Skipping already processed/in-progress file: {file_path}")
                return
            self.in_progress_files.add(file_path)

        try:
            if not self.wait_for_file_stability(file_path):
                logger.error(f"File {file_path} is not stable, skipping.")
                return

            mtime = os.path.getctime(file_path)
            timestamp = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

            if self.file_type == 'FASTQ' and file_path.endswith(FASTQ_EXTENSIONS):
                logger.debug(f"Processing FASTQ file: {file_path} with timestamp {timestamp}")
                self.process_fastq_file(file_path, timestamp)
            elif self.file_type == 'BAM' and file_path.endswith(BAM_EXTENSIONS):
                logger.debug(f"Processing BAM file: {file_path} with timestamp {timestamp}")
                self.process_bam_file(file_path, timestamp)
            else:
                logger.debug(f"Ignoring file {file_path} as it does not match expected type {self.file_type}")
                return  # don't mark non-matching paths as processed

            # Promote from in-progress to fully processed
            self._record_processed(file_path)

        except Exception as e:
            logger.error(f"Unhandled error processing {file_path}: {e}", exc_info=True)
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
                if size1 == size2:
                    return True
            except OSError as e:
                logger.error(f"Error checking file size for {file_path}: {e}")
                return False
        logger.warning(f"File {file_path} did not stabilize within {timeout} seconds.")
        return False

    def is_bam_valid(self, bam_file):
        """Check if a BAM file is valid using pysam quickcheck."""
        try:
            pysam.quickcheck(bam_file)
            return True
        except pysam.utils.SamtoolsError as e:
            logger.error(f"BAM file {bam_file} is invalid or corrupted: {e}")
            return False

    def process_fastq_file(self, src_path: str, timestamp: str = None):
        """Align one FASTQ to the project's index via the configured
        classifier, then fold the resulting per-batch coverage into the
        rolling accumulator.

        The classifier (LOGBOOK section 4.3) is responsible for
        producing a coordinate-sorted, indexed BAM at
        `runs/<basename>_sorted.bam`. Without the index the
        accumulator's `pysam.count_coverage` would raise `fetch called
        on bamfile without index` and the whole batch's coverage would
        be silently dropped — that contract is part of the
        `Classifier.align` docstring.

        Per-batch cost is O(reads in this batch); the previous design
        re-merged AND re-sorted the cumulative BAM here, which was
        O(cumulative). See LOGBOOK section 4.1.
        """
        index_file = self.get_index_file()
        if not index_file:
            return

        os.makedirs(self.runs_dir, exist_ok=True)
        basename = os.path.basename(src_path)
        try:
            sorted_bam_output = str(self.classifier.align(
                fastq_path=src_path,
                index_path=index_file,
                output_dir=self.runs_dir,
                output_basename=basename,
            ))
        except Exception as e:
            logger.error(f"Classifier {self.classifier.name} failed on {src_path}: {e}", exc_info=True)
            return

        if not self.is_bam_valid(sorted_bam_output):
            logger.error(f"Generated BAM file {sorted_bam_output} is invalid.")
            if os.path.exists(sorted_bam_output):
                os.remove(sorted_bam_output)
            return

        # Defence in depth: the Classifier.align contract says it must
        # leave a .bai sibling, but old plug-ins or external authors
        # might miss this. If the contract was already met this is a
        # cheap no-op (mtime check inside _ensure_bam_index).
        if not self._ensure_bam_index(sorted_bam_output):
            return

        # Fold this batch's coverage into the rolling accumulator and
        # emit the standard coverage_update / region-alert work. Keep
        # the per-FASTQ BAM on disk — the lazy merge needs it.
        self.calculate_and_record_coverage(sorted_bam_output, timestamp)

    def process_bam_file(self, bam_path: str, timestamp: str = None):
        """Fold an externally-produced BAM into the rolling accumulator.

        The BAM must already be sorted (FileHandler does no sort here —
        minimap2's `samtools sort` step does that for the FASTQ path;
        external BAMs are assumed to be coordinate-sorted upstream by
        the producer). We always (re-)index because the accumulator
        needs the index, even if the producer didn't ship one.
        """
        if not self.is_bam_valid(bam_path):
            logger.error(f"Skipping invalid BAM file: {bam_path}")
            return
        # Copy into runs/ so the lazy-merge picks it up alongside FASTQ-derived BAMs.
        os.makedirs(self.runs_dir, exist_ok=True)
        target = os.path.join(self.runs_dir, f'{os.path.basename(bam_path)}_sorted.bam')
        if bam_path != target:
            shutil.copy(bam_path, target)
            # Bring along the producer's .bai if they shipped one.
            src_bai = bam_path + '.bai'
            if os.path.exists(src_bai):
                shutil.copy(src_bai, target + '.bai')
        if not self._ensure_bam_index(target):
            return
        self.calculate_and_record_coverage(target, timestamp)

    def _ensure_bam_index(self, bam_path: str) -> bool:
        """Make sure a `.bai` sibling exists for `bam_path`. Returns
        True on success, False on failure (the caller should skip the
        rest of the batch).

        Cheap to call repeatedly — if the index is already present and
        newer than the BAM, we skip the subprocess. The mtime check
        guards against a stale `.bai` from an interrupted previous run.
        """
        if not os.path.exists(bam_path):
            return False
        bai = bam_path + '.bai'
        if os.path.exists(bai) and os.path.getmtime(bai) >= os.path.getmtime(bam_path):
            return True
        try:
            subprocess.run(['samtools', 'index', bam_path], check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"samtools index failed for {bam_path}: {e}")
            return False

    def get_index_file(self) -> str | None:
        """Resolve the classifier's index path.

        Preferred source: `alertinfo.cfg['indexPath']`, written by
        `tasks.int_download_database` after `classifier.build_index()`
        runs. Non-minimap2 plug-ins may produce files with arbitrary
        extensions (or even directories), so the explicit path is the
        only correct lookup in general.

        Fallback: legacy projects whose alertinfo.cfg predates the
        classifier protocol have no `indexPath` key but do have an
        `.mmi` under `database/`. Glob for that so existing setups
        keep working without a manual migration.
        """
        cfg_path = self.config.get('indexPath')
        if cfg_path and os.path.exists(cfg_path):
            return cfg_path
        files = glob.glob(os.path.join(self.app_loc, 'database', '*.mmi'))
        if files:
            return files[0]
        logger.error(
            "No classifier index found — neither alertinfo.cfg['indexPath'] "
            f"nor a fallback *.mmi under {self.app_loc}/database/"
        )
        return None

    def calculate_and_record_coverage(self, batch_bam_path: str, timestamp: str = None):
        """Fold one batch BAM into the rolling accumulator, then emit
        the same coverage_update / alerts / coverage.csv-row work the
        previous merged-BAM code path did.

        `batch_bam_path` is the per-FASTQ sorted BAM that was just
        produced. We open it once to extract this batch's depth and
        feed it to the accumulator; aggregate stats then come straight
        from the accumulator without touching any larger file. Region
        alerts slice the accumulator directly — no second BAM pass.
        """
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        try:
            with pysam.AlignmentFile(batch_bam_path, "rb", check_sq=False) as batch_bam:
                self.coverage_acc.update_from_bam(batch_bam)
            self.coverage_acc.save()

            coverage_data = {}
            for ref in self.coverage_acc.refs():
                depth_coverage, breadth_coverage, read_count = self.coverage_acc.stats(ref)
                coverage_data[ref] = {
                    "depth": depth_coverage,
                    "breadth": breadth_coverage,
                    "read_count": read_count,
                }
                logger.debug(
                    f"Reference: {ref}, Depth Coverage: {depth_coverage:.2f}x, "
                    f"Breadth Coverage: {breadth_coverage:.2f}%, Read Count: {read_count}"
                )
                self.check_coverage_alerts(ref, depth_coverage, breadth_coverage)

                # Region-specific coverage and alerts. Dedup-keyed on
                # f"{ref}_region_{id}_depth" so an over-threshold region
                # fires once per run, not once per FASTQ batch. Slices
                # the accumulator instead of re-running count_coverage
                # on a BAM (which used to be the cumulative merged BAM
                # — see LOGBOOK section 4.1).
                if ref in self.regions_data:
                    query = self.header_to_query.get(ref)
                    default_threshold = float(query.get("depth_threshold", 0)) if query else 0
                    depth_arr = self.coverage_acc.depth_array(ref)
                    for region in self.regions_data[ref]:
                        if not region.get('alert_enabled', False):
                            continue
                        start = region['start']
                        end = region['end']
                        region_id = region.get('id', f'{start}-{end}')
                        region_length = end - start + 1
                        if depth_arr is None or region_length <= 0:
                            continue
                        # GFF is 1-based inclusive; numpy is 0-based half-open.
                        region_slice = depth_arr[start - 1:end]
                        region_total_depth = int(region_slice.sum())
                        region_depth_coverage = region_total_depth / region_length

                        threshold = float(region.get('threshold', default_threshold))
                        if region_depth_coverage < threshold:
                            continue

                        alert_key = f"{ref}_region_{region_id}_depth"
                        if self._check_if_alert_sent(alert_key):
                            logger.debug(f"Region depth alert {alert_key} already sent, skipping")
                            continue

                        alert_str = (
                            f"Alert: Region {region_id} in {ref} depth coverage reached "
                            f"{region_depth_coverage:.2f}x (threshold: {threshold}x)"
                        )
                        logger.critical(alert_str)
                        self._send_notifications(alert_str)
                        self._mark_alert_as_sent(alert_key, {
                            'type': 'region_depth',
                            'reference': ref,
                            'region_id': region_id,
                            'value': region_depth_coverage,
                            'threshold': threshold,
                        })

            coverage_data['unmapped'] = {
                "depth": 0.0,
                "breadth": 0.0,
                "read_count": self.coverage_acc.unmapped_count,
            }

            with open(self.coverage_file, 'a') as f:
                for ref, cov in coverage_data.items():
                    f.write(f"{timestamp},{ref},{cov['depth']},{cov['breadth']},{cov['read_count']}\n")
            logger.debug(f"Coverage and read counts recorded at {timestamp}")

            emit_payload = {
                'projectId': self.config.get('projectId', ''),
                'timestamp': timestamp,
                'coverage': coverage_data,
            }

            def _emit_updates(payload):
                try:
                    socketio.emit('coverage_update', payload)
                    socketio.emit('run_health_update', {
                        'projectId': payload.get('projectId', ''),
                        'timestamp': payload.get('timestamp', ''),
                    })
                except Exception as exc:
                    logger.warning(f"emit failed (non-fatal): {exc}")

            # Use the SocketIO server's own task spawner. With eventlet async
            # mode this schedules a greenlet on the hub, which is the only
            # documented thread-safe way to call socketio.emit from outside
            # an existing greenlet (we're being called from a watchdog
            # native thread). A raw threading.Thread "mostly works" but
            # messages occasionally never reach the client — which is what
            # caused the file-progress badge to need a page reload.
            socketio.start_background_task(_emit_updates, emit_payload)
        except Exception as e:
            logger.error(f"Error calculating coverage: {e}", exc_info=True)

    def check_coverage_alerts(self, ref: str, depth_coverage: float, breadth_coverage: float):
        """Check if depth coverage exceeds the threshold and trigger alerts if necessary."""
        logger.debug(f"Checking alerts for {ref}: Depth {depth_coverage}, Breadth {breadth_coverage}")
        query = self.header_to_query.get(ref)
        logger.debug(f"header_to_query keys: {list(self.header_to_query.keys())}")
        logger.debug(query)
        if query:
            if query.get("alert_on_depth", False):
                depth_threshold = float(query.get("depth_threshold", 0))
                if depth_coverage >= depth_threshold:
                    alert_key = f"{ref}_depth"
                    if not self._check_if_alert_sent(alert_key):
                        alert_str = f"Alert: {query['name']} - {ref} depth coverage reached {depth_coverage:.2f}x (threshold: {depth_threshold}x)"
                        logger.critical(alert_str)
                        self._send_notifications(alert_str)
                        self._mark_alert_as_sent(alert_key, {
                            'type': 'depth',
                            'reference': ref,
                            'value': depth_coverage,
                            'threshold': depth_threshold
                        })
                    else:
                        logger.debug(f"Depth alert for {alert_key} already sent, skipping")
            if query.get("alert_on_breadth", False):
                breadth_threshold = float(query.get("breadth_threshold", 0))
                if breadth_coverage >= breadth_threshold:
                    alert_key = f"{ref}_breadth"
                    if not self._check_if_alert_sent(alert_key):
                        alert_str = f"Alert: {query['name']} - {ref} breadth coverage reached {breadth_coverage:.2f}% (threshold: {breadth_threshold}%)"
                        logger.critical(alert_str)
                        self._send_notifications(alert_str)
                        self._mark_alert_as_sent(alert_key, {
                            'type': 'breadth',
                            'reference': ref,
                            'value': breadth_coverage,
                            'threshold': breadth_threshold
                        })
                    else:
                        logger.debug(f"Breadth alert for {alert_key} already sent, skipping")
            

    def _send_notifications(self, alert_str: str):
        device = self.config.get("device", "")
        alert_notif_config = self.config.get("alertNotifConfig", {})

        if device:
            try:
                LinuxNotification.send_notification(device, alert_str)
            except Exception as e:
                logger.error(f"Failed to send Linux notification: {e}")

        if alert_notif_config.get("enableEmail", False):
            email_config = alert_notif_config.get("emailConfig", {})
            if all(key in email_config for key in ["sender", "recipient", "smtpServer", "smtpPort", "password"]):
                try:
                    send_email("nanoCAS Alert", alert_str, email_config)
                except Exception as e:
                    logger.error(f"Failed to send email notification: {e}")
            else:
                logger.error("Email configuration is incomplete.")

        if alert_notif_config.get("enableSMS", False):
            sms_recipient = alert_notif_config.get("smsRecipient", "")
            if sms_recipient:
                try:
                    send_sms(alert_str, sms_recipient)
                except Exception as e:
                    logger.error(f"Failed to send SMS notification: {e}")
            else:
                logger.error("SMS recipient phone number is missing.")

    def _record_processed(self, file_path: str):
        """Mark `file_path` as fully processed: add to in-memory set, append
        to processed_files.txt, release any in-progress claim, and notify
        the UI over Socket.IO.

        Centralised so the bookkeeping stays identical for both the watchdog
        dispatch path (`_handle_path`) and the startup catch-up loop
        (`process_existing_files`).
        """
        with self.processed_files_lock:
            self.processed_files.add(file_path)
            self.in_progress_files.discard(file_path)
            with open(self.processed_files_path, 'a') as f:
                f.write(file_path + '\n')
            count = len(self.processed_files)
        self._emit_file_progress(count, file_path)

    def _emit_file_progress(self, count: int, file_path: str):
        """Push a progress update so the UI can show the processed-file count
        and the most recent filename next to the Monitoring badge.

        Dispatched through `socketio.start_background_task` so the emit runs
        on an eventlet greenlet in the hub — calling socketio.emit directly
        from a watchdog native thread is undocumented behaviour and was
        sometimes losing messages, which made the badge appear stale until
        the user manually reloaded the page.
        """
        payload = {
            'projectId': self.config.get('projectId', ''),
            'files_processed': count,
            'last_file': os.path.basename(file_path),
            'last_file_full_path': file_path,
        }

        def _do_emit(p):
            try:
                socketio.emit('file_progress_update', p)
            except Exception as exc:
                logger.warning(f"file_progress emit failed (non-fatal): {exc}")

        socketio.start_background_task(_do_emit, payload)

    def get_existing_files(self, directory):
        """Get list of existing files of the specified type, sorted by modification time."""
        if self.file_type == 'FASTQ':
            extensions = FASTQ_EXTENSIONS
        elif self.file_type == 'BAM':
            extensions = BAM_EXTENSIONS
        else:
            return []

        files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(extensions)]
        with self.processed_files_lock:
            files = [f for f in files if f not in self.processed_files]
        files.sort(key=lambda x: os.path.getctime(x))
        return files

    def process_existing_files(self, directory):
        """Process existing files in the directory before starting the observer."""
        files = self.get_existing_files(directory)
        for file in files:
            try:
                mtime = os.path.getmtime(file)
                timestamp = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                if self.file_type == 'FASTQ':
                    self.process_fastq_file(file, timestamp)
                elif self.file_type == 'BAM':
                    self.process_bam_file(file, timestamp)
                self._record_processed(file)
            except Exception as e:
                logger.error(f"Error processing existing file {file}: {e}", exc_info=True)
