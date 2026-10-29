// Smoky Agenda : semaine (cours fixes + blocs planifiés), tâches à caser, ajout et réglages.
'use strict';
// Code d'accès au serveur local : transmis par le lanceur dans l'adresse (#k=…), jamais écrit dans
// la page (un autre programme du PC qui lirait la page ne l'obtient pas). Gardé pour les rechargements.
const TOKEN = (() => {
  const m = location.hash.match(/k=([A-Za-z0-9_-]+)/);
  if (m) {
    try { sessionStorage.setItem('smoky-k', m[1]); } catch { /* stockage indisponible */ }
    history.replaceState(null, '', location.pathname);
    return m[1];
  }
  try { return sessionStorage.getItem('smoky-k') || ''; } catch { return ''; }
})();
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let S = null;
let week = 0;
let addKind = 'block';
let toastTimer = 0;

function toast(msg, ms = 3200) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  t.style.animation = 'none'; void t.offsetWidth; t.style.animation = '';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), ms);
}

async function api(path, body) {
  const r = await fetch('/api/' + path, {
    method: body ? 'POST' : 'GET',
    headers: { 'X-Smoky-Token': TOKEN, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

async function act(body, okMsg) {
  const r = await api('action', { week, ...body });
  if (!r.ok) toast(r.message || 'Action impossible', 5000);
  else if (r.message || okMsg) toast(r.message || okMsg);
  return r;
}

// --- Temps --------------------------------------------------------------------------------------
const mins = (hhmm) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
const timeOf = (isoStr) => isoStr.slice(11, 16);
const dayOf = (isoStr) => isoStr.slice(0, 10);
const addDays = (d, n) => { const x = new Date(d + 'T12:00'); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
const fmtShort = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' });
const fmtDay = new Intl.DateTimeFormat('fr-FR', { weekday: 'short' });
const fmtLong = new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });

// --- Affichage de la semaine ---------------------------------------------------------------------
function render() {
  const st = S.settings;
  const top = Math.max(0, Math.floor(mins(st.wake) / 60) - 1) * 60;
  const bottom = Math.min(24, Math.ceil(mins(st.sleep) / 60) + 1) * 60;
  const hour = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--hour')) || 52;
  const px = hour / 60;
  const days = [...Array(7)].map((_, i) => addDays(S.week_start, i));
  $('#range').textContent = `${fmtShort.format(new Date(days[0] + 'T12:00'))} – ${fmtShort.format(new Date(days[6] + 'T12:00'))}`;

  const items = [...S.fixed.map((e) => ({ ...e, fixed: true })), ...S.plan];
  let html = '<div class="dh"></div>';
  for (const d of days) {
    const dt = new Date(d + 'T12:00');
    html += `<div class="dh ${d === S.today ? 'today' : ''}"><span>${fmtDay.format(dt)}</span><b>${dt.getDate()}</b></div>`;
  }
  html += '<div class="allday"></div>';
  for (const d of days) {
    const all = items.filter((e) => e.allday && dayOf(e.start) <= d && d < (dayOf(e.end) || d));
    html += `<div class="allday">${all.map((e) => `<div title="${esc(e.title)}">${esc(e.title)}</div>`).join('')}</div>`;
  }
  html += `<div class="hours" style="height:${(bottom - top) * px}px">`;
  for (let m = top; m < bottom; m += 60) html += `<div>${String(m / 60).padStart(2, '0')}:00</div>`;
  html += '</div>';
  for (const d of days) {
    const list = items.filter((e) => !e.allday && dayOf(e.start) === d).sort((a, b) => a.start.localeCompare(b.start));
    // chevauchements : côte à côte
    const lanes = [];
    for (const e of list) {
      let lane = lanes.findIndex((end) => end <= e.start);
      if (lane < 0) { lane = lanes.length; lanes.push(e.end); } else lanes[lane] = e.end;
      e._lane = lane;
    }
    const n = Math.max(1, lanes.length);
    html += `<div class="col ${d === S.today ? 'today' : ''}" style="height:${(bottom - top) * px}px">`;
    for (const e of list) {
      const s = Math.max(top, mins(timeOf(e.start))), f = Math.min(bottom, mins(timeOf(e.end)));
      if (f <= top || s >= bottom) continue;
      const w = 100 / n;
      html += `<div class="blk ${e.fixed ? 'fixed' : ''} ${e.done ? 'done' : ''}" data-id="${esc(e.id)}"
        style="--c:var(--${esc(e.type)}, var(--perso));top:${(s - top) * px}px;height:${Math.max(18, (f - s) * px - 2)}px;left:calc(${e._lane * w}% + 3px);right:auto;width:calc(${w}% - 6px)">
        <b>${esc(e.title)}</b><span>${timeOf(e.start)} – ${timeOf(e.end)}${e.where ? ' · ' + esc(e.where) : ''}</span></div>`;
    }
    if (d === S.today) {
      const nm = mins(S.now.slice(11, 16));
      if (nm > top && nm < bottom) html += `<div class="now" style="top:${(nm - top) * px}px"></div>`;
    }
    html += '</div>';
  }
  $('#week').innerHTML = html;
  document.querySelectorAll('.blk').forEach((el) => { el.onclick = (ev) => openPop(el.dataset.id, ev); });

  // colonne de gauche
  const today = items.filter((e) => !e.allday && dayOf(e.start) === S.today).sort((a, b) => a.start.localeCompare(b.start));
  $('#agenda-today').innerHTML = today.length ? today.map((e) => `<div class="it ${e.done ? 'done' : ''}"><i class="dot" style="color:var(--${esc(e.type)})"></i>
    <span class="t">${timeOf(e.start)}</span>${esc(e.title)}</div>`).join('') : '<p class="hint">Rien de prévu (ou autre semaine affichée).</p>';
  const tasks = S.tasks.filter((t) => !t.done);
  $('#tasks').innerHTML = tasks.length ? tasks.map((t) => `<div class="it"><i class="dot" style="color:var(--tache)"></i>${esc(t.title)}
    <span class="t">${t.minutes} min${t.due ? ' · ' + fmtShort.format(new Date(t.due.slice(0, 10) + 'T12:00')) : ''}</span>
    <button data-del="${esc(t.id)}" title="Supprimer">✕</button></div>`).join('') : '<p class="hint">Aucune tâche en attente.</p>';
  document.querySelectorAll('[data-del]').forEach((b) => { b.onclick = async () => { await act({ action: 'delete', id: b.dataset.del }); refresh(); }; });
  $('#legend').innerHTML = Object.entries(S.types).map(([k, l]) => `<span><i class="dot" style="color:var(--${k})"></i>${esc(l)}</span>`).join('');
  $('#info').textContent = (S.settings.ics_url ? (S.edt_ok && !S.edt_error ? 'Emploi du temps relié. '
      : `Emploi du temps : lien pas lu${S.edt_error ? ' (' + S.edt_error + ')' : ''}. `)
    : S.edt_file ? 'Emploi du temps importé depuis un fichier. ' : 'Relie ton emploi du temps dans les réglages. ') + (S.planned_by === 'claude' ? 'Dernier planning fait par Claude. ' : '')
    + `Le planning est aussi dans Notes/Planning Smoky.ics.`;
  $('#plan-claude').disabled = !S.claude;
  $('#plan-claude').title = S.claude ? 'Claude organise ta semaine (ton compte Claude)' : 'Connecte d’abord ton compte Claude (Smoky Mail → Réglages)';
}

// --- Détail d'un bloc ---------------------------------------------------------------------------------
function openPop(id, ev) {
  const e = [...S.fixed.map((x) => ({ ...x, fixed: true })), ...S.plan].find((x) => x.id === id);
  if (!e) return;
  const pop = $('#pop');
  const canEdit = !e.fixed || e.source === 'toi';
  const min = mins(timeOf(e.end)) - mins(timeOf(e.start));
  pop.innerHTML = `<h3>${esc(e.title)}</h3>
    <div class="meta">${esc(fmtLong.format(new Date(dayOf(e.start) + 'T12:00')))} · ${timeOf(e.start)} – ${timeOf(e.end)}${e.where ? '<br>' + esc(e.where) : ''}
    <br>${esc(S.types[e.type] || '')}${e.source === 'edt' ? ' · emploi du temps' : e.source === 'moodle' ? ' · échéance Moodle' : ''}</div>
    <div class="btns">
      ${e.fixed ? '' : `<button class="btn primary" data-p="toggle">${e.done ? 'Pas fait' : 'Fait ✓'}</button>`}
      ${e.type === 'revision' && !e.done ? `<button class="btn" data-p="focus">Concentration ${Math.min(min, 240)} min</button>` : ''}
      ${canEdit ? '<button class="btn danger" data-p="delete">Supprimer</button>' : ''}
      <button class="btn" data-p="close">Fermer</button>
    </div>`;
  pop.classList.remove('hidden');
  const r = pop.getBoundingClientRect();
  pop.style.left = Math.min(window.innerWidth - r.width - 12, ev.clientX + 10) + 'px';
  pop.style.top = Math.min(window.innerHeight - r.height - 12, ev.clientY + 10) + 'px';
  pop.querySelectorAll('[data-p]').forEach((b) => {
    b.onclick = async () => {
      const p = b.dataset.p;
      pop.classList.add('hidden');
      if (p === 'toggle') { await act({ action: 'toggle', id }); refresh(); }
      if (p === 'delete') { await act({ action: 'delete', id }, 'Supprimé'); refresh(); }
      if (p === 'focus') act({ action: 'focus', minutes: Math.max(5, Math.min(min, 240)) }, 'Concentration lancée : les sites qui distraient sont bloqués');
    };
  });
}
document.addEventListener('click', (ev) => {
  const pop = $('#pop');
  if (!pop.classList.contains('hidden') && !pop.contains(ev.target) && !ev.target.closest('.blk')) pop.classList.add('hidden');
});

// --- Planifier ------------------------------------------------------------------------------------------
async function plan(claude) {
  const b = claude ? $('#plan-claude') : $('#plan');
  const label = b.textContent;
  b.disabled = true;
  b.textContent = claude ? 'Claude réfléchit…' : 'Planification…';
  await act({ action: 'plan', claude });
  b.disabled = false;
  b.textContent = label;
  refresh();
}
$('#plan').onclick = () => plan(false);
$('#plan-claude').onclick = () => plan(true);
$('#prev').onclick = () => { week -= 1; refresh(); };
$('#next').onclick = () => { week += 1; refresh(); };
$('#today').onclick = () => { week = 0; refresh(); };

// --- Ajouter ---------------------------------------------------------------------------------------------
function openAdder(kind) {
  addKind = kind;
  document.querySelectorAll('#add-kind button').forEach((b) => b.classList.toggle('on', b.dataset.k === kind));
  $('#a-when').classList.toggle('hidden', kind === 'task');
  $('#a-task').classList.toggle('hidden', kind !== 'task');
  $('#a-type').innerHTML = Object.entries(S.types).filter(([k]) => k !== 'devoir' && (kind === 'event' || k !== 'cours'))
    .map(([k, l]) => `<option value="${k}" ${k === (kind === 'event' ? 'perso' : 'revision') ? 'selected' : ''}>${esc(l)}</option>`).join('');
  if (!$('#a-day').value) $('#a-day').value = S.today;
  $('#adder').classList.remove('hidden');
  $('#a-title').focus();
}
document.querySelectorAll('#add-kind button').forEach((b) => { b.onclick = () => openAdder(b.dataset.k); });
$('#add').onclick = () => openAdder('block');
$('#add-task').onclick = () => openAdder('task');
$('#a-cancel').onclick = () => $('#adder').classList.add('hidden');
$('#a-save').onclick = async () => {
  const title = $('#a-title').value;
  let r;
  if (addKind === 'task') {
    r = await act({ action: 'add_task', title, minutes: Number($('#a-min').value), due: $('#a-due').value }, 'Tâche ajoutée : elle sera casée au prochain planning');
  } else {
    const d = $('#a-day').value;
    r = await act({ action: addKind === 'event' ? 'add_event' : 'add_block', title, type: $('#a-type').value,
      start: `${d}T${$('#a-start').value}`, end: `${d}T${$('#a-end').value}`, where: $('#a-where').value }, 'Ajouté');
  }
  if (r.ok) { $('#adder').classList.add('hidden'); $('#a-title').value = ''; refresh(); }
};

// --- Réglages ---------------------------------------------------------------------------------------------
const FIELDS = ['wake', 'sleep', 'lunch', 'dinner', 'meal_min', 'commute_min', 'gym_per_week', 'gym_min', 'gym_from', 'gym_to',
  'groceries_day', 'groceries_time', 'groceries_min', 'revision_weekday_min', 'revision_weekend_min', 'block_min', 'remind_before', 'model'];
function openPrefs() {
  const st = S.settings;
  $('#p-groceries_day').innerHTML = S.days.map((d, i) => `<option value="${i}">${d}</option>`).join('');
  $('#p-model').innerHTML = Object.entries(S.models).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('');
  for (const f of FIELDS) $('#p-' + f).value = st[f];
  $('#p-ics').value = st.ics_url;
  $('#p-subjects').value = st.subjects.join(', ');
  $('#p-reminders').checked = st.reminders;
  $('#p-icsremove').hidden = !S.edt_file;
  $('#p-claude').textContent = S.claude ? '✅ Compte Claude connecté : « ✨ Avec Claude » organise ta semaine (ça compte dans ton forfait).'
    : 'Pour « ✨ Avec Claude », connecte ton compte Claude dans Smoky Mail → Réglages (une seule fois pour tout Smoky OS).';
  $('#prefs').classList.remove('hidden');
}
$('#prefs-btn').onclick = openPrefs;
$('#p-icsfile').onchange = async (ev) => {
  const f = ev.target.files[0];
  ev.target.value = '';
  if (!f) return;
  if (f.size > 5 * 1024 * 1024) { toast('Fichier trop gros (5 Mo maximum)', 5000); return; }
  const r = await act({ action: 'import_ics', content: await f.text() });
  if (r.ok) { await refresh(); $('#p-icsremove').hidden = false; }
};
$('#p-icsremove').onclick = async () => {
  const r = await act({ action: 'remove_ics' });
  if (r.ok) { await refresh(); $('#p-icsremove').hidden = true; }
};
$('#p-cancel').onclick = () => $('#prefs').classList.add('hidden');
$('#p-save').onclick = async () => {
  const values = { ics_url: $('#p-ics').value, subjects: $('#p-subjects').value, reminders: $('#p-reminders').checked };
  for (const f of FIELDS) {
    const el = $('#p-' + f);
    values[f] = el.type === 'number' || f === 'groceries_day' ? Number(el.value) : el.value;
  }
  const r = await act({ action: 'settings', values }, 'Réglages enregistrés');
  if (r.ok) { $('#prefs').classList.add('hidden'); refresh(); }
};

async function refresh() {
  try {
    S = await api('state?week=' + week);
    render();
  } catch {
    toast('Smoky Agenda ne répond pas');
  }
}
refresh();
// la ligne « maintenant » avance ; rien n'est interrogé quand la fenêtre est cachée
setInterval(() => { if (document.visibilityState === 'visible' && week === 0) refresh(); }, 120000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refresh(); });
