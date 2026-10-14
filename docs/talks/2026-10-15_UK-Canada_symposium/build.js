/* nanoCAS talk for the Joint UK–Canada Symposium, 15 October 2026. AAFC template look. */
const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const sharp = require('sharp');
const Fi = require('react-icons/fi');
const { applyTheme } = require('/root/.claude/skills/synced/ac9bbaba-3e82-495c-af68-f5450ea1ed53_ad0f772d-9d9f-400c-b442-5a597b120479/pptx/scripts/apply_theme.js');

const A = p => path.join(__dirname, 'assets', p);
const OUT = path.join(__dirname, 'nanoCAS_UK-Canada_Symposium_2026-10-15.pptx');

const THEME = {
  name: 'nanoCAS AAFC',
  headFontFace: 'Arial',
  bodyFontFace: 'Arial',
  colors: {
    dk1: '1A1A1A', lt1: 'FFFFFF', dk2: '1E3E2F', lt2: 'EEF2EF',
    accent1: '1E3E2F', accent2: '4F7A63', accent3: 'B5473A', accent4: '6B7A82', accent5: 'C9D6CD', accent6: 'E9B44C',
    hlink: '1E3E2F', folHlink: '4F7A63',
  },
};

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE'; // 13.333 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.author = 'Tayab Soomro';
pres.title = 'nanoCAS: a real-time classification and alerting system for pathogen detection during nanopore sequencing';
const C = pres.SchemeColor;
const W = 13.333, H = 7.5;
const BANNER_H = 0.645, FOOTER_H = 0.63;
const GREEN = THEME.colors.dk2, RED = THEME.colors.accent3, GREY = THEME.colors.accent4, MOSS = THEME.colors.accent2, TINT = THEME.colors.lt2;

// ---- icons -----------------------------------------------------------------------------------------
async function icon(name, colorHex, px = 256) {
  const el = React.createElement(Fi[name], { color: '#' + colorHex, size: px, strokeWidth: 1.6 });
  const svg = renderToStaticMarkup(el);
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return 'image/png;base64,' + buf.toString('base64');
}

// ---- layouts ---------------------------------------------------------------------------------------
pres.defineSlideMaster({
  title: 'TITLE', background: { color: 'FFFFFF' },
  objects: [
    { image: { x: 0, y: 0, w: W, h: 2.49, path: A('banner_title.png') } },
    { image: { x: 0, y: H - FOOTER_H, w: W, h: FOOTER_H, path: A('footer.png') } },
    { placeholder: { options: { name: 'title', type: 'title', x: 1.2, y: 2.85, w: 10.93, h: 1.1, align: 'center', bold: true, fontSize: 40, color: C.text1, margin: 0 } } },
    { placeholder: { options: { name: 'body', type: 'body', x: 1.5, y: 3.95, w: 10.33, h: 1.0, align: 'center', fontSize: 22, color: C.text1, margin: 0 } } },
  ],
});
pres.defineSlideMaster({
  title: 'CONTENT', background: { color: 'FFFFFF' },
  objects: [
    { image: { x: 0, y: 0, w: W, h: BANNER_H, path: A('banner_slim.png') } },
    { image: { x: 0, y: H - FOOTER_H, w: W, h: FOOTER_H, path: A('footer.png') } },
    { placeholder: { options: { name: 'title', type: 'title', x: 0.9, y: 0.85, w: 11.53, h: 0.7, align: 'center', bold: true, fontSize: 28, color: C.text1, margin: 0 } } },
  ],
  slideNumber: { x: 12.3, y: H - FOOTER_H - 0.35, w: 0.6, h: 0.3, fontSize: 10, color: GREY, align: 'right' },
});
pres.defineSlideMaster({
  title: 'STATEMENT', background: { color: 'FFFFFF' },
  objects: [
    { image: { x: 0, y: 0, w: W, h: BANNER_H, path: A('banner_slim.png') } },
    { image: { x: 0, y: H - FOOTER_H, w: W, h: FOOTER_H, path: A('footer.png') } },
    { placeholder: { options: { name: 'title', type: 'title', x: 0.9, y: 2.4, w: 11.53, h: 1.6, align: 'center', bold: true, fontSize: 32, color: C.text1, margin: 0, valign: 'middle' } } },
    { placeholder: { options: { name: 'body', type: 'body', x: 2.0, y: 4.15, w: 9.33, h: 0.9, align: 'center', fontSize: 20, color: C.text2, margin: 0, valign: 'top' } } },
  ],
  slideNumber: { x: 12.3, y: H - FOOTER_H - 0.35, w: 0.6, h: 0.3, fontSize: 10, color: GREY, align: 'right' },
});

