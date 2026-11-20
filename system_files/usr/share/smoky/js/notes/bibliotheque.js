// Smoky — Notes : la bibliothèque. Les carnets rangés par classeur (une matière, ou ton propre
// classeur), le plus récemment écrit d'abord ; favoris, recherche, corbeille.
import { h, icone, bouton, annoncer, confirmer, segment, remplacer, ajouter } from "/js/ui.js";
import { api, tenter } from "/js/app.js";
import { COUVERTURES, MODELES, COULEURS, FORMATS } from "/js/notes/papier.js";
import { CarnetOuvert } from "/js/notes/stockage.js";
import * as pdf from "/js/notes/pdf.js";

const HEURE = new Intl.DateTimeFormat("fr-FR", { hour: "numeric", minute: "2-digit" });
const JOUR = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long" });
const JOUR_ANNEE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });

export function quand(ms, maintenant = Date.now()) {
  if (!ms) return "";
  const d = new Date(ms), n = new Date(maintenant);
  const minutes = Math.round((maintenant - ms) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const jour = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const ecart = Math.round((jour(n) - jour(d)) / 86400000);
  if (ecart === 0) return `aujourd'hui à ${HEURE.format(d).replace(":", " h ")}`;
  if (ecart === 1) return "hier";
  return `le ${(d.getFullYear() === n.getFullYear() ? JOUR : JOUR_ANNEE).format(d)}`;
}

export function monterBibliotheque(conteneur, { vue = "tous", classeur = null, surOuvrir, contexte }) {
  let b = null;                       // ce que le serveur renvoie (carnets, corbeille, matières…)
  let recherche = "";
  let instant = -1;                   // lecture du dossier affichée (les réponses peuvent arriver dans le désordre)

  const sous = h("p", { class: "sous" });
  const actions = h("div", { class: "boutons" });
  const corps = h("div", { class: "corps large" });
  const page = h("div", { class: "notes-biblio" },
    h("header", { class: "entete" }, h("div", {}, h("h1", { texte: "notes" }), sous), actions), corps);
  conteneur.replaceChildren(page);

  const choixPdf = h("input", { type: "file", accept: "application/pdf,.pdf", hidden: true });
  choixPdf.addEventListener("change", () => { const f = choixPdf.files[0]; choixPdf.value = ""; if (f) importerPdf(f); });
  page.append(choixPdf);

  async function relire() {
    try {
      const r = await api.lire("/api/notes");
      if (r.instant < instant) return;              // plus ancienne que ce qui est déjà affiché
      instant = r.instant;
      b = r;
      dessiner();
    } catch (e) { annoncer(e.message, { erreur: true }); }
  }

  const tousLesClasseurs = () => {
    const noms = new Set((b?.matieres || []).map((m) => m.nom));
    for (const c of b?.carnets || []) if (c.classeur) noms.add(c.classeur);
    return [...noms];
  };

  function dessiner() {
    if (!b) return;
    const n = b.carnets.length;
    sous.textContent = vue === "corbeille" ? "corbeille"
      : classeur ? `classeur ${classeur}` : n ? `${n} carnet${n > 1 ? "s" : ""}` : "tes carnets";
    remplacer(actions,
      vue === "corbeille" ? null : bouton("Importer un PDF", { titre: "Un cours en PDF devient un carnet à annoter", surClic: () => choixPdf.click() }),
      vue === "corbeille" ? null : bouton("Nouveau carnet", { genre: "plein", surClic: () => creer() }));
    const recherchee = h("input", { class: "champ recherche", type: "search", placeholder: "Chercher un carnet", "aria-label": "Chercher un carnet", value: recherche });
    recherchee.addEventListener("input", () => {
      recherche = recherchee.value;
      const curseur = recherchee.selectionStart;
      dessinerListe();
      recherchee.focus();
      recherchee.setSelectionRange(curseur, curseur);
    });
    const filtres = h("div", { class: "filtres" },
      segment({ options: [["tous", "Tous"], ["favoris", "Favoris"], ["corbeille", `Corbeille${b.corbeille.length ? ` (${b.corbeille.length})` : ""}`]],
        valeur: vue === "corbeille" ? "corbeille" : vue === "favoris" ? "favoris" : "tous", nom: "Afficher",
        surChange: (v) => { location.hash = v === "corbeille" ? "#/notes/corbeille" : v === "favoris" ? "#/notes/favoris" : "#/notes"; } }),
      vue === "corbeille" ? null : recherchee);
    remplacer(corps, filtres,
      classeur ? h("p", { class: "fil" }, h("a", { href: "#/notes", texte: "Tous les carnets" }), ` › ${classeur}`) : null,
      h("div", { class: "liste-carnets" }),
      b.ancien && vue === "tous" && !classeur ? anciens() : null);
    dessinerListe();
  }

  // Les carnets d'avant la refonte restent dans l'ancienne appli, intacts : on rappelle où ils sont.
  function anciens() {
    return h("section", { class: "anciens-carnets", "aria-labelledby": "t-anciens" },
      h("h2", { id: "t-anciens", texte: "carnets d'avant" }),
      h("p", { class: "discret petit", texte: "Tes carnets d'avant restent dans l'ancien Smoky Notes, sans changement. Ils ne sont pas repris ici." }),
      bouton("Ouvrir l'ancien Smoky Notes", { surClic: () => tenter(() => api.envoyer("/api/ouvrir", { quoi: "notes" }),
        { succes: "L'ancien Smoky Notes s'ouvre dans sa fenêtre." }) }));
  }

  function dessinerListe() {
    const zone = corps.querySelector(".liste-carnets");
    if (!zone) return;
    if (vue === "corbeille") { zone.replaceChildren(corbeille()); return; }
    const q = recherche.trim().toLocaleLowerCase("fr");
    let carnets = b.carnets.filter((c) => (!classeur || c.classeur === classeur) && (vue !== "favoris" || c.favori)
      && (!q || c.titre.toLocaleLowerCase("fr").includes(q) || c.classeur.toLocaleLowerCase("fr").includes(q)));
    if (!b.carnets.length) { zone.replaceChildren(invitation()); return; }
    if (!carnets.length) {
      remplacer(zone, h("p", { class: "vide-liste", texte: q ? "Aucun carnet ne porte ce nom." : vue === "favoris" ? "Aucun favori : ouvre le menu d'un carnet pour l'ajouter." : "Ce classeur est vide." }),
        classeur ? bouton(`Nouveau carnet dans ${classeur}`, { genre: "plein", surClic: () => creer() }) : null);
      return;
    }
    // Peu de carnets, une recherche, les favoris ou un classeur : une seule grille. Sinon : les
    // derniers carnets écrits, puis les classeurs (une pile de couvertures chacun), puis le reste.
    if (classeur || q || vue === "favoris" || b.carnets.length <= 6) {
      remplacer(zone, h("ul", { class: "grille-carnets" }, carnets.map((c) => carte(c, !classeur))));
      return;
    }
    const groupes = new Map();
    for (const c of carnets) {
      if (!c.classeur) continue;
      if (!groupes.has(c.classeur)) groupes.set(c.classeur, []);
      groupes.get(c.classeur).push(c);
    }
    const seuls = carnets.filter((c) => !c.classeur);
    remplacer(zone,
      h("section", { class: "classeur", "aria-labelledby": "t-recents" }, h("h2", { id: "t-recents", texte: "derniers carnets" }),
        h("ul", { class: "grille-carnets" }, carnets.slice(0, 6).map((c) => carte(c, true)))),
      groupes.size ? h("section", { class: "classeur", "aria-labelledby": "t-classeurs" }, h("h2", { id: "t-classeurs", texte: "classeurs" }),
        h("ul", { class: "grille-carnets" }, [...groupes.entries()].map(([nom, liste]) => dossier(nom, liste)))) : null,
      seuls.length ? h("section", { class: "classeur", "aria-labelledby": "t-seuls" }, h("h2", { id: "t-seuls", texte: "sans classeur" }),
        h("ul", { class: "grille-carnets" }, seuls.map((c) => carte(c)))) : null);
  }

  // Un classeur : ses trois dernières couvertures en pile
  function dossier(nom, liste) {
    const pile = h("div", { class: "pile-couvertures", "aria-hidden": "true" }, liste.slice(0, 3).reverse().map((c) => couverture(c)));
    return h("li", { class: "carnet dossier" },
      h("a", { class: "ouvrir", href: `#/notes/classeur/${encodeURIComponent(nom)}`, "aria-label": `Classeur ${nom}, ${liste.length} carnet${liste.length > 1 ? "s" : ""}` },
        pile, h("span", { class: "titre", texte: nom }), h("span", { class: "meta", texte: `${liste.length} carnet${liste.length > 1 ? "s" : ""}` })));
  }

  function couverture(c, grand = false) {
    const cv = COUVERTURES[c.couverture] || COUVERTURES.fumee;
    const div = h("div", { class: grand ? "couverture grande" : "couverture", "aria-hidden": "true" },
      h("span", { class: "dos" }), h("span", { class: "nom", texte: c.titre }),
      c.pdf ? h("span", { class: "etiquette", texte: "PDF" }) : null);
    div.style.background = `linear-gradient(155deg, ${cv.a}, ${cv.b})`;
    div.style.color = cv.texte;
    return div;
  }

  function carte(c, avecClasseur = false) {
    const meta = `${avecClasseur && c.classeur ? `${c.classeur}, ` : ""}${c.pages} page${c.pages > 1 ? "s" : ""}, ${quand(c.modifie)}`;
    return h("li", { class: "carnet" },
      h("button", { type: "button", class: "ouvrir", "aria-label": `Ouvrir ${c.titre}, ${meta}`, surclick: () => surOuvrir(c.id) },
        couverture(c), h("span", { class: "titre", texte: c.titre }), h("span", { class: "meta", texte: meta })),
      c.favori ? h("span", { class: "favori", title: "Favori", "aria-label": "Favori" }, icone("signet")) : null,
      h("button", { type: "button", class: "icone-seule options", "aria-label": `Options de ${c.titre}`, surclick: (e) => options(c, e.currentTarget) }, icone("menu")));
  }

  function invitation() {
    return h("section", { class: "invitation" },
      h("h2", { texte: "ton premier carnet" }),
      h("p", { class: "secondaire", texte: "Un carnet par matière, ou un cours en PDF à annoter au stylet. Tout est rangé dans Notes/Carnets, et donc sauvegardé avec Google Drive comme le reste du dossier Notes." }),
      h("div", { class: "boutons" },
        bouton("Nouveau carnet", { genre: "plein", surClic: () => creer() }),
        bouton("Importer un PDF", { surClic: () => choixPdf.click() })));
  }

  function corbeille() {
    if (!b.corbeille.length) return h("p", { class: "vide-liste", texte: "La corbeille est vide." });
    return h("ul", { class: "liste-corbeille" }, b.corbeille.map((c) => h("li", {},
      couverture(c),
      h("div", { class: "quoi" }, h("span", { class: "titre", texte: c.titre }),
        h("span", { class: "meta", texte: `${c.pages} page${c.pages > 1 ? "s" : ""}, mis à la corbeille ${quand(c.jete)}` })),
      h("div", { class: "boutons" },
        bouton("Restaurer", { surClic: () => agir({ action: "restaurer", id: c.id }) }),
        bouton("Effacer", { genre: "braise", surClic: async () => {
          if (await confirmer({ titre: `Effacer « ${c.titre} » pour de bon ?`, texte: "Il ne pourra plus être restauré.", oui: "Effacer", danger: true })) {
            agir({ action: "effacer", id: c.id });
          }
        } })))));
  }

  async function agir(corps2) {
    try {
      const r = await api.envoyer("/api/notes", corps2);
      if (r.message) annoncer(r.message);
      await relire();
      return r;
    } catch (e) { annoncer(e.message, { erreur: true }); return null; }
  }

  // --- Menu d'un carnet ---------------------------------------------------------------------------------
  function options(c, ancre) {
    const d = h("dialog", { class: "menu-notes", "aria-label": `Options de ${c.titre}` });
    const fermer = () => d.close();
    const entree = (texte, faire, danger = false) => h("button", { type: "button", class: danger ? "entree braise" : "entree", surclick: () => { fermer(); faire(); } }, texte);
    ajouter(d,
      h("div", { class: "groupe-menu" },
        entree("Ouvrir", () => surOuvrir(c.id)),
        entree("Renommer", () => renommer(c)),
        entree(c.favori ? "Retirer des favoris" : "Ajouter aux favoris", () => agir({ action: "favori", id: c.id, favori: !c.favori })),
        entree("Ranger dans un classeur", () => ranger(c)),
        entree("Dupliquer", () => agir({ action: "dupliquer", id: c.id }))),
      h("div", { class: "groupe-menu" }, h("p", { class: "titre-groupe", texte: "couverture" }),
        h("div", { class: "nuancier-couvertures" }, Object.entries(COUVERTURES).map(([k, cv]) => {
          const pastille = h("button", { type: "button", class: "pastille-couverture", "aria-label": `Couverture ${cv.nom}`, "aria-pressed": String(c.couverture === k),
            surclick: () => { fermer(); agir({ action: "couverture", id: c.id, couverture: k }); } });
          pastille.style.background = `linear-gradient(155deg, ${cv.a}, ${cv.b})`;
          return pastille;
        }))),
      h("div", { class: "groupe-menu" }, entree("Mettre à la corbeille", () => agir({ action: "supprimer", id: c.id }), true)));
    d.addEventListener("close", () => d.remove());
    document.body.append(d);
    d.show();
    const r = ancre.getBoundingClientRect();
    const haut = Math.min(r.bottom + 6, innerHeight - d.offsetHeight - 8);
    Object.assign(d.style, { position: "fixed", top: `${Math.max(8, haut)}px`, left: `${Math.max(8, Math.min(r.left, innerWidth - d.offsetWidth - 8))}px`, margin: "0" });
    d.querySelector("button")?.focus();
    const dehors = (e) => { if (!d.contains(e.target)) { fermer(); document.removeEventListener("pointerdown", dehors, true); } };
    document.addEventListener("pointerdown", dehors, true);
    d.addEventListener("keydown", (e) => { if (e.key === "Escape") fermer(); });
  }

  function demander({ titre, etiquette, valeur = "", oui, liste = null }) {
    return new Promise((resoudre) => {
      const champ = h("input", { class: "champ", type: "text", value: valeur, maxlength: "100", "aria-label": etiquette, list: liste ? "classeurs-connus" : null });
      const d = h("dialog", { class: "demande" },
        h("form", { method: "dialog" },
          h("h2", { texte: titre }),
          h("label", {}, h("span", { texte: etiquette }), champ),
          liste ? h("datalist", { id: "classeurs-connus" }, liste.map((x) => h("option", { value: x }))) : null,
          h("div", { class: "boutons" }, bouton("Annuler", { surClic: () => d.close("") }), h("button", { type: "submit", class: "bouton plein" }, oui))));
      d.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); d.close("ok"); });
      d.addEventListener("close", () => { d.remove(); resoudre(d.returnValue === "ok" ? champ.value.trim() : null); });
      document.body.append(d);
      d.showModal();
      champ.select();
    });
  }

  async function renommer(c) {
    const titre = await demander({ titre: "renommer", etiquette: "Nom du carnet", valeur: c.titre, oui: "Renommer" });
    if (titre && titre !== c.titre) agir({ action: "renommer", id: c.id, titre });
  }

  async function ranger(c) {
    const nom = await demander({ titre: "ranger", etiquette: "Classeur (une matière, ou un nom de ton choix ; vide : aucun)", valeur: c.classeur, oui: "Ranger", liste: tousLesClasseurs() });
    if (nom !== null && nom !== c.classeur) agir({ action: "classer", id: c.id, classeur: nom });
  }

  // --- Nouveau carnet ---------------------------------------------------------------------------------
  function creer() {
    const matiere = (b.matieres || []).find((m) => m.nom === classeur);
    let modele = matiere?.modele || "ligne", couleur = "blanc", format = "a4", cv = "fumee";
    const titre = h("input", { class: "champ", type: "text", maxlength: "100", value: classeur || "", "aria-label": "Nom du carnet", placeholder: "Algèbre, Projet de BDR…" });
    const choixClasseur = h("input", { class: "champ", type: "text", maxlength: "60", value: classeur || "", list: "classeurs-nouveau", "aria-label": "Classeur" });
    const apercu = h("div", { class: "apercu-papier", "aria-hidden": "true" });
    const peindreApercu = () => {
      apercu.dataset.modele = modele;
      apercu.style.backgroundColor = COULEURS[couleur].fond;
      apercu.dataset.sombre = String(!COULEURS[couleur].clair);
      apercu.style.aspectRatio = `${FORMATS[format].w} / ${FORMATS[format].h}`;
    };
    const pastilles = h("div", { class: "nuancier-couvertures" }, Object.entries(COUVERTURES).map(([k, x]) => {
      const p = h("button", { type: "button", class: "pastille-couverture", "aria-label": `Couverture ${x.nom}`, "aria-pressed": String(k === cv),
        surclick: () => { cv = k; for (const autre of pastilles.children) autre.setAttribute("aria-pressed", String(autre === p)); } });
      p.style.background = `linear-gradient(155deg, ${x.a}, ${x.b})`;
      return p;
    }));
    const d = h("dialog", { class: "nouveau-carnet", "aria-labelledby": "t-nouveau" },
      h("form", { method: "dialog" },
        h("h2", { id: "t-nouveau", texte: "nouveau carnet" }),
        h("div", { class: "deux-colonnes" },
          h("div", { class: "champs" },
            h("label", {}, h("span", { texte: "Nom" }), titre),
            h("label", {}, h("span", { texte: "Classeur" }), choixClasseur),
            h("datalist", { id: "classeurs-nouveau" }, tousLesClasseurs().map((x) => h("option", { value: x }))),
            h("div", { class: "choix" }, h("span", { texte: "Papier" }),
              segment({ options: Object.entries(MODELES), valeur: modele, nom: "Papier", surChange: (v) => { modele = v; peindreApercu(); } })),
            h("div", { class: "choix" }, h("span", { texte: "Couleur du papier" }),
              segment({ options: Object.entries(COULEURS).map(([k, x]) => [k, x.nom]), valeur: couleur, nom: "Couleur du papier", surChange: (v) => { couleur = v; peindreApercu(); } })),
            h("div", { class: "choix" }, h("span", { texte: "Format" }),
              segment({ options: Object.entries(FORMATS).map(([k, x]) => [k, x.nom]), valeur: format, nom: "Format", surChange: (v) => { format = v; peindreApercu(); } })),
            h("div", { class: "choix" }, h("span", { texte: "Couverture" }), pastilles)),
          apercu),
        h("div", { class: "boutons" }, bouton("Annuler", { surClic: () => d.close() }), h("button", { type: "submit", class: "bouton plein" }, "Créer"))));
    // la matière choisie propose son papier habituel
    choixClasseur.addEventListener("change", () => {
      const m = (b.matieres || []).find((x) => x.nom === choixClasseur.value.trim());
      if (m && m.modele !== modele) {
        modele = m.modele;
        for (const bt of d.querySelectorAll('[aria-label="Papier"] button')) bt.setAttribute("aria-pressed", String(bt.textContent === MODELES[modele]));
        peindreApercu();
      }
      if (!titre.value.trim() && m) titre.value = m.nom;
    });
    d.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!titre.value.trim()) { titre.focus(); annoncer("Donne un nom au carnet.", { erreur: true }); return; }
      const r = await agir({ action: "creer", titre: titre.value.trim(), classeur: choixClasseur.value.trim(), couverture: cv, papier: { format, modele, couleur } });
      if (r?.carnet) { d.close(); surOuvrir(r.carnet.id); }
    });
    d.addEventListener("close", () => d.remove());
    document.body.append(d);
    peindreApercu();
    d.showModal();
    titre.focus();
  }

  // --- Un PDF devient un carnet ---------------------------------------------------------------------------
  async function importerPdf(fichier) {
    const titre = fichier.name.replace(/\.pdf$/i, "").replace(/[_]+/g, " ").trim().slice(0, 100) || "Cours";
    annoncer(`Import de « ${titre} »…`);
    const r = await agir({ action: "creer", titre, classeur: classeur || "", couverture: "ardoise", vide: true });
    if (!r?.carnet) return;
    const carnet = new CarnetOuvert(r.carnet);
    try {
      carnet.carnet.pages = await pdf.importer(carnet, fichier);
      carnet.modifierCarnet();
      await carnet.enregistrer();
      if (carnet.aEnregistrer()) throw new Error("Le carnet n'a pas pu être enregistré.");
      carnet.ferme = true;
      surOuvrir(r.carnet.id);
    } catch (e) {
      carnet.ferme = true;
      annoncer(e.message || "Ce PDF n'a pas pu être importé.", { erreur: true });
      try {                                           // pas de carnet vide laissé derrière
        await api.envoyer("/api/notes", { action: "supprimer", id: r.carnet.id });
        const restes = (await api.lire("/api/notes")).corbeille.filter((c) => c.id.startsWith(`${r.carnet.id}-`));
        for (const c of restes) await api.envoyer("/api/notes", { action: "effacer", id: c.id });
      } catch { /* tant pis : il reste dans la bibliothèque, vide */ }
      relire();
    }
  }

  const oublier = contexte.surChangement((quoi) => { if (quoi === "notes" || !quoi) relire(); });
  relire();
  return {
    demonter() { oublier(); },
    aller(nouvelleVue, nouveauClasseur) { vue = nouvelleVue; classeur = nouveauClasseur; dessiner(); },
  };
}
