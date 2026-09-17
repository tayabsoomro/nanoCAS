import React, { useCallback, useEffect, useState } from "react";
import { useHistory } from "react-router-dom";
import { Modal, Button } from "react-bootstrap";
import TruncatedText from "../../../components/TruncatedText";
import { socket } from "../../../app.component";
import { api, AlertRecord, Region, RuleStatus, RUN_HEALTH_FIELDS, describeThresholds, severityBadgeClass } from "../../../api";

interface AlertsTabProps {
    projectId: string;
    projectData: any;
    monitoring: boolean;
}

const RULE_LABELS: Record<string, string> = {
    depth: 'Depth threshold',
    breadth: 'Breadth threshold',
    reads: 'Read-count threshold',
    fraction: 'Read-fraction threshold',
    region_depth: 'Region depth threshold',
    run_not_started: 'Run not started',
    data_stalled: 'Data stalled',
    low_median_q: 'Low read quality',
    pore_decline: 'Pore decline',
    low_active_channels: 'Few active channels',
    low_pass_rate: 'Low pass rate',
    short_reads: 'Short reads',
    batch_failed: 'Batch processing failed',
    index_missing: 'Reference index missing',
    tool_missing: 'Alignment tool missing',
    monitoring_started: 'Monitoring started',
    monitoring_stopped: 'Monitoring stopped',
    project_created: 'Project created',
};

