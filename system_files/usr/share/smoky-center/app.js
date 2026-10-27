// Smoky Center : chaque carte lit l'état réel de la machine et envoie des actions précises.
'use strict';
const TOKEN = document.querySelector('meta[name="smoky-token"]').content;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let S = null;
let toastTimer = 0;

function toast(msg, ms = 3200) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
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
  if (r.message) toast(r.message, 5000);
  else if (r.ok && okMsg) toast(okMsg);
  else if (!r.ok) toast('Action impossible');
  await refresh();
  return r;
}

const seg = (key, options, current) =>
  `<div class="seg" data-seg="${key}">${options.map(([v, l]) => `<button data-v="${esc(v)}" class="${String(v) === String(current) ? 'on' : ''}">${esc(l)}</button>`).join('')}</div>`;
const sw = (key, on) => `<label class="switch"><input type="checkbox" data-sw="${key}" ${on ? 'checked' : ''}><i></i></label>`;
const fmtDate = new Intl.DateTimeFormat('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

function render() {
  const s = S;
  $('#sys').textContent = `${s.system}${s.nvidia ? ' · pilote NVIDIA' : ''}${s.update_staged ? ' · mise à jour prête : redémarre pour l’appliquer' : ''}`;
  const b = s.battery, f = s.focus, m = s.moodle, ad = s.adaptive;
  const left = Math.max(0, Math.round((f.end * 1000 - Date.now()) / 60000));
  const deadlines = (m.deadlines || []).filter((e) => e.time * 1000 > Date.now()).slice(0, 4);
  $('#grid').innerHTML = `
  <section class="card"><h2>🔋 Énergie <small>${esc(b.capacity)} % · ${b.status === 'Charging' ? 'en charge' : b.status === 'Discharging' ? 'sur batterie' : esc(b.status)}</small></h2>
    <div class="row"><span>Limite de charge</span>${seg('battery', [[60, '60 %'], [80, '80 %'], [100, '100 %']], b.limit)}</div>
    <p class="hint">80 % préserve la batterie si le PC est souvent branché ; 100 % avant un long trajet.</p>
    <div class="row"><span>Profil</span>${seg('profile', [['power-saver', 'Économie'], ['balanced', 'Équilibré'], ['performance', 'Performance']], s.profile)}</div>
    <div class="row"><span>Écran 120 Hz sur secteur, 60 Hz sur batterie</span>${sw('refresh', ad.refresh)}</div>
  </section>
  <section class="card"><h2>🎮 Carte graphique <small>${esc(s.gpu)}</small></h2>
    <div class="row"><span>Mode</span>${seg('gpu', [['Integrated', 'Intel (autonomie)'], ['Hybrid', 'RTX activée']], s.gpu)}</div>
    <p class="hint">Changement appliqué après déconnexion. La RTX ne sert qu'aux jeux exigeants.</p>
    <div class="row"><span>Pilote NVIDIA (jeux)</span><button class="btn" data-a="nvidia">${s.nvidia ? 'Revenir au système standard' : 'Installer'}</button></div>
    <p class="hint">⚠️ Le pilote NVIDIA n'est pas signé : désactive le Secure Boot dans le BIOS (F2) avant de redémarrer.</p>
  </section>
  <section class="card"><h2>📱 Tablette</h2>
    <div class="row"><span>Grandes icônes et clavier à l'écran quand le clavier est détaché</span>${sw('tablet', ad.tablet)}</div>
    <div class="row"><span>Proposer d'ouvrir Smoky Notes</span>${sw('tablet_open_notes', ad.tablet_open_notes)}</div>
  </section>
  <section class="card"><h2>🎓 Cours (Moodle) <small><span class="pill ${m.connected ? 'on' : ''}">${m.connected ? 'connecté' : 'non connecté'}</span></small></h2>
    ${m.connected ? `<p class="hint">${m.documents || 0} document(s) importé(s) dans Smoky Notes · vérification toutes les 2 h</p>` : '<p class="hint">Tes PDF de cours arrivent automatiquement dans Smoky Notes (un classeur par cours), et tes échéances te sont rappelées la veille.</p>'}
    ${deadlines.map((e) => `<div class="due"><b>${esc(e.name)}</b><span>${esc(fmtDate.format(new Date(e.time * 1000)))}</span></div>`).join('')}
    <div class="btns">${m.connected ? '<button class="btn primary" data-a="moodle_sync">Synchroniser maintenant</button><button class="btn danger" data-a="moodle_disconnect">Déconnecter</button>' : '<button class="btn primary" data-a="moodle_connect">Connecter Moodle</button>'}</div>
  </section>
  <section class="card"><h2>🎯 Concentration ${left ? '<small><span class="pill on">en cours</span></small>' : ''}</h2>
    ${left ? `<div class="big">${left} min</div><p class="hint">Réseaux sociaux, vidéo et streaming bloqués jusqu'à la fin.</p><div class="btns"><button class="btn danger" data-a="focus_stop">Arrêter</button></div>`
      : `<p class="hint">Bloque les sites qui distraient, puis une notification annonce la pause.</p><div class="btns">${[25, 50, 90].map((n) => `<button class="btn ${n === 25 ? 'primary' : ''}" data-focus="${n}">${n} min</button>`).join('')}</div>`}
  </section>
  <section class="card"><h2>🏠 Maison <small><span class="pill ${s.home.running ? 'on' : ''}">${s.home.running ? 'Smoky Home démarré' : 'arrêté'}</span></small></h2>
    <div class="row"><span>Garder Smoky Home démarré (boutons maison toujours prêts)</span>${sw('home_background', s.home.background)}</div>
    <div class="row"><span>Boutons dans le centre de contrôle</span><span class="pill ${s.home.token ? 'on' : ''}">${s.home.token ? 'reliés' : 'à relier'}</span></div>
    <input id="home-token" type="password" placeholder="Colle ici un jeton d'accès Smoky Home">
    <p class="hint">Smoky Home → ton profil (en bas à gauche) → Sécurité → Jetons d'accès longue durée → Créer.</p>
    <div class="btns"><button class="btn primary" data-a="home_token">Relier</button><button class="btn" data-a="home_open">Ouvrir Smoky Home</button></div>
  </section>
  <section class="card"><h2>🛡️ VPN <small><span class="pill ${s.vpn.active ? 'on' : ''}">${s.vpn.active ? 'actif' : s.vpn.configured ? 'prêt' : 'non configuré'}</span></small></h2>
    ${s.vpn.configured ? `<div class="row"><span>VPN</span>${sw('vpn', s.vpn.active)}</div>
    <div class="row"><span>Activer tout seul sur les Wi-Fi ouverts (publics)</span>${sw('vpn_auto', ad.vpn_auto)}</div>` : ''}
    <p class="hint">Proton VPN (gratuit) : account.protonvpn.com → Téléchargements → WireGuard → télécharge un fichier .conf, puis importe-le ici. Le VPN apparaît aussi dans le centre de contrôle.</p>
    <div class="btns"><button class="btn ${s.vpn.configured ? '' : 'primary'}" data-a="vpn_import">${s.vpn.configured ? 'Remplacer la configuration' : 'Importer un fichier .conf'}</button></div>
  </section>
  <section class="card"><h2>💾 Sauvegardes</h2>
    <p class="hint">Sauvegarde automatique de ton dossier personnel sur Google Drive (ou un disque, un NAS), avec restauration en quelques clics.</p>
    <div class="btns"><button class="btn primary" data-a="backup_open">Ouvrir les sauvegardes</button></div>
  </section>
  <section class="card"><h2>✨ Apparence</h2>
    <p class="hint">Les logos des nouvelles applis passent au style Smoky tout seuls. Pour forcer une mise à jour :</p>
    <div class="btns"><button class="btn" data-a="icons_regen">Régénérer les logos Smoky</button></div>
  </section>`;
  bind();
}

function bind() {
  document.querySelectorAll('[data-seg] button').forEach((btn) => {
    btn.onclick = () => {
      const key = btn.parentElement.dataset.seg, v = btn.dataset.v;
      if (key === 'battery') act({ action: 'battery', limit: Number(v) }, `Charge limitée à ${v} %`);
      if (key === 'profile') act({ action: 'profile', name: v });
      if (key === 'gpu') act({ action: 'gpu', mode: v });
    };
  });
  document.querySelectorAll('[data-sw]').forEach((inp) => {
    inp.onchange = () => {
      const k = inp.dataset.sw, on = inp.checked;
      if (['refresh', 'tablet', 'tablet_open_notes', 'vpn_auto'].includes(k)) act({ action: 'adaptive', [k]: on });
      if (k === 'home_background') act({ action: 'home_background', on });
      if (k === 'vpn') act({ action: 'vpn', on });
    };
  });
  document.querySelectorAll('[data-focus]').forEach((btn) => {
    btn.onclick = () => act({ action: 'focus_start', minutes: Number(btn.dataset.focus) }, `Concentration : ${btn.dataset.focus} minutes`);
  });
  document.querySelectorAll('[data-a]').forEach((btn) => {
    btn.onclick = async () => {
      const a = btn.dataset.a;
      if (a === 'home_token') return act({ action: 'home_token', token: $('#home-token').value }, 'Boutons maison reliés');
      if (a === 'vpn_import') return $('#vpn-file').click();
      if (a === 'nvidia') {
        const on = !S.nvidia;
        if (on && !confirm('Installer le pilote NVIDIA ?\n\nLe système va être remplacé par la variante NVIDIA (plusieurs minutes de téléchargement), puis il faudra redémarrer.\n\nDésactive d\'abord le Secure Boot dans le BIOS (touche F2 au démarrage).')) return;
        return act({ action: 'nvidia', on });
      }
      const msgs = { moodle_sync: 'Synchronisation lancée', moodle_connect: 'Fenêtre de connexion ouverte', icons_regen: 'Logos en cours de génération' };
      return act({ action: a }, msgs[a]);
    };
  });
}

$('#vpn-file').onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  if (file) act({ action: 'vpn_import', content: await file.text() }, 'VPN importé');
};

async function refresh() {
  try {
    S = await api('state');
    if (!document.activeElement || document.activeElement.tagName !== 'INPUT' || document.activeElement.type !== 'password') render();
  } catch {
    toast('Smoky Center ne répond pas');
  }
}

refresh();
setInterval(refresh, 15000);
