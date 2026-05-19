# nanoCAS — Developmental Logbook & Code Audit

> A comprehensive walkthrough of what the app does, how every piece is wired together, and a frank list of the design flaws that need to be addressed before this is a robust diagnostic instrument.
>
> Author of this audit: Claude (Opus 4.7) — read every file under `server/` and `frontend/src/` end-to-end.
> Date: 2026-05-19

---

## Part 1 — What the app actually is

### 1.1 Purpose (biological framing)

nanoCAS (Nanopore Classification & Alerting System) is designed to run **alongside a live Oxford Nanopore sequencing run** (MinION Mk1B/Mk1C, GridION, PromethION) and notify the user the *moment* a sequence of interest crosses a coverage threshold. The target use case is **pathogen / contamination detection in field diagnostics**: a sample of interest is sequenced, and the operator does not want to babysit the run for hours — they want a phone/email/MinKNOW notification when the bug they're hunting actually shows up in the data.

The current implementation realises a narrow slice of that vision:

| Capability | Status |
|---|---|
| Watch a directory for new FASTQ / BAM files | ✅ implemented |
| Align reads to a user-provided reference set (FASTA) | ✅ implemented (minimap2 only) |
| Track depth and breadth of coverage per reference over time | ✅ implemented |
| Fire alerts when depth or breadth crosses a threshold | ✅ implemented (with a deadlock bug — see §3) |
| Per-region alerts driven by GFF | ✅ implemented (but no de-duplication of alerts) |
| Run-quality / pore-health dashboard | ✅ partial — parsed from `sequencing_summary.txt` only |
| Pluggable classifier (Kraken2, Centrifuge, BWA, …) | ❌ not yet — minimap2 is hard-coded |
| Alert if pores are dying / ATP depleting / run quality crashing | ❌ not yet — only static Q-score histograms |
| Live MinKNOW state (real pore activity, mux scans) | ❌ not used (only notifications) |
| POD5 / FAST5 support, basecalling | ❌ not yet — assumes basecalled FASTQ already on disk |

### 1.2 End-to-end user flow

1. **Open the web UI** at `http://localhost:3000` (dev) or `:5000` (Replit). The home page is a project list.
2. **Create a new project** through the 3-step setup wizard:
   - *Database setup* — pick the nanopore output directory, upload one or more reference FASTA files, optionally upload a GFF, set a depth and/or breadth threshold per query, optionally pick a MinKNOW device for in-instrument notifications.
   - *Notification setup* — toggle email (SMTP) and SMS (Twilio).
   - *Summary* — confirm and create. The backend writes `~/.nanocas/<projectId>/alertinfo.cfg`, builds a minimap2 `.mmi` index from the selected references in a background thread, and initialises `coverage.csv`.
3. **Open the project**, hit **Start Monitoring**. A `FileHandler` and a `watchdog` `Observer` are created; existing files in the directory are processed in a worker thread, and new files trigger live processing.
4. **The Coverage tab** polls `/get_coverage` every 10s and listens to the `coverage_update` socket event. It renders a Google Charts line plot of depth/breadth over elapsed time, with a dashed red threshold line. Below it, an SVG-based alignment viewer shows reads stacked over the selected reference, with GFF regions overlaid.
5. **The Run Health tab** polls `/run_health` every 15s. It parses `sequencing_summary.txt` (produced by MinKNOW) and renders Chart.js histograms for Q-score and read length, a line chart for median-Q over time, and a pore-health summary card.
6. **The Alerts tab** is mostly informational (threshold table, notification toggles) plus a Danger-Zone "Remove Analysis" button.

### 1.3 What happens on disk

`~/.nanocas/` is the workspace root:

```
~/.nanocas/
├── .cache                          # tab-separated index: projectId<TAB>minionDir<TAB>nanocasDir
├── nanopore_data/                  # default directory the wizard suggests for "watch this folder"
└── <projectId>/                    # one per project (UUID4)
    ├── alertinfo.cfg               # JSON dump of the full setup form (queries, thresholds, device, notif config, …)
    ├── database/
    │   └── <timestamp>.mmi         # minimap2 index built from the queries
    ├── minimap2/runs/              # transient per-FASTQ sorted BAMs (deleted after merge)
    ├── merged.bam                  # cumulative aligned reads
    ├── merged.bam.bai
    ├── merged_stable.bam           # a *copy* of merged.bam used for safe reads
    ├── merged_stable.bam.bai
    ├── coverage.csv                # one row per (timestamp, reference) — the chart's source
    ├── processed_files.txt         # newline-delimited list of FASTQs already seen
    ├── sent_alerts.json            # de-dup state for fired alerts
    ├── regions.json                # GFF regions metadata
    └── gff_file.gff                # the user's uploaded GFF
```

---

## Part 2 — How the app is built

### 2.1 Tech stack

**Backend** (`server/`)
- **Python 3.10+** (pyproject says 3.12, server/requirements.txt is compatible with 3.10).
- **Flask 2.3.3** + **flask-cors** for the REST surface.
- **flask-socketio 5.3.6** on **eventlet 0.39.1** — this is the realtime spine. The frontend is forced into `transports: ['polling']` (see `app.component.tsx:15`), so the eventlet async worker is mostly a coincidence; long-polling would also work on a stock dev server.
- **watchdog 6.0** — filesystem event loop. The `Observer` runs one dispatch thread per directory.
- **pysam 0.23** — Python bindings for HTSlib (samtools/BCF). Used for BAM validation, `count_coverage`, `fetch`.
- **biopython 1.86** — `SeqIO.parse` for FASTA reading when building the index.
- **minknow_api 6.2.1** — gRPC client to MinKNOW. Currently used **only** to (a) enumerate connected flow-cell positions and (b) push a `notify-send` + log message to the instrument. None of the live device state (channel mux, run config, basecalling progress) is consumed.
- **twilio** — SMS.
- **redis + celery** are *in* `requirements.txt` and `pyproject.toml`, but **nothing actually imports them**. The database-build was moved to an in-process `Thread` (see `events.py:_build_database_task`). The Celery/Redis dependency is dead code.

