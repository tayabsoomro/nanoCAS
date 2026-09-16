import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js';
import { Scatter } from 'react-chartjs-2';
import { api, Regression, formatNumber } from "../../api";
import "../project/project-detail.css";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend);

interface Agreement {
    sensitivity: number | null; sensitivity_ci: (number | null)[];
    specificity: number | null; specificity_ci: (number | null)[];
    tp: number; fp: number; fn: number; tn: number; kappa: number | null;
}

interface CohortTarget {
    key: string;
    name: string; references: string[]; runs: number; demo_runs: number;
    nanopore_positive: number; positivity: number | null; positivity_ci: [number, number] | null;
    lab_tested: number; lab_positive: number; lab_positivity: number | null; lab_positivity_ci: [number, number] | null;
    agreement: Agreement | null; median_time_to_detection_min: number | null;
    regression: Regression | null; points: { ct: number; log10_rpm: number; project: string; reads: number; total_reads: number }[];
    lod_ct: number | null;
}

interface CohortRun {
    projectId: string; project: string; demo: boolean; created_at: string | null; target: string; reference: string;
    detected: boolean; reads: number; fraction: number; time_to_detection_min: number | null; ct: number | null; lab_positive: boolean | null;
}

const pct = (v: number | null | undefined) => v === null || v === undefined ? '—' : `${(v * 100).toFixed(0)}%`;
const ci = (c: (number | null)[] | null | undefined) => c && c[0] != null && c[1] != null ? ` (${(c[0] * 100).toFixed(0)}–${(c[1] * 100).toFixed(0)}%)` : '';
const fmtMin = (m: number | null) => m === null || m === undefined ? '—' : m < 60 ? `${m.toFixed(0)} min` : `${(m / 60).toFixed(1)} h`;

