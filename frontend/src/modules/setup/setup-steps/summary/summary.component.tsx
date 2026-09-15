import React, { FunctionComponent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { IDatabseSetupInput, ILocationConfig } from "../database-setup/database-setup.interfaces";
import { socket } from "../../../../app.component";
import { IAlertNotifSetupInput } from '../alert-notif-setup/alert-notif-setup.interfaces';
import { api, RUN_HEALTH_FIELDS } from '../../../../api';

type ISummaryComponentProps = {
    databaseSetupInput: IDatabseSetupInput
    alertNotifSetupInput: IAlertNotifSetupInput
}

type BuildState = 'idle' | 'validating' | 'building' | 'done' | 'failed';

const validateLocations = (locations: ILocationConfig) => {
    const locationData = new FormData();
    locationData.append('minION', locations.nanoporeLocation);
    return api.post('/validate_locations', locationData);
};

const getUniqueUID = (locations: ILocationConfig) => {
    const locationData = new FormData();
    locationData.append('minION', locations.nanoporeLocation);
    return api.post('/get_uid', locationData);
};

const SummaryComponent: FunctionComponent<ISummaryComponentProps> = ({ databaseSetupInput, alertNotifSetupInput }) => {
    const [error, setError] = useState("");
    const [state, setState] = useState<BuildState>('idle');
    const [uid, setUID] = useState("");
    const [progress, setProgress] = useState(0);
    const [statusMessage, setStatusMessage] = useState("");

    const queries = databaseSetupInput.queries;
    const rhc = alertNotifSetupInput.runHealthConfig;

    useEffect(() => {
        const handleStatus = (data: any) => {
            if (uid && data.projectId && data.projectId !== uid) return;
            setProgress(data.percent_done ?? 0);
            setStatusMessage(data.status_message ?? '');
        };
        const handleComplete = (data: any) => {
            if (uid && data.projectId && data.projectId !== uid) return;
            if (data.success) {
                setState('done');
                setProgress(100);
                setStatusMessage('Reference index built. The project is ready to monitor.');
            } else {
                setState('failed');
                setError(data.message || data.error || 'Database build failed');
            }
        };
        socket.on('download_database_status', handleStatus);
        socket.on('download_database_complete', handleComplete);
        return () => {
            socket.off('download_database_status', handleStatus);
            socket.off('download_database_complete', handleComplete);
        };
    }, [uid]);

    const initiateDatabaseCreation = async (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => {
        e.preventDefault();
        setError("");
        setState('validating');
        window.scrollTo({ top: 0, behavior: 'smooth' });
        try {
            const res = await validateLocations(databaseSetupInput.locations);
            if (res.data.code !== 0) {
                setState('failed');
                setError(res.data.message || "The nanopore directory is not valid");
                return;
            }
            const res_uid = await getUniqueUID(databaseSetupInput.locations);
            const newUID: string = res_uid.data.uid;
            setUID(newUID);
            setState('building');
            setStatusMessage('Submitting project…');
            const dbInfo = {
                projectId: newUID,
                projectName: databaseSetupInput.locations.projectName || '',
                minion: databaseSetupInput.locations.nanoporeLocation,
                fileType: 'FASTQ',
                queries,
                device: databaseSetupInput.device.device,
                gff_file: databaseSetupInput.gff_file,
                alertNotifConfig: {
                    enableEmail: alertNotifSetupInput.enableEmail,
                    emailConfig: alertNotifSetupInput.emailConfig,
                    enableSMS: alertNotifSetupInput.enableSMS,
                    smsRecipient: alertNotifSetupInput.smsRecipient,
                },
                runHealthConfig: rhc,
            };
            socket.emit('download_database', dbInfo);
        } catch (err: any) {
            setState('failed');
            setError(err?.response?.data?.error || "An error occurred during setup");
            console.error(err);
        }
    };

    const busy = state === 'validating' || state === 'building';

    return (
        <div className="container text-center">
            <div className="vspacer-20" />
            {(state === 'building' || state === 'done') && (
                <div className={`alert ${state === 'done' ? 'alert-success' : 'alert-info'} text-left`}>
                    <div className="d-flex justify-content-between align-items-center">
                        <strong>{state === 'done' ? 'Project created' : 'Building reference index…'}</strong>
                        <span>{progress}%</span>
                    </div>
                    <div className="progress my-2" style={{ height: 8 }}>
                        <div className={`progress-bar ${state === 'done' ? 'bg-success' : 'progress-bar-striped progress-bar-animated'}`}
                             role="progressbar" style={{ width: `${progress}%` }} aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} />
                    </div>
                    <div className="small">{statusMessage}</div>
                    {uid && (
                        <div className="mt-2">
                            <Link className="btn btn-primary btn-sm" to={`/project/${uid}`}>
                                {state === 'done' ? 'Open project' : 'Open project (index still building)'}
                            </Link>
                        </div>
                    )}
                </div>
            )}
            {error && <div className="alert alert-danger text-left">ERROR: {error}</div>}
            <h4>Setup Summary</h4>
            <p>Review your configuration below, then create the project.</p>
            <div className="vspacer-20" />
            <table className="table table-bordered text-start">
                <thead className="thead-light">
                <tr><th colSpan={3}>Alert sequences</th></tr>
                </thead>
                <tbody>
                {queries.length > 0 ? (
                    queries.map((query, idx) => (
                        <tr key={idx}>
                            <th>{idx === 0 ? "Sequences" : ""}</th>
                            <td>{query.name} <code className="text-muted">{query.header}</code></td>
                            <td>
                                {query.alert_on_depth ? `depth ≥ ${query.depth_threshold}x` : ''}
                                {query.alert_on_depth && query.alert_on_breadth ? ', ' : ''}
                                {query.alert_on_breadth ? `breadth ≥ ${query.breadth_threshold}%` : ''}
                            </td>
                        </tr>
                    ))
                ) : (
                    <tr><td colSpan={3}>No alert sequences provided.</td></tr>
                )}
                {databaseSetupInput.gff_file && (
                    <tr>
                        <th>GFF File</th>
                        <td colSpan={2}>{databaseSetupInput.gff_file.split('/').pop()}</td>
                    </tr>
                )}
                </tbody>
                <thead className="thead-light">
                <tr><th colSpan={3}>Configuration</th></tr>
                </thead>
                <tbody>
                <tr><th>Project name</th><td colSpan={2}>{databaseSetupInput.locations.projectName || <span className="text-muted">(auto)</span>}</td></tr>
                <tr><th>Nanopore directory</th><td colSpan={2}>{databaseSetupInput.locations.nanoporeLocation}</td></tr>
                <tr><th>MinKNOW device</th><td colSpan={2}>{databaseSetupInput.device.device || "Not provided"}</td></tr>
                </tbody>
                <thead className="thead-light">
                <tr><th colSpan={3}>Notifications</th></tr>
                </thead>
                <tbody>
                <tr><th>Email</th><td colSpan={2}>{alertNotifSetupInput.enableEmail ? `Enabled → ${alertNotifSetupInput.emailConfig?.recipient} via ${alertNotifSetupInput.emailConfig?.smtpServer}:${alertNotifSetupInput.emailConfig?.smtpPort}` : 'Disabled'}</td></tr>
                <tr><th>SMS</th><td colSpan={2}>{alertNotifSetupInput.enableSMS ? `Enabled → ${alertNotifSetupInput.smsRecipient}` : 'Disabled'}</td></tr>
                </tbody>
                <thead className="thead-light">
                <tr><th colSpan={3}>Run-health alerts</th></tr>
                </thead>
                <tbody>
                {rhc && rhc.enabled !== false ? RUN_HEALTH_FIELDS.map(f => (
                    <tr key={f.key}><th>{f.label}</th><td colSpan={2}>{String(rhc[f.key] ?? '')}{f.unit ? ` ${f.unit}` : ''}</td></tr>
                )) : <tr><td colSpan={3}>Disabled</td></tr>}
                </tbody>
            </table>
            <div className="vspacer-20" />
            <button className="btn btn-primary" disabled={busy || state === 'done'} onClick={(e) => initiateDatabaseCreation(e)}>
                {busy ? 'Working…' : state === 'done' ? 'Project created' : 'Create project'}
            </button>
        </div>
    );
}

export default SummaryComponent;
