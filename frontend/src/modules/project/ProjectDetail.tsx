import React, { useEffect, useState } from "react";
import { useParams, Link, useHistory } from "react-router-dom";
import axios from "axios";
import { socket } from "../../app.component";
import CoverageTab from "./tabs/CoverageTab";
import RunHealthTab from "./tabs/RunHealthTab";
import AlertsTab from "./tabs/AlertsTab";
import "./project-detail.css";

const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT ?? '';

type TabType = 'coverage' | 'runhealth' | 'alerts';

interface ProjectParams {
    id: string;
    tab?: string;
}

const ProjectDetail: React.FC = () => {
    const { id, tab } = useParams<ProjectParams>();
    const history = useHistory();
    const activeTab: TabType = (tab && ['coverage', 'runhealth', 'alerts'].includes(tab))
        ? (tab as TabType)
        : 'coverage';
    const [projectData, setProjectData] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [listenerRunning, setListenerRunning] = useState(false);
    const [isDatabaseReady, setIsDatabaseReady] = useState(false);

    const switchTab = (t: TabType) => {
        history.push(`/project/${id}/${t}`);
    };

    useEffect(() => {
        const fetchProject = async () => {
            try {
                const res = await axios.get(`${API_ENDPOINT}/get_analysis_info?uid=${id}`);
                if (res.data.status === 200) {
                    setProjectData(res.data.data);
                } else {
                    setError("Project not found");
                }
            } catch (err) {
                setError("Failed to load project");
            } finally {
                setLoading(false);
            }
        };
        fetchProject();

        const checkDb = async () => {
            try {
                const res = await axios.get(`${API_ENDPOINT}/check_database_status?projectId=${id}`);
                setIsDatabaseReady(res.data.is_ready);
            } catch { }
        };
        checkDb();

        socket.emit('check_fastq_file_listener', { projectId: id });

        const handleStatus = (data: any) => {
            if (data.projectId === id) setListenerRunning(data.is_running);
        };
        const handleStarted = (data: any) => {
            if (data.projectId === id) setListenerRunning(true);
        };
        const handleStopped = (data: any) => {
            if (data.projectId === id) setListenerRunning(false);
        };

        socket.on('fastq_file_listener_status', handleStatus);
        socket.on('fastq_file_listener_started', handleStarted);
        socket.on('fastq_file_listener_stopped', handleStopped);

        return () => {
            socket.off('fastq_file_listener_status', handleStatus);
            socket.off('fastq_file_listener_started', handleStarted);
            socket.off('fastq_file_listener_stopped', handleStopped);
        };
    }, [id]);

    const handleStartListener = () => {
        if (projectData) {
            socket.emit('start_fastq_file_listener', {
                minion_location: projectData.minion,
                projectId: projectData.projectId
            });
        }
    };

    const handleStopListener = () => {
        socket.emit('stop_fastq_file_listener', { projectId: id });
    };

    if (loading) {
        return (
            <div className="nano-project-loading">
                <div className="nano-spinner"></div>
                <p>Loading project...</p>
            </div>
        );
    }

    if (error || !projectData) {
        return (
            <div className="nano-project-error">
                <h2>Project Not Found</h2>
                <p>{error || "The requested project could not be loaded."}</p>
                <Link to="/" className="btn btn-primary">Back to Projects</Link>
            </div>
        );
    }

    return (
        <div className="nano-project-detail">
            <div className="nano-project-header">
                <div className="nano-project-header-left">
                    <Link to="/" className="nano-back-link">&larr; Projects</Link>
                    <h2 className="nano-project-title">Project {id?.substring(0, 8)}</h2>
                    <span className="nano-project-path">{projectData.minion}</span>
                </div>
                <div className="nano-project-header-right">
                    <span className={`nano-status-indicator ${listenerRunning ? 'active' : 'inactive'}`}>
                        <span className="nano-status-dot"></span>
                        {listenerRunning ? 'Monitoring' : 'Stopped'}
                    </span>
                    {listenerRunning ? (
                        <button className="btn btn-danger btn-sm" onClick={handleStopListener}>
                            Stop
                        </button>
                    ) : (
                        <button
                            className="btn btn-primary btn-sm"
                            onClick={handleStartListener}
                            disabled={!isDatabaseReady}
                            title={!isDatabaseReady ? 'Database not ready' : ''}
                        >
                            Start Monitoring
                        </button>
                    )}
                </div>
            </div>

            <div className="nano-tab-bar">
                <button
                    className={`nano-tab ${activeTab === 'coverage' ? 'active' : ''}`}
                    onClick={() => switchTab('coverage')}
                >
                    Coverage
                </button>
                <button
                    className={`nano-tab ${activeTab === 'runhealth' ? 'active' : ''}`}
                    onClick={() => switchTab('runhealth')}
                >
                    Run Health
                </button>
                <button
                    className={`nano-tab ${activeTab === 'alerts' ? 'active' : ''}`}
                    onClick={() => switchTab('alerts')}
                >
                    Alerts
                </button>
            </div>

            <div className="nano-tab-content">
                {activeTab === 'coverage' && (
                    <CoverageTab projectId={id!} projectData={projectData} />
                )}
                {activeTab === 'runhealth' && (
                    <RunHealthTab projectId={id!} />
                )}
                {activeTab === 'alerts' && (
                    <AlertsTab projectId={id!} projectData={projectData} />
                )}
            </div>
        </div>
    );
};

export default ProjectDetail;
