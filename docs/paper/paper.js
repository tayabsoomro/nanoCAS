/* Builds the nanoCAS BMC Bioinformatics manuscript draft as a .docx with real Word comments. */
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, BorderStyle, ImageRun, CommentRangeStart, CommentRangeEnd, CommentReference,
  PageBreak, ShadingType, LevelFormat, PageNumber, Footer, TabStopType,
} = require('docx');

// ---------------------------------------------------------------------------
// References: cited in the text as {key}; numbered in order of first appearance.
// ---------------------------------------------------------------------------
const REFS = {
  charalampous: 'Charalampous T, Kay GL, Richardson H, Aydin A, Baldan R, Jeanes C, et al. Nanopore metagenomics enables rapid clinical diagnosis of bacterial lower respiratory infection. Nat Biotechnol. 2019;37(7):783-92.',
  gu: 'Gu W, Deng X, Lee M, Sucu YD, Arevalo S, Stryke D, et al. Rapid pathogen detection by metagenomic next-generation sequencing of infected body fluids. Nat Med. 2021;27(1):115-24.',
  harper: 'Harper SJ, Ward LI, Clover GRG. Development of LAMP and real-time PCR methods for the rapid detection of Xylella fastidiosa for quarantine and field applications. Phytopathology. 2010;100(12):1282-8.',
  probert: 'Probert WS, Schrader KN, Khuong NY, Bystrom SL, Graves MH. Real-time multiplex PCR assay for detection of Brucella spp., B. abortus, and B. melitensis. J Clin Microbiol. 2004;42(3):1290-3.',
  faino: 'Faino L, Scala V, Albanese A, Modesti V, Grottoli A, Pucci N, et al. Nanopore sequencing for the detection and identification of Xylella fastidiosa subspecies and sequence types from naturally infected plant material. Plant Pathol. 2021;70(8):1860-70.',
  ont: 'Oxford Nanopore Technologies. MinKNOW and EPI2ME documentation. https://nanoporetech.com/document/experiment-companion-minknow and https://epi2me.nanoporetech.com/. Accessed [date].',
  rampart: 'ARTIC Network. RAMPART: Read Assignment, Mapping, and Phylogenetic Analysis in Real Time. https://github.com/artic-network/rampart. Accessed [date].',
  minotour: 'Munro R, Santos R, Payne A, Forey T, Osei S, Holmes N, et al. minoTour, real-time monitoring and analysis for nanopore sequencers. Bioinformatics. 2022;38(4):1133-5.',
  boardion: 'Bruno A, Aury JM, Engelen S. BoardION: real-time monitoring of Oxford Nanopore sequencing instruments. BMC Bioinformatics. 2021;22(1):245.',
  marti: 'Peel N, Martin S, Heavens D, Yu DW, Clark MD, Leggett RM. Real-time analysis and visualization of nanopore metagenomic samples with MARTi. Genome Res. 2025;35(11):2488-[end page].',
  nanometa: 'Sandås K, Lewerentz J, Karlsson E, Karlsson L, Sundell D, Simonyté-Sjödin K, et al. Nanometa Live: a user-friendly application for real-time metagenomic data analysis and pathogen identification. Bioinformatics. 2024;40(3):btae108.',
  nanook: 'Leggett RM, Alcon-Giner C, Heavens D, Caim S, Brook TC, Kujawska M, et al. Rapid MinION profiling of preterm microbiota and antimicrobial-resistant pathogens. Nat Microbiol. 2020;5(3):430-42.',
  bugseq: 'Fan J, Huang S, Chorlton SD. BugSeq: a highly accurate cloud platform for long-read metagenomic analyses. BMC Bioinformatics. 2021;22(1):160.',
  fastv: 'Chen S, He C, Li Y, Li Z, Melançon CE. A computational toolset for rapid identification of SARS-CoV-2, other viruses and microorganisms from sequencing data. Brief Bioinform. 2021;22(2):924-35.',
  sunbeam: 'Clarke EL, Taylor LJ, Zhao C, Connell A, Lee JJ, Fett B, et al. Sunbeam: an extensible pipeline for analyzing metagenomic sequencing experiments. Microbiome. 2019;7(1):46.',
  readfish: 'Payne A, Holmes N, Clarke T, Munro R, Debebe BJ, Loose M. Readfish enables targeted nanopore sequencing of gigabase-sized genomes. Nat Biotechnol. 2021;39(4):442-50.',
  martin: 'Martin S, Heavens D, Lan Y, Horsfield S, Clark MD, Leggett RM. Nanopore adaptive sampling: a tool for enrichment of low abundance species in metagenomic samples. Genome Biol. 2022;23(1):11.',
  minimap2: 'Li H. Minimap2: pairwise alignment for nucleotide sequences. Bioinformatics. 2018;34(18):3094-100.',
  kraken2: 'Wood DE, Lu J, Langmead B. Improved metagenomic analysis with Kraken 2. Genome Biol. 2019;20(1):257.',
  centrifuge: 'Kim D, Song L, Breitwieser FP, Salzberg SL. Centrifuge: rapid and sensitive classification of metagenomic sequences. Genome Res. 2016;26(12):1721-9.',
  samtools: 'Danecek P, Bonfield JK, Liddle J, Marshall J, Ohan V, Pollard MO, et al. Twelve years of SAMtools and BCFtools. Gigascience. 2021;10(2):giab008.',
  nanoplot: 'De Coster W, D\'Hert S, Schultz DT, Cruts M, Van Broeckhoven C. NanoPack: visualizing and processing long-read sequencing data. Bioinformatics. 2018;34(15):2666-9.',
  pycoqc: 'Leger A, Leonardi T. pycoQC, interactive quality control for Oxford Nanopore Sequencing. J Open Source Softw. 2019;4(34):1236.',
  wilson: 'Wilson EB. Probable inference, the law of succession, and statistical inference. J Am Stat Assoc. 1927;22(158):209-12.',
  cohen: 'Cohen J. A coefficient of agreement for nominal scales. Educ Psychol Meas. 1960;20(1):37-46.',
  sicard: 'Sicard A, Zeilinger AR, Vanhove M, Schartel TE, Beal DJ, Daugherty MP, et al. Xylella fastidiosa: insights into an emerging plant pathogen. Annu Rev Phytopathol. 2018;56:181-202.',
  olsen: 'Olsen SC, Palmer MV. Advancement of knowledge of Brucella over the past 50 years. Vet Pathol. 2014;51(6):1076-89.',
};
const refOrder = [];
function cite(keys) {
  const nums = keys.split(',').map(k => k.trim()).map(k => {
    if (!REFS[k]) throw new Error('unknown reference ' + k);
    let i = refOrder.indexOf(k);
    if (i < 0) { refOrder.push(k); i = refOrder.length - 1; }
    return i + 1;
  });
  // collapse runs (1,2,3 -> 1-3)
  nums.sort((a, b) => a - b);
  const parts = [];
  let s = nums[0], p = nums[0];
  for (let i = 1; i <= nums.length; i++) {
    if (i < nums.length && nums[i] === p + 1) { p = nums[i]; continue; }
    parts.push(s === p ? `${s}` : (p === s + 1 ? `${s}, ${p}` : `${s}-${p}`));
    if (i < nums.length) { s = nums[i]; p = nums[i]; }
  }
  return `[${parts.join(', ')}]`;
}