const text = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, fontSize: 16, color: C.text1, ...o });
const caption = (s, t, o) => text(s, t, { fontSize: 12, color: GREY, ...o });
const box = (s, x, y, w, h, fill, o = {}) => s.addShape(pres.ShapeType.roundRect, { x, y, w, h, fill: { color: fill }, line: { color: fill, width: 0 }, rectRadius: 0.08, ...o });

(async () => {
pres.addSection({ title: 'Talk' });

// 1 Title -------------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'TITLE', sectionTitle: 'Talk' });
  s.addText('nanoCAS', { placeholder: 'title' });
  s.addText('A real-time classification and alerting system\nfor pathogen detection during nanopore sequencing', { placeholder: 'body' });
  text(s, 'Plant Health, Environmental Surveillance, and Biosecurity: A Joint UK–Canada Symposium   ·   15 October 2026', { x: 1.0, y: 5.25, w: 11.33, h: 0.35, align: 'center', fontSize: 14, color: GREY });
  text(s, 'Tayab Soomro', { x: 1.0, y: 5.85, w: 11.33, h: 0.35, align: 'center', fontSize: 18, bold: true });
  text(s, 'Bioinformatics Study Leader, Agriculture and Agri-Food Canada', { x: 1.0, y: 6.2, w: 11.33, h: 0.35, align: 'center', fontSize: 14, color: GREY });
  s.addNotes('Thank you. I lead bioinformatics at the Brandon Research and Development Centre. I want to tell you about a small piece of software, but I want to start with the problem it came from, because the problem is the interesting part.\n\nPause. Let the title sit.');
}

// 2 The story -----------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('The answer was in the data at 11 pm. Nobody was there.', { placeholder: 'title' });
  // timeline
  const y = 3.6, x0 = 1.6, x1 = 11.7;
  s.addShape(pres.ShapeType.line, { x: x0, y, w: x1 - x0, h: 0, line: { color: GREY, width: 1.5 } });
  const pts = [
    { x: x0, t: 'Friday, 4 pm', d: 'A sample from a suspected\ninterception goes on the MinION.', c: GREY },
    { x: (x0 + x1) / 2, t: 'Friday, 11 pm', d: 'Enough reads to call the pathogen\nare already on the disk.', c: RED },
    { x: x1, t: 'Monday, 9 am', d: 'Someone opens the laptop\nand looks.', c: GREY },
  ];
  pts.forEach((p, i) => {
    s.addShape(pres.ShapeType.ellipse, { x: p.x - 0.13, y: y - 0.13, w: 0.26, h: 0.26, fill: { color: p.c }, line: { color: 'FFFFFF', width: 1.5 } });
    text(s, p.t, { x: p.x - 1.7, y: y - 0.95, w: 3.4, h: 0.4, align: 'center', fontSize: 18, bold: true, color: p.c === RED ? RED : C.text1 });
    text(s, p.d, { x: p.x - 1.8, y: y + 0.35, w: 3.6, h: 0.9, align: 'center', fontSize: 14, color: GREY, valign: 'top' });
  });
  text(s, 'Sixty hours between the answer existing and the answer being known.', { x: 1.5, y: 5.45, w: 10.33, h: 0.5, align: 'center', fontSize: 18, italic: true, color: C.text2 });
  s.addNotes('This is a composite of things that have happened to us and to colleagues. A run starts late on a Friday. Nanopore gives you reads continuously, so by late evening the evidence for the organism you were worried about is sitting in the FASTQ files. And then nothing happens until Monday, because the only way to find out was to look.\n\nThe technology delivered real time. The workflow threw it away.\n\nSlow down here. This is the whole talk in one slide.');
}

