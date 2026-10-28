// Smoky Mail : plusieurs boîtes dans une seule liste triée par catégorie, lecture, écriture et réglages.
'use strict';
const TOKEN = document.querySelector('meta[name="smoky-token"]').content;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const CAT_ICONS = { all: '📥', important: '⭐', cours: '🎓', perso: '💬', achats: '🧾', newsletters: '📰', notifications: '🔔', indesirable: '🚫' };
const CSTATE = { ready: '✅ connecté', logged_out: 'pas connecté', absent: 'pas encore installé' };
let S = null;
let current = 'all';     // catégorie affichée
let acct = 'all';        // boîte affichée
let openKey = null;
let openMail = null;
let reply = null;
let preset = 'gmail';
let adding = false;      // fenêtre « ajouter une boîte » ouverte depuis la boîte de réception
let toastTimer = 0;
let msTimer = 0;

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

async function act(body, okMsg, ms) {
  const r = await api('action', body);
  if (!r.ok) toast(r.message || 'Action impossible', 5000);
  else if (okMsg) toast(okMsg, ms);
  return r;
}

const emailOf = (id) => (S.accounts.find((a) => a.id === id) || {}).email || '';

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
  const has = S.accounts.length > 0;
  $('#setup').classList.toggle('hidden', has && !adding);
  $('#app').classList.toggle('hidden', !has || adding);
  document.querySelectorAll('.s-cancel').forEach((b) => b.classList.toggle('hidden', !has));
  renderMs();
  if (!has) return;
  if (acct !== 'all' && !S.accounts.some((a) => a.id === acct)) acct = 'all';

  $('#accts').innerHTML = S.accounts.length < 2 ? '' : [['all', 'Toutes les boîtes'], ...S.accounts.map((a) => [a.id, a.email])]
    .map(([id, l]) => `<button class="${acct === id ? 'on' : ''}" data-acct="${id}" title="${esc(l)}">${esc(l)}</button>`).join('');
  document.querySelectorAll('[data-acct]').forEach((b) => { b.onclick = () => { acct = b.dataset.acct; render(); }; });

  const inBox = acct === 'all' ? S.mails : S.mails.filter((m) => m.account === acct);
  const cats = [['all', 'Tout'], ...Object.entries(S.categories)];
  $('#cats').innerHTML = cats.map(([id, label]) => {
    const list = id === 'all' ? inBox : inBox.filter((m) => m.category === id);
    const unread = list.filter((m) => !m.seen).length;
    return `<button class="cat ${current === id ? 'on' : ''}" data-cat="${id}">${CAT_ICONS[id] || '•'} ${esc(label)}
      <span class="n ${unread ? 'unread' : ''}">${unread || (list.length || '')}</span></button>`;
  }).join('');
  document.querySelectorAll('[data-cat]').forEach((b) => { b.onclick = () => { current = b.dataset.cat; render(); }; });

  const by = S.settings.claude ? `Tri par Claude (${esc((S.models[S.settings.model] || '').split(' ')[0])})` : 'Tri simple (sans Claude)';
  const last = S.last_sync ? ` · relevé à ${fmtTime.format(new Date(S.last_sync * 1000))}` : '';
  $('#sortinfo').innerHTML = by + last + (S.sort_status ? `<br>⚠ ${esc(S.sort_status)}` : '');
  $('#status').textContent = S.status;
  $('#status').classList.toggle('hidden', !S.status);

  const q = $('#search').value.trim().toLowerCase();
  let list = current === 'all' ? inBox : inBox.filter((m) => m.category === current);
  if (q) list = list.filter((m) => `${m.from_name} ${m.from} ${m.subject} ${m.summary} ${m.preview}`.toLowerCase().includes(q));
  const many = S.accounts.length > 1 && acct === 'all';
  let html = '', lastDay = '';
  for (const m of list) {
    const day = dayLabel(m.date);
    if (day !== lastDay) { html += `<div class="day">${day}</div>`; lastDay = day; }
    const tags = (m.priority === 'haute' ? '<span class="tag haute">urgent</span>' : '') + (m.action ? '<span class="tag act">à faire</span>' : '')
      + (current === 'all' && m.category ? `<span class="tag">${esc(S.categories[m.category])}</span>` : '');
    html += `<div class="item ${m.seen ? '' : 'unread'} ${m.k === openKey ? 'on' : ''}" data-k="${esc(m.k)}">
      <div class="top"><span class="who">${esc(m.from_name)}</span><span class="when">${when(m.date)}</span></div>
      <div class="subj">${esc(m.subject)}</div>
      <div class="sum">${esc(m.summary || m.preview)}</div>
      ${tags || many ? `<div class="top">${tags}${many ? `<span class="box">→ ${esc(emailOf(m.account))}</span>` : ''}</div>` : ''}</div>`;
  }
  $('#list').innerHTML = html || '<div class="day">Aucun mail ici.</div>';
  document.querySelectorAll('[data-k]').forEach((el) => { el.onclick = () => show(el.dataset.k); });
}