// ---------------------------------------------------------------------------
// Comments
// ---------------------------------------------------------------------------
const comments = [];
function newComment(text) {
  const id = comments.length;
  comments.push({ id, author: 'Draft notes', initials: 'DN', date: new Date(), children: [new Paragraph({ children: [new TextRun({ text, font: 'Arial', size: 20 })] })] });
  return id;
}

// ---------------------------------------------------------------------------
// Inline markup:  _italic_   **bold**   [[anchor text||comment text]]   {refkey,refkey}
// ---------------------------------------------------------------------------
const FONT = 'Arial';
const SIZE = 22; // 11 pt
function inline(text, base = {}) {
  text = text.replace(/\{([a-z0-9_, ]+)\}/g, (m, keys) => cite(keys));
  const out = [];
  const re = /\[\[([\s\S]*?)\|\|([\s\S]*?)\]\]/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(...fmt(text.slice(last, m.index), base));
    const id = newComment(m[2]);
    out.push(new CommentRangeStart(id));
    out.push(...fmt(m[1], base));
    out.push(new CommentRangeEnd(id));
    out.push(new TextRun({ children: [new CommentReference(id)], font: FONT, size: SIZE }));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...fmt(text.slice(last), base));
  return out;
}
function fmt(text, base) {
  const out = [];
  const re = /(\*\*[\s\S]+?\*\*|(?<![\w])_[^_\n]+?_(?![\w]))/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, size: SIZE, ...base }));
    const tok = m[0];
    if (tok.startsWith('**')) out.push(...fmt(tok.slice(2, -2), { ...base, bold: true }));
    else out.push(new TextRun({ text: tok.slice(1, -1), font: FONT, size: SIZE, italics: true, ...base }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, size: SIZE, ...base }));
  return out;
}
const P = (text, opts = {}) => new Paragraph({ children: inline(text, opts.run || {}), spacing: { after: 160, line: 360 }, alignment: AlignmentType.LEFT, ...opts.para });
const H1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 160 }, children: [new TextRun({ text: t, font: FONT, size: 28, bold: true, color: '000000' })] });
const H2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 240, after: 120 }, children: [new TextRun({ text: t, font: FONT, size: 24, bold: true, color: '000000' })] });
const H3 = t => new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 200, after: 80 }, children: [new TextRun({ text: t, font: FONT, size: SIZE, bold: true, italics: true, color: '000000' })] });
const Bullet = t => new Paragraph({ numbering: { reference: 'bullets', level: 0 }, spacing: { after: 80, line: 360 }, children: inline(t) });
const Numbered = t => new Paragraph({ numbering: { reference: 'refs', level: 0 }, spacing: { after: 80, line: 300 }, children: inline(t) });
const Break = () => new Paragraph({ children: [new PageBreak()] });

function table(headers, rows, widths, opts = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: '9AA5AD' };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (t, w, head) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: head ? { type: ShadingType.CLEAR, fill: 'EEF1F4', color: 'auto' } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ spacing: { after: 0, line: 260 }, children: inline(String(t), head ? { bold: true, size: 18 } : { size: 18 }) })],
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map(r => new TableRow({ children: r.map((c, i) => cell(c, widths[i], false)) }))],
  });
}
function image(path, widthIn) {
  const buf = fs.readFileSync(path);
  const { width, height } = pngSize(buf);
  const w = Math.round(widthIn * 96), h = Math.round(w * height / width);
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new ImageRun({ type: 'png', data: buf, transformation: { width: w, height: h } })] });
}
function pngSize(buf) { return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }; }
const Caption = t => new Paragraph({ spacing: { after: 240, line: 300 }, children: inline(t, { size: 20 }) });

// ---------------------------------------------------------------------------
// Content
// ---------------------------------------------------------------------------
const body = [];
const add = (...x) => body.push(...x);

// Title page ---------------------------------------------------------------
add(new Paragraph({ spacing: { after: 240 }, children: inline('[[nanoCAS: a real-time classification and alerting system for pathogen detection during nanopore sequencing||Title. Your draft used "Web-platform for nanopore-based point-of-care diagnostics". I have led with what the software does (classify, alert, monitor) because BMC software titles work best when the tool name is followed by its function. Two alternatives if you prefer to keep the diagnostics angle: "nanoCAS: real-time alerting for nanopore-based pathogen diagnostics" or "nanoCAS: turning a nanopore sequencing run into a monitored diagnostic test".]]', { bold: true, size: 32 }) }));
const sup = t => new TextRun({ text: t, font: FONT, size: SIZE, superScript: true });
const tr = t => new TextRun({ text: t, font: FONT, size: SIZE });
add(new Paragraph({ spacing: { after: 160, line: 360 }, children: [tr('Tayab Soomro'), sup('1'), tr(', Sam Horovatin'), sup('2'), tr(', Tim J. Dumonceaux'), sup('1'), tr(', Matthew G. Links'), sup('2*')] }));
add(new Paragraph({ spacing: { after: 80, line: 360 }, children: [sup('1'), tr(' Agriculture and Agri-Food Canada, Saskatoon Research and Development Centre, Saskatoon, Saskatchewan, Canada')] }));
add(new Paragraph({ spacing: { after: 160, line: 360 }, children: [sup('2'), tr(' Department of Animal and Poultry Science, University of Saskatchewan, Saskatoon, Saskatchewan, Canada')] }));
add(P('[[Tayab Soomro, tayab.soomro@usask.ca. Sam Horovatin, s.horovatin@usask.ca. Tim J. Dumonceaux, tim.dumonceaux@agr.gc.ca. Matthew G. Links, matthew.links@usask.ca.||Please confirm affiliations. T.S. is listed under AAFC in your draft but uses a usask.ca address, so a dual affiliation (1,2) may be more accurate. Add ORCID iDs for all authors if available: BMC asks for them at submission.]]'));
add(P('*Corresponding author: Matthew G. Links, matthew.links@usask.ca'));
add(P('Article type: Software'));