// 3 Real time is the point ---------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('Real time is the whole point of nanopore', { placeholder: 'title' });
  const rows = [
    { label: 'Short-read sequencing', fill: 0, note: 'Result at the end of the run' },
    { label: 'Nanopore sequencing', fill: 1, note: 'Reads arrive every few minutes, from the first minute' },
  ];
  const bx = 3.6, bw = 7.6, by0 = 2.3;
  rows.forEach((r, i) => {
    const y = by0 + i * 1.45;
    text(s, r.label, { x: 0.9, y: y, w: 2.6, h: 0.5, fontSize: 16, bold: true, valign: 'middle' });
    s.addShape(pres.ShapeType.rect, { x: bx, y: y + 0.05, w: bw, h: 0.4, fill: { color: TINT }, line: { color: 'C9D6CD', width: 1 } });
    if (r.fill === 0) {
      s.addShape(pres.ShapeType.rect, { x: bx + bw - 0.35, y: y + 0.05, w: 0.35, h: 0.4, fill: { color: GREEN }, line: { color: GREEN, width: 0 } });
    } else {
      for (let k = 0; k < 20; k++) s.addShape(pres.ShapeType.rect, { x: bx + 0.08 + k * 0.376, y: y + 0.1, w: 0.26, h: 0.3, fill: { color: GREEN }, line: { color: GREEN, width: 0 } });
    }
    caption(s, r.note, { x: bx, y: y + 0.55, w: bw, h: 0.35, fontSize: 13 });
  });
  s.addShape(pres.ShapeType.line, { x: bx, y: by0 + 2.95, w: bw, h: 0, line: { color: GREY, width: 1 } });
  text(s, 'run start', { x: bx, y: by0 + 3.02, w: 2, h: 0.3, fontSize: 12, color: GREY });
  text(s, 'run end', { x: bx + bw - 2, y: by0 + 3.02, w: 2, h: 0.3, fontSize: 12, color: GREY, align: 'right' });
  text(s, 'A positive sample can be called hours before the flow cell is spent. A negative one needs the whole run, and someone has to know which is which.', { x: 0.9, y: 6.05, w: 11.53, h: 0.6, align: 'center', fontSize: 15, color: C.text2, italic: true });
  s.addNotes('A quick reminder of why we use this platform for diagnostics at all. With short reads, the answer comes when the run finishes. With nanopore, reads land on disk every few minutes, so for a strongly positive sample the answer can exist within the first hour.\n\nThe catch is that someone has to be watching to benefit from that.');
}

// 4 Three ways the advantage is lost -----------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('Three ways the real-time advantage gets lost', { placeholder: 'title' });
  const cards = [
    { ic: 'FiEye', t: 'Someone has to watch', d: 'Live plots exist, but a plot does not decide anything. A person has to notice the line crossing a value they carry in their head.' },
    { ic: 'FiActivity', t: 'The instrument fails quietly', d: 'Pores die, a run never starts, output stalls. You find out when you come back, not when it happens.' },
    { ic: 'FiClipboard', t: 'The confirmation lives elsewhere', d: 'The qPCR result is in a spreadsheet. Comparing sequencing with the reference test is redone by hand, every study.' },
  ];
  const cw = 3.6, gap = 0.4, x0 = (W - (3 * cw + 2 * gap)) / 2, y0 = 2.0, ch = 3.9;
  for (let i = 0; i < cards.length; i++) {
    const c = cards[i], x = x0 + i * (cw + gap);
    box(s, x, y0, cw, ch, TINT);
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.35, y: y0 + 0.35, w: 0.8, h: 0.8, fill: { color: 'FFFFFF' }, line: { color: 'FFFFFF', width: 0 } });
    s.addImage({ data: await icon(c.ic, GREEN), x: x + 0.52, y: y0 + 0.52, w: 0.46, h: 0.46 });
    text(s, c.t, { x: x + 0.35, y: y0 + 1.4, w: cw - 0.7, h: 0.5, fontSize: 18, bold: true, color: C.text2 });
    text(s, c.d, { x: x + 0.35, y: y0 + 2.0, w: cw - 0.7, h: 1.7, fontSize: 14, color: C.text1, valign: 'top' });
  }
  s.addNotes('When we looked at how real-time nanopore data is actually used in a diagnostic setting, the advantage leaked away in three places.\n\nFirst, a plot is not a decision. Second, the sequencer itself can be the thing that fails, and it fails quietly. Third, the test you compare against, usually qPCR, is kept somewhere else entirely.\n\nTake one card at a time. No need to rush.');
}

