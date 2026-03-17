# nanoCAS

A nanopore classification and alerting web application for portable diagnostics.

## Project Structure

- `frontend/` — React + TypeScript frontend (Create React App)
- `server/` — Python Flask + SocketIO backend

## Architecture

- **Frontend**: React 17, TypeScript, Chart.js, Bootstrap. Runs on port 5000 in dev.
- **Backend**: Flask 2.3, Flask-SocketIO, eventlet. Runs on port 8000 in dev.
- **Realtime**: WebSocket communication via Socket.IO between frontend and backend.

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
- minknow_api (Nanopore device integration)
- watchdog (file system monitoring)
- celery + redis (distributed tasks)
- twilio (SMS alerts)

### Frontend (Node.js)
- react, react-dom, react-router-dom
- chart.js, react-chartjs-2
- socket.io-client
- axios, bootstrap

## Features

- Real-time nanopore sequencing monitoring
- Custom alerting thresholds with SMS notifications via Twilio
- Interactive dashboard with coverage statistics
- MinKNOW device integration
- File watcher for FASTQ files

## Notes

- Twilio SMS alerts require TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, ALERT_RECIPIENT_PHONE in server/.env
- Redis required for distributed/Celery mode (ENABLE_DISTRIBUTED=true)
- MinKNOW API requires a running MinKNOW instance for device communication
