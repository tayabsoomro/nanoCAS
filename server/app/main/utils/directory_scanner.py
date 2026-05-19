import os
import glob
import logging

logger = logging.getLogger('nanocas')

NANOPORE_EXTENSIONS = {
    'fastq': ['.fastq', '.fastq.gz', '.fq', '.fq.gz'],
    'bam': ['.bam'],
    'pod5': ['.pod5'],
    'fast5': ['.fast5'],
    'sequencing_summary': ['sequencing_summary'],
    'fasta': ['.fasta', '.fa', '.fasta.gz', '.fa.gz'],
}

KNOWN_SUBDIRS = ['fastq_pass', 'fastq_fail', 'fast5_pass', 'fast5_fail', 'pod5_pass', 'pod5_fail']


def scan_directory(directory: str) -> dict:
    result = {
        'directory': directory,
        'exists': False,
        'fastq_files': [],
        'bam_files': [],
        'pod5_files': [],
        'fast5_files': [],
        'sequencing_summary': None,
        'fasta_files': [],
        'subdirectories': [],
        'suggested_watch_dir': None,
        'file_type': None,
        'total_files': 0,
    }

    if not os.path.isdir(directory):
        return result

    result['exists'] = True

    for entry in os.scandir(directory):
        if entry.is_dir():
            result['subdirectories'].append(entry.name)

    for root, dirs, files in os.walk(directory):
        rel_root = os.path.relpath(root, directory)
        for fname in files:
            full_path = os.path.join(root, fname)
            rel_path = os.path.join(rel_root, fname) if rel_root != '.' else fname
            lower = fname.lower()

            if 'sequencing_summary' in lower and (lower.endswith('.txt') or lower.endswith('.csv')):
                result['sequencing_summary'] = full_path
                continue

            for ext in NANOPORE_EXTENSIONS['fastq']:
                if lower.endswith(ext):
                    result['fastq_files'].append(rel_path)
                    break

            for ext in NANOPORE_EXTENSIONS['bam']:
                if lower.endswith(ext):
                    result['bam_files'].append(rel_path)
                    break

            for ext in NANOPORE_EXTENSIONS['pod5']:
                if lower.endswith(ext):
                    result['pod5_files'].append(rel_path)
                    break

            for ext in NANOPORE_EXTENSIONS['fast5']:
                if lower.endswith(ext):
                    result['fast5_files'].append(rel_path)
                    break

            for ext in NANOPORE_EXTENSIONS['fasta']:
                if lower.endswith(ext):
                    result['fasta_files'].append(rel_path)
                    break

    result['total_files'] = (
        len(result['fastq_files']) +
        len(result['bam_files']) +
        len(result['pod5_files']) +
        len(result['fast5_files'])
    )

    if result['fastq_files']:
        result['file_type'] = 'FASTQ'
    elif result['bam_files']:
        result['file_type'] = 'BAM'

    fastq_pass = os.path.join(directory, 'fastq_pass')
    if os.path.isdir(fastq_pass) and result['fastq_files']:
        result['suggested_watch_dir'] = fastq_pass
    else:
        result['suggested_watch_dir'] = directory

    return result


def parse_sequencing_summary(summary_path: str, max_reads: int = 50000) -> dict:
    result = {
        'q_scores': [],
        'read_lengths': [],
        'channel_states': {},
        'channels': set(),
        'timestamps': [],
        'median_q_over_time': [],
        'total_reads': 0,
    }

    if not summary_path or not os.path.exists(summary_path):
        return result

    try:
        import csv
        with open(summary_path, 'r') as f:
            first_line = f.readline()
            delimiter = '\t' if '\t' in first_line else ','
            f.seek(0)
            reader = csv.DictReader(f, delimiter=delimiter)
            headers = reader.fieldnames or []
            
            q_col = None
            for candidate in ['mean_qscore_template', 'mean_qscore', 'quality_score']:
                if candidate in headers:
                    q_col = candidate
                    break

            len_col = None
            for candidate in ['sequence_length_template', 'sequence_length', 'read_length']:
                if candidate in headers:
                    len_col = candidate
                    break

            channel_col = 'channel' if 'channel' in headers else None
            time_col = None
            for candidate in ['start_time', 'template_start']:
                if candidate in headers:
                    time_col = candidate
                    break

            q_scores = []
            read_lengths = []
            time_q_pairs = []
            count = 0

            for row in reader:
                if count >= max_reads:
                    break

                if q_col and row.get(q_col):
                    try:
                        q = float(row[q_col])
                        q_scores.append(q)
                    except (ValueError, TypeError):
                        pass

                if len_col and row.get(len_col):
                    try:
                        rl = int(float(row[len_col]))
                        read_lengths.append(rl)
                    except (ValueError, TypeError):
                        pass

                if channel_col and row.get(channel_col):
                    try:
                        ch = int(row[channel_col])
                        result['channels'].add(ch)
                    except (ValueError, TypeError):
                        pass

                if time_col and row.get(time_col) and q_col and row.get(q_col):
                    try:
                        t = float(row[time_col])
                        q = float(row[q_col])
                        time_q_pairs.append((t, q))
                    except (ValueError, TypeError):
                        pass

                count += 1

            result['q_scores'] = q_scores
            result['read_lengths'] = read_lengths
            result['total_reads'] = count
            result['channels'] = list(result['channels'])

            if time_q_pairs:
                time_q_pairs.sort(key=lambda x: x[0])
                bucket_size = max(1, len(time_q_pairs) // 50)
                medians = []
                for i in range(0, len(time_q_pairs), bucket_size):
                    bucket = time_q_pairs[i:i + bucket_size]
                    bucket_qs = sorted([p[1] for p in bucket])
                    mid = len(bucket_qs) // 2
                    median_q = bucket_qs[mid] if len(bucket_qs) % 2 == 1 else (bucket_qs[mid - 1] + bucket_qs[mid]) / 2
                    avg_time = sum(p[0] for p in bucket) / len(bucket)
                    medians.append({'time': avg_time, 'median_q': round(median_q, 2)})
                result['median_q_over_time'] = medians

    except Exception as e:
        logger.error(f"Error parsing sequencing summary {summary_path}: {e}")

    return result


def get_pore_health(summary_path: str) -> dict:
    health = {
        'total_channels': 0,
        'active_channels': 0,
        'channel_states': {
            'sequencing': 0,
            'unavailable': 0,
            'other': 0,
        },
        'occupancy_rate': 0.0,
    }

    if not summary_path or not os.path.exists(summary_path):
        return health

    try:
        import csv
        channels_seen = set()
        channels_with_reads = set()

        with open(summary_path, 'r') as f:
            first_line = f.readline()
            delimiter = '\t' if '\t' in first_line else ','
            f.seek(0)
            reader = csv.DictReader(f, delimiter=delimiter)
            headers = reader.fieldnames or []
            channel_col = 'channel' if 'channel' in headers else None

            if not channel_col:
                return health

            for row in reader:
                try:
                    ch = int(row[channel_col])
                    channels_seen.add(ch)
                    channels_with_reads.add(ch)
                except (ValueError, TypeError):
                    pass

        total = max(len(channels_seen), 512)
        active = len(channels_with_reads)
        health['total_channels'] = total
        health['active_channels'] = active
        health['channel_states']['sequencing'] = active
        health['channel_states']['unavailable'] = total - active
        health['occupancy_rate'] = round((active / total) * 100, 1) if total > 0 else 0.0

    except Exception as e:
        logger.error(f"Error computing pore health from {summary_path}: {e}")

    return health
