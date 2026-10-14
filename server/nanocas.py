"""nanoCAS backend entry point.

    python nanocas.py                 # http://0.0.0.0:5007
    BACKEND_PORT=8000 python nanocas.py

Logs go to stdout and to a rotating file under ``~/.nanocas/logs/``.
"""

import logging
import logging.handlers
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def configure_logging() -> None:
    logger = logging.getLogger('nanocas')
    if logger.handlers:
        return
    level = getattr(logging, os.getenv('NANOCAS_LOG_LEVEL', 'INFO').upper(), logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    log_dir = os.path.join(os.path.expanduser('~'), '.nanocas', 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, 'nanocas.log'), maxBytes=20 * 1024 * 1024, backupCount=5)
        rotating.setFormatter(formatter)
        logger.addHandler(rotating)
    except OSError as exc:
        print(f"Could not open log file in {log_dir}: {exc}", file=sys.stderr)
    logger.setLevel(level)


configure_logging()

from app import create_app, socketio  # noqa: E402  (logging must be configured first)

app = create_app()

if __name__ == '__main__':
    port = int(os.getenv('BACKEND_PORT', 5007))
    host = os.getenv('BACKEND_HOST', '0.0.0.0')
    logging.getLogger('nanocas').info(f"nanoCAS backend listening on http://{host}:{port}")
    # allow_unsafe_werkzeug: nanoCAS is a single-user instrument-side tool;
    # the Werkzeug server is the intended runtime. Use gunicorn (see
    # README) if you expose it beyond localhost.
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