add(Break());

// Abstract -------------------------------------------------------------------
add(H1('Abstract'));
add(H2('Background'));
add(P('Nanopore sequencing delivers reads while the run is in progress, so a pathogen or a contaminant can be detected long before the run ends. Existing real-time tools draw live plots and leave the decision to a person watching the screen. None of them let the user define what counts as a positive result, raise an alarm about the sequencer itself, or keep the sequencing result next to the confirmatory laboratory test.'));
add(H2('Results'));
add(P('We present nanoCAS (Nanopore Classification and Alerting System), an open-source web application that watches an Oxford Nanopore sequencer\'s output, classifies each new batch of reads against user-defined targets and sends an alert the moment a threshold is crossed. Thresholds can be set on depth, breadth, read count or read fraction for any target, and on depth over individual features from a GFF3 annotation. The classifier is a plug-in: minimap2, Kraken2 and Centrifuge are included, and another tool can be added with a small Python class. A second monitor reads the sequencing summary written by MinKNOW and alerts on the run itself, such as a run that never started, stalled output or declining pore activity. Alerts go out by e-mail, SMS, desktop notification and into MinKNOW. Quantitative PCR results can be recorded per target, and agreement, time to detection and the relationship between cycle threshold and read yield are computed in the application. A built-in simulator lets every function be tried without an instrument. We applied nanoCAS to naturally infected plant samples carrying _Xylella fastidiosa_ with matching qPCR quantification, and to a dilution series of _Brucella abortus_ DNA in a bovine background sequenced with adaptive sampling. [[Time to alert and read yield tracked the qPCR cycle threshold, and nanoCAS raised an alert for every spike level down to [lowest level] while flagging pore decline during the three-day run.||Placeholder for the headline numbers. Once the case-study analyses are done, replace with one or two concrete sentences: number of samples, correlation between Ct and log10 reads per million, median time to alert, lowest dilution detected. Keep the whole abstract under 350 words.]]'));
add(H2('Conclusions'));
add(P('nanoCAS turns a nanopore run into a monitored process that tells people when something they care about has happened. It is a decision layer on top of whichever classifier a laboratory already trusts, and it records the evidence needed to validate that decision against a reference test.'));
add(H2('Keywords'));
add(P('Nanopore sequencing, real-time analysis, pathogen detection, alerting, run monitoring, adaptive sampling, quantitative PCR, _Xylella fastidiosa_, _Brucella abortus_'));

// Background -----------------------------------------------------------------
add(H1('Background'));
add(P('The value of a diagnostic result depends on when it arrives. In a livestock herd or a crop, a pathogen that is identified early can be contained by isolating animals, removing plants or changing a treatment plan, and one that is identified late has already spread. In a clinical setting the same logic applies to the choice of an antimicrobial or the decision to isolate a patient. Sequencing-based diagnostics have shown that a causative organism can be identified from a clinical sample within hours {charalampous,gu}, but the time from sample to answer is only part of the picture. The other part is how quickly the answer reaches the person who has to act on it.'));
add(P('Most routine pathogen testing still relies on culture or on targeted amplification. Quantitative PCR (qPCR) assays exist for many agricultural pathogens, including _Xylella fastidiosa_ {harper} and _Brucella_ species {probert}, and they are sensitive and inexpensive. They also answer only the question that was asked. A qPCR panel cannot report an organism it has no primers for, it gives no information about which genes or plasmids are present, and the result is available only after the cycling program has finished. Metagenomic sequencing answers a broader question at the cost of more DNA input and more analysis, and nanopore sequencing adds a property that no other platform has: reads are delivered continuously while the run is in progress, so the analysis can start with the first batch of reads and stop as soon as the answer is clear {faino}.'));
add(P('Several tools already use this property. MinKNOW, the instrument control software from Oxford Nanopore Technologies, can align reads to a reference during a run and draw coverage plots, and the EPI2ME workflows can watch an output directory and update a report as files appear {ont}. RAMPART shows amplicon coverage per barcode for viral genome sequencing {rampart}. minoTour is a laboratory information system that captures run metrics and sequence data from MinKNOW and can run alignment and metagenomic classification on them {minotour}. BoardION monitors instrument performance across flow cells {boardion}. MARTi {marti}, Nanometa Live {nanometa} and NanoOK RT {nanook} classify reads taxonomically while the run is in progress and present the result as an interactive report. Cloud platforms such as BugSeq {bugseq} and general pipelines such as fastv {fastv} and Sunbeam {sunbeam} process the data after the run. Adaptive sampling tools such as readfish {readfish} act at the signal level to enrich or deplete chosen sequences, and have been shown to enrich low-abundance species in metagenomic samples {martin}.'));
add(P('What these tools have in common is that they stop at the plot. The user must sit in front of the screen, decide what a positive result looks like and notice when it appears. None of them let a laboratory state in advance that, for example, ten reads or five-fold depth over a given gene means a positive sample, and then notify a person by text message when that happens. None of them raise an alarm when the instrument is the problem rather than the sample, for instance when a flow cell produces no data or read quality collapses part way through a run. And none of them keep the confirmatory laboratory result in the same place as the sequencing result, so the comparison between the two is redone by hand in every study.'));
add(P('nanoCAS was written to fill this gap. It is not a new aligner or classifier. It is the layer that sits on top of an existing classifier, watches the sequencer, evaluates user-defined rules on every new batch of reads and on the state of the run, delivers alerts, and records the evidence that a laboratory needs to validate the rules against a reference test. In this paper we describe the design of nanoCAS and demonstrate it on two case studies: a plant pathogen in naturally infected plant tissue with matching qPCR data, and an animal pathogen spiked into a bovine background at decreasing concentrations and sequenced with adaptive sampling.'));

