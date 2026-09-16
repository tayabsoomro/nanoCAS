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
    app = Flask(__name__, static_folder=None)
    cors_origins = os.getenv('CORS_ALLOWED_ORIGINS', '*')
    CORS(app, origins=cors_origins)
    if debug is None:
        debug = os.getenv('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    app.debug = debug
    app.config['SECRET_KEY'] = _resolve_secret_key()
    app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '2048')) * 1024 * 1024

    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)
    _register_frontend(app)

    socketio.init_app(app, cors_allowed_origins=cors_origins, max_http_buffer_size=10_000_000)
    return app


def _frontend_build_dir() -> str | None:
    """Directory holding the production UI build, if any.

    ``NANOCAS_STATIC_DIR`` overrides; otherwise ``../frontend/build`` next
    to the server package is used when it exists. Set the variable to an
    empty string to disable serving the UI from the backend."""
    override = os.getenv('NANOCAS_STATIC_DIR')
    if override is not None:
        return override or None
    candidate = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'build'))
    return candidate if os.path.isfile(os.path.join(candidate, 'index.html')) else None


def _register_frontend(app: Flask) -> None:
    """Serve the React build from the backend so a deployment needs only
    one port: API routes keep precedence, static assets are served from
    the build directory, and every other path returns index.html so the
    client-side router can handle it."""
    from flask import send_from_directory
    build_dir = _frontend_build_dir()
    if not build_dir or not os.path.isfile(os.path.join(build_dir, 'index.html')):
        return
    logger.info(f"Serving the web UI from {build_dir}")

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def frontend(path):  # noqa: ANN001
        target = os.path.normpath(os.path.join(build_dir, path)) if path else ''
        if path and target.startswith(build_dir) and os.path.isfile(target):
            return send_from_directory(build_dir, path)
        response = send_from_directory(build_dir, 'index.html')
        response.headers['Cache-Control'] = 'no-cache'
        return response
