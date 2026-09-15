"""AlertLog persistence and Notifier channel selection."""

import json

from app.main.utils.alerts import (SEVERITY_CRITICAL, SEVERITY_INFO,
                                   SOURCE_COVERAGE, AlertLog, Notifier)


def test_alert_log_append_and_read_newest_first(tmp_path):
    log = AlertLog(str(tmp_path))
    first = log.append('depth', SEVERITY_CRITICAL, 'first', source=SOURCE_COVERAGE, details={'v': 1})
    second = log.append('breadth', SEVERITY_INFO, 'second')
    records = log.read()
    assert [r['id'] for r in records] == [second['id'], first['id']]
    assert records[1]['details'] == {'v': 1}
    assert records[0]['severity'] == SEVERITY_INFO
    assert log.count() == 2


def test_alert_log_skips_corrupt_lines(tmp_path):
    log = AlertLog(str(tmp_path))
    log.append('a', SEVERITY_INFO, 'ok')
    with open(log.path, 'a') as fh:
        fh.write('{not json\n')
    log.append('b', SEVERITY_INFO, 'ok2')
    assert [r['type'] for r in log.read()] == ['b', 'a']


def test_alert_log_unknown_severity_downgrades(tmp_path):
    log = AlertLog(str(tmp_path))
    rec = log.append('x', 'bogus', 'msg')
    assert rec['severity'] == SEVERITY_INFO


def test_notifier_channels_reflect_config():
    assert Notifier({}, desktop=False).channels() == []
    cfg = {
        'device': 'MN12345',
        'alertNotifConfig': {
            'enableEmail': True,
            'emailConfig': {'sender': 'a@b.c', 'recipient': 'd@e.f', 'smtpServer': 's', 'smtpPort': 587, 'password': 'p'},
            'enableSMS': True,
            'smsRecipient': '+15555555555',
        },
    }
    assert Notifier(cfg, desktop=False).channels() == ['minknow', 'email', 'sms']
    # Incomplete e-mail config is not an active channel.
    cfg['alertNotifConfig']['emailConfig']['password'] = ''
    assert 'email' not in Notifier(cfg, desktop=False).channels()


def test_notifier_reports_per_channel_errors(monkeypatch):
    from app.main.utils import alerts as alerts_mod
    monkeypatch.setattr(alerts_mod, 'send_email', lambda *a, **k: (False, 'boom'))
    monkeypatch.setattr(alerts_mod, 'send_sms', lambda *a, **k: (True, None))
    cfg = {'alertNotifConfig': {
        'enableEmail': True,
        'emailConfig': {'sender': 'a@b.c', 'recipient': 'd@e.f', 'smtpServer': 's', 'smtpPort': '465', 'password': 'p'},
        'enableSMS': True, 'smsRecipient': '+1',
    }}
    results = Notifier(cfg, desktop=False)._send_sync('s', 'm', SEVERITY_CRITICAL)
    assert results['email'].startswith('error')
    assert results['sms'] == 'sent'
    assert 'desktop' not in results


def test_alert_record_is_json_serialisable(tmp_path):
    log = AlertLog(str(tmp_path))
    rec = log.append('depth', SEVERITY_CRITICAL, 'm', details={'value': 1.5})
    json.dumps(rec)
