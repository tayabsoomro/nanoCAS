import logging
import os
import secrets
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS

logger = logging.getLogger('nanocas')

socketio = SocketIO()


def _resolve_secret_key() -> str:
    """Read SECRET_KEY from the environment; fall back to a random per-process
    key with a loud warning. The previous hard-coded value (`gjr39dkjn344_!67#`)
    was checked into the repo, so anything signed with it on a public deployment
    was effectively unsigned. See LOGBOOK section 4.16.

    For local dev you can leave SECRET_KEY unset — sessions just won't survive
    a restart, which is fine for the single-user case. For anything fronted
    by a real URL, set SECRET_KEY in the environment.
    """
    key = os.getenv('SECRET_KEY')
    if key:
        return key
    logger.warning(
        "SECRET_KEY is not set in the environment; generating an ephemeral "
        "per-process key. Sessions and CSRF tokens will be invalidated on "
        "every restart. Set SECRET_KEY in your .env for a persistent value."
    )
    return secrets.token_urlsafe(32)


def create_app(debug=True):
    """Create an application."""
    app = Flask(__name__)
    # CORS_ALLOWED_ORIGINS env honoured for the day someone exposes this
    # past localhost. Default stays permissive so the existing local-dev
    # setup keeps working unchanged.
    cors_origins = os.getenv('CORS_ALLOWED_ORIGINS', '*')
    CORS(app, origins=cors_origins)
    app.debug = debug
    app.config['SECRET_KEY'] = _resolve_secret_key()

    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    socketio.init_app(app, cors_allowed_origins=cors_origins)

    return app