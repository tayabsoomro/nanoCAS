/**
 * Shared API client + small helpers used across the UI.
 *
 * `REACT_APP_API_ENDPOINT` points at the backend when the UI is served
 * from a different origin (e.g. the CRA dev server on :3000 talking to
 * Flask on :5007). When it is empty, requests are relative and go
 * through the CRA `proxy` (development) or the same origin (production
 * build served by the backend / a reverse proxy).
 */
import axios from 'axios';

export const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT ?? '';

export const api = axios.create({ baseURL: API_ENDPOINT || undefined });

/** Backend timestamps are "YYYY-MM-DD HH:MM:SS" (local time). Safari and
 *  Firefox refuse that format in `new Date()`, so normalise to ISO. */
export function parseTimestamp(ts: string): number {
    if (!ts) return NaN;
    const iso = ts.includes('T') ? ts : ts.replace(' ', 'T');
    return new Date(iso).getTime();
}

export function formatDuration(seconds: number | null | undefined): string {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return 'n/a';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(1)} min`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} h`;
    return `${(seconds / 86400).toFixed(1)} d`;
}

export function formatBases(bases: number | null | undefined): string {
    if (!bases) return '0';
    if (bases >= 1e9) return `${(bases / 1e9).toFixed(2)} Gb`;
    if (bases >= 1e6) return `${(bases / 1e6).toFixed(1)} Mb`;
    if (bases >= 1e3) return `${(bases / 1e3).toFixed(1)} kb`;
    return `${bases} b`;
}

export function formatNumber(n: number | null | undefined, digits = 0): string {
    if (n === null || n === undefined || isNaN(n)) return 'n/a';
    return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export type Severity = 'info' | 'warning' | 'critical';

export interface AlertRecord {
    id: string;
    timestamp: string;
    projectId?: string | null;
    source: 'coverage' | 'run_health' | 'system';
    type: string;
    severity: Severity;
    state: 'fired' | 'recovered';
    message: string;
    details: Record<string, any>;
}

export interface RuleStatus {
    id: string;
    description: string;
    active: boolean;
    fired_at: number | null;
    message: string | null;
}

export interface RunHealthConfig {
    enabled: boolean;
    runStartTimeoutMin: number;
    stallTimeoutMin: number;
    minMedianQ: number;
    qScoreThreshold: number;
    minPassRate: number;
    minActivePoresPct: number;
    minActiveChannelsPct: number;
    minMedianReadLength: number;
    windowReads: number;
    poreWindowMin: number;
    minWindowReads: number;
    consecutiveChecks: number;
    checkIntervalSec: number;
}

export const RUN_HEALTH_FIELDS: { key: keyof RunHealthConfig; label: string; help: string; unit?: string; step?: number }[] = [
    { key: 'runStartTimeoutMin', label: 'Run-start timeout', unit: 'min', help: 'Alert if no sequencing output appears this long after monitoring starts.' },
    { key: 'stallTimeoutMin', label: 'Stall timeout', unit: 'min', help: 'Alert if no new data arrives for this long once the run has started.' },
    { key: 'minMedianQ', label: 'Minimum median Q', step: 0.5, help: 'Alert when the median Q-score of the recent-read window drops below this.' },
    { key: 'qScoreThreshold', label: 'Pass Q-score', step: 0.5, help: 'Per-read pass cut-off used for histogram colouring and pass rate when MinKNOW does not report passes_filtering (Q7 HAC legacy, Q9 R10.4, Q10 SUP).' },
    { key: 'minPassRate', label: 'Minimum pass rate', unit: '%', help: 'Alert when fewer than this share of recent reads pass.' },
    { key: 'minActivePoresPct', label: 'Pore decline floor', unit: '% of peak', help: 'Alert when the number of channels producing reads drops below this fraction of the run peak.' },
    { key: 'minActiveChannelsPct', label: 'Minimum active channels', unit: '% of flow cell', help: 'Alert when fewer than this share of all channels produce reads (catches a bad flow cell from the start).' },
    { key: 'minMedianReadLength', label: 'Minimum median read length', unit: 'bp (0 = off)', help: 'Optional: alert when recent reads are shorter than this.' },
    { key: 'checkIntervalSec', label: 'Check interval', unit: 's', help: 'How often the run-health rules are evaluated.' },
];

export interface RunHealthSnapshot {
    projectId?: string;
    monitoring: boolean;
    summary_file?: { path: string; size: number; mtime: number; parse_errors: number } | null;
    totals: {
        reads: number; bases?: number; mean_q?: number | null; pass_reads?: number; fail_reads?: number;
        has_pass_column?: boolean; run_elapsed_seconds?: number | null; end_reasons?: Record<string, number>;
    };
    q_hist?: number[];
    len_hist?: { edges: number[]; counts: number[] };
    median_q_over_time?: { time: number; median_q: number | null; reads: number }[];
    throughput?: { time: number; reads: number; bases: number; passed: number; seconds: number }[];
    window?: {
        reads: number; median_q: number | null; mean_q: number | null; median_length: number | null;
        n50: number; pass_rate: number | null; active_channels: number; span_seconds: number;
    };
    pores?: {
        flow_cell_type: string; total_channels: number; channels_seen: number; active_channels: number;
        active_window_min: number; occupancy_rate: number;
        channel_states: { sequencing: number; unavailable: number; other: number };
    };
    inputs?: {
        watch_dir?: string; data_files?: number; last_data_file?: string | null; last_data_time?: number | null;
        data_seen?: boolean; monitor_started?: number; files_processed?: number; files_failed?: number;
    };
    minknow?: Record<string, any> | null;
    rules?: RuleStatus[];
    config?: RunHealthConfig;
    q_threshold?: number;
    evaluated_at?: number;
}

export function severityBadgeClass(sev: Severity | string): string {
    switch (sev) {
        case 'critical': return 'nano-badge nano-badge-critical';
        case 'warning': return 'nano-badge nano-badge-warning';
        default: return 'nano-badge nano-badge-info';
    }
}

/** First whitespace token of a FASTA header: the id samtools/pysam use. */
export function canonicalRefId(header: string | undefined | null): string {
    return (header || '').trim().split(/\s+/)[0] || '';
}

/** Map canonical reference id -> query config for a project. */
export function queryByReference(projectData: any): Map<string, any> {
    const map = new Map<string, any>();
    (projectData?.queries || []).forEach((q: any) => {
        const headers: string[] = [...(q.headers || []), ...(q.header ? [q.header] : [])];
        headers.forEach(h => {
            const id = canonicalRefId(h);
            if (id) map.set(id, q);
        });
    });
    return map;
}
