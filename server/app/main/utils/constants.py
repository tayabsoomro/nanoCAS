"""File-type constants shared by the watcher, scanner and run-health code."""

# Canonical FASTQ extension set. `.fasta` is deliberately excluded: FASTA
# reads carry no quality scores, so every run-health metric would be
# empty while alignment silently "worked". See LOGBOOK section 4.17.
FASTQ_EXTENSIONS = ('.fastq', '.fq', '.fastq.gz', '.fq.gz')

# External BAM ingestion path (sorted BAMs from elsewhere).
BAM_EXTENSIONS = ('.bam',)

# Raw-signal outputs MinKNOW writes before/alongside basecalling. They
# aren't processed by nanoCAS but they *are* evidence that the run has
# started, which the run-health "run not started" rule relies on.
RAW_SIGNAL_EXTENSIONS = ('.pod5', '.fast5')

# Everything that counts as "the sequencer is producing data".
DATA_EXTENSIONS = FASTQ_EXTENSIONS + BAM_EXTENSIONS + RAW_SIGNAL_EXTENSIONS

# MinKNOW output sub-directories worth looking into when the user points
# nanoCAS at the top-level run directory.
MINKNOW_SUBDIRS = ('fastq_pass', 'fastq_fail', 'bam_pass', 'bam_fail',
                   'pod5_pass', 'pod5_fail', 'pod5', 'fast5_pass', 'fast5_fail')