async function show(k) {
  openKey = k;
  const m = S.mails.find((x) => x.k === k);
  if (!m) return;
  m.seen = true;
  render();
  $('#reader').innerHTML = `<h1 class="r-subj">${esc(m.subject)}</h1><div class="hint">Chargement…</div>`;
  const r = await act({ action: 'open', k });
  if (!r.ok || openKey !== k) return;
  openMail = { ...m, ...r.mail };
  const options = Object.entries(S.categories).map(([id, l]) => `<option value="${id}" ${m.category === id ? 'selected' : ''}>${esc(l)}</option>`).join('');
  $('#reader').innerHTML = `
    <h1 class="r-subj">${esc(m.subject)}</h1>
    <div class="r-meta"><span><b>${esc(m.from_name)}</b> &lt;${esc(m.from)}&gt;${S.accounts.length > 1 ? ` → ${esc(emailOf(m.account))}` : ''}</span><span>${esc(fmtFull.format(new Date(m.date * 1000)))}</span></div>
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
    body.append(f);
  } else {
    const d = document.createElement('div');
    d.className = 'r-text';
    d.textContent = openMail.text || '(message vide)';
    body.append(d);
  }
  $('#r-cat').onchange = async (e) => { await act({ action: 'recategorize', k, category: e.target.value }, 'Rangé'); refresh(); };
  $('#r-reply').onclick = () => compose(openMail);
  $('#r-archive').onclick = () => remove('archive', k, 'Archivé');
  $('#r-trash').onclick = () => remove('trash', k, 'Mis à la corbeille');
}

async function remove(kind, k, msg) {
  const r = await act({ action: kind, k }, msg);
  if (r.ok) {
    S.mails = S.mails.filter((m) => m.k !== k);
    openKey = null;
    $('#reader').innerHTML = '<div class="empty">Choisis un mail.</div>';
    render();
  }
}

// --- Écrire ----------------------------------------------------------------------------------------
function compose(orig) {
  reply = orig || null;
  const from = orig ? orig.account : (acct !== 'all' ? acct : S.accounts[0].id);
  $('#c-from').innerHTML = S.accounts.map((a) => `<option value="${a.id}" ${a.id === from ? 'selected' : ''}>${esc(a.email)}</option>`).join('');
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
    action: 'send', account: $('#c-from').value, to: $('#c-to').value, subject: $('#c-subject').value, body: $('#c-body').value,
    in_reply_to: reply ? reply.message_id : '', references: reply ? reply.references : '',
  }, 'Message envoyé');
  btn.disabled = false;
  if (r.ok) $('#composer').classList.add('hidden');
};

// --- Ajouter une boîte ------------------------------------------------------------------------------------
const PW_HINTS = {
  gmail: '— Gmail demande un « mot de passe d’application » (myaccount.google.com → Sécurité → Validation en deux étapes → Mots de passe des applications)',
  orange: '', free: '', other: '— pour l’UPHF, les serveurs IMAP/SMTP sont indiqués sur l’ENT',
};
function setPreset(p) {
  preset = p;
  document.querySelectorAll('#presets button').forEach((b) => b.classList.toggle('on', b.dataset.p === p));
  $('#pw-form').classList.toggle('hidden', p === 'outlook');
  $('#ms-form').classList.toggle('hidden', p !== 'outlook');
  $('#s-hosts').classList.toggle('hidden', p !== 'other');
  $('#s-pwhint').textContent = PW_HINTS[p] || '';
  $('#s-email').placeholder = p === 'gmail' ? 'prenom.nom@gmail.com' : 'adresse@exemple.fr';
}
document.querySelectorAll('#presets button').forEach((b) => { b.onclick = () => setPreset(b.dataset.p); });
setPreset('gmail');
document.querySelectorAll('.s-cancel').forEach((b) => { b.onclick = () => { adding = false; render(); }; });
$('#s-save').onclick = async () => {
  const btn = $('#s-save');
  btn.disabled = true; btn.textContent = 'Connexion…';
  const r = await act({
    action: 'account', preset, email: $('#s-email').value, name: $('#s-name').value, password: $('#s-pass').value,
    imap: $('#s-imap').value, imap_port: 993, smtp: $('#s-smtp').value, smtp_port: Number($('#s-smtpport').value),
  }, 'Boîte ajoutée : relève en cours…');
  btn.disabled = false; btn.textContent = 'Se connecter';
  if (r.ok) { $('#s-pass').value = ''; $('#s-email').value = ''; adding = false; await refresh(); setTimeout(refresh, 6000); }
};

// Outlook : connexion Microsoft par code
let editCid = false;
function renderMs() {
  const f = S.ms_flow || {};
  const waiting = f.state === 'waiting';
  $('#ms-noid').classList.toggle('hidden', (!!S.settings.ms_client_id && !editCid) || waiting);
  $('#ms-go').classList.toggle('hidden', !S.settings.ms_client_id || editCid || waiting);
  $('#ms-wait').classList.toggle('hidden', !waiting);
  if (waiting) { $('#ms-code').textContent = f.user_code; $('#ms-uri').textContent = f.uri; }
  if (f.state === 'done' && msTimer) { stopMs(); adding = false; toast(`Boîte Outlook ajoutée : ${f.email}`); act({ action: 'ms_cancel' }); }
  if (f.state === 'error' && msTimer) { stopMs(); toast('Connexion Microsoft : ' + f.error, 6000); act({ action: 'ms_cancel' }); }
}
function stopMs() { clearInterval(msTimer); msTimer = 0; }
$('#ms-savecid').onclick = async () => {
  const r = await act({ action: 'ms_client_id', client_id: $('#ms-cid').value }, 'Identifiant enregistré');
  if (r.ok) { editCid = false; await refresh(); }
};
$('#ms-editcid').onclick = () => { editCid = true; $('#ms-cid').value = S.settings.ms_client_id; renderMs(); };
$('#ms-start').onclick = async () => {
  const r = await act({ action: 'ms_start' });
  if (!r.ok) return;
  await refresh();
  stopMs();
  msTimer = setInterval(refresh, 3000);
};
$('#ms-open').onclick = () => window.open(S.ms_flow.uri, '_blank', 'noopener');
$('#ms-copy').onclick = async () => { try { await navigator.clipboard.writeText(S.ms_flow.user_code); toast('Code copié'); } catch { toast('Sélectionne le code pour le copier'); } };
$('#ms-cancel').onclick = async () => { stopMs(); await act({ action: 'ms_cancel' }); await refresh(); };

// --- Réglages -------------------------------------------------------------------------------------------
function openPrefs() {
  $('#p-model').innerHTML = Object.entries(S.models).map(([id, l]) => `<option value="${id}" ${S.settings.model === id ? 'selected' : ''}>${esc(l)}</option>`).join('');
  $('#p-claude').checked = S.settings.claude;
  $('#p-cstate').textContent = CSTATE[S.claude_state] || S.claude_state;
  $('#p-connect').textContent = S.claude_state === 'ready' ? 'Changer de compte Claude' : 'Connecter mon compte Claude';
  $('#p-accounts').innerHTML = S.accounts.map((a) => `<div class="acc-row"><span>${esc(a.email)} <small>${a.auth === 'microsoft' ? 'connexion Microsoft' : 'mot de passe'}</small></span>
    <button class="btn danger" data-rm="${a.id}">Retirer</button></div>`).join('');
  document.querySelectorAll('[data-rm]').forEach((b) => {
    b.onclick = async () => {
      const email = emailOf(b.dataset.rm);
      if (!confirm(`Retirer ${email} de Smoky Mail ?\n\nSes accès sont effacés de ce PC ; tes mails restent sur le serveur.`)) return;
      await act({ action: 'remove_account', id: b.dataset.rm }, 'Boîte retirée');
      await refresh();
      if (S.accounts.length) openPrefs(); else $('#prefs').classList.add('hidden');
    };
  });
  $('#prefs').classList.remove('hidden');
}
$('#settings').onclick = openPrefs;
$('#p-close').onclick = () => $('#prefs').classList.add('hidden');
$('#p-add').onclick = () => { $('#prefs').classList.add('hidden'); adding = true; setPreset('gmail'); render(); };
$('#p-connect').onclick = () => act({ action: 'claude_connect' }, 'Suis les étapes dans la fenêtre qui s’ouvre, puis clique sur « Vérifier ».', 6000);
$('#p-recheck').onclick = async () => { await refresh(); openPrefs(); toast(S.claude_state === 'ready' ? 'Compte Claude connecté' : 'Pas encore connecté'); };
$('#p-save').onclick = async () => {
  const r = await act({ action: 'claude', enabled: $('#p-claude').checked, model: $('#p-model').value },
    $('#p-claude').checked ? 'Tri par Claude activé : les mails sont en cours de tri…' : 'Réglages enregistrés');
  if (r.ok) { $('#prefs').classList.add('hidden'); await refresh(); setTimeout(refresh, 15000); }
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
