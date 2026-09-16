# nanoCAS in the landscape of real-time nanopore analysis tools

*Catalogue compiled 2026-09-16 from vendor documentation and the primary literature (links at the end). The purpose is
to state precisely what already exists, where nanoCAS overlaps, and what it does that nothing else in this list does.*

## 1. The objection

"MinKNOW can already align reads to a reference during a run." True: MinKNOW accepts a FASTA/MMI (and an optional BED
file) at run setup and populates live alignment graphs, and EPI2ME's `wf-alignment` / `wf-metagenomics` can watch an
output directory and analyse files as they appear. What none of these do is **decide and notify**: there is no threshold
on a sequence of interest, no message to a phone when it is crossed, no instrument-health rule set, and no link to the
laboratory's confirmatory test. nanoCAS is not an aligner or a classifier; it is the alerting and decision layer that sits
on top of whichever classifier the lab already trusts.

## 2. Catalogue

### 2.1 Vendor software (Oxford Nanopore)

| Tool | What it does | Real-time | Alerts | Run-health rules | Pluggable classifier | Lab-result link |
|---|---|---|---|---|---|---|
| **MinKNOW** live alignment | Aligns basecalled reads to a user FASTA/MMI (optional BED) and draws coverage plots in the run UI; writes BAM/FASTQ. | Yes | No (visual only) | Pore-scan and channel-state plots, but no user-configurable rules or notifications | No (minimap2 only) | No |
| **EPI2ME `wf-alignment`** | Nextflow alignment + QC report; can watch a directory for new files. | Yes (directory watching) | No | No | No | No |
| **EPI2ME `wf-metagenomics`** (successor of WIMP) | Kraken2 (server mode) or minimap2 taxonomic classification with a live report; watches directory. | Yes | No | No | Kraken2 or minimap2, fixed | No |
| **EPI2ME `wf-basecalling`** | Dorado basecalling with optional minimap2 alignment; directory watching. | Yes | No | No | No | No |
| **Adaptive sampling** (in MinKNOW) | Real-time read rejection to enrich/deplete targets. | Yes (signal level) | No | No | No | No |

### 2.2 Academic real-time monitoring tools

| Tool | Focus | Real-time | Alerts | Run-health | Classifier | Notes |
|---|---|---|---|---|---|---|
| **RAMPART** (ARTIC network) | Amplicon coverage per barcode for viral genome sequencing. | Yes | No | No | minimap2 | Purpose-built for tiled amplicons; no thresholds/notifications. |
| **VisPan** (2025) | RAMPART adapted for multiplex-PCR syndromic panels; per-target detection view. | Yes (snakemake every minute) | No | No | minimap2 | Closest visual analogue for panels; no alerting or run rules. |
| **minoTour** | Web platform for run monitoring; ARTIC pipeline integration; predicts which samples will reach coverage. | Yes (from MinKNOW API) | Email on ARTIC coverage milestones | Run metrics from MinKNOW, no rule engine | minimap2 / Centrifuge (metagenomics app) | Nearest overall relative; Django/Celery stack, heavier to deploy. |
| **NanoOK RT** | Real-time metagenomics + AMR detection with per-minute updates. | Yes | No | No | BLAST-based | Research tool. |
| **MARTi** (2025) | Real-time metagenomics engine + GUI with prefiltering, classification, AMR. | Yes | No | No | Several (Centrifuge, Kraken2, BLAST, …) | Strong on taxonomy visualisation; not on run health or notifications. |
| **MMonitor** (2025) | Real-time monitoring of microbial communities from long reads. | Yes | No | No | Fixed | Community profiling, not diagnostics. |
| **Nanometa Live** | Real-time metagenomic pathogen identification with a simple GUI. | Yes | Highlights pathogens of interest | No | Kraken2 | Closest "pathogen list" concept; no thresholds/notifications/run rules/qPCR. |
| **readfish / ReadBouncer / UNCALLED / BOSS-RUNS** | Adaptive sampling decision engines. | Yes (signal) | No | No | minimap2 / IBF / raw signal | Solve a different problem (enrichment), can be combined with nanoCAS. |
| **Icarust** | Real-time simulator for adaptive-sampling development. | n/a | n/a | n/a | n/a | Same idea as nanoCAS's simulator, at the signal level. |

### 2.3 Batch / cloud metagenomics platforms

