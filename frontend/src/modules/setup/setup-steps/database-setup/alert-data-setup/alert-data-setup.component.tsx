import React, { FunctionComponent, useEffect, useMemo, useState } from "react";
import { IDatabaseSetupConstituent } from "../database-setup.interfaces";
import { Modal, Button, Form, Table } from "react-bootstrap";
import { IAlertData, IClassifierSelection, IFastaRecord, IQuery } from "./alert-data-setup.interfaces";
import { api, ClassifierInfo, GffFeature, THRESHOLD_KINDS, describeThresholds } from "../../../../../api";

/**
 * Step 1, panel 2: the classifier, the targets to watch for, their alert
 * thresholds, and (optionally) GFF features to alert on.
 */
const AlertDataSetup: FunctionComponent<IDatabaseSetupConstituent<IAlertData>> = ({ initialConfig, updateConfig }) => {
    const [queries, setQueries] = useState<IQuery[]>(initialConfig.queries);
    const [gffFilePath, setGffFilePath] = useState<string | null>(initialConfig.gff_file || null);
    const [gffError, setGffError] = useState<string | null>(null);
    const [gffFeatures, setGffFeatures] = useState<GffFeature[]>([]);
    const [gffTypes, setGffTypes] = useState<Record<string, number>>({});
    const [regions, setRegions] = useState<GffFeature[]>(initialConfig.regions || []);
    const [showModal, setShowModal] = useState(false);
    const [showGff, setShowGff] = useState(false);
    const [classifiers, setClassifiers] = useState<ClassifierInfo[]>([]);
    const [classifier, setClassifier] = useState<IClassifierSelection>(initialConfig.classifier || { name: 'minimap2' });

    useEffect(() => {
        api.get('/classifiers').then(res => setClassifiers(res.data.classifiers || [])).catch(() => { });
    }, []);

    const current = useMemo(() => classifiers.find(c => c.name === classifier.name), [classifiers, classifier.name]);
    const isTaxonomic = current?.kind === 'taxonomic';

    const handleAddQueries = (newQueries: IQuery[]) => {
        setQueries((prev) => {
            const known = new Set(prev.map(q => `${q.file}::${q.header}`));
            return [...prev, ...newQueries.filter(q => !known.has(`${q.file}::${q.header}`))];
        });
        setShowModal(false);
    };

    const handleRemoveQuery = (index: number) => {
        setQueries((prev) => prev.filter((_, i) => i !== index));
    };

    const handleGffFileChange = async (evt: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFile = evt.target.files?.[0];
        if (!selectedFile) return;
        const formData = new FormData();
        formData.append('file', selectedFile);
        setGffError(null);
        try {
            const uploadRes = await api.post('/upload_gff', formData);
            const path = uploadRes.data.file_path;
            setGffFilePath(path);
            const parsed = await api.post('/parse_gff', { file_path: path });
            setGffFeatures(parsed.data.features || []);
            setGffTypes(parsed.data.types || {});
            setRegions([]);
            setShowGff(true);
        } catch (err: any) {
            setGffError(err?.response?.data?.error || 'GFF upload failed');
        }
    };

    const changeClassifier = (name: string) => {
        setClassifier({ name, database: '' });
        // Targets are classifier-specific (FASTA records vs taxa); start over.
        setQueries([]);
    };

    useEffect(() => {
        updateConfig({ queries, gff_file: gffFilePath || undefined, regions, classifier });
    }, [queries, gffFilePath, regions, classifier, updateConfig]);

    const selectedRegions = regions.filter(r => r.alert_enabled !== false);

    return (
        <div>
            <h4>What to watch for</h4>
            <p>Choose how reads are classified, then add the sequences or taxa that should raise an alert.</p>

            <div className="nano-field-row">
                <label htmlFor="classifier">Classifier</label>
                <div>
                    <select id="classifier" className="form-select" value={classifier.name} onChange={e => changeClassifier(e.target.value)}>
                        {classifiers.map(c => (
                            <option key={c.name} value={c.name} disabled={!c.available}>
                                {c.label}{!c.available ? ' (not installed)' : ''}{!c.builtin ? ' · plug-in' : ''}
                            </option>
                        ))}
                        {classifiers.length === 0 && <option value="minimap2">minimap2 (alignment)</option>}
                    </select>
                    <div className="form-text">{current?.description || 'Reads are aligned to your reference sequences with minimap2.'}</div>
                </div>
            </div>

            {current?.reference_input === 'database' && (
                <div className="nano-field-row">
                    <label htmlFor="database">Database</label>
                    <div>
                        <input id="database" className="form-control" type="text" placeholder="/path/to/database"
                               value={classifier.database || ''} onChange={e => setClassifier(prev => ({ ...prev, database: e.target.value }))} />
                        <div className="form-text">{current.database_hint} Must be readable by the nanoCAS server.</div>
                    </div>
                </div>
            )}

            {queries.length === 0 ? (
                <div className="nano-projects-empty" style={{ padding: 16 }}>
                    <p>No targets yet.</p>
                </div>
            ) : (
                <Table hover responsive className="mt-3 mb-2">
                    <thead>
                        <tr>
                            <th>Target</th>
                            <th>{isTaxonomic ? 'Taxon / taxid' : 'Reference ID'}</th>
                            <th>Alert when</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {queries.map((q, i) => (
                            <tr key={`${q.file}-${q.header}-${i}`}>
                                <td>{q.name}</td>
                                <td><code>{q.header}</code>{q.description ? <div className="nano-hint">{q.description}{q.length ? ` · ${q.length.toLocaleString()} bp` : ''}</div> : null}</td>
                                <td>{describeThresholds(q).join(', ') || <span className="text-muted">no alert</span>}</td>
                                <td className="text-end">
                                    <Button variant="outline-secondary" size="sm" onClick={() => handleRemoveQuery(i)} aria-label="Remove target">Remove</Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            )}

            <div className="d-flex align-items-center gap-3 mt-2 flex-wrap">
                <Button variant="primary" size="sm" onClick={() => setShowModal(true)}
                        disabled={current?.reference_input === 'database' && !classifier.database}>
                    + Add targets
                </Button>
                {!isTaxonomic && (
                    <>
                        <Form.Group className="mb-0 d-flex align-items-center gap-2">
                            <Form.Label className="mb-0 nano-hint">Features (GFF3, optional)</Form.Label>
                            <Form.Control type="file" size="sm" accept=".gff,.gff3,.txt,.gz" onChange={handleGffFileChange} style={{ maxWidth: 240 }} />
                        </Form.Group>
                        {gffFilePath && (
                            <button type="button" className="btn btn-link btn-sm p-0" onClick={() => setShowGff(true)}>
                                {selectedRegions.length} feature alert{selectedRegions.length === 1 ? '' : 's'} · edit
                            </button>
                        )}
                        {gffError && <span className="text-danger small">{gffError}</span>}
                    </>
                )}
            </div>

            <AddTargetModal show={showModal} onHide={() => setShowModal(false)} onAdd={handleAddQueries}
                            classifier={current} database={classifier.database} />
            <GffFeatureModal show={showGff} onHide={() => setShowGff(false)} features={gffFeatures} types={gffTypes}
                             initial={regions} onSave={(sel) => { setRegions(sel); setShowGff(false); }} />
        </div>
    );
};

// ---------------------------------------------------------------------------
// Add targets
// ---------------------------------------------------------------------------

type ThresholdState = { [key: string]: any };

const defaultThresholds = (taxonomic: boolean): ThresholdState => taxonomic
    ? { alert_on_depth: false, depth_threshold: '', alert_on_breadth: false, breadth_threshold: '',
        alert_on_reads: true, reads_threshold: '50', alert_on_fraction: false, fraction_threshold: '1' }
    : { alert_on_depth: true, depth_threshold: '10', alert_on_breadth: false, breadth_threshold: '',
        alert_on_reads: false, reads_threshold: '', alert_on_fraction: false, fraction_threshold: '' };

type AddTargetModalProps = {
    show: boolean;
    onHide: () => void;
    onAdd: (newQueries: IQuery[]) => void;
    classifier?: ClassifierInfo;
    database?: string;
};

const AddTargetModal: FunctionComponent<AddTargetModalProps> = ({ show, onHide, onAdd, classifier, database }) => {
    const taxonomic = classifier?.kind === 'taxonomic';
    const allowed = classifier?.metrics || ['depth', 'breadth', 'reads', 'fraction'];
    const [filePath, setFilePath] = useState<string>("");
    const [records, setRecords] = useState<IFastaRecord[]>([]);
    const [selectedHeaders, setSelectedHeaders] = useState<string[]>([]);
    const [taxa, setTaxa] = useState<string>("");
    const [displayName, setDisplayName] = useState("");
    const [thresholds, setThresholds] = useState<ThresholdState>(defaultThresholds(false));
    const [errors, setErrors] = useState<{ [key: string]: string }>({});
    const [parsing, setParsing] = useState(false);

    useEffect(() => { setThresholds(defaultThresholds(!!taxonomic)); }, [taxonomic]);

    const reset = () => {
        setFilePath(""); setRecords([]); setSelectedHeaders([]); setTaxa(""); setDisplayName("");
        setThresholds(defaultThresholds(!!taxonomic)); setErrors({});
    };

    const handleFileChange = async (evt: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFile = evt.target.files?.[0];
        if (!selectedFile) return;
        setParsing(true);
        setErrors({});
        const formData = new FormData();
        formData.append('file', selectedFile);
        try {
            const uploadRes = await api.post('/upload_fasta', formData);
            const path = uploadRes.data.file_path;
            setFilePath(path);
            const headersRes = await api.post('/parse_fasta_headers', { file_path: path });
            const recs: IFastaRecord[] = headersRes.data.records
                || (headersRes.data.headers || []).map((h: string) => ({ id: h, description: '', length: 0 }));
            setRecords(recs);
            setSelectedHeaders(recs.length === 1 ? [recs[0].id] : []);
        } catch (err: any) {
            setErrors({ file: err?.response?.data?.error || 'Failed to upload or parse the FASTA file' });
        } finally {
            setParsing(false);
        }
    };

    const handleHeaderChange = (evt: React.ChangeEvent<HTMLSelectElement>) => {
        const selected: string[] = [];
        for (let i = 0; i < evt.target.options.length; i++) {
            if (evt.target.options[i].selected) selected.push(evt.target.options[i].value);
        }
        setSelectedHeaders(selected);
    };

    const validate = () => {
        const e: { [key: string]: string } = {};
        if (taxonomic) {
            if (!taxa.trim()) e.taxa = 'Enter at least one taxon name or NCBI taxid.';
        } else {
            if (!filePath) e.file = 'A reference FASTA file is required.';
            if (selectedHeaders.length === 0) e.header = 'Select at least one sequence.';
        }
        const enabled = THRESHOLD_KINDS.filter(k => allowed.includes(k.metric) && thresholds[k.flag]);
        if (enabled.length === 0) e.alert = 'Enable at least one alert threshold.';
        for (const k of enabled) {
            const v = parseFloat(thresholds[k.key]);
            if (thresholds[k.key] === '' || isNaN(v) || v < 0 || (k.unit === '%' && v > 100) || (k.metric === 'fraction' && v > 100)) {
                e[k.key] = k.unit === '%' || k.metric === 'fraction' ? 'Enter a value between 0 and 100.' : 'Enter a number ≥ 0.';
            }
        }
        setErrors(e);
        return Object.keys(e).length === 0;
    };

    const thresholdFields = (): Partial<IQuery> => {
        const out: any = {};
        THRESHOLD_KINDS.forEach(k => {
            const on = allowed.includes(k.metric) && !!thresholds[k.flag];
            out[k.flag] = on;
            out[k.key] = on ? String(thresholds[k.key]) : '';
        });
        return out;
    };

    const handleSubmit = () => {
        if (!validate()) return;
        let newQueries: IQuery[];
        if (taxonomic) {
            const items = taxa.split(/[\n,;]+/).map(t => t.trim()).filter(Boolean);
            newQueries = items.map(t => ({
                name: (items.length === 1 && displayName.trim()) ? displayName.trim() : t,
                file: database || '', header: t, headers: [t],
                alert_on_depth: false, alert_on_breadth: false, ...thresholdFields(),
            }));
        } else {
            const useAll = selectedHeaders.includes("ALL");
            const chosen = useAll ? records : records.filter(r => selectedHeaders.includes(r.id));
            newQueries = chosen.map(rec => ({
                name: (chosen.length === 1 && displayName.trim()) ? displayName.trim() : rec.id,
                file: filePath, header: rec.id, headers: [rec.id], description: rec.description, length: rec.length,
                alert_on_depth: false, alert_on_breadth: false, ...thresholdFields(),
            }));
        }
        onAdd(newQueries);
        reset();
    };

    const single = taxonomic
        ? taxa.split(/[\n,;]+/).map(t => t.trim()).filter(Boolean).length === 1
        : selectedHeaders.length === 1 && selectedHeaders[0] !== 'ALL';

    return (
        <Modal show={show} onHide={() => { reset(); onHide(); }} centered size="lg">
            <Modal.Header closeButton>
                <Modal.Title>Add targets</Modal.Title>
            </Modal.Header>
            <Modal.Body>
                <Form>
                    {taxonomic ? (
                        <Form.Group className="mb-3">
                            <Form.Label>Taxa to watch for</Form.Label>
                            <Form.Control as="textarea" rows={3} value={taxa} onChange={e => setTaxa(e.target.value)}
                                          placeholder={"One per line, e.g.\nEscherichia coli\n1280"} isInvalid={!!errors.taxa} />
                            <Form.Text className="text-muted">Names exactly as they appear in the classifier's report, or NCBI taxids. Clade counts are used (a genus includes its species).</Form.Text>
                            <Form.Control.Feedback type="invalid">{errors.taxa}</Form.Control.Feedback>
                        </Form.Group>
                    ) : (
                        <>
                            <Form.Group className="mb-3">
                                <Form.Label>Reference FASTA file</Form.Label>
                                <Form.Control type="file" accept=".fasta,.fna,.fa,.fasta.gz,.fna.gz,.fa.gz"
                                              onChange={handleFileChange} isInvalid={!!errors.file} />
                                <Form.Control.Feedback type="invalid">{errors.file}</Form.Control.Feedback>
                                {parsing && <Form.Text className="text-muted">Uploading and reading headers…</Form.Text>}
                            </Form.Group>
                            {records.length > 0 && (
                                <Form.Group className="mb-3">
                                    <Form.Label>Sequences ({records.length} in file)</Form.Label>
                                    <Form.Select multiple value={selectedHeaders} onChange={handleHeaderChange}
                                                 isInvalid={!!errors.header} htmlSize={Math.min(8, records.length + 1)}>
                                        {records.length > 1 && <option value="ALL">ALL sequences in this file</option>}
                                        {records.map((rec) => (
                                            <option key={rec.id} value={rec.id}>
                                                {rec.id}{rec.description ? ` — ${rec.description}` : ''}{rec.length ? ` (${rec.length.toLocaleString()} bp)` : ''}
                                            </option>
                                        ))}
                                    </Form.Select>
                                    <Form.Text className="text-muted">Ctrl/Cmd-click to select several. Each becomes its own target.</Form.Text>
                                    <Form.Control.Feedback type="invalid">{errors.header}</Form.Control.Feedback>
                                </Form.Group>
                            )}
                        </>
                    )}
                    {single && (
                        <Form.Group className="mb-3">
                            <Form.Label>Display name (optional)</Form.Label>
                            <Form.Control type="text" value={displayName} onChange={e => setDisplayName(e.target.value)} maxLength={80}
                                          placeholder="Shown in charts and alert messages" />
                        </Form.Group>
                    )}
                    <Form.Label>Alert when</Form.Label>
                    <div className="row">
                        {THRESHOLD_KINDS.filter(k => allowed.includes(k.metric)).map(k => (
                            <div className="col-md-6" key={k.key}>
                                <Form.Group className="mb-3">
                                    <Form.Check type="checkbox" id={`chk-${k.key}`} label={`${k.label} ≥`} checked={!!thresholds[k.flag]}
                                                onChange={e => setThresholds(prev => ({ ...prev, [k.flag]: e.target.checked }))} />
                                    <div className="input-group input-group-sm">
                                        <Form.Control type="number" min="0" step={k.metric === 'reads' ? 1 : 0.1} value={thresholds[k.key]}
                                                      disabled={!thresholds[k.flag]} isInvalid={!!errors[k.key]}
                                                      onChange={e => setThresholds(prev => ({ ...prev, [k.key]: e.target.value }))} />
                                        <span className="input-group-text">{k.unit}</span>
                                    </div>
                                    <Form.Text className="text-muted">{k.help}</Form.Text>
                                    {errors[k.key] && <div className="text-danger small">{errors[k.key]}</div>}
                                </Form.Group>
                            </div>
                        ))}
                    </div>
                    {errors.alert && <div className="text-danger small">{errors.alert}</div>}
                </Form>
            </Modal.Body>
            <Modal.Footer>
                <Button variant="outline-secondary" onClick={() => { reset(); onHide(); }}>Cancel</Button>
                <Button variant="primary" onClick={handleSubmit} disabled={parsing}>Add</Button>
            </Modal.Footer>
        </Modal>
    );
};

// ---------------------------------------------------------------------------
// GFF feature picker
// ---------------------------------------------------------------------------

type GffModalProps = {
    show: boolean;
    onHide: () => void;
    features: GffFeature[];
    types: Record<string, number>;
    initial: GffFeature[];
    onSave: (selection: GffFeature[]) => void;
};

const GffFeatureModal: FunctionComponent<GffModalProps> = ({ show, onHide, features, types, initial, onSave }) => {
    const [typeFilter, setTypeFilter] = useState<string>('');
    const [search, setSearch] = useState('');
    const [selected, setSelected] = useState<Map<string, GffFeature>>(new Map());
    const [defaultThreshold, setDefaultThreshold] = useState('10');

    const keyOf = (f: GffFeature) => `${f.seqid}:${f.start}-${f.end}:${f.id}`;

    useEffect(() => {
        if (show) setSelected(new Map(initial.map(f => [keyOf(f), f])));
    }, [show, initial]);

    useEffect(() => {
        if (!typeFilter && Object.keys(types).length) {
            const preferred = ['gene', 'CDS', 'mRNA'].find(t => types[t]) || Object.keys(types)[0];
            setTypeFilter(preferred);
        }
    }, [types, typeFilter]);

    const visible = useMemo(() => {
        const q = search.trim().toLowerCase();
        return features.filter(f => (!typeFilter || f.type === typeFilter) &&
            (!q || f.id.toLowerCase().includes(q) || f.name.toLowerCase().includes(q) || f.product.toLowerCase().includes(q)))
            .slice(0, 500);
    }, [features, typeFilter, search]);

    const toggle = (f: GffFeature) => {
        setSelected(prev => {
            const next = new Map(prev);
            const k = keyOf(f);
            if (next.has(k)) next.delete(k);
            else next.set(k, { ...f, alert_enabled: true, threshold: defaultThreshold });
            return next;
        });
    };

    const selectVisible = (on: boolean) => {
        setSelected(prev => {
            const next = new Map(prev);
            visible.forEach(f => { const k = keyOf(f); if (on) next.set(k, { ...f, alert_enabled: true, threshold: next.get(k)?.threshold ?? defaultThreshold }); else next.delete(k); });
            return next;
        });
    };

    const setThreshold = (f: GffFeature, value: string) => {
        setSelected(prev => {
            const next = new Map(prev);
            const k = keyOf(f);
            if (next.has(k)) next.set(k, { ...next.get(k)!, threshold: value });
            return next;
        });
    };

    return (
        <Modal show={show} onHide={onHide} centered size="lg" scrollable>
            <Modal.Header closeButton>
                <Modal.Title>Feature alerts ({selected.size} selected)</Modal.Title>
            </Modal.Header>
            <Modal.Body>
                <p className="nano-hint">Tick the features (genes, CDS, …) that should raise an alert when their own depth of coverage reaches the threshold. Features on sequences you are not watching are ignored.</p>
                <div className="d-flex gap-2 flex-wrap align-items-center mb-2">
                    <select className="form-select form-select-sm" style={{ maxWidth: 200 }} value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
                        <option value="">All types</option>
                        {Object.entries(types).map(([t, n]) => <option key={t} value={t}>{t} ({n})</option>)}
                    </select>
                    <input className="form-control form-control-sm" style={{ maxWidth: 240 }} placeholder="Search id / name / product" value={search} onChange={e => setSearch(e.target.value)} />
                    <div className="input-group input-group-sm" style={{ maxWidth: 200 }}>
                        <span className="input-group-text">Default</span>
                        <input type="number" className="form-control" min="0" step="0.5" value={defaultThreshold} onChange={e => setDefaultThreshold(e.target.value)} />
                        <span className="input-group-text">x</span>
                    </div>
                    <button className="btn btn-outline-secondary btn-sm" onClick={() => selectVisible(true)}>Select shown</button>
                    <button className="btn btn-outline-secondary btn-sm" onClick={() => selectVisible(false)}>Clear shown</button>
                </div>
                <Table hover size="sm" responsive className="mb-0">
                    <thead>
                        <tr><th></th><th>Feature</th><th>Type</th><th>Sequence</th><th>Position</th><th>Threshold (x)</th></tr>
                    </thead>
                    <tbody>
                        {visible.map(f => {
                            const k = keyOf(f);
                            const sel = selected.get(k);
                            return (
                                <tr key={k} onClick={() => toggle(f)} style={{ cursor: 'pointer' }}>
                                    <td><input type="checkbox" className="form-check-input" checked={!!sel} onChange={() => toggle(f)} onClick={e => e.stopPropagation()} /></td>
                                    <td>{f.name || f.id}{f.product ? <div className="nano-hint">{f.product}</div> : null}</td>
                                    <td>{f.type}</td>
                                    <td><code>{f.seqid}</code></td>
                                    <td className="nano-alert-time">{f.start.toLocaleString()}–{f.end.toLocaleString()} {f.strand}</td>
                                    <td onClick={e => e.stopPropagation()}>
                                        <input type="number" className="form-control form-control-sm" style={{ width: 90 }} min="0" step="0.5"
                                               value={sel ? String(sel.threshold ?? defaultThreshold) : ''} disabled={!sel}
                                               onChange={e => setThreshold(f, e.target.value)} />
                                    </td>
                                </tr>
                            );
                        })}
                        {visible.length === 0 && <tr><td colSpan={6} className="text-center nano-hint">No features match.</td></tr>}
                    </tbody>
                </Table>
                {features.length > 500 && <p className="nano-hint mt-2">Showing the first 500 matches; narrow the filter to find others.</p>}
            </Modal.Body>
            <Modal.Footer>
                <Button variant="outline-secondary" onClick={onHide}>Cancel</Button>
                <Button variant="primary" onClick={() => onSave(Array.from(selected.values()))}>Save {selected.size} feature alert{selected.size === 1 ? '' : 's'}</Button>
            </Modal.Footer>
        </Modal>
    );
};

export default AlertDataSetup;
