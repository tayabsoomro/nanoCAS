import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import "./project-list.css";

const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT ?? '';

interface ProjectMeta {
    id: string;
    minion_dir: string;
    nanocas_dir: string;
}

const ProjectList: React.FC = () => {
    const [projects, setProjects] = useState<ProjectMeta[]>([]);
    const [loading, setLoading] = useState(true);

    const fetchProjects = async () => {
        try {
            const res = await axios.get(`${API_ENDPOINT}/get_all_analyses`);
            if (res.data.status === 200) {
                setProjects(res.data.data);
            }
        } catch (err) {
            console.error("Error fetching projects:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchProjects();
    }, []);

    const handleDelete = async (id: string) => {
        const uid = new FormData();
        uid.append('uid', id);
        try {
            const res = await axios.post(`${API_ENDPOINT}/delete_analyses`, uid, {
                headers: { "Content-Type": "multipart/form-data" },
            });
            if (res.data.status === 200 && res.data.found) {
                fetchProjects();
            }
        } catch (err) {
            console.error("Error deleting project:", err);
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
                                <div className="nano-project-card-id">
                                    {project.id.substring(0, 8)}...
                                </div>
                                <div className="nano-project-card-path">
                                    <span className="nano-path-label">Nanopore Dir</span>
                                    <span className="nano-path-value">{project.minion_dir}</span>
                                </div>
                            </div>
                            <div className="nano-project-card-actions">
                                <Link
                                    to={`/project/${project.id}`}
                                    className="btn btn-primary btn-sm"
                                >
                                    Open
                                </Link>
                                <button
                                    className="btn btn-outline-danger btn-sm"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleDelete(project.id);
                                    }}
                                >
                                    Delete
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default ProjectList;
