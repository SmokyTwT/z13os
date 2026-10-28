// Éditeur de carnet : pages, outils, gestes tactiles, annuler/rétablir, sauvegarde.
import { api, hashName } from './api.js';
import { INK_COLORS, HIGHLIGHT_COLORS, PAPERS, TEMPLATES, cloneItems, itemBounds, newPage } from './model.js';
import { drawPaper, drawItems, drawStroke, TEXT_FONT } from './render.js';
import { strokeHit, eraseFromStroke, itemInLasso, shapePoints, recognize, transformItem, isScribble, scribbleTargets } from './geometry.js';
import { renderPdfPage, importPdf } from './pdfdoc.js';
import { exportById } from './library.js';
import { icon, hydrateIcons } from './icons.js';
import { $, esc, toast, openMenu, openModal, confirmBox } from './ui.js';
import { initAudio, audioOnOpen, audioOnClose, listenAt, fadeFn } from './audio.js';

const DPR = () => Math.min(window.devicePixelRatio || 1, 3);
const MIN_ZOOM = 0.3, MAX_ZOOM = 4;

const TOOL_DEFAULTS = {
  pen: { color: '#111113', width: 1.8, scribble: true },
  highlighter: { color: '#ffe066', width: 14 },
  eraser: { width: 12, mode: 'stroke' },
  shape: { color: '#111113', width: 1.8, kind: 'rect' },
  text: { color: '#111113', size: 16, bold: false },
  lasso: {},
  listen: {},
  laser: { color: '#ff3b30' },
};
const SIZES = {
  pen: [0.9, 1.8, 3, 5],
  highlighter: [8, 14, 22],
  eraser: [6, 12, 26],
  shape: [1, 1.8, 3, 5],
  text: [12, 16, 22, 32],
};

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem('smoky-notes-prefs')) || {}; } catch { return {}; }
}
function savePrefs(p) {
  try { localStorage.setItem('smoky-notes-prefs', JSON.stringify(p)); } catch { /* stockage indisponible */ }
}

const prefs = loadPrefs();
const S = {
  nb: null,
  views: new Map(),          // page.id → { page, el, bg, ink, live, ui, scale, stale, visible }
  zoom: 1,
  tool: prefs.tool || 'pen',
  cfg: Object.fromEntries(Object.entries(TOOL_DEFAULTS).map(([k, v]) => [k, { ...v, ...(prefs.cfg?.[k] || {}) }])),
  finger: prefs.finger || false,
  undo: [],
  redo: [],
  sel: null,                 // { view, items: Set, box }
  clip: null,
  images: new Map(),
  current: 0,
  saveTimer: null,
  saving: false,
  dirty: false,
  observer: null,
  onBack: null,
};

// ---------------------------------------------------------------------------
// Ouverture / fermeture
// ---------------------------------------------------------------------------
export function initEditor(onBack) {
  S.onBack = onBack;
  hydrateIcons($('#editor'));
  $('#ed-back').onclick = () => closeEditor();
  $('#ed-pages-btn').onclick = () => toggleSidebar();
  $('#ed-undo').onclick = undo;
  $('#ed-redo').onclick = redo;
  $('#ed-finger').onclick = () => {
    S.finger = !S.finger;
    persistPrefs();
    syncChrome();
    toast(S.finger ? 'Dessin au doigt activé' : 'Doigt : défiler et zoomer · stylet : écrire');
  };
  $('#ed-more').onclick = (e) => moreMenu(e.currentTarget);
  $('#ed-image').onclick = pickImage;
  $('#ed-add-page').onclick = () => addPage(S.current + 1);
  $('#ed-title').onchange = () => {
    S.nb.title = $('#ed-title').value.trim() || 'Sans titre';
    markDirty();
  };
  document.querySelectorAll('#ed-tools .tool').forEach((b) => { b.onclick = () => setTool(b.dataset.tool); });
  document.querySelectorAll('.side-head .tab').forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll('.side-head .tab').forEach((x) => x.classList.toggle('active', x === t));
      renderThumbs();
    };
  });
  document.querySelectorAll('#sel-bar [data-sel]').forEach((b) => { b.onclick = (e) => selAction(b.dataset.sel, e.currentTarget); });
  bindInput();
  initAudio({ nb: () => S.nb, markDirty, rerender: () => { for (const v of S.views.values()) if (v.visible && !v.stale) renderInk(v); } });
  addEventListener('keydown', onKey);
  addEventListener('resize', () => { if (S.nb) layout(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) flushSave(); });
  addEventListener('pagehide', () => flushSave());
}

export async function openEditor(id) {
  let nb;
  try {
    nb = await api.load(id);
  } catch (e) {
    toast('Carnet illisible : ' + e.message);
    return;
  }
  S.nb = nb;
  nb.pages.forEach((p) => { p.items ||= []; });
  S.undo = []; S.redo = []; S.sel = null; S.current = 0;
  $('#library').classList.add('hidden');
  $('#editor').classList.remove('hidden');
  $('#ed-title').value = nb.title || 'Sans titre';
  setSaveState('Enregistré');
  buildPages();
  S.zoom = fitZoom();
  layout();
  $('#ed-scroll').scrollTop = 0;
  setTool(S.tool);
  syncChrome();
  loadImages();
  audioOnOpen();
}

async function closeEditor() {
  await audioOnClose();
  commitText();
  clearSelection();
  await flushSave();
  S.observer?.disconnect();
  $('#ed-pages').innerHTML = '';
  S.views.clear();
  S.nb = null;
  S.onBack();
}

// ---------------------------------------------------------------------------
// Sauvegarde automatique
// ---------------------------------------------------------------------------
function setSaveState(t) { $('#ed-save').textContent = t; }

function markDirty() {
  S.dirty = true;
  setSaveState('Modifié…');
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(flushSave, 700);
}

async function flushSave() {
  clearTimeout(S.saveTimer);
  if (!S.nb || !S.dirty) return;
  S.dirty = false;
  setSaveState('Enregistrement…');
  try {
    const snapshot = JSON.parse(JSON.stringify(S.nb, (k, v) => (k === 'h' && v === undefined ? undefined : v)));
    await api.save(snapshot);
    if (!S.dirty) setSaveState('Enregistré');
  } catch (e) {
    S.dirty = true;
    setSaveState('Non enregistré');
    toast('Enregistrement impossible : ' + e.message, 4000);
  }
}

// ---------------------------------------------------------------------------
// Pages et rendu
// ---------------------------------------------------------------------------
function fitZoom() {
  const avail = $('#ed-scroll').clientWidth - 80;
  const maxW = Math.max(...S.nb.pages.map((p) => p.w));
  return Math.max(MIN_ZOOM, Math.min(1.6, avail / maxW));
}

function buildPages() {
  const host = $('#ed-pages');
  host.innerHTML = '';
  S.views.clear();
  S.observer?.disconnect();
  S.observer = new IntersectionObserver((entries) => {
    for (const en of entries) {
      const v = en.target._view;
      v.visible = en.isIntersecting;
      if (v.visible && v.stale) renderView(v);
      if (!v.visible) releaseView(v);
    }
  }, { root: $('#ed-scroll'), rootMargin: '900px 0px' });
  S.nb.pages.forEach((page) => host.appendChild(makeView(page).el));
  updatePageNo();
}

