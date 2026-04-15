import React, { useState } from "react";
import { socket } from "../../../app.component";
import { Modal, Button } from "react-bootstrap";

interface AlertsTabProps {
    projectId: string;
    projectData: any;
}

const AlertsTab: React.FC<AlertsTabProps> = ({ projectId, projectData }) => {
    const [showConfirmModal, setShowConfirmModal] = useState(false);

    const handleRemoveAnalysis = () => {
        setShowConfirmModal(true);
    };

    const confirmRemoveAnalysis = () => {
        socket.emit('remove_analysis', { projectId });
        setShowConfirmModal(false);
        setTimeout(() => {
            window.location.href = '/';
        }, 1000);
    };

    const queries = projectData.queries || [];

    return (
        <div className="nano-alerts-tab">
            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Alert Configuration</h3>
                </div>
                <div className="nano-panel-body">
                    {queries.length > 0 ? (
                        <table className="nano-table">
                            <thead>
                                <tr>
                                    <th>Sequence</th>
                                    <th>Depth Threshold</th>
                                    <th>Depth Alert</th>
                                    <th>Breadth Threshold</th>
                                    <th>Breadth Alert</th>
                                </tr>
                            </thead>
                            <tbody>
                                {queries.map((q: any, idx: number) => (
                                    <tr key={idx}>
                                        <td>{q.name}</td>
                                        <td>{q.depth_threshold || 'N/A'}</td>
                                        <td>
                                            <span className={`nano-badge ${q.alert_on_depth ? 'nano-badge-active' : 'nano-badge-inactive'}`}>
                                                {q.alert_on_depth ? 'Enabled' : 'Disabled'}
                                            </span>
                                        </td>
                                        <td>{q.breadth_threshold || 'N/A'}</td>
                                        <td>
                                            <span className={`nano-badge ${q.alert_on_breadth ? 'nano-badge-active' : 'nano-badge-inactive'}`}>
                                                {q.alert_on_breadth ? 'Enabled' : 'Disabled'}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : (
                        <div className="nano-empty-state">
                            <p>No alert sequences configured.</p>
                        </div>
                    )}
                </div>
            </div>

            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Notification Settings</h3>
                </div>
                <div className="nano-panel-body">
                    <div className="nano-notif-grid">
                        <div className="nano-notif-item">
                            <span className="nano-notif-label">Email Notifications</span>
                            <span className={`nano-badge ${projectData.alertNotifConfig?.enableEmail ? 'nano-badge-active' : 'nano-badge-inactive'}`}>
                                {projectData.alertNotifConfig?.enableEmail ? 'Enabled' : 'Disabled'}
                            </span>
                        </div>
                        <div className="nano-notif-item">
                            <span className="nano-notif-label">SMS Notifications</span>
                            <span className={`nano-badge ${projectData.alertNotifConfig?.enableSMS ? 'nano-badge-active' : 'nano-badge-inactive'}`}>
                                {projectData.alertNotifConfig?.enableSMS ? 'Enabled' : 'Disabled'}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <div className="nano-panel nano-danger-zone">
                <div className="nano-panel-header">
                    <h3>Danger Zone</h3>
                </div>
                <div className="nano-panel-body">
                    <p>Permanently remove this analysis and all associated data.</p>
                    <button className="btn btn-danger" onClick={handleRemoveAnalysis}>
                        Remove Analysis
                    </button>
                </div>
            </div>

            <Modal show={showConfirmModal} onHide={() => setShowConfirmModal(false)}>
                <Modal.Header closeButton>
                    <Modal.Title>Confirm Removal</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>Are you sure you want to remove this analysis? This action cannot be undone.</p>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="outline-secondary" onClick={() => setShowConfirmModal(false)}>
                        Cancel
                    </Button>
                    <Button variant="danger" onClick={confirmRemoveAnalysis}>
                        Remove
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default AlertsTab;