| Tool | Focus | Real-time | Alerts | Notes |
|---|---|---|---|---|
| **CZ ID** | Cloud pathogen detection + AMR, long-read pipeline. | No (upload after run) | No | Free, no-code; excellent for retrospective analysis. |
| **BugSeq** | Commercial cloud long-read metagenomics with reporting. | No | Reports | High accuracy; not instrument-side. |
| **Kraken2 / Bracken, Centrifuge, MetaMaps, sourmash, Taxor** | Classifiers / abundance estimators. | Library-level | No | These are the engines nanoCAS can wrap. |
| **Pavian, Krona** | Visualisation of classifier reports. | No | No | Complementary. |
| **NanoPlot / pycoQC / MinIONQC** | Post-run QC of `sequencing_summary`. | No | No | nanoCAS tails the same file live and turns it into rules. |

### 2.4 What the literature says about qPCR vs nanopore yield

Clinical validations consistently report a linear relationship between log10(reads per million) and qPCR Ct, with
sensitivity collapsing above Ct ≈ 30–35 and near-complete genomes only below Ct ≈ 25. None of the tools above capture
the confirmatory qPCR result next to the sequencing result, so this relationship is re-derived by hand in every study.

## 3. Where nanoCAS is different

1. **Decision layer, not another classifier.** Thresholds (depth, breadth, read count, read fraction) per target and
   per GFF feature; each fires once and is delivered by e-mail, SMS, desktop notification and into MinKNOW. Every
   other real-time tool stops at a plot.
2. **Instrument-health rules with hysteresis.** Run never started, data stalled, low median Q, pore decline, few active
   channels, low pass rate, short reads: evaluated continuously from the live `sequencing_summary`, with recovery
   events. minoTour surfaces metrics; MinKNOW shows plots; neither lets a lab manager say "text me if pores fall
   below half of peak".
3. **Classifier plug-ins.** minimap2, Kraken2 and Centrifuge are built in; any tool that yields a BAM or per-taxon
   counts can be added by dropping a Python file in `~/.nanocas/plugins/`. Alerts are defined on metrics, not on a
   tool.
4. **Lab-result integration.** qPCR Ct values are recorded per target and project; nanoCAS computes the log10(RPM)–Ct
   regression, concordance (sensitivity, specificity, Cohen's kappa), Wilson-interval positivity rates across runs,
   median time-to-detection and a Ct-based limit of detection. This turns individual runs into a validation dataset.
5. **Demonstrable without an instrument.** A built-in MinKNOW-like simulator with scripted failure modes; every
   feature above can be shown on a laptop.
6. **Single-process, offline deployment.** One Python process serves API, UI and monitoring; no CDN, no cloud, no
   Nextflow, no Redis.

## 4. Honest gaps

- No basecalling and no signal-level features (adaptive sampling); nanoCAS starts at FASTQ.
- No AMR gene detection or consensus genome assembly (CZ ID, BugSeq, MARTi do this).
- Taxonomic visualisation is a table, not a Krona/Sankey chart.
- Cohort statistics are descriptive; there is no multi-site or spatial epidemiology.

## Sources

- MinKNOW live alignment and analysis: https://nanoporetech.com/document/experiment-companion-minknow ,
  https://nanoporetech.com/document/data-analysis
- EPI2ME workflows: https://nanoporetech.com/support/software/EPI2ME/installation-and-updating/what-workflows-are-available-on-epi2me ,
  https://epi2me.nanoporetech.com/epi2me-docs/workflows/wf-basecalling/ , https://epi2me.nanoporetech.com/progressive-kraken2/
- RAMPART / VisPan: https://pmc.ncbi.nlm.nih.gov/articles/PMC13290484/ , https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10083257/
- minoTour: https://academic.oup.com/bioinformatics/article/38/4/1133/6428657
- MARTi: https://genome.cshlp.org/content/35/11/2488
- MMonitor: https://www.cell.com/cell-reports-methods/fulltext/S2667-2375(25)00302-9
- Nanometa Live: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10924712/
- CZ ID: https://link.springer.com/article/10.1186/s13073-025-01480-2 ; BugSeq: https://bmcbioinformatics.biomedcentral.com/articles/10.1186/s12859-021-04089-5
- ReadBouncer / adaptive sampling benchmark: https://academic.oup.com/bioinformatics/article/38/Supplement_1/i153/6617484 ,
  https://link.springer.com/article/10.1186/s13059-025-03729-w ; Icarust: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10980563/
- MetaMaps: https://www.nature.com/articles/s41467-019-10934-2 ; long-read tool review: https://academic.oup.com/gpb/article/23/4/qzaf075/8239969
- qPCR–nanopore relationship: https://pmc.ncbi.nlm.nih.gov/articles/PMC8601544/ , https://pubmed.ncbi.nlm.nih.gov/42632487/ ,
  https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7822954/
