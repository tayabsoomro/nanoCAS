import React, { useCallback, useEffect, useState } from "react";
import { socket } from "../../../app.component";
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    LineElement,
    PointElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js';
import { Bar, Line } from 'react-chartjs-2';
import { api, formatBases, formatDuration, formatNumber, RunHealthSnapshot } from "../../../api";

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Title, Tooltip, Legend, Filler);

interface RunHealthTabProps {
    projectId: string;
    projectData: any;
    monitoring: boolean;
}

const POLL_MS = 15000;

const chartBase = (xTitle: string, yTitle: string) => ({
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, title: { display: false } },
    scales: {
        x: { title: { display: true, text: xTitle } },
        y: { title: { display: true, text: yTitle }, beginAtZero: true },
    },
});

const timeLabel = (seconds: number) =>
    seconds >= 3600 ? `${(seconds / 3600).toFixed(1)}h` : seconds >= 60 ? `${(seconds / 60).toFixed(0)}m` : `${seconds.toFixed(0)}s`;

const RunHealthTab: React.FC<RunHealthTabProps> = ({ projectId, projectData, monitoring }) => {
    const [data, setData] = useState<RunHealthSnapshot | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchRunHealth = useCallback(async () => {
        try {
            const res = await api.get(`/run_health?projectId=${projectId}`);
            setData(res.data);
            setError(null);
        } catch (err: any) {
            if (err.response?.status === 404) {
                setError("No sequencing summary found yet. MinKNOW writes sequencing_summary_*.txt into the run "
                    + "directory once basecalling starts; run-health statistics appear as soon as it exists.");
            } else {
                setError("Failed to load run health data.");
            }
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchRunHealth();
        const interval = setInterval(fetchRunHealth, POLL_MS);
        const handleUpdate = (update: any) => {
            if (update.projectId === projectId) fetchRunHealth();
        };
        socket.on('run_health_update', handleUpdate);
        return () => {
            clearInterval(interval);
            socket.off('run_health_update', handleUpdate);
        };
    }, [projectId, fetchRunHealth]);

    if (loading) {
        return (
            <div className="nano-loading-state">
                <div className="nano-spinner"></div>
                <p>Loading run health data...</p>
            </div>
        );
    }

    const rules = data?.rules || [];
    const cfg = data?.config || projectData?.runHealthConfig;

    if (error || !data) {
        return (
            <div className="nano-run-health">
                <div className="nano-empty-state-large">
                    <div className="nano-empty-icon">&#9764;</div>
                    <h3>Run Health</h3>
                    <p>{error || "No data available"}</p>
                    {!monitoring && <p className="nano-hint">Start monitoring to enable the run-health rules (run-start, stall, quality and pore alerts).</p>}
                </div>
            </div>
        );
    }

    const qThreshold = data.q_threshold ?? cfg?.qScoreThreshold ?? 7;
    const totals = data.totals || { reads: 0 };
    const window = data.window;
    const pores = data.pores;
    const inputs = data.inputs;

    const qHist = data.q_hist && data.q_hist.some(v => v > 0) ? (() => {
        const maxBin = Math.max(...data.q_hist!.map((v, i) => (v > 0 ? i : 0)));
        const upper = Math.min(Math.max(maxBin + 1, 10), data.q_hist!.length - 1);
        const bins = data.q_hist!.slice(0, upper + 1);
        return {
            labels: bins.map((_, i) => `Q${i}`),
            datasets: [{
                label: 'Reads',
                data: bins,
                backgroundColor: bins.map((_, i) => i >= qThreshold ? 'rgba(0, 176, 189, 0.7)' : 'rgba(231, 76, 60, 0.7)'),
                borderColor: bins.map((_, i) => i >= qThreshold ? 'rgba(0, 176, 189, 1)' : 'rgba(231, 76, 60, 1)'),
                borderWidth: 1,
            }],
        };
    })() : null;

    const lenHist = data.len_hist && data.len_hist.counts.some(v => v > 0) ? {
        labels: data.len_hist.edges.map((e, i, arr) => {
            const fmt = (n: number) => (n >= 1000 ? `${n / 1000}k` : `${n}`);
            return i < arr.length - 1 ? `${fmt(e)}–${fmt(arr[i + 1])}` : `≥${fmt(e)}`;
        }),
        datasets: [{
            label: 'Reads',
            data: data.len_hist.counts,
            backgroundColor: 'rgba(0, 78, 90, 0.7)',
            borderColor: 'rgba(0, 78, 90, 1)',
            borderWidth: 1,
        }],
    } : null;

    const medianSeries = data.median_q_over_time && data.median_q_over_time.length > 0 ? {
        labels: data.median_q_over_time.map(p => timeLabel(p.time)),
        datasets: [{
            label: 'Median Q-score',
            data: data.median_q_over_time.map(p => p.median_q),
            borderColor: '#00B0BD',
            backgroundColor: 'rgba(0, 176, 189, 0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 1.5,
            pointHoverRadius: 5,
            spanGaps: true,
        }, {
            label: 'Floor',
            data: data.median_q_over_time.map(() => cfg?.minMedianQ ?? null),
            borderColor: '#E74C3C',
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false,
        }],
    } : null;

    const throughput = data.throughput && data.throughput.length > 0 ? {
        labels: data.throughput.map(p => timeLabel(p.time)),
        datasets: [{
            label: 'Reads per interval',
            data: data.throughput.map(p => p.reads),
            backgroundColor: 'rgba(0, 176, 189, 0.6)',
            borderColor: 'rgba(0, 176, 189, 1)',
            borderWidth: 1,
        }],
    } : null;

    const minutesSinceData = inputs?.last_data_time ? Math.max(0, (Date.now() / 1000 - inputs.last_data_time) / 60) : null;
    const activeRules = rules.filter(r => r.active);
    const passRate = totals.reads ? ((totals.pass_reads || 0) / totals.reads) * 100 : null;

    return (
        <div className="nano-run-health">
            {!data.monitoring && (
                <div className="nano-alert-banner info">
                    <span className="nano-alert-message">
                        Showing statistics parsed from <code>{data.summary_file?.path?.split('/').pop()}</code>. Start monitoring
                        to evaluate the run-health alert rules continuously.
                    </span>
                </div>
            )}
            {activeRules.length > 0 && (
                <div className="nano-alert-banner critical">
                    <span className="nano-alert-message">
                        <strong>{activeRules.length} run-health rule{activeRules.length > 1 ? 's' : ''} active:</strong>{' '}
                        {activeRules.map(r => r.description).join('; ')}
                    </span>
                </div>
            )}

            <div className="nano-health-summary">
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{formatNumber(totals.reads)}</span>
                    <span className="nano-stat-label">Total Reads</span>
                    <span className="nano-stat-sub">{formatBases(totals.bases)} basecalled</span>
                </div>
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{totals.mean_q != null ? totals.mean_q.toFixed(1) : 'n/a'}</span>
                    <span className="nano-stat-label">Mean Q (run)</span>
                    <span className="nano-stat-sub">{passRate != null ? `${passRate.toFixed(1)}% pass (Q≥${qThreshold})` : ''}</span>
                </div>
                <div className={`nano-stat-card ${cfg && window?.median_q != null && window.median_q < cfg.minMedianQ ? 'warn' : ''}`}>
                    <span className="nano-stat-value">{window?.median_q != null ? window.median_q.toFixed(1) : 'n/a'}</span>
                    <span className="nano-stat-label">Median Q (recent)</span>
                    <span className="nano-stat-sub">last {formatNumber(window?.reads)} reads{cfg ? `, floor ${cfg.minMedianQ}` : ''}</span>
                </div>
                <div className={`nano-stat-card ${cfg && window?.pass_rate != null && window.pass_rate < cfg.minPassRate ? 'warn' : ''}`}>
                    <span className="nano-stat-value">{window?.pass_rate != null ? `${window.pass_rate.toFixed(0)}%` : 'n/a'}</span>
                    <span className="nano-stat-label">Pass rate (recent)</span>
                    <span className="nano-stat-sub">{totals.has_pass_column ? 'MinKNOW passes_filtering' : `Q ≥ ${qThreshold}`}</span>
                </div>
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{window?.median_length != null ? formatNumber(window.median_length) : 'n/a'}</span>
                    <span className="nano-stat-label">Median length (recent)</span>
                    <span className="nano-stat-sub">N50 {formatNumber(window?.n50)} bp</span>
                </div>
                <div className={`nano-stat-card ${activeRules.some(r => r.id === 'pore_decline' || r.id === 'low_active_channels') ? 'warn' : ''}`}>
                    <span className="nano-stat-value">{pores ? `${pores.active_channels}/${pores.total_channels}` : 'n/a'}</span>
                    <span className="nano-stat-label">Active channels</span>
                    <span className="nano-stat-sub">{pores ? `${pores.flow_cell_type}, last ${pores.active_window_min} min` : ''}</span>
                </div>
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{formatDuration(totals.run_elapsed_seconds)}</span>
                    <span className="nano-stat-label">Run time</span>
                    <span className="nano-stat-sub">from sequencing summary</span>
                </div>
                <div className={`nano-stat-card ${activeRules.some(r => r.id === 'data_stalled' || r.id === 'run_not_started') ? 'warn' : ''}`}>
                    <span className="nano-stat-value">{minutesSinceData != null ? `${minutesSinceData.toFixed(0)} min` : 'n/a'}</span>
                    <span className="nano-stat-label">Since last data</span>
                    <span className="nano-stat-sub">{inputs?.last_data_file || (inputs ? 'no data files yet' : 'not monitoring')}</span>
                </div>
            </div>

            {rules.length > 0 && (
                <div className="nano-panel">
                    <div className="nano-panel-header">
                        <h3>Run-health rules</h3>
                        <span className="nano-hint">evaluated every {cfg?.checkIntervalSec ?? 30} s</span>
                    </div>
                    <div className="nano-panel-body">
                        <div className="nano-rule-list">
                            {rules.map(rule => (
                                <div key={rule.id} className={`nano-rule-item ${rule.active ? 'active' : ''} ${cfg && !cfg.enabled ? 'disabled' : ''}`}>
                                    <span className="nano-rule-light" />
                                    <div>
                                        <div className="nano-rule-title">{rule.description}</div>
                                        <div className="nano-rule-desc">{rule.active ? rule.message : 'OK'}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            <div className="nano-health-grid">
                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Q-Score Distribution</h3></div>
                    <div className="nano-panel-body">
                        {qHist ? (
                            <div className="nano-chart-box"><Bar data={qHist} options={chartBase('Mean read Q-score', 'Reads')} /></div>
                        ) : <div className="nano-empty-state"><p>No Q-score data available</p></div>}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Read Length Distribution</h3></div>
                    <div className="nano-panel-body">
                        {lenHist ? (
                            <div className="nano-chart-box"><Bar data={lenHist} options={chartBase('Read length (bp)', 'Reads')} /></div>
                        ) : <div className="nano-empty-state"><p>No read length data available</p></div>}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Median Q-Score Over Time</h3></div>
                    <div className="nano-panel-body">
                        {medianSeries ? (
                            <div className="nano-chart-box">
                                <Line data={medianSeries} options={{
                                    ...chartBase('Run time', 'Median Q-score'),
                                    scales: { x: { title: { display: true, text: 'Run time' } }, y: { title: { display: true, text: 'Median Q-score' }, beginAtZero: false } },
                                }} />
                            </div>
                        ) : <div className="nano-empty-state"><p>No Q-score trend data available</p></div>}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Throughput</h3></div>
                    <div className="nano-panel-body">
                        {throughput ? (
                            <div className="nano-chart-box"><Bar data={throughput} options={chartBase('Run time', 'Reads')} /></div>
                        ) : <div className="nano-empty-state"><p>No throughput data available</p></div>}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Pore Health</h3></div>
                    <div className="nano-panel-body nano-pore-health">
                        {pores && pores.total_channels > 0 ? (
                            <>
                                <div className="nano-pore-stats">
                                    <div className="nano-pore-stat">
                                        <div className="nano-pore-stat-value nano-pore-active">{pores.active_channels}</div>
                                        <div className="nano-pore-stat-label">Active (last {pores.active_window_min} min)</div>
                                    </div>
                                    <div className="nano-pore-stat">
                                        <div className="nano-pore-stat-value nano-pore-total">{pores.channels_seen}</div>
                                        <div className="nano-pore-stat-label">Channels seen (run)</div>
                                    </div>
                                    <div className="nano-pore-stat">
                                        <div className="nano-pore-stat-value">{pores.occupancy_rate}%</div>
                                        <div className="nano-pore-stat-label">of {pores.total_channels} ({pores.flow_cell_type})</div>
                                    </div>
                                </div>
                                <div className="nano-pore-bar">
                                    <div className="nano-pore-bar-fill" style={{ width: `${Math.min(100, pores.occupancy_rate)}%` }}></div>
                                </div>
                                <p className="nano-hint">
                                    "Active" counts channels that produced at least one read in the last {pores.active_window_min} minutes
                                    of run time; it approximates the number of sequencing pores from the sequencing summary. The flow-cell
                                    type is inferred from the highest channel number seen.
                                </p>
                            </>
                        ) : <div className="nano-empty-state"><p>No pore health data available</p></div>}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Inputs &amp; instrument</h3></div>
                    <div className="nano-panel-body">
                        <dl className="nano-kv">
                            <dt>Sequencing summary</dt><dd>{data.summary_file?.path || 'not found'}</dd>
                            <dt>Watched directory</dt><dd>{inputs?.watch_dir || projectData?.minion}</dd>
                            <dt>Data files seen</dt><dd>{inputs?.data_files ?? 'n/a'}</dd>
                            <dt>Files processed / failed</dt><dd>{inputs ? `${inputs.files_processed ?? 0} / ${inputs.files_failed ?? 0}` : 'n/a'}</dd>
                            <dt>Parse errors</dt><dd>{data.summary_file?.parse_errors ?? 0}</dd>
                            {totals.end_reasons && Object.keys(totals.end_reasons).length > 0 && (
                                <>
                                    <dt>Read end reasons</dt>
                                    <dd>{Object.entries(totals.end_reasons).map(([k, v]) => `${k}: ${formatNumber(v)}`).join(', ')}</dd>
                                </>
                            )}
                            <dt>MinKNOW</dt>
                            <dd>
                                {data.minknow ? (
                                    <>
                                        {data.minknow.acquisition_status || 'unknown'}
                                        {data.minknow.flow_cell_id ? ` · flow cell ${data.minknow.flow_cell_id}` : ''}
                                        {data.minknow.product_code ? ` (${data.minknow.product_code})` : ''}
                                        {data.minknow.channel_count ? ` · ${data.minknow.channel_count} channels` : ''}
                                    </>
                                ) : (projectData?.device ? 'not reachable' : 'no device configured')}
                            </dd>
                        </dl>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default RunHealthTab;