**Frontend** (`frontend/`)
- **React 17 + TypeScript** (Create React App).
- **react-router-dom v5** — routes: `/`, `/setup`, `/project/:id/:tab?`.
- **react-bootstrap** for layout primitives (Modal, Dropdown, Form).
- **chart.js + react-chartjs-2** for Run Health charts.
- **react-google-charts** for the Coverage time-series chart. (Two charting libraries in the same app — see §4.)
- **socket.io-client** for live updates.
- **axios** for REST calls.

**External binaries** required on `$PATH`:
- `minimap2` — alignment & indexing.
- `samtools` — merge, sort, index BAMs.
- `notify-send` (Linux) — desktop notifications.

### 2.2 Module-by-module map

#### Entry point — `server/nanocas.py`
Bootstraps Flask via `create_app()`, attaches a stdout logger, and calls `socketio.run(app, host='0.0.0.0', port=$BACKEND_PORT)`. The port defaults to 5007 in the script but the env files use 8000 (Replit) — a config-source drift you'll want to consolidate.

#### `server/app/__init__.py`
Creates the Flask app, registers the `main` blueprint, attaches `SocketIO`. CORS is wide open (`origins="*"`).

#### `server/app/main/routes.py`
HTTP endpoints. The interesting ones:

| Route | Method | Purpose |
|---|---|---|
| `/version` | GET | Trivial. |
| `/check_database_status` | GET | Returns `is_ready` based on the presence of any `.mmi` in `database/`. |
| `/get_timeline_info` | GET | Reads `~/.nanocas/analysis.timeline` for two integers. **Dead path** — no one writes to that file in the current code. |
| `/get_uid`, `/get_all_analyses`, `/delete_analyses`, `/get_analysis_info` | mixed | CRUD over the tab-separated `.cache` file. |
| `/analysis` | GET | Legacy server-rendered template route (`render_template('analysis.html', …)`). The React frontend never calls this. Dead/legacy. |
| `/get_default_nanopore_path` | GET | `mkdir -p ~/.nanocas/nanopore_data` and return it. |
| `/upload_reference`, `/upload_fasta`, `/upload_gff` | POST | File uploads. `/upload_reference` sanitises with `os.path.basename`; the other two do **not** — path-traversal vulnerable (see §5). |
| `/parse_fasta_headers` | POST | Reads a FASTA and returns its `>` header lines. Used by the setup wizard to populate the "which sequences to use" dropdown. |
| `/validate_locations` | POST | `mkdir -p` for both the workspace and the minION directory. |
| `/get_coverage` | GET | Reads `<projectId>/coverage.csv` line-by-line and returns rows as JSON. |
| `/get_alignments` | GET | Opens `merged_stable.bam` with pysam, fetches alignments overlapping the chosen reference, parses GFF for regions, returns both. |
| `/index_devices` | GET | Enumerates MinKNOW positions, **sends a "Device discovered" notification to every one** as a side effect — surprising for a GET (see §5). |
| `/scan_directory` | POST | Walks a directory and inventories `.fastq`, `.bam`, `.pod5`, `.fast5`, `sequencing_summary*`. |
| `/run_health` | GET | Parses `sequencing_summary.txt` for Q-score and read-length stats and rough pore occupancy. |

#### `server/app/main/events.py`
SocketIO handlers + the live file-watcher orchestration:

- `start_fastq_file_listener` — creates a `FileHandler` and a `watchdog.Observer`, kicks off `process_existing_files` in a thread, schedules the observer on the minion directory. Tracks observers in a global `observers: dict[projectId, Observer]`.
- `stop_fastq_file_listener` — `observer.stop()` + `observer.join()`.
- `download_database` — main project-creation entry. Wipes `~/.nanocas/<projectId>/`, moves the uploaded GFF in, writes `alertinfo.cfg`, then spawns `_build_database_task` in a background thread (no Celery — the README in §2.1 of the project's README is misleading). Progress is pushed back over the socket.
- `remove_analysis` — `rmtree` the project directory and strip its entry from `.cache`.
- Misc: `log` (echo-to-server-logger), `check_fastq_file_listener` (status ping).

#### `server/app/main/utils/FileHandler.py` — **the heart of the live pipeline**
A `watchdog.FileSystemEventHandler` subclass. On every filesystem event it:

1. Calls `on_moved` (for atomic-rename creation, which is how MinKNOW writes) or `on_any_event` (created/modified).
2. `_handle_path(file_path)`:
   - Acquires `processed_files_lock`. If the file is already processed or already in-flight, return. Otherwise, claim it by inserting into `in_progress_files`.
   - `wait_for_file_stability(path)` — polls size for up to 60s, returns once two consecutive reads match.
   - `process_fastq_file` (or `process_bam_file`).
   - Promote to `processed_files`, persist to `processed_files.txt`.
   - `finally`: always discard from `in_progress_files`.
3. `process_fastq_file`:
   - Build the minimap2 command as a **shell string**: `minimap2 -a {index_file} {src_path} | samtools view -b | samtools sort -o {sorted}` and run with `shell=True`. Output → `<projectId>/minimap2/runs/<basename>_sorted.bam`.
   - `is_bam_valid` (pysam quickcheck).
   - `merge_bam(sorted_bam)`.
   - `calculate_and_record_coverage(timestamp)`.
   - Delete the per-FASTQ sorted BAM.
4. `merge_bam`:
   - If `merged.bam` doesn't exist yet, copy the new BAM in.
   - Otherwise `samtools merge temp_merged.bam merged.bam new.bam`.
   - `samtools sort temp_merged -o merged_sorted.bam`, `samtools index`.
   - `shutil.move(merged_sorted.bam, merged.bam)` then `shutil.copy(merged.bam, merged_stable.bam)` (and same for the `.bai`).
5. `calculate_and_record_coverage`:
   - Opens `merged_stable.bam`.
   - For each reference: compute `depth_coverage = sum(count_coverage) / ref_length`, `breadth = covered_positions / ref_length * 100`, `read_count = bam.count(ref)`.
   - Call `check_coverage_alerts(ref, depth, breadth)`.
   - If the reference appears in `regions_data`, iterate every region; if `alert_enabled`, recompute coverage on the slice and fire `_send_notifications` **with no de-duplication**.
   - Append rows to `coverage.csv`.
   - `Thread(target=_emit_updates).start()` to push the `coverage_update` and `run_health_update` socket events.
6. `check_coverage_alerts`:
   - Looks up `query = header_to_query.get(ref)`.
   - If `alert_on_depth` and depth ≥ threshold and `_check_if_alert_sent` is False: send notifications, mark sent.
   - Same for breadth.
7. `_send_notifications`:
   - If a MinKNOW device is configured: `LinuxNotification.send_notification` (which does `device.connect()` over gRPC + `notify-send` + `log.send_user_message`).
   - If email enabled and config complete: `send_email` (SMTP, **synchronous**).
   - If SMS enabled: `send_sms` (Twilio REST, **synchronous**).

#### `server/app/main/utils/tasks.py` — database build
Runs in a background thread (via `events.py:_build_database_task`). For each query:
- Open the uploaded FASTA, write the records matching the requested header(s) into a single combined FASTA.
- `minimap2 -x map-ont -d <db>.mmi <combined>.fa`.
- Initialise `coverage.csv` with a header row.
- Push progress callbacks (`5%`, `5..50%` per-query, `55%`, `100%`).
- `finally` block cleans up the temp-upload directories.

#### `server/app/main/utils/directory_scanner.py`
Walks a candidate nanopore output directory and inventories file types. Also parses `sequencing_summary.*` for Q-scores, read lengths, and channel occupancy. Caps at 50 000 reads to keep parse-time bounded.

#### `server/app/main/utils/LinuxNotification.py`
Thin wrapper around `minknow_api.manager.Manager` + a subprocess call to `notify-send`. Despite the name, this is the **only** integration with MinKNOW in the codebase.

#### `server/app/main/utils/email.py` & `sms.py`
`smtplib.SMTP` and `twilio.rest.Client` respectively. Synchronous, no retry, no timeout.

#### Frontend layout
- `app.component.tsx` — sets up the Socket.IO client (polling only), wires the `Router`.
- `modules/project/ProjectList.tsx` — home grid.
- `modules/project/ProjectDetail.tsx` — header (start/stop monitoring button, status pill), tab bar, lazy-loaded tab contents.
- `modules/project/tabs/CoverageTab.tsx` — Google Charts line chart + the SVG alignment viewer.
- `modules/project/tabs/RunHealthTab.tsx` — Chart.js histograms and trend.
- `modules/project/tabs/AlertsTab.tsx` — Threshold table + danger-zone delete.
- `modules/setup/…` — 3-step wizard.
- `modules/analysis/analysis-data/alignment-viewer.component.tsx` — the SVG read-stacking viewer.

### 2.3 Threading model

Three classes of threads in the running server:
1. **eventlet's main green thread** — handles HTTP + the Socket.IO event loop.
2. **`watchdog.Observer` thread** (one per active project) — owns the inotify/FSEvents loop; dispatches each filesystem event sequentially to the `FileHandler`. **If a handler call blocks, the entire observer blocks.** This is the property that makes the §3 bug fatal.
3. **Ad-hoc `threading.Thread` workers** — `process_existing_files` at listener startup; `_build_database_task` for the index build; `_emit_updates` for socket emission inside `calculate_and_record_coverage`.

Mixing native `threading.Thread` with eventlet is a smell — `socketio.emit` from a non-greenlet thread relies on `flask_socketio`'s monkey-patch behaving well, which it sometimes does and sometimes doesn't. The clean replacement is `socketio.start_background_task(...)`.

### 2.4 Data contracts

`alertinfo.cfg` — the canonical project config, dumped verbatim from the React setup form. Keys consumed by the backend:

```json
{
  "projectId": "<uuid>",
  "minion": "/abs/path/to/watch",
  "fileType": "FASTQ" | "BAM",
  "device": "MN12345" | "",
  "gff_file": "/abs/path/to/gff",
  "queries": [
    {
      "name": "human readable",
      "file": "/tmp/uploaded.fa",
      "header": "chr1",         // legacy single
      "headers": ["chr1", "chr2"], // current multi
      "depth_threshold": "100",
      "alert_on_depth": true,
      "breadth_threshold": "90",
      "alert_on_breadth": false
    }
  ],
  "alertNotifConfig": {
    "enableEmail": true,
    "emailConfig": { "sender":"...", "recipient":"...", "smtpServer":"...", "smtpPort": 587, "password":"..." },
    "enableSMS": false,
    "smsRecipient": "+1..."
  }
}
```

`coverage.csv`:
```
timestamp,reference,depth,breadth,read_count
2026-05-19 12:34:56,EBV_genome,1.23,45.6,17
2026-05-19 12:34:56,unmapped,0.0,0.0,832
...
```

`sent_alerts.json` — `{ "<ref>_depth": { "timestamp": "...", "info": {...} }, "<ref>_breadth": {...} }`.

---

## Part 3 — The bug: why mapping stops when depth ≥ threshold

> **TL;DR — there is a self-deadlock on `self.sent_alerts_lock` inside `_mark_alert_as_sent`. The first time any alert fires, the watchdog observer thread acquires the lock, then re-enters it inside `_save_sent_alerts`, and hangs forever. All subsequent filesystem events queue up but are never dispatched, so no further FASTQs are mapped.**

### 3.1 Variable-by-variable walkthrough of the alert pipeline

When a new `.fastq` lands, the watchdog observer fires `on_any_event` → `_handle_path(path)`. Eventually that calls `process_fastq_file` → `merge_bam` → `calculate_and_record_coverage`. Inside the per-reference loop:

```python
self.check_coverage_alerts(ref, depth_coverage, breadth_coverage)
```

`check_coverage_alerts` ([FileHandler.py:382-420](server/app/main/utils/FileHandler.py)):

| Variable | Origin | Role | Notes |
|---|---|---|---|
| `ref` | enumerated from `bam.references` | The reference name minimap2 used. | Comes from FASTA header *exactly as written* — including any whitespace/comment after the first token, which would break the `header_to_query` lookup if the user's FASTA uses long descriptive headers. |
| `query` | `self.header_to_query.get(ref)` | Looks up the configured threshold for this reference. | `header_to_query` is built once in `__init__` from `config['queries']`, by iterating both the `header` (singular) and `headers` (plural) keys. **Quietly returns None if the FASTA header includes a space** — common in NCBI FASTAs (`>NC_000913.3 Escherichia coli K-12 ...`). |
| `depth_threshold` | `float(query.get("depth_threshold", 0))` | Numeric threshold. | Fine. |
| `depth_coverage >= depth_threshold` | computed earlier | Trigger predicate. | Fine. |
| `alert_key` | `f"{ref}_depth"` | De-dup key. | Stable across calls. |
| `self._check_if_alert_sent(alert_key)` | reads `sent_alerts` under `sent_alerts_lock` | De-dup guard. | Holds the lock only for the duration of the `in` test — releases cleanly. |
| `alert_str` | f-string | Human-readable message body. | Fine. |
| `self._send_notifications(alert_str)` | three sequential I/O calls | Side-effecting. | **Synchronous, blocking. No timeouts.** A slow SMTP server (`smtplib.SMTP(...)` with no timeout defaults to indefinitely) can hang the call here, but assume it returns. |
| `self._mark_alert_as_sent(alert_key, info)` | mutates `sent_alerts`, persists to disk | The recording step. | **The deadlock lives here.** |

### 3.2 The deadlock

```python
def _save_sent_alerts(self):                        # FileHandler.py:78
    with self.sent_alerts_lock:                     # acquire #2  ← BLOCKS FOREVER
        with open(self.sent_alerts_path, 'w') as f:
            json.dump(self.sent_alerts, f, indent=2)

def _mark_alert_as_sent(self, alert_key, info):     # FileHandler.py:89
    with self.sent_alerts_lock:                     # acquire #1  (we hold the lock)
        self.sent_alerts[alert_key] = { ... }
        self._save_sent_alerts()                    # ← calls #2 which tries to acquire the same lock
```

`self.sent_alerts_lock = Lock()` is a plain `threading.Lock`, which is **not reentrant**. The second `acquire()` from the *same thread* blocks indefinitely. There is no timeout, no `try`/`finally` short-circuit, no watchdog of the watchdog. The observer thread sits forever in `lock.acquire()` inside `_save_sent_alerts`.

Symptoms a user sees:
- The alert email / SMS / MinKNOW notification **does fire** (because `_send_notifications` is called *before* `_mark_alert_as_sent`).
- The CSV row for the alert-triggering FASTQ **does get written** (because `calculate_and_record_coverage` writes to disk *before* it would emit the `coverage_update`… actually look closer: the alert is fired inside the per-reference loop, **before** the `coverage_data` is written. So actually the CSV row may or may not be written depending on which reference triggered first. In practice the loop is interrupted at the first triggering reference.).
- **Hmm, let me re-check.** `calculate_and_record_coverage`:
   ```python
   for ref in bam.references:
       …compute…
       coverage_data[ref] = {...}
       print(f"Reference: {ref}, …")
       self.check_coverage_alerts(ref, depth, breadth)  # ← deadlocks here
       …regions block…
   …
   with open(self.coverage_file, 'a') as f:
       for ref, cov in coverage_data.items(): …
   ```
   So the CSV write happens **after** the loop. The deadlock occurs inside the loop. **The CSV row is never appended** for the file that triggered the alert, and the socket `coverage_update` is never emitted either. From the UI you'll see: chart line stops moving, monitoring badge still says "Monitoring", file watcher count freezes.
- All subsequent file-create events queue up in the watchdog dispatcher but are never handled. `processed_files.txt` does not grow. New FASTQs accumulate on disk untouched.

### 3.3 What confused things further

- The lock is named `sent_alerts_lock`, suggesting "protects the sent alerts dict". But the JSON-write half (`_save_sent_alerts`) shouldn't even need that protection if the in-memory mutation under the lock already serialised everything. The lock is over-applied, which is what enabled the re-entry.
- `_load_sent_alerts` is called from `__init__` and reads the JSON without taking the lock — a benign inconsistency, but more evidence that the locking scheme wasn't fully thought through.
- The region-alert branch (`if region_depth_coverage >= threshold: self._send_notifications(alert_str)`) does **not** call `_mark_alert_as_sent`, so the deadlock wouldn't fire from there — but that means region alerts will spam every cycle.

### 3.4 The fix (smallest possible patch)

Either:

**(a)** Remove the inner `with self.sent_alerts_lock:` — the outer caller already holds it. Make `_save_sent_alerts` a pure I/O helper:

```python
def _save_sent_alerts_unlocked(self):
    """Caller must hold sent_alerts_lock."""
    with open(self.sent_alerts_path, 'w') as f:
        json.dump(self.sent_alerts, f, indent=2)

def _mark_alert_as_sent(self, alert_key, info):
    with self.sent_alerts_lock:
        self.sent_alerts[alert_key] = {'timestamp': datetime.datetime.now().isoformat(), 'info': info}
        self._save_sent_alerts_unlocked()
```

**(b)** Use `threading.RLock()` instead of `threading.Lock()`. One-character fix, but it papers over the design issue.

I'd take (a). It's still small but it forces a clear contract about who owns the lock, and removes a public method (`_save_sent_alerts`) that nobody but the internals should be calling anyway.

While in there, also fix the **collateral damage**:
- Wrap `_send_notifications` in a `Thread` (or `socketio.start_background_task`) so that SMTP / Twilio / MinKNOW latency can never block the watchdog dispatcher again, even when it's not deadlocking.
- Add `_check_if_alert_sent` + `_mark_alert_as_sent` to the **region** alert branch so it stops spamming.
- Set `timeout=10` on the `smtplib.SMTP(...)` constructor.
- Set `timeout` on the Twilio client (it accepts an `http_client` with a timeout).

---

## Part 4 — Other flaws worth fixing

These are ordered roughly by impact. Each entry: what's wrong, why it matters in a real diagnostic context, and a concrete suggestion.

### 4.1 The merge pipeline is O(n²) and rebuilds everything on every FASTQ

`merge_bam` does, per incoming FASTQ:
1. `samtools merge temp_merged.bam merged.bam new.bam` — re-reads the entire cumulative BAM.
2. `samtools sort temp_merged.bam -o merged_sorted.bam` — re-sorts everything.
3. `samtools index merged_sorted.bam`.
4. `shutil.copy(merged.bam, merged_stable.bam)` — duplicates the whole file on disk.

A typical MinION run produces FASTQs in batches of ~4000 reads, every ~30s, for 24-72 hours. By hour 6 you're re-merging and re-sorting a multi-gigabyte BAM every 30 seconds. **This is the dominant performance bottleneck**, and on PromethION-scale data it will fall over completely.

**Suggestion**: Don't maintain a single growing merged BAM at all. Either:
- Keep all sorted per-FASTQ BAMs in `minimap2/runs/` and merge **lazily** when the coverage tab is opened — `samtools depth -b regions.bed *.bam` is O(reads), not O(reads²), and pysam can `AlignmentFile` a stream of them.
- Or use a **rolling coverage accumulator**: maintain a numpy `int32` array per reference (`ref_length` long) and just add per-FASTQ pileups into it. You never need a merged BAM at all for coverage. The alignment viewer can fetch from per-batch BAMs on demand.
- If you must keep a merged BAM, use `samtools cat` (which is O(n) and doesn't re-sort) and only re-sort + index every Nth batch.

The `merged_stable.bam` duplicate is also wasteful — a single sorted BAM, opened read-only with pysam, is safe to read while a *new* BAM is being constructed under a temp name and `mv`-renamed. The whole "stable copy" pattern can go.

### 4.2 No timeouts on any I/O

- `smtplib.SMTP(smtp_server, smtp_port)` — defaults to OS socket timeout, often "forever".
- `twilio.rest.Client` — no `http_client` timeout configured.
- `subprocess.run([...samtools merge...], check=True)` — no `timeout=` parameter.
- `MinKNOW Manager(host=, port=)` — no timeout.
- `wait_for_file_stability` does have a `timeout=60` ✓.

**Suggestion**: add `timeout=10` (or 30 for network) to every external call. A diagnostic instrument that wedges because Gmail is slow is unacceptable.

### 4.3 No classifier abstraction (the modular-tools requirement from the user)

`FileHandler.process_fastq_file` hard-codes minimap2 as a single f-string with `shell=True`. The roadmap calls for Kraken2, Centrifuge, BWA, BLAST, etc. Each of those has a different output format (Kraken2 has its own report format with taxon IDs; Centrifuge uses NCBI taxonomy; minimap2 emits SAM; BWA emits SAM; BLAST emits tabular outfmt6).

**Suggestion**: define a `Classifier` protocol something like:

```python
class Classifier(Protocol):
    name: str

    def build_index(self, reference_paths: list[Path], output_dir: Path,
                    progress: ProgressCallback) -> Path:
        """Return the index path. Idempotent."""

    def classify(self, fastq: Path, index: Path, workdir: Path) -> ClassificationResult:
        """Run classification on one FASTQ batch. Must NOT mutate global state."""

class ClassificationResult(TypedDict):
    sorted_bam: Path | None       # for alignment-based classifiers
    taxa_counts: dict[int, int]   # for k-mer classifiers, taxon_id -> read_count
    per_read_assignments: Path    # tsv: read_id, taxon_id_or_ref, score
```

Then `FileHandler` calls `self.classifier.classify(fastq, index, workdir)` and updates a unified `coverage_or_abundance.csv` based on the result. Built-in implementations: `Minimap2Classifier`, `Kraken2Classifier`, `CentrifugeClassifier`. Users with a custom classifier subclass `Classifier`, drop it into a plugins directory, and reference it by name in `alertinfo.cfg`.

The alert configuration also needs to generalise: for k-mer classifiers, "depth coverage" doesn't apply — you want "read count" or "relative abundance" or "fraction of reads classified as taxon X". Make the alert predicate a small DSL or a callable on the result struct.

### 4.4 Real run-health monitoring is missing

The user's roadmap mentions: alert if "pores are dead, ATP depleted, or run is consistently low quality". Today, the Run Health tab only parses `sequencing_summary.txt`, which:
- is only written by MinKNOW **at the end of each batch**, not in real time;
- doesn't reflect the live pore state at all — `pore_health` in the response is just "channels seen so far in this summary file";
- assumes 512 channels in `get_pore_health` (`total = max(len(channels_seen), 512)`) — wrong for GridION (5 × 512 = 2560), PromethION (3000 per cell × 24 or 48 cells).

**Suggestions**:
- Use the **MinKNOW API live** instead of (or in addition to) the summary file. `minknow_api.acquisition.AcquisitionService` exposes `get_acquisition_run_info`, `watch_engine_states`, and most importantly `get_progress` (basecalling progress, mux scan state). `minknow_api.statistics.StatisticsService.stream_acquisition_output` and `stream_temperature_engine_stats` give live channel-state breakdowns.
- The hard part is that this is *all gRPC*, so you'd want a long-lived `Thread`/greenlet streaming each update and emitting `pore_state_update` over Socket.IO.
- For Q-score / quality-trend alerts, the right primitive is a **rolling window** (e.g., last 5 minutes) and a configurable rule: "alert if median Q over the last N reads drops below X". Push it through the same `Classifier`-like protocol so the user can configure custom rules.
- Channel-count assumption: pull it from MinKNOW (`Manager.flow_cell_positions()` → `device.connect().device.get_flow_cell_info()`) instead of hard-coding 512.

### 4.5 Reuse a mature run-QC library (seqfu2 or NanoStat / NanoPlot)

You suggested `seqfu2`. It's a fine choice — single binary, fast, and handles gz inputs natively. Alternatives:
- [**NanoStat** / **NanoPlot**](https://github.com/wdecoster/NanoPlot) (`pip install nanoplot`) — purpose-built for ONT data, produces the same kind of read-length × Q-score plots out of the box. Pure Python, easy to call from `subprocess`.
- [**chopper**](https://github.com/wdecoster/chopper) (formerly NanoFilt) — Rust, very fast, for quality filtering.
- [**fastp**](https://github.com/OpenGene/fastp) — fast, emits JSON summary you can drop straight into the dashboard.

A practical hybrid: use **fastp** or **NanoStat** to produce a JSON QC summary **per incoming FASTQ batch**, persist them, and aggregate in the backend. This sidesteps the "parse sequencing_summary.txt" approach entirely and works for any FASTQ source, not just MinKNOW-with-summary.

### 4.6 SocketIO + threading is finicky; backpressure is missing

- `_emit_updates` spawns a fresh `threading.Thread` on every coverage update. On a fast-running PromethION batch you can fire dozens per minute. `socketio.start_background_task(...)` is the eventlet-native equivalent and integrates with the worker pool.
- There's no rate-limiting on emits, no debouncing. If 20 FASTQs land in one second, the frontend gets 20 `coverage_update` events and polls `/get_coverage` 20 times — and the chart re-renders 20 times.
- Frontend transports are forced to `polling`. That defeats most of the point of Socket.IO. Remove the constraint and let it upgrade to websocket; if you're on Replit and websockets don't work, fall back is automatic.

**Suggestion**: replace the per-update `Thread` with `socketio.start_background_task`, and debounce emits to ≤ 1/s using a small `time.monotonic()` gate. Frontend: switch to `['websocket', 'polling']`.

### 4.7 Per-file alerts but no per-region de-duplication

`calculate_and_record_coverage` fires `_send_notifications(alert_str)` for **every** region that's above threshold, **on every coverage recompute** (i.e., once per FASTQ). Once the user crosses the region threshold, they'll get an email/SMS per FASTQ for the rest of the run. Not just annoying — Twilio costs money per SMS.

**Suggestion**: route region alerts through the same `_check_if_alert_sent`/`_mark_alert_as_sent` machinery, with `alert_key = f"{ref}_region_{region['id']}_depth"`.

### 4.8 Path-traversal in upload + per-project endpoints

- `/upload_fasta` and `/upload_gff` save `file.filename` directly under a freshly-`mkdtemp`'d directory. The filename isn't sanitised — `werkzeug.utils.secure_filename(...)` exists for exactly this. Today, a malicious filename like `../../../../etc/cron.d/evil` could escape the temp dir. Mitigated by `mkdtemp` being random per upload, but still — fix it.
- `/get_coverage`, `/get_alignments`, `/check_database_status` accept `projectId` from query string and `os.path.join(NANOCAS_DIR, project_id, …)` directly. If `projectId` is `../something`, you read elsewhere. The `/run_health` endpoint **does** sanitize via `_is_safe_path` — apply the same guard to those three.

### 4.9 CSV-based coverage is fragile

- No locking on `coverage.csv` writes. `process_existing_files` and the watchdog thread can append concurrently — rare in practice (existing files are processed before the observer starts) but possible during a restart.
- One row per `(timestamp, reference)` — a project with 200 references and 24h of 30s batches is ~575 000 rows. Parsing it on every `/get_coverage` (which the frontend polls every 10s) is wasteful.
- The frontend reconstructs a `Map<string, any>` from the entire array every poll.

**Suggestion**: store coverage in **SQLite** (or DuckDB if you want analytical queries). One table `coverage(timestamp, reference, depth, breadth, read_count)`, indexed on `(reference, timestamp)`. Add a `/get_coverage?since=<ts>&projectId=…` incremental endpoint. Frontend: append-only chart updates instead of re-fetch.

### 4.10 `.cache` is a tab-separated file with no schema

`~/.nanocas/.cache` is the index of all projects. It's a hand-rolled TSV that the code parses by `.split("\t")[0..3]`. Adding any column would break every existing install. `delete_analyses` rewrites it by filtering substring matches — if a UUID happens to be a substring of another path, you'd delete the wrong row.

**Suggestion**: same SQLite database. One table `projects(id, minion_dir, nanocas_dir, created_at, file_type, …)`.

### 4.11 `shell=True` in alignment command

```python
cmd = f'minimap2 -a {index_file} {src_path} | samtools view -b | samtools sort -o {sorted_bam_output}'
subprocess.run(cmd, shell=True, …)
```

In the current architecture the paths come from the server's own `~/.nanocas` directory, so injection requires write access to the workspace anyway. But the pattern is fragile and there's no reason for `shell=True` here.

**Suggestion**: use `subprocess.Popen` chained on file descriptors, e.g.:
```python
p1 = subprocess.Popen(['minimap2', '-a', '-t', '4', index_file, src_path], stdout=subprocess.PIPE)
p2 = subprocess.Popen(['samtools', 'sort', '-@', '4', '-o', sorted_bam_output, '-'], stdin=p1.stdout)
p1.stdout.close()
p2.wait()
```
Also adds `-t 4` and `-@ 4` for parallelism, which the current code is missing.

### 4.12 Dead / stale code

- `celery`, `redis` in `requirements.txt` and `pyproject.toml` — no longer imported anywhere.
- `routes.py:/analysis` route renders an `analysis.html` template — frontend never calls it, no `templates/` directory in the repo.
- `routes.py:/get_timeline_info` reads `~/.nanocas/analysis.timeline` — nothing writes to it.
- `FileHandler.num_files_classified = 0` — set in `__init__`, never read or incremented.
- `server.tar.gz`, `frontend/src.tar.gz`, `my_seq.fasta` in repo root — archive cruft.
- `setup.py` (21k lines), `setup.sh`, `start_nanocas.sh`, `start_nanocas.scpt`, `nanocas_mac_setup.scpt` — multiple parallel install paths; choose one (Docker + a single shell entrypoint) and delete the rest.
- `frontend/src/modules/analysis/` and `frontend/src/modules/home/` — referenced nowhere in the current router; the active UI is `modules/project/*`. Delete after confirming.

### 4.13 `processed_files.txt` grows without bound

Every processed FASTQ is appended as a full absolute path. On a 72h PromethION run you'll have hundreds of thousands of lines, and **the file is re-read into a `set` on every FileHandler construction**. Combined with the open file-descriptor that's appended-to on every dispatch, this is fine but ugly.

**Suggestion**: same SQLite, one row per processed file with a hash of the path. Or just keep the in-memory set and snapshot it every N minutes instead of fsync-on-append.

### 4.14 BAM index regeneration sometimes runs twice in a row

`merge_bam` ends with:
```python
if os.path.exists(sorted_merged_index):
    shutil.move(sorted_merged_index, self.merged_bam + '.bai')
    shutil.copy(self.merged_bam + '.bai', self.stable_bam + '.bai')
else:
    logger.warning(...)
    subprocess.run(['samtools', 'index', self.merged_bam], check=True)
    subprocess.run(['samtools', 'index', self.stable_bam], check=True)
```
If `samtools index` writes a non-standard suffix (it doesn't, but it's possible), the fallback double-indexes. Minor.

### 4.15 Frontend issues

- Two chart libraries (Google Charts + Chart.js + a hand-rolled SVG viewer) — pick one. Chart.js can do the time-series too.
- `frontend/src/app.component.tsx:15` forces `transports: ['polling']` — see §4.6.
- `CoverageTab` calls `setCoverageMap(map)` on every poll and the `useMemo` keyed on `coverageMap` re-creates the chart data every poll. Move the map computation server-side or memoise on length.
- `AlignmentViewer.tsx` mutates the props array in-place (`alignments.sort(...)`). On re-render that's the original prop reference — mutating it can break React's referential equality elsewhere. `[...alignments].sort(...)`.
- No error boundaries; an unhandled error in a tab takes the whole app down.
- `react-router-dom` v5 is two majors behind. Not urgent but you'll hit issues with newer libs.

### 4.16 Security / hygiene

- `app.config['SECRET_KEY'] = 'gjr39dkjn344_!67#'` — checked into the repo. Read it from env.
- `CORS(app, origins="*")` — fine for local dev, must not stay in production.
- `/index_devices` (a GET) **sends a notification to every device** it finds. GETs should be safe to repeat. Move that side-effect to a separate POST.
- `print(...)` calls in `calculate_and_record_coverage` (line 324) leak alignment data to stdout in production logs.

### 4.17 Biology-specific concerns

- **`.fasta` is treated as a FASTQ extension** (`FileHandler.py:138`). FASTAs have no quality scores; mapping a FASTA where you meant FASTQ would silently succeed but produce useless coverage. Either accept it explicitly with a UI flag or refuse it.
- **`.fq` (unzipped FASTQ)** is not accepted (`(".fastq", ".fasta", ".fastq.gz", ".fq.gz")`) — `.fq` is a common dorado/guppy output suffix. Add it.
- **No basecalling step**. MinKNOW now defaults to writing POD5 and basecalling on-demand. If the user points at a directory of POD5s, nanoCAS silently does nothing. Either explicitly detect POD5 (`directory_scanner` already inventories them) and prompt the user to enable basecalling (`dorado`), or call dorado yourself in streaming mode.
- **No adapter trimming, no length / quality filtering**. Pass FASTQs through chopper / fastp before mapping. Filthy adapter reads inflate the unmapped count and skew the coverage metrics on short references.
- **FASTA header lookup matches `record.id` only.** NCBI-style headers (`>NC_000913.3 Escherichia coli K-12 substr. MG1655, complete genome`) split on whitespace; that's fine for `record.id`, but `bam.references` returns `NC_000913.3` while a user typing the header into the wizard may type the whole line. Add a UI fuzzy-match, or normalise to the first whitespace-token both client and server side. Also worth showing the user a preview of which references will actually be indexed.
- **No taxonomic context for alerts.** Right now the alert message says "depth coverage reached X on reference Y". For a clinical / field operator, "FluA matrix gene detected (15× coverage)" is more useful. If the user uploads a GFF with `Name=` or `gene_biotype=` attributes, surface them in the alert text.
- **Q-score 7 is the de facto "passing" cutoff in `RunHealthTab` colour-coding.** That's the MinKNOW default for fast/HAC basecalling. For super-accurate (SUP) basecalling the threshold is typically Q10. Make it configurable.

### 4.18 Reproducibility / packaging

- `pyproject.toml` declares `requires-python = ">=3.12"` but the README says 3.10+. Lock it down.
- The project name in `pyproject.toml` is `repl-nix-workspace` — change to `nanocas`.
- No CI. No tests. No type-checking (despite TypeScript on the frontend, the backend is untyped Python).
- The Dockerfile mixes apt and pip without a frozen lock file. `uv` is in the repo; pick one tool.

### 4.19 Logging is ad hoc

Three different logger-initialisation blocks (`nanocas.py`, `tasks.py`, file-by-file `getLogger('nanocas')`) and a `logging.ini` that's commented out. Logs go to stdout in dev. There's no rotation, no per-project log file, no structured logging.

**Suggestion**: one logger config at startup (`logging.config.dictConfig`), per-project file handler created when the project is registered, structured JSON (e.g., `python-json-logger`) so the events are grep-able by `projectId`.

### 4.20 Recommended Python-library swaps (concrete)

| Today | Suggestion | Reason |
|---|---|---|
| `watchdog` | Keep, but run the handler in a `ThreadPoolExecutor` so the dispatcher never blocks | Single-threaded dispatch is the root cause of bug §3 going from "annoying" to "fatal". |
| `pysam` (`count_coverage`, `count`, `fetch`) | Keep — it's the right tool, but use **numpy** accumulators per reference instead of recomputing from a growing merged BAM | See §4.1. |
| `samtools merge/sort/index` as subprocess | `samtools cat` for streaming, or `pysam.merge` + `pysam.sort` with `-@` for threading | Avoids shell overhead, threadable. |
| `subprocess.run(shell=True, …)` for minimap2 | `subprocess.Popen` chained with PIPEs, `-t N` | §4.11. |
| `Bio.SeqIO.parse` (biopython) | Keep — it's fine for FASTA. For massive FASTAs, **pyfastx** is ~5× faster | Cheap win. |
| `csv` / `coverage.csv` | `sqlite3` (stdlib) | §4.9, §4.10. |
| `smtplib` synchronous | Either `aiosmtplib` (if you go async) or just push it to a queue and `Thread` it out | Don't block the watcher. |
| `twilio.rest.Client` | Same — wrap in a fire-and-forget worker | Don't block the watcher. |
| `chart.js` + `react-google-charts` | Pick one; **Chart.js** can do both | §4.15. |
| Hand-rolled QC parsing of `sequencing_summary.txt` | `NanoStat` / `NanoPlot` JSON output (subprocess), or [`pycoQC`](https://github.com/a-slide/pycoQC) | §4.5. |
| MinKNOW limited to notify-send | Real `acquisition`, `statistics`, `device` services via `minknow_api` | §4.4. |
| `tempfile.mkdtemp(dir=NANOCAS_DIR)` per upload + `file.filename` | `werkzeug.utils.secure_filename` + one upload dir | §4.8. |
| `eventlet` | Either keep with proper `start_background_task`, or migrate to `flask[async]` + `asgiref` + `gevent` if you outgrow it | Eventlet is in maintenance mode but still works. |
| celery / redis in requirements | Delete | Dead dependency. |

---

## Part 5 — Suggested rewrite order

If you only do one thing today: fix the deadlock (§3). The whole app is broken downstream of that. 30 minutes of work, immediately verifiable.

After that, in priority order:
1. **De-duplicate region alerts** (§4.7). One-line guard, prevents an SMS bill.
2. **Add timeouts to email / SMS / MinKNOW** (§4.2). The next user complaint after the deadlock will be a hang on a slow SMTP.
3. **Path-traversal sanitisation** on the three project-id endpoints + uploads (§4.8). Cheap, high payoff if anyone ever exposes this beyond localhost.
4. **Introduce the `Classifier` protocol** (§4.3). This unblocks the modularity roadmap and makes the rest of the refactor easier.
5. **Replace the O(n²) merge** (§4.1). The single biggest perf win.
6. **Replace `coverage.csv` + `.cache` with SQLite** (§4.9, §4.10). Foundation for everything else.
7. **Wire up live MinKNOW state for pore health + run alerts** (§4.4). Realises the user's "alert on dead pores / low Q" roadmap.
8. **Cleanup**: delete dead routes, dead modules, dead deps (§4.12). Polish.

---

## Appendix A — File-by-file size sanity check

```
server/app/main/utils/FileHandler.py     485 lines  ← the heart, also the bug
server/app/main/routes.py                536 lines
server/app/main/events.py                274 lines
server/app/main/utils/directory_scanner.py 258 lines
server/app/main/utils/tasks.py           165 lines
server/app/main/utils/email.py            34 lines
server/app/main/utils/sms.py              31 lines
server/app/main/utils/LinuxNotification.py 47 lines
frontend/src/modules/project/tabs/RunHealthTab.tsx   371 lines
frontend/src/modules/project/tabs/CoverageTab.tsx    225 lines
frontend/src/modules/project/tabs/AlertsTab.tsx      128 lines
frontend/src/modules/analysis/.../alignment-viewer.component.tsx  285 lines
```

Total backend Python: ~1800 lines. Total frontend TS/TSX: ~2400 lines. This is a small enough codebase that the refactor in §5 is genuinely feasible inside a single sprint.

## Appendix B — One-liners I'd add to CI on day one

- `ruff check server/` — catches the `print(...)` in production paths, unused imports, the dead `self.num_files_classified` variable.
- `mypy --strict server/` — would have caught the `Lock`-vs-`RLock` issue if `_save_sent_alerts` was annotated `# requires lock held`.
- `pytest server/tests/` — even a single test of "two consecutive alerts don't deadlock" would have caught §3 immediately.
- `npm run build` in `frontend/` — the React Router v5 deprecations are real and the TypeScript looser config (`tsconfig.json` does not have `"strict": true`) is hiding bugs.
