// Smoky — page « Système » : les réglages du PC, une section à la fois.
// Chaque commande envoie une action précise au serveur (liste fermée, smoky/systeme.py), puis
// l'état réel de la machine est relu : la page montre toujours ce que le PC a vraiment retenu.
import { h, bouton, interrupteur, segment, rangee, annoncer, confirmer } from "/js/ui.js";
import { api, tenter } from "/js/app.js";

const ETATS = { Charging: "En charge.", Discharging: "Sur batterie.", Full: "Batterie pleine.", "Not charging": "Branché, la charge est en pause." };
const HEURE = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export async function monter(conteneur, contexte) {
  let e = null;               // état de la machine
  let section = "energie";
  let enCours = 0;            // actions envoyées, pas encore revenues
  let minuterie = 0;

  const sommaire = h("nav", { class: "sommaire", "aria-label": "Sections des réglages" });
  const contenu = h("div", { class: "section", "aria-live": "off" });
  const fichierVpn = h("input", { type: "file", accept: ".conf,text/plain", hidden: true });

  // --- actions ---
  async function agir(corps, succes) {
    enCours++;
    const ok = await tenter(() => api.envoyer("/api/systeme", corps), { succes });
    enCours--;
    await relire();
    setTimeout(relire, 1500);      // charge, profil… s'appliquent parfois avec un temps de retard
    return ok;
  }
  async function agirApresQuestion(question, corps, succes) {
    if (await confirmer(question)) return agir(corps, succes);
    return false;
  }

  // --- commandes prêtes pour les réglages GNOME (absents de l'état = pas sur cette machine) ---
  const gBascule = (nom, libelle, aide, inverse = false) => (e.gnome[nom] === undefined ? null
    : rangee(libelle, aide, interrupteur({ coche: inverse ? !e.gnome[nom] : e.gnome[nom], nom: libelle,
      surChange: (v) => agir({ action: "gnome", nom, valeur: inverse ? !v : v }) })));
  const gChoix = (nom, libelle, aide, options) => (e.gnome[nom] === undefined ? null
    : rangee(libelle, aide, segment({ options, valeur: e.gnome[nom], nom: libelle, surChange: (v) => agir({ action: "gnome", nom, valeur: v }) })));
  const adaptatif = (cle, libelle, aide) => rangee(libelle, aide, interrupteur({ coche: e.adaptatif[cle], nom: libelle,
    surChange: (v) => agir({ action: "adaptatif", [cle]: v }) }));
  const etiquette = (texte) => h("span", { class: "valeur", texte });
  const groupe = (...rangees) => { const r = rangees.flat().filter(Boolean); return r.length ? h("div", { class: "groupe" }, r) : null; };
  // un intertitre n'apparaît que si son groupe a au moins un réglage sur cette machine
  const titre = (texte, bloc) => (bloc ? [h("h3", { texte }), bloc] : null);

  const SECTIONS = [
    ["energie", "Énergie", () => {
      const b = e.energie;
      return [
        h("p", { class: "grand-chiffre", texte: b.niveau === "?" ? "—" : `${b.niveau} %` }),
        h("p", { class: "intro", texte: b.niveau === "?" ? "Batterie introuvable sur cette machine." : ETATS[b.etat] || `Batterie : ${b.etat}.` }),
        groupe(
          rangee("Limite de charge", "80 % préserve la batterie si le PC est souvent branché : bien plus de cycles avant usure.",
            segment({ options: [[60, "60 %"], [80, "80 %"], [100, "100 %"]], valeur: Number(b.limite), nom: "Limite de charge",
              surChange: (v) => agir({ action: "limite_de_charge", limite: v }, `Charge limitée à ${v} %.`) })),
          rangee("Charger à 100 % cette fois-ci", "Pour un long trajet : la limite revient toute seule dès que tu débranches.",
            bouton("Charger à 100 %", { surClic: () => agir({ action: "charge_complete_une_fois" }) })),
          rangee("Profil d'énergie", "Économie allonge l'autonomie, Performance libère toute la puissance.",
            segment({ options: [["power-saver", "Économie"], ["balanced", "Équilibré"], ["performance", "Performance"]], valeur: b.profil, nom: "Profil d'énergie",
              surChange: (v) => agir({ action: "profil", nom: v }) })),
          adaptatif("refresh", "Écran à 120 Hz sur secteur, 60 Hz sur batterie", "Plus fluide branché, plus endurant débranché."),
          gBascule("battery_pct", "Pourcentage de batterie dans la barre du haut")),
        titre("Veille", groupe(
          gChoix("idle_delay", "Éteindre l'écran après", null, [[120, "2 min"], [300, "5 min"], [600, "10 min"], [0, "Jamais"]]),
          gChoix("sleep_battery", "Mettre en veille sur batterie après", null, [[600, "10 min"], [900, "15 min"], [1800, "30 min"], [3600, "1 h"]]),
          gChoix("sleep_ac", "Mettre en veille sur secteur", null, [["suspend", "Oui"], ["nothing", "Jamais"]]))),
      ];
    }],
    ["ecran", "Écran", () => [groupe(
      gBascule("night_light", "Veilleuse", "Lumière plus chaude le soir, moins fatigante pour les yeux."),
      gChoix("night_light_temp", "Ton de la veilleuse", null, [[4500, "Léger"], [3500, "Moyen"], [2700, "Chaud"]]),
      gBascule("night_light_auto", "Veilleuse du coucher au lever du soleil"),
      gBascule("ambient", "Luminosité automatique", "Suit la lumière de la pièce."),
      gBascule("rotation_lock", "Bloquer la rotation de l'écran"),
      gChoix("text_scale", "Taille du texte", null, [[1, "Normale"], [1.1, "Grande"], [1.25, "Très grande"]]),
      gBascule("animations", "Animations", "Les couper économise un peu de batterie ; celles de Smoky s'arrêtent aussi."))]],
    ["graphique", "Carte graphique", () => {
      const m = e.carte_graphique.mux || {};
      const surNvidia = m.mux === 0;
      const double = m.mux === null || m.mux === undefined ? null
        : surNvidia ? `L'écran est relié à la carte NVIDIA (mode Ultimate de Windows). ${m.probleme || "Redémarre Smoky OS pour revenir à la puce Intel."}`
          : `Sur Smoky OS, l'écran reste sur la puce Intel. ${m.windows_ultimate ? "Le mode Ultimate est remis quand tu passes par « Redémarrer sur Windows »." : "Si Windows passe en mode Ultimate, Smoky OS redémarre une fois tout seul pour revenir à la puce Intel."}${m.probleme ? ` ${m.probleme}` : ""}`;
      const lignes = [rangee("Carte utilisée", "Intel suffit pour les cours et le streaming, et tient bien plus longtemps sur batterie. Le changement s'applique après avoir fermé puis rouvert ta session.",
        segment({ options: [["Integrated", "Intel (autonomie)"], ["Hybrid", "RTX activée"]], valeur: e.carte_graphique.mode, nom: "Carte utilisée",
          surChange: (v) => agir({ action: "carte_graphique", mode: v }) }))];
      if (double) { const r = rangee("Avec Windows", double); if (surNvidia) r.classList.add("alerte"); lignes.push(r); }
      return [groupe(lignes)];
    }],
    ["tablette", "Tablette et dock", () => [
      groupe(
        adaptatif("tablet_mode", "Mode tablette", "Grandes icônes et clavier à l'écran. Aussi dans le menu en haut à droite."),
        adaptatif("tablet_open_notes", "Proposer d'ouvrir les notes en passant en tablette")),
      titre("Dock et pavé tactile", groupe(
        gChoix("dock_size", "Taille du dock", null, [[44, "Petit"], [52, "Moyen"], [60, "Grand"]]),
        gBascule("dock_fixed", "Dock toujours visible"),
        gBascule("hot_corner", "Coin actif en haut à gauche"),
        gBascule("tap_click", "Toucher le pavé pour cliquer"),
        gBascule("natural_scroll", "Défilement naturel"))),
    ]],
    ["calme", "Notifications et concentration", () => {
      const c = e.concentration;
      const reste = Math.max(0, Math.round((c.end * 1000 - Date.now()) / 60000));
      return [
        groupe(
          gBascule("show_banners", "Ne pas déranger", "Les notifications arrivent sans s'afficher.", true),
          gBascule("lock_notifs", "Notifications sur l'écran verrouillé"),
          gBascule("event_sounds", "Sons du système"),
          gBascule("volume_boost", "Volume au-delà de 100 %", "Pour des haut-parleurs trop faibles.")),
        h("h3", { texte: "Concentration" }),
        groupe(reste
          ? rangee(`Encore ${reste} min`, "Réseaux sociaux, vidéo et streaming sont bloqués jusqu'à la fin.",
            bouton("Arrêter", { genre: "braise", surClic: () => agir({ action: "concentration_fin" }, "Concentration arrêtée.") }))
          : rangee("Lancer une session", "Bloque les sites qui distraient, puis une notification annonce la pause.",
            [25, 50, 90].map((n) => bouton(`${n} min`, { genre: n === 25 ? "plein" : "", surClic: () => agir({ action: "concentration_debut", minutes: n }, `Concentration : ${n} minutes.`) })))),
      ];
    }],
    ["confidentialite", "Confidentialité et VPN", () => {
      const v = e.vpn;
      return [
        groupe(
          gChoix("lock_delay", "Verrouiller après l'extinction de l'écran", null, [[0, "Aussitôt"], [60, "1 min"], [300, "5 min"]]),
          gBascule("camera_off", "Caméra coupée pour toutes les applis"),
          gBascule("location", "Localisation", "Sert à la météo et au fuseau horaire."),
          gBascule("recent_files", "Garder l'historique des fichiers récents"),
          gBascule("old_trash", "Vider la corbeille après 30 jours"),
          gBascule("old_temp", "Supprimer les fichiers temporaires anciens")),
        h("h3", { texte: "VPN" }),
        groupe(
          v.configure ? rangee("VPN", v.actif ? "Actif : ta connexion passe par Proton VPN." : "Prêt.",
            interrupteur({ coche: v.actif, nom: "VPN", surChange: (x) => agir({ action: "vpn", actif: x }) })) : null,
          v.configure ? adaptatif("vpn_auto", "L'activer tout seul sur les Wi-Fi ouverts", "Cafés, gares, hôtels : les réseaux sans mot de passe.") : null,
          rangee(v.configure ? "Remplacer la configuration" : "Configurer l'activation automatique",
            "L'appli Proton VPN est déjà installée. Pour l'activation automatique : account.protonvpn.com, Téléchargements, WireGuard, télécharge un fichier .conf, puis importe-le ici.",
            bouton(v.configure ? "Choisir un autre fichier" : "Importer un fichier .conf", { genre: v.configure ? "" : "plein", surClic: () => fichierVpn.click() }))),
      ];
    }],
    ["cours", "Cours", () => {
      const m = e.cours;
      const echeances = (m.deadlines || []).filter((d) => d.time * 1000 > Date.now()).slice(0, 6);
      return [
        h("p", { class: "intro", texte: m.connected ? `Moodle est connecté : ${m.documents || 0} document(s) importé(s) dans tes notes, vérification toutes les 2 heures.`
          : "Connecte Moodle une fois : tes PDF de cours arrivent tout seuls dans tes notes, un classeur par cours, et tes échéances te sont rappelées. Seul un jeton est gardé, jamais ton mot de passe." }),
        groupe(
          echeances.map((d) => rangee(d.name, null, etiquette(HEURE.format(new Date(d.time * 1000))))),
          m.connected
            ? rangee("Moodle", "Connecté.", bouton("Synchroniser maintenant", { genre: "plein", surClic: () => agir({ action: "cours", quoi: "sync" }, "Synchronisation lancée.") }),
              bouton("Déconnecter", { genre: "braise", surClic: () => agirApresQuestion({ titre: "Déconnecter Moodle ?", texte: "Les documents déjà importés restent dans tes notes. Les nouveaux n'arriveront plus.", oui: "Déconnecter", danger: true }, { action: "cours", quoi: "disconnect" }) }))
            : rangee("Moodle", "Non connecté.", bouton("Connecter Moodle", { genre: "plein", surClic: () => agir({ action: "cours", quoi: "connect" }, "Fenêtre de connexion ouverte.") }))),
      ];
    }],
    ["maison", "Maison", () => {
      const m = e.maison;
      const jeton = h("input", { class: "champ", type: "password", placeholder: "Jeton d'accès Smoky Home", "aria-label": "Jeton d'accès Smoky Home", autocomplete: "off" });
      return [groupe(
        rangee("Smoky Home", m.active ? "Démarré : robot, lumières et enceintes sont joignables." : "Arrêté. Il démarre quand tu l'ouvres.",
          bouton("Ouvrir Smoky Home", { surClic: () => agir({ action: "maison_ouvrir" }, "Smoky Home s'ouvre dans sa fenêtre.") })),
        rangee("Le garder démarré", "Les boutons « Maison » du menu en haut à droite répondent tout de suite.",
          interrupteur({ coche: m.arriere_plan, nom: "Garder Smoky Home démarré", surChange: (v) => agir({ action: "maison_arriere_plan", actif: v }) })),
        rangee("Boutons du menu en haut à droite", m.jeton ? "Reliés. Pour changer de jeton, colle le nouveau." : "À relier : dans Smoky Home, ton profil (en bas à gauche), Sécurité, Jetons d'accès longue durée, Créer.",
          jeton, bouton("Relier", { genre: m.jeton ? "" : "plein", surClic: () => agir({ action: "maison_jeton", jeton: jeton.value }, "Boutons maison reliés.") })))];
    }],
    ["stockage", "Stockage et sauvegardes", () => {
      const s = e.stockage, t = e.travaux, sv = e.sauvegarde || {};
      const jauge = h("div", { class: "jauge", role: "img", "aria-label": `${s.utilise_pct} % du disque utilisé` }, h("i"));
      jauge.firstChild.style.width = `${Math.min(100, Number(s.utilise_pct) || 0)}%`;
      const quand = sv.days === null || sv.days === undefined ? "Jamais faite." : sv.days === 0 ? "Faite aujourd'hui." : `Faite il y a ${sv.days} jour${sv.days > 1 ? "s" : ""}.`;
      const sauvegarde = rangee("Sauvegarde de ton dossier personnel", `${quand}${sv.late ? " Une sauvegarde est à faire." : ""}${sv.days !== null && sv.days !== undefined && !sv.periodic ? " Active « Sauvegarde automatique » dans Déjà Dup pour ne plus y penser." : ""}`,
        bouton("Ouvrir les sauvegardes", { genre: sv.late ? "plein" : "", surClic: () => agir({ action: "sauvegarde_ouvrir" }) }));
      if (sv.late) sauvegarde.classList.add("alerte");
      return [groupe(
        rangee(`${s.libre} libres sur ${s.total}`, `Corbeille : ${s.corbeille || "?"}. Caches : ${s.cache || "?"}.`, jauge),
        rangee("Nettoyer", `Vide la corbeille et les caches (Chrome, miniatures), retire les composants d'applis inutilisés. Tes fichiers ne sont jamais touchés.${t.nettoyage.resultat ? ` Dernier nettoyage : ${t.nettoyage.resultat} libérés.` : ""}`,
          Object.assign(bouton(t.nettoyage.en_cours ? "Nettoyage…" : "Nettoyer", { surClic: () => agirApresQuestion({ titre: "Vider la corbeille et les caches ?", texte: "Tes fichiers et tes notes ne sont pas touchés. Ce qui est dans la corbeille est supprimé pour de bon.", oui: "Nettoyer", danger: true }, { action: "nettoyer" }, "Nettoyage lancé.") }), { disabled: t.nettoyage.en_cours })),
        rangee("Applis", `Proton VPN, mpv, Déjà Dup… se mettent à jour avec le système ; ce bouton le fait tout de suite.${t.applis.resultat === "erreur" ? " La dernière mise à jour a échoué : vérifie la connexion." : ""}`,
          Object.assign(bouton(t.applis.en_cours ? "Mise à jour…" : "Mettre à jour les applis", { surClic: () => agir({ action: "applis_mettre_a_jour" }, "Mise à jour des applis lancée.") }), { disabled: t.applis.en_cours })),
        sauvegarde,
        rangee("Logos Smoky", "Les logos des nouvelles applis passent au style Smoky tout seuls. Ce bouton force la mise à jour.",
          bouton("Régénérer les logos", { surClic: () => agir({ action: "logos" }) })))];
    }],
    ["maj", "Mises à jour et démarrage", () => {
      const m = e.maj, i = e.infos;
      const texte = m.en_cours ? "Téléchargement de la nouvelle version de Smoky OS : quelques minutes, tu peux continuer à utiliser le PC."
        : m.prete ? "Nouvelle version téléchargée : elle s'applique au redémarrage."
          : m.resultat === "a_jour" ? "Smoky OS est à jour."
            : m.resultat === "erreur" ? "La recherche a échoué : vérifie la connexion internet."
              : "Smoky OS se met aussi à jour tout seul chaque semaine, au redémarrage. En cas de souci, la version précédente reste proposée au démarrage.";
      const redemarrer = () => agirApresQuestion({ titre: "Redémarrer maintenant ?", texte: "Enregistre ton travail avant.", oui: "Redémarrer" }, { action: "redemarrer" });
      return [
        groupe(
          rangee("Smoky OS", texte, m.prete ? bouton("Redémarrer", { genre: "plein", surClic: redemarrer })
            : Object.assign(bouton(m.en_cours ? "Mise à jour en cours…" : "Rechercher une mise à jour", { genre: "plein", surClic: () => agir({ action: "mettre_a_jour" }, "Recherche lancée.") }), { disabled: m.en_cours })),
          e.windows ? rangee("Redémarrer sur Windows", "Une seule fois : au redémarrage suivant, le PC revient sur Smoky OS.",
            bouton("Redémarrer sur Windows", { surClic: () => agirApresQuestion({ titre: "Redémarrer sur Windows maintenant ?", texte: "Enregistre ton travail avant. Au redémarrage suivant, le PC revient sur Smoky OS.", oui: "Redémarrer sur Windows" }, { action: "windows" }) })) : null,
          rangee("Réglages UEFI (BIOS)", "Ouvre directement les réglages du firmware, sans appuyer sur F2. Pour en sortir : F10 enregistre, Échap quitte sans rien changer.",
            bouton("Redémarrer vers l'UEFI", { surClic: () => agirApresQuestion({ titre: "Redémarrer dans les réglages UEFI ?", texte: "Enregistre ton travail avant.", oui: "Redémarrer vers l'UEFI" }, { action: "uefi" }) })),
          rangee("Démarrage vérifié (Secure Boot)", e.demarrage_securise === "off" ? "À activer : redémarre vers l'UEFI, puis Security, Secure Boot, Enabled, et F10. Smoky OS et Windows démarrent tous les deux avec." : null,
            etiquette(e.demarrage_securise === "on" ? "Activé" : e.demarrage_securise === "off" ? "Désactivé" : "Inconnu"))),
        h("h3", { texte: "À propos" }),
        groupe(
          rangee("Système", null, etiquette(i.systeme)),
          rangee("Noyau", null, etiquette(i.noyau)),
          rangee("Mémoire", null, etiquette(i.memoire)),
          i.temperature ? rangee("Processeur", null, etiquette(i.temperature)) : null,
          rangee("Allumé depuis", null, etiquette(i.allume))),
      ];
    }],
  ];

  fichierVpn.addEventListener("change", async () => {
    const f = fichierVpn.files[0];
    fichierVpn.value = "";
    if (!f) return;
    if (f.size > 20000) { annoncer("Ce fichier est trop gros pour être une configuration WireGuard.", { erreur: true }); return; }
    agir({ action: "vpn_importer", contenu: await f.text() }, "Configuration VPN importée.");
  });

  function dessiner() {
    if (!e) return;
    const actifs = [...contenu.querySelectorAll("button, input")];
    const index = actifs.indexOf(document.activeElement);
    for (const a of sommaire.children) { if (a.dataset.section === section) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); }
    const [, nom, faire] = SECTIONS.find(([id]) => id === section);
    const noeuds = faire().flat().filter(Boolean);
    contenu.replaceChildren(h("h2", { texte: nom }), ...(noeuds.length ? noeuds : [h("p", { class: "vide", texte: "Ces réglages ne sont pas disponibles sur cette machine." })]));
    if (index >= 0) contenu.querySelectorAll("button, input")[index]?.focus({ preventScroll: true });
  }

  async function relire() {
    try { e = await api.lire("/api/systeme"); if (!enCours) dessiner(); } catch (erreur) { if (!e) annoncer(erreur.message, { erreur: true }); }
  }

  function aller(suite) {
    const voulue = SECTIONS.some(([id]) => id === suite?.[0]) ? suite[0] : "energie";
    if (voulue !== section) { section = voulue; dessiner(); conteneur.scrollTop = 0; }
  }

  for (const [id, nom] of SECTIONS) sommaire.append(h("a", { href: `#/systeme/${id}`, "data-section": id }, nom));
  conteneur.replaceChildren(
    h("header", { class: "entete" }, h("h1", { texte: "système" })),
    h("div", { class: "corps systeme" }, sommaire, contenu), fichierVpn);
  section = SECTIONS.some(([id]) => id === contexte.suite?.[0]) ? contexte.suite[0] : "energie";
  contenu.replaceChildren(h("p", { class: "vide", texte: "Lecture de l'état du PC…" }));

  const tic = () => { if (document.visibilityState === "visible") relire(); };
  minuterie = setInterval(tic, 20000);
  document.addEventListener("visibilitychange", tic);
  const oublier = contexte.surChangement((quoi) => { if (quoi === "systeme") relire(); });
  await relire();
  return { aller, demonter() { clearInterval(minuterie); document.removeEventListener("visibilitychange", tic); oublier(); } };
}