function makeView(page) {
  const el = document.createElement('div');
  el.className = 'page';
  const mk = (cls) => { const c = document.createElement('canvas'); c.className = cls; el.appendChild(c); return c; };
  const v = { page, el, bg: mk('bg'), ink: mk('ink'), live: mk('live'), ui: mk('ui'), scale: 0, stale: true, visible: false };
  el._view = v;
  S.views.set(page.id, v);
  S.observer.observe(el);
  return v;
}

function layout() {
  for (const v of S.views.values()) {
    v.el.style.width = v.page.w * S.zoom + 'px';
    v.el.style.height = v.page.h * S.zoom + 'px';
    v.el.querySelector('.bm-flag')?.remove();
    if (v.page.marked) v.el.insertAdjacentHTML('beforeend', `<span class="bm-flag">${icon('bookmark', 22)}</span>`);
    v.stale = true;
  }
  clearTimeout(S.renderTimer);
  S.renderTimer = setTimeout(() => { for (const v of S.views.values()) if (v.visible) renderView(v); }, 60);
  positionTextEditor();
  updatePageNo(true);
}

function canvasScale(page) {
  // limite la taille des canvas (mémoire) aux très forts zooms
  return Math.min(S.zoom * DPR(), 8192 / Math.max(page.w, page.h));
}

function sizeCanvas(c, page, s) {
  const w = Math.round(page.w * s), h = Math.round(page.h * s);
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
}

function renderView(v) {
  const s = canvasScale(v.page);
  v.scale = s;
  v.stale = false;
  for (const c of [v.bg, v.ink, v.live, v.ui]) sizeCanvas(c, v.page, s);
  renderBg(v);
  renderInk(v);
  drawSelection();
}

function releaseView(v) {
  // libère la mémoire des pages éloignées
  for (const c of [v.bg, v.ink, v.live, v.ui]) { c.width = 0; c.height = 0; }
  v.stale = true;
}

async function renderBg(v) {
  const ctx = v.bg.getContext('2d');
  drawPaper(ctx, v.page, v.scale);
  if (v.page.bg?.type === 'pdf') {
    const s = v.scale;
    try {
      v.bg._pdfTask?.cancel();
      const tmp = document.createElement('canvas');
      tmp.width = v.bg.width; tmp.height = v.bg.height;
      await renderPdfPage(tmp, S.nb.id, v.page.bg, s * (v.page.w / v.page.w));
      if (v.scale === s && v.bg.width === tmp.width) ctx.drawImage(tmp, 0, 0);
    } catch (e) {
      if (e?.name !== 'RenderingCancelledException') console.warn(e);
    }
  }
}

function renderInk(v, skip) {
  const ctx = v.ink.getContext('2d');
  ctx.clearRect(0, 0, v.ink.width, v.ink.height);
  drawItems(ctx, v.page, v.scale, S.images, skip, fadeFn());
}

function viewAt(index) { return S.views.get(S.nb.pages[index]?.id); }
function viewIndex(v) { return S.nb.pages.indexOf(v.page); }

function updatePageNo(force) {
  const sc = $('#ed-scroll');
  const mid = sc.getBoundingClientRect().top + sc.clientHeight / 3;
  let best = 0;
  S.nb.pages.forEach((p, i) => {
    const r = S.views.get(p.id).el.getBoundingClientRect();
    if (r.top <= mid) best = i;
  });
  if (best !== S.current || force) {
    S.current = best;
    document.querySelectorAll('.thumb').forEach((t) => t.classList.toggle('current', +t.dataset.i === best));
  }
  $('#ed-pageno').textContent = `${S.current + 1} / ${S.nb.pages.length}`;
}

async function loadImages() {
  for (const p of S.nb.pages) {
    for (const it of p.items) if (it.type === 'image') ensureImage(it.asset);
  }
}

function ensureImage(asset) {
  if (S.images.has(S.nb.id + asset) || S.images.has(asset)) return;
  const img = new Image();
  S.images.set(asset, img);
  api.getAsset(S.nb.id, asset).then((buf) => {
    img.onload = () => { for (const v of S.views.values()) if (v.visible && v.page.items.some((i) => i.asset === asset)) renderInk(v); };
    img.src = URL.createObjectURL(new Blob([buf]));
  });
}

// ---------------------------------------------------------------------------
// Annuler / rétablir
// ---------------------------------------------------------------------------
function pushUndo(cmd) {
  S.undo.push(cmd);
  if (S.undo.length > 200) S.undo.shift();
  S.redo = [];
  markDirty();
  syncChrome();
}

function recordItems(v, before) {
  pushUndo({ type: 'items', pageId: v.page.id, before, after: v.page.items.slice() });
  scheduleThumb(v.page);
}

function applyCmd(cmd, dir) {
  if (cmd.type === 'items') {
    const v = S.views.get(cmd.pageId);
    if (!v) return;
    v.page.items = (dir === 'undo' ? cmd.before : cmd.after).slice();
    renderInk(v);
    scheduleThumb(v.page);
  } else if (cmd.type === 'pages') {
    S.nb.pages = (dir === 'undo' ? cmd.before : cmd.after).slice();
    rebuildKeepScroll();
  } else if (cmd.type === 'page-prop') {
    const page = S.nb.pages.find((p) => p.id === cmd.pageId);
    if (page) Object.assign(page, dir === 'undo' ? cmd.before : cmd.after);
    layout();
    renderThumbs();
  }
  markDirty();
}

function undo() {
  commitText();
  clearSelection();
  const c = S.undo.pop();
  if (!c) return;
  applyCmd(c, 'undo');
  S.redo.push(c);
  syncChrome();
}

function redo() {
  commitText();
  clearSelection();
  const c = S.redo.pop();
  if (!c) return;
  applyCmd(c, 'redo');
  S.undo.push(c);
  syncChrome();
}

// ---------------------------------------------------------------------------
// Outils et barre secondaire
// ---------------------------------------------------------------------------
function persistPrefs() { savePrefs({ tool: S.tool, cfg: S.cfg, finger: S.finger }); }

function setTool(t) {
  if (t !== 'text') commitText();
  if (t !== 'lasso') clearSelection();
  S.tool = t;
  persistPrefs();
  document.querySelectorAll('#ed-tools .tool').forEach((b) => {
    b.classList.toggle('active', b.dataset.tool === t);
    b.querySelector('.dot')?.remove();
    const c = S.cfg[b.dataset.tool]?.color;
    if (c && ['pen', 'highlighter', 'shape', 'text'].includes(b.dataset.tool)) b.insertAdjacentHTML('beforeend', `<i class="dot" style="background:${c}"></i>`);
  });
  buildSubBar();
}

function syncChrome() {
  $('#ed-undo').disabled = !S.undo.length;
  $('#ed-redo').disabled = !S.redo.length;
  $('#ed-finger').classList.toggle('on', S.finger);
}

