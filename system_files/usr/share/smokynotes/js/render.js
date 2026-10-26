// Dessin sur canvas : papier, traits (pression), surlignage, texte, images.
import { PAPERS, templateShapes } from './model.js';

export function drawPaper(ctx, page, s) {
  const paper = PAPERS[page.paper] || PAPERS.white;
  ctx.fillStyle = paper.bg;
  ctx.fillRect(0, 0, page.w * s, page.h * s);
  if (page.bg) return; // page de PDF : le fond vient du PDF
  const { lines, dots } = templateShapes(page);
  ctx.lineWidth = Math.max(1, 0.75 * s);
  for (const [x1, y1, x2, y2, strong] of lines) {
    ctx.strokeStyle = strong ? paper.strong : paper.line;
    ctx.beginPath();
    ctx.moveTo(x1 * s, y1 * s);
    ctx.lineTo(x2 * s, y2 * s);
    ctx.stroke();
  }
  ctx.fillStyle = paper.strong;
  for (const [x, y, r] of dots) {
    ctx.beginPath();
    ctx.arc(x * s, y * s, Math.max(0.8, r * s), 0, Math.PI * 2);
    ctx.fill();
  }
}

// Largeur d'un point selon la pression (stylo) — douce, jamais nulle.
export function widthAt(it, p) {
  if (it.tool === 'highlighter' || it.tool === 'shape') return it.width;
  return it.width * (0.35 + 0.95 * Math.min(1, Math.max(0, p)));
}

export function drawStroke(ctx, it, s, from = 0) {
  const p = it.points;
  const n = p.length / 3;
  if (n === 0) return;
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = it.color;
  ctx.fillStyle = it.color;
  if (it.tool === 'highlighter') {
    ctx.globalAlpha = 0.38;
    ctx.globalCompositeOperation = 'multiply';
  }
  if (n === 1) {
    ctx.beginPath();
    ctx.arc(p[0] * s, p[1] * s, (widthAt(it, p[2]) * s) / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    return;
  }
  if (it.tool === 'highlighter' || it.tool === 'shape') {
    // largeur constante : un seul chemin (pas de chevauchements visibles)
    ctx.lineWidth = it.width * s;
    if (it.tool === 'highlighter') ctx.lineCap = 'butt';
    ctx.beginPath();
    ctx.moveTo(p[0] * s, p[1] * s);
    for (let i = 3; i < p.length; i += 3) ctx.lineTo(p[i] * s, p[i + 1] * s);
    ctx.stroke();
    ctx.restore();
    return;
  }
  // stylo : segments lissés (courbes par les milieux), largeur selon la pression
  const start = Math.max(1, from);
  for (let i = start; i < n; i++) {
    const a = (i - 1) * 3, b = i * 3;
    const ax = p[a] * s, ay = p[a + 1] * s, bx = p[b] * s, by = p[b + 1] * s;
    const pw = (widthAt(it, p[a + 2]) + widthAt(it, p[b + 2])) / 2;
    ctx.lineWidth = pw * s;
    ctx.beginPath();
    if (i >= 2) {
      const z = (i - 2) * 3;
      const mx0 = ((p[z] + p[a]) / 2) * s, my0 = ((p[z + 1] + p[a + 1]) / 2) * s;
      ctx.moveTo(mx0, my0);
      ctx.quadraticCurveTo(ax, ay, (ax + bx) / 2, (ay + by) / 2);
    } else {
      ctx.moveTo(ax, ay);
      ctx.lineTo((ax + bx) / 2, (ay + by) / 2);
    }
    ctx.stroke();
  }
  // dernier demi-segment jusqu'au point final
  const l = (n - 1) * 3, k = (n - 2) * 3;
  ctx.lineWidth = widthAt(it, p[l + 2]) * s;
  ctx.beginPath();
  ctx.moveTo(((p[k] + p[l]) / 2) * s, ((p[k + 1] + p[l + 1]) / 2) * s);
  ctx.lineTo(p[l] * s, p[l + 1] * s);
  ctx.stroke();
  ctx.restore();
}

export function wrapText(ctx, text, maxW) {
  const out = [];
  for (const para of String(text).split('\n')) {
    const words = para.split(/(\s+)/);
    let line = '';
    for (const w of words) {
      const t = line + w;
      if (ctx.measureText(t).width > maxW && line.trim()) {
        out.push(line.trimEnd());
        line = w.trimStart();
      } else line = t;
    }
    out.push(line);
  }
  return out;
}

export const TEXT_FONT = '"Inter", "Adwaita Sans", "Cantarell", "Helvetica Neue", Arial, sans-serif';

export function drawText(ctx, it, s) {
  ctx.save();
  ctx.fillStyle = it.color;
  ctx.font = `${it.bold ? 700 : 400} ${it.size * s}px ${TEXT_FONT}`;
  ctx.textBaseline = 'top';
  const lines = wrapText(ctx, it.text, it.w * s);
  const lh = it.size * 1.3 * s;
  lines.forEach((ln, i) => ctx.fillText(ln, it.x * s, it.y * s + i * lh));
  ctx.restore();
  return (lines.length * it.size * 1.3);
}

export function drawItems(ctx, page, s, images, skip) {
  for (const it of page.items) {
    if (skip && skip.has(it)) continue;
    if (it.type === 'stroke') drawStroke(ctx, it, s);
    else if (it.type === 'text') it.h = Math.max(it.size * 1.3, drawText(ctx, it, s));
    else if (it.type === 'image') {
      const img = images.get(it.asset);
      if (img && img.complete) ctx.drawImage(img, it.x * s, it.y * s, it.w * s, it.h * s);
      else {
        ctx.fillStyle = 'rgba(128,128,128,0.15)';
        ctx.fillRect(it.x * s, it.y * s, it.w * s, it.h * s);
      }
    }
  }
}