// Implementation -------------------------------------------------------------
add(H1('Implementation'));
add(H2('Design overview'));
add(P('nanoCAS is a single Python process that serves a web interface, a JSON API and the monitoring threads (Fig. 1). The back end is written in Python 3.10 or later on Flask with Flask-SocketIO for live updates to the browser, watchdog for file-system events, pysam and NumPy for alignment processing, and minknow_api for communication with the sequencer. The front end is a React application written in TypeScript with Chart.js for plots. It is compiled once and served by the same process, so a deployment consists of one program, the minimap2 and samtools binaries and no external services. Each analysis is a project with its own directory under the user\'s home directory that holds the configuration, the reference index, one BAM file per processed batch, the rolling coverage state, the coverage time series, the alert log and any laboratory results. Nothing is sent to a remote server and the application works without an internet connection.'));
add(P('A project is created in a three-step form. The user selects a directory to watch, either by choosing a sequencing position discovered through minknow_api or by giving a path, uploads the reference sequences and optionally a GFF3 annotation, picks the sequence records and features to monitor, and sets the alert thresholds. Once the reference index is built the project is ready and monitoring can be started with one click.'));

add(H2('Data ingestion'));
add(P('When monitoring is active nanoCAS watches the chosen directory, which is normally the fastq_pass folder written by MinKNOW. It accepts FASTQ files, gzipped or not, and BAM files produced by another tool. MinKNOW writes each batch to a temporary name and renames it when complete, and nanoCAS waits for the rename so that partially written files are never processed. Files already present when monitoring starts are processed first, so an analysis can be started or restarted part way through a run without losing data. A batch that fails, for example because the aligner ran out of memory, is recorded and retried on the next start rather than silently skipped. Batches are processed one at a time in the order they arrive.'));

add(H2('Classification and targets'));
add(P('Each batch is passed to a classifier. The default classifier aligns the reads with minimap2 {minimap2} using the nanopore preset and sorts the output with samtools {samtools}. From the resulting BAM file nanoCAS updates a per-position depth array for every reference sequence. The array is updated incrementally, so the cost of a batch depends on the number of reads in that batch and not on the number of reads seen so far. Depth counts every aligned base regardless of base quality, which matches the behaviour of samtools depth, and read counts include primary alignments only. From the arrays nanoCAS derives, for every target and after every batch, the mean depth, the breadth of coverage (the fraction of positions with at least one read), the number of reads and the fraction of all reads in the run so far that were assigned to the target. These four metrics are appended to a coverage time series that drives the coverage-over-time plot (Fig. 2a).'));
add(P('The classifier is a plug-in. A classifier is a Python class that declares a name, a kind (alignment or taxonomic), how it builds its index from the uploaded reference, and a method that classifies one batch and returns either a BAM file or a table of read counts per taxon. Kraken2 {kraken2} and Centrifuge {centrifuge} are included as taxonomic classifiers, in which case the targets are taxon names or NCBI taxonomy identifiers and the available metrics are read count and read fraction. A user can add another tool by placing a Python file in a plug-ins directory. The alert rules are defined on the metrics rather than on the tool, so a project can be moved from one classifier to another without changing its alerts. An example plug-in that classifies reads by shared k-mers is shipped with the source code and is used by the automated tests.'));

add(H2('Alert rules'));
add(P('A target can carry any combination of four thresholds: mean depth, breadth of coverage, read count and read fraction. Each rule is evaluated after every batch and fires once per run. When a GFF3 annotation was uploaded, the user can select individual features, for example a toxin gene or a resistance gene, and give each a depth threshold of its own. Feature rules are evaluated over the feature\'s coordinates on the same depth arrays and are useful when presence of a gene rather than presence of an organism is the question, for instance to distinguish a virulent strain from a harmless relative or a plasmid backbone from its insert. Feature thresholds can be edited while monitoring is running and take effect from the next batch.'));

add(H2('Run-health monitoring'));
add(P('A second thread reads the sequencing summary file that MinKNOW writes alongside the reads. The file is read incrementally, and from each new block of rows nanoCAS maintains a Q-score histogram, a read-length histogram, per-minute throughput, the set of channels that produced reads in the last ten minutes and a rolling window of the most recent reads. Seven rules are evaluated on this state at a fixed interval, by default every 30 seconds (Table 2). Each rule fires only after its condition has held for two consecutive evaluations and logs a recovery entry when the condition clears, after which it can fire again. This hysteresis prevents a single slow batch from raising an alarm. The flow-cell type is inferred from the highest channel number in the summary, so the active-channel rule uses the correct denominator for a Flongle, MinION or PromethION flow cell. When the project is linked to a sequencing position, the live acquisition state reported by MinKNOW is shown in the interface and is used to suppress the run-not-started rule while the instrument is still preparing. The same summary statistics that post-run tools such as NanoPlot {nanoplot} and pycoQC {pycoqc} report from a finished run are shown while the run is in progress (Fig. 2b).'));

add(H2('Notifications and alert history'));
add(P('Every alert, whether from a target rule or a run-health rule, carries a severity, a timestamp, a message and the values that triggered it. It is appended to a per-project log, pushed to any open browser session and passed to the configured notification channels: e-mail over SMTP, SMS through Twilio, a desktop notification on the host computer and a user message inside the MinKNOW interface of the linked sequencing position. A test button sends a message through every configured channel so that the delivery path can be checked before a run rather than discovered to be broken during one. The alert history is browsable and filterable in the interface (Fig. 2c) and the log file is plain JSON lines so that it can be consumed by other software.'));

add(H2('Laboratory results and statistics'));
add(P('For any target the user can record the result of a reference test, in practice a qPCR assay, as positive, negative or inconclusive together with the cycle threshold (Ct), a sample identifier and a date. nanoCAS then reports, for each target, whether sequencing detected it (that is, whether any of its alert rules fired), the time from the first processed batch to the first alert, and whether the sequencing result agrees with the laboratory result (Fig. 2d). Across targets with a Ct value it fits an ordinary least-squares regression of log10 reads per million on Ct, reports the slope, the coefficient of determination and a t-test p-value for the slope, and computes Spearman\'s rank correlation as a distribution-free check. A separate view pools all projects on the same server and reports, for each target, the positivity rate with a Wilson score interval {wilson}, the sensitivity and specificity of sequencing against the laboratory test, Cohen\'s kappa {cohen}, the median time to detection and [[an estimate of the highest Ct at which sequencing still detected the target||Check this description against the code in server/app/main/utils/stats.py and lab_results.py before submission so the manuscript states exactly how the Ct limit of detection is estimated.]]. These are the quantities that validation studies of sequencing-based diagnostics usually report, and computing them inside the application means that each run adds a row to the validation dataset instead of a line in a spreadsheet.'));