function buildSubBar() {
  const t = S.tool, cfg = S.cfg[t];
  const colors = $('#ed-colors'), sizes = $('#ed-sizes'), extra = $('#ed-sub-extra');
  colors.innerHTML = ''; sizes.innerHTML = ''; extra.innerHTML = '';
  if ('color' in cfg && t !== 'laser') {
    const palette = t === 'highlighter' ? HIGHLIGHT_COLORS : INK_COLORS;
    for (const c of palette) {
      const b = document.createElement('button');
      b.className = 'swatch' + (cfg.color === c ? ' active' : '');
      b.style.background = c;
      b.onclick = () => { cfg.color = c; setTool(t); };
      colors.appendChild(b);
    }
    const custom = document.createElement('label');
    custom.className = 'swatch custom' + (palette.includes(cfg.color) ? '' : ' active');
    custom.title = 'Autre couleur';
    custom.innerHTML = `<input type="color" value="${cfg.color}">`;
    custom.querySelector('input').onchange = (e) => { cfg.color = e.target.value; setTool(t); };
    colors.appendChild(custom);
  }
  if (SIZES[t]) {
    const key = t === 'text' ? 'size' : 'width';
    SIZES[t].forEach((w, i) => {
      const b = document.createElement('button');
      b.className = 'size' + (cfg[key] === w ? ' active' : '');
      const d = t === 'text' ? 0 : Math.min(22, 4 + i * 5);
      b.innerHTML = t === 'text' ? `<span style="font-weight:700;font-size:${11 + i * 3}px">A</span>` : `<i style="width:${d}px;height:${d}px"></i>`;
      b.title = t === 'text' ? `${w} pt` : `${w}`;
      b.onclick = () => { cfg[key] = w; setTool(t); };
      sizes.appendChild(b);
    });
  }
  const chip = (label, active, fn) => {
    const b = document.createElement('button');
    b.className = 'chip' + (active ? ' active' : '');
    b.textContent = label;
    b.onclick = fn;
    extra.appendChild(b);
  };
  if (t === 'eraser') {
    chip('Trait entier', cfg.mode === 'stroke', () => { cfg.mode = 'stroke'; setTool(t); });
    chip('Précise', cfg.mode === 'precise', () => { cfg.mode = 'precise'; setTool(t); });
    chip('Effacer la page', false, clearPage);
  } else if (t === 'shape') {
    for (const [k, l] of [['line', 'Ligne'], ['arrow', 'Flèche'], ['rect', 'Rectangle'], ['ellipse', 'Ellipse'], ['triangle', 'Triangle']]) {
      chip(l, cfg.kind === k, () => { cfg.kind = k; setTool(t); });
    }
  } else if (t === 'text') {
    chip('Gras', cfg.bold, () => { cfg.bold = !cfg.bold; setTool(t); });
    extra.insertAdjacentHTML('beforeend', '<span style="color:var(--fg-3);font-size:12px">Touche la page pour écrire</span>');
  } else if (t === 'lasso') {
    extra.insertAdjacentHTML('beforeend', '<span style="color:var(--fg-3);font-size:13px">Entoure des éléments pour les déplacer, redimensionner, recolorer ou copier</span>');
  } else if (t === 'listen') {
    extra.insertAdjacentHTML('beforeend', '<span style="color:var(--fg-3);font-size:13px">Touche un mot ou un dessin : l’enregistrement repart au moment où tu l’as écrit</span>');
  } else if (t === 'laser') {
    for (const [c, l] of [['#ff3b30', 'Rouge'], ['#ffffff', 'Blanc'], ['#34c759', 'Vert']]) chip(l, cfg.color === c, () => { cfg.color = c; setTool(t); });
  } else if (t === 'pen') {
    chip('Gribouiller = effacer', cfg.scribble !== false, () => { cfg.scribble = cfg.scribble === false; setTool(t); });
    extra.insertAdjacentHTML('beforeend', '<span style="color:var(--fg-3);font-size:12px">Astuce : garde le stylet immobile à la fin d’un trait pour en faire une forme parfaite</span>');
  }
}

// ---------------------------------------------------------------------------
// Entrées : stylet, souris, doigts
// ---------------------------------------------------------------------------
const touches = new Map();
let gesture = null;   // { kind: 'pan' | 'pinch', ... }
let action = null;    // action de dessin en cours
let lastPen = 0;

function pagePoint(v, e) {
  const r = v.el.getBoundingClientRect();
  return [(e.clientX - r.left) / S.zoom, (e.clientY - r.top) / S.zoom];
}

function viewFromEvent(e) {
  const el = document.elementsFromPoint(e.clientX, e.clientY).find((x) => x.classList?.contains('page'));
  return el?._view || null;
}

function pressure(e) {
  if (e.pointerType === 'pen') return e.pressure || 0.5;
  return 0.5;
}

function bindInput() {
  const sc = $('#ed-scroll');
  sc.addEventListener('pointerdown', onDown);
  sc.addEventListener('pointermove', onMove);
  sc.addEventListener('pointerup', onUp);
  sc.addEventListener('pointercancel', onUp);
  sc.addEventListener('scroll', () => { updatePageNo(); positionSelBar(); });
  sc.addEventListener('wheel', (e) => {
    if (e.ctrlKey) {
      e.preventDefault();
      zoomAt(S.zoom * Math.exp(-e.deltaY * 0.0022), e.clientX, e.clientY);
    }
  }, { passive: false });
  sc.addEventListener('contextmenu', (e) => e.preventDefault());
}

function onDown(e) {
  if (e.target.closest('.text-edit')) return;
  if (e.pointerType === 'pen') lastPen = performance.now();
  const isTouch = e.pointerType === 'touch';
  if (isTouch) {
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const palm = performance.now() - lastPen < 800 || (action && action.pointerType === 'pen');
    if (touches.size >= 2 || !S.finger || palm) {
      if (action && action.pointerType === 'touch') cancelAction();
      if (!palm || touches.size >= 2) startGesture();
      return;
    }
  }
  if (e.pointerType === 'mouse' && e.button !== 0) {
    if (e.button === 1) { touches.set(e.pointerId, { x: e.clientX, y: e.clientY }); startGesture(); }
    return;
  }
  const v = viewFromEvent(e);
  if (!v) { if (S.tool === 'text') commitText(); clearSelection(); return; }
  e.preventDefault();
  $('#ed-scroll').setPointerCapture(e.pointerId);
  startAction(v, e);
}

function onMove(e) {
  if (touches.has(e.pointerId)) {
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (gesture) moveGesture();
    return;
  }
  if (!action || action.id !== e.pointerId) {
    if (S.tool === 'eraser' && e.pointerType !== 'touch') hoverEraser(e);
    return;
  }
  const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
  for (const ev of (evs.length ? evs : [e])) moveAction(ev);
}

function onUp(e) {
  if (touches.has(e.pointerId)) {
    touches.delete(e.pointerId);
    if (touches.size === 0) endGesture();
    else startGesture();
    return;
  }
  if (action && action.id === e.pointerId) endAction(e);
}