// 5 What exists --------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('Good tools already exist. They all stop at the plot', { placeholder: 'title' });
  const tools = ['MinKNOW live alignment', 'EPI2ME workflows', 'RAMPART', 'minoTour', 'MARTi', 'Nanometa Live'];
  const cols = ['Live\nanalysis', 'Decide on\na threshold', 'Notify\na person', 'Watch the\ninstrument', 'Keep the\nqPCR result'];
  const rows = [
    ['Y', 'N', 'N', 'N', 'N'],
    ['Y', 'N', 'N', 'N', 'N'],
    ['Y', 'N', 'N', 'N', 'N'],
    ['Y', 'N', 'P', 'P', 'N'],
    ['Y', 'N', 'N', 'N', 'N'],
    ['Y', 'P', 'N', 'N', 'N'],
  ];
  const x0 = 1.0, y0 = 2.0, lw = 3.2, cw = 1.75, rh = 0.5;
  cols.forEach((c, j) => text(s, c, { x: x0 + lw + j * cw, y: y0 - 0.65, w: cw, h: 0.6, fontSize: 12, bold: true, color: GREY, align: 'center', valign: 'bottom' }));
  tools.forEach((t, i) => {
    const y = y0 + i * rh;
    if (i % 2 === 0) s.addShape(pres.ShapeType.rect, { x: x0 - 0.1, y: y - 0.02, w: lw + cols.length * cw + 0.2, h: rh, fill: { color: TINT }, line: { color: TINT, width: 0 } });
    text(s, t, { x: x0, y, w: lw, h: rh - 0.04, fontSize: 15, valign: 'middle' });
    rows[i].forEach((v, j) => {
      const cx = x0 + lw + j * cw + cw / 2;
      if (v === 'Y') s.addShape(pres.ShapeType.ellipse, { x: cx - 0.11, y: y + rh / 2 - 0.13, w: 0.22, h: 0.22, fill: { color: GREEN }, line: { color: GREEN, width: 0 } });
      else if (v === 'P') s.addShape(pres.ShapeType.ellipse, { x: cx - 0.11, y: y + rh / 2 - 0.13, w: 0.22, h: 0.22, fill: { color: 'FFFFFF' }, line: { color: GREEN, width: 1.5 } });
      else s.addShape(pres.ShapeType.ellipse, { x: cx - 0.05, y: y + rh / 2 - 0.07, w: 0.1, h: 0.1, fill: { color: 'C9D6CD' }, line: { color: 'C9D6CD', width: 0 } });
    });
  });
  const ly = y0 + tools.length * rh + 0.3;
  s.addShape(pres.ShapeType.ellipse, { x: x0, y: ly + 0.05, w: 0.2, h: 0.2, fill: { color: GREEN }, line: { color: GREEN, width: 0 } });
  caption(s, 'yes', { x: x0 + 0.3, y: ly, w: 0.8, h: 0.3, valign: 'middle' });
  s.addShape(pres.ShapeType.ellipse, { x: x0 + 1.1, y: ly + 0.05, w: 0.2, h: 0.2, fill: { color: 'FFFFFF' }, line: { color: GREEN, width: 1.5 } });
  caption(s, 'partly (ARTIC milestones, listed pathogens)', { x: x0 + 1.4, y: ly, w: 4.5, h: 0.3, valign: 'middle' });
  caption(s, 'From the published descriptions of each tool, 2021 to 2025. Any of these can be the classifier underneath what comes next.', { x: x0, y: ly + 0.5, w: 11.0, h: 0.35 });
  s.addNotes('I want to be fair to the field. These are good tools and we use several of them. MinKNOW will align during a run. minoTour, MARTi and Nanometa Live classify reads as they arrive and show you beautiful live reports.\n\nWhat none of them do is let a lab say, in advance, what a positive result is, and then tell a person when it happens. And none of them watch the sequencer for you, or keep the qPCR result alongside.\n\nSo the gap is not classification. The gap is what happens after the plot.');
}