add(H2('Simulation and testing'));
add(P('nanoCAS includes a sequencer simulator that writes gzipped FASTQ batches and a sequencing summary in the same layout, naming scheme and timing as MinKNOW. Six scripted scenarios are provided: a clean run, a contamination that appears part way through, a low-abundance pathogen, a flow cell that loses pores, a run that stalls and a run that never starts. A demo project can be created in one click and comes with a replayed history so that the coverage plot, the feature alerts, the run-health alerts, the notification channels and the laboratory-result views are all populated without an instrument or any user data. The simulator is also the basis of the automated test suite, which contains 123 tests including an end-to-end test that runs real minimap2 and samtools on simulated reads, and which is executed on every change by continuous integration.'));

add(H2('Deployment'));
add(P('nanoCAS runs on Linux and macOS. A setup script creates a Python environment, installs the dependencies and builds the front end, and a Docker image is provided for a container deployment. The only external requirements are minimap2 and samtools, plus Kraken2 or Centrifuge if those classifiers are used. Because the whole system is one process with local storage, it can run on the laptop that controls a MinION in the field as easily as on a server in a diagnostic laboratory.'));

add(H2('Case study data'));
add(H3('Case study 1: Xylella fastidiosa in naturally infected plant material'));
add(P('[[Plant samples naturally infected with _X. fastidiosa_ were collected from [host species, location, year]. DNA was extracted from [tissue type] with [kit or method]. Each extract was tested by real-time PCR using the assay of Harper et al. {harper} on a [instrument], and the number of genome copies per reaction was estimated from a standard curve of [describe standard]. Sequencing libraries were prepared with the [ligation or rapid] kit [SQK-xxx] and sequenced on [MinION / GridION] with [flow cell type, chemistry] for [duration]. Basecalling was performed by MinKNOW with [Dorado version, model] and reads were written to the fastq_pass directory watched by nanoCAS.||Tim: please fill in the sample origin, number of samples (the draft has an action item on this), extraction method, qPCR instrument, standard curve details, library kit, flow cell, run length and basecalling model. Also state whether samples were multiplexed with barcodes; if so, nanoCAS was run on each barcode directory separately.]]'));
add(P('[[A nanoCAS project was created for each sample with the _X. fastidiosa_ [subspecies, strain, accession] genome and the [host] genome as reference sequences. Alert rules were set to [depth, breadth, read count and read fraction thresholds]. The qPCR result and Ct of each sample were entered as laboratory results.||State the exact reference sequences and thresholds used. I suggest keeping the same thresholds for every sample so that time to alert is comparable across the Ct range, and reporting a sensitivity analysis over a few threshold values in a supplementary table.]]'));
add(H3('Case study 2: Brucella abortus in a bovine background with adaptive sampling'));
add(P('[[Genomic DNA of _B. abortus_ [strain] was spiked into genomic DNA extracted from [bull tissue or semen?] at [n] levels, from [highest] to [lowest] [copies or ng per reaction, or percentage of input], with the same bovine background in every sample. Libraries were prepared with [kit] and sequenced on [device] with [flow cell]. Each run began with 30 minutes of sequencing without adaptive sampling to establish a baseline, after which adaptive sampling was enabled in MinKNOW with the _B. abortus_ reference genome [accession] as the enrichment target and no BED file, so that the whole genome was enriched. Sequencing continued for three days.||Please fill in the strain, the background sample type ("bull samples" in your notes), the number and range of spike levels, the kit and flow cell, and how the spike levels were separated (one flow cell per level, or barcodes on one flow cell). If barcodes were used with adaptive sampling on one flow cell, say so explicitly because the enrichment then competes across levels.]]'));
add(P('[[Each level was monitored as a separate nanoCAS project with the _B. abortus_ genome and the _Bos taurus_ genome as reference sequences and alert rules of [thresholds]. The run-health monitor was left at its default settings. Enrichment by adaptive sampling was quantified as the ratio of the _B. abortus_ read fraction after adaptive sampling was enabled to the read fraction in the 30-minute baseline.||Your notes mention the ASMR R package (github.com/coadunate/asmr) for adaptive-sampling analysis. If it was used to compute enrichment, describe it here and cite it. Otherwise the ratio of read fractions that nanoCAS records is sufficient and needs no extra tool.]]'));
add(H3('Analysis'));
add(P('[[For both case studies, time to alert was taken from the nanoCAS alert log as the interval between the first processed batch and the first alert on the pathogen target. Depth, breadth, read count and read fraction at fixed time points were taken from the coverage time series. Regression of log10 reads per million on Ct, Spearman correlation, sensitivity, specificity and Cohen\'s kappa were computed by nanoCAS as described above and checked independently in R [version].||If you also produced figures in R, cite R and the packages used and deposit the scripts with the data.]]'));

// Results and discussion -----------------------------------------------------
add(H1('Results and discussion'));
add(H2('Comparison with existing real-time tools'));
add(P('Table 1 places nanoCAS next to the real-time tools described in the Background. All of them process reads while the run is in progress and most of them draw coverage or taxonomy plots. The features that separate nanoCAS from the others are the ones that concern what happens after the plot is drawn: user-defined thresholds that fire once and are delivered to a person, rules about the instrument rather than the sample, a classifier that can be swapped without changing the rules, a place to record the confirmatory test, and a simulator that lets the whole system be demonstrated and tested without hardware. minoTour comes closest, as it can e-mail the user when amplicon coverage milestones are reached in its ARTIC workflow, but it has no general threshold rules, no instrument rules and no laboratory-result view, and it requires a Django, Celery and Redis deployment. nanoCAS is deliberately narrower than MARTi or Nanometa Live in what it reports about a sample. It does not attempt to describe a whole community. It answers the question a diagnostic laboratory asks, which is whether a named organism or gene is present above a stated level, and it says so as soon as the answer is known.'));

