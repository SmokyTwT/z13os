// PDF : import (pdf.js) pour annoter des cours, export vectoriel (pdf-lib).
import { api, hashName } from './api.js';
import { newPage, PAPERS, templateShapes } from './model.js';
import { widthAt } from './render.js';

let pdfjsPromise = null;
function pdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import('../vendor/pdf.min.mjs').then((m) => {
      m.GlobalWorkerOptions.workerSrc = new URL('../vendor/pdf.worker.min.mjs', import.meta.url).href;
      return m;
    });
  }
  return pdfjsPromise;
}

// Ressources de pdf.js : polices standard, CMaps, décodeurs (JPEG 2000, JBIG2)
const RES = new URL('../vendor/pdfjs/', import.meta.url).href;
function docOptions(data) {
  return {
    data,
    isEvalSupported: false,
    cMapUrl: RES + 'cmaps/',
    cMapPacked: true,
    standardFontDataUrl: RES + 'standard_fonts/',
    wasmUrl: RES + 'wasm/',
    iccUrl: RES + 'iccs/',
  };
}

// Documents PDF ouverts, par carnet + fichier
const docs = new Map();

export async function openPdf(nbId, asset) {
  const key = nbId + '/' + asset;
  if (!docs.has(key)) {
    docs.set(key, (async () => {
      const lib = await pdfjs();
      const data = new Uint8Array(await api.getAsset(nbId, asset));
      return lib.getDocument(docOptions(data)).promise;
    })());
  }
  return docs.get(key);
}

export async function renderPdfPage(canvas, nbId, bg, scale) {
  const doc = await openPdf(nbId, bg.asset);
  const page = await doc.getPage(bg.page + 1);
  const vp = page.getViewport({ scale });
  const ctx = canvas.getContext('2d');
  const task = page.render({ canvasContext: ctx, viewport: vp, background: 'rgba(255,255,255,1)' });
  canvas._pdfTask = task;
  await task.promise;
}

// Importe un fichier PDF : l'enregistre dans le carnet, renvoie les pages créées.
export async function importPdf(nb, file) {
  const buf = await file.arrayBuffer();
  const name = await hashName(buf, 'pdf');
  await api.putAsset(nb.id, name, new Blob([buf], { type: 'application/pdf' }));
  const lib = await pdfjs();
  const doc = await lib.getDocument(docOptions(new Uint8Array(buf.slice(0)))).promise;
  const pages = [];
  for (let i = 0; i < doc.numPages; i++) {
    const pg = await doc.getPage(i + 1);
    const vp = pg.getViewport({ scale: 1 });
    pages.push(newPage({ w: Math.round(vp.width), h: Math.round(vp.height), template: 'blank', paper: 'white', bg: { type: 'pdf', asset: name, page: i } }));
  }
  docs.set(nb.id + '/' + name, Promise.resolve(doc));
  return pages;
}