// --- Gestes : un doigt défile, deux doigts zooment ----------------------------
let tap = null; // détection « toucher à 2 ou 3 doigts »
function startGesture() {
  const pts = [...touches.values()];
  if (!tap || performance.now() - tap.t > 300) tap = { t: performance.now(), n: 0, moved: false, z: S.zoom, st: $('#ed-scroll').scrollTop };
  tap.n = Math.max(tap.n, pts.length);
  const sc = $('#ed-scroll');
  if (pts.length === 1) {
    gesture = { kind: 'pan', x: pts[0].x, y: pts[0].y, sl: sc.scrollLeft, st: sc.scrollTop, vx: 0, vy: 0, t: performance.now() };
  } else if (pts.length >= 2) {
    const [a, b] = pts;
    gesture = { kind: 'pinch', d: Math.hypot(a.x - b.x, a.y - b.y), z: S.zoom, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
  }
  cancelMomentum();
}

function moveGesture() {
  const pts = [...touches.values()];
  const sc = $('#ed-scroll');
  if (gesture.kind === 'pan' && pts.length === 1) {
    const now = performance.now();
    const nx = pts[0].x, ny = pts[0].y;
    const dt = Math.max(1, now - gesture.t);
    gesture.vx = (gesture.lx ?? nx) - nx; gesture.vy = (gesture.ly ?? ny) - ny;
    gesture.vx /= dt; gesture.vy /= dt;
    gesture.lx = nx; gesture.ly = ny; gesture.t = now;
    sc.scrollLeft = gesture.sl - (nx - gesture.x);
    sc.scrollTop = gesture.st - (ny - gesture.y);
  } else if (gesture.kind === 'pinch' && pts.length >= 2) {
    const [a, b] = pts;
    const d = Math.hypot(a.x - b.x, a.y - b.y);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    zoomAt(gesture.z * (d / gesture.d), mx, my, gesture.mx - mx, gesture.my - my);
    gesture.mx = mx; gesture.my = my;
    gesture.z = S.zoom; gesture.d = d;
  }
}

let momentum = 0;
function endGesture() {
  if (tap && !gesture?.moved && performance.now() - tap.t < 260 && Math.abs(S.zoom - tap.z) < 0.02 && Math.abs($('#ed-scroll').scrollTop - tap.st) < 8) {
    if (tap.n === 2) { undo(); toast('Annulé', 900); }
    else if (tap.n === 3) { redo(); toast('Rétabli', 900); }
    tap = null;
    gesture = null;
    return;
  }
  tap = null;
  if (gesture?.kind === 'pan' && performance.now() - gesture.t < 80) {
    let vx = gesture.vx * 16, vy = gesture.vy * 16;
    const sc = $('#ed-scroll');
    const step = () => {
      vx *= 0.94; vy *= 0.94;
      sc.scrollLeft += vx; sc.scrollTop += vy;
      if (Math.abs(vx) + Math.abs(vy) > 0.5) momentum = requestAnimationFrame(step);
    };
    momentum = requestAnimationFrame(step);
  }
  gesture = null;
}
function cancelMomentum() { cancelAnimationFrame(momentum); }

function zoomAt(z, cx, cy, panX = 0, panY = 0) {
  z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
  const sc = $('#ed-scroll');
  // point de la page sous le centre du geste, conservé après le zoom
  const v = viewFromEvent({ clientX: cx, clientY: cy }) || viewAt(S.current);
  const r0 = v.el.getBoundingClientRect();
  const px = (cx - r0.left) / S.zoom, py = (cy - r0.top) / S.zoom;
  S.zoom = z;
  layout();
  const r1 = v.el.getBoundingClientRect();
  sc.scrollLeft += r1.left + px * z - cx + panX;
  sc.scrollTop += r1.top + py * z - cy + panY;
  const pill = $('#ed-zoom');
  pill.textContent = Math.round(z * 100) + ' %';
  pill.classList.add('show');
  clearTimeout(pill._t);
  pill._t = setTimeout(() => pill.classList.remove('show'), 900);
  positionSelBar();
}

// --- Actions de dessin -------------------------------------------------------
function startAction(v, e) {
  const [x, y] = pagePoint(v, e);
  // bout « gomme » du stylet (bouton 5) : gomme sans changer d'outil
  const t = e.pointerType === 'pen' && (e.button === 5 || (e.buttons & 32)) ? 'eraser' : S.tool;
  action = { id: e.pointerId, pointerType: e.pointerType, v, tool: t, x0: x, y0: y, t0: Date.now(), before: v.page.items.slice() };

  if (t === 'pen' || t === 'highlighter') {
    const cfg = S.cfg[t];
    action.item = { type: 'stroke', tool: t, color: cfg.color, width: cfg.width, points: [x, y, pressure(e)] };
    action.hx = x; action.hy = y;
    armHold();
    drawLive();
  } else if (t === 'eraser') {
    eraseAt(x, y);
  } else if (t === 'lasso') {
    if (S.sel && S.sel.view === v && hitSelection(x, y)) {
      action.kind = hitHandle(x, y) ? 'scale' : 'move';
      action.box = { ...S.sel.box };
      action.orig = new Map([...S.sel.items].map((it) => [it, it]));
      renderInk(v, S.sel.items);
    } else {
      clearSelection();
      action.kind = 'lasso';
      action.poly = [x, y];
    }
  } else if (t === 'shape') {
    action.item = null;
  } else if (t === 'text') {
    action.kind = 'text';
    action.hadEdit = !!textEdit;
    commitText();
  } else if (t === 'laser') {
    laserAdd(v, x, y);
  } else if (t === 'listen') {
    // élément le plus récent sous le doigt / le stylet
    const hit = [...v.page.items].reverse().find((it) => {
      if (it.type === 'stroke') return strokeHit(it, x, y, 8);
      const b = itemBounds(it);
      return x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + (b.h || 20);
    });
    listenAt(hit);
  }
}

function moveAction(e) {
  const a = action;
  const [x, y] = pagePoint(a.v, e);
  if (a.tool === 'pen' || a.tool === 'highlighter') {
    const p = a.item.points;
    const lx = p[p.length - 3], ly = p[p.length - 2];
    if (Math.hypot(x - lx, y - ly) < 0.35 / S.zoom) return;
    // le minuteur « forme parfaite » repart dès qu'on s'éloigne de 3 pt du point d'arrêt
    if (Math.hypot(x - a.hx, y - a.hy) > 3) { a.hx = x; a.hy = y; armHold(); }
    if (a.shaped) return;
    p.push(x, y, pressure(e));
    drawLive();
  } else if (a.tool === 'eraser') {
    eraseAt(x, y);
  } else if (a.tool === 'lasso') {
    if (a.kind === 'lasso') {
      a.poly.push(x, y);
      drawLassoPath();
    } else {
      a.dx = x - a.x0; a.dy = y - a.y0;
      previewTransform();
    }
  } else if (a.tool === 'shape') {
    const cfg = S.cfg.shape;
    a.item = { type: 'stroke', tool: 'shape', color: cfg.color, width: cfg.width, points: shapePoints(cfg.kind, a.x0, a.y0, x, y) };
    drawLive();
  } else if (a.tool === 'laser') {
    laserAdd(a.v, x, y);
  }
}

function endAction(e) {
  const a = action;
  action = null;
  clearTimeout(holdTimer);
  const v = a.v;
  const live = v.live.getContext('2d');
  live.clearRect(0, 0, v.live.width, v.live.height);
  if (a.tool === 'pen' && a.item && !a.shaped && S.cfg.pen.scribble !== false && isScribble(a.item.points)) {
    // gribouillis sur de l'écriture : on efface ce qu'il recouvre au lieu d'ajouter le trait
    const gone = new Set(scribbleTargets(v.page.items, a.item.points, itemBounds));
    if (gone.size) {
      v.page.items = v.page.items.filter((it) => !gone.has(it));
      renderInk(v);
      recordItems(v, a.before);
      fadeErased(v, [...gone]);
      toast(gone.size > 1 ? `${gone.size} éléments effacés` : 'Effacé', 900);
      return;
    }
  }
  if ((a.tool === 'pen' || a.tool === 'highlighter' || a.tool === 'shape') && a.item) {
    a.item.t = a.t0;                         // heure d'écriture : synchro avec l'audio
    v.page.items.push(a.item);
    drawStroke(v.ink.getContext('2d'), a.item, v.scale);
    if (a.tool === 'highlighter') renderInk(v);
    recordItems(v, a.before);
  } else if (a.tool === 'eraser') {
    clearUi(v);
    if (a.changed) recordItems(v, a.before);
  } else if (a.tool === 'lasso') {
    if (a.kind === 'lasso') {
      clearUi(v);
      const items = v.page.items.filter((it) => itemInLasso(it, a.poly));
      if (items.length) select(v, items);
    } else {
      commitTransform(a);
    }
  } else if (a.tool === 'text') {
    const [x, y] = pagePoint(v, e);
    if (!a.hadEdit && Math.hypot(x - a.x0, y - a.y0) < 6) textAt(v, x, y);
  }
}

function cancelAction() {
  if (!action) return;
  const v = action.v;
  v.page.items = action.before;
  v.live.getContext('2d').clearRect(0, 0, v.live.width, v.live.height);
  clearUi(v);
  renderInk(v);
  action = null;
  clearTimeout(holdTimer);
}

function drawLive() {
  const a = action, v = a.v;
  const ctx = v.live.getContext('2d');
  ctx.clearRect(0, 0, v.live.width, v.live.height);
  // Gribouillis repéré pendant le tracé : trait rouge + aperçu de ce qui va être effacé
  if (a.tool === 'pen' && !a.shaped && S.cfg.pen.scribble !== false) {
    const n = a.item.points.length / 3;
    if (n >= 12 && n - (a.scribbleAt || 0) >= 4) {
      a.scribbleAt = n;
      a.scribble = isScribble(a.item.points) ? scribbleTargets(v.page.items, a.item.points, itemBounds) : null;
    }
    if (a.scribble && a.scribble.length) {
      drawTargets(ctx, v, a.scribble, 0.85);
      ctx.save(); ctx.globalAlpha = 0.55;
      drawStroke(ctx, { ...a.item, color: SCRIBBLE_RED }, v.scale);
      ctx.restore();
      return;
    }
  }
  drawStroke(ctx, a.item, v.scale);
}

const SCRIBBLE_RED = '#ff4d5e';
function drawTargets(ctx, v, items, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  for (const it of items) {
    if (it.type === 'stroke') drawStroke(ctx, { ...it, color: SCRIBBLE_RED }, v.scale);
    else {
      const b = itemBounds(it);
      ctx.fillStyle = 'rgba(255, 77, 94, 0.28)';
      ctx.fillRect(b.x * v.scale, b.y * v.scale, b.w * v.scale, (b.h || 20) * v.scale);
    }
  }
  ctx.restore();
}

// Ce qui vient d'être effacé par un gribouillis s'estompe en rouge (~0,3 s)
function fadeErased(v, items) {
  const ctx = v.live.getContext('2d');
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / 320);
    ctx.clearRect(0, 0, v.live.width, v.live.height);
    if (k < 1 && !action) { drawTargets(ctx, v, items, 0.85 * (1 - k)); requestAnimationFrame(step); }
  };
  requestAnimationFrame(step);
}

