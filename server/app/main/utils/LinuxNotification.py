"""MinKNOW integration.

Despite the historical file name this is the only place nanoCAS talks
to MinKNOW (over gRPC through ``minknow_api``). It is used to

* enumerate flow-cell positions so the wizard can offer them,
* push user messages into the MinKNOW UI when an alert fires, and
* read the live acquisition / flow-cell state for the run-health monitor.

Every gRPC call is wrapped in a wall-clock timeout so an unreachable
MinKNOW can never block a caller. See LOGBOOK section 4.2.
"""

import logging
import threading

from minknow_api.manager import Manager

logger = logging.getLogger('nanocas')

_MINKNOW_TIMEOUT_SECONDS = 10


def _run_with_timeout(func, timeout: float, default=None):
    """Run a no-arg callable on a daemon thread with a wall-clock cap.

    Returns the function's return value, or `default` if `timeout`
    elapses. On timeout the worker thread is orphaned; we can't cancel an
    in-flight gRPC call from outside, but the goal is only to keep the
    caller unblocked. Re-raises non-timeout exceptions to the caller.
    """
    result = {'value': default, 'error': None}

    def _worker():
        try:
            result['value'] = func()
        except Exception as exc:  # noqa: BLE001
            result['error'] = exc

    t = threading.Thread(target=_worker, daemon=True, name='nanocas-minknow')
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        logger.warning(f"MinKNOW call did not return within {timeout}s; abandoning the request")
        return default
    if result['error'] is not None:
        raise result['error']
    return result['value']


class LinuxNotification:
    """Namespace of static helpers (kept as a class for backwards
    compatibility with the existing call sites)."""

    @staticmethod
    def index_devices(host="127.0.0.1", port=None, timeout: float = _MINKNOW_TIMEOUT_SECONDS):
        def _do():
            manager = Manager(host=host, port=port)
            return list(manager.flow_cell_positions())
        try:
            return _run_with_timeout(_do, timeout=timeout, default=[]) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"index_devices failed (MinKNOW not reachable?): {exc}")
            return []

    @staticmethod
    def get_device(device_name, host="127.0.0.1", port=None):
        for device in LinuxNotification.index_devices(host, port):
            if device.name == device_name:
                return device
        logger.error(f"Could not find MinKNOW position {device_name}")
        return None

    @staticmethod
    def send_notification(device_name, msg, severity=2, timeout: float = _MINKNOW_TIMEOUT_SECONDS):
        """Post ``msg`` into the MinKNOW UI of ``device_name``.

        ``severity`` follows MinKNOW's scale: 1 = info, 2 = warning,
        3 = error. Returns True when the message was accepted.
        """
        device = LinuxNotification.get_device(device_name)
        if device is None:
            return False

        def _do():
            connection = device.connect()
            connection.log.send_user_message(severity=severity, user_message=msg)
            return True

        try:
            return bool(_run_with_timeout(_do, timeout=timeout, default=False))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"MinKNOW notification failed: {exc}")
            return False

    @staticmethod
    def get_device_status(device_name, timeout: float = _MINKNOW_TIMEOUT_SECONDS) -> dict | None:
        """Best-effort live snapshot of a MinKNOW position for the run-health
        monitor. Returns None if MinKNOW / the position isn't reachable.

        Keys: ``position_state``, ``acquisition_status`` (READY / STARTING /
        PROCESSING / FINISHING / ...), ``flow_cell_id``, ``product_code``,
        ``channel_count``, ``has_flow_cell``.
        """
        device = LinuxNotification.get_device(device_name)
        if device is None:
            return None

        def _do():
            connection = device.connect()
            info: dict = {'position_state': str(getattr(device, 'state', ''))}
            try:
                status = connection.acquisition.current_status()
                info['acquisition_status'] = _enum_name(status, 'status')
            except Exception as exc:  # noqa: BLE001
                info['acquisition_status'] = f'unknown ({exc.__class__.__name__})'
            try:
                fc = connection.device.get_flow_cell_info()
                info['has_flow_cell'] = bool(getattr(fc, 'has_flow_cell', False))
                info['flow_cell_id'] = getattr(fc, 'flow_cell_id', '') or getattr(fc, 'user_specified_flow_cell_id', '')
                info['product_code'] = getattr(fc, 'product_code', '') or getattr(fc, 'user_specified_product_code', '')
                info['channel_count'] = int(getattr(fc, 'channel_count', 0) or 0)
            except Exception as exc:  # noqa: BLE001
                info['flow_cell_error'] = str(exc)
            return info

        try:
            return _run_with_timeout(_do, timeout=timeout, default=None)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"get_device_status failed: {exc}")
            return None


def _enum_name(message, field: str) -> str:
    """Resolve a protobuf enum field to its symbolic name."""
    try:
        value = getattr(message, field)
        return message.DESCRIPTOR.fields_by_name[field].enum_type.values_by_number[value].name
    except Exception:  # noqa: BLE001
        return str(getattr(message, field, ''))
