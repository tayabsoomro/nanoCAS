import React, { FunctionComponent, useEffect, useState } from 'react';
import { IAlertNotifSetupProps } from '../../setup.interfaces';
import { IAlertNotifSetupInput, IEmailConfig } from './alert-notif-setup.interfaces';
import { api, RunHealthConfig, RUN_HEALTH_FIELDS } from '../../../../api';

const EMPTY_EMAIL: IEmailConfig = { sender: '', recipient: '', smtpServer: '', smtpPort: 587, password: '' };

const AlertNotifSetupComponent: FunctionComponent<IAlertNotifSetupProps> = ({ advanceStep, goBack, update, initial }) => {
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
        <div className="nano-field-row">
            <label>{label}</label>
            <div>
                {control}
                {help && <div className="form-text">{help}</div>}
            </div>
        </div>
    );

    return (
        <div>
            <div className="nano-wizard-panel">
                <h4>Notifications</h4>
                <p>Alerts always appear in nanoCAS and in its alert log. Add e-mail or SMS to be reached away from the instrument.</p>

                {row('Email',
                    <div className="form-check"><input type="checkbox" className="form-check-input" id="enable-email" checked={enableEmail} onChange={(e) => setEnableEmail(e.target.checked)} /><label className="form-check-label" htmlFor="enable-email">Send alerts by e-mail</label></div>)}
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

                {row('SMS',
                    <div className="form-check"><input type="checkbox" className="form-check-input" id="enable-sms" checked={enableSMS} onChange={(e) => setEnableSMS(e.target.checked)} /><label className="form-check-label" htmlFor="enable-sms">Send alerts by SMS (Twilio)</label></div>,
                    twilioConfigured === false ? 'Twilio credentials are not configured on the server (.env); SMS cannot be sent until they are.' : undefined)}
                {enableSMS && row('Recipient phone', <input className="form-control" type="tel" value={smsRecipient} onChange={(e) => setSmsRecipient(e.target.value)} placeholder="+15551234567" />)}

                {(enableEmail || enableSMS) && (
                    <div className="nano-field-row">
                        <label></label>
                        <div>
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

            </div>
            <div className="nano-wizard-panel">
                <h4>Run-health alerts</h4>
                <p>Checks on the run itself: never started, stalled, low read quality, dying pores. Defaults suit a MinION R10.4 run.</p>
                {row('Enabled',
                    <div className="form-check"><input type="checkbox" className="form-check-input" id="enable-rh" checked={runHealth.enabled !== false} onChange={(e) => setRH('enabled', e.target.checked)} /><label className="form-check-label" htmlFor="enable-rh">Evaluate run-health rules while monitoring</label></div>)}
                {runHealth.enabled !== false && RUN_HEALTH_FIELDS.map(f => row(
                    <>{f.label}{f.unit ? <span className="text-muted small"> ({f.unit})</span> : null}</>,
                    <input className="form-control" type="number" min="0" step={f.step ?? 1}
                           value={(runHealth[f.key] as number | '' | undefined) ?? ''}
                           onChange={(e) => setRH(f.key, e.target.value)} />,
                    f.help + (defaults ? ` Default: ${defaults[f.key]}.` : '')
                ))}
            </div>
            {error && <div className="nano-alert-banner critical"><span className="nano-alert-message">{error}</span></div>}
            <div className="nano-wizard-actions">
                <button className="btn btn-outline-secondary" onClick={goBack}>Back</button>
                <span className="spacer" />
                <button className="btn btn-primary" onClick={updateAlertNotifSetupConfiguration}>Continue</button>
            </div>
        </div>
    );
};

export default AlertNotifSetupComponent;