// Maintenir immobile ~0,6 s : le trait devient une forme parfaite
let holdTimer = 0;
function armHold() {
  clearTimeout(holdTimer);
  holdTimer = setTimeout(() => {
    const a = action;
    if (!a || !a.item || a.shaped) return;
    const r = recognize(a.item.points);
    if (!r) return;
    const [x0, y0, x1, y1] = r.box;
    a.item = { ...a.item, tool: a.item.tool === 'highlighter' ? 'highlighter' : 'shape', points: shapePoints(r.kind, x0, y0, x1, y1) };
    a.shaped = true;
    drawLive();
    if (navigator.vibrate) navigator.vibrate(10);
  }, 600);
}

// --- Gomme -------------------------------------------------------------------
function eraseAt(x, y) {
  const a = action, v = a.v;
  const cfg = S.cfg.eraser;
  const r = cfg.width / 2;
  let changed = false;
  const out = [];
  for (const it of v.page.items) {
    if (it.type === 'stroke') {
      if (cfg.mode === 'precise') {
        const parts = eraseFromStroke(it, x, y, r);
        if (parts) { out.push(...parts); changed = true; continue; }
      } else if (strokeHit(it, x, y, r)) { changed = true; continue; }
    } else if (cfg.mode === 'stroke') {
      const b = itemBounds(it);
      if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + (b.h || 20)) { changed = true; continue; }
    }
    out.push(it);
  }
  if (changed) {
    v.page.items = out;
    a.changed = true;
    renderInk(v);
  }
  drawEraserCursor(v, x, y);
}

function drawEraserCursor(v, x, y) {
  const ctx = v.ui.getContext('2d');
  ctx.clearRect(0, 0, v.ui.width, v.ui.height);
  const s = v.scale;
  ctx.beginPath();
  ctx.arc(x * s, y * s, (S.cfg.eraser.width / 2) * s, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(255,255,255,0.25)';
  ctx.strokeStyle = 'rgba(40,40,46,0.7)';
  ctx.lineWidth = 1.2 * DPR();
  ctx.fill();
  ctx.stroke();
}

let hoverView = null;
function hoverEraser(e) {
  const v = viewFromEvent(e);
  if (hoverView && hoverView !== v) clearUi(hoverView);
  hoverView = v;
  if (v) { const [x, y] = pagePoint(v, e); drawEraserCursor(v, x, y); }
}

function clearUi(v) {
  v.ui.getContext('2d').clearRect(0, 0, v.ui.width, v.ui.height);
  if (S.sel?.view === v) drawSelection();
}

async function clearPage() {
  const v = viewAt(S.current);
  if (!v || !v.page.items.length) return;
  if (!(await confirmBox('Effacer cette page ?', 'Tout ce qui est écrit sur la page sera effacé (tu pourras annuler).', 'Effacer'))) return;
  const before = v.page.items.slice();
  v.page.items = [];
  renderInk(v);
  recordItems(v, before);
}

// --- Lasso et sélection --------------------------------------------------------
function drawLassoPath() {
  const a = action, v = a.v, s = v.scale;
  const ctx = v.ui.getContext('2d');
  ctx.clearRect(0, 0, v.ui.width, v.ui.height);
  ctx.beginPath();
  for (let i = 0; i < a.poly.length; i += 2) ctx[i ? 'lineTo' : 'moveTo'](a.poly[i] * s, a.poly[i + 1] * s);
  ctx.closePath();
  ctx.fillStyle = 'rgba(31,111,235,0.08)';
  ctx.fill();
  ctx.setLineDash([6 * DPR(), 5 * DPR()]);
  ctx.strokeStyle = '#1f6feb';
  ctx.lineWidth = 1.5 * DPR();
  ctx.stroke();
}

function boxOf(items) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const it of items) {
    const b = itemBounds(it);
    x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + (b.h || 20));
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function select(v, items) {
  if (S.tool !== 'lasso') setTool('lasso');
  S.sel = { view: v, items: new Set(items), box: boxOf(items) };
  drawSelection();
  positionSelBar();
}

function clearSelection() {
  if (!S.sel) return;
  const v = S.sel.view;
  S.sel = null;
  clearUi(v);
  $('#sel-bar').classList.add('hidden');
}

