"""Alert log + notification dispatch.

Every alert nanoCAS raises, whether it comes from the coverage pipeline
(FileHandler) or the run-health monitor, goes through :class:`AlertLog`
so the UI can show a complete history, and through :class:`Notifier` so
the operator is told about it through whatever channels the project
enabled (MinKNOW device message, e-mail, SMS, desktop notification).

The log is an append-only JSON-lines file ``<project>/alerts.jsonl``;
one JSON object per line, newest last. It is cheap to append to from
the watchdog thread and cheap to tail from the API.

Notification dispatch is asynchronous by default: the caller hands over
a record and a daemon thread does the (potentially slow) network I/O so
neither the watchdog dispatcher nor the run-health monitor ever blocks
on SMTP, Twilio or gRPC.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import uuid
from datetime import datetime

from .email import send_email
from .sms import send_sms
from .LinuxNotification import LinuxNotification

logger = logging.getLogger('nanocas')

SEVERITY_INFO = 'info'
SEVERITY_WARNING = 'warning'
SEVERITY_CRITICAL = 'critical'
SEVERITIES = (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL)

# Sources tell the UI (and the reader of the log) which subsystem raised
# the alert.
SOURCE_COVERAGE = 'coverage'
SOURCE_RUN_HEALTH = 'run_health'
SOURCE_SYSTEM = 'system'

REQUIRED_EMAIL_KEYS = ('sender', 'recipient', 'smtpServer', 'smtpPort', 'password')


class AlertLog:
    """Append-only per-project alert history."""

    FILENAME = 'alerts.jsonl'

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.path = os.path.join(project_dir, self.FILENAME)
        self._lock = threading.Lock()

    def append(self, alert_type: str, severity: str, message: str, *,
               source: str = SOURCE_SYSTEM, details: dict | None = None,
               state: str = 'fired', project_id: str | None = None) -> dict:
        if severity not in SEVERITIES:
            severity = SEVERITY_INFO
        record = {
            'id': str(uuid.uuid4()),
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'projectId': project_id,
            'source': source,
            'type': alert_type,
            'severity': severity,
            'state': state,
            'message': message,
            'details': details or {},
        }
        with self._lock:
            os.makedirs(self.project_dir, exist_ok=True)
            with open(self.path, 'a') as fh:
                fh.write(json.dumps(record) + '\n')
        return record

    def read(self, limit: int = 200) -> list[dict]:
        """Newest first. Corrupt lines are skipped rather than failing the
        whole read so one bad write can't hide the rest of the history."""
        if not os.path.exists(self.path):
            return []
        records: list[dict] = []
        with self._lock:
            with open(self.path, 'r') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning(f'Skipping corrupt alert log line in {self.path}')
        records.reverse()
        return records[:limit] if limit else records

    def count(self) -> int:
        return len(self.read(limit=0))


class Notifier:
    """Fan an alert out to every channel enabled in ``alertinfo.cfg``.

    ``config`` is the full project config dict. The relevant keys are
    ``device`` (MinKNOW position name, optional) and ``alertNotifConfig``
    (``enableEmail`` / ``emailConfig`` / ``enableSMS`` / ``smsRecipient``).
    """

    def __init__(self, config: dict | None, *, desktop: bool = True):
        self.config = config or {}
        self.desktop = desktop

    # -- introspection -------------------------------------------------

    def channels(self) -> list[str]:
        """Names of the channels that will actually be used."""
        chans: list[str] = []
        if self.config.get('device'):
            chans.append('minknow')
        notif = self.config.get('alertNotifConfig') or {}
        if notif.get('enableEmail') and self.email_config_complete(notif.get('emailConfig') or {}):
            chans.append('email')
        if notif.get('enableSMS') and notif.get('smsRecipient'):
            chans.append('sms')
        if self.desktop:
            chans.append('desktop')
        return chans

    @staticmethod
    def email_config_complete(email_config: dict) -> bool:
        return all(email_config.get(k) not in (None, '') for k in REQUIRED_EMAIL_KEYS)

    # -- dispatch ------------------------------------------------------

    def send(self, subject: str, message: str, *, severity: str = SEVERITY_WARNING,
             background: bool = True) -> None:
        if background:
            t = threading.Thread(target=self._send_sync, args=(subject, message, severity),
                                 daemon=True, name='nanocas-notify')
            t.start()
        else:
            self._send_sync(subject, message, severity)

    def _send_sync(self, subject: str, message: str, severity: str) -> dict:
        """Send on every channel; return a per-channel status dict. Errors
        are logged and reported, never raised, so one broken channel
        never prevents the others from firing."""
        results: dict[str, str] = {}
        device = self.config.get('device', '')
        notif = self.config.get('alertNotifConfig') or {}

        if self.desktop:
            results['desktop'] = _desktop_notify(subject, message)

        if device:
            try:
                # MinKNOW severities: 1 = info, 2 = warning, 3 = error.
                mk_sev = {SEVERITY_INFO: 1, SEVERITY_WARNING: 2, SEVERITY_CRITICAL: 3}.get(severity, 2)
                LinuxNotification.send_notification(device, f'{subject}: {message}', severity=mk_sev)
                results['minknow'] = 'sent'
            except Exception as exc:  # noqa: BLE001
                logger.error(f'MinKNOW notification failed: {exc}')
                results['minknow'] = f'error: {exc}'

        if notif.get('enableEmail'):
            email_config = notif.get('emailConfig') or {}
            if self.email_config_complete(email_config):
                ok, err = send_email(subject, message, email_config)
                results['email'] = 'sent' if ok else f'error: {err}'
            else:
                logger.error('Email notifications enabled but the configuration is incomplete.')
                results['email'] = 'error: incomplete configuration'

        if notif.get('enableSMS'):
            recipient = notif.get('smsRecipient', '')
            if recipient:
                ok, err = send_sms(f'{subject}: {message}', recipient)
                results['sms'] = 'sent' if ok else f'error: {err}'
            else:
                logger.error('SMS notifications enabled but no recipient phone number is set.')
                results['sms'] = 'error: no recipient'

        return results

    def send_test(self) -> dict:
        """Synchronous test send used by the /test_notification endpoint."""
        return self._send_sync('nanoCAS test notification',
                               'This is a test message from nanoCAS. If you can read this, '
                               'notifications for this project are working.',
                               SEVERITY_INFO)


def _desktop_notify(subject: str, message: str) -> str:
    """Best-effort local desktop popup (``notify-send`` on Linux,
    ``osascript`` on macOS). Never raises."""
    try:
        if os.name == 'posix' and os.uname().sysname == 'Darwin':
            script = f'display notification "{_osa_escape(message)}" with title "{_osa_escape(subject)}"'
            subprocess.Popen(['osascript', '-e', script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(['notify-send', subject, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 'sent'
    except Exception as exc:  # noqa: BLE001
        logger.debug(f'Desktop notification unavailable: {exc}')
        return f'unavailable: {exc}'


def _osa_escape(text: str) -> str:
    return text.replace('\\', '\\\\').replace('"', '\\"')


def safe_emit(event: str, payload: dict) -> None:
    """``socketio.emit`` that never raises. In threading async mode the
    emit is thread-safe, so this can be called directly from the watchdog
    dispatcher, the run-health monitor or a notification thread. When no
    server is attached (unit tests, CLI use) the event is simply dropped."""
    try:
        from app import socketio
        if getattr(socketio, 'server', None) is None:
            return
        socketio.emit(event, payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f'{event} emit skipped: {exc}')


def emit_alert(record: dict) -> None:
    """Push an alert record to connected browsers."""
    safe_emit('alert_fired', record)
