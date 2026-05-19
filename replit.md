# nanoCAS

A nanopore classification and alerting web application for portable diagnostics.

## Project Structure

- `frontend/` — React + TypeScript frontend (Create React App)
- `server/` — Python Flask + SocketIO backend

## Architecture

- **Frontend**: React 17, TypeScript, Chart.js, react-chartjs-2, Bootstrap. Runs on port 5000 in dev.
- **Backend**: Flask 2.3, Flask-SocketIO, eventlet. Runs on port 8000 in dev.
- **Realtime**: WebSocket communication via Socket.IO between frontend and backend.

## Navigation & Routing

- `/` — Projects list (ProjectList component)
- `/setup` — Project setup wizard (multi-step: database, notifications, summary)
- `/project/:id` — Project detail view with sub-tabs:
  - `/project/:id/coverage` — Coverage visualization and time series
  - `/project/:id/runhealth` — Run Health dashboard (Q-score, read length, pore health)
  - `/project/:id/alerts` — Alert configuration and notification settings

## Development Setup

### Environment Variables

- `server/.env` — Backend configuration (BACKEND_PORT=8000, Twilio credentials, etc.)
- `frontend/.env` — Frontend config (REACT_APP_API_ENDPOINT=http://localhost:8000, PORT=5000)

### Workflows

- **Start application** — `cd frontend && npm start` on port 5000 (webview)
- **Backend API** — `cd server && python3 nanocas.py` on port 8000 (console)

## Key Dependencies

### Backend (Python)
- Flask, Flask-SocketIO, flask-cors
- eventlet (async worker)
- pysam (bioinformatics)
- biopython
- minimap2 (system package — sequence alignment / index building)
- minknow_api (Nanopore device integration)
- watchdog (file system monitoring)
- twilio (SMS alerts)

### Frontend (Node.js)
- react, react-dom, react-router-dom
- chart.js, react-chartjs-2 (Run Health histograms and trend charts)
- react-google-charts (Coverage time series)
- socket.io-client
- axios, react-bootstrap

## Key Backend Endpoints

- `GET /run_health?projectId=` — Returns Q-scores, read lengths, median Q trend, pore health from sequencing_summary.txt
- `POST /scan_directory` — Scans a nanopore output directory for known file structures (FASTQ, BAM, pod5, fast5, sequencing summary)
- `GET /get_coverage?projectId=` — Returns coverage data over time
- `GET /get_alignments?projectId=&reference=` — Returns alignment data for visualization
- `GET /get_all_analyses` — Returns all projects

## Key SocketIO Events

- `coverage_update` — Emitted when new coverage data is available
- `run_health_update` — Emitted when new sequencing data is processed (triggers Run Health dashboard refresh)
- `start_fastq_file_listener` / `stop_fastq_file_listener` — Controls file watching
- `download_database` — Triggers database build in background thread

## Features

- Projects-first navigation with sub-tabs for Coverage, Run Health, and Alerts
- Run Health dashboard: Q-score distribution, read length distribution, median Q-score trend, pore health summary
- Auto-discovery of nanopore output directory structure
- Real-time nanopore sequencing monitoring via WebSocket
- Custom alerting thresholds with SMS/email notifications
- Interactive coverage dashboard with alignment visualization
- File watcher for FASTQ/BAM files

## Notes

- Twilio SMS alerts require TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, ALERT_RECIPIENT_PHONE in server/.env
- MinKNOW API requires a running MinKNOW instance for device communication
- Database creation runs in a background thread (no Celery/Redis required); progress is pushed to the client via Socket.IO
- Run Health data is parsed from sequencing_summary.txt files produced by MinKNOW
- Directory scanner utility: `server/app/main/utils/directory_scanner.py`
