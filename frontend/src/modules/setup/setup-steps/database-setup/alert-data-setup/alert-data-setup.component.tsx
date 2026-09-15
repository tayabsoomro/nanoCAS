import React, { FunctionComponent, useEffect, useState } from "react";
import { IDatabaseSetupConstituent } from "../database-setup.interfaces";
import { Modal, Button, Form, Table } from "react-bootstrap";
import { IAlertData, IFastaRecord, IQuery } from "./alert-data-setup.interfaces";
import { api } from "../../../../../api";

const AlertDataSetup: FunctionComponent<IDatabaseSetupConstituent<IAlertData>> = ({ initialConfig, updateConfig }) => {
    const [queries, setQueries] = useState<IQuery[]>(initialConfig.queries);
    const [gffFilePath, setGffFilePath] = useState<string | null>(initialConfig.gff_file || null);
    const [gffError, setGffError] = useState<string | null>(null);
    const [showModal, setShowModal] = useState(false);

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
            setGffFilePath(uploadRes.data.file_path);
        } catch (err: any) {
            setGffError(err?.response?.data?.error || 'GFF upload failed');
        }
    };

    useEffect(() => {
        updateConfig({ queries, gff_file: gffFilePath || undefined });
    }, [queries, gffFilePath, updateConfig]);

    return (
        <div className="container">
            <h4 className="">Alert Sequences</h4>
            <p className="text-muted">
                Upload one or more reference FASTA files and choose which sequences to monitor. Reads are aligned to
                every selected sequence with minimap2; an alert fires when a sequence's depth or breadth of coverage
                reaches its threshold.
            </p>
            {queries.length === 0 ? (
                <div className="text-center text-muted py-3">
                    No alert sequences added yet. Click '+' below to add one.
                </div>
            ) : (
                <Table striped bordered hover responsive className="mt-3">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Reference ID</th>
                            <th>Length</th>
                            <th>Depth alert</th>
                            <th>Breadth alert</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {queries.map((q, i) => (
                            <tr key={`${q.file}-${q.header}-${i}`}>
                                <td>{q.name}</td>
                                <td><code>{q.header}</code>{q.description ? <div className="text-muted small">{q.description}</div> : null}</td>
                                <td>{q.length ? `${q.length.toLocaleString()} bp` : '—'}</td>
                                <td>{q.alert_on_depth ? `≥ ${q.depth_threshold}x` : <span className="text-muted">off</span>}</td>
                                <td>{q.alert_on_breadth ? `≥ ${q.breadth_threshold}%` : <span className="text-muted">off</span>}</td>
                                <td>
                                    <Button variant="danger" size="sm" onClick={() => handleRemoveQuery(i)} aria-label="Remove sequence">
                                        <i className="fa fa-trash-alt" />
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            )}
            <Form.Group className="mb-3">
                <Form.Label>Optional: GFF file with regions of interest</Form.Label>
                <Form.Control type="file" accept=".gff,.gff3,.txt" onChange={handleGffFileChange} />
                <Form.Text className="text-muted">
                    Regions whose seqid matches a selected reference are drawn on the alignment viewer.
                </Form.Text>
                {gffFilePath && <div className="small text-success">Uploaded: {gffFilePath.split('/').pop()}</div>}
                {gffError && <div className="small text-danger">{gffError}</div>}
            </Form.Group>
            <div className="text-center">
                <hr />
                <Button variant="primary" onClick={() => setShowModal(true)} className="mt-3" aria-label="Add alert sequence">
                    <i className="fa fa-plus" />
                </Button>
                <AddAlertModal show={showModal} onHide={() => setShowModal(false)} onAdd={handleAddQueries} />
            </div>
        </div>
    );
};

type AddAlertModalProps = {
    show: boolean;
    onHide: () => void;
    onAdd: (newQueries: IQuery[]) => void;
};

const AddAlertModal: FunctionComponent<AddAlertModalProps> = ({ show, onHide, onAdd }) => {
    const [file, setFile] = useState<File | null>(null);
    const [filePath, setFilePath] = useState<string>("");
    const [records, setRecords] = useState<IFastaRecord[]>([]);
    const [selectedHeaders, setSelectedHeaders] = useState<string[]>([]);
    const [displayName, setDisplayName] = useState("");
    const [depthThreshold, setDepthThreshold] = useState("10");
    const [alertOnDepth, setAlertOnDepth] = useState(true);
    const [breadthThreshold, setBreadthThreshold] = useState("");
    const [alertOnBreadth, setAlertOnBreadth] = useState(false);
    const [errors, setErrors] = useState<{ [key: string]: string }>({});
    const [parsing, setParsing] = useState(false);

    const reset = () => {
        setFile(null);
        setFilePath("");
        setRecords([]);
        setSelectedHeaders([]);
        setDisplayName("");
        setDepthThreshold("10");
        setAlertOnDepth(true);
        setBreadthThreshold("");
        setAlertOnBreadth(false);
        setErrors({});
    };

    const handleFileChange = async (evt: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFile = evt.target.files?.[0];
        if (!selectedFile) return;
        setFile(selectedFile);
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
            // Single-record FASTAs are the common case: preselect it.
            setSelectedHeaders(recs.length === 1 ? [recs[0].id] : []);
        } catch (err: any) {
            console.error(err);
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

    const validateForm = () => {
        const newErrors: { [key: string]: string } = {};
        if (!file || !filePath) newErrors.file = "FASTA file is required.";
        if (selectedHeaders.length === 0) newErrors.header = "Select at least one sequence.";
        if (!alertOnDepth && !alertOnBreadth) newErrors.alert = "Enable at least one alert type.";
        if (alertOnDepth && (depthThreshold === "" || isNaN(parseFloat(depthThreshold)) || parseFloat(depthThreshold) < 0)) {
            newErrors.depth = "Depth threshold must be a number ≥ 0.";
        }
        if (alertOnBreadth) {
            const b = parseFloat(breadthThreshold);
            if (breadthThreshold === "" || isNaN(b) || b < 0 || b > 100) newErrors.breadth = "Breadth threshold must be between 0 and 100 %.";
        }
        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const handleSubmit = () => {
        if (!validateForm()) return;
        const useAll = selectedHeaders.includes("ALL");
        const chosen = useAll ? records : records.filter(r => selectedHeaders.includes(r.id));
        const newQueries: IQuery[] = chosen.map(rec => ({
            name: (chosen.length === 1 && displayName.trim()) ? displayName.trim() : rec.id,
            file: filePath,
            header: rec.id,
            headers: [rec.id],
            description: rec.description,
            length: rec.length,
            depth_threshold: alertOnDepth ? depthThreshold : "",
            alert_on_depth: alertOnDepth,
            breadth_threshold: alertOnBreadth ? breadthThreshold : "",
            alert_on_breadth: alertOnBreadth,
        }));
        onAdd(newQueries);
        reset();
    };

    return (
        <Modal show={show} onHide={() => { reset(); onHide(); }} centered size="lg">
            <Modal.Header closeButton>
                <Modal.Title>Add alert sequence(s)</Modal.Title>
            </Modal.Header>
            <Modal.Body>
                <Form>
                    <Form.Group className="mb-3">
                        <Form.Label>Reference FASTA file</Form.Label>
                        <Form.Control
                            type="file"
                            accept=".fasta,.fna,.fa,.fasta.gz,.fna.gz,.fa.gz"
                            onChange={handleFileChange}
                            isInvalid={!!errors.file}
                        />
                        <Form.Control.Feedback type="invalid">{errors.file}</Form.Control.Feedback>
                        {parsing && <Form.Text className="text-muted">Uploading and reading headers…</Form.Text>}
                    </Form.Group>
                    {records.length > 0 && (
                        <Form.Group className="mb-3">
                            <Form.Label>Sequences to monitor ({records.length} in file)</Form.Label>
                            <Form.Select
                                multiple
                                value={selectedHeaders}
                                onChange={handleHeaderChange}
                                isInvalid={!!errors.header}
                                htmlSize={Math.min(8, records.length + 1)}
                            >
                                {records.length > 1 && <option value="ALL">ALL sequences in this file</option>}
                                {records.map((rec) => (
                                    <option key={rec.id} value={rec.id}>
                                        {rec.id}{rec.description ? ` — ${rec.description}` : ''}{rec.length ? ` (${rec.length.toLocaleString()} bp)` : ''}
                                    </option>
                                ))}
                            </Form.Select>
                            <Form.Text className="text-muted">
                                Use Ctrl/Cmd or Shift to select several. Each selected sequence becomes its own alert target.
                            </Form.Text>
                            <Form.Control.Feedback type="invalid">{errors.header}</Form.Control.Feedback>
                        </Form.Group>
                    )}
                    {selectedHeaders.length === 1 && selectedHeaders[0] !== 'ALL' && (
                        <Form.Group className="mb-3">
                            <Form.Label>Display name (optional)</Form.Label>
                            <Form.Control type="text" value={displayName} placeholder={selectedHeaders[0]}
                                          onChange={e => setDisplayName(e.target.value)} maxLength={80} />
                            <Form.Text className="text-muted">Shown in charts and alert messages instead of the raw reference ID.</Form.Text>
                        </Form.Group>
                    )}
                    <div className="row">
                        <div className="col-md-6">
                            <Form.Group className="mb-3">
                                <Form.Check type="checkbox" label="Alert on depth of coverage" checked={alertOnDepth}
                                            onChange={e => setAlertOnDepth(e.target.checked)} />
                                <Form.Control type="number" value={depthThreshold} onChange={e => setDepthThreshold(e.target.value)}
                                              min="0" step="0.1" disabled={!alertOnDepth} isInvalid={!!errors.depth} placeholder="e.g. 10" />
                                <Form.Text className="text-muted">Mean fold coverage (x) across the whole sequence.</Form.Text>
                                <Form.Control.Feedback type="invalid">{errors.depth}</Form.Control.Feedback>
                            </Form.Group>
                        </div>
                        <div className="col-md-6">
                            <Form.Group className="mb-3">
                                <Form.Check type="checkbox" label="Alert on breadth of coverage" checked={alertOnBreadth}
                                            onChange={e => setAlertOnBreadth(e.target.checked)} />
                                <Form.Control type="number" value={breadthThreshold} onChange={e => setBreadthThreshold(e.target.value)}
                                              min="0" max="100" step="1" disabled={!alertOnBreadth} isInvalid={!!errors.breadth} placeholder="e.g. 90" />
                                <Form.Text className="text-muted">Percentage of positions covered by at least one read.</Form.Text>
                                <Form.Control.Feedback type="invalid">{errors.breadth}</Form.Control.Feedback>
                            </Form.Group>
                        </div>
                    </div>
                    {errors.alert && <div className="text-danger small">{errors.alert}</div>}
                </Form>
            </Modal.Body>
            <Modal.Footer>
                <Button variant="secondary" onClick={() => { reset(); onHide(); }}>Cancel</Button>
                <Button variant="primary" onClick={handleSubmit} disabled={parsing}>Add sequences</Button>
            </Modal.Footer>
        </Modal>
    );
};

export default AlertDataSetup;
