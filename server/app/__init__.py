import logging
import os
import secrets

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

logger = logging.getLogger('nanocas')

# async_mode='threading': nanoCAS does its real work on native threads
# (watchdog observer, alignment subprocesses, the run-health monitor,
# notification dispatch). Under eventlet those threads could not safely
# call socketio.emit, which is why live updates used to be dropped and
# every UI element needed a polling fallback. In threading mode
# python-socketio's emit is thread-safe, WebSocket is served through
# simple-websocket, and blocking subprocess calls never stall the
# server's event loop because there is no single event loop to stall.
socketio = SocketIO(async_mode='threading')


def _resolve_secret_key() -> str:
    """Read SECRET_KEY from the environment; fall back to a random
    per-process key with a warning. The previous hard-coded value was
    checked into the repo. See LOGBOOK section 4.16."""
    key = os.getenv('SECRET_KEY')
    if key:
        return key
    logger.warning(
        "SECRET_KEY is not set; generating an ephemeral per-process key. "
        "Set SECRET_KEY in your .env for a persistent value."
    )
    return secrets.token_urlsafe(32)


def create_app(debug: bool | None = None):
    """Create the Flask application."""
    app = Flask(__name__)
    cors_origins = os.getenv('CORS_ALLOWED_ORIGINS', '*')
    CORS(app, origins=cors_origins)
    if debug is None:
        debug = os.getenv('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    app.debug = debug
    app.config['SECRET_KEY'] = _resolve_secret_key()
    app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '2048')) * 1024 * 1024

    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    socketio.init_app(app, cors_allowed_origins=cors_origins, max_http_buffer_size=10_000_000)
    return app
