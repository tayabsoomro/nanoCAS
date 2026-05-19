import React, { useEffect, useState, useMemo } from "react";
import axios from "axios";
import { socket } from "../../../app.component";
import { Chart } from "react-google-charts";
import { Dropdown } from "react-bootstrap";
import AlignmentViewer from "../../analysis/analysis-data/alignment-viewer.component";

const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT ?? '';
const POLLING_INTERVAL_MS = 10000;

interface CoverageTabProps {
    projectId: string;
    projectData: any;
}

interface AlignmentData {
    ref_length: number;
    alignments: { start: number; end: number; strand: string }[];
    regions: { start: number; end: number; id: string; read_count: number }[];
}

type TimeUnit = 'seconds' | 'minutes' | 'hours' | 'days';

const CoverageTab: React.FC<CoverageTabProps> = ({ projectId, projectData }) => {
    const [coverageData, setCoverageData] = useState<any[]>([]);
    const [coverageMap, setCoverageMap] = useState(new Map<string, any>());
    const [metric, setMetric] = useState<'depth' | 'breadth'>('depth');
    const [timeUnit, setTimeUnit] = useState<TimeUnit>('seconds');
    const [selectedReference, setSelectedReference] = useState<string | null>(null);
    const [alignmentData, setAlignmentData] = useState<AlignmentData | null>(null);

    const threshold = projectData.queries?.[0]?.depth_threshold
        ? parseFloat(projectData.queries[0].depth_threshold)
        : 100;

    const unitLabels: Record<TimeUnit, string> = {
        seconds: 's', minutes: 'min', hours: 'h', days: 'd'
    };

    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await axios.get(`${API_ENDPOINT}/get_coverage?projectId=${projectId}`);
                const data = res.data;
                setCoverageData(data);
                const map = new Map<string, any>();
                data.forEach((entry: any) => {
                    map.set(`${entry.timestamp}-${entry.reference}`, entry);
                });
                setCoverageMap(map);
            } catch { }
        };

        fetchData();
        const interval = setInterval(fetchData, POLLING_INTERVAL_MS);

        const handleCoverageUpdate = (data: any) => {
            if (data.projectId === projectId) {
                fetchData();
            }
        };
        socket.on('coverage_update', handleCoverageUpdate);

        return () => {
            clearInterval(interval);
            socket.off('coverage_update', handleCoverageUpdate);
        };
    }, [projectId]);

    useEffect(() => {
        const fetchAlignments = async () => {
            if (selectedReference) {
                try {
                    const res = await axios.get(
                        `${API_ENDPOINT}/get_alignments?projectId=${projectId}&reference=${selectedReference}`
                    );
                    setAlignmentData(res.data);
                } catch {
                    setAlignmentData(null);
                }
            }
        };
        fetchAlignments();
    }, [selectedReference, projectId]);

    const formatCoverageData = () => {
        const refs = [...new Set(coverageData.map(d => d.reference))].filter(ref => ref !== 'Unmapped');
        const times = [...new Set(coverageData.map(d => d.timestamp))].sort();
        if (times.length === 0) return [];

        const startTime = new Date(times[0]).getTime();
        const factors: Record<TimeUnit, number> = { seconds: 1, minutes: 60, hours: 3600, days: 86400 };
        const factor = factors[timeUnit];

        const header: any[] = [{ type: 'number', label: `Elapsed Time (${unitLabels[timeUnit]})`, role: '' }];
        refs.forEach(ref => {
            header.push({ type: 'number', label: ref, role: '' });
            header.push({ type: 'string', label: 'for', role: 'tooltip' });
        });
        if (metric === "depth" && !isNaN(threshold)) {
            header.push({ type: 'number', label: 'Threshold', role: '' });
            header.push({ type: 'string', label: 'for', role: 'tooltip' });
        }

        const rows = times.map(time => {
            const elapsed = (new Date(time).getTime() - startTime) / 1000 / factor;
            const row: (number | string)[] = [elapsed];
            refs.forEach(ref => {
                const entry = coverageMap.get(`${time}-${ref}`);
                const y = entry ? (metric === "depth" ? entry.depth : entry.breadth) : 0;
                const unit = metric === "depth" ? 'X' : '%';
                row.push(y);
                row.push(`${ref}: ${y.toFixed(2)}${unit}`);
            });
            if (metric === "depth" && !isNaN(threshold)) {
                row.push(threshold);
                row.push(`Threshold: ${threshold}`);
            }
            return row;
        });

        return [header, ...rows];
    };

    const formattedData = useMemo(() => formatCoverageData(), [coverageMap, metric, timeUnit]);

    const refs = [...new Set(coverageData.map(d => d.reference))];

    const chartOptions = {
        title: `${metric === "depth" ? "Depth of Coverage" : "Breadth of Coverage"} Over Time`,
        hAxis: { title: `Elapsed Time (${unitLabels[timeUnit]})` },
        vAxis: { title: metric === "depth" ? 'Depth (X)' : 'Breadth (%)', minValue: 0 },
        legend: { position: 'bottom' },
        colors: ['#00B0BD', '#004E5A', '#FF6A45', '#27AE60'],
        chartArea: { width: '80%', height: '70%' },
        animation: { startup: true, duration: 1000, easing: 'out' },
        series: metric === "depth" && !isNaN(threshold) ? {
            [refs.filter(r => r !== 'Unmapped').length]: { lineDashStyle: [4, 4], color: 'red', lineWidth: 2, pointSize: 0 }
        } : {}
    };

    return (
        <div className="nano-coverage-tab">
            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Sequence Coverage Visualization</h3>
                    <Dropdown>
                        <Dropdown.Toggle variant="secondary" size="sm">
                            {selectedReference || "Select Reference"}
                        </Dropdown.Toggle>
                        <Dropdown.Menu>
                            {projectData.queries?.map((query: any, idx: number) => (
                                <Dropdown.Item key={idx} onClick={() => setSelectedReference(query.name)}>
                                    {query.name}
                                </Dropdown.Item>
                            ))}
                        </Dropdown.Menu>
                    </Dropdown>
                </div>
                <div className="nano-panel-body">
                    {selectedReference && alignmentData ? (
                        <AlignmentViewer
                            refId={selectedReference}
                            refLength={alignmentData.ref_length}
                            alignments={alignmentData.alignments}
                            regions={alignmentData.regions}
                        />
                    ) : (
                        <div className="nano-empty-state">
                            <p>Select a reference to view sequence coverage.</p>
                        </div>
                    )}
                </div>
            </div>

            <div className="nano-panel">
                <div className="nano-panel-header">
                    <h3>Coverage Over Time</h3>
                    <div className="nano-panel-controls">
                        <Dropdown>
                            <Dropdown.Toggle variant="secondary" size="sm">
                                {metric.charAt(0).toUpperCase() + metric.slice(1)}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                <Dropdown.Item onClick={() => setMetric('depth')}>Depth</Dropdown.Item>
                                <Dropdown.Item onClick={() => setMetric('breadth')}>Breadth</Dropdown.Item>
                            </Dropdown.Menu>
                        </Dropdown>
                        <Dropdown>
                            <Dropdown.Toggle variant="secondary" size="sm">
                                {timeUnit.charAt(0).toUpperCase() + timeUnit.slice(1)}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                <Dropdown.Item onClick={() => setTimeUnit('seconds')}>Seconds</Dropdown.Item>
                                <Dropdown.Item onClick={() => setTimeUnit('minutes')}>Minutes</Dropdown.Item>
                                <Dropdown.Item onClick={() => setTimeUnit('hours')}>Hours</Dropdown.Item>
                                <Dropdown.Item onClick={() => setTimeUnit('days')}>Days</Dropdown.Item>
                            </Dropdown.Menu>
                        </Dropdown>
                    </div>
                </div>
                <div className="nano-panel-body">
                    {coverageData.length > 0 ? (
                        <Chart
                            key={metric}
                            chartType="LineChart"
                            data={formattedData}
                            options={chartOptions}
                            width="100%"
                            height="400px"
                        />
                    ) : (
                        <div className="nano-empty-state">
                            <p>No coverage data available yet.</p>
                            <p className="nano-hint">Start monitoring to begin collecting coverage data.</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default CoverageTab;
