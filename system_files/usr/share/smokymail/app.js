// Smoky Mail : boîte de réception triée par catégorie, lecture, écriture et réglages.
'use strict';
const TOKEN = document.querySelector('meta[name="smoky-token"]').content;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const CAT_ICONS = { all: '📥', important: '⭐', cours: '🎓', perso: '💬', achats: '🧾', newsletters: '📰', notifications: '🔔', indesirable: '🚫' };
const COST = {
  'claude-opus-5-5': 'Claude Opus 5.5 : le tri le plus fin. Ordre de grandeur : 30 centimes pour 100 mails.',
  'claude-haiku-5-5': 'Claude Haiku 5.5 : environ 40 fois moins cher (moins d’un centime pour 100 mails), un peu moins fin sur les cas ambigus.',
};
let S = null;
let current = 'all';
let openUid = null;
let openMail = null;
let reply = null;
let preset = 'gmail';
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
  const r = await api('action', body);
  if (!r.ok) toast(r.message || 'Action impossible', 5000);
  else if (okMsg) toast(okMsg);
  return r;
}

// --- Dates --------------------------------------------------------------------------------
const fmtTime = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' });
const fmtDay = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' });
const fmtFull = new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
function when(ts) {
  const d = new Date(ts * 1000), now = new Date();
  return d.toDateString() === now.toDateString() ? fmtTime.format(d) : fmtDay.format(d);
}
function dayLabel(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const diff = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
  if (diff === 0) return "Aujourd'hui";
  if (diff === 1) return 'Hier';
  if (diff < 7) return 'Cette semaine';
  return 'Plus ancien';
}

// --- Affichage ----------------------------------------------------------------------------------
function render() {
  $('#setup').classList.toggle('hidden', S.configured);
  $('#app').classList.toggle('hidden', !S.configured);
  if (!S.configured) return;
  const cats = [['all', 'Tout'], ...Object.entries(S.categories)];
  $('#cats').innerHTML = cats.map(([id, label]) => {
    const list = id === 'all' ? S.mails : S.mails.filter((m) => m.category === id);
    const unread = list.filter((m) => !m.seen).length;
    return `<button class="cat ${current === id ? 'on' : ''}" data-cat="${id}">${CAT_ICONS[id] || '•'} ${esc(label)}
      <span class="n ${unread ? 'unread' : ''}">${unread || (list.length || '')}</span></button>`;
  }).join('');
  document.querySelectorAll('[data-cat]').forEach((b) => { b.onclick = () => { current = b.dataset.cat; render(); }; });

  const by = S.account.claude ? `Tri : ${esc(S.models[S.account.model] || 'Claude')}` : 'Tri simple (sans Claude)';
  const last = S.last_sync ? ` · relevé à ${fmtTime.format(new Date(S.last_sync * 1000))}` : '';
  $('#sortinfo').innerHTML = by + last + (S.sort_status ? `<br>⚠ ${esc(S.sort_status)}` : '');
  $('#status').textContent = S.status;
  $('#status').classList.toggle('hidden', !S.status);

  const q = $('#search').value.trim().toLowerCase();
  let list = current === 'all' ? S.mails : S.mails.filter((m) => m.category === current);
  if (q) list = list.filter((m) => `${m.from_name} ${m.from} ${m.subject} ${m.summary} ${m.preview}`.toLowerCase().includes(q));
  let html = '', lastDay = '';
  for (const m of list) {
    const day = dayLabel(m.date);
    if (day !== lastDay) { html += `<div class="day">${day}</div>`; lastDay = day; }
    const tags = (m.priority === 'haute' ? '<span class="tag haute">urgent</span>' : '') + (m.action ? '<span class="tag act">à faire</span>' : '')
      + (current === 'all' && m.category ? `<span class="tag">${esc(S.categories[m.category])}</span>` : '');
    html += `<div class="item ${m.seen ? '' : 'unread'} ${m.uid === openUid ? 'on' : ''}" data-uid="${m.uid}">
      <div class="top"><span class="who">${esc(m.from_name)}</span><span class="when">${when(m.date)}</span></div>
      <div class="subj">${esc(m.subject)}</div>
      <div class="sum">${esc(m.summary || m.preview)}</div>
      ${tags ? `<div class="top">${tags}</div>` : ''}</div>`;
  }
  $('#list').innerHTML = html || '<div class="day">Aucun mail ici.</div>';
  document.querySelectorAll('[data-uid]').forEach((el) => { el.onclick = () => show(Number(el.dataset.uid)); });
}