// 6 The idea -----------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'STATEMENT', sectionTitle: 'Talk' });
  s.addText('So we did not build another classifier.\nWe built the layer that decides, and tells you.', { placeholder: 'title' });
  s.addText('nanoCAS: Nanopore Classification and Alerting System', { placeholder: 'body' });
  s.addNotes('That was the design decision. Do not compete with minimap2 or Kraken. Sit on top of whichever one the lab already trusts, and own the part nobody owned: the rule, the alert, the record.\n\nPause here before the next slide.');
}

// 7 How it works -------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('How it works', { placeholder: 'title' });
  const steps = [
    { ic: 'FiHardDrive', t: 'Sequencer writes', d: 'FASTQ batches and the\nsequencing summary,\nas MinKNOW already does' },
    { ic: 'FiSearch', t: 'nanoCAS classifies', d: 'minimap2 built in\nKraken2, Centrifuge\nor your own plug-in' },
    { ic: 'FiSliders', t: 'Rules you set', d: 'depth, breadth, reads, fraction\nper target or per gene (GFF)\nplus seven instrument rules' },
    { ic: 'FiBell', t: 'A person is told', d: 'e-mail, SMS, desktop\nand a MinKNOW message,\nthe moment a rule fires' },
  ];
  const n = steps.length, cw = 2.75, gap = 0.35, x0 = (W - (n * cw + (n - 1) * gap)) / 2, y0 = 2.0;
  for (let i = 0; i < n; i++) {
    const st = steps[i], x = x0 + i * (cw + gap);
    box(s, x, y0, cw, 3.7, i === 3 ? GREEN : TINT);
    const dark = i === 3;
    s.addShape(pres.ShapeType.ellipse, { x: x + cw / 2 - 0.45, y: y0 + 0.4, w: 0.9, h: 0.9, fill: { color: 'FFFFFF' }, line: { color: 'FFFFFF', width: 0 } });
    s.addImage({ data: await icon(st.ic, GREEN), x: x + cw / 2 - 0.26, y: y0 + 0.59, w: 0.52, h: 0.52 });
    text(s, st.t, { x: x + 0.2, y: y0 + 1.5, w: cw - 0.4, h: 0.45, fontSize: 17, bold: true, align: 'center', color: dark ? 'FFFFFF' : C.text2 });
    text(s, st.d, { x: x + 0.2, y: y0 + 2.0, w: cw - 0.4, h: 1.5, fontSize: 13, align: 'center', color: dark ? 'FFFFFF' : C.text1, valign: 'top' });
    if (i < n - 1) s.addShape(pres.ShapeType.rightArrow, { x: x + cw + 0.05, y: y0 + 1.65, w: 0.25, h: 0.35, fill: { color: 'C9D6CD' }, line: { color: 'C9D6CD', width: 0 } });
  }
  caption(s, 'One Python process on the laptop that runs the MinION. No cloud, no account, nothing leaves the lab. Every alert fires once per run and is written to a log.', { x: 1.0, y: 6.05, w: 11.33, h: 0.5, align: 'center', fontSize: 13 });
  s.addNotes('Four steps. The sequencer writes files exactly as it does today, nothing changes on the instrument side. nanoCAS watches that folder, classifies each batch with whatever tool you chose, evaluates the rules you wrote down before the run, and when one fires it tells a person.\n\nThe rules are the important bit. Depth, breadth, read count, read fraction, on an organism or on a single gene from an annotation. And a second set of rules about the instrument itself.\n\nIt runs on the same laptop as MinKNOW. Nothing goes to a cloud.');
}

