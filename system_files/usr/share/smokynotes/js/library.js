// Bibliothèque : couvertures des carnets, création, import de PDF.
import { api } from './api.js';
import { COVERS, PAGE_SIZES, PAPERS, TEMPLATES, newNotebook, newPage, uid } from './model.js';
import { drawPaper } from './render.js';
import { icon, hydrateIcons } from './icons.js';
import { $, esc, toast, openMenu, openModal, confirmBox, promptBox } from './ui.js';
import { importPdf, exportNotebook } from './pdfdoc.js';

let notebooks = [];
let filter = 'all';      // 'all' | 'fav' | 'f:<classeur>'
let openEditor = () => {};

const fmt = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' });

export function initLibrary(onOpen) {
  openEditor = onOpen;
  hydrateIcons($('#library'));
  $('#lib-new').onclick = () => newNotebookDialog();
  $('#lib-import').onclick = () => pickPdf();
  $('#lib-search').oninput = render;
  $('#lib-sort').onchange = render;
  document.querySelectorAll('.lib-tabs .tab').forEach((t) => {
    t.onclick = () => {
      filter = t.dataset.filter;
      render();
    };
  });
}

export async function showLibrary() {
  $('#editor').classList.add('hidden');
  $('#library').classList.remove('hidden');
  try {
    notebooks = await api.list();
  } catch (e) {
    toast('Impossible de lire les carnets : ' + e.message);
    notebooks = [];
  }
  render();
}

function renderFolders() {
  const tabs = document.querySelector('.lib-tabs');
  tabs.querySelectorAll('.tab.folder').forEach((t) => t.remove());
  const folders = [...new Set(notebooks.map((n) => n.folder).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'fr'));
  if (filter.startsWith('f:') && !folders.includes(filter.slice(2))) filter = 'all';
  const sort = $('#lib-sort');
  for (const f of folders) {
    const b = document.createElement('button');
    b.className = 'tab folder' + (filter === 'f:' + f ? ' active' : '');
    b.innerHTML = icon('folder', 16) + ' ' + esc(f);
    b.style.display = 'inline-flex'; b.style.alignItems = 'center'; b.style.gap = '6px';
    b.onclick = () => { filter = 'f:' + f; syncTabs(); render(); };
    tabs.insertBefore(b, sort);
  }
  syncTabs();
}

function syncTabs() {
  document.querySelectorAll('.lib-tabs .tab').forEach((t) => {
    const key = t.dataset.filter || (t.classList.contains('folder') ? 'f:' + t.textContent.trim() : '');
    t.classList.toggle('active', key === filter);
  });
}

function render() {
  renderFolders();
  const q = $('#lib-search').value.trim().toLowerCase();
  const sort = $('#lib-sort').value;
  let list = notebooks.filter((n) => (filter === 'fav' ? n.favorite : filter.startsWith('f:') ? n.folder === filter.slice(2) : true) && (!q || (n.title || '').toLowerCase().includes(q)));
  list.sort((a, b) => (sort === 'title' ? (a.title || '').localeCompare(b.title || '', 'fr') : (b[sort] || 0) - (a[sort] || 0)));
  const grid = $('#lib-grid');
  grid.innerHTML = '';
  $('#lib-empty').classList.toggle('hidden', notebooks.length > 0);
  for (const n of list) {
    const c = COVERS[n.cover] || COVERS.graphite;
    const card = document.createElement('div');
    card.className = 'nb-card';
    card.innerHTML = `
      <div class="nb-cover" style="background:linear-gradient(155deg, ${c.a}, ${c.b});color:${c.fg}">
        <div class="cv-smoke"></div>
        <div class="cv-title">${esc(n.title || 'Sans titre')}</div>
        <div class="cv-label"></div>
        ${n.favorite ? `<span class="nb-fav">${icon('star', 18)}</span>` : ''}
      </div>
      <div class="nb-meta">
        <span class="t">${esc(n.title || 'Sans titre')}</span>
        <button class="nb-menu" title="Options">${icon('more', 18)}</button>
      </div>
      <div class="nb-meta"><span class="d">${fmt.format(new Date(n.updated || n.created || Date.now()))} · ${n.pages || 1} page${(n.pages || 1) > 1 ? 's' : ''}</span></div>`;
    card.querySelector('.nb-cover').onclick = () => openEditor(n.id);
    card.querySelector('.nb-menu').onclick = (e) => { e.stopPropagation(); cardMenu(e.currentTarget, n); };
    grid.appendChild(card);
  }
}

async function mutate(id, fn) {
  const nb = await api.load(id);
  fn(nb);
  await api.save(nb);
  await showLibrary();
}

