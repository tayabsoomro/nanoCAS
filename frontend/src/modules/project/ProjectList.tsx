import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
    exists: boolean;
}

const ProjectList: React.FC = () => {
    const [projects, setProjects] = useState<ProjectMeta[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [pendingDelete, setPendingDelete] = useState<ProjectMeta | null>(null);

    const fetchProjects = useCallback(async () => {
        try {
            const res = await api.get('/get_all_analyses');
            if (res.data.status === 200) {
                setProjects(res.data.data);
                setError(null);
            }
        } catch (err) {
            console.error("Error fetching projects:", err);
            setError("Could not reach the nanoCAS backend. Is the server running?");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchProjects();
    }, [fetchProjects]);

    const confirmDelete = async () => {
        if (!pendingDelete) return;
        const form = new FormData();
        form.append('uid', pendingDelete.id);
        try {
            await api.post('/delete_analyses', form);
        } catch (err) {
            console.error("Error deleting project:", err);
        } finally {
            setPendingDelete(null);
            fetchProjects();
        }
    };

    if (loading) {
        return (
            <div className="nano-projects-loading">
                <div className="nano-spinner"></div>
                <p>Loading projects...</p>
            </div>
        );
    }

    return (
        <div className="nano-projects-page">
            <div className="nano-projects-header">
                <div>
                    <h1 className="nano-projects-title">Projects</h1>
                    <p className="nano-projects-subtitle">Manage your nanopore sequencing analyses</p>
                </div>
                <Link to="/setup" className="btn btn-primary">
                    + New Project
                </Link>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {projects.length === 0 ? (
                <div className="nano-projects-empty">
                    <div className="nano-empty-icon-large">&#128300;</div>
                    <h3>No projects yet</h3>
                    <p>Create a new project to start monitoring your nanopore sequencing runs.</p>
                    <Link to="/setup" className="btn btn-accent">
                        Create Your First Project
                    </Link>
                </div>
            ) : (
                <div className="nano-projects-grid">
                    {projects.map((project) => (
                        <div key={project.id} className="nano-project-card">
                            <div className="nano-project-card-body">
                                <div className="nano-project-card-id" title={project.id}>
                                    {project.name || `Project ${project.id.substring(0, 8)}`}
                                    {project.monitoring && (
                                        <span className="nano-badge nano-badge-active" style={{ marginLeft: 8 }}>Monitoring</span>
                                    )}
                                </div>
                                <div className="nano-project-card-path">
                                    <span className="nano-path-label">Nanopore Dir</span>
                                    <span className="nano-path-value">{project.minion_dir}</span>
                                </div>
                                <div className="nano-project-card-path">
                                    <span className="nano-path-label">Details</span>
                                    <span className="nano-path-value">
                                        {project.file_type} &middot; {project.query_count} target sequence{project.query_count === 1 ? '' : 's'}
                                        {project.created_at ? ` · created ${project.created_at.replace('T', ' ')}` : ''}
                                    </span>
                                </div>
                            </div>
                            <div className="nano-project-card-actions">
                                <Link to={`/project/${project.id}`} className="btn btn-primary btn-sm">
                                    Open
                                </Link>
                                <button
                                    className="btn btn-outline-danger btn-sm"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setPendingDelete(project);
                                    }}
                                >
                                    Delete
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <Modal show={pendingDelete !== null} onHide={() => setPendingDelete(null)}>
                <Modal.Header closeButton>
                    <Modal.Title>Delete project</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>
                        Delete <strong>{pendingDelete?.name || pendingDelete?.id}</strong>? Monitoring will be stopped and all
                        coverage data, alignments and alert history for this project will be removed. The sequencer output
                        directory itself is not touched.
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