const AlertsTab: React.FC<AlertsTabProps> = ({ projectId, projectData, monitoring }) => {
    const history = useHistory();
    const [alerts, setAlerts] = useState<AlertRecord[]>([]);
    const [rules, setRules] = useState<RuleStatus[]>([]);
    const [channels, setChannels] = useState<string[]>([]);
    const [severityFilter, setSeverityFilter] = useState<'all' | 'critical' | 'warning' | 'info'>('all');
    const [sourceFilter, setSourceFilter] = useState<'all' | 'coverage' | 'run_health' | 'system'>('all');
    const [showConfirmModal, setShowConfirmModal] = useState(false);
    const [removing, setRemoving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<{ ok: boolean; results: Record<string, string>; error?: string } | null>(null);
    const [regions, setRegions] = useState<Record<string, Region[]>>({});
    const [regionsDirty, setRegionsDirty] = useState(false);
    const [savingRegions, setSavingRegions] = useState(false);

    const fetchRegions = useCallback(async () => {
        try {
            const res = await api.get(`/get_regions?projectId=${projectId}`);
            setRegions(res.data.regions || {});
            setRegionsDirty(false);
        } catch { }
    }, [projectId]);

    const updateRegion = (seqid: string, idx: number, patch: Partial<Region>) => {
        setRegions(prev => ({ ...prev, [seqid]: prev[seqid].map((r, i) => i === idx ? { ...r, ...patch } : r) }));
        setRegionsDirty(true);
    };

    const saveRegions = async () => {
        setSavingRegions(true);
        try {
            const res = await api.post('/update_regions', { projectId, regions });
            setRegions(res.data.regions || {});
            setRegionsDirty(false);
        } finally {
            setSavingRegions(false);
        }
    };

    const fetchAlerts = useCallback(async () => {
        try {
            const res = await api.get(`/get_alerts?projectId=${projectId}`);
            setAlerts(res.data.alerts || []);
            setRules(res.data.rules || []);
            setChannels(res.data.channels || []);
        } catch (err) {
            console.error('Could not load alerts', err);
        }
    }, [projectId]);

    useEffect(() => {
        fetchAlerts();
        fetchRegions();
        const handleAlert = (record: AlertRecord) => {
            if (!record.projectId || record.projectId === projectId) fetchAlerts();
        };
        const handleRemoved = (data: any) => {
            if (data?.success) history.push('/');
            else setRemoving(false);
        };
        socket.on('alert_fired', handleAlert);
        socket.on('analysis_removed', handleRemoved);
        const interval = setInterval(fetchAlerts, 30000);
        return () => {
            socket.off('alert_fired', handleAlert);
            socket.off('analysis_removed', handleRemoved);
            clearInterval(interval);
        };
    }, [projectId, fetchAlerts, fetchRegions, history]);

    const confirmRemoveAnalysis = () => {
        setRemoving(true);
        socket.emit('remove_analysis', { projectId });
        setShowConfirmModal(false);
    };

    const sendTest = async () => {
        setTesting(true);
        setTestResult(null);
        try {
            const res = await api.post('/test_notification', { projectId });
            setTestResult(res.data);
        } catch (err: any) {
            setTestResult({ ok: false, results: err?.response?.data?.results || {}, error: err?.response?.data?.error || 'Request failed' });
        } finally {
            setTesting(false);
        }
    };

    const queries = projectData.queries || [];
    const notif = projectData.alertNotifConfig || {};
    const rhc = projectData.runHealthConfig;
    const visible = alerts.filter(a =>
        (severityFilter === 'all' || a.severity === severityFilter) &&
        (sourceFilter === 'all' || a.source === sourceFilter));

    return (
        <div className="nano-alerts-tab">
            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Alert history{alerts.length > 0 ? ` (${alerts.length})` : ''}</h3>
                    <div className="nano-alert-filters">
                        <select className="form-select form-select-sm" value={severityFilter} onChange={e => setSeverityFilter(e.target.value as any)}>
                            <option value="all">All severities</option>
                            <option value="critical">Critical</option>
                            <option value="warning">Warning</option>
                            <option value="info">Info</option>
                        </select>
                        <select className="form-select form-select-sm" value={sourceFilter} onChange={e => setSourceFilter(e.target.value as any)}>
                            <option value="all">All sources</option>
                            <option value="coverage">Coverage</option>
                            <option value="run_health">Run health</option>
                            <option value="system">System</option>
                        </select>
                        <button className="btn btn-outline-primary btn-sm" onClick={fetchAlerts}>Refresh</button>
                    </div>
                </div>
                <div className="nano-panel-body">
                    {visible.length === 0 ? (
                        <div className="nano-empty-state">
                            <p>No alerts{alerts.length > 0 ? ' match the current filter' : ' have been raised for this project yet'}.</p>
                            {alerts.length === 0 && (
                                <p className="nano-hint">Coverage alerts fire once per reference when a threshold is reached; run-health alerts fire while a rule condition holds and log a recovery when it clears.</p>
                            )}
                        </div>
                    ) : (
                        <table className="nano-table">
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Severity</th>
                                    <th>Source</th>
                                    <th>Rule</th>
                                    <th>Message</th>
                                </tr>
                            </thead>
                            <tbody>
                                {visible.map(a => (
                                    <tr key={a.id} className={`nano-alert-row ${a.state}`}>
                                        <td className="nano-alert-time">{a.timestamp.replace('T', ' ')}</td>
                                        <td><span className={severityBadgeClass(a.severity)}>{a.state === 'recovered' ? 'recovered' : a.severity}</span></td>
                                        <td>{a.source.replace('_', ' ')}</td>
                                        <td>{RULE_LABELS[a.type] || a.type}</td>
                                        <td>{a.message}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>

            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Target thresholds</h3>
                    <span className="nano-hint">{projectData.classifier?.name || 'minimap2'}</span>
                </div>
                <div className="nano-panel-body">
                    {queries.length > 0 ? (
                        <table className="nano-table">
                            <thead>
                                <tr>
                                    <th>Target</th>
                                    <th>ID(s)</th>
                                    <th>Alert when</th>
                                </tr>
                            </thead>
                            <tbody>
                                {queries.map((q: any, idx: number) => (
                                    <tr key={idx}>
                                        <td className="nano-cell-name"><TruncatedText text={q.name} /></td>
                                        <td className="nano-cell-id"><TruncatedText text={[...(q.headers || []), ...(q.header && !(q.headers || []).includes(q.header) ? [q.header] : [])].join(', ')} mono /></td>
                                        <td className="nano-cell-rules">{describeThresholds(q).join(', ') || <span className="text-muted">no alert</span>}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : (
                        <div className="nano-empty-state"><p>No targets configured.</p></div>
                    )}
                </div>
            </div>

            {(Object.keys(regions).length > 0 || projectData.gff_file) && (
                <div className="nano-panel">
                    <div className="nano-panel-header">
                        <h3>Feature alerts (GFF)</h3>
                        {regionsDirty && <button className="btn btn-primary btn-sm" onClick={saveRegions} disabled={savingRegions}>{savingRegions ? 'Saving…' : 'Save changes'}</button>}
                    </div>
                    <div className="nano-panel-body">
                        {Object.keys(regions).length === 0 ? (
                            <div className="nano-empty-state"><p>No feature alerts were selected for this project.</p></div>
                        ) : (
                            <table className="nano-table">
                                <thead><tr><th>Alert</th><th>Feature</th><th>Type</th><th>Sequence</th><th>Position</th><th>Depth threshold (x)</th></tr></thead>
                                <tbody>
                                    {Object.entries(regions).flatMap(([seqid, items]) => items.map((r, i) => (
                                        <tr key={`${seqid}-${i}`} className={r.alert_enabled ? '' : 'nano-alert-row recovered'}>
                                            <td><input type="checkbox" className="form-check-input" checked={!!r.alert_enabled} onChange={e => updateRegion(seqid, i, { alert_enabled: e.target.checked })} /></td>
                                            <td>{r.name || r.id}</td>
                                            <td>{r.type || '—'}</td>
                                            <td><code>{seqid}</code></td>
                                            <td className="nano-alert-time">{r.start.toLocaleString()}–{r.end.toLocaleString()}</td>
                                            <td><input type="number" className="form-control form-control-sm" style={{ width: 90 }} min="0" step="0.5" value={r.threshold} onChange={e => updateRegion(seqid, i, { threshold: parseFloat(e.target.value) || 0 })} /></td>
                                        </tr>
                                    )))}
                                </tbody>
                            </table>
                        )}
                        <p className="nano-hint mt-2">Changes apply to the next processed batch; each feature alert fires once per run.</p>
                    </div>
                </div>
            )}

            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Run-health rules</h3>
                    <span className={`nano-badge ${rhc?.enabled === false ? 'nano-badge-inactive' : 'nano-badge-active'}`}>
                        {rhc?.enabled === false ? 'Disabled' : monitoring ? 'Evaluating' : 'Enabled (starts with monitoring)'}
                    </span>
                </div>
                <div className="nano-panel-body">
                    {rules.length > 0 && (
                        <div className="nano-rule-list" style={{ marginBottom: 16 }}>
                            {rules.map(rule => (
                                <div key={rule.id} className={`nano-rule-item ${rule.active ? 'active' : ''}`}>
                                    <span className="nano-rule-light" />
                                    <div>
                                        <div className="nano-rule-title">{rule.description}</div>
                                        <div className="nano-rule-desc">{rule.active ? rule.message : 'OK'}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                    {rhc ? (
                        <table className="nano-table">
                            <thead><tr><th>Setting</th><th>Value</th><th>Meaning</th></tr></thead>
                            <tbody>
                                {RUN_HEALTH_FIELDS.map(f => (
                                    <tr key={f.key}>
                                        <td>{f.label}</td>
                                        <td>{String(rhc[f.key])}{f.unit ? ` ${f.unit}` : ''}</td>
                                        <td className="nano-hint">{f.help}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : <div className="nano-empty-state"><p>No run-health configuration stored for this project (defaults apply).</p></div>}
                </div>
            </div>

            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Notification channels</h3>
                    <button className="btn btn-outline-primary btn-sm" onClick={sendTest} disabled={testing}>
                        {testing ? 'Sending…' : 'Send test notification'}
                    </button>
                </div>
                <div className="nano-panel-body">
                    <div className="nano-notif-grid">
                        <div className="nano-notif-item">
                            <span className="nano-notif-label">Email</span>
                            <span className={`nano-badge ${notif.enableEmail ? 'nano-badge-active' : 'nano-badge-inactive'}`}>
                                {notif.enableEmail ? `Enabled → ${notif.emailConfig?.recipient || '?'}` : 'Disabled'}
                            </span>
                        </div>
                        <div className="nano-notif-item">
                            <span className="nano-notif-label">SMS</span>
                            <span className={`nano-badge ${notif.enableSMS ? 'nano-badge-active' : 'nano-badge-inactive'}`}>
                                {notif.enableSMS ? `Enabled → ${notif.smsRecipient || '?'}` : 'Disabled'}
                            </span>
                        </div>
                        <div className="nano-notif-item">
                            <span className="nano-notif-label">MinKNOW</span>
                            <span className={`nano-badge ${projectData.device ? 'nano-badge-active' : 'nano-badge-inactive'}`}>
                                {projectData.device ? projectData.device : 'No device'}
                            </span>
                        </div>
                        <div className="nano-notif-item">
                            <span className="nano-notif-label">Desktop</span>
                            <span className="nano-badge nano-badge-active">Enabled (server host)</span>
                        </div>
                    </div>
                    {channels.length > 0 && <p className="nano-hint" style={{ marginTop: 8 }}>Active channels: {channels.join(', ')}</p>}
                    {testResult && (
                        <div className={`alert ${testResult.ok ? 'alert-success' : 'alert-danger'} py-2 mt-3 mb-0`}>
                            {testResult.error && <div>{testResult.error}</div>}
                            <div className="nano-test-results">
                                {Object.entries(testResult.results).map(([ch, status]) => (
                                    <span key={ch} className={`nano-badge ${status === 'sent' ? 'nano-badge-active' : 'nano-badge-critical'}`}>{ch}: {status}</span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            <div className="nano-panel nano-danger-zone">
                <div className="nano-panel-header">
                    <h3>Danger Zone</h3>
                </div>
                <div className="nano-panel-body">
                    <p>Permanently remove this analysis and all associated data (coverage, alignments, alert history). The sequencer output directory is not touched.</p>
                    <button className="btn btn-danger" onClick={() => setShowConfirmModal(true)} disabled={removing}>
                        {removing ? 'Removing…' : 'Remove Analysis'}
                    </button>
                </div>
            </div>

            <Modal show={showConfirmModal} onHide={() => setShowConfirmModal(false)}>
                <Modal.Header closeButton>
                    <Modal.Title>Confirm Removal</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>Are you sure you want to remove this analysis? Monitoring will be stopped. This action cannot be undone.</p>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="outline-secondary" onClick={() => setShowConfirmModal(false)}>Cancel</Button>
                    <Button variant="danger" onClick={confirmRemoveAnalysis}>Remove</Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default AlertsTab;