/** Detection summary pooled across every project. */
const CohortPage: React.FC = () => {
    const [targets, setTargets] = useState<CohortTarget[]>([]);
    const [runs, setRuns] = useState<CohortRun[]>([]);
    const [projects, setProjects] = useState(0);
    const [selected, setSelected] = useState<string>('');
    const [includeDemo, setIncludeDemo] = useState(true);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        api.get('/cohort').then(res => {
            setTargets(res.data.targets || []);
            setRuns(res.data.runs || []);
            setProjects(res.data.projects || 0);
            if (res.data.targets?.length) setSelected(res.data.targets[0].key);
        }).catch(() => { }).finally(() => setLoading(false));
    }, []);

    const target = targets.find(t => t.key === selected);
    const shownRuns = runs.filter(r => (!selected || r.target === selected) && (includeDemo || !r.demo));
    const reg = target?.regression || null;
    const scatter = target && target.points.length > 0 ? {
        datasets: [
            { label: 'Runs', data: target.points.map(p => ({ x: p.ct, y: p.log10_rpm })), backgroundColor: '#0f4c5c', pointRadius: 5 },
            ...(reg ? [{
                label: `log10(RPM) = ${reg.slope.toFixed(3)}·Ct + ${reg.intercept.toFixed(2)}`,
                data: [{ x: reg.x_range[0], y: reg.slope * reg.x_range[0] + reg.intercept }, { x: reg.x_range[1], y: reg.slope * reg.x_range[1] + reg.intercept }],
                type: 'line' as const, borderColor: '#c0392b', borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, fill: false,
            }] : []),
        ],
    } : null;

    return (
        <div className="nano-project-detail">
            <div className="nano-project-header">
                <div className="nano-project-header-left">
                    <Link to="/" className="nano-back-link">&larr; Projects</Link>
                    <h2 className="nano-project-title">Across runs</h2>
                    <span className="nano-project-path">{projects} project{projects === 1 ? '' : 's'} · {targets.length} target{targets.length === 1 ? '' : 's'}</span>
                </div>
                <div className="nano-project-header-right">
                    <div className="form-check">
                        <input className="form-check-input" type="checkbox" id="incl-demo" checked={includeDemo} onChange={e => setIncludeDemo(e.target.checked)} />
                        <label className="form-check-label nano-hint" htmlFor="incl-demo">include demo runs</label>
                    </div>
                </div>
            </div>

            {loading ? <div className="nano-loading-state"><div className="nano-spinner" /></div> : targets.length === 0 ? (
                <div className="nano-empty-state-large"><h3>Nothing to summarise yet</h3><p>Create projects with targets; this page pools their detections and laboratory results.</p></div>
            ) : (
                <>
                    <div className="nano-panel">
                        <div className="nano-panel-header"><h3>Detection by target</h3></div>
                        <div className="nano-panel-body">
                            <table className="nano-table">
                                <thead>
                                    <tr>
                                        <th>Target</th><th>Runs</th><th>Detected by nanopore</th><th>qPCR positive</th>
                                        <th>Sensitivity</th><th>Specificity</th><th>Kappa</th><th>Median time to detection</th><th>Ct limit of detection</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {targets.map(t => (
                                        <tr key={t.key} onClick={() => setSelected(t.key)} style={{ cursor: 'pointer', background: t.key === selected ? 'var(--ont-light-gray)' : undefined }}>
                                            <td>{t.name}<div className="nano-hint"><code>{t.references.join(', ')}</code></div>{t.demo_runs > 0 && <span className="nano-badge nano-badge-info ms-2">{t.demo_runs} demo</span>}</td>
                                            <td>{t.runs}</td>
                                            <td>{t.nanopore_positive}/{t.runs} · {pct(t.positivity)}<span className="nano-hint">{ci(t.positivity_ci)}</span></td>
                                            <td>{t.lab_tested ? `${t.lab_positive}/${t.lab_tested} · ${pct(t.lab_positivity)}` : <span className="text-muted">no results</span>}</td>
                                            <td>{t.agreement ? <>{pct(t.agreement.sensitivity)}<span className="nano-hint">{ci(t.agreement.sensitivity_ci)}</span></> : '—'}</td>
                                            <td>{t.agreement ? <>{pct(t.agreement.specificity)}<span className="nano-hint">{ci(t.agreement.specificity_ci)}</span></> : '—'}</td>
                                            <td>{t.agreement?.kappa != null ? t.agreement.kappa.toFixed(2) : '—'}</td>
                                            <td>{fmtMin(t.median_time_to_detection_min)}</td>
                                            <td>{t.lod_ct != null ? `Ct ≈ ${t.lod_ct.toFixed(1)}` : '—'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            <p className="nano-hint mt-2">
                                Proportions carry Wilson 95 % intervals. Sensitivity and specificity treat qPCR as the reference test.
                                The Ct limit of detection is where the pooled fit predicts 3 target reads in a median-sized run (95 % chance of ≥ 1 read under a Poisson model).
                            </p>
                        </div>
                    </div>

                    <div className="nano-health-grid">
                        <div className="nano-panel">
                            <div className="nano-panel-header"><h3>Read yield vs Ct{target ? `: ${target.name}` : ''}</h3></div>
                            <div className="nano-panel-body">
                                {scatter ? (
                                    <>
                                        <div className="nano-chart-box"><Scatter data={scatter as any} options={{
                                            responsive: true, maintainAspectRatio: false,
                                            plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } }, tooltip: { callbacks: { label: (i: any) => `${target!.points[i.dataIndex]?.project ?? ''}: Ct ${i.parsed.x}, ${i.parsed.y.toFixed(2)}` } } },
                                            scales: { x: { title: { display: true, text: 'qPCR Ct' } }, y: { title: { display: true, text: 'log10 reads per million' } } },
                                        }} /></div>
                                        {reg && <dl className="nano-kv mt-3">
                                            <dt>n</dt><dd>{reg.n}</dd>
                                            <dt>Pearson r</dt><dd>{reg.r.toFixed(3)} (p {reg.p < 0.001 ? '< 0.001' : reg.p.toFixed(3)})</dd>
                                            <dt>Slope</dt><dd>{reg.slope.toFixed(3)} log10 RPM / Ct</dd>
                                        </dl>}
                                    </>
                                ) : <div className="nano-empty-state"><p>No runs with both a detection and a Ct for this target yet.</p></div>}
                            </div>
                        </div>

                        <div className="nano-panel">
                            <div className="nano-panel-header"><h3>Runs{target ? `: ${target.name}` : ''}</h3></div>
                            <div className="nano-panel-body">
                                <table className="nano-table">
                                    <thead><tr><th>Project</th><th>Nanopore</th><th>Reads</th><th>Time to detection</th><th>qPCR</th></tr></thead>
                                    <tbody>
                                        {shownRuns.map(r => (
                                            <tr key={`${r.projectId}-${r.reference}`}>
                                                <td><Link to={`/project/${r.projectId}/results`}>{r.project}</Link>{r.demo && <span className="nano-badge nano-badge-info ms-2">demo</span>}</td>
                                                <td><span className={`nano-badge ${r.detected ? 'nano-badge-critical' : 'nano-badge-inactive'}`}>{r.detected ? 'detected' : 'not detected'}</span></td>
                                                <td>{formatNumber(r.reads)}</td>
                                                <td>{fmtMin(r.time_to_detection_min)}</td>
                                                <td>{r.lab_positive === null ? '—' : r.lab_positive ? `positive${r.ct != null ? ` (Ct ${r.ct})` : ''}` : 'negative'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
};

export default CohortPage;