function cardMenu(anchor, n) {
  openMenu(anchor, [
    { label: 'Ouvrir', icon: 'edit', action: () => openEditor(n.id) },
    { label: 'Renommer', icon: 'text', action: async () => {
      const t = await promptBox('Renommer le carnet', n.title || 'Sans titre');
      if (t) mutate(n.id, (nb) => { nb.title = t; });
    } },
    { label: n.favorite ? 'Retirer des favoris' : 'Ajouter aux favoris', icon: 'star', action: () => mutate(n.id, (nb) => { nb.favorite = !nb.favorite; }) },
    { label: n.folder ? `Classeur : ${n.folder}…` : 'Ranger dans un classeur…', icon: 'folder', action: async () => {
      const f = await promptBox('Nom du classeur (vide pour aucun)', n.folder || '');
      if (f !== null) mutate(n.id, (nb) => { nb.folder = f === ' ' ? '' : f.trim(); });
    } },
    { html: `<div class="sw-row">${Object.entries(COVERS).map(([k, c]) => `<button class="cover-opt" data-c="${k}" title="${esc(c.label)}" style="width:26px;height:34px;padding:0;background:linear-gradient(155deg,${c.a},${c.b})"></button>`).join('')}</div>`,
      bind: (div, close) => div.querySelectorAll('[data-c]').forEach((b) => { b.onclick = () => { close(); mutate(n.id, (nb) => { nb.cover = b.dataset.c; }); }; }) },
    'sep',
    { label: 'Dupliquer', icon: 'duplicate', action: async () => {
      const id = uid('n');
      await api.duplicate(n.id, id);
      await mutate(id, (nb) => { nb.id = id; nb.title = (nb.title || 'Sans titre') + ' (copie)'; nb.created = Date.now(); });
    } },
    { label: 'Exporter en PDF', icon: 'export', action: () => exportById(n.id) },
    'sep',
    { label: 'Supprimer', icon: 'trash', danger: true, action: async () => {
      if (await confirmBox('Supprimer ce carnet ?', `« ${n.title} » sera déplacé dans la corbeille (Notes/Smoky Notes/.corbeille).`)) {
        await api.remove(n.id);
        showLibrary();
      }
    } },
  ]);
}

export async function exportById(id) {
  try {
    toast('Export en cours…', 60000);
    const nb = await api.load(id);
    const bytes = await exportNotebook(nb);
    const name = (nb.title || 'Sans titre').replace(/[\\/:*?"<>|\x00-\x1f]/g, '-').slice(0, 100) + '.pdf';
    const res = await api.exportPdf(name, bytes);
    toast('PDF enregistré dans Notes/PDF : ' + name, 4500);
    return res;
  } catch (e) {
    toast('Export impossible : ' + e.message, 5000);
  }
}

function tplCanvas(template, paper) {
  const c = document.createElement('canvas');
  c.width = 108; c.height = 144;
  const page = { w: 595, h: 842, template, paper, bg: null };
  drawPaper(c.getContext('2d'), page, 108 / 595);
  return c;
}

export function newNotebookDialog() {
  const st = { title: 'Nouveau carnet', cover: 'graphite', template: 'lined', paper: 'white', size: 'a4' };
  openModal(`
    <h2>Nouveau carnet</h2>
    <label class="field"><span>Titre</span><input type="text" id="nn-title" value="${esc(st.title)}"></label>
    <div class="field"><span>Couverture</span><div class="opts" id="nn-cover">${Object.entries(COVERS).map(([k, c]) => `<button class="cover-opt" data-v="${k}" title="${esc(c.label)}" style="background:linear-gradient(155deg,${c.a},${c.b})"></button>`).join('')}</div></div>
    <div class="field"><span>Papier</span><div class="opts" id="nn-tpl"></div></div>
    <div class="field"><span>Couleur du papier</span><div class="opts" id="nn-paper">${Object.entries(PAPERS).map(([k, p]) => `<button class="opt" data-v="${k}">${esc(p.label)}</button>`).join('')}</div></div>
    <div class="field"><span>Format</span><div class="opts" id="nn-size">${Object.entries(PAGE_SIZES).map(([k, p]) => `<button class="opt" data-v="${k}">${esc(p.label)}</button>`).join('')}</div></div>
    <div class="modal-actions"><button class="btn ghost" data-a="no">Annuler</button><button class="btn primary" data-a="ok">Créer</button></div>`,
  (card, close) => {
    const tpl = card.querySelector('#nn-tpl');
    const drawTpls = () => {
      tpl.innerHTML = '';
      for (const [k, label] of Object.entries(TEMPLATES)) {
        const b = document.createElement('button');
        b.className = 'opt tpl-opt' + (k === st.template ? ' active' : '');
        b.dataset.v = k;
        b.appendChild(tplCanvas(k, st.paper));
        b.insertAdjacentHTML('beforeend', `<span>${esc(label)}</span>`);
        b.onclick = () => { st.template = k; drawTpls(); };
        tpl.appendChild(b);
      }
    };
    const group = (sel, key, after) => {
      const box = card.querySelector(sel);
      const sync = () => box.querySelectorAll('[data-v]').forEach((b) => b.classList.toggle('active', b.dataset.v === st[key]));
      box.querySelectorAll('[data-v]').forEach((b) => { b.onclick = () => { st[key] = b.dataset.v; sync(); after?.(); }; });
      sync();
    };
    group('#nn-cover', 'cover');
    group('#nn-paper', 'paper', drawTpls);
    group('#nn-size', 'size');
    drawTpls();
    card.querySelector('[data-a=no]').onclick = close;
    card.querySelector('[data-a=ok]').onclick = async () => {
      st.title = card.querySelector('#nn-title').value.trim() || 'Sans titre';
      const nb = newNotebook(st);
      if (filter.startsWith('f:')) nb.folder = filter.slice(2);
      await api.save(nb);
      close();
      openEditor(nb.id);
    };
  });
}

function pickPdf() {
  const inp = $('#file-pdf');
  inp.value = '';
  inp.onchange = async () => {
    for (const file of inp.files) {
      try {
        toast(`Import de ${file.name}…`, 60000);
        const nb = newNotebook({ title: file.name.replace(/\.pdf$/i, ''), cover: 'slate', template: 'blank' });
        nb.pages = await importPdf(nb, file);
        nb.defaults.template = 'lined';
        await api.save(nb);
        toast(`« ${nb.title} » importé (${nb.pages.length} pages)`);
      } catch (e) {
        toast('Import impossible : ' + e.message, 5000);
      }
    }
    showLibrary();
  };
  inp.click();
}

export { newPage };