// --- Export ---------------------------------------------------------------------
function rgb(hex) {
  const { rgb: mk } = window.PDFLib;
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return mk(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

function cssRgb(css) {
  // 'rgba(r,g,b,a)' → [couleur, opacité]
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (!m) return [rgb(css), 1];
  const [r, g, b, a = 1] = m[1].split(',').map(Number);
  return [window.PDFLib.rgb(r / 255, g / 255, b / 255), a];
}

function winAnsiSafe(text) {
  // Les polices standard PDF ne couvrent que l'alphabet latin (accents compris).
  return text.replace(/[^\x20-\x7e\xa0-\xffŒœ€’‘“”…–—\n]/g, '?');
}

export async function exportNotebook(nb, images) {
  const { PDFDocument, StandardFonts, LineCapStyle } = window.PDFLib;
  const out = await PDFDocument.create();
  out.setTitle(nb.title);
  out.setCreator('Smoky Notes');
  const font = await out.embedFont(StandardFonts.Helvetica);
  const bold = await out.embedFont(StandardFonts.HelveticaBold);
  const srcDocs = new Map();
  const embedded = new Map();

  for (const page of nb.pages) {
    let pg;
    if (page.bg && page.bg.type === 'pdf') {
      if (!srcDocs.has(page.bg.asset)) {
        const bytes = await api.getAsset(nb.id, page.bg.asset);
        srcDocs.set(page.bg.asset, await PDFDocument.load(bytes, { ignoreEncryption: true }));
      }
      const [copied] = await out.copyPages(srcDocs.get(page.bg.asset), [page.bg.page]);
      pg = out.addPage(copied);
    } else {
      pg = out.addPage([page.w, page.h]);
      const paper = PAPERS[page.paper] || PAPERS.white;
      pg.drawRectangle({ x: 0, y: 0, width: page.w, height: page.h, color: rgb(paper.bg) });
      const { lines, dots } = templateShapes(page);
      for (const [x1, y1, x2, y2, strong] of lines) {
        const [c, o] = cssRgb(strong ? paper.strong : paper.line);
        pg.drawLine({ start: { x: x1, y: page.h - y1 }, end: { x: x2, y: page.h - y2 }, thickness: 0.75, color: c, opacity: o });
      }
      const [dc, dop] = cssRgb(paper.strong);
      for (const [x, y, r] of dots) pg.drawCircle({ x, y: page.h - y, size: r, color: dc, opacity: dop });
    }
    const H = pg.getHeight();
    const sx = pg.getWidth() / page.w, sy = H / page.h;

    for (const it of page.items) {
      if (it.type === 'stroke') {
        const c = rgb(it.color);
        const op = it.tool === 'highlighter' ? 0.38 : 1;
        const p = it.points;
        if (p.length === 3) {
          pg.drawCircle({ x: p[0] * sx, y: H - p[1] * sy, size: (widthAt(it, p[2]) * sx) / 2, color: c, opacity: op });
          continue;
        }
        if (it.tool === 'highlighter' || it.tool === 'shape') {
          let d = `M ${p[0] * sx} ${p[1] * sy}`;
          for (let i = 3; i < p.length; i += 3) d += ` L ${p[i] * sx} ${p[i + 1] * sy}`;
          pg.drawSvgPath(d, { x: 0, y: H, borderColor: c, borderWidth: it.width * sx, borderOpacity: op, borderLineCap: LineCapStyle.Round });
        } else {
          for (let i = 3; i < p.length; i += 3) {
            pg.drawLine({
              start: { x: p[i - 3] * sx, y: H - p[i - 2] * sy },
              end: { x: p[i] * sx, y: H - p[i + 1] * sy },
              thickness: ((widthAt(it, p[i - 1]) + widthAt(it, p[i + 2])) / 2) * sx,
              color: c, lineCap: LineCapStyle.Round,
            });
          }
        }
      } else if (it.type === 'text') {
        const f = it.bold ? bold : font;
        const size = it.size * sx;
        const lh = it.size * 1.3 * sy;
        const lines = [];
        for (const para of winAnsiSafe(it.text).split('\n')) {
          let line = '';
          for (const w of para.split(/(\s+)/)) {
            const t = line + w;
            if (f.widthOfTextAtSize(t, size) > it.w * sx && line.trim()) { lines.push(line.trimEnd()); line = w.trimStart(); } else line = t;
          }
          lines.push(line);
        }
        lines.forEach((ln, i) => pg.drawText(ln, { x: it.x * sx, y: H - it.y * sy - size * 0.95 - i * lh, size, font: f, color: rgb(it.color) }));
      } else if (it.type === 'image') {
        if (!embedded.has(it.asset)) {
          const bytes = await api.getAsset(nb.id, it.asset);
          embedded.set(it.asset, /\.jpe?g$/.test(it.asset) ? await out.embedJpg(bytes) : await out.embedPng(bytes));
        }
        pg.drawImage(embedded.get(it.asset), { x: it.x * sx, y: H - (it.y + it.h) * sy, width: it.w * sx, height: it.h * sy });
      }
    }
  }
  return out.save();
}
