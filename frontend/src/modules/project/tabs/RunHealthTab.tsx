import React, { useEffect, useState } from "react";
import axios from "axios";
import { socket } from "../../../app.component";
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    LineElement,
    PointElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js';
import { Bar, Line } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Title, Tooltip, Legend, Filler);

const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT ?? '';

interface RunHealthTabProps {
    projectId: string;
}

interface RunHealthData {
    q_scores: number[];
    read_lengths: number[];
    median_q_over_time: { time: number; median_q: number }[];
    total_reads: number;
    pore_health: {
        total_channels: number;
        active_channels: number;
        channel_states: { sequencing: number; unavailable: number; other: number };
        occupancy_rate: number;
    };
}

const RunHealthTab: React.FC<RunHealthTabProps> = ({ projectId }) => {
    const [data, setData] = useState<RunHealthData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchRunHealth = async () => {
        try {
            const res = await axios.get(`${API_ENDPOINT}/run_health?projectId=${projectId}`);
            setData(res.data);
            setError(null);
        } catch (err: any) {
            if (err.response?.status === 404) {
                setError("No sequencing summary found. Run health data will appear when a sequencing_summary.txt file is available in the nanopore output directory.");
            } else {
                setError("Failed to load run health data.");
            }
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchRunHealth();
        const interval = setInterval(fetchRunHealth, 15000);

        const handleUpdate = (update: any) => {
            if (update.projectId === projectId) {
                fetchRunHealth();
            }
        };
        socket.on('run_health_update', handleUpdate);

        return () => {
            clearInterval(interval);
            socket.off('run_health_update', handleUpdate);
        };
    }, [projectId]);

    if (loading) {
        return (
            <div className="nano-loading-state">
                <div className="nano-spinner"></div>
                <p>Loading run health data...</p>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="nano-empty-state-large">
                <div className="nano-empty-icon">&#9764;</div>
                <h3>Run Health</h3>
                <p>{error || "No data available"}</p>
            </div>
        );
    }

    const buildQScoreHistogram = () => {
        if (!data.q_scores || data.q_scores.length === 0) return null;

        const maxQ = Math.min(Math.ceil(Math.max(...data.q_scores)), 40);
        const bins = Array(maxQ + 1).fill(0);
        data.q_scores.forEach(q => {
            const bin = Math.min(Math.floor(q), maxQ);
            if (bin >= 0) bins[bin]++;
        });

        const labels = bins.map((_, i) => `Q${i}`);
        const colors = bins.map((_, i) => i >= 7 ? 'rgba(0, 176, 189, 0.7)' : 'rgba(231, 76, 60, 0.7)');
        const borderColors = bins.map((_, i) => i >= 7 ? 'rgba(0, 176, 189, 1)' : 'rgba(231, 76, 60, 1)');

        return {
            labels,
            datasets: [{
                label: 'Read Count',
                data: bins,
                backgroundColor: colors,
                borderColor: borderColors,
                borderWidth: 1,
            }]
        };
    };

    const buildReadLengthHistogram = () => {
        if (!data.read_lengths || data.read_lengths.length === 0) return null;

        const sorted = [...data.read_lengths].sort((a, b) => a - b);
        const p99 = sorted[Math.floor(sorted.length * 0.99)];
        const maxLen = Math.min(p99, 50000);
        const numBins = 30;
        const binSize = Math.max(1, Math.ceil(maxLen / numBins));
        const bins = Array(numBins).fill(0);
        const labels: string[] = [];

        for (let i = 0; i < numBins; i++) {
            const start = i * binSize;
            const end = start + binSize;
            labels.push(binSize >= 1000 ? `${(start / 1000).toFixed(1)}k` : `${start}`);
        }

        data.read_lengths.forEach(len => {
            const bin = Math.min(Math.floor(len / binSize), numBins - 1);
            if (bin >= 0) bins[bin]++;
        });

        return {
            labels,
            datasets: [{
                label: 'Read Count',
                data: bins,
                backgroundColor: 'rgba(0, 78, 90, 0.7)',
                borderColor: 'rgba(0, 78, 90, 1)',
                borderWidth: 1,
            }]
        };
    };

    const buildMedianQTrend = () => {
        if (!data.median_q_over_time || data.median_q_over_time.length === 0) return null;

        const labels = data.median_q_over_time.map(p =>
            p.time >= 3600 ? `${(p.time / 3600).toFixed(1)}h` :
            p.time >= 60 ? `${(p.time / 60).toFixed(1)}m` :
            `${p.time.toFixed(0)}s`
        );

        return {
            labels,
            datasets: [{
                label: 'Median Q-Score',
                data: data.median_q_over_time.map(p => p.median_q),
                borderColor: '#00B0BD',
                backgroundColor: 'rgba(0, 176, 189, 0.1)',
                fill: true,
                tension: 0.4,
                pointRadius: 2,
                pointHoverRadius: 5,
            }]
        };
    };

    const qHistData = buildQScoreHistogram();
    const readLenData = buildReadLengthHistogram();
    const medianQData = buildMedianQTrend();
    const poreHealth = data.pore_health;

    const meanQ = data.q_scores.length > 0
        ? (data.q_scores.reduce((a, b) => a + b, 0) / data.q_scores.length).toFixed(1)
        : 'N/A';

    const medianLength = data.read_lengths.length > 0
        ? (() => {
            const sorted = [...data.read_lengths].sort((a, b) => a - b);
            const mid = Math.floor(sorted.length / 2);
            return sorted.length % 2 === 1 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
        })()
        : 'N/A';

    const n50 = data.read_lengths.length > 0
        ? (() => {
            const sorted = [...data.read_lengths].sort((a, b) => b - a);
            const totalBases = sorted.reduce((a, b) => a + b, 0);
            let cumulative = 0;
            for (const len of sorted) {
                cumulative += len;
                if (cumulative >= totalBases / 2) return len;
            }
            return 0;
        })()
        : 'N/A';

    return (
        <div className="nano-run-health">
            <div className="nano-health-summary">
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{data.total_reads.toLocaleString()}</span>
                    <span className="nano-stat-label">Total Reads</span>
                </div>
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{meanQ}</span>
                    <span className="nano-stat-label">Mean Q-Score</span>
                </div>
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{typeof medianLength === 'number' ? medianLength.toLocaleString() : medianLength}</span>
                    <span className="nano-stat-label">Median Read Length</span>
                </div>
                <div className="nano-stat-card">
                    <span className="nano-stat-value">{typeof n50 === 'number' ? n50.toLocaleString() : n50}</span>
                    <span className="nano-stat-label">N50</span>
                </div>
            </div>

            <div className="nano-health-grid">
                <div className="nano-panel">
                    <div className="nano-panel-header">
                        <h3>Q-Score Distribution</h3>
                    </div>
                    <div className="nano-panel-body">
                        {qHistData ? (
                            <Bar
                                data={qHistData}
                                options={{
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    plugins: {
                                        legend: { display: false },
                                        title: { display: false },
                                    },
                                    scales: {
                                        x: { title: { display: true, text: 'Q-Score' } },
                                        y: { title: { display: true, text: 'Read Count' }, beginAtZero: true },
                                    },
                                }}
                                height={300}
                            />
                        ) : (
                            <div className="nano-empty-state"><p>No Q-score data available</p></div>
                        )}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header">
                        <h3>Read Length Distribution</h3>
                    </div>
                    <div className="nano-panel-body">
                        {readLenData ? (
                            <Bar
                                data={readLenData}
                                options={{
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    plugins: {
                                        legend: { display: false },
                                        title: { display: false },
                                    },
                                    scales: {
                                        x: { title: { display: true, text: 'Read Length (bp)' } },
                                        y: { title: { display: true, text: 'Read Count' }, beginAtZero: true },
                                    },
                                }}
                                height={300}
                            />
                        ) : (
                            <div className="nano-empty-state"><p>No read length data available</p></div>
                        )}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header">
                        <h3>Median Q-Score Over Time</h3>
                    </div>
                    <div className="nano-panel-body">
                        {medianQData ? (
                            <Line
                                data={medianQData}
                                options={{
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    plugins: {
                                        legend: { display: false },
                                        title: { display: false },
                                    },
                                    scales: {
                                        x: { title: { display: true, text: 'Time' } },
                                        y: { title: { display: true, text: 'Median Q-Score' }, beginAtZero: false },
                                    },
                                }}
                                height={300}
                            />
                        ) : (
                            <div className="nano-empty-state"><p>No Q-score trend data available</p></div>
                        )}
                    </div>
                </div>

                <div className="nano-panel">
                    <div className="nano-panel-header">
                        <h3>Pore Health</h3>
                    </div>
                    <div className="nano-panel-body nano-pore-health">
                        {poreHealth && poreHealth.total_channels > 0 ? (
                            <>
                                <div className="nano-pore-stats">
                                    <div className="nano-pore-stat">
                                        <div className="nano-pore-stat-value nano-pore-active">
                                            {poreHealth.active_channels}
                                        </div>
                                        <div className="nano-pore-stat-label">Active Pores</div>
                                    </div>
                                    <div className="nano-pore-stat">
                                        <div className="nano-pore-stat-value nano-pore-total">
                                            {poreHealth.total_channels}
                                        </div>
                                        <div className="nano-pore-stat-label">Total Channels</div>
                                    </div>
                                    <div className="nano-pore-stat">
                                        <div className="nano-pore-stat-value">
                                            {poreHealth.occupancy_rate}%
                                        </div>
                                        <div className="nano-pore-stat-label">Occupancy Rate</div>
                                    </div>
                                </div>
                                <div className="nano-pore-bar">
                                    <div
                                        className="nano-pore-bar-fill"
                                        style={{ width: `${poreHealth.occupancy_rate}%` }}
                                    ></div>
                                </div>
                                <div className="nano-pore-legend">
                                    <span className="nano-pore-legend-item">
                                        <span className="nano-dot nano-dot-active"></span>
                                        Sequencing: {poreHealth.channel_states.sequencing}
                                    </span>
                                    <span className="nano-pore-legend-item">
                                        <span className="nano-dot nano-dot-unavailable"></span>
                                        Unavailable: {poreHealth.channel_states.unavailable}
                                    </span>
                                </div>
                            </>
                        ) : (
                            <div className="nano-empty-state"><p>No pore health data available</p></div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default RunHealthTab;
