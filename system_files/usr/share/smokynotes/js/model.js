// Modèle de données : carnets, pages, modèles de papier, couvertures.

export const PAGE_SIZES = {
  a4: { label: 'A4 portrait', w: 595, h: 842 },
  a4l: { label: 'A4 paysage', w: 842, h: 595 },
  letter: { label: 'Lettre US', w: 612, h: 792 },
  wide: { label: 'Large (écran)', w: 842, h: 474 },
};

export const TEMPLATES = {
  blank: 'Blanc',
  lined: 'Ligné',
  grid: 'Quadrillé',
  dots: 'Pointillé',
  cornell: 'Cornell',
  seyes: 'Seyès',
  music: 'Portées',
};

export const PAPERS = {
  white: { label: 'Blanc', bg: '#ffffff', line: 'rgba(30,30,40,0.16)', strong: 'rgba(30,30,40,0.32)' },
  ivory: { label: 'Ivoire', bg: '#fbf8f1', line: 'rgba(60,50,30,0.16)', strong: 'rgba(60,50,30,0.3)' },
  ash: { label: 'Cendre', bg: '#e9e9ec', line: 'rgba(20,20,30,0.15)', strong: 'rgba(20,20,30,0.3)' },
  smoke: { label: 'Fumée (sombre)', bg: '#1c1c20', line: 'rgba(255,255,255,0.13)', strong: 'rgba(255,255,255,0.26)' },
};

export const COVERS = {
  graphite: { label: 'Graphite', a: '#3a3a40', b: '#16161a', fg: '#f2f2f4' },
  ash: { label: 'Cendre', a: '#d6d6da', b: '#9d9da4', fg: '#18181b' },
  ivory: { label: 'Ivoire', a: '#f7f5ee', b: '#d9d5c8', fg: '#1c1b18' },
  onyx: { label: 'Onyx', a: '#0e0e10', b: '#000000', fg: '#e9e9ec' },
  slate: { label: 'Ardoise', a: '#5b6573', b: '#2c323b', fg: '#eef1f5' },
  ember: { label: 'Braise', a: '#b4483a', b: '#5f1f18', fg: '#fff1ee' },
  sage: { label: 'Sauge', a: '#7f9483', b: '#3f4f43', fg: '#f1f6f1' },
  ink: { label: 'Encre', a: '#3d5a8a', b: '#1b2a45', fg: '#eef3ff' },
};

export const INK_COLORS = ['#111113', '#5c5c66', '#ffffff', '#1f6feb', '#d6332f', '#1f9d55', '#e8a317', '#8e44ad'];
export const HIGHLIGHT_COLORS = ['#ffe066', '#9be89b', '#8fd3ff', '#ff9ec9', '#ffb86b', '#c9c9cf'];

export function uid(prefix = '') {
  const r = crypto.getRandomValues(new Uint32Array(2));
  return prefix + Date.now().toString(36) + '-' + r[0].toString(36) + r[1].toString(36).slice(0, 4);
}

export function newPage({ size = 'a4', template = 'lined', paper = 'white', w, h, bg } = {}) {
  const s = PAGE_SIZES[size] || PAGE_SIZES.a4;
  return {
    id: uid('p'),
    w: w || s.w,
    h: h || s.h,
    template,
    paper,
    bg: bg || null,          // { type: 'pdf', asset, page } pour une page de PDF importé
    items: [],
    marked: false,
  };
}

export function newNotebook({ title = 'Sans titre', cover = 'graphite', size = 'a4', template = 'lined', paper = 'white' } = {}) {
  const now = Date.now();
  return {
    id: uid('n'),
    version: 1,
    title,
    cover,
    created: now,
    updated: now,
    favorite: false,
    defaults: { size, template, paper },
    pages: [newPage({ size, template, paper })],
  };
}

// Primitives du modèle de papier, partagées par l'écran et l'export PDF.
// Renvoie { lines: [[x1,y1,x2,y2,strong]], dots: [[x,y,r]] } en points PDF.
export function templateShapes(page) {
  const { w, h, template } = page;
  const lines = [];
  const dots = [];
  const m = 36;
  if (template === 'lined') {
    for (let y = 90; y < h - 28; y += 24) lines.push([m, y, w - m, y, false]);
    lines.push([m + 44, 0, m + 44, h, true]);
  } else if (template === 'grid') {
    for (let x = 18; x < w; x += 18) lines.push([x, 0, x, h, false]);
    for (let y = 18; y < h; y += 18) lines.push([0, y, w, y, false]);
  } else if (template === 'dots') {
    for (let x = 22; x < w - 10; x += 20) for (let y = 22; y < h - 10; y += 20) dots.push([x, y, 1.05]);
  } else if (template === 'cornell') {
    const cue = Math.round(w * 0.3);
    const sum = h - Math.round(h * 0.2);
    for (let y = 96; y < sum - 8; y += 24) lines.push([cue + 10, y, w - m, y, false]);
    lines.push([0, 70, w, 70, true]);
    lines.push([cue, 70, cue, sum, true]);
    lines.push([0, sum, w, sum, true]);
  } else if (template === 'seyes') {
    // Seyès (cahier français) : grands carreaux de 8 mm, 3 lignes fines entre
    const big = 22.7;
    const step = big / 4;
    for (let y = 60, i = 0; y < h - 20; y += step, i++) lines.push([m, y, w - 20, y, i % 4 === 0]);
    for (let x = m + 50; x < w - 20; x += big) lines.push([x, 60, x, h - 20, false]);
    lines.push([m + 50, 0, m + 50, h, true]);
  } else if (template === 'music') {
    for (let top = 70; top < h - 60; top += 72) {
      for (let k = 0; k < 5; k++) lines.push([m, top + k * 7, w - m, top + k * 7, true]);
    }
  }
  return { lines, dots };
}

export function cloneItems(items) {
  return items.map((it) => (it.points ? { ...it, points: it.points.slice() } : { ...it }));
}

export function itemBounds(it) {
  if (it.type === 'stroke') {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const p = it.points;
    for (let i = 0; i < p.length; i += 3) {
      if (p[i] < x0) x0 = p[i];
      if (p[i] > x1) x1 = p[i];
      if (p[i + 1] < y0) y0 = p[i + 1];
      if (p[i + 1] > y1) y1 = p[i + 1];
    }
    const pad = it.width;
    return { x: x0 - pad, y: y0 - pad, w: x1 - x0 + 2 * pad, h: y1 - y0 + 2 * pad };
  }
  return { x: it.x, y: it.y, w: it.w, h: it.h };
}