async function show(uid) {
  openUid = uid;
  const m = S.mails.find((x) => x.uid === uid);
  if (!m) return;
  m.seen = true;
  render();
  $('#reader').innerHTML = `<h1 class="r-subj">${esc(m.subject)}</h1><div class="hint">Chargement…</div>`;
  const r = await act({ action: 'open', uid });
  if (!r.ok || openUid !== uid) return;
  openMail = { ...m, ...r.mail };
  const options = Object.entries(S.categories).map(([id, l]) => `<option value="${id}" ${m.category === id ? 'selected' : ''}>${esc(l)}</option>`).join('');
  $('#reader').innerHTML = `
    <h1 class="r-subj">${esc(m.subject)}</h1>
    <div class="r-meta"><span><b>${esc(m.from_name)}</b> &lt;${esc(m.from)}&gt;</span><span>${esc(fmtFull.format(new Date(m.date * 1000)))}</span></div>
    <div class="r-ai">${m.summary ? `✨ <b>${esc(m.summary)}</b>` : ''}<span class="hint">Rangé dans</span>
      <select id="r-cat">${options}</select>${m.sorted_by === 'claude' ? '<span class="hint">par Claude</span>' : ''}</div>
    <div class="r-tools">
      <button class="btn primary" id="r-reply">Répondre</button>
      <button class="btn" id="r-archive">Archiver</button>
      <button class="btn danger" id="r-trash">Supprimer</button>
    </div>
    ${m.attachments.length ? `<div class="r-att">📎 ${m.attachments.map(esc).join(', ')} <span class="hint">(à ouvrir depuis ta messagerie web)</span></div>` : ''}
    <div id="r-body"></div>`;
  const body = $('#r-body');
  if (openMail.html) {
    // cadre isolé : aucun script, aucun formulaire ; images distantes bloquées (pisteurs)
    const f = document.createElement('iframe');
    f.className = 'r-frame';
    f.setAttribute('sandbox', 'allow-popups allow-popups-to-escape-sandbox');
    f.setAttribute('referrerpolicy', 'no-referrer');
    f.srcdoc = `<base target="_blank"><style>body{font-family:Arial,sans-serif;margin:16px;color:#111;word-wrap:break-word}img{max-width:100%;height:auto}</style>${openMail.html}`;
    f.onload = () => { try { f.style.height = Math.max(400, f.contentDocument.body.scrollHeight + 40) + 'px'; } catch { /* cadre isolé */ } };
    body.append(f);
  } else {
    const d = document.createElement('div');
    d.className = 'r-text';
    d.textContent = openMail.text || '(message vide)';
    body.append(d);
  }
  $('#r-cat').onchange = async (e) => { await act({ action: 'recategorize', uid, category: e.target.value }, 'Rangé'); refresh(); };
  $('#r-reply').onclick = () => compose(openMail);
  $('#r-archive').onclick = () => remove('archive', uid, 'Archivé');
  $('#r-trash').onclick = () => remove('trash', uid, 'Mis à la corbeille');
}

async function remove(kind, uid, msg) {
  const r = await act({ action: kind, uid }, msg);
  if (r.ok) {
    S.mails = S.mails.filter((m) => m.uid !== uid);
    openUid = null;
    $('#reader').innerHTML = '<div class="empty">Choisis un mail.</div>';
    render();
  }
}

// --- Écrire ----------------------------------------------------------------------------------------
function compose(orig) {
  reply = orig || null;
  $('#c-title').textContent = orig ? 'Répondre' : 'Nouveau message';
  $('#c-to').value = orig ? (orig.reply_to || orig.from) : '';
  $('#c-subject').value = orig ? (/^re\s*:/i.test(orig.subject) ? orig.subject : 'Re : ' + orig.subject) : '';
  const quoted = orig ? `\n\n\nLe ${fmtFull.format(new Date(orig.date * 1000))}, ${orig.from_name} a écrit :\n`
    + (orig.text || '').split('\n').slice(0, 60).map((l) => '> ' + l).join('\n') : '';
  $('#c-body').value = quoted;
  $('#composer').classList.remove('hidden');
  (orig ? $('#c-body') : $('#c-to')).focus();
  if (orig) $('#c-body').setSelectionRange(0, 0);
}
$('#compose').onclick = () => compose(null);
$('#c-cancel').onclick = () => $('#composer').classList.add('hidden');
$('#c-send').onclick = async () => {
  const btn = $('#c-send');
  btn.disabled = true;
  const r = await act({
    action: 'send', to: $('#c-to').value, subject: $('#c-subject').value, body: $('#c-body').value,
    in_reply_to: reply ? reply.message_id : '', references: reply ? reply.references : '',
  }, 'Message envoyé');
  btn.disabled = false;
  if (r.ok) $('#composer').classList.add('hidden');
};

