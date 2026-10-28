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
// Réglages GNOME (liste fermée côté serveur) : la ligne n'apparaît que si le réglage existe
const gsw = (name, label, invert = false) => (S.g[name] === undefined ? ''
  : `<div class="row"><span>${label}</span><label class="switch"><input type="checkbox" data-g="${name}" data-inv="${invert ? 1 : ''}" ${(invert ? !S.g[name] : S.g[name]) ? 'checked' : ''}><i></i></label></div>`);
const gseg = (name, label, options) => (S.g[name] === undefined ? ''
  : `<div class="row"><span>${label}</span>${seg('g:' + name, options, S.g[name])}</div>`);
const fmtDate = new Intl.DateTimeFormat('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

function render() {
  const s = S;
  $('#sys').textContent = `${s.system}${s.update_staged ? ' · mise à jour prête : redémarre pour l’appliquer' : ''}`;
  const b = s.battery, f = s.focus, m = s.moodle, ad = s.adaptive;
  const left = Math.max(0, Math.round((f.end * 1000 - Date.now()) / 60000));
  const deadlines = (m.deadlines || []).filter((e) => e.time * 1000 > Date.now()).slice(0, 4);
  $('#grid').innerHTML = `
  <section class="card"><h2>🔋 Énergie <small>${esc(b.capacity)} % · ${b.status === 'Charging' ? 'en charge' : b.status === 'Discharging' ? 'sur batterie' : esc(b.status)}</small></h2>
    <div class="row"><span>Limite de charge</span>${seg('battery', [[60, '60 %'], [80, '80 %'], [100, '100 %']], b.limit)}</div>
    <p class="hint">80 % préserve la batterie si le PC est souvent branché (bien plus de cycles avant usure).</p>
    <div class="btns"><button class="btn" data-a="charge_once">Charger à 100 % pour cette fois</button></div>
    <p class="hint">Pour un long trajet : la limite revient toute seule dès que tu débranches.</p>
    <div class="row"><span>Profil</span>${seg('profile', [['power-saver', 'Économie'], ['balanced', 'Équilibré'], ['performance', 'Performance']], s.profile)}</div>
    <div class="row"><span>Écran 120 Hz sur secteur, 60 Hz sur batterie</span>${sw('refresh', ad.refresh)}</div>
  </section>
  <section class="card"><h2>🎮 Carte graphique <small>${esc(s.gpu)}</small></h2>
    <div class="row"><span>Mode</span>${seg('gpu', [['Integrated', 'Intel (autonomie)'], ['Hybrid', 'RTX activée']], s.gpu)}</div>
    <p class="hint">Changement appliqué après déconnexion. Intel suffit pour les cours et le streaming, et tient bien plus longtemps sur batterie.</p>
  </section>
  <section class="card"><h2>📱 Tablette</h2>
    <p class="hint">Aussi dans le menu en haut à droite (bouton « Tablette »).</p>
    <div class="row"><span>Mode tablette : grandes icônes et clavier à l'écran</span>${sw('tablet_mode', ad.tablet_mode)}</div>
    <div class="row"><span>Proposer d'ouvrir Smoky Notes en passant en tablette</span>${sw('tablet_open_notes', ad.tablet_open_notes)}</div>
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
    <p class="hint">L'appli Proton VPN est installée (dans les applis). Pour l'activation automatique sur les Wi-Fi publics : account.protonvpn.com → Téléchargements → WireGuard → télécharge un fichier .conf, puis importe-le ici.</p>
    <div class="btns"><button class="btn ${s.vpn.configured ? '' : 'primary'}" data-a="vpn_import">${s.vpn.configured ? 'Remplacer la configuration' : 'Importer un fichier .conf'}</button></div>
  </section>
  <section class="card"><h2>🔄 Mises à jour</h2>
    <p class="hint">${s.update.running ? 'Téléchargement de la nouvelle version de Smoky OS… (quelques minutes, tu peux continuer à utiliser le PC)'
      : s.update_staged ? 'Nouvelle version téléchargée : elle s’applique au redémarrage.'
      : s.update.result === 'uptodate' ? 'Smoky OS est à jour.'
      : s.update.result === 'error' ? 'La recherche a échoué : vérifie la connexion internet.'
      : 'Smoky OS se met aussi à jour tout seul chaque semaine, appliqué au redémarrage. En cas de souci, la version précédente reste disponible au démarrage.'}</p>
    <div class="btns">
      ${s.update_staged ? '<button class="btn primary" data-a="reboot">Redémarrer maintenant</button>'
        : `<button class="btn primary" data-a="update" ${s.update.running ? 'disabled' : ''}>${s.update.running ? 'Mise à jour en cours…' : 'Rechercher une mise à jour'}</button>`}
    </div>
  </section>
  <section class="card"><h2>🖥️ Écran</h2>
    ${gsw('night_light', 'Veilleuse (lumière chaude le soir)')}
    ${gseg('night_light_temp', 'Ton', [[4500, 'Léger'], [3500, 'Moyen'], [2700, 'Chaud']])}
    ${gsw('night_light_auto', 'Du coucher au lever du soleil')}
    ${gsw('ambient', 'Luminosité automatique')}
    ${gsw('rotation_lock', 'Bloquer la rotation de l’écran')}
    ${gseg('text_scale', 'Taille du texte', [[1, 'Normale'], [1.1, 'Grande'], [1.25, 'Très grande']])}
  </section>
  <section class="card"><h2>🌙 Veille et verrouillage</h2>
    ${gseg('idle_delay', 'Écran éteint après', [[120, '2 min'], [300, '5 min'], [600, '10 min'], [0, 'Jamais']])}
    ${gseg('sleep_battery', 'Veille sur batterie', [[600, '10 min'], [900, '15 min'], [1800, '30 min'], [3600, '1 h']])}
    ${gseg('sleep_ac', 'Veille sur secteur', [['suspend', 'Oui'], ['nothing', 'Jamais']])}
    ${gseg('lock_delay', 'Verrouiller', [[0, 'Aussitôt'], [60, '1 min'], [300, '5 min']])}
  </section>
  <section class="card"><h2>🔔 Notifications et son</h2>
    ${gsw('show_banners', 'Ne pas déranger', true)}
    ${gsw('lock_notifs', 'Notifications sur l’écran verrouillé')}
    ${gsw('event_sounds', 'Sons du système')}
    ${gsw('volume_boost', 'Volume au-delà de 100 % (haut-parleurs faibles)')}
  </section>
  <section class="card"><h2>🔒 Confidentialité</h2>
    ${gsw('recent_files', 'Garder l’historique des fichiers récents')}
    ${gsw('old_trash', 'Vider la corbeille après 30 jours')}
    ${gsw('old_temp', 'Supprimer les fichiers temporaires anciens')}
    ${gsw('camera_off', 'Caméra désactivée pour toutes les applis')}
    ${gsw('location', 'Localisation (météo, fuseau horaire)')}
  </section>
  <section class="card"><h2>🧭 Interface</h2>
    ${gseg('dock_size', 'Taille du dock', [[44, 'Petit'], [52, 'Moyen'], [60, 'Grand']])}
    ${gsw('dock_fixed', 'Dock toujours visible')}
    ${gsw('battery_pct', 'Pourcentage de batterie en haut')}
    ${gsw('hot_corner', 'Coin actif (en haut à gauche)')}
    ${gsw('animations', 'Animations (désactiver économise la batterie)')}
    ${gsw('tap_click', 'Toucher le pavé pour cliquer')}
    ${gsw('natural_scroll', 'Défilement naturel')}
  </section>
  <section class="card"><h2>💽 Stockage <small>${esc(s.storage.free)} libres sur ${esc(s.storage.total)}</small></h2>
    <div class="bar"><i style="width:${Number(s.storage.used_pct) || 0}%"></i></div>
    <p class="hint">Corbeille : ${esc(s.storage.trash)} · caches : ${esc(s.storage.cache)}. Le nettoyage vide la corbeille et les caches (Chrome, miniatures) et retire les composants d’applis inutilisés. Tes fichiers ne sont jamais touchés.</p>
    <div class="btns"><button class="btn primary" data-a="clean" ${s.jobs.clean.running ? 'disabled' : ''}>${s.jobs.clean.running ? 'Nettoyage…' : 'Nettoyer'}</button></div>
    ${s.jobs.clean.result ? `<p class="hint">Dernier nettoyage : ${esc(s.jobs.clean.result)} libérés.</p>` : ''}
  </section>
  <section class="card"><h2>📦 Applis</h2>
    <p class="hint">Les applis (Spotify, Proton VPN, Déjà Dup…) se mettent à jour avec le système ; ce bouton le fait tout de suite.</p>
    <div class="btns"><button class="btn primary" data-a="apps_update" ${s.jobs.apps.running ? 'disabled' : ''}>${s.jobs.apps.running ? 'Mise à jour…' : 'Mettre à jour les applis'}</button></div>
    ${s.jobs.apps.result === 'error' ? '<p class="hint">La dernière mise à jour a échoué : vérifie la connexion.</p>' : ''}
  </section>
  <section class="card"><h2>ℹ️ Système</h2>
    <p class="hint">${esc(s.system)} · noyau ${esc(s.info.kernel)} · ${esc(s.info.ram)} de mémoire${s.info.temp ? ' · processeur à ' + esc(s.info.temp) : ''} · allumé depuis ${esc(s.info.uptime)}</p>
    ${s.windows ? '<div class="btns"><button class="btn" data-a="windows">Redémarrer sur Windows</button></div><p class="hint">Une seule fois : au redémarrage suivant, retour à Smoky OS.</p>' : ''}
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
      if (key.startsWith('g:')) {
        const name = key.slice(2), cur = S.g[name];
        act({ action: 'gset', name, value: typeof cur === 'string' ? v : Number(v) });
      }
    };
  });
  document.querySelectorAll('[data-sw]').forEach((inp) => {
    inp.onchange = () => {
      const k = inp.dataset.sw, on = inp.checked;
      if (['refresh', 'tablet_mode', 'tablet_open_notes', 'vpn_auto'].includes(k)) act({ action: 'adaptive', [k]: on });
      if (k === 'home_background') act({ action: 'home_background', on });
      if (k === 'vpn') act({ action: 'vpn', on });
    };
  });
  document.querySelectorAll('[data-g]').forEach((inp) => {
    inp.onchange = () => act({ action: 'gset', name: inp.dataset.g, value: inp.dataset.inv ? !inp.checked : inp.checked });
  });
  document.querySelectorAll('[data-focus]').forEach((btn) => {
    btn.onclick = () => act({ action: 'focus_start', minutes: Number(btn.dataset.focus) }, `Concentration : ${btn.dataset.focus} minutes`);
  });
  document.querySelectorAll('[data-a]').forEach((btn) => {
    btn.onclick = async () => {
      const a = btn.dataset.a;
      if (a === 'home_token') return act({ action: 'home_token', token: $('#home-token').value }, 'Boutons maison reliés');
      if (a === 'vpn_import') return $('#vpn-file').click();
      if (a === 'windows' && !confirm('Redémarrer sur Windows maintenant ?\n\nEnregistre ton travail avant. Au redémarrage suivant, le PC revient sur Smoky OS.')) return;
      if (a === 'clean' && !confirm('Vider la corbeille et les caches ?\n\nTes fichiers et tes notes ne sont pas touchés.')) return;
      if (a === 'reboot' && !confirm('Redémarrer maintenant pour appliquer la mise à jour ?\n\nEnregistre ton travail avant.')) return;
      const msgs = { charge_once: 'Charge jusqu’à 100 %, puis retour à la limite au débranchement', clean: 'Nettoyage lancé', apps_update: 'Mise à jour des applis lancée', update: 'Recherche de mise à jour lancée', moodle_sync: 'Synchronisation lancée', moodle_connect: 'Fenêtre de connexion ouverte', icons_regen: 'Logos en cours de génération' };
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

// entrée des cartes en cascade : seulement à l'ouverture, pas à chaque rafraîchissement
document.body.classList.add('intro');
setTimeout(() => document.body.classList.remove('intro'), 1200);
refresh();
// rafraîchissement plus rapide pendant une mise à jour
// fenêtre cachée ou réduite : aucune interrogation (économise la batterie)
const visible = () => document.visibilityState === 'visible';
setInterval(() => { if (visible() && S && ((S.update && S.update.running) || S.jobs.apps.running || S.jobs.clean.running)) refresh(); }, 4000);
setInterval(() => { if (visible()) refresh(); }, 15000);
document.addEventListener('visibilitychange', () => { if (visible()) refresh(); });
