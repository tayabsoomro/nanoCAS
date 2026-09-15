import React, { FunctionComponent, useEffect, useState } from 'react';
import { IAlertNotifSetupProps } from '../../setup.interfaces';
import { IAlertNotifSetupInput, IEmailConfig } from './alert-notif-setup.interfaces';
import { api, RunHealthConfig, RUN_HEALTH_FIELDS } from '../../../../api';

const EMPTY_EMAIL: IEmailConfig = { sender: '', recipient: '', smtpServer: '', smtpPort: 587, password: '' };

const AlertNotifSetupComponent: FunctionComponent<IAlertNotifSetupProps> = ({ advanceStep, update, initial }) => {
    const [enableEmail, setEnableEmail] = useState(initial.enableEmail);
    const [emailConfig, setEmailConfig] = useState<IEmailConfig>(initial.emailConfig || EMPTY_EMAIL);
    const [enableSMS, setEnableSMS] = useState(initial.enableSMS);
    const [smsRecipient, setSmsRecipient] = useState(initial.smsRecipient || '');
    const [twilioConfigured, setTwilioConfigured] = useState<boolean | null>(null);
    // Numeric fields may transiently be '' while the user is typing.
    type RunHealthForm = Partial<Record<keyof RunHealthConfig, number | boolean | ''>>;
    const [runHealth, setRunHealth] = useState<RunHealthForm>(initial.runHealthConfig || {});
    const [defaults, setDefaults] = useState<RunHealthConfig | null>(null);
    const [error, setError] = useState('');
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<{ ok: boolean; results: Record<string, string>; error?: string } | null>(null);

    useEffect(() => {
        api.get('/run_health_defaults')
            .then(res => {
                setDefaults(res.data.defaults);
                setRunHealth(prev => ({ ...res.data.defaults, ...prev }));
            })
            .catch(() => { });
        api.get('/health').then(res => setTwilioConfigured(!!res.data.twilio_configured)).catch(() => { });
    }, []);

    const handleEmailConfigChange = (key: keyof IEmailConfig) => (evt: React.ChangeEvent<HTMLInputElement>) => {
        const value = key === 'smtpPort' ? parseInt(evt.target.value) || 0 : evt.target.value;
        setEmailConfig((prev) => ({ ...prev, [key]: value }));
    };

    const setRH = (key: keyof RunHealthConfig, value: string | boolean) => {
        setRunHealth(prev => ({ ...prev, [key]: typeof value === 'boolean' ? value : (value === '' ? '' : Number(value)) }));
    };

    const validate = (): string | null => {
        if (enableEmail) {
            const { sender, recipient, smtpServer, smtpPort, password } = emailConfig;
            if (!sender || !recipient || !smtpServer || !smtpPort || !password) {
                return 'All email fields are required when email notifications are enabled.';
            }
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(sender) || !emailRegex.test(recipient)) return 'Invalid email format.';
        }
        if (enableSMS && !/^\+?[0-9]{7,15}$/.test(smsRecipient.replace(/[\s-]/g, ''))) {
            return 'Enter the recipient phone number in international format, e.g. +15551234567.';
        }
        for (const f of RUN_HEALTH_FIELDS) {
            const v = runHealth[f.key];
            if (v === '' || v === undefined || (typeof v === 'number' && (isNaN(v) || v < 0))) {
                return `Run-health setting "${f.label}" must be a number ≥ 0.`;
            }
        }
        return null;
    };

    const buildConfig = (): IAlertNotifSetupInput => ({
        enableEmail,
        emailConfig: enableEmail ? emailConfig : undefined,
        enableSMS,
        smsRecipient: enableSMS ? smsRecipient.replace(/[\s-]/g, '') : undefined,
        runHealthConfig: runHealth as Partial<RunHealthConfig>,
    });

    const updateAlertNotifSetupConfiguration = () => {
        setError('');
        const problem = validate();
        if (problem) { setError(problem); return; }
        update(buildConfig());
        advanceStep();
    };

    const sendTest = async () => {
        setError('');
        const problem = validate();
        if (problem) { setError(problem); return; }
        if (!enableEmail && !enableSMS) {
            setError('Enable email or SMS to send a test notification.');
            return;
        }
        setTesting(true);
        setTestResult(null);
        try {
            const cfg = buildConfig();
            const res = await api.post('/test_notification', {
                alertNotifConfig: { enableEmail: cfg.enableEmail, emailConfig: cfg.emailConfig, enableSMS: cfg.enableSMS, smsRecipient: cfg.smsRecipient },
                desktop: false,
            });
            setTestResult(res.data);
        } catch (err: any) {
            setTestResult({ ok: false, results: err?.response?.data?.results || {}, error: err?.response?.data?.error || 'Request failed' });
        } finally {
            setTesting(false);
        }
    };

    const row = (label: React.ReactNode, control: React.ReactNode, help?: string) => (
        <div className="mb-3 d-flex flex-row align-items-start">
            <label className="col-sm-4 col-form-label text-end pe-3">{label}</label>
            <div className="col-sm-5">
                {control}
                {help && <div className="form-text">{help}</div>}
            </div>
        </div>
    );

    return (
        <div className="container-fluid vspacer-100 d-flex p-0 flex-column h-100" style={{ borderTop: "1px solid #CCC" }}>
            <div className="vspacer-20"></div>
            <p className="lead text-center">Notifications</p>
            <p className="text-center text-muted small">
                Alerts are always shown in the nanoCAS UI, written to the project's alert log and posted to a selected
                MinKNOW device. Add e-mail and/or SMS to be notified away from the instrument.
            </p>
            <div className="container">
                {error && <div className="mx-auto col-sm-8 alert alert-danger text-left">{error}</div>}

                {row(<h5 className="m-0">Email notifications</h5>,
                    <input type="checkbox" className="form-check-input" checked={enableEmail} onChange={(e) => setEnableEmail(e.target.checked)} />)}
                {enableEmail && (
                    <>
                        {row('Sender', <input className="form-control" type="email" value={emailConfig.sender} onChange={handleEmailConfigChange("sender")} placeholder="sender@example.org" />)}
                        {row('Recipient', <input className="form-control" type="email" value={emailConfig.recipient} onChange={handleEmailConfigChange("recipient")} placeholder="you@example.org" />)}
                        {row('SMTP server', <input className="form-control" type="text" value={emailConfig.smtpServer} onChange={handleEmailConfigChange("smtpServer")} placeholder="smtp.gmail.com" />)}
                        {row('SMTP port', <input className="form-control" type="number" value={emailConfig.smtpPort} onChange={handleEmailConfigChange("smtpPort")} placeholder="587" />,
                            '587 = STARTTLS (most providers), 465 = implicit TLS.')}
                        {row('Password', <input className="form-control" type="password" value={emailConfig.password} onChange={handleEmailConfigChange("password")} placeholder="······" autoComplete="new-password" />,
                            'For Gmail use an app password. Stored in the project configuration on the server; never shown again in the UI.')}
                    </>
                )}

                {row(<h5 className="m-0">SMS notifications</h5>,
                    <input type="checkbox" className="form-check-input" checked={enableSMS} onChange={(e) => setEnableSMS(e.target.checked)} />,
                    twilioConfigured === false ? 'Twilio credentials are not configured on the server (.env); SMS cannot be sent until they are.' : undefined)}
                {enableSMS && row('Recipient phone', <input className="form-control" type="tel" value={smsRecipient} onChange={(e) => setSmsRecipient(e.target.value)} placeholder="+15551234567" />)}

                {(enableEmail || enableSMS) && (
                    <div className="mb-3 d-flex flex-row">
                        <div className="col-sm-4"></div>
                        <div className="col-sm-5">
                            <button type="button" className="btn btn-outline-primary btn-sm" onClick={sendTest} disabled={testing}>
                                {testing ? 'Sending…' : 'Send test notification'}
                            </button>
                            {testResult && (
                                <div className={`alert ${testResult.ok ? 'alert-success' : 'alert-danger'} py-2 mt-2 mb-0 small`}>
                                    {testResult.error && <div>{testResult.error}</div>}
                                    {Object.entries(testResult.results).map(([ch, status]) => <div key={ch}><strong>{ch}</strong>: {status}</div>)}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                <hr />
                <p className="lead text-center">Run-health alerts</p>
                <p className="text-center text-muted small">
                    Instrument-level checks evaluated continuously while monitoring: run never started, data stalled,
                    read quality, pass rate and pore availability. Thresholds below are sensible defaults for a MinION
                    R10.4 run; adjust for your chemistry.
                </p>
                {row(<h5 className="m-0">Enable run-health alerts</h5>,
                    <input type="checkbox" className="form-check-input" checked={runHealth.enabled !== false} onChange={(e) => setRH('enabled', e.target.checked)} />)}
                {runHealth.enabled !== false && RUN_HEALTH_FIELDS.map(f => row(
                    <>{f.label}{f.unit ? <span className="text-muted small"> ({f.unit})</span> : null}</>,
                    <input className="form-control" type="number" min="0" step={f.step ?? 1}
                           value={(runHealth[f.key] as number | '' | undefined) ?? ''}
                           onChange={(e) => setRH(f.key, e.target.value)} />,
                    f.help + (defaults ? ` Default: ${defaults[f.key]}.` : '')
                ))}
            </div>
            <div className="vspacer-50" />
            <hr />
            <br />
            <div className="container text-center">
                <button className="btn btn-success col-lg-2 mx-auto" onClick={updateAlertNotifSetupConfiguration}>
                    Next Step
                </button>
            </div>
        </div>
    );
};

export default AlertNotifSetupComponent;