// --- Connexion ----------------------------------------------------------------------------------------
const PW_HINTS = {
  gmail: '— Gmail demande un « mot de passe d’application » (myaccount.google.com → Sécurité → Validation en deux étapes → Mots de passe des applications)',
  outlook: '— avec la validation en deux étapes, crée un mot de passe d’application',
  orange: '', free: '', other: '— pour l’UPHF, les serveurs IMAP/SMTP sont indiqués sur l’ENT',
};
function setPreset(p) {
  preset = p;
  document.querySelectorAll('#presets button').forEach((b) => b.classList.toggle('on', b.dataset.p === p));
  $('#s-hosts').classList.toggle('hidden', p !== 'other');
  $('#s-pwhint').textContent = PW_HINTS[p] || '';
}
document.querySelectorAll('#presets button').forEach((b) => { b.onclick = () => setPreset(b.dataset.p); });
setPreset('gmail');
$('#s-save').onclick = async () => {
  const btn = $('#s-save');
  btn.disabled = true; btn.textContent = 'Connexion…';
  const r = await act({
    action: 'account', preset, email: $('#s-email').value, name: $('#s-name').value, password: $('#s-pass').value,
    imap: $('#s-imap').value, imap_port: 993, smtp: $('#s-smtp').value, smtp_port: Number($('#s-smtpport').value),
  }, 'Boîte connectée : relève en cours…');
  btn.disabled = false; btn.textContent = 'Se connecter';
  if (r.ok) { $('#s-pass').value = ''; $('#s-cancel').classList.add('hidden'); await refresh(); setTimeout(refresh, 6000); }
};
$('#s-cancel').onclick = () => { $('#setup').classList.add('hidden'); $('#app').classList.remove('hidden'); };

// --- Réglages -------------------------------------------------------------------------------------------
function openPrefs() {
  $('#p-model').innerHTML = Object.entries(S.models).map(([id, l]) => `<option value="${id}" ${S.account.model === id ? 'selected' : ''}>${esc(l)}</option>`).join('');
  $('#p-claude').checked = S.account.claude;
  $('#p-keystate').textContent = S.has_key ? '— clé enregistrée' : '— aucune clé';
  $('#p-key').value = '';
  $('#p-cost').textContent = COST[S.account.model] || '';
  $('#p-account').textContent = `${S.account.email} (${S.account.imap})`;
  $('#prefs').classList.remove('hidden');
}
$('#p-model').onchange = (e) => { $('#p-cost').textContent = COST[e.target.value] || ''; };
$('#settings').onclick = openPrefs;
$('#p-close').onclick = () => $('#prefs').classList.add('hidden');
$('#p-save').onclick = async () => {
  const key = $('#p-key').value.trim();
  if (!key && !S.has_key && $('#p-claude').checked) return toast('Colle d’abord ta clé d’API Claude.');
  const r = await act({ action: 'claude', key, enabled: $('#p-claude').checked, model: $('#p-model').value },
    $('#p-claude').checked ? 'Tri par Claude activé : les mails sont en cours de tri…' : 'Réglages enregistrés');
  if (r.ok) { $('#prefs').classList.add('hidden'); await refresh(); setTimeout(refresh, 8000); }
};
$('#p-forget').onclick = async () => { await act({ action: 'forget_key' }, 'Clé oubliée'); await refresh(); openPrefs(); };
$('#p-change').onclick = () => {
  $('#prefs').classList.add('hidden');
  $('#s-email').value = S.account.email; $('#s-name').value = S.account.name;
  $('#app').classList.add('hidden'); $('#setup').classList.remove('hidden'); $('#s-cancel').classList.remove('hidden');
};
$('#p-logout').onclick = async () => {
  if (!confirm('Se déconnecter de cette boîte ? Le mot de passe est retiré de ce PC (tes mails restent sur le serveur).')) return;
  await act({ action: 'logout' }, 'Déconnecté');
  $('#prefs').classList.add('hidden');
  await refresh();
};

// --- Relève --------------------------------------------------------------------------------------------
$('#refresh').onclick = async () => {
  const b = $('#refresh');
  b.disabled = true;
  await act({ action: 'sync' });
  b.disabled = false;
  await refresh();
};
$('#search').oninput = () => render();

async function refresh() {
  try {
    S = await api('state');
    render();
  } catch {
    toast('Smoky Mail ne répond pas');
  }
}
refresh();
// la page n'interroge le serveur que lorsqu'elle est visible
setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 30000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refresh(); });