// 8 Coverage screenshot ------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('The moment a threshold is crossed', { placeholder: 'title' });
  s.addImage({ path: A('shot_coverage.png'), x: 2.52, y: 1.75, w: 8.3, h: 4.77 });
  s.addNotes('This is the coverage view on a simulated run. Three targets, a contaminant appears part way through, and the moment its depth and breadth cross the thresholds we set, the row turns red and the alert goes out. The dashed line on the chart is the threshold.\n\nEverything you see here was produced without a sequencer. I will come back to that.');
}
// 9 Run health ---------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('When the instrument is the problem', { placeholder: 'title' });
  s.addImage({ path: A('shot_runhealth.png'), x: 0.9, y: 1.85, w: 8.0, h: 3.7 });
  const rules = ['Run never started', 'Output stalled', 'Read quality collapsed', 'Pores declining', 'Too few active channels', 'Low pass rate', 'Reads too short'];
  text(s, 'Seven rules, evaluated every 30 seconds', { x: 9.3, y: 1.8, w: 3.3, h: 0.65, fontSize: 15, bold: true, color: C.text2, valign: 'top' });
  s.addText(rules.map((r, i) => ({ text: r, options: { bullet: { indent: 14 }, breakLine: i < rules.length - 1, paraSpaceAfter: 6 } })), { x: 9.3, y: 2.6, w: 3.3, h: 3.2, isTextBox: true, margin: 0, fontSize: 14, color: C.text1, valign: 'top' });
  caption(s, 'Each rule fires after two consecutive checks and logs a recovery when it clears, so a slow batch does not raise an alarm.', { x: 0.9, y: 6.0, w: 11.53, h: 0.5, align: 'center', fontSize: 13 });
  s.addNotes('This is the part that came out of painful experience. The same sequencing summary that you look at after a run with NanoPlot is read live, and seven rules watch it.\n\nThis simulated flow cell is dying: median quality has dropped to six, two percent of recent reads pass, thirty-nine channels left out of five hundred and twelve. On a real run you would get a text message when that started, not a surprise in the morning.');
}
// 10 Lab results -------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('Sequencing next to the test you already trust', { placeholder: 'title' });
  s.addImage({ path: A('shot_lab.png'), x: 3.07, y: 1.75, w: 7.2, h: 4.2 });
  text(s, 'Record the qPCR result and Ct per target. nanoCAS reports agreement, time to detection, and the relationship between Ct and read yield, and pools them across runs.', { x: 1.0, y: 6.05, w: 11.33, h: 0.5, align: 'center', fontSize: 13, color: GREY });
  s.addNotes('The third gap. For every target you can enter the result of the confirmatory test, in practice a qPCR Ct. nanoCAS then does the comparison that every validation paper does by hand: did sequencing agree, how long did it take, and how does read yield track Ct. Across runs it reports sensitivity, specificity and kappa.\n\nThe idea is that every routine run becomes a row in your validation dataset instead of a line in a spreadsheet.');
}