add(H2('Case study 1: Xylella fastidiosa in naturally infected plant material'));
add(P('_X. fastidiosa_ is a xylem-limited bacterium that causes disease in olive, grapevine, citrus and many other hosts and is a quarantine organism in much of the world {sicard}. Detection in plant tissue is difficult because the bacterium is unevenly distributed in the plant and present at low titre relative to host DNA, and the current reference method is qPCR {harper}. Direct nanopore sequencing has detected _X. fastidiosa_ in naturally infected material but was reported to succeed only at high bacterial load, with amplicon sequencing needed for low-titre samples {faino}. This case study asks a different question. Given a set of naturally infected samples spanning a range of qPCR Ct values, how does the point at which nanoCAS raises an alert, and the depth and breadth it reports, relate to the amount of pathogen DNA that qPCR measured?'));
add(P('[[Across the [n] samples, qPCR Ct values ranged from [min] to [max], corresponding to [range] genome copies per reaction (Table 3). nanoCAS raised an alert on the _X. fastidiosa_ target in [k] of [n] samples. Time to first alert ranged from [x] minutes in the sample with the lowest Ct to [y] hours in the sample with the highest Ct that was detected, and the [m] samples with Ct above [value] produced no alert within the [duration] run (Fig. 3a).||Results placeholder. Fig. 3a should show time to first alert against Ct, one point per sample, with undetected samples marked at the top of the axis.]]'));
add(P('[[Read yield tracked the qPCR result closely. log10 reads per million assigned to _X. fastidiosa_ decreased linearly with Ct (slope [b], R2 [r2], p [p], Spearman rho [rho], Fig. 3b), which is the relationship expected when both measurements scale with the number of pathogen genomes in the extract. Breadth of coverage was a less useful predictor: it saturated near 100% in the [k] samples with Ct below [value] and fell steeply above that, so it separated strong positives from weak ones but did not rank samples within either group (Fig. 3c). Mean depth behaved like read count because the reference genome is fixed, and read fraction removed the effect of differences in total yield between runs, which made it the most comparable metric across flow cells.||Your draft asks whether depth or breadth is the better metric for this correlation. This paragraph proposes an answer that follows from how the metrics are defined: read count and read fraction are proportional to pathogen genome copies over the whole range, breadth saturates. Confirm with the data and adjust the wording. If you want a single recommendation for a "standard", read fraction with a fixed threshold is the most defensible because it is independent of run yield.]]'));
add(P('[[The practical consequence is a rule that a laboratory can set in advance. With a read-fraction threshold of [value], nanoCAS detected every sample with Ct up to [value] within [t] hours, and the alert arrived a median of [h] hours before the end of the run. For a diagnostic laboratory that runs a flow cell for a fixed period, this is the difference between reporting at the end of the day and reporting at lunch.||Adjust once the numbers are in. If some samples were only detected late or not at all, say so plainly and relate it to the Ct limit reported by Faino et al. for direct sequencing.]]'));

add(H2('Case study 2: Brucella abortus in a bovine background with adaptive sampling'));
add(P('Bovine brucellosis, caused by _B. abortus_, is a notifiable zoonosis that is controlled by test-and-slaughter programs in most countries {olsen}. The organism is present at low levels in tissues and fluids against an overwhelming excess of host DNA, so direct sequencing without enrichment yields few pathogen reads. Adaptive sampling offers a way to shift the balance during the run, because reads that do not map to the pathogen genome are ejected from the pore after the first few hundred bases and the pore is freed for the next molecule {readfish,martin}. This case study asks how far down a dilution series nanoCAS can raise an alert, how much sooner the alert arrives when adaptive sampling is enabled, and whether the run-health monitor adds anything over a three-day run.'));
add(P('[[In the 30-minute baseline without adaptive sampling, _B. abortus_ reads made up [x]% of reads at the highest spike level and were [not observed / observed at y%] at the lowest (Table 4). After adaptive sampling was enabled, the _B. abortus_ read fraction rose by a factor of [fold] to [fold] across the levels (Fig. 4a), in line with the enrichment reported for low-abundance species in mock communities {martin}. nanoCAS raised an alert at every level down to [lowest detected level], with time to alert increasing from [t1] at the highest level to [t2] at the lowest (Fig. 4b). At [level(s) below that], no alert was raised within three days, and the read count at the end of the run was [n] reads, below the [threshold] read threshold.||Results placeholder. Fig. 4a: read fraction over time for each level with the 30-minute mark indicated. Fig. 4b: time to alert against spike level on a log axis. Table 4: per level, baseline fraction, post-AS fraction, enrichment factor, time to alert, final depth and breadth.]]'));
add(P('[[Breadth of coverage at the end of the run was [value] at the highest level and [value] at the lowest detected level, so at low input the reads were spread thinly across the 3.3 Mb genome rather than concentrated. This is the situation in which feature-level rules are informative: a depth threshold over a single marker such as the IS711 element or the _bcsp31_ gene would have fired [earlier / later] than the whole-genome read threshold. Time to alert followed the spike level approximately as the reciprocal of concentration, which is what a Poisson model of read arrival predicts and which gives a simple way to estimate, for a given input, how long a run must be before a negative result can be trusted.||Only keep the IS711 / bcsp31 sentence if a feature rule was actually configured on those loci. If it was not, either run it on the replayed data (nanoCAS can replay a completed run from its fastq_pass directory) or delete the sentence. The Poisson statement follows from the poisson_detection_probability function in stats.py; report the fitted relationship if you want to keep it.]]'));
add(P('[[Over the three-day runs the run-health monitor raised [n] pore-decline alerts and [m] data-stalled alerts (Table 4). The pore-decline alert fired at [time] when the number of channels producing reads fell below half of the run peak, roughly [hours] before the yield in the last hour dropped to a level at which no further detection would have been possible. In one run a stall alert was triggered by [cause, e.g. the host computer suspending] and cleared when data resumed, with a recovery entry in the log.||Placeholder. If there was nothing notable in the run-health log, say so in one sentence: it is still useful to report that the monitor ran for three days with no false alarms.]]'));

add(H2('Limitations'));
add(P('nanoCAS starts at basecalled reads. It does not basecall and it does not act at the signal level, so adaptive sampling is configured in MinKNOW or in a dedicated tool and nanoCAS observes its effect rather than controlling it. It does not assemble genomes, call variants or detect antimicrobial resistance genes, and a laboratory that needs those results will run a separate pipeline after the run. The taxonomic view is a table rather than a tree, and the statistics across runs are descriptive. The case studies use one pathogen in one background each and were not designed as validation studies with negative controls at every level, so the sensitivity and specificity that nanoCAS reports for them should be read as a demonstration of the feature rather than as performance claims for _X. fastidiosa_ or _B. abortus_ detection. [[Finally, the alert thresholds are chosen by the user, and the appropriate values depend on the organism, the reference and the background, which is why nanoCAS records the reference result alongside the sequencing result: the intended use is that a laboratory tunes its thresholds on its own validation runs.||Consider whether to add negative-control samples (uninfected plant, unspiked bovine DNA) to each case study before submission. Reviewers of diagnostic software often ask for them, and they let you report specificity with a denominator.]]'));

