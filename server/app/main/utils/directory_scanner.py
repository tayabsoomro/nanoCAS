import os
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
