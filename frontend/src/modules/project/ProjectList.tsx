import React, { useCallback, useEffect, useState } from "react";
import { Link, useHistory } from "react-router-dom";
import { Button, Modal } from "react-bootstrap";
import { api } from "../../api";
import "./project-list.css";

interface ProjectMeta {
    id: string;
    name: string;
    minion_dir: string;
    nanocas_dir: string;
    file_type: string;
    created_at: string | null;
    query_count: number;
    monitoring: boolean;
    simulating: boolean;
    demo: boolean;
    demo_scenario: string | null;
    exists: boolean;
}

interface Scenario {
    id: string;
    label: string;
    summary: string;
    expect: string[];
}

const ProjectList: React.FC = () => {
    const history = useHistory();
    const [projects, setProjects] = useState<ProjectMeta[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [pendingDelete, setPendingDelete] = useState<ProjectMeta | null>(null);
    const [showDemo, setShowDemo] = useState(false);
    const [scenarios, setScenarios] = useState<Scenario[]>([]);
    const [scenario, setScenario] = useState('contamination');
    const [seedHistory, setSeedHistory] = useState(true);
    const [creating, setCreating] = useState(false);
    const [demoError, setDemoError] = useState<string | null>(null);

    const fetchProjects = useCallback(async () => {
        try {
            const res = await api.get('/get_all_analyses');
            if (res.data.status === 200) {
                setProjects(res.data.data);
                setError(null);
            }
        } catch (err) {
            setError("The nanoCAS backend is not reachable. Start it with `python server/nanocas.py`.");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchProjects();
        api.get('/simulation/scenarios').then(res => setScenarios(res.data.scenarios || [])).catch(() => { });
    }, [fetchProjects]);

    const confirmDelete = async () => {
        if (!pendingDelete) return;
        const form = new FormData();
        form.append('uid', pendingDelete.id);
        try {
            await api.post('/delete_analyses', form);
        } finally {
            setPendingDelete(null);
            fetchProjects();
        }
    };

    const createDemo = async () => {
        setCreating(true);
        setDemoError(null);
        try {
            const res = await api.post('/demo/create', { scenario, seed_history: seedHistory });
            setShowDemo(false);
            history.push(`/project/${res.data.projectId}`);
        } catch (err: any) {
            setDemoError(err?.response?.data?.error || 'Could not create the demo project.');
        } finally {
            setCreating(false);
        }
    };

    const selected = scenarios.find(s => s.id === scenario);

    return (
        <div className="nano-projects-page">
            <section className="nano-hero">
                <h1>Know the moment your nanopore run goes wrong.</h1>
                <p>
                    nanoCAS watches a live Oxford Nanopore run, aligns each new batch of reads against the sequences
                    you care about, and alerts you when foreign DNA appears or the run itself fails.
                </p>
                <ol className="nano-steps">
                    <li><span>1</span><strong>Watch</strong><em>the run's <code>fastq_pass</code> folder as MinKNOW writes it</em></li>
                    <li><span>2</span><strong>Align</strong><em>every batch of reads to your reference sequences</em></li>
                    <li><span>3</span><strong>Alert</strong><em>on contamination, dying pores, low quality or a stalled run</em></li>
                </ol>
                <div className="nano-hero-actions">
                    <Link to="/setup" className="btn btn-primary">New project</Link>
                    <button className="btn btn-outline-primary" onClick={() => setShowDemo(true)}>
                        Try it without a sequencer
                    </button>
                </div>
            </section>

            <div className="nano-projects-header">
                <h2 className="nano-projects-title">Projects</h2>
                {projects.length > 0 && <span className="nano-hint">{projects.length} project{projects.length === 1 ? '' : 's'}</span>}
            </div>

            {error && <div className="nano-alert-banner critical"><span className="nano-alert-message">{error}</span></div>}

            {loading ? (
                <div className="nano-projects-loading"><div className="nano-spinner"></div></div>
            ) : projects.length === 0 ? (
                <div className="nano-projects-empty">
                    <p>No projects yet. Create one for a real run, or start with a demo.</p>
                </div>
            ) : (
                <div className="nano-projects-grid">
                    {projects.map((project) => (
                        <div key={project.id} className="nano-project-card">
                            <div className="nano-project-card-body">
                                <div className="nano-project-card-id" title={project.id}>
                                    {project.name || `Project ${project.id.substring(0, 8)}`}
                                </div>
                                <div className="nano-project-card-tags">
                                    {project.demo && <span className="nano-badge nano-badge-info">demo</span>}
                                    {project.simulating && <span className="nano-badge nano-badge-warning">simulating</span>}
                                    {project.monitoring && <span className="nano-badge nano-badge-active">monitoring</span>}
                                </div>
                                <div className="nano-project-card-path">
                                    <span className="nano-path-label">Watching</span>
                                    <span className="nano-path-value">{project.minion_dir}</span>
                                </div>
                                <div className="nano-project-card-path">
                                    <span className="nano-path-label">Targets</span>
                                    <span className="nano-path-value">
                                        {project.query_count} sequence{project.query_count === 1 ? '' : 's'}
                                        {project.created_at ? ` · ${project.created_at.replace('T', ' ').slice(0, 16)}` : ''}
                                    </span>
                                </div>
                            </div>
                            <div className="nano-project-card-actions">
                                <Link to={`/project/${project.id}`} className="btn btn-primary btn-sm">Open</Link>
                                <button className="btn btn-outline-secondary btn-sm"
                                        onClick={(e) => { e.stopPropagation(); setPendingDelete(project); }}>
                                    Delete
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <Modal show={showDemo} onHide={() => setShowDemo(false)} centered>
                <Modal.Header closeButton>
                    <Modal.Title>Create a demo project</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p className="nano-hint">
                        A demo project uses three synthetic reference sequences (sample DNA, a contaminant and a pathogen)
                        and a simulated sequencer that writes reads exactly like MinKNOW does. No hardware needed.
                    </p>
                    <label className="form-label">Scenario</label>
                    <select className="form-select" value={scenario} onChange={e => setScenario(e.target.value)}>
                        {scenarios.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
                    </select>
                    {selected && <p className="nano-hint mt-2">{selected.summary}</p>}
                    <div className="form-check mt-3">
                        <input className="form-check-input" type="checkbox" id="seed-history" checked={seedHistory}
                               onChange={e => setSeedHistory(e.target.checked)} />
                        <label className="form-check-label" htmlFor="seed-history">
                            Include a completed 3-hour run (coverage history and alerts ready to inspect)
                        </label>
                    </div>
                    <p className="nano-hint mt-2">
                        Either way you can start a live simulation from the project page.
                    </p>
                    {demoError && <div className="nano-alert-banner critical mt-2"><span className="nano-alert-message">{demoError}</span></div>}
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="outline-secondary" onClick={() => setShowDemo(false)} disabled={creating}>Cancel</Button>
                    <Button variant="primary" onClick={createDemo} disabled={creating}>
                        {creating ? (seedHistory ? 'Building and replaying run…' : 'Building…') : 'Create demo'}
                    </Button>
                </Modal.Footer>
            </Modal>

            <Modal show={pendingDelete !== null} onHide={() => setPendingDelete(null)}>
                <Modal.Header closeButton>
                    <Modal.Title>Delete project</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>
                        Delete <strong>{pendingDelete?.name || pendingDelete?.id}</strong>? Monitoring stops and all coverage
                        data, alignments and alert history are removed. The sequencer output directory is not touched.
                    </p>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="outline-secondary" onClick={() => setPendingDelete(null)}>Cancel</Button>
                    <Button variant="danger" onClick={confirmDelete}>Delete</Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default ProjectList;