// Conclusions ----------------------------------------------------------------
add(H1('Conclusions'));
add(P('nanoCAS makes a nanopore sequencing run behave like a monitored instrument. A laboratory states in advance what a positive result is, in terms of depth, breadth, reads or read fraction over an organism or a gene, and is told when that result is reached. It is also told when the run itself is failing. The classifier underneath is a choice, not a commitment, and the confirmatory test result lives next to the sequencing result so that every run contributes to the validation of the rules. In naturally infected plant material the time to alert and the read yield followed the qPCR cycle threshold, and in a dilution series with adaptive sampling nanoCAS detected the pathogen [[down to [level]||Fill in.]] and flagged pore decline during a three-day run. The software is open source, runs on a laptop and can be tried in full without a sequencer.'));

// Availability -----------------------------------------------------------------
add(H1('Availability and requirements'));
add(Bullet('**Project name:** nanoCAS (Nanopore Classification and Alerting System)'));
add(Bullet('**Project home page:** https://github.com/tayabsoomro/nanoCAS'));
add(Bullet('**Operating system(s):** Linux, macOS (Docker image provided)'));
add(Bullet('**Programming language:** Python 3.10 or later (back end), TypeScript and React (front end)'));
add(Bullet('**Other requirements:** minimap2 2.26 or later, samtools 1.19 or later, and Node.js 18 or later to build the front end. Kraken2 or Centrifuge are optional, as is a Twilio account for SMS'));
add(Bullet('[[**License:** Creative Commons Attribution 4.0 (CC BY 4.0)||The repository currently declares CC-BY-4.0 in pyproject.toml. CC BY is a content licence rather than a software licence, and reviewers sometimes query it. Consider switching the code to MIT, Apache 2.0 or GPL-3.0 before submission and updating this line.]]'));
add(Bullet('**Any restrictions to use by non-academics:** none'));

// Abbreviations ----------------------------------------------------------------
add(H1('Abbreviations'));
add(P('API: application programming interface. BAM: binary alignment map. Ct: cycle threshold. GFF3: generic feature format version 3. ONT: Oxford Nanopore Technologies. qPCR: quantitative polymerase chain reaction. RPM: reads per million. SMS: short message service. SMTP: simple mail transfer protocol.'));

// Declarations ------------------------------------------------------------------
add(H1('Declarations'));
add(H2('Ethics approval and consent to participate'));
add(P('[[Not applicable. No human participants were involved. [Bovine DNA was obtained from ... under animal use protocol ... approved by ...]||If the bovine samples came from live animals, state the animal care committee approval number. If they were from an existing archived collection or a commercial source, say so and state that no animals were handled for this study.]]'));
add(H2('Consent for publication'));
add(P('Not applicable.'));
add(H2('Availability of data and materials'));
add(P('[[The nanoCAS source code is available at https://github.com/tayabsoomro/nanoCAS and the version used in this study is archived at [Zenodo DOI]. Sequencing reads for both case studies are deposited in the NCBI Sequence Read Archive under BioProject [PRJNA...]. The nanoCAS project directories, including coverage time series, alert logs and laboratory results, and the analysis scripts are available at [Zenodo DOI].||Create a Zenodo release of the repository at submission so that the software has a citable DOI, and deposit reads plus the nanoCAS project directories. BMC requires this statement, and reviewers of software papers usually test the tool on the deposited data.]]'));
add(H2('Competing interests'));
add(P('The authors declare that they have no competing interests.'));
add(H2('Funding'));
add(P('[[This work was supported by [funder, grant number]. The funders had no role in the design of the study, in the collection, analysis and interpretation of data, or in writing the manuscript.||Fill in.]]'));
add(H2('Authors\' contributions'));
add(P('[[TS and MGL conceived the project. TS and SH implemented the software. TJD provided the biological samples and performed the laboratory experiments. TS analysed the case-study data. TS wrote the first draft. All authors reviewed and edited the manuscript and approved the final version.||Adjust to match who did what, especially data analysis for the case studies and who ran the sequencing.]]'));
add(H2('Acknowledgements'));
add(P('[[We thank [names] for [sequencing support / sample collection / helpful discussion].||Fill in or delete.]]'));

// References ------------------------------------------------------------------
// (numbering is resolved after all text has been generated: see below)

// Figure legends ----------------------------------------------------------------
const figuresAndTables = [];
figuresAndTables.push(H1('Figure legends'));
figuresAndTables.push(P('**Figure 1. Architecture of nanoCAS.** Basecalled reads and the sequencing summary written by MinKNOW, or by the built-in simulator, are picked up by a directory watcher. Each batch of reads is passed to the configured classifier plug-in and the summary is passed to the run-health rules. Target metrics, feature metrics and run-health conditions are evaluated after every batch, and each alert is logged once, shown in the web interface and delivered through the configured notification channels. Laboratory results entered by the user are compared with the sequencing result within the same project.'));
figuresAndTables.push(P('**Figure 2. The nanoCAS interface, shown on simulated runs.** (a) Coverage tab with the current metrics per target, the thresholds that were reached and the coverage-over-time plot with the threshold line. (b) Run-health tab for a simulated failing flow cell, with the summary statistics, quality and length distributions and pore activity that feed the run-health rules. (c) Alert history and the configured target and run-health rules. (d) Laboratory-result view comparing the sequencing result with a recorded qPCR result and the relationship between read yield and Ct. [[All panels were captured from demo projects created without a sequencer.||Replace with screenshots from the real case studies if you prefer; the simulated ones are included so the draft is complete.]]'));
figuresAndTables.push(P('[[**Figure 3. Case study 1: _Xylella fastidiosa_ in naturally infected plant material.** (a) Time from the first processed batch to the first nanoCAS alert against the qPCR Ct of each sample. Samples with no alert are shown at the top of the axis. (b) log10 reads per million assigned to _X. fastidiosa_ against Ct with the least-squares fit and its 95% confidence band. (c) Breadth of coverage of the _X. fastidiosa_ genome at the end of the run against Ct.||Figure to be produced from the case-study data. nanoCAS exports the coverage time series (coverage.csv) and the alert log (alerts.jsonl) per project; the read-yield versus Ct plot in the Lab results tab can also be exported directly.]]'));
figuresAndTables.push(P('[[**Figure 4. Case study 2: _Brucella abortus_ spiked into a bovine background and sequenced with adaptive sampling.** (a) _B. abortus_ read fraction over run time for each spike level, with the point at which adaptive sampling was enabled marked. (b) Time to first nanoCAS alert against spike level on a logarithmic axis. (c) Active channels over the three-day run with the pore-decline alert and its recovery marked.||Figure to be produced from the case-study data.]]'));