// 11 Case study 1 ------------------------------------------------------------------------------------
async function caseSlide(title, species, context, steps, question, notes) {
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText(title, { placeholder: 'title' });
  s.addText([{ text: species, options: { italic: true, bold: true } }, { text: context }], { x: 1.0, y: 1.7, w: 11.33, h: 0.6, isTextBox: true, margin: 0, fontSize: 15, color: C.text2, align: 'center' });
  const n = steps.length, cw = 3.4, gap = 0.45, x0 = (W - (n * cw + (n - 1) * gap)) / 2, y0 = 2.6;
  for (let i = 0; i < n; i++) {
    const st = steps[i], x = x0 + i * (cw + gap);
    box(s, x, y0, cw, 2.5, TINT);
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.3, y: y0 + 0.3, w: 0.55, h: 0.55, fill: { color: GREEN }, line: { color: GREEN, width: 0 } });
    text(s, String(i + 1), { x: x + 0.3, y: y0 + 0.3, w: 0.55, h: 0.55, fontSize: 16, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
    text(s, st.t, { x: x + 1.0, y: y0 + 0.32, w: cw - 1.25, h: 0.5, fontSize: 16, bold: true, color: C.text2, valign: 'middle' });
    text(s, st.d, { x: x + 0.3, y: y0 + 1.05, w: cw - 0.6, h: 1.3, fontSize: 13, color: C.text1, valign: 'top' });
    if (i < n - 1) s.addShape(pres.ShapeType.rightArrow, { x: x + cw + 0.1, y: y0 + 1.05, w: 0.25, h: 0.35, fill: { color: 'C9D6CD' }, line: { color: 'C9D6CD', width: 0 } });
  }
  box(s, 1.0, 5.45, 11.33, 1.0, 'FFFFFF', { line: { color: 'C9D6CD', width: 1, dashType: 'dash' } });
  text(s, question, { x: 1.3, y: 5.5, w: 9.3, h: 0.9, fontSize: 15, italic: true, color: C.text2, valign: 'middle' });
  box(s, 10.75, 5.75, 1.35, 0.4, RED);
  text(s, 'in progress', { x: 10.75, y: 5.75, w: 1.35, h: 0.4, fontSize: 11, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
  s.addNotes(notes);
}
await caseSlide('Case study 1: a plant pathogen, naturally infected tissue', 'Xylella fastidiosa',
  '   ·   quarantine organism, low titre in host tissue, qPCR is the reference method',
  [
    { t: 'Samples', d: 'Naturally infected plant material spanning a range of qPCR Ct values, each with absolute quantification.' },
    { t: 'Runs', d: 'Direct nanopore sequencing with nanoCAS watching, same thresholds for every sample.' },
    { t: 'Compare', d: 'Time to first alert, depth and breadth, and read yield against the Ct of each sample.' },
  ],
  'Which sequencing metric tracks the qPCR quantity best, and how early can a lab trust the alert?',
  'The first case study is the plant one, and the one closest to this audience. Xylella is a quarantine organism, unevenly distributed in the plant and present at low titre. The reference method is qPCR, so every sample has a Ct and an absolute quantity.\n\nWe sequence the same extracts directly, with nanoCAS watching and the same rules for every sample, and ask a simple question: which of depth, breadth, read count or read fraction tracks the qPCR quantity, and at what Ct does the alert stop arriving in time.\n\nThe runs are done, the analysis is being finished for the paper. If you have your own Ct series, this is exactly the kind of dataset we would like to compare against.');

// 12 Case study 2 ------------------------------------------------------------------------------------
await caseSlide('Case study 2: an animal pathogen, a dilution series', 'Brucella abortus',
  '   ·   notifiable zoonosis, spiked into bovine DNA at decreasing levels, adaptive sampling on',
  [
    { t: 'Dilution series', d: 'B. abortus genomic DNA in a constant bovine background, from easy to find to very rare.' },
    { t: 'Runs', d: '30 minutes of plain sequencing as a baseline, then three days with adaptive sampling enriching the pathogen genome.' },
    { t: 'Compare', d: 'How far down the series an alert still fires, how much sooner with enrichment, and what the instrument rules caught over three days.' },
  ],
  'How rare can the target be before real-time detection is no longer real time?',
  'The second case study is the One Health side. Brucella abortus, a notifiable zoonosis, spiked into bovine DNA at decreasing levels. The background is the same for every level, so the only thing changing is how rare the target is.\n\nEach run starts with thirty minutes of ordinary sequencing, then adaptive sampling is switched on in MinKNOW so that reads that are not Brucella are ejected from the pore. nanoCAS watches the whole three days. The questions are how far down the series it can still raise an alert, how much sooner it arrives with enrichment, and what the run-health rules caught over a three-day run, because flow cells do not last three days gracefully.');

// 13 Try it ----------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('Try it this afternoon, without a sequencer', { placeholder: 'title' });
  const items = [
    ['Built-in simulator', 'Writes FASTQ batches and a sequencing summary the way MinKNOW does. Six scenarios: clean run, contamination, rare pathogen, failing flow cell, stalled run, run that never starts.'],
    ['One-click demo projects', 'Every screen you saw today, including the alerts, the run-health rules and the qPCR comparison, populated on a laptop in a minute.'],
    ['Open source', 'Python and React, one process, runs on Linux and macOS. 123 automated tests. Plug in your own classifier with a short Python class.'],
  ];
  items.forEach(([t, d], i) => {
    const y = 1.9 + i * 1.35;
    s.addShape(pres.ShapeType.ellipse, { x: 1.0, y: y + 0.05, w: 0.5, h: 0.5, fill: { color: GREEN }, line: { color: GREEN, width: 0 } });
    text(s, String(i + 1), { x: 1.0, y: y + 0.05, w: 0.5, h: 0.5, fontSize: 15, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
    text(s, t, { x: 1.7, y, w: 6.6, h: 0.45, fontSize: 17, bold: true, color: C.text2, valign: 'middle' });
    text(s, d, { x: 1.7, y: y + 0.5, w: 6.6, h: 0.8, fontSize: 13, color: C.text1, valign: 'top' });
  });
  s.addImage({ path: A('qr_github.png'), x: 9.4, y: 2.0, w: 2.6, h: 2.6 });
  text(s, 'github.com/tayabsoomro/nanoCAS', { x: 8.7, y: 4.7, w: 4.0, h: 0.4, fontSize: 13, align: 'center', color: C.text2, bold: true });
  s.addNotes('I promised to come back to the simulator. Everything in this talk was shown on simulated runs because we wanted anyone to be able to see the whole system without a MinION and without their own data.\n\nThe simulator writes files exactly the way MinKNOW does, with scripted failure modes. So you can scan this code, run it on a laptop over coffee, and see a flow cell die on purpose.\n\nIt is open source. If your lab has a classifier you prefer, it plugs in with a short Python class.');
}

// 14 Collaboration ----------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: 'Talk' });
  s.addText('What we would like to explore together', { placeholder: 'title' });
  const asks = [
    { ic: 'FiCheckCircle', t: 'Validation on your samples', d: 'Run nanoCAS beside your qPCR on the organisms you regulate, and compare Ct against time to alert.' },
    { ic: 'FiTarget', t: 'Agreed thresholds', d: 'What depth, breadth or read fraction should count as positive for a given regulated pathogen? That is a shared question, not a software one.' },
    { ic: 'FiLayers', t: 'Shared classifiers', d: 'Plug in the databases and tools each side already trusts, and compare them on the same runs.' },
    { ic: 'FiGlobe', t: 'A pooled concordance dataset', d: 'Every run adds a row. Across two countries that becomes evidence a regulator can use.' },
  ];
  const cw = 5.5, chh = 1.75, gx = 0.45, gy = 0.4, x0 = (W - (2 * cw + gx)) / 2, y0 = 1.85;
  for (let i = 0; i < asks.length; i++) {
    const a = asks[i], x = x0 + (i % 2) * (cw + gx), y = y0 + Math.floor(i / 2) * (chh + gy);
    box(s, x, y, cw, chh, TINT);
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.3, y: y + 0.3, w: 0.7, h: 0.7, fill: { color: 'FFFFFF' }, line: { color: 'FFFFFF', width: 0 } });
    s.addImage({ data: await icon(a.ic, GREEN), x: x + 0.46, y: y + 0.46, w: 0.38, h: 0.38 });
    text(s, a.t, { x: x + 1.2, y: y + 0.25, w: cw - 1.45, h: 0.45, fontSize: 16, bold: true, color: C.text2, valign: 'middle' });
    text(s, a.d, { x: x + 1.2, y: y + 0.72, w: cw - 1.45, h: 0.95, fontSize: 13, color: C.text1, valign: 'top' });
  }
  caption(s, 'The session discussion is on validation, interpretation and implementation. These four are where we think that conversation can become concrete.', { x: 1.0, y: 6.2, w: 11.33, h: 0.4, align: 'center', fontSize: 12 });
  s.addNotes('This is a UK–Canada symposium, so let me end with what we would actually like to do with the people in this room.\n\nFirst, validation on your sample types, beside your qPCR. Second, thresholds. What should count as positive for a regulated pathogen is a question for diagnosticians and regulators, not for a software developer, and the tool makes it a concrete number you can argue about. Third, plug in the classifiers and databases each side trusts and compare them on identical runs. Fourth, pool the concordance data. Across two countries that becomes something a regulator can actually use.');
}

// 15 Thank you ---------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: 'STATEMENT', sectionTitle: 'Talk' });
  s.addText('Thank you', { placeholder: 'title' });
  s.addText('Sam Horovatin, Tim Dumonceaux, Matthew G. Links\nAgriculture and Agri-Food Canada   ·   University of Saskatchewan', { placeholder: 'body' });
  text(s, 'tayab.soomro@agr.gc.ca', { x: 2.0, y: 5.35, w: 9.33, h: 0.4, align: 'center', fontSize: 16, color: C.text2 });
  s.addImage({ path: A('qr_github.png'), x: 11.2, y: 0.85, w: 1.35, h: 1.35 });
  caption(s, 'github.com/tayabsoomro/nanoCAS', { x: 10.2, y: 2.22, w: 3.0, h: 0.3, align: 'center', fontSize: 10 });
  s.addNotes('Thank you. Sam built much of the application with me, Tim provided the samples and the laboratory work, and Matthew has been the scientific lead on nanopore work with me since the first MinION in his lab.\n\nI am happy to take questions now or in the discussion session.');
}


await pres.writeFile({ fileName: OUT });
await applyTheme(OUT, THEME);
console.log('wrote', OUT);
})().catch(e => { console.error(e); process.exit(1); });
