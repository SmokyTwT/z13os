// Petits éléments d'interface : notifications, menus, fenêtres.
import { icon, hydrateIcons } from './icons.js';

export const $ = (sel, root = document) => root.querySelector(sel);
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let toastTimer;
export function toast(msg, ms = 2600) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), ms);
}

// Menu contextuel. entries: [{ label, icon, action, danger }] | 'sep' | { html, bind }
export function openMenu(anchor, entries) {
  const m = $('#menu');
  m.innerHTML = '';
  for (const e of entries) {
    if (e === 'sep') { m.appendChild(document.createElement('hr')); continue; }
    if (e.html) {
      const div = document.createElement('div');
      div.innerHTML = e.html;
      m.appendChild(div);
      e.bind?.(div, closeMenu);
      continue;
    }
    const b = document.createElement('button');
    if (e.danger) b.className = 'danger';
    b.innerHTML = (e.icon ? icon(e.icon, 18) : '') + `<span>${esc(e.label)}</span>` + (e.check ? `<span style="margin-left:auto">${icon('check', 16)}</span>` : '');
    b.onclick = () => { closeMenu(); e.action(); };
    m.appendChild(b);
  }
  m.classList.remove('hidden');
  const r = anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : { left: anchor.x, right: anchor.x, top: anchor.y, bottom: anchor.y };
  const mw = m.offsetWidth, mh = m.offsetHeight;
  let x = Math.min(r.left, innerWidth - mw - 10);
  let y = r.bottom + 6;
  if (y + mh > innerHeight - 10) y = Math.max(10, r.top - mh - 6);
  m.style.left = Math.max(10, x) + 'px';
  m.style.top = y + 'px';
  setTimeout(() => addEventListener('pointerdown', outside, true), 0);
}
function outside(e) {
  if (!$('#menu').contains(e.target)) closeMenu();
}
export function closeMenu() {
  $('#menu').classList.add('hidden');
  removeEventListener('pointerdown', outside, true);
}

export function openModal(html, bind) {
  const modal = $('#modal');
  const card = $('#modal-card');
  card.innerHTML = html;
  hydrateIcons(card);
  modal.classList.remove('hidden');
  const close = () => modal.classList.add('hidden');
  modal.onpointerdown = (e) => { if (e.target === modal) close(); };
  bind(card, close);
  const first = card.querySelector('input[type=text]');
  if (first) setTimeout(() => { first.focus(); first.select(); }, 30);
  return close;
}

export function confirmBox(title, text, okLabel = 'Supprimer') {
  return new Promise((resolve) => {
    openModal(`<h2>${esc(title)}</h2><p style="color:var(--fg-2)">${esc(text)}</p>
      <div class="modal-actions"><button class="btn ghost" data-a="no">Annuler</button><button class="btn danger" data-a="ok">${esc(okLabel)}</button></div>`,
    (card, close) => {
      card.querySelector('[data-a=no]').onclick = () => { close(); resolve(false); };
      card.querySelector('[data-a=ok]').onclick = () => { close(); resolve(true); };
    });
  });
}

export function promptBox(title, value) {
  return new Promise((resolve) => {
    openModal(`<h2>${esc(title)}</h2><label class="field"><input type="text" value="${esc(value)}"></label>
      <div class="modal-actions"><button class="btn ghost" data-a="no">Annuler</button><button class="btn primary" data-a="ok">OK</button></div>`,
    (card, close) => {
      const inp = card.querySelector('input');
      const ok = () => { close(); resolve(inp.value.trim()); };
      inp.onkeydown = (e) => { if (e.key === 'Enter') ok(); };
      card.querySelector('[data-a=no]').onclick = () => { close(); resolve(null); };
      card.querySelector('[data-a=ok]').onclick = ok;
    });
  });
}
