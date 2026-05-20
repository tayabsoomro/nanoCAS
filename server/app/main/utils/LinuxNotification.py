
import subprocess
import threading
from dataclasses import dataclass
from minknow_api.manager import Manager
import logging

logger = logging.getLogger('nanocas')

# MinKNOW gRPC defaults: per LOGBOOK §4.2 these had no timeouts, so a dead
# or unreachable MinKNOW would block the alert path (and therefore the
# watchdog dispatcher) indefinitely. The library doesn't expose a
# per-call timeout we can reliably pass through, so we wrap each external
# call in a daemon-thread watchdog: if the call hasn't returned by
# `timeout` we abandon it (the thread keeps running until the gRPC
# attempt fails on its own) and unblock the caller.
_MINKNOW_TIMEOUT_SECONDS = 10


def _run_with_timeout(func, timeout: float, default=None):
    """Run a no-arg callable on a daemon thread with a wall-clock cap.

    Returns the function's return value, or `default` if `timeout`
    elapses. On timeout the worker thread is orphaned — that's
    intentional: we can't cancel an in-flight gRPC call from outside, but
    the goal here is only to keep the caller (the watchdog dispatcher)
    unblocked. Re-raises non-timeout exceptions to the caller.
    """
    result = {'value': default, 'error': None}

    def _worker():
        try:
            result['value'] = func()
        except Exception as exc:
            result['error'] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        logger.warning(
            f"MinKNOW call did not return within {timeout}s — abandoning the request"
        )
        return default
    if result['error'] is not None:
        raise result['error']
    return result['value']


@dataclass
class LinuxNotification():

    def index_devices(host="127.0.0.1", port=None, timeout: float = _MINKNOW_TIMEOUT_SECONDS):
        def _do():
            manager = Manager(host=host, port=port)
            return [position for position in manager.flow_cell_positions()]
        try:
            return _run_with_timeout(_do, timeout=timeout, default=[]) or []
        except Exception as exc:
            logger.debug(f"index_devices failed: {exc}")
            return []


    def get_device(device_name, host="127.0.0.1", port=None):
        for device in LinuxNotification.index_devices(host, port):
            if device.name == device_name:
                return device
        logger.error(f"Error: Could not find device {device_name}")
        return None

    def test_connection( device_name, msg="This is a linux test connection"):
        LinuxNotification.send_notification(msg)
        pass

    def send_notification(device_name, msg, severity=2, timeout: float = _MINKNOW_TIMEOUT_SECONDS):
        device = LinuxNotification.get_device(device_name)
        if device is None:
            logger.error(f"Cannot send notification: device {device_name} not found")
            return

        # notify-send is fire-and-forget on the local machine — safe outside
        # the timeout. Use Popen with no .wait() so we don't even block on
        # process startup. The bare-except is intentional: notify-send is
        # absent on macOS and we just want a debug breadcrumb, not a crash.
        try:
            subprocess.Popen(['notify-send', msg])
        except Exception:
            logger.debug("notify-send not available (non-Linux host?)")

        # The gRPC calls go in the timeout wrapper so a hung MinKNOW
        # can't block the watchdog dispatcher.
        def _do():
            connection = device.connect()
            connection.log.send_user_message(severity=severity, user_message=msg)
            logger.debug(connection.device.get_device_state())
        try:
            _run_with_timeout(_do, timeout=timeout)
        except Exception as exc:
            logger.warning(f"MinKNOW notification failed: {exc}")

