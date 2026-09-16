import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js';
import { Scatter } from 'react-chartjs-2';
import { api, LabResult, Regression, formatNumber } from "../../../api";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend);

interface ResultsTabProps {
    projectId: string;
    projectData: any;
}

interface TargetRow {
    reference: string;
    name: string;
    reads: number;
    fraction: number;
    depth: number;
    breadth: number;
    total_reads: number;
    log10_rpm: number | null;
    detected: boolean;
    time_to_detection_min: number | null;
    thresholds: { metric: string; value: number }[];
    lab_results: LabResult[];
    ct: number | null;
    lab_positive: boolean | null;
    agreement: 'concordant' | 'discordant' | null;
}

interface Correlation {
    targets: TargetRow[];
    regression: Regression | null;
    spearman: number | null;
    points: { ct: number; log10_rpm: number }[];
    unmatched_results: LabResult[];
}

const fmtMin = (m: number | null) => m === null || m === undefined ? '—' : m < 60 ? `${m.toFixed(0)} min` : `${(m / 60).toFixed(1)} h`;

/** qPCR results next to what the run found, with the log10(RPM)–Ct relationship. */
const ResultsTab: React.FC<ResultsTabProps> = ({ projectId, projectData }) => {
    const [data, setData] = useState<Correlation | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [form, setForm] = useState({ target: '', sample_id: '', assay: 'qPCR', ct: '', result: 'positive', date: new Date().toISOString().slice(0, 10), notes: '' });

    const targets: { ref: string; name: string }[] = useMemo(() => {
        const out: { ref: string; name: string }[] = [];
        (projectData?.queries || []).forEach((q: any) => {
            const ref = (q.header || (q.headers || [])[0] || '').trim().split(/\s+/)[0];
            const kind = projectData?.classifier?.name;
            const key = (kind === 'kraken2' || kind === 'centrifuge') ? (q.header || '').trim().toLowerCase() : ref;
            if (key && !out.find(o => o.ref === key)) out.push({ ref: key, name: q.name || key });
        });
        return out;
    }, [projectData]);

    const load = useCallback(async () => {
        try {
            const res = await api.get(`/lab_correlation?projectId=${projectId}`);
            setData(res.data);
            setError(null);
        } catch (err: any) {
            setError(err?.response?.data?.error || 'Could not load results.');
        }
    }, [projectId]);

    useEffect(() => { load(); }, [load]);
    useEffect(() => { if (!form.target && targets.length) setForm(f => ({ ...f, target: targets[0].ref })); }, [targets, form.target]);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        try {
            await api.post('/lab_results', { projectId, ...form, ct: form.result === 'positive' ? form.ct : '' });
            setForm(f => ({ ...f, sample_id: '', ct: '', notes: '' }));
            await load();
        } catch (err: any) {
            setError(err?.response?.data?.error || 'Could not save the result.');
        } finally {
            setSaving(false);
        }
    };

    const remove = async (id: string) => {
        await api.delete('/lab_results', { data: { projectId, id } });
        await load();
    };

    const reg = data?.regression || null;
    const scatter = data && data.points.length > 0 ? {
        datasets: [
            {
                label: 'Targets',
                data: data.points.map(p => ({ x: p.ct, y: p.log10_rpm })),
                backgroundColor: '#0f4c5c',
                pointRadius: 5,
            },
            ...(reg ? [{
                label: `Fit: log10(RPM) = ${reg.slope.toFixed(3)}·Ct + ${reg.intercept.toFixed(2)}`,
                data: [{ x: reg.x_range[0], y: reg.slope * reg.x_range[0] + reg.intercept }, { x: reg.x_range[1], y: reg.slope * reg.x_range[1] + reg.intercept }],
                type: 'line' as const, borderColor: '#c0392b', borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, fill: false,
            }] : []),
        ],
    } : null;

    return (
        <div className="nano-results-tab">
            <div className="nano-panel">
                <div className="nano-panel-header"><h3>Sequencing vs laboratory result</h3></div>
                <div className="nano-panel-body">
                    {error && <div className="nano-alert-banner critical"><span className="nano-alert-message">{error}</span></div>}
                    {data && data.targets.length > 0 ? (
                        <table className="nano-table">
                            <thead>
                                <tr>
                                    <th>Target</th><th>Nanopore</th><th>Reads</th><th>% of reads</th><th>Time to detection</th>
                                    <th>qPCR</th><th>Ct</th><th>Agreement</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.targets.map(t => (
                                    <tr key={t.reference}>
                                        <td>{t.name}<div className="nano-hint"><code>{t.reference}</code></div></td>
                                        <td><span className={`nano-badge ${t.detected ? 'nano-badge-critical' : 'nano-badge-inactive'}`}>{t.detected ? 'detected' : 'not detected'}</span></td>
                                        <td>{formatNumber(t.reads)}</td>
                                        <td>{t.fraction != null ? `${t.fraction.toFixed(2)}%` : '—'}</td>
                                        <td>{fmtMin(t.time_to_detection_min)}</td>
                                        <td>{t.lab_positive === null ? <span className="text-muted">no result</span> : <span className={`nano-badge ${t.lab_positive ? 'nano-badge-critical' : 'nano-badge-inactive'}`}>{t.lab_positive ? 'positive' : 'negative'}</span>}</td>
                                        <td>{t.ct != null ? t.ct.toFixed(1) : '—'}</td>
                                        <td>{t.agreement ? <span className={`nano-badge ${t.agreement === 'concordant' ? 'nano-badge-active' : 'nano-badge-warning'}`}>{t.agreement}</span> : '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : <div className="nano-empty-state"><p>No targets configured.</p></div>}
                    <p className="nano-hint mt-2">"Detected" means one of the target's alert thresholds was reached; time to detection is measured from the first processed batch.</p>
                </div>
            </div>

            <div className="nano-health-grid">
                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Add a laboratory result</h3></div>
                    <div className="nano-panel-body">
                        <form onSubmit={submit}>
                            <div className="nano-field-row">
                                <label>Target</label>
                                <select className="form-select" value={form.target} onChange={e => setForm({ ...form, target: e.target.value })}>
                                    {targets.map(t => <option key={t.ref} value={t.ref}>{t.name}</option>)}
                                </select>
                            </div>
                            <div className="nano-field-row">
                                <label>Result</label>
                                <div className="d-flex gap-3">
                                    {['positive', 'negative', 'inconclusive'].map(r => (
                                        <div className="form-check" key={r}>
                                            <input className="form-check-input" type="radio" id={`res-${r}`} checked={form.result === r} onChange={() => setForm({ ...form, result: r })} />
                                            <label className="form-check-label" htmlFor={`res-${r}`}>{r}</label>
                                        </div>
                                    ))}
                                </div>
                            </div>
                            {form.result === 'positive' && (
                                <div className="nano-field-row">
                                    <label>Ct value</label>
                                    <div>
                                        <input className="form-control" type="number" min="1" max="59" step="0.1" required value={form.ct} onChange={e => setForm({ ...form, ct: e.target.value })} placeholder="e.g. 24.5" />
                                    </div>
                                </div>
                            )}
                            <div className="nano-field-row">
                                <label>Sample ID</label>
                                <input className="form-control" value={form.sample_id} onChange={e => setForm({ ...form, sample_id: e.target.value })} placeholder="optional" />
                            </div>
                            <div className="nano-field-row">
                                <label>Assay</label>
                                <input className="form-control" value={form.assay} onChange={e => setForm({ ...form, assay: e.target.value })} />
                            </div>
                            <div className="nano-field-row">
                                <label>Date</label>
                                <input className="form-control" type="date" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} />
                            </div>
                            <div className="d-flex justify-content-end">
                                <button className="btn btn-primary btn-sm" type="submit" disabled={saving || !form.target}>{saving ? 'Saving…' : 'Save result'}</button>
                            </div>
                        </form>
                        {data && (data.targets.some(t => t.lab_results.length) || data.unmatched_results.length > 0) && (
                            <table className="nano-table mt-3">
                                <thead><tr><th>Date</th><th>Target</th><th>Sample</th><th>Result</th><th>Ct</th><th></th></tr></thead>
                                <tbody>
                                    {[...data.targets.flatMap(t => t.lab_results.map(r => ({ ...r, name: t.name }))),
                                      ...data.unmatched_results.map(r => ({ ...r, name: `${r.target} (not a target)` }))]
                                        .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
                                        .map(r => (
                                            <tr key={r.id}>
                                                <td className="nano-alert-time">{r.date}</td><td>{r.name}</td><td>{r.sample_id || '—'}</td>
                                                <td>{r.result}</td><td>{r.ct != null ? r.ct.toFixed(1) : '—'}</td>
                                                <td className="text-end"><button className="btn btn-link btn-sm p-0" onClick={() => remove(r.id)}>remove</button></td>
                                            </tr>
                                        ))}
                                </tbody>
                            </table>
                        )}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header"><h3>Read yield vs Ct</h3></div>
                    <div className="nano-panel-body">
                        {scatter ? (
                            <>
                                <div className="nano-chart-box">
                                    <Scatter data={scatter as any} options={{
                                        responsive: true, maintainAspectRatio: false,
                                        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } },
                                        scales: {
                                            x: { title: { display: true, text: 'qPCR Ct' } },
                                            y: { title: { display: true, text: 'log10 reads per million' } },
                                        },
                                    }} />
                                </div>
                                <dl className="nano-kv mt-3">
                                    <dt>Points</dt><dd>{data!.points.length} target{data!.points.length === 1 ? '' : 's'} with a Ct</dd>
                                    {reg ? (
                                        <>
                                            <dt>Pearson r</dt><dd>{reg.r.toFixed(3)} (r² {reg.r2.toFixed(3)}, p {reg.p < 0.001 ? '< 0.001' : reg.p.toFixed(3)})</dd>
                                            <dt>Slope</dt><dd>{reg.slope.toFixed(3)} log10 RPM per Ct (−0.30 expected at 100 % PCR efficiency)</dd>
                                            <dt>Spearman ρ</dt><dd>{data!.spearman != null ? data!.spearman.toFixed(3) : '—'}</dd>
                                        </>
                                    ) : <><dt>Fit</dt><dd>needs at least 3 targets with a Ct; the across-runs summary pools every project.</dd></>}
                                </dl>
                            </>
                        ) : (
                            <div className="nano-empty-state">
                                <p>Add positive qPCR results with Ct values to see how read yield tracks template load.</p>
                                <p className="nano-hint">Each Ct cycle is one doubling of template, so log10(reads per million) is expected to fall linearly with Ct.</p>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ResultsTab;
