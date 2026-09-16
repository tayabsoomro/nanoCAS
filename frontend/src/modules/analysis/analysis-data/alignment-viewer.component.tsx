import React, { useMemo, useRef, useLayoutEffect, useState } from 'react';
import { Form, OverlayTrigger, Tooltip } from 'react-bootstrap';

interface Alignment {
    start: number;
    end: number;
    strand: string;
}

interface Region {
    start: number;
    end: number;
    id: string;
    read_count: number;
}

interface AlignmentViewerProps {
    refId: string;
    refLength: number;
    alignments: Alignment[];
    regions: Region[];
}

const DEPTH_BINS = 400;
const ROW_STEP = 25;

/** Depth track (per-bin mean depth) plus a bounded pile-up of reads.
 *
 *  A long run can have tens of thousands of reads on one reference; drawing
 *  every one produced pages thousands of pixels tall. The depth track shows
 *  the whole picture at a glance and the read rows are capped, with a
 *  control to reveal more. */
const AlignmentViewer: React.FC<AlignmentViewerProps> = ({ refId, refLength, alignments, regions }) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const [svgWidth, setSvgWidth] = useState(800);
    const [showRegions, setShowRegions] = useState(true);
    const [maxRows, setMaxRows] = useState(ROW_STEP);

    useLayoutEffect(() => {
        const update = () => { if (containerRef.current) setSvgWidth(containerRef.current.offsetWidth); };
        update();
        window.addEventListener('resize', update);
        return () => window.removeEventListener('resize', update);
    }, []);

    const leftMargin = 56;
    const rightMargin = 16;
    const trackTop = 28;
    const trackHeight = 90;
    const barHeight = 18;
    const readHeight = 9;
    const rowGap = 3;

    const plotWidth = Math.max(100, svgWidth - leftMargin - rightMargin);
    const scale = plotWidth / Math.max(1, refLength);

    // Depth per bin from the alignment intervals (difference array).
    const depth = useMemo(() => {
        const bins = new Float64Array(DEPTH_BINS);
        const binSize = refLength / DEPTH_BINS;
        alignments.forEach(a => {
            const s = Math.max(0, Math.min(DEPTH_BINS - 1, Math.floor(a.start / binSize)));
            const e = Math.max(0, Math.min(DEPTH_BINS - 1, Math.floor((a.end - 1) / binSize)));
            for (let b = s; b <= e; b++) {
                const lo = Math.max(a.start, b * binSize);
                const hi = Math.min(a.end, (b + 1) * binSize);
                bins[b] += Math.max(0, hi - lo) / binSize;
            }
        });
        return bins;
    }, [alignments, refLength]);
    const maxDepth = Math.max(1, ...Array.from(depth));

    // Greedy pile-up, sorted by start.
    const rows = useMemo(() => {
        const sorted = [...alignments].sort((a, b) => a.start - b.start);
        const out: Alignment[][] = [];
        const rowEnds: number[] = [];
        sorted.forEach(a => {
            let placed = false;
            for (let r = 0; r < out.length; r++) {
                if (rowEnds[r] < a.start) { out[r].push(a); rowEnds[r] = a.end; placed = true; break; }
            }
            if (!placed) { out.push([a]); rowEnds.push(a.end); }
        });
        return out;
    }, [alignments]);

    const visibleRows = rows.slice(0, maxRows);
    const readsTop = trackTop + trackHeight + 16 + barHeight + 10;
    const readsHeight = visibleRows.length > 0 ? visibleRows.length * (readHeight + rowGap) : 24;
    const axisY = readsTop + readsHeight + 8;
    const svgHeight = axisY + 28;

    const fmt = (bp: number) => bp >= 1_000_000 ? `${(bp / 1_000_000).toFixed(2).replace(/\.00$/, '')} Mb`
        : bp >= 1_000 ? `${(bp / 1_000).toFixed(1).replace(/\.0$/, '')} kb` : `${bp} bp`;
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => Math.round(refLength * f));

    const depthPath = useMemo(() => {
        const binW = plotWidth / DEPTH_BINS;
        let d = `M ${leftMargin} ${trackTop + trackHeight}`;
        for (let b = 0; b < DEPTH_BINS; b++) {
            const y = trackTop + trackHeight - (depth[b] / maxDepth) * trackHeight;
            d += ` L ${leftMargin + b * binW} ${y} L ${leftMargin + (b + 1) * binW} ${y}`;
        }
        d += ` L ${leftMargin + plotWidth} ${trackTop + trackHeight} Z`;
        return d;
    }, [depth, maxDepth, plotWidth, leftMargin]);

    return (
        <div ref={containerRef} style={{ width: '100%' }}>
            <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
                <span className="nano-hint">
                    {alignments.length.toLocaleString()} primary alignments on {refId} ({fmt(refLength)}), {rows.length.toLocaleString()} pile-up rows
                </span>
                {regions.length > 0 && (
                    <Form.Check type="switch" id="show-regions-switch" label="GFF regions" checked={showRegions}
                                onChange={() => setShowRegions(!showRegions)} className="nano-hint" />
                )}
            </div>
            <svg width="100%" height={svgHeight} viewBox={`0 0 ${svgWidth} ${svgHeight}`} style={{ display: 'block' }}>
                {/* Depth track */}
                <text x={leftMargin} y={trackTop - 10} fontSize={11} fill="#5b6470">Depth (max {maxDepth.toFixed(1)}x)</text>
                <line x1={leftMargin} y1={trackTop + trackHeight} x2={leftMargin + plotWidth} y2={trackTop + trackHeight} stroke="#e3e6ea" />
                <line x1={leftMargin} y1={trackTop} x2={leftMargin + plotWidth} y2={trackTop} stroke="#e3e6ea" strokeDasharray="3 3" />
                <text x={leftMargin - 6} y={trackTop + 4} fontSize={10} textAnchor="end" fill="#8a919b">{maxDepth.toFixed(0)}x</text>
                <text x={leftMargin - 6} y={trackTop + trackHeight + 4} fontSize={10} textAnchor="end" fill="#8a919b">0</text>
                <path d={depthPath} fill="rgba(15, 76, 92, 0.35)" stroke="#0f4c5c" strokeWidth={1} />

                {/* Reference bar + regions */}
                <rect x={leftMargin} y={trackTop + trackHeight + 16} width={plotWidth} height={barHeight} fill="#e3e6ea" rx={2} />
                <text x={leftMargin + plotWidth / 2} y={trackTop + trackHeight + 16 + barHeight / 2 + 4} fontSize={10}
                      textAnchor="middle" fill="#1f2933">{refId}</text>
                {showRegions && regions.map((region, index) => {
                    const x = leftMargin + (region.start - 1) * scale;
                    const width = Math.max(1, (region.end - region.start + 1) * scale);
                    return (
                        <OverlayTrigger key={index} placement="top"
                                        overlay={<Tooltip id={`region-${index}`}>{region.id} [{fmt(region.start)} – {fmt(region.end)}] · {region.read_count} reads</Tooltip>}>
                            <rect x={x} y={trackTop + trackHeight + 16} width={width} height={barHeight}
                                  fill="rgba(183, 121, 31, 0.45)" stroke="#b7791f" strokeWidth={1} style={{ cursor: 'pointer' }}
                                  onClick={() => navigator.clipboard?.writeText(`${refId}:${region.start}-${region.end}`)} />
                        </OverlayTrigger>
                    );
                })}

                {/* Reads */}
                {visibleRows.length === 0 ? (
                    <text x={leftMargin + plotWidth / 2} y={readsTop + 14} textAnchor="middle" fontSize={12} fill="#8a919b">No aligned reads</text>
                ) : visibleRows.map((row, r) => row.map((a, i) => {
                    const x = leftMargin + a.start * scale;
                    const width = Math.max(1, (a.end - a.start) * scale);
                    const y = readsTop + r * (readHeight + rowGap);
                    return (
                        <rect key={`${r}-${i}`} x={x} y={y} width={width} height={readHeight} rx={1}
                              fill={a.strand === '+' ? '#0f4c5c' : '#7fa7b3'}>
                            <title>{a.strand} strand · {a.start.toLocaleString()}–{a.end.toLocaleString()}</title>
                        </rect>
                    );
                }))}
                {visibleRows.length > 0 && (
                    <text x={leftMargin - 8} y={readsTop + readsHeight / 2} fontSize={10} fill="#5b6470" textAnchor="middle"
                          transform={`rotate(-90, ${leftMargin - 8}, ${readsTop + readsHeight / 2})`}>reads</text>
                )}

                {/* Axis */}
                <line x1={leftMargin} y1={axisY} x2={leftMargin + plotWidth} y2={axisY} stroke="#8a919b" />
                {ticks.map((pos, i) => (
                    <g key={i}>
                        <line x1={leftMargin + pos * scale} y1={axisY} x2={leftMargin + pos * scale} y2={axisY + 4} stroke="#8a919b" />
                        <text x={leftMargin + pos * scale} y={axisY + 16} textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'} fontSize={10} fill="#5b6470">
                            {pos.toLocaleString()}
                        </text>
                    </g>
                ))}
            </svg>
            <div className="d-flex align-items-center gap-3 mt-2 nano-hint">
                <span><span style={{ display: 'inline-block', width: 10, height: 10, background: '#0f4c5c', marginRight: 4 }} />forward</span>
                <span><span style={{ display: 'inline-block', width: 10, height: 10, background: '#7fa7b3', marginRight: 4 }} />reverse</span>
                {rows.length > visibleRows.length && (
                    <button className="btn btn-link btn-sm p-0" onClick={() => setMaxRows(m => m + ROW_STEP * 2)}>
                        Show more rows ({visibleRows.length} of {rows.length})
                    </button>
                )}
                {maxRows > ROW_STEP && (
                    <button className="btn btn-link btn-sm p-0" onClick={() => setMaxRows(ROW_STEP)}>Collapse</button>
                )}
            </div>
        </div>
    );
};

export default AlignmentViewer;
