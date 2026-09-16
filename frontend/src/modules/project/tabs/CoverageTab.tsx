import React, { useEffect, useMemo, useState } from "react";
import { Dropdown } from "react-bootstrap";
import {
    Chart as ChartJS,
    LinearScale,
    LineElement,
    PointElement,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import AlignmentViewer from "../../analysis/analysis-data/alignment-viewer.component";
import { api, parseTimestamp, queryByReference } from "../../../api";

ChartJS.register(LinearScale, LineElement, PointElement, Tooltip, Legend, Filler);

interface CoverageTabProps {
    projectId: string;
    projectData: any;
    // Coverage data is owned by ProjectDetail and passed down so the
    // chart doesn't lose its state when the user switches tabs.
    coverageData: any[];
    coverageMap: Map<string, any>;
}

interface AlignmentData {
    reference: string;
    ref_length: number;
    alignments: { start: number; end: number; strand: string }[];
    regions: { start: number; end: number; id: string; read_count: number }[];
    total_alignments: number;
    truncated: boolean;
}

type TimeUnit = 'seconds' | 'minutes' | 'hours' | 'days';
type Metric = 'depth' | 'breadth';

const UNIT_LABELS: Record<TimeUnit, string> = { seconds: 's', minutes: 'min', hours: 'h', days: 'd' };
const UNIT_FACTORS: Record<TimeUnit, number> = { seconds: 1, minutes: 60, hours: 3600, days: 86400 };
const SERIES_COLORS = ['#0f4c5c', '#c0392b', '#2e7d4f', '#b7791f', '#6c5b7b', '#355c7d', '#7a4e2d', '#4b6f44'];

const CoverageTab: React.FC<CoverageTabProps> = ({ projectId, projectData, coverageData, coverageMap }) => {
    const [metric, setMetric] = useState<Metric>('depth');
    const [timeUnit, setTimeUnit] = useState<TimeUnit>('minutes');
    const [selectedReference, setSelectedReference] = useState<string | null>(null);
    const [alignmentData, setAlignmentData] = useState<AlignmentData | null>(null);
    const [alignmentError, setAlignmentError] = useState<string | null>(null);
    const [loadingAlignments, setLoadingAlignments] = useState(false);

    const queries = useMemo(() => queryByReference(projectData), [projectData]);

    // References known from the coverage rows (id -> display name), in
    // first-seen order, with `unmapped` excluded from the chart.
    const references = useMemo(() => {
        const seen = new Map<string, string>();
        coverageData.forEach(d => {
            if (d.reference !== 'unmapped' && !seen.has(d.reference)) seen.set(d.reference, d.name || d.reference);
        });
        // Fall back to the configured queries before any data exists.
        if (seen.size === 0) {
            queries.forEach((q, ref) => seen.set(ref, q.name || ref));
        }
        return seen;
    }, [coverageData, queries]);

    useEffect(() => {
        if (!selectedReference && references.size > 0) {
            // Prefer a reference that actually has an alert threshold so the
            // chart opens with a threshold line.
            const withAlert = Array.from(references.keys()).find(ref => {
                const q = queries.get(ref);
                return q && (q.alert_on_depth || q.alert_on_breadth);
            });
            setSelectedReference(withAlert ?? references.keys().next().value ?? null);
        }
    }, [references, selectedReference, queries]);

    const thresholdFor = (ref: string | null, m: Metric): number | null => {
        if (!ref) return null;
        const q = queries.get(ref);
        if (!q) return null;
        if (m === 'depth' && q.alert_on_depth && q.depth_threshold !== undefined && q.depth_threshold !== '') {
            const v = parseFloat(q.depth_threshold);
            return isNaN(v) ? null : v;
        }
        if (m === 'breadth' && q.alert_on_breadth && q.breadth_threshold !== undefined && q.breadth_threshold !== '') {
            const v = parseFloat(q.breadth_threshold);
            return isNaN(v) ? null : v;
        }
        return null;
    };
    const threshold = thresholdFor(selectedReference, metric);

    useEffect(() => {
        let cancelled = false;
        const fetchAlignments = async () => {
            if (!selectedReference) return;
            setLoadingAlignments(true);
            try {
                const res = await api.get(`/get_alignments`, { params: { projectId, reference: selectedReference } });
                if (!cancelled) { setAlignmentData(res.data); setAlignmentError(null); }
            } catch (err: any) {
                if (!cancelled) {
                    setAlignmentData(null);
                    setAlignmentError(err?.response?.data?.error || 'Alignments are not available yet.');
                }
            } finally {
                if (!cancelled) setLoadingAlignments(false);
            }
        };
        fetchAlignments();
        return () => { cancelled = true; };
    }, [selectedReference, projectId, coverageData.length]);

    const chart = useMemo(() => {
        const refs = Array.from(references.keys());
        const times = Array.from(new Set(coverageData.map(d => d.timestamp)))
            .map(t => ({ t, ms: parseTimestamp(t) }))
            .filter(x => !isNaN(x.ms))
            .sort((a, b) => a.ms - b.ms);
        if (times.length === 0 || refs.length === 0) return null;

        const startTime = times[0].ms;
        const factor = UNIT_FACTORS[timeUnit];
        const toElapsed = (ms: number) => (ms - startTime) / 1000 / factor;
        // Carry the last known value forward so a reference missing from
        // one batch row doesn't drop to zero on the chart.
        const last: Record<string, number> = {};
        const datasets: any[] = refs.map((ref, i) => ({
            label: references.get(ref) || ref,
            data: times.map(({ t, ms }) => {
                const entry = coverageMap.get(`${t}-${ref}`);
                const y = entry ? (metric === 'depth' ? entry.depth : entry.breadth) : (last[ref] ?? 0);
                last[ref] = y;
                return { x: toElapsed(ms), y };
            }),
            borderColor: SERIES_COLORS[i % SERIES_COLORS.length],
            backgroundColor: SERIES_COLORS[i % SERIES_COLORS.length],
            borderWidth: ref === selectedReference ? 2.5 : 1.5,
            pointRadius: times.length > 120 ? 0 : 2,
            pointHoverRadius: 4,
            tension: 0.15,
        }));
        if (threshold !== null) {
            datasets.push({
                label: `Threshold (${references.get(selectedReference!) || selectedReference})`,
                data: [{ x: 0, y: threshold }, { x: toElapsed(times[times.length - 1].ms), y: threshold }],
                borderColor: '#c0392b',
                borderDash: [6, 4],
                borderWidth: 1.5,
                pointRadius: 0,
                fill: false,
            });
        }
        const unit = metric === 'depth' ? 'x' : '%';
        const options: any = {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'nearest', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, usePointStyle: true } },
                tooltip: {
                    callbacks: {
                        title: (items: any[]) => `${items[0]?.parsed.x.toFixed(2)} ${UNIT_LABELS[timeUnit]}`,
                        label: (item: any) => `${item.dataset.label}: ${item.parsed.y.toFixed(2)}${unit}`,
                    },
                },
            },
            scales: {
                x: { type: 'linear', title: { display: true, text: `Elapsed time (${UNIT_LABELS[timeUnit]})` }, min: 0 },
                y: {
                    title: { display: true, text: metric === 'depth' ? 'Depth (x)' : 'Breadth (%)' },
                    beginAtZero: true,
                    ...(metric === 'breadth' ? { max: 100 } : {}),
                },
            },
        };
        return { data: { datasets }, options };
    }, [coverageData, coverageMap, references, metric, timeUnit, threshold, selectedReference]);

    const latestRows = useMemo(() => {
        const latest = new Map<string, any>();
        coverageData.forEach(d => latest.set(d.reference, d));
        return Array.from(latest.values()).sort((a, b) => (a.reference === 'unmapped' ? 1 : 0) - (b.reference === 'unmapped' ? 1 : 0));
    }, [coverageData]);

    const selectedName = selectedReference ? (references.get(selectedReference) || selectedReference) : null;

    return (
        <div className="nano-coverage-tab">
            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Current Coverage</h3>
                </div>
                <div className="nano-panel-body">
                    {latestRows.length === 0 ? (
                        <div className="nano-empty-state">
                            <p>No coverage data available yet.</p>
                            <p className="nano-hint">Start monitoring to begin collecting coverage data.</p>
                        </div>
                    ) : (
                        <table className="nano-table">
                            <thead>
                                <tr>
                                    <th>Sequence</th>
                                    <th>Reference ID</th>
                                    <th>Depth</th>
                                    <th>Breadth</th>
                                    <th>Reads</th>
                                    <th>Depth threshold</th>
                                    <th>Breadth threshold</th>
                                    <th>Updated</th>
                                </tr>
                            </thead>
                            <tbody>
                                {latestRows.map(row => {
                                    const q = queries.get(row.reference);
                                    const dt = q?.alert_on_depth ? parseFloat(q.depth_threshold) : NaN;
                                    const bt = q?.alert_on_breadth ? parseFloat(q.breadth_threshold) : NaN;
                                    const isUnmapped = row.reference === 'unmapped';
                                    return (
                                        <tr key={row.reference}>
                                            <td>{isUnmapped ? <em>Unmapped reads</em> : row.name}</td>
                                            <td><code>{isUnmapped ? '—' : row.reference}</code></td>
                                            <td className={!isNaN(dt) && row.depth >= dt ? 'nano-threshold-hit' : ''}>
                                                {isUnmapped ? '—' : `${row.depth.toFixed(2)}x`}
                                            </td>
                                            <td className={!isNaN(bt) && row.breadth >= bt ? 'nano-threshold-hit' : ''}>
                                                {isUnmapped ? '—' : `${row.breadth.toFixed(2)}%`}
                                            </td>
                                            <td>{row.read_count.toLocaleString()}</td>
                                            <td>{!isNaN(dt) ? `${dt}x` : <span className="text-muted">off</span>}</td>
                                            <td>{!isNaN(bt) ? `${bt}%` : <span className="text-muted">off</span>}</td>
                                            <td className="nano-alert-time">{row.timestamp}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>

            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Coverage Over Time</h3>
                    <div className="nano-panel-controls">
                        <Dropdown>
                            <Dropdown.Toggle variant="secondary" size="sm">
                                {metric === 'depth' ? 'Depth' : 'Breadth'}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                <Dropdown.Item onClick={() => setMetric('depth')}>Depth</Dropdown.Item>
                                <Dropdown.Item onClick={() => setMetric('breadth')}>Breadth</Dropdown.Item>
                            </Dropdown.Menu>
                        </Dropdown>
                        <Dropdown>
                            <Dropdown.Toggle variant="secondary" size="sm">
                                {timeUnit.charAt(0).toUpperCase() + timeUnit.slice(1)}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                {(['seconds', 'minutes', 'hours', 'days'] as TimeUnit[]).map(u => (
                                    <Dropdown.Item key={u} onClick={() => setTimeUnit(u)}>
                                        {u.charAt(0).toUpperCase() + u.slice(1)}
                                    </Dropdown.Item>
                                ))}
                            </Dropdown.Menu>
                        </Dropdown>
                        <Dropdown>
                            <Dropdown.Toggle variant="secondary" size="sm">
                                {selectedName ? `Threshold: ${selectedName}` : 'Select reference'}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                {Array.from(references.entries()).map(([ref, name]) => (
                                    <Dropdown.Item key={ref} onClick={() => setSelectedReference(ref)}>{name}</Dropdown.Item>
                                ))}
                            </Dropdown.Menu>
                        </Dropdown>
                    </div>
                </div>
                <div className="nano-panel-body">
                    {chart ? (
                        <div className="nano-chart-box nano-chart-box-tall">
                            <Line data={chart.data} options={chart.options} />
                        </div>
                    ) : (
                        <div className="nano-empty-state">
                            <p>No coverage data available yet.</p>
                            <p className="nano-hint">The chart appears once the first batch of reads has been aligned.</p>
                        </div>
                    )}
                    {selectedReference && threshold === null && (
                        <p className="nano-hint" style={{ marginTop: 8 }}>
                            No {metric} alert threshold is configured for {selectedName}; no threshold line is drawn.
                        </p>
                    )}
                </div>
            </div>

            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Read Alignments{selectedName ? `: ${selectedName}` : ''}</h3>
                    <Dropdown>
                        <Dropdown.Toggle variant="secondary" size="sm">
                            {selectedName || "Select reference"}
                        </Dropdown.Toggle>
                        <Dropdown.Menu>
                            {Array.from(references.entries()).map(([ref, name]) => (
                                <Dropdown.Item key={ref} onClick={() => setSelectedReference(ref)}>
                                    {name} {name !== ref && <span className="text-muted">({ref})</span>}
                                </Dropdown.Item>
                            ))}
                        </Dropdown.Menu>
                    </Dropdown>
                </div>
                <div className="nano-panel-body">
                    {selectedReference && alignmentData ? (
                        <>
                            {alignmentData.truncated && (
                                <p className="nano-hint">
                                    Showing the first {alignmentData.alignments.length.toLocaleString()} of{' '}
                                    {alignmentData.total_alignments.toLocaleString()} primary alignments.
                                </p>
                            )}
                            <AlignmentViewer
                                refId={selectedReference}
                                refLength={alignmentData.ref_length}
                                alignments={alignmentData.alignments}
                                regions={alignmentData.regions}
                            />
                        </>
                    ) : (
                        <div className="nano-empty-state">
                            {loadingAlignments ? <p>Loading alignments…</p> : (
                                <p>{alignmentError || 'Select a reference to view its aligned reads.'}</p>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default CoverageTab;
