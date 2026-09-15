import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, Link, useHistory } from "react-router-dom";
import { socket } from "../../app.component";
import { api, AlertRecord } from "../../api";
import CoverageTab from "./tabs/CoverageTab";
import RunHealthTab from "./tabs/RunHealthTab";
import AlertsTab from "./tabs/AlertsTab";
import "./project-detail.css";

type TabType = 'coverage' | 'runhealth' | 'alerts';
const TABS: TabType[] = ['coverage', 'runhealth', 'alerts'];

interface ProjectParams {
    id: string;
    tab?: string;
}

interface FileProgress {
    files_processed: number;
    files_failed: number;
    last_file: string | null;
}

const POLL_MS = 10000;
const TOAST_MS = 8000;

const ProjectDetail: React.FC = () => {
    const { id, tab } = useParams<ProjectParams>();
    const history = useHistory();
    const activeTab: TabType = (tab && TABS.includes(tab as TabType)) ? (tab as TabType) : 'coverage';
    const [projectData, setProjectData] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [listenerRunning, setListenerRunning] = useState(false);
    const [listenerError, setListenerError] = useState<string | null>(null);
    const [isDatabaseReady, setIsDatabaseReady] = useState(false);
    const [fileProgress, setFileProgress] = useState<FileProgress | null>(null);
    // Coverage data lives here (not in CoverageTab) so switching to
    // Run Health and back doesn't unmount the chart's data.
    const [coverageData, setCoverageData] = useState<any[]>([]);
    const [coverageMap, setCoverageMap] = useState(new Map<string, any>());
    const [banner, setBanner] = useState<AlertRecord | null>(null);
    const [toasts, setToasts] = useState<AlertRecord[]>([]);
    const [unseenAlerts, setUnseenAlerts] = useState(0);
    const activeTabRef = useRef(activeTab);
    activeTabRef.current = activeTab;

    const switchTab = (t: TabType) => {
        history.push(`/project/${id}/${t}`);
    };

    useEffect(() => {
        if (activeTab === 'alerts') setUnseenAlerts(0);
    }, [activeTab]);

    const fetchCoverage = useCallback(async () => {
        try {
            const res = await api.get(`/get_coverage?projectId=${id}`);
            const data = Array.isArray(res.data) ? res.data : [];
            setCoverageData(data);
            const map = new Map<string, any>();
            data.forEach((entry: any) => {
                map.set(`${entry.timestamp}-${entry.reference}`, entry);
            });
            setCoverageMap(map);
        } catch { }
    }, [id]);

    const fetchProgress = useCallback(async () => {
        try {
            const res = await api.get(`/get_processing_status?projectId=${id}`);
            if (res.data && typeof res.data.files_processed === 'number') {
                setFileProgress({
                    files_processed: res.data.files_processed,
                    files_failed: res.data.files_failed ?? 0,
                    last_file: res.data.last_file ?? null,
                });
                if (typeof res.data.monitoring === 'boolean') setListenerRunning(res.data.monitoring);
            }
        } catch { }
    }, [id]);

    useEffect(() => {
        let cancelled = false;
        const fetchProject = async () => {
            try {
                const res = await api.get(`/get_analysis_info?uid=${id}`);
                if (!cancelled && res.data.status === 200) {
                    setProjectData(res.data.data);
                } else if (!cancelled) {
                    setError("Project not found");
                }
            } catch (err: any) {
                if (!cancelled) setError(err?.response?.status === 404 ? "Project not found" : "Failed to load project");
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        fetchProject();

        const checkDb = async () => {
            try {
                const res = await api.get(`/check_database_status?projectId=${id}`);
                setIsDatabaseReady(res.data.is_ready);
            } catch { }
        };
        checkDb();
        const dbInterval = setInterval(() => { if (!isDatabaseReady) checkDb(); }, POLL_MS);

        fetchProgress();
        fetchCoverage();
        // Polling keeps the page correct even if a socket message is lost.
        const progressInterval = setInterval(fetchProgress, POLL_MS);
        const coverageInterval = setInterval(fetchCoverage, POLL_MS);

        socket.emit('check_fastq_file_listener', { projectId: id });

        const handleStatus = (data: any) => {
            if (data.projectId === id) setListenerRunning(data.is_running);
        };
        const handleStarted = (data: any) => {
            if (data.projectId === id) { setListenerRunning(true); setListenerError(null); }
        };
        const handleStopped = (data: any) => {
            if (data.projectId === id) setListenerRunning(false);
        };
        const handleListenerError = (data: any) => {
            if (data.projectId === id) setListenerError(data.error || 'Could not start monitoring');
        };
        const handleProgress = (data: any) => {
            if (data.projectId === id && typeof data.files_processed === 'number') {
                setFileProgress({
                    files_processed: data.files_processed,
                    files_failed: data.files_failed ?? 0,
                    last_file: data.last_file ?? null,
                });
            }
        };
        const handleCoverageUpdate = (data: any) => {
            if (data.projectId === id) fetchCoverage();
        };
        const handleAlert = (record: AlertRecord) => {
            if (record.projectId && record.projectId !== id) return;
            if (record.state === 'fired' && record.severity !== 'info') {
                setBanner(record);
            }
            setToasts(prev => [...prev.slice(-3), record]);
            setTimeout(() => setToasts(prev => prev.filter(t => t.id !== record.id)), TOAST_MS);
            if (activeTabRef.current !== 'alerts') setUnseenAlerts(n => n + 1);
        };

        socket.on('fastq_file_listener_status', handleStatus);
        socket.on('fastq_file_listener_started', handleStarted);
        socket.on('fastq_file_listener_stopped', handleStopped);
        socket.on('fastq_file_listener_error', handleListenerError);
        socket.on('file_progress_update', handleProgress);
        socket.on('coverage_update', handleCoverageUpdate);
        socket.on('alert_fired', handleAlert);

        return () => {
            cancelled = true;
            clearInterval(progressInterval);
            clearInterval(coverageInterval);
            clearInterval(dbInterval);
            socket.off('fastq_file_listener_status', handleStatus);
            socket.off('fastq_file_listener_started', handleStarted);
            socket.off('fastq_file_listener_stopped', handleStopped);
            socket.off('fastq_file_listener_error', handleListenerError);
            socket.off('file_progress_update', handleProgress);
            socket.off('coverage_update', handleCoverageUpdate);
            socket.off('alert_fired', handleAlert);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id, fetchCoverage, fetchProgress]);

    const handleStartListener = () => {
        if (projectData) {
            setListenerError(null);
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

    const title = projectData.projectName || `Project ${id?.substring(0, 8)}`;

    return (
        <div className="nano-project-detail">
            <div className="nano-project-header">
                <div className="nano-project-header-left">
                    <Link to="/" className="nano-back-link">&larr; Projects</Link>
                    <h2 className="nano-project-title" title={id}>{title}</h2>
                    <span className="nano-project-path">{projectData.minion}</span>
                    {fileProgress && (fileProgress.files_processed > 0 || fileProgress.files_failed > 0) && (
                        <span className="nano-progress-indicator" title={fileProgress.last_file ?? ''}>
                            <strong>{fileProgress.files_processed.toLocaleString()}</strong>
                            {' '}files processed
                            {fileProgress.files_failed > 0 && (
                                <span className="nano-threshold-hit"> &middot; {fileProgress.files_failed} failed</span>
                            )}
                            {fileProgress.last_file && (
                                <span className="nano-progress-last"> &middot; last: <code>{fileProgress.last_file}</code></span>
                            )}
                        </span>
                    )}
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
                            title={!isDatabaseReady ? 'The reference index is still being built' : ''}
                        >
                            Start Monitoring
                        </button>
                    )}
                </div>
            </div>

            {!isDatabaseReady && (
                <div className="nano-alert-banner info">
                    <span className="nano-alert-message">
                        The reference index for this project has not been built yet (or the build failed). Monitoring
                        cannot start until a <code>.mmi</code> index exists under the project's database directory.
                    </span>
                </div>
            )}
            {listenerError && (
                <div className="nano-alert-banner critical">
                    <span className="nano-alert-message">Could not start monitoring: {listenerError}</span>
                    <button className="nano-alert-close" onClick={() => setListenerError(null)} aria-label="Dismiss">&times;</button>
                </div>
            )}
            {banner && (
                <div className={`nano-alert-banner ${banner.severity}`}>
                    <span className={`nano-badge nano-badge-${banner.severity}`}>{banner.severity}</span>
                    <span className="nano-alert-message">
                        <strong>{banner.timestamp.replace('T', ' ')}</strong> &middot; {banner.message}
                    </span>
                    <button className="btn btn-outline-primary btn-sm" onClick={() => switchTab('alerts')}>View alerts</button>
                    <button className="nano-alert-close" onClick={() => setBanner(null)} aria-label="Dismiss">&times;</button>
                </div>
            )}

            <div className="nano-tab-bar">
                <button className={`nano-tab ${activeTab === 'coverage' ? 'active' : ''}`} onClick={() => switchTab('coverage')}>
                    Coverage
                </button>
                <button className={`nano-tab ${activeTab === 'runhealth' ? 'active' : ''}`} onClick={() => switchTab('runhealth')}>
                    Run Health
                </button>
                <button className={`nano-tab ${activeTab === 'alerts' ? 'active' : ''}`} onClick={() => switchTab('alerts')}>
                    Alerts{unseenAlerts > 0 && <span className="nano-badge-count">{unseenAlerts}</span>}
                </button>
            </div>

            <div className="nano-tab-content">
                {activeTab === 'coverage' && (
                    <CoverageTab
                        projectId={id!}
                        projectData={projectData}
                        coverageData={coverageData}
                        coverageMap={coverageMap}
                    />
                )}
                {activeTab === 'runhealth' && (
                    <RunHealthTab projectId={id!} projectData={projectData} monitoring={listenerRunning} />
                )}
                {activeTab === 'alerts' && (
                    <AlertsTab projectId={id!} projectData={projectData} monitoring={listenerRunning} />
                )}
            </div>

            {toasts.length > 0 && (
                <div className="nano-toast-stack" aria-live="polite">
                    {toasts.map(t => (
                        <div key={t.id} className={`nano-toast ${t.severity}`}>
                            <strong>{t.state === 'recovered' ? 'Recovered' : t.severity.toUpperCase()}</strong>: {t.message}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default ProjectDetail;