figuresAndTables.push(Break());
figuresAndTables.push(P('**Figure 1**'));
figuresAndTables.push(image(__dirname + '/fig1_architecture.png', 6.5));
figuresAndTables.push(Break());
figuresAndTables.push(P('**Figure 2**'));
figuresAndTables.push(image(__dirname + '/fig2_interface.png', 6.5));

// Tables ---------------------------------------------------------------------------
figuresAndTables.push(Break());
figuresAndTables.push(H1('Tables'));
figuresAndTables.push(P('**Table 1. Real-time nanopore analysis tools and the functions that nanoCAS adds.** Yes or no indicates whether the function is present in the published version of each tool. [[Please verify each cell against the current documentation of each tool before submission, since several of them are actively developed.||Verify the table.]]'));
figuresAndTables.push(table(
  ['Tool', 'Real-time analysis', 'User-defined threshold alerts with notification', 'Instrument-health rules', 'Classifier can be swapped', 'Records reference test result', 'Runs without a sequencer'],
  [
    ['MinKNOW live alignment {ont}', 'Yes', 'No', 'No (plots only)', 'No', 'No', 'No'],
    ['EPI2ME wf-metagenomics {ont}', 'Yes', 'No', 'No', 'Kraken2 or minimap2', 'No', 'No'],
    ['RAMPART {rampart}', 'Yes', 'No', 'No', 'No', 'No', 'No'],
    ['minoTour {minotour}', 'Yes', 'E-mail on ARTIC coverage milestones', 'Metrics shown, no rules', 'No', 'No', 'No'],
    ['BoardION {boardion}', 'Yes', 'No', 'Metrics shown, no rules', 'Not applicable', 'No', 'No'],
    ['MARTi {marti}', 'Yes', 'No', 'No', 'Several built in', 'No', 'No'],
    ['Nanometa Live {nanometa}', 'Yes', 'Highlights listed pathogens', 'No', 'No', 'No', 'No'],
    ['NanoOK RT {nanook}', 'Yes', 'No', 'No', 'No', 'No', 'No'],
    ['BugSeq {bugseq}', 'No (after run)', 'No', 'No', 'No', 'No', 'Not applicable'],
    ['nanoCAS (this work)', 'Yes', 'Yes: depth, breadth, reads, fraction, GFF features; e-mail, SMS, desktop, MinKNOW', 'Yes: seven rules with hysteresis', 'Yes: minimap2, Kraken2, Centrifuge, user plug-ins', 'Yes: qPCR Ct, agreement, regression', 'Yes: built-in simulator'],
  ],
  [1500, 1000, 1900, 1400, 1400, 1200, 960]));
figuresAndTables.push(P(''));
figuresAndTables.push(P('**Table 2. Run-health rules evaluated by nanoCAS.** All thresholds are configurable per project. A rule fires after its condition has held for two consecutive evaluations (default interval 30 s) and logs a recovery entry when it clears.'));
figuresAndTables.push(table(
  ['Rule', 'Fires when', 'Default'],
  [
    ['Run not started', 'No data file and no summary rows have appeared since monitoring started, unless MinKNOW reports that the position is still preparing', '15 min'],
    ['Data stalled', 'No new data file or summary rows for the stall timeout after data has been seen', '30 min'],
    ['Low median Q', 'Median mean Q-score of the most recent reads is below the floor', 'Q 9 over 2,000 reads'],
    ['Pore decline', 'Channels producing reads in the last 10 min fall below a fraction of the run peak', '50% of peak'],
    ['Low active channels', 'Recently active channels are below a fraction of the flow-cell channel count', '10% of flow cell'],
    ['Low pass rate', 'Fraction of recent reads passing the quality filter is below the floor', '50%'],
    ['Short reads', 'Median read length of the recent window is below the floor (off by default)', 'off'],
  ],
  [1800, 5560, 2000]));
figuresAndTables.push(P(''));
figuresAndTables.push(P('[[**Table 3. Case study 1: samples, qPCR results and nanoCAS results.** One row per sample: sample identifier, host and tissue, qPCR Ct, estimated genome copies per reaction, total reads in the run, reads assigned to _X. fastidiosa_, reads per million, final depth, final breadth, time to first alert, and whether the sequencing and qPCR results agree.||Table to be produced from the case-study data. The Lab results tab and the across-runs view in nanoCAS provide most of these columns.]]'));
figuresAndTables.push(P('[[**Table 4. Case study 2: spike levels, enrichment and nanoCAS results.** One row per spike level: input of _B. abortus_ DNA, baseline read fraction in the first 30 minutes, read fraction after adaptive sampling was enabled, enrichment factor, time to first alert, final depth and breadth, and run-health alerts raised during the run.||Table to be produced from the case-study data.]]'));

// ---------------------------------------------------------------------------
// Assemble: references must be numbered after all citing text (including tables) is built.
// ---------------------------------------------------------------------------
const refSection = [];
refSection.push(H1('References'));
refOrder.forEach((k, i) => refSection.push(new Paragraph({ spacing: { after: 80, line: 300 }, indent: { left: 500, hanging: 500 }, children: [new TextRun({ text: `${i + 1}. `, font: FONT, size: 20 }), ...fmt(REFS[k].replace(/(Xylella fastidiosa|Brucella spp\.|B\. abortus|B\. melitensis)/g, '_$1_'), { size: 20 })] })));
const unused = Object.keys(REFS).filter(k => !refOrder.includes(k));
refSection.push(P(`[[Reference list.||All references were assembled from the published record but must be verified against the sources before submission, in particular author lists beyond the sixth author, page ranges (MARTi end page is missing) and access dates for the two web references. Vancouver style with numbering in order of first citation, as BMC requires. Unused keys in the generator: ${unused.join(', ') || 'none'}.]]`));

const doc = new Document({
  creator: 'nanoCAS authors',
  title: 'nanoCAS manuscript draft',
  comments: { children: comments },
  numbering: {
    config: [
      { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 300 } } } }] },
      { reference: 'refs', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 400 } } } }] },
    ],
  },
  styles: { default: { document: { run: { font: FONT, size: SIZE } } } },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 18 })] })] }) },
    children: [...body, ...refSection, Break(), ...figuresAndTables],
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(__dirname + '/nanoCAS_BMC_Bioinformatics_draft.docx', buf);
  console.log('written; references:', refOrder.length, 'comments:', comments.length);
});