const HANDLE = 14;
function drawSelection(box) {
  if (!S.sel) return;
  const v = S.sel.view, s = v.scale;
  const b = box || S.sel.box;
  const ctx = v.ui.getContext('2d');
  ctx.clearRect(0, 0, v.ui.width, v.ui.height);
  ctx.setLineDash([6 * DPR(), 5 * DPR()]);
  ctx.strokeStyle = '#1f6feb';
  ctx.lineWidth = 1.5 * DPR();
  ctx.strokeRect((b.x - 4) * s, (b.y - 4) * s, (b.w + 8) * s, (b.h + 8) * s);
  ctx.setLineDash([]);
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc((b.x + b.w + 4) * s, (b.y + b.h + 4) * s, (HANDLE / 2) * DPR(), 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function hitSelection(x, y) {
  const b = S.sel.box;
  return x >= b.x - 8 && x <= b.x + b.w + 14 && y >= b.y - 8 && y <= b.y + b.h + 14;
}
function hitHandle(x, y) {
  const b = S.sel.box;
  return Math.hypot(x - (b.x + b.w + 4), y - (b.y + b.h + 4)) <= (HANDLE * 1.4) / S.zoom + 4;
}

function transformFn(a) {
  const b = a.box;
  if (a.kind === 'move') return (x, y) => [x + (a.dx || 0), y + (a.dy || 0)];
  const k = Math.max(0.1, Math.max((b.w + (a.dx || 0)) / (b.w || 1), (b.h + (a.dy || 0)) / (b.h || 1)));
  return (x, y) => [b.x + (x - b.x) * k, b.y + (y - b.y) * k];
}

function previewTransform() {
  const a = action, v = a.v, s = v.scale;
  const fn = transformFn(a);
  const ctx = v.live.getContext('2d');
  ctx.clearRect(0, 0, v.live.width, v.live.height);
  const moved = [...S.sel.items].map((it) => transformItem(it, fn));
  drawItems(ctx, { items: moved }, s, S.images);
  drawSelection(boxOf(moved));
  $('#sel-bar').classList.add('hidden');
}

function commitTransform(a) {
  const v = a.v;
  v.live.getContext('2d').clearRect(0, 0, v.live.width, v.live.height);
  if (!a.dx && !a.dy) { renderInk(v); drawSelection(); positionSelBar(); return; }
  const fn = transformFn(a);
  const map = new Map();
  v.page.items = v.page.items.map((it) => {
    if (!S.sel.items.has(it)) return it;
    const n = transformItem(it, fn);
    map.set(it, n);
    return n;
  });
  S.sel.items = new Set(map.values());
  S.sel.box = boxOf(S.sel.items);
  renderInk(v);
  drawSelection();
  positionSelBar();
  recordItems(v, a.before);
}

function positionSelBar() {
  const bar = $('#sel-bar');
  if (!S.sel) { bar.classList.add('hidden'); return; }
  const r = S.sel.view.el.getBoundingClientRect();
  const b = S.sel.box;
  bar.classList.remove('hidden');
  const x = r.left + (b.x + b.w / 2) * S.zoom - bar.offsetWidth / 2;
  let y = r.top + (b.y - 8) * S.zoom - bar.offsetHeight - 10;
  if (y < 120) y = r.top + (b.y + b.h + 14) * S.zoom + 10;
  bar.style.left = Math.max(8, Math.min(innerWidth - bar.offsetWidth - 8, x)) + 'px';
  bar.style.top = Math.max(118, Math.min(innerHeight - 60, y)) + 'px';
}

function selAction(kind, anchor) {
  if (!S.sel) return;
  const v = S.sel.view;
  const before = v.page.items.slice();
  if (kind === 'delete') {
    v.page.items = v.page.items.filter((it) => !S.sel.items.has(it));
    clearSelection();
    renderInk(v);
    recordItems(v, before);
  } else if (kind === 'copy') {
    S.clip = cloneItems([...S.sel.items]);
    toast('Copié — Ctrl+V ou menu ⋯ pour coller');
  } else if (kind === 'duplicate') {
    const copies = cloneItems([...S.sel.items]).map((it) => transformItem(it, (x, y) => [x + 20, y + 20]));
    v.page.items.push(...copies);
    renderInk(v);
    recordItems(v, before);
    select(v, copies);
  } else if (kind === 'color') {
    openMenu(anchor, [{ html: `<div class="sw-row">${INK_COLORS.concat(HIGHLIGHT_COLORS).map((c) => `<button class="swatch" data-c="${c}" style="background:${c}"></button>`).join('')}</div>`,
      bind: (div, close) => div.querySelectorAll('[data-c]').forEach((b) => {
        b.onclick = () => {
          close();
          const map = new Map();
          v.page.items = v.page.items.map((it) => {
            if (!S.sel.items.has(it) || it.type === 'image') return it;
            const n = { ...it, color: b.dataset.c };
            map.set(it, n);
            return n;
          });
          S.sel.items = new Set([...S.sel.items].map((it) => map.get(it) || it));
          renderInk(v);
          drawSelection();
          recordItems(v, before);
        };
      }) }]);
  }
}

function paste() {
  if (!S.clip) { toast('Rien à coller'); return; }
  const v = viewAt(S.current);
  const before = v.page.items.slice();
  const items = cloneItems(S.clip).map((it) => transformItem(it, (x, y) => [x + 24, y + 24]));
  v.page.items.push(...items);
  renderInk(v);
  recordItems(v, before);
  select(v, items);
}

// --- Texte -------------------------------------------------------------------
let textEdit = null;   // { v, item, ta, before, isNew }

function textAt(v, x, y) {
  commitText();
  const hit = [...v.page.items].reverse().find((it) => it.type === 'text' && x >= it.x && x <= it.x + it.w && y >= it.y && y <= it.y + (it.h || it.size * 1.3));
  const cfg = S.cfg.text;
  const item = hit || { type: 'text', x, y: y - cfg.size * 0.65, w: Math.min(320, v.page.w - x - 24), text: '', size: cfg.size, color: cfg.color, bold: cfg.bold };
  if (item.w < 60) { item.x = Math.max(12, v.page.w - 220); item.w = 200; }
  const ta = document.createElement('textarea');
  ta.className = 'text-edit';
  ta.value = item.text;
  v.el.appendChild(ta);
  textEdit = { v, item, ta, before: v.page.items.slice(), isNew: !hit };
  if (hit) renderInk(v, new Set([hit]));
  positionTextEditor();
  ta.oninput = positionTextEditor;
  ta.onkeydown = (e) => { if (e.key === 'Escape') { e.preventDefault(); commitText(); } e.stopPropagation(); };
  ta.onblur = () => setTimeout(() => { if (textEdit?.ta === ta && document.activeElement !== ta) commitText(); }, 0);
  ta.focus();
  setTimeout(() => ta.focus(), 0);
}

function positionTextEditor() {
  if (!textEdit) return;
  const { item, ta } = textEdit;
  const z = S.zoom;
  ta.style.left = item.x * z + 'px';
  ta.style.top = item.y * z + 'px';
  ta.style.width = item.w * z + 'px';
  ta.style.fontSize = item.size * z + 'px';
  ta.style.fontWeight = item.bold ? 700 : 400;
  ta.style.fontFamily = TEXT_FONT;
  ta.style.color = item.color;
  ta.style.height = 'auto';
  ta.style.height = Math.max(item.size * 1.3 * z, ta.scrollHeight) + 'px';
}

function commitText() {
  if (!textEdit) return;
  const { v, item, ta, before, isNew } = textEdit;
  textEdit = null;
  const text = ta.value.replace(/\s+$/, '');
  ta.remove();
  if (isNew) {
    if (text) { v.page.items.push({ ...item, text, t: Date.now() }); recordItems(v, before); }
  } else if (!text) {
    v.page.items = v.page.items.filter((it) => it !== item);
    recordItems(v, before);
  } else if (text !== item.text) {
    v.page.items = v.page.items.map((it) => (it === item ? { ...item, text } : it));
    recordItems(v, before);
  }
  renderInk(v);
}

// --- Pointeur laser (non enregistré) --------------------------------------------
let laser = { v: null, pts: [], raf: 0 };
function laserAdd(v, x, y) {
  if (laser.v && laser.v !== v) { clearUi(laser.v); laser.pts = []; }
  laser.v = v;
  laser.pts.push({ x, y, t: performance.now() });
  if (!laser.raf) laser.raf = requestAnimationFrame(laserFrame);
}
function laserFrame() {
  const v = laser.v, s = v.scale, now = performance.now();
  laser.pts = laser.pts.filter((p) => now - p.t < 700);
  const ctx = v.ui.getContext('2d');
  ctx.clearRect(0, 0, v.ui.width, v.ui.height);
  const c = S.cfg.laser.color;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (let i = 1; i < laser.pts.length; i++) {
    const a = laser.pts[i - 1], b = laser.pts[i];
    const life = 1 - (now - b.t) / 700;
    ctx.strokeStyle = c;
    ctx.globalAlpha = Math.max(0, life);
    ctx.shadowColor = c;
    ctx.shadowBlur = 12 * DPR();
    ctx.lineWidth = 4 * s;
    ctx.beginPath();
    ctx.moveTo(a.x * s, a.y * s);
    ctx.lineTo(b.x * s, b.y * s);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
  ctx.shadowBlur = 0;
  if (laser.pts.length) laser.raf = requestAnimationFrame(laserFrame);
  else { laser.raf = 0; clearUi(v); }
}

// ---------------------------------------------------------------------------
// Pages : ajout, suppression, ordre, modèle, signets
// ---------------------------------------------------------------------------
function rebuildKeepScroll() {
  const st = $('#ed-scroll').scrollTop;
  clearSelection();
  buildPages();
  layout();
  $('#ed-scroll').scrollTop = st;
  renderThumbs();
}

function addPage(at, page) {
  const d = S.nb.defaults || {};
  const ref = S.nb.pages[Math.min(at, S.nb.pages.length) - 1];
  const p = page || newPage({
    template: ref && !ref.bg ? ref.template : d.template || 'lined',
    paper: ref && !ref.bg ? ref.paper : d.paper || 'white',
    w: ref ? (ref.bg ? undefined : ref.w) : undefined,
    h: ref ? (ref.bg ? undefined : ref.h) : undefined,
    size: d.size || 'a4',
  });
  const before = S.nb.pages.slice();
  S.nb.pages.splice(at, 0, p);
  pushUndo({ type: 'pages', before, after: S.nb.pages.slice() });
  rebuildKeepScroll();
  goToPage(at);
}

function goToPage(i) {
  const v = viewAt(i);
  if (!v) return;
  const sc = $('#ed-scroll');
  sc.scrollTop += v.el.getBoundingClientRect().top - sc.getBoundingClientRect().top - 20;
}

function pageOp(i, op) {
  const before = S.nb.pages.slice();
  const pages = S.nb.pages;
  if (op === 'delete') {
    if (pages.length === 1) { toast('Un carnet garde au moins une page'); return; }
    pages.splice(i, 1);
  } else if (op === 'up' && i > 0) [pages[i - 1], pages[i]] = [pages[i], pages[i - 1]];
  else if (op === 'down' && i < pages.length - 1) [pages[i + 1], pages[i]] = [pages[i], pages[i + 1]];
  else if (op === 'duplicate') pages.splice(i + 1, 0, { ...pages[i], id: newPage().id, items: cloneItems(pages[i].items) });
  else return;
  pushUndo({ type: 'pages', before, after: pages.slice() });
  rebuildKeepScroll();
}

function setPageProp(i, props) {
  const page = S.nb.pages[i];
  const before = Object.fromEntries(Object.keys(props).map((k) => [k, page[k]]));
  Object.assign(page, props);
  pushUndo({ type: 'page-prop', pageId: page.id, before, after: { ...props } });
  layout();
  renderThumbs();
}

function templateDialog(i) {
  const page = S.nb.pages[i];
  openModal(`<h2>Papier de la page ${i + 1}</h2>
    <div class="field"><span>Modèle</span><div class="opts" id="tp-t">${Object.entries(TEMPLATES).map(([k, l]) => `<button class="opt" data-v="${k}">${esc(l)}</button>`).join('')}</div></div>
    <div class="field"><span>Couleur</span><div class="opts" id="tp-p">${Object.entries(PAPERS).map(([k, p]) => `<button class="opt" data-v="${k}">${esc(p.label)}</button>`).join('')}</div></div>
    <label class="field" style="flex-direction:row;align-items:center;gap:10px"><input type="checkbox" id="tp-all"> Appliquer à toutes les pages (sauf PDF)</label>
    <div class="modal-actions"><button class="btn ghost" data-a="no">Annuler</button><button class="btn primary" data-a="ok">Appliquer</button></div>`,
  (card, close) => {
    const st = { template: page.template, paper: page.paper };
    for (const [sel, key] of [['#tp-t', 'template'], ['#tp-p', 'paper']]) {
      const box = card.querySelector(sel);
      const sync = () => box.querySelectorAll('[data-v]').forEach((b) => b.classList.toggle('active', b.dataset.v === st[key]));
      box.querySelectorAll('[data-v]').forEach((b) => { b.onclick = () => { st[key] = b.dataset.v; sync(); }; });
      sync();
    }
    card.querySelector('[data-a=no]').onclick = close;
    card.querySelector('[data-a=ok]').onclick = () => {
      close();
      if (card.querySelector('#tp-all').checked) {
        const before = S.nb.pages.slice();
        S.nb.pages = S.nb.pages.map((p) => (p.bg ? p : { ...p, ...st }));
        S.nb.defaults = { ...(S.nb.defaults || {}), ...st };
        pushUndo({ type: 'pages', before, after: S.nb.pages.slice() });
        rebuildKeepScroll();
      } else setPageProp(i, st);
    };
  });
}

// --- Miniatures ------------------------------------------------------------------
function toggleSidebar() {
  const sb = $('#ed-sidebar');
  sb.classList.toggle('hidden');
  $('#ed-pages-btn').classList.toggle('on', !sb.classList.contains('hidden'));
  if (!sb.classList.contains('hidden')) renderThumbs();
  setTimeout(() => layout(), 0);
}

const thumbTimers = new Map();
function scheduleThumb(page) {
  if ($('#ed-sidebar').classList.contains('hidden')) return;
  clearTimeout(thumbTimers.get(page.id));
  thumbTimers.set(page.id, setTimeout(() => {
    const el = document.querySelector(`.thumb[data-id="${page.id}"] canvas`);
    if (el) drawThumb(el, page);
  }, 400));
}

async function drawThumb(c, page) {
  const s = 150 / page.w;
  c.width = 150; c.height = Math.round(page.h * s);
  const ctx = c.getContext('2d');
  drawPaper(ctx, page, s);
  if (page.bg?.type === 'pdf') {
    try {
      const tmp = document.createElement('canvas');
      tmp.width = c.width; tmp.height = c.height;
      await renderPdfPage(tmp, S.nb.id, page.bg, s);
      ctx.drawImage(tmp, 0, 0);
    } catch { /* miniature sans fond */ }
  }
  drawItems(ctx, page, s, S.images);
}

function renderThumbs() {
  const box = $('#ed-thumbs');
  if (!S.nb || $('#ed-sidebar').classList.contains('hidden')) return;
  const marked = document.querySelector('.side-head .tab.active')?.dataset.side === 'marked';
  box.innerHTML = '';
  const io = new IntersectionObserver((ents) => ents.forEach((en) => {
    if (en.isIntersecting && !en.target._drawn) { en.target._drawn = true; drawThumb(en.target.querySelector('canvas'), en.target._page); }
  }), { root: box, rootMargin: '300px' });
  S.nb.pages.forEach((page, i) => {
    if (marked && !page.marked) return;
    const t = document.createElement('div');
    t.className = 'thumb' + (i === S.current ? ' current' : '');
    t.dataset.i = i;
    t.dataset.id = page.id;
    t._page = page;
    t.innerHTML = `<canvas></canvas><span class="n">${i + 1}</span>${page.marked ? `<span class="bm">${icon('bookmark', 18)}</span>` : ''}<button class="tm" title="Options">${icon('more', 16)}</button>`;
    t.onclick = (e) => { if (!e.target.closest('.tm')) goToPage(i); };
    t.querySelector('.tm').onclick = (e) => { e.stopPropagation(); pageMenu(e.currentTarget, i); };
    box.appendChild(t);
    io.observe(t);
  });
  if (marked && !box.children.length) box.innerHTML = '<p style="color:var(--fg-3);font-size:13px;text-align:center">Aucun signet.<br>Menu ⋯ → « Ajouter un signet ».</p>';
}

function pageMenu(anchor, i) {
  const page = S.nb.pages[i];
  openMenu(anchor, [
    { label: 'Ajouter une page après', icon: 'plus', action: () => addPage(i + 1) },
    { label: 'Dupliquer la page', icon: 'duplicate', action: () => pageOp(i, 'duplicate') },
    { label: page.marked ? 'Retirer le signet' : 'Ajouter un signet', icon: 'bookmark', action: () => setPageProp(i, { marked: !page.marked }) },
    ...(page.bg ? [] : [{ label: 'Papier de la page…', icon: 'template', action: () => templateDialog(i) }]),
    'sep',
    { label: 'Monter', icon: 'up', action: () => pageOp(i, 'up') },
    { label: 'Descendre', icon: 'down', action: () => pageOp(i, 'down') },
    'sep',
    { label: 'Supprimer la page', icon: 'trash', danger: true, action: () => pageOp(i, 'delete') },
  ]);
}

// ---------------------------------------------------------------------------
// Menu « plus », images, PDF, clavier
// ---------------------------------------------------------------------------
function moreMenu(anchor) {
  const i = S.current;
  const page = S.nb.pages[i];
  openMenu(anchor, [
    { label: 'Ajouter une page', icon: 'plus', action: () => addPage(i + 1) },
    { label: page.marked ? 'Retirer le signet' : 'Ajouter un signet', icon: 'bookmark', action: () => setPageProp(i, { marked: !page.marked }) },
    ...(page.bg ? [] : [{ label: 'Papier de la page…', icon: 'template', action: () => templateDialog(i) }]),
    { label: 'Insérer un PDF ici', icon: 'import', action: () => pickPdfInto(i + 1) },
    { label: 'Coller', icon: 'copy', action: paste },
    'sep',
    { label: 'Ajuster à la largeur', icon: 'zoomfit', action: () => { S.zoom = fitZoom(); layout(); } },
    { label: 'Exporter en PDF', icon: 'export', action: async () => { await flushSave(); exportById(S.nb.id); } },
  ]);
}

function pickPdfInto(at) {
  const inp = $('#file-pdf');
  inp.value = '';
  inp.onchange = async () => {
    for (const file of inp.files) {
      try {
        toast(`Import de ${file.name}…`, 60000);
        const pages = await importPdf(S.nb, file);
        const before = S.nb.pages.slice();
        S.nb.pages.splice(at, 0, ...pages);
        pushUndo({ type: 'pages', before, after: S.nb.pages.slice() });
        rebuildKeepScroll();
        goToPage(at);
        toast(`${pages.length} pages ajoutées`);
        at += pages.length;
      } catch (e) {
        toast('Import impossible : ' + e.message, 5000);
      }
    }
  };
  inp.click();
}

function pickImage() {
  const inp = $('#file-img');
  inp.value = '';
  inp.onchange = async () => {
    const file = inp.files[0];
    if (!file) return;
    try {
      const bmp = await createImageBitmap(file);
      let blob = file, ext = file.type === 'image/jpeg' ? 'jpg' : 'png';
      if (file.type !== 'image/jpeg' && file.type !== 'image/png') {
        const c = document.createElement('canvas');
        c.width = bmp.width; c.height = bmp.height;
        c.getContext('2d').drawImage(bmp, 0, 0);
        blob = await new Promise((r) => c.toBlob(r, 'image/png'));
        ext = 'png';
      }
      const buf = await blob.arrayBuffer();
      const name = await hashName(buf, ext);
      await api.putAsset(S.nb.id, name, new Blob([buf], { type: ext === 'jpg' ? 'image/jpeg' : 'image/png' }));
      const img = new Image();
      img.src = URL.createObjectURL(new Blob([buf]));
      S.images.set(name, img);
      await img.decode().catch(() => {});
      const v = viewAt(S.current);
      const w = Math.min(v.page.w * 0.6, bmp.width), h = (w * bmp.height) / bmp.width;
      const sc = $('#ed-scroll');
      const r = v.el.getBoundingClientRect();
      const midY = Math.min(v.page.h - h - 20, Math.max(20, (sc.getBoundingClientRect().top + sc.clientHeight / 2 - r.top) / S.zoom - h / 2));
      const item = { type: 'image', asset: name, x: (v.page.w - w) / 2, y: midY, w, h, t: Date.now() };
      const before = v.page.items.slice();
      v.page.items.push(item);
      renderInk(v);
      recordItems(v, before);
      select(v, [item]);
    } catch (e) {
      toast('Image impossible : ' + e.message, 4000);
    }
  };
  inp.click();
}

function onKey(e) {
  if (!S.nb || $('#editor').classList.contains('hidden')) return;
  if (textEdit || e.target.closest('input, textarea, select') || !$('#modal').classList.contains('hidden')) return;
  const k = e.key.toLowerCase();
  const mod = e.ctrlKey || e.metaKey;
  if (mod && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  else if (mod && k === 'y') { e.preventDefault(); redo(); }
  else if (mod && k === 'c' && S.sel) { e.preventDefault(); selAction('copy'); }
  else if (mod && k === 'v') { e.preventDefault(); paste(); }
  else if (mod && k === 'd' && S.sel) { e.preventDefault(); selAction('duplicate'); }
  else if (mod && k === 's') { e.preventDefault(); flushSave(); }
  else if ((k === 'delete' || k === 'backspace') && S.sel) { e.preventDefault(); selAction('delete'); }
  else if (k === 'escape') clearSelection();
  else if (mod && (k === '+' || k === '=')) { e.preventDefault(); zoomAt(S.zoom * 1.2, innerWidth / 2, innerHeight / 2); }
  else if (mod && k === '-') { e.preventDefault(); zoomAt(S.zoom / 1.2, innerWidth / 2, innerHeight / 2); }
  else if (mod && k === '0') { e.preventDefault(); S.zoom = fitZoom(); layout(); }
  else if (!mod) {
    const map = { p: 'pen', h: 'highlighter', e: 'eraser', l: 'lasso', s: 'shape', t: 'text' };
    if (map[k]) setTool(map[k]);
  }
}
