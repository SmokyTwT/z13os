// Smoky — Notes : l'éditeur d'un carnet.
// Les pages s'empilent verticalement ; seules celles proches de l'écran ont leurs dessins (trois
// calques : papier ou PDF, encre, et « vif » pour ce qui est en train de s'écrire). Le stylet
// écrit ; les doigts font défiler, zoomer, et annulent (2 doigts) ou rétablissent (3 doigts).
import { h, icone, annoncer, confirmer, remplacer, ajouter } from "/js/ui.js";
import { api } from "/js/app.js";
import { CarnetOuvert, nouvelId, nomFichier } from "/js/notes/stockage.js";
import { chemin2D, rempli, bornes, touche, gommer, dansLasso, transformer } from "/js/notes/encre.js";
import { reconnaitre, gribouillis, cibles } from "/js/notes/formes.js";
import { peindrePapier, COULEURS, MODELES, FORMATS, ENCRES, SURLIGNEURS } from "/js/notes/papier.js";
import * as pdf from "/js/notes/pdf.js";
import { Enregistreur } from "/js/notes/audio.js";

const ESPACE = 28;                       // entre deux pages, en pixels d'écran
const MARGE = 28;
const ZOOM_MIN = 0.35, ZOOM_MAX = 5;
const PIXELS_MAXI = 16e6;                // taille maxi d'un calque (mémoire)
const ROUGE = "#ff5a52";
const dpr = () => Math.min(window.devicePixelRatio || 1, 2.5);

export const OUTILS_DEFAUT = {
  outil: "stylo",
  stylo: { couleur: "#141417", largeur: 2 },
  surligneur: { couleur: "#ffe45c", largeur: 14 },
  gomme: { largeur: 14, precise: false },
  texte: { couleur: "#141417", largeur: 16 },
  doigt: false, formes: true, gribouillis: true,
};
const LARGEURS = { stylo: [1.2, 2, 3.4], surligneur: [8, 14, 22], gomme: [6, 14, 30], texte: [12, 16, 24] };
const NOMS = { stylo: "Stylo", surligneur: "Surligneur", gomme: "Gomme", lasso: "Lasso", texte: "Texte", laser: "Pointeur laser", ecouter: "Écouter" };

export async function monterEditeur(conteneur, { carnetId, prefs, surRetour, enregistrerPrefs, contexte }) {
  const carnetBrut = await api.lire(`/api/notes/${encodeURIComponent(carnetId)}`);
  const etat = h("span", { class: "etat-enregistrement", "aria-live": "polite" });
  const carnet = new CarnetOuvert(carnetBrut, { surEtat: (e, m) => montrerEtat(e, m) });
  const reglages = structuredClone({ ...OUTILS_DEFAUT, ...(prefs || {}) });
  let outil = reglages.outil in NOMS ? reglages.outil : "stylo";
  let zoom = 1;
  let ajuste = true;                              // zoom « page entière en largeur » (suit la fenêtre)
  const vues = new Map();                         // id de page → vue (div + calques), seulement près de l'écran
  const pileAnnuler = [], pileRefaire = [];
  let selection = null;                           // { pid, items: [{ genre, item }], boite }
  let pressePapier = null;
  let action = null;                              // geste en cours avec le stylet / la souris / un doigt qui dessine
  const doigts = new Map();                       // doigts posés (pointerId → { x, y, x0, y0, t0 })
  let geste = null;                               // pincement / défilement aux doigts
  let dernierStylet = -1e9;                       // rejet de la paume : un stylet vu à l'instant
  let elan = 0;                                   // défilement qui continue sur sa lancée
  let rendu = 0;
  let enLecture = null;                           // lecture d'un enregistrement
  const enregistreur = new Enregistreur();

  // --- Charpente --------------------------------------------------------------------------------
  const titre = h("input", { class: "titre-carnet", value: carnet.carnet.titre, "aria-label": "Nom du carnet", maxlength: "100", spellcheck: "false" });
  const numero = h("span", { class: "numero-page" });
  const outils = h("div", { class: "outils", role: "toolbar", "aria-label": "Outils" });
  const reglageOutil = h("div", { class: "reglage-outil", role: "group", "aria-label": "Réglages de l'outil" });
  const boutonAnnuler = h("button", { type: "button", class: "icone-seule", "aria-label": "Annuler", title: "Annuler (Ctrl+Z, ou toucher à deux doigts)", surclick: () => annuler() }, icone("annuler"));
  const boutonRefaire = h("button", { type: "button", class: "icone-seule", "aria-label": "Rétablir", title: "Rétablir (Ctrl+Maj+Z, ou toucher à trois doigts)", surclick: () => refaire() }, icone("retablir"));
  const boutonMicro = h("button", { type: "button", class: "icone-seule", "aria-label": "Enregistrer le son", title: "Enregistrer le cours : ce que tu écris est relié au son", surclick: () => basculerEnregistrement() }, icone("micro"));
  const panneau = h("aside", { class: "panneau-pages", hidden: true, "aria-label": "Pages du carnet" });
  const barreLecture = h("div", { class: "barre-lecture", hidden: true });
  const barre = h("header", { class: "barre-notes" },
    h("div", { class: "rangee-haut" },
      h("button", { type: "button", class: "icone-seule", "aria-label": "Revenir aux carnets", title: "Revenir aux carnets", surclick: () => surRetour() }, icone("gauche")),
      titre, etat,
      h("div", { class: "pousse" }),
      numero,
      boutonMicro,
      h("button", { type: "button", class: "icone-seule", "aria-label": "Pages", title: "Pages du carnet", surclick: () => basculerPanneau() }, icone("pages")),
      h("button", { type: "button", class: "icone-seule", "aria-label": "Plus d'options", title: "Ajouter, exporter…", surclick: (e) => menu(e.currentTarget) }, icone("menu"))),
    h("div", { class: "rangee-outils" }, outils, h("span", { class: "separateur" }), reglageOutil, h("div", { class: "pousse" }), boutonAnnuler, boutonRefaire));
  const pile = h("div", { class: "pile" });
  const feuilles = h("div", { class: "feuilles", tabindex: "0", "aria-label": `Pages de ${carnet.carnet.titre}` }, pile);
  const racine = h("div", { class: "editeur" }, barre, h("div", { class: "zone" }, feuilles, panneau), barreLecture);
  conteneur.replaceChildren(racine);
  titre.addEventListener("change", () => renommer());
  titre.addEventListener("keydown", (e) => { if (e.key === "Enter") titre.blur(); });

  function montrerEtat(e, message) {
    etat.dataset.etat = e;
    etat.textContent = { modifie: "", en_cours: "Enregistrement…", enregistre: "Enregistré", erreur: "Pas encore enregistré" }[e] || "";
    etat.title = e === "erreur" ? `${message || ""} Nouvel essai dans quelques secondes.` : "";
  }

  async function renommer() {
    const nouveau = titre.value.trim();
    if (!nouveau || nouveau === carnet.carnet.titre) { titre.value = carnet.carnet.titre; return; }
    try {
      await api.envoyer("/api/notes", { action: "renommer", id: carnet.carnet.id, titre: nouveau });
      carnet.carnet.titre = nouveau;
    } catch (e) { titre.value = carnet.carnet.titre; annoncer(e.message, { erreur: true }); }
  }

  // --- Outils -----------------------------------------------------------------------------------
  function dessinerOutils() {
    outils.replaceChildren(...["stylo", "surligneur", "gomme", "lasso", "texte", "laser"].map((o) =>
      h("button", { type: "button", class: "icone-seule outil", "aria-pressed": String(o === outil), "aria-label": NOMS[o], title: NOMS[o],
        surclick: () => choisirOutil(o) }, icone(o))));
    if (carnet.carnet.sons?.length) {
      outils.append(h("button", { type: "button", class: "icone-seule outil", "aria-pressed": String(outil === "ecouter"), "aria-label": NOMS.ecouter,
        title: "Écouter : touche ce que tu as écrit pendant un enregistrement", surclick: () => choisirOutil("ecouter") }, icone("ecouter")));
    }
    const r = reglages[outil];
    const elements = [];
    if (outil === "stylo" || outil === "surligneur" || outil === "texte") {
      const couleurs = outil === "surligneur" ? SURLIGNEURS : ENCRES;
      elements.push(h("div", { class: "nuancier", role: "group", "aria-label": "Couleur" }, couleurs.map((c) =>
        h("button", { type: "button", class: "pastille-couleur", "aria-pressed": String(c === r.couleur), "aria-label": `Couleur ${c}`,
          "data-couleur": c, surclick: () => { r.couleur = c; changerReglages(); } }, h("i", { "data-c": c })))));
    }
    if (LARGEURS[outil]) {
      elements.push(h("div", { class: "epaisseurs", role: "group", "aria-label": outil === "texte" ? "Taille du texte" : "Épaisseur" },
        LARGEURS[outil].map((l, i) => h("button", { type: "button", class: "epaisseur", "aria-pressed": String(l === r.largeur),
          "aria-label": ["Fin", "Moyen", "Épais"][i], surclick: () => { r.largeur = l; changerReglages(); } }, h("i", { "data-i": String(i) })))));
    }
    if (outil === "gomme") {
      elements.push(h("button", { type: "button", class: "bascule-mode", "aria-pressed": String(!!r.precise),
        title: "Gomme précise : n'efface que ce qu'elle touche, au lieu du trait entier",
        surclick: () => { r.precise = !r.precise; changerReglages(); } }, "Précise"));
    }
    if (outil === "stylo") {
      elements.push(h("button", { type: "button", class: "bascule-mode", "aria-pressed": String(reglages.formes),
        title: "Garde le stylet immobile une demi-seconde au bout d'un trait : ligne, rectangle, ellipse ou triangle parfaits",
        surclick: () => { reglages.formes = !reglages.formes; changerReglages(); } }, "Formes"));
    }
    elements.push(h("button", { type: "button", class: "icone-seule bascule-doigt", "aria-pressed": String(reglages.doigt),
      "aria-label": "Écrire au doigt", title: reglages.doigt ? "Le doigt écrit (deux doigts font défiler)" : "Le doigt fait défiler ; le stylet écrit",
      surclick: () => { reglages.doigt = !reglages.doigt; changerReglages(); } }, icone("doigt")));
    remplacer(reglageOutil, elements);
    for (const i of reglageOutil.querySelectorAll(".pastille-couleur i")) i.style.background = i.dataset.c;
    for (const i of reglageOutil.querySelectorAll(".epaisseur i")) i.style.height = `${[2, 4, 7][Number(i.dataset.i)]}px`;
    feuilles.dataset.outil = outil;
  }

  function choisirOutil(o) {
    if (o !== "lasso") abandonnerSelection();
    outil = o;
    reglages.outil = o === "ecouter" ? reglages.outil : o;
    changerReglages();
  }

  let minuteurPrefs = 0;
  function changerReglages() {
    dessinerOutils();
    clearTimeout(minuteurPrefs);
    minuteurPrefs = setTimeout(() => { minuteurPrefs = 0; enregistrerPrefs({ ...reglages }); }, 800);
  }

  // --- Mise en page des feuilles ----------------------------------------------------------------
  const positions = [];                            // haut de chaque page (px), dans l'ordre
  function largeurDispo() { return Math.max(200, feuilles.clientWidth - 2 * MARGE); }

  function ajusterZoom() {
    const plusLarge = Math.max(...carnet.carnet.pages.map((p) => p.w), 595);
    zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, largeurDispo() / plusLarge));
    if (zoom > 1.6) zoom = 1.6;                    // grand écran : pas de page géante
  }

  function miseEnPage() {
    let y = MARGE;
    positions.length = 0;
    let largeurMax = 0;
    for (const p of carnet.carnet.pages) {
      positions.push(y);
      y += p.h * zoom + ESPACE;
      largeurMax = Math.max(largeurMax, p.w * zoom);
    }
    const largeur = Math.max(feuilles.clientWidth, largeurMax + 2 * MARGE);
    pile.style.width = `${largeur}px`;
    pile.style.height = `${y - ESPACE + MARGE}px`;
    for (const [pid, v] of vues) {
      const i = carnet.index(pid);
      if (i < 0) { liberer(pid); continue; }
      placer(v, i, largeur);
    }
    pile.dataset.largeur = String(largeur);
  }

  function placer(v, i, largeur = Number(pile.dataset.largeur)) {
    const p = carnet.carnet.pages[i];
    v.div.style.top = `${positions[i]}px`;
    v.div.style.left = `${Math.max(MARGE, (largeur - p.w * zoom) / 2)}px`;
    v.div.style.width = `${p.w * zoom}px`;
    v.div.style.height = `${p.h * zoom}px`;
  }

  // Pages proches de l'écran : elles ont leurs calques ; les autres sont libérées (mémoire).
  function rafraichirVisibles() {
    const haut = feuilles.scrollTop - feuilles.clientHeight, bas = feuilles.scrollTop + 2 * feuilles.clientHeight;
    const voulues = new Set();
    carnet.carnet.pages.forEach((p, i) => {
      const y0 = positions[i], y1 = y0 + p.h * zoom;
      if (y1 >= haut && y0 <= bas) voulues.add(p.id);
    });
    for (const pid of [...vues.keys()]) if (!voulues.has(pid) && !(action && action.pid === pid)) liberer(pid);
    for (const pid of voulues) if (!vues.has(pid)) creerVue(pid);
    mettreNumero();
  }

  function creerVue(pid) {
    const i = carnet.index(pid);
    const p = carnet.carnet.pages[i];
    const fond = h("canvas", { class: "calque fond", "aria-hidden": "true" });
    const encre = h("canvas", { class: "calque encre", "aria-hidden": "true" });
    const vif = h("canvas", { class: "calque vif", "aria-hidden": "true" });
    const div = h("div", { class: "feuille", "data-page": pid, role: "group", "aria-label": `Page ${i + 1}` }, fond, encre, vif,
      p.signet ? h("span", { class: "marque-signet", "aria-hidden": "true" }, icone("signet")) : null);
    const v = { pid, div, fond, encre, vif, echelle: 0, fondEchelle: 0, rendu: null };
    vues.set(pid, v);
    placer(v, i);
    pile.append(div);
    peindreVue(v);
    // data-prete : le contenu de la page est arrivé, on peut y écrire
    carnet.contenu(pid).then(() => { if (vues.get(pid) === v) { div.dataset.prete = "1"; peindreEncre(v); } }).catch((e) => annoncer(e.message, { erreur: true }));
  }

  function liberer(pid) {
    const v = vues.get(pid);
    if (!v) return;
    v.rendu?.cancel?.();
    for (const c of [v.fond, v.encre, v.vif]) { c.width = 0; c.height = 0; }
    v.div.remove();
    vues.delete(pid);
  }

  function echelleCalque(p) {
    const voulue = zoom * dpr();
    return Math.min(voulue, Math.sqrt(PIXELS_MAXI / (p.w * p.h)));
  }

  function dimensionner(c, p, s) {
    const w = Math.max(1, Math.round(p.w * s)), hh = Math.max(1, Math.round(p.h * s));
    if (c.width !== w || c.height !== hh) { c.width = w; c.height = hh; }
  }

  function peindreVue(v) {
    const p = carnet.page(v.pid);
    if (!p) return;
    const s = echelleCalque(p);
    if (v.echelle !== s) {
      v.echelle = s;
      dimensionner(v.encre, p, s);
      dimensionner(v.vif, p, s);
      peindreEncre(v);
    }
    if (v.fondEchelle !== s) {
      v.fondEchelle = s;
      peindreFond(v, p, s);
    }
  }

  function peindreFond(v, p, s) {
    if (p.fond) {
      v.rendu?.cancel?.();
      const ctx = v.fond.getContext("2d");
      if (v.fond.width === 0 || !v.fondPeint) {                // en attendant le PDF : papier blanc
        dimensionner(v.fond, p, s);
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, v.fond.width, v.fond.height);
      }
      v.rendu = pdf.peindre(carnet, p.fond.pdf, p.fond.page, s, (image) => {
        if (vues.get(v.pid) !== v) return;
        dimensionner(v.fond, p, s);
        v.fond.getContext("2d").drawImage(image, 0, 0, v.fond.width, v.fond.height);
        v.fondPeint = true;
      });
      return;
    }
    dimensionner(v.fond, p, s);
    const ctx = v.fond.getContext("2d");
    ctx.setTransform(s, 0, 0, s, 0, 0);
    peindrePapier(ctx, p);
  }

  // Encre d'une page : images, surligneur, encre et formes, textes ; toujours tout le calque
  function peindreEncre(v, sauf = null) {
    const p = carnet.page(v.pid);
    const c = carnet.charge(v.pid);
    if (!p) return;
    const ctx = v.encre.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, v.encre.width, v.encre.height);
    if (!c) return;
    ctx.setTransform(v.echelle, 0, 0, v.echelle, 0, 0);
    for (const im of c.images) {
      if (sauf && sauf.has(im.id)) continue;
      const bitmap = images.get(im.fichier);
      if (bitmap && bitmap !== "attente") ctx.drawImage(bitmap, im.x, im.y, im.w, im.h);
      else chargerImage(im.fichier);
    }
    for (const passe of ["surligneur", "stylo"]) {
      for (const t of c.traits) {
        if (t.outil !== passe || (sauf && sauf.has(t.id))) continue;
        peindreTrait(ctx, t);
      }
    }
    for (const t of c.textes) if (!(sauf && sauf.has(t.id)) && !(editionTexte && editionTexte.item.id === t.id)) peindreTexte(ctx, t);
  }

  function peindreTrait(ctx, t, couleur = null, alpha = 1) {
    const chemin = chemin2D(t);
    if (rempli(t)) {
      ctx.globalAlpha = alpha;
      ctx.fillStyle = couleur || t.couleur;
      ctx.fill(chemin);
    } else {
      ctx.globalAlpha = (t.outil === "surligneur" ? 0.38 : 1) * alpha;
      ctx.strokeStyle = couleur || t.couleur;
      ctx.lineWidth = t.largeur;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.stroke(chemin);
    }
    ctx.globalAlpha = 1;
  }

  const POLICE = '"Adwaita Sans", "Inter", "Cantarell", sans-serif';
  function peindreTexte(ctx, t) {
    ctx.fillStyle = t.couleur;
    ctx.font = `${t.taille}px ${POLICE}`;
    ctx.textBaseline = "top";
    t.texte.split("\n").forEach((ligne, i) => ctx.fillText(ligne, t.x, t.y + i * t.taille * 1.3));
  }

  const images = new Map();
  function chargerImage(fichier) {
    if (images.has(fichier)) return;
    images.set(fichier, "attente");
    carnet.url(fichier).then((url) => {
      const img = new Image();
      img.src = url;
      return img.decode().then(() => {
        images.set(fichier, img);
        for (const v of vues.values()) if (carnet.charge(v.pid)?.images.some((i) => i.fichier === fichier)) peindreEncre(v);
      });
    }).catch(() => images.delete(fichier));
  }

  function repeindre(pid) {
    const v = vues.get(pid);
    if (v) peindreEncre(v);
  }

  // Après un zoom : nouvelles tailles tout de suite (les calques s'étirent), dessin net un peu après
  let minuteurNettete = 0;
  function apresZoom() {
    miseEnPage();
    rafraichirVisibles();
    clearTimeout(minuteurNettete);
    minuteurNettete = setTimeout(() => { for (const v of vues.values()) peindreVue(v); }, 140);
  }

  function mettreNumero() {
    const milieu = feuilles.scrollTop + feuilles.clientHeight / 2;
    let i = 0;
    while (i < positions.length - 1 && positions[i + 1] <= milieu) i++;
    pageCourante = i;
    numero.textContent = `${i + 1} / ${carnet.carnet.pages.length}`;
  }
  let pageCourante = 0;

  // --- Coordonnées ------------------------------------------------------------------------------
  function vueSous(clientX, clientY) {
    for (const v of vues.values()) {
      const r = v.div.getBoundingClientRect();
      if (clientX >= r.left && clientX <= r.right && clientY >= r.top && clientY <= r.bottom) return v;
    }
    return null;
  }

  function pointPage(v, e) {
    const r = v.div.getBoundingClientRect();
    return [(e.clientX - r.left) / zoom, (e.clientY - r.top) / zoom];
  }

  function pression(e) {
    if (e.pointerType === "pen") return e.pressure > 0 ? e.pressure : 0.5;
    return 0.5;
  }

  // Zoomer en gardant sous le doigt (ou la souris) le même endroit de la page
  function zoomerAutour(nouveau, clientX, clientY) {
    nouveau = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, nouveau));
    if (Math.abs(nouveau - zoom) < 1e-4) return;
    const r = feuilles.getBoundingClientRect();
    const v = vueSous(clientX, clientY) || [...vues.values()][0];
    let ancre = null;
    if (v) {
      const [x, y] = pointPage(v, { clientX, clientY });
      ancre = { pid: v.pid, x, y };
    }
    zoom = nouveau;
    ajuste = false;
    miseEnPage();
    if (ancre) {
      const i = carnet.index(ancre.pid);
      const p = carnet.carnet.pages[i];
      const gauche = Math.max(MARGE, (Number(pile.dataset.largeur) - p.w * zoom) / 2);
      feuilles.scrollLeft = gauche + ancre.x * zoom - (clientX - r.left);
      feuilles.scrollTop = positions[i] + ancre.y * zoom - (clientY - r.top);
    }
    apresZoom();
  }

  // --- Annuler / rétablir -----------------------------------------------------------------------
  // Une action = sur une page, des éléments retirés (avant) et ajoutés (après).
  function faire(pid, avant, apres, { enregistrer = true } = {}) {
    if (!avant.length && !apres.length) return;
    appliquer(pid, avant, apres);
    pileAnnuler.push({ pid, avant, apres });
    if (pileAnnuler.length > 300) pileAnnuler.shift();
    pileRefaire.length = 0;
    majAnnuler();
    if (enregistrer) carnet.modifier(pid);
  }

  function appliquer(pid, retires, ajoutes) {
    const c = carnet.charge(pid);
    if (!c) return;
    for (const genre of ["traits", "textes", "images"]) {
      const ids = new Set(retires.filter((x) => x.genre === genre).map((x) => x.item.id));
      if (ids.size) c[genre] = c[genre].filter((i) => !ids.has(i.id));
      for (const x of ajoutes) if (x.genre === genre) c[genre].push(x.item);
    }
    repeindre(pid);
  }

  async function annuler() {
    const a = pileAnnuler.pop();
    if (!a) return;
    abandonnerSelection();
    await carnet.contenu(a.pid);
    appliquer(a.pid, a.apres, a.avant);
    pileRefaire.push(a);
    carnet.modifier(a.pid);
    majAnnuler();
    allerA(a.pid, true);
  }

  async function refaire() {
    const a = pileRefaire.pop();
    if (!a) return;
    abandonnerSelection();
    await carnet.contenu(a.pid);
    appliquer(a.pid, a.avant, a.apres);
    pileAnnuler.push(a);
    carnet.modifier(a.pid);
    majAnnuler();
    allerA(a.pid, true);
  }

  function majAnnuler() {
    boutonAnnuler.disabled = !pileAnnuler.length;
    boutonRefaire.disabled = !pileRefaire.length;
  }

  // Amène une page à l'écran (si elle n'y est pas déjà, ou toujours avec seulementSiCachee = false)
  function allerA(pid, seulementSiCachee = false) {
    const i = carnet.index(pid);
    if (i < 0) return;
    const y0 = positions[i], y1 = y0 + carnet.carnet.pages[i].h * zoom;
    if (seulementSiCachee && y1 > feuilles.scrollTop && y0 < feuilles.scrollTop + feuilles.clientHeight) return;
    feuilles.scrollTop = y0 - MARGE;
    rafraichirVisibles();
  }

  // --- Entrées : stylet, souris, doigts -----------------------------------------------------------
  feuilles.addEventListener("pointerdown", appui);
  feuilles.addEventListener("pointermove", mouvement);
  feuilles.addEventListener("pointerup", relache);
  feuilles.addEventListener("pointercancel", (e) => relache(e, true));
  feuilles.addEventListener("pointerleave", (e) => { if (e.pointerType === "pen" && !action) masquerGomme(); });
  feuilles.addEventListener("contextmenu", (e) => e.preventDefault());
  feuilles.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;                        // pincement au pavé tactile, ou Ctrl + molette
    e.preventDefault();
    zoomerAutour(zoom * Math.exp(-e.deltaY * 0.01), e.clientX, e.clientY);
  }, { passive: false });
  let attenteDefilement = 0;
  feuilles.addEventListener("scroll", () => {
    cancelAnimationFrame(attenteDefilement);
    attenteDefilement = requestAnimationFrame(rafraichirVisibles);
  });

  function appui(e) {
    if (e.target.closest(".boite-selection, .zone-texte, .menu-selection")) return;
    // un texte en cours d'écriture se termine dès qu'on touche ailleurs (le geste ne déplace pas le focus)
    if (editionTexte) editionTexte.zone.blur();
    cancelAnimationFrame(elan);
    if (e.pointerType === "pen") dernierStylet = performance.now();
    if (e.pointerType === "touch") {
      doigts.set(e.pointerId, { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t0: performance.now() });
      const paume = performance.now() - dernierStylet < 700 || (action && action.type === "pen");
      if (paume) return;                           // une main posée pendant que le stylet écrit
      if (doigts.size >= 2 || !reglages.doigt) {
        if (action && action.type === "touch") annulerAction();
        demarrerGeste();
        return;
      }
    }
    if (e.pointerType === "mouse" && e.button === 1) { demarrerGeste(e); return; }
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (action) return;
    const v = vueSous(e.clientX, e.clientY);
    if (!v || !carnet.charge(v.pid)) return;
    feuilles.setPointerCapture(e.pointerId);
    e.preventDefault();
    commencer(v, e);
  }

  function mouvement(e) {
    if (e.pointerType === "pen") {
      dernierStylet = performance.now();
      if (!action && outil === "gomme") survolGomme(e);
    }
    if (e.pointerType === "touch" && doigts.has(e.pointerId)) {
      const d = doigts.get(e.pointerId);
      d.x = e.clientX; d.y = e.clientY;
      if (geste) { bougerGeste(); return; }
    }
    if (geste && geste.souris && e.pointerType === "mouse") { bougerGeste(e); return; }
    if (!action || action.id !== e.pointerId) return;
    const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of evs.length ? evs : [e]) continuer(ev);
    action.prevus = e.getPredictedEvents ? e.getPredictedEvents() : [];
    demanderRendu();
  }

  function relache(e, annule = false) {
    if (e.pointerType === "touch") {
      const d = doigts.get(e.pointerId);
      doigts.delete(e.pointerId);
      if (geste && !geste.souris) {
        if (d) geste.tapes.push({ bouge: Math.hypot(d.x - d.x0, d.y - d.y0), duree: performance.now() - d.t0 });
        if (!doigts.size) finirGeste();
        else demarrerGeste(null, geste);
        return;
      }
    }
    if (geste && geste.souris && e.pointerType === "mouse") { finirGeste(); return; }
    if (!action || action.id !== e.pointerId) return;
    if (annule) annulerAction(); else terminer(e);
  }

  // Gestes aux doigts : défiler (avec élan), pincer pour zoomer, toucher à 2 / 3 doigts
  function demarrerGeste(souris = null, precedent = null) {
    const pts = souris ? [{ x: souris.clientX, y: souris.clientY }] : [...doigts.values()];
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length, cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
    const ecart = pts.length >= 2 ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) : 0;
    geste = { cx, cy, ecart, zoom0: zoom, n: pts.length, max: Math.max(precedent?.max || 0, pts.length), debut: precedent?.debut ?? performance.now(),
      tapes: precedent?.tapes || [], souris: !!souris, vitesse: [0, 0], t: performance.now() };
  }

  function bougerGeste(souris = null) {
    const pts = souris ? [{ x: souris.clientX, y: souris.clientY }] : [...doigts.values()];
    if (!pts.length) return;
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length, cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
    const maintenant = performance.now();
    if (pts.length >= 2 && geste.ecart > 20) {
      const ecart = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const voulu = geste.zoom0 * (ecart / geste.ecart);
      if (Math.abs(voulu - zoom) / zoom > 0.01) zoomerAutour(voulu, cx, cy);
    }
    const dx = cx - geste.cx, dy = cy - geste.cy;
    feuilles.scrollLeft -= dx;
    feuilles.scrollTop -= dy;
    const dt = Math.max(1, maintenant - geste.t);
    geste.vitesse = [0.8 * (dx / dt) + 0.2 * geste.vitesse[0], 0.8 * (dy / dt) + 0.2 * geste.vitesse[1]];
    geste.cx = cx; geste.cy = cy; geste.t = maintenant;
  }

  function finirGeste() {
    const g = geste;
    geste = null;
    if (!g) return;
    const duree = performance.now() - g.debut;
    const tape = !g.souris && duree < 320 && g.tapes.length >= 2 && g.tapes.every((t) => t.bouge < 14);
    if (tape && g.max === 2) { annuler(); return; }
    if (tape && g.max === 3) { refaire(); return; }
    // élan : le défilement continue et ralentit
    let [vx, vy] = g.vitesse;
    if (g.souris || Math.hypot(vx, vy) < 0.15) return;
    let t = performance.now();
    const pas = () => {
      const n = performance.now(), dt = n - t;
      t = n;
      feuilles.scrollLeft -= vx * dt;
      feuilles.scrollTop -= vy * dt;
      const f = Math.pow(0.994, dt);
      vx *= f; vy *= f;
      if (Math.hypot(vx, vy) > 0.02) elan = requestAnimationFrame(pas);
    };
    elan = requestAnimationFrame(pas);
  }

  // --- Les outils ----------------------------------------------------------------------------------
  function commencer(v, e) {
    const [x, y] = pointPage(v, e);
    const gommeStylet = e.pointerType === "pen" && (e.button === 5 || (e.buttons & 32));
    const o = gommeStylet ? "gomme" : outil;
    action = { id: e.pointerId, type: e.pointerType, pid: v.pid, v, outil: o, x0: x, y0: y, dernier: [x, y], prevus: [],
      retires: [], ajoutes: [], t0: performance.now() };
    if (o === "stylo" || o === "surligneur") {
      const r = reglages[o];
      action.trait = { id: nouvelId("t"), outil: o, couleur: r.couleur, largeur: r.largeur, points: [arr(x), arr(y), arr(pression(e))] };
      if (enregistreur.actif) { action.trait.son = enregistreur.id; action.trait.ts = Math.round(enregistreur.temps()); }
      armerForme();
    } else if (o === "gomme") {
      gommerEn(x, y);
    } else if (o === "lasso") {
      if (selection && selection.pid === v.pid && dansBoite(selection.boite, x, y, 6 / zoom)) {
        const poignee = Math.hypot(x - (selection.boite.x + selection.boite.w), y - (selection.boite.y + selection.boite.h)) < 18 / zoom;
        action.deplacer = { poignee, boite: { ...selection.boite } };
        cacherMenuSelection();
      } else {
        abandonnerSelection();
        action.lasso = [x, y];
      }
    } else if (o === "texte") {
      action.tape = true;
    } else if (o === "laser") {
      action.laser = [[x, y, performance.now()]];
    } else if (o === "ecouter") {
      action.tape = true;
    }
    demanderRendu();
  }

  const arr = (v) => Math.round(v * 100) / 100;

  function continuer(e) {
    const a = action;
    const [x, y] = pointPage(a.v, e);
    if (a.trait) {
      if (a.forme) return;
      const p = a.trait.points;
      const [lx, ly] = [p[p.length - 3], p[p.length - 2]];
      // lissage léger (le trait suit la main sans trembler) et points trop proches ignorés
      const k = a.type === "pen" ? 0.62 : 0.5;
      const sx = lx + (x - lx) * k, sy = ly + (y - ly) * k;
      if (Math.hypot(sx - lx, sy - ly) < 0.35 / zoom) return;
      p.push(arr(sx), arr(sy), arr(pression(e)));
      if (Math.hypot(x - a.dernier[0], y - a.dernier[1]) > 2.5 / zoom) { a.dernier = [x, y]; armerForme(); }
      if (a.outil === "stylo" && reglages.gribouillis && p.length >= 36 && p.length / 3 - (a.verifie || 0) >= 4) {
        a.verifie = p.length / 3;
        a.gribouillis = gribouillis(p) ? cibles(carnet.charge(a.pid).traits.concat(carnet.charge(a.pid).textes, carnet.charge(a.pid).images), p) : null;
      }
    } else if (a.outil === "gomme") {
      gommerEn(x, y);
      a.dernier = [x, y];
    } else if (a.lasso) {
      a.lasso.push(arr(x), arr(y));
    } else if (a.deplacer) {
      a.dernier = [x, y];
    } else if (a.laser) {
      a.laser.push([x, y, performance.now()]);
    }
    if (a.tape && Math.hypot(x - a.x0, y - a.y0) > 6 / zoom) a.tape = false;
  }

  // Forme parfaite : le stylet reste immobile une demi-seconde au bout du trait
  function armerForme() {
    clearTimeout(action?.minuteurForme);
    if (!action?.trait || action.outil !== "stylo" || !reglages.formes) return;
    const a = action;
    a.minuteurForme = setTimeout(() => {
      if (action !== a || a.forme) return;
      const f = reconnaitre(a.trait.points);
      if (!f) return;
      a.forme = f;
      a.trait = { ...a.trait, points: f.points, forme: f.forme, ferme: f.ferme };
      a.gribouillis = null;
      demanderRendu();
    }, 520);
  }

  function terminer() {
    const a = action;
    action = null;
    clearTimeout(a.minuteurForme);
    const c = carnet.charge(a.pid);
    if (a.trait) {
      if (a.gribouillis && a.gribouillis.length && !a.forme) {
        const retires = a.gribouillis.map((item) => ({ genre: genreDe(item, c), item }));
        faire(a.pid, retires, []);
        estomper(a.v, a.gribouillis);
      } else {
        faire(a.pid, [], [{ genre: "traits", item: a.trait }]);
      }
    } else if (a.outil === "gomme") {
      if (a.retires.length || a.ajoutes.length) {
        const { retires, ajoutes } = bilanGomme(a, c);
        pileAnnuler.push({ pid: a.pid, avant: retires, apres: ajoutes });
        pileRefaire.length = 0;
        majAnnuler();
        carnet.modifier(a.pid);
      }
      masquerGomme();
    } else if (a.lasso) {
      choisirAuLasso(a);
    } else if (a.deplacer) {
      finirDeplacement(a);
    } else if (a.outil === "texte" && a.tape) {
      ouvrirTexte(a.v, a.x0, a.y0);
    } else if (a.outil === "ecouter" && a.tape) {
      ecouterA(a.pid, a.x0, a.y0);
    } else if (a.laser) {
      estomperLaser(a);
      return;
    }
    viderVif(a.v);
  }

  function annulerAction() {
    const a = action;
    action = null;
    if (!a) return;
    clearTimeout(a.minuteurForme);
    if (a.outil === "gomme" && (a.retires.length || a.ajoutes.length)) {   // on remet tout comme avant le geste
      const { retires, ajoutes } = bilanGomme(a, carnet.charge(a.pid));
      appliquer(a.pid, ajoutes, retires);
    }
    if (a.outil === "gomme") masquerGomme();
    viderVif(a.v);
    if (a.deplacer && selection) montrerSelection();
  }

  // Ce qu'un geste de gomme a changé en tout : un morceau coupé puis recoupé dans le même geste ne
  // compte pas ; restent ce qui existait avant (retiré) et les morceaux encore là à la fin (ajoutés).
  function bilanGomme(a, c) {
    const idsAjoutes = new Set(a.ajoutes.map((x) => x.item.id));
    return {
      retires: a.retires.filter((x) => !idsAjoutes.has(x.item.id)),
      ajoutes: a.ajoutes.filter((x) => c[x.genre].includes(x.item)),
    };
  }

  function genreDe(item, c) {
    if (c.traits.includes(item)) return "traits";
    if (c.textes.includes(item)) return "textes";
    return "images";
  }

  // Gomme : trait entier (tout ce qu'elle touche disparaît) ou précise (coupe les traits)
  function gommerEn(x, y) {
    const a = action;
    const c = carnet.charge(a.pid);
    const r = reglages.gomme.largeur / 2;
    let change = false;
    for (const t of [...c.traits]) {
      if (!touche(t, x, y, r)) continue;
      if (reglages.gomme.precise && !t.forme) {
        const morceaux = gommer(t, x, y, r, () => nouvelId("t"));
        if (!morceaux) continue;
        c.traits.splice(c.traits.indexOf(t), 1, ...morceaux);
        a.retires.push({ genre: "traits", item: t });
        for (const m of morceaux) a.ajoutes.push({ genre: "traits", item: m });
      } else {
        c.traits.splice(c.traits.indexOf(t), 1);
        a.retires.push({ genre: "traits", item: t });
      }
      change = true;
    }
    if (!reglages.gomme.precise) {
      for (const genre of ["textes", "images"]) {
        for (const it of [...c[genre]]) {
          if (!touche(it, x, y, r)) continue;
          c[genre].splice(c[genre].indexOf(it), 1);
          a.retires.push({ genre, item: it });
          change = true;
        }
      }
    }
    if (change) repeindre(a.pid);
    montrerGomme(a.v, x, y, r);
  }

  function survolGomme(e) {
    const v = vueSous(e.clientX, e.clientY);
    if (!v) { masquerGomme(); return; }
    const [x, y] = pointPage(v, e);
    montrerGomme(v, x, y, reglages.gomme.largeur / 2);
  }

  let gommeVue = null;
  function montrerGomme(v, x, y, r) {
    if (gommeVue && gommeVue !== v) viderVif(gommeVue);
    gommeVue = v;
    const ctx = v.vif.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, v.vif.width, v.vif.height);
    ctx.setTransform(v.echelle, 0, 0, v.echelle, 0, 0);
    ctx.lineWidth = 1 / zoom;
    ctx.strokeStyle = "rgba(120,120,130,0.9)";
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  function masquerGomme() { if (gommeVue) { viderVif(gommeVue); gommeVue = null; } }

  // --- Dessin de ce qui est en cours (calque vif) -------------------------------------------------
  function demanderRendu() {
    if (rendu) return;
    rendu = requestAnimationFrame(() => { rendu = 0; peindreVif(); });
  }

  function viderVif(v) {
    if (!v) return;
    const ctx = v.vif.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, v.vif.width, v.vif.height);
  }

  function peindreVif() {
    const a = action;
    if (!a) return;
    const v = a.v;
    const ctx = v.vif.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, v.vif.width, v.vif.height);
    ctx.setTransform(v.echelle, 0, 0, v.echelle, 0, 0);
    if (a.trait) {
      if (a.gribouillis && a.gribouillis.length) {
        for (const it of a.gribouillis) {
          if (it.points) peindreTrait(ctx, it, ROUGE);
          else { const b = bornes(it); ctx.fillStyle = "rgba(255,90,82,0.35)"; ctx.fillRect(b.x, b.y, b.w, b.h); }
        }
      }
      // le trait, plus les points que le stylet va probablement atteindre (moins de retard à l'œil)
      let t = a.trait;
      if (!a.forme && a.prevus?.length) {
        const extra = [];
        for (const ev of a.prevus.slice(0, 3)) { const [x, y] = pointPage(v, ev); extra.push(arr(x), arr(y), arr(pression(ev))); }
        t = { ...t, points: t.points.concat(extra) };
      }
      peindreTrait(ctx, { ...t }, null, a.gribouillis?.length ? 0.45 : 1);
    } else if (a.lasso) {
      ctx.lineWidth = 1.2 / zoom;
      ctx.setLineDash([5 / zoom, 4 / zoom]);
      ctx.strokeStyle = "rgba(120,120,135,0.95)";
      ctx.beginPath();
      ctx.moveTo(a.lasso[0], a.lasso[1]);
      for (let i = 2; i < a.lasso.length; i += 2) ctx.lineTo(a.lasso[i], a.lasso[i + 1]);
      ctx.stroke();
      ctx.setLineDash([]);
    } else if (a.deplacer) {
      const [dx, dy, s, ox, oy] = transformationEnCours(a);
      const items = selection.items.map((x) => transformer(x.item, dx, dy, s, ox, oy));
      for (const it of items) {
        if (it.points) peindreTrait(ctx, it);
        else if (it.texte !== undefined) peindreTexte(ctx, it);
        else { const b = images.get(it.fichier); if (b && b !== "attente") ctx.drawImage(b, it.x, it.y, it.w, it.h); }
      }
      const b = selection.boite;
      ctx.lineWidth = 1 / zoom;
      ctx.setLineDash([4 / zoom, 3 / zoom]);
      ctx.strokeStyle = "rgba(120,120,135,0.95)";
      ctx.strokeRect(ox + (b.x - ox) * s + dx, oy + (b.y - oy) * s + dy, b.w * s, b.h * s);
      ctx.setLineDash([]);
    } else if (a.laser) {
      peindreLaser(ctx, a.laser);
    }
  }

  function peindreLaser(ctx, pts) {
    const n = performance.now();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (let i = 1; i < pts.length; i++) {
      const age = n - pts[i][2];
      const alpha = Math.max(0, 1 - age / 900);
      if (!alpha) continue;
      ctx.strokeStyle = `rgba(255,90,82,${alpha})`;
      ctx.lineWidth = 3.2 / Math.sqrt(zoom);
      ctx.shadowColor = `rgba(255,90,82,${alpha})`;
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.moveTo(pts[i - 1][0], pts[i - 1][1]);
      ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
  }

  function estomperLaser(a) {
    const v = a.v;
    const pas = () => {
      if (action && action.v === v) return;
      const ctx = v.vif.getContext("2d");
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, v.vif.width, v.vif.height);
      ctx.setTransform(v.echelle, 0, 0, v.echelle, 0, 0);
      peindreLaser(ctx, a.laser);
      if (performance.now() - a.laser[a.laser.length - 1][2] < 950) requestAnimationFrame(pas);
      else viderVif(v);
    };
    requestAnimationFrame(pas);
  }

  // Ce qu'un gribouillis vient d'effacer s'estompe en rouge
  function estomper(v, items) {
    const debut = performance.now();
    const pas = () => {
      if (action && action.v === v) return;
      const t = (performance.now() - debut) / 320;
      const ctx = v.vif.getContext("2d");
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, v.vif.width, v.vif.height);
      if (t >= 1) return;
      ctx.setTransform(v.echelle, 0, 0, v.echelle, 0, 0);
      for (const it of items) if (it.points) peindreTrait(ctx, it, ROUGE, 1 - t);
      requestAnimationFrame(pas);
    };
    requestAnimationFrame(pas);
  }

  // --- Lasso et sélection -----------------------------------------------------------------------
  const boiteSelection = h("div", { class: "boite-selection", hidden: true }, h("span", { class: "poignee", "aria-hidden": "true" }));
  const menuSelection = h("div", { class: "menu-selection", hidden: true, role: "toolbar", "aria-label": "Sélection" });
  pile.append(boiteSelection, menuSelection);

  function dansBoite(b, x, y, m = 0) { return x >= b.x - m && x <= b.x + b.w + m && y >= b.y - m && y <= b.y + b.h + m; }

  function boiteDe(items) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const { item } of items) {
      const b = bornes(item);
      x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h);
    }
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  function choisirAuLasso(a) {
    const c = carnet.charge(a.pid);
    if (a.lasso.length < 6) { viderVif(a.v); return; }
    const items = [];
    for (const genre of ["traits", "textes", "images"]) for (const it of c[genre]) if (dansLasso(it, a.lasso)) items.push({ genre, item: it });
    viderVif(a.v);
    if (!items.length) return;
    selection = { pid: a.pid, items, boite: boiteDe(items) };
    montrerSelection();
  }

  function montrerSelection() {
    const v = vues.get(selection?.pid);
    if (!selection || !v) { cacherSelection(); return; }
    const b = selection.boite;
    const gauche = parseFloat(v.div.style.left), haut = parseFloat(v.div.style.top);
    Object.assign(boiteSelection.style, { left: `${gauche + b.x * zoom - 4}px`, top: `${haut + b.y * zoom - 4}px`, width: `${b.w * zoom + 8}px`, height: `${b.h * zoom + 8}px` });
    boiteSelection.hidden = false;
    remplacer(menuSelection,
      ...(selection.items.some((x) => x.item.points || x.item.texte !== undefined)
        ? ENCRES.map((c) => h("button", { type: "button", class: "pastille-couleur", "aria-label": `Recolorer en ${c}`, "data-c": c, surclick: () => recolorer(c) }, h("i")))
        : []),
      h("button", { type: "button", class: "icone-seule", "aria-label": "Copier", title: "Copier (Ctrl+C)", surclick: () => copier() }, icone("copier")),
      h("button", { type: "button", class: "icone-seule", "aria-label": "Dupliquer", title: "Dupliquer (Ctrl+D)", surclick: () => dupliquer() }, icone("plus")),
      h("button", { type: "button", class: "icone-seule", "aria-label": "Supprimer la sélection", title: "Supprimer (Suppr)", surclick: () => supprimerSelection() }, icone("poubelle")));
    for (const b2 of menuSelection.querySelectorAll(".pastille-couleur")) b2.firstChild.style.background = b2.dataset.c;
    Object.assign(menuSelection.style, { left: `${gauche + b.x * zoom}px`, top: `${Math.max(4, haut + b.y * zoom - 56)}px` });
    menuSelection.hidden = false;
  }

  function cacherMenuSelection() { menuSelection.hidden = true; boiteSelection.hidden = true; }
  function cacherSelection() { cacherMenuSelection(); }

  function abandonnerSelection() {
    selection = null;
    cacherSelection();
  }

  function transformationEnCours(a) {
    const b = a.deplacer.boite;
    const [x, y] = a.dernier;
    if (a.deplacer.poignee) {
      const s = Math.max(0.1, Math.min(10, Math.max((x - b.x) / Math.max(1, b.w), (y - b.y) / Math.max(1, b.h))));
      return [0, 0, s, b.x, b.y];
    }
    return [x - a.x0, y - a.y0, 1, 0, 0];
  }

  function finirDeplacement(a) {
    const [dx, dy, s, ox, oy] = transformationEnCours(a);
    viderVif(a.v);
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(s - 1) < 0.01) { montrerSelection(); return; }
    const nouveaux = selection.items.map((x) => ({ genre: x.genre, item: { ...transformer(x.item, dx, dy, s, ox, oy) } }));
    faire(selection.pid, selection.items, nouveaux);
    selection = { pid: selection.pid, items: nouveaux, boite: boiteDe(nouveaux) };
    montrerSelection();
  }

  function recolorer(couleur) {
    if (!selection) return;
    const nouveaux = selection.items.map((x) => ({ genre: x.genre,
      item: x.item.points && x.item.outil === "stylo" || x.item.texte !== undefined ? { ...x.item, couleur } : x.item }));
    const changes = nouveaux.filter((x, i) => x.item !== selection.items[i].item);
    faire(selection.pid, selection.items.filter((x, i) => nouveaux[i].item !== x.item), changes);
    selection = { ...selection, items: nouveaux };
  }

  function copier() {
    if (!selection) return;
    pressePapier = selection.items.map((x) => ({ genre: x.genre, item: structuredClone(x.item) }));
    annoncer("Copié. « Coller » est dans le menu (ou Ctrl+V).");
  }

  function coller(pid = carnet.carnet.pages[pageCourante]?.id, decalage = 12) {
    if (!pressePapier || !pid) return;
    const nouveaux = pressePapier.map((x) => ({ genre: x.genre, item: { ...transformer(x.item, decalage, decalage), id: nouvelId(x.genre[0]) } }));
    carnet.contenu(pid).then(() => {
      faire(pid, [], nouveaux);
      selection = { pid, items: nouveaux, boite: boiteDe(nouveaux) };
      outil = "lasso";
      dessinerOutils();
      montrerSelection();
    });
  }

  function dupliquer() {
    if (!selection) return;
    copier();
    coller(selection.pid);
  }

  function supprimerSelection() {
    if (!selection) return;
    faire(selection.pid, selection.items, []);
    abandonnerSelection();
  }

  // --- Texte --------------------------------------------------------------------------------------
  let editionTexte = null;
  function ouvrirTexte(v, x, y) {
    if (editionTexte) editionTexte.zone.blur();
    const c = carnet.charge(v.pid);
    const existant = c.textes.find((t) => dansBoite(bornes(t), x, y, 4));
    const r = reglages.texte;
    const item = existant || { id: nouvelId("x"), x: arr(x), y: arr(y - r.largeur * 0.65), w: 0, h: 0, taille: r.largeur, couleur: r.couleur, texte: "" };
    const zone = h("textarea", { class: "zone-texte", "aria-label": "Texte", spellcheck: "true", rows: "1" });
    zone.value = item.texte;
    Object.assign(zone.style, { left: `${item.x * zoom}px`, top: `${item.y * zoom}px`, fontSize: `${item.taille * zoom}px`, color: item.couleur });
    const ajuster = () => { zone.style.height = "auto"; zone.style.height = `${zone.scrollHeight}px`; zone.style.width = "auto"; zone.style.width = `${Math.max(120, zone.scrollWidth + 8)}px`; };
    zone.addEventListener("input", ajuster);
    editionTexte = { item, zone, pid: v.pid };
    if (existant) peindreEncre(v);
    v.div.append(zone);
    ajuster();
    zone.focus();
    const finir = () => {
      if (editionTexte?.zone !== zone) return;
      editionTexte = null;
      zone.remove();
      const texte = zone.value.replace(/\s+$/, "");
      const ctx = v.encre.getContext("2d");
      ctx.font = `${item.taille}px ${POLICE}`;
      const lignes = texte.split("\n");
      const nouveau = { ...item, texte, w: arr(Math.max(...lignes.map((l) => ctx.measureText(l).width), 4)), h: arr(lignes.length * item.taille * 1.3) };
      if (existant && !texte) faire(v.pid, [{ genre: "textes", item: existant }], []);
      else if (existant && texte !== existant.texte) faire(v.pid, [{ genre: "textes", item: existant }], [{ genre: "textes", item: nouveau }]);
      else if (!existant && texte) faire(v.pid, [], [{ genre: "textes", item: nouveau }]);
      else peindreEncre(v);
    };
    zone.addEventListener("blur", finir);
    zone.addEventListener("keydown", (e) => { if (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey))) { e.preventDefault(); zone.blur(); } });
  }

  // --- Images -----------------------------------------------------------------------------------
  async function insererImage(fichier) {
    const ext = { "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp" }[fichier.type];
    if (!ext) { annoncer("Choisis une image PNG, JPEG ou WebP.", { erreur: true }); return; }
    const pid = carnet.carnet.pages[pageCourante]?.id;
    if (!pid) return;
    try {
      const nom = await nomFichier(fichier, ext);
      await carnet.envoyerFichier(nom, fichier);
      const img = new Image();
      img.src = URL.createObjectURL(fichier);
      await img.decode();
      images.set(nom, img);
      const p = carnet.page(pid);
      const w = Math.min(p.w * 0.6, img.naturalWidth * 0.75);
      const hh = w * (img.naturalHeight / img.naturalWidth);
      await carnet.contenu(pid);
      const item = { id: nouvelId("i"), x: arr((p.w - w) / 2), y: arr(Math.max(30, (p.h - hh) / 3)), w: arr(w), h: arr(hh), fichier: nom };
      faire(pid, [], [{ genre: "images", item }]);
      selection = { pid, items: [{ genre: "images", item }], boite: boiteDe([{ genre: "images", item }]) };
      outil = "lasso";
      dessinerOutils();
      montrerSelection();
    } catch (e) { annoncer(e.message, { erreur: true }); }
  }

  // --- Pages : ajouter, supprimer, papier, signets ----------------------------------------------------
  function nouvellePage(apres = pageCourante, modele = null) {
    const ref = carnet.carnet.pages[apres] || carnet.carnet.pages[carnet.carnet.pages.length - 1];
    const papier = carnet.carnet.papier || { format: "a4", modele: "ligne", couleur: "blanc" };
    const f = FORMATS[papier.format] || FORMATS.a4;
    const page = { id: nouvelId("p"), w: ref && !ref.fond ? ref.w : f.w, h: ref && !ref.fond ? ref.h : f.h,
      modele: modele || (ref && !ref.fond ? ref.modele : papier.modele), couleur: ref && !ref.fond ? ref.couleur : papier.couleur, signet: false };
    carnet.carnet.pages.splice(apres + 1, 0, page);
    carnet.contenus.set(page.id, { traits: [], textes: [], images: [] });
    carnet.modifierCarnet();
    miseEnPage();
    allerA(page.id);
    dessinerPanneau();
    return page;
  }

  async function supprimerPage(i = pageCourante) {
    const p = carnet.carnet.pages[i];
    if (!p) return;
    if (carnet.carnet.pages.length === 1) { annoncer("Un carnet garde au moins une page.", { erreur: true }); return; }
    const c = await carnet.contenu(p.id);
    const vide = !c.traits.length && !c.textes.length && !c.images.length;
    if (!vide && !(await confirmer({ titre: `Supprimer la page ${i + 1} ?`, texte: "Ce qui est écrit dessus disparaît avec elle.", oui: "Supprimer la page", danger: true }))) return;
    liberer(p.id);
    carnet.carnet.pages.splice(i, 1);
    carnet.contenus.delete(p.id);
    carnet.sales.delete(p.id);
    // ses actions ne peuvent plus être annulées
    for (const pileX of [pileAnnuler, pileRefaire]) for (let k = pileX.length - 1; k >= 0; k--) if (pileX[k].pid === p.id) pileX.splice(k, 1);
    majAnnuler();
    if (selection?.pid === p.id) abandonnerSelection();
    carnet.modifierCarnet();
    miseEnPage();
    rafraichirVisibles();
    dessinerPanneau();
  }

  function changerPapier(modele, couleur) {
    const p = carnet.carnet.pages[pageCourante];
    if (!p || p.fond) return;
    if (modele) p.modele = modele;
    if (couleur) p.couleur = couleur;
    carnet.carnet.papier = { ...(carnet.carnet.papier || {}), modele: p.modele, couleur: p.couleur };
    carnet.modifierCarnet();
    const v = vues.get(p.id);
    if (v) { v.fondEchelle = 0; peindreVue(v); }
  }

  function basculerSignet(i = pageCourante) {
    const p = carnet.carnet.pages[i];
    if (!p) return;
    p.signet = !p.signet;
    carnet.modifierCarnet();
    const v = vues.get(p.id);
    if (v) { liberer(p.id); creerVue(p.id); }
    dessinerPanneau();
    annoncer(p.signet ? `Signet posé sur la page ${i + 1}.` : "Signet retiré.");
  }

  // --- Panneau des pages (miniatures) --------------------------------------------------------------
  let seulementSignets = false;
  function basculerPanneau() {
    panneau.hidden = !panneau.hidden;
    racine.classList.toggle("avec-panneau", !panneau.hidden);
    if (!panneau.hidden) dessinerPanneau();
    requestAnimationFrame(() => { if (ajuste) { ajusterZoom(); } apresZoom(); });
  }

  const observateur = new IntersectionObserver((entrees) => {
    for (const en of entrees) if (en.isIntersecting && !en.target.dataset.peinte) { en.target.dataset.peinte = "1"; peindreMiniature(en.target); }
  }, { root: panneau, rootMargin: "200px" });

  function dessinerPanneau() {
    if (panneau.hidden) return;
    observateur.disconnect();
    const liste = carnet.carnet.pages.map((p, i) => ({ p, i })).filter(({ p }) => !seulementSignets || p.signet);
    remplacer(panneau,
      h("div", { class: "tete-panneau" },
        h("button", { type: "button", class: "bascule-mode", "aria-pressed": String(seulementSignets), surclick: () => { seulementSignets = !seulementSignets; dessinerPanneau(); } }, "Signets"),
        h("button", { type: "button", class: "icone-seule", "aria-label": "Ajouter une page", title: "Ajouter une page après celle-ci", surclick: () => nouvellePage() }, icone("plus"))),
      h("ol", { class: "miniatures" }, liste.map(({ p, i }) => {
        const mini = h("canvas", { "data-page": p.id, "aria-hidden": "true" });
        const li = h("li", { "aria-current": i === pageCourante ? "page" : null },
          h("button", { type: "button", class: "miniature", "aria-label": `Aller à la page ${i + 1}${p.signet ? " (signet)" : ""}`, surclick: () => allerA(p.id) }, mini,
            h("span", { class: "num", texte: String(i + 1) }), p.signet ? h("span", { class: "marque-signet" }, icone("signet")) : null));
        observateur.observe(mini);
        return li;
      })),
      liste.length ? null : h("p", { class: "discret petit vide-panneau", texte: "Aucune page avec un signet. Pose-en un depuis le menu ⋯." }));
  }

  async function peindreMiniature(canvas) {
    const p = carnet.page(canvas.dataset.page);
    if (!p) return;
    const largeur = 132;
    const s = (largeur / p.w) * dpr();
    canvas.width = Math.round(p.w * s);
    canvas.height = Math.round(p.h * s);
    canvas.style.aspectRatio = `${p.w} / ${p.h}`;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(s, 0, 0, s, 0, 0);
    if (p.fond) {
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, p.w, p.h);
      pdf.peindre(carnet, p.fond.pdf, p.fond.page, s, (image) => {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        ctx.setTransform(s, 0, 0, s, 0, 0);
        dessinerContenu();
      });
    } else peindrePapier(ctx, p);
    const c = await carnet.contenu(p.id).catch(() => null);
    function dessinerContenu() {
      if (!c) return;
      for (const passe of ["surligneur", "stylo"]) for (const t of c.traits) if (t.outil === passe) peindreTrait(ctx, t);
      for (const t of c.textes) peindreTexte(ctx, t);
    }
    if (!p.fond) dessinerContenu();
  }

  // --- Menu « ⋯ » -------------------------------------------------------------------------------------
  const choixImage = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true });
  const choixPdf = h("input", { type: "file", accept: "application/pdf,.pdf", hidden: true });
  racine.append(choixImage, choixPdf);
  choixImage.addEventListener("change", () => { const f = choixImage.files[0]; choixImage.value = ""; if (f) insererImage(f); });
  choixPdf.addEventListener("change", () => { const f = choixPdf.files[0]; choixPdf.value = ""; if (f) insererPdf(f); });

  function menu(ancre) {
    const p = carnet.carnet.pages[pageCourante];
    const d = h("dialog", { class: "menu-notes", "aria-label": "Options du carnet" });
    const fermer = () => { d.close(); d.remove(); };   // retiré tout de suite : pas de menu fermé qui traîne
    const entree = (texte, faireX, { danger = false, inactif = false } = {}) => h("button", { type: "button", class: danger ? "entree braise" : "entree", disabled: inactif,
      surclick: () => { fermer(); faireX(); } }, texte);
    ajouter(d,
      h("div", { class: "groupe-menu" },
        entree("Ajouter une page après celle-ci", () => nouvellePage()),
        entree(p?.signet ? "Retirer le signet de cette page" : "Poser un signet sur cette page", () => basculerSignet()),
        entree("Supprimer cette page", () => supprimerPage(), { danger: true })),
      p && !p.fond ? h("div", { class: "groupe-menu" },
        h("p", { class: "titre-groupe", texte: "papier de cette page" }),
        h("div", { class: "choix-papier" }, Object.entries(MODELES).map(([k, nom]) => h("button", { type: "button", "aria-pressed": String(p.modele === k),
          surclick: () => { changerPapier(k, null); fermer(); } }, nom))),
        h("div", { class: "choix-papier" }, Object.entries(COULEURS).map(([k, c]) => h("button", { type: "button", "aria-pressed": String(p.couleur === k),
          surclick: () => { changerPapier(null, k); fermer(); } }, c.nom)))) : null,
      h("div", { class: "groupe-menu" },
        entree("Insérer une image", () => choixImage.click()),
        entree("Ajouter les pages d'un PDF", () => choixPdf.click()),
        pressePapier ? entree("Coller", () => coller()) : null,
        entree("Exporter en PDF (dans Notes/PDF)", () => exporter())));
    d.addEventListener("close", () => d.remove());
    d.addEventListener("click", (e) => { if (e.target === d) fermer(); });
    document.body.append(d);
    const r = ancre.getBoundingClientRect();
    d.show();
    Object.assign(d.style, { position: "fixed", top: `${r.bottom + 8}px`, right: `${Math.max(8, innerWidth - r.right)}px`, left: "auto", margin: "0" });
    d.querySelector("button")?.focus();
    const dehors = (e) => { if (!d.contains(e.target) && e.target !== ancre) { fermer(); document.removeEventListener("pointerdown", dehors, true); } };
    document.addEventListener("pointerdown", dehors, true);
    d.addEventListener("keydown", (e) => { if (e.key === "Escape") fermer(); });
  }

  // --- PDF : ajouter des pages, exporter ------------------------------------------------------------
  async function insererPdf(fichier) {
    try {
      annoncer("Lecture du PDF…");
      const pages = await pdf.importer(carnet, fichier);
      const apres = pageCourante;
      carnet.carnet.pages.splice(apres + 1, 0, ...pages);
      for (const p of pages) carnet.contenus.set(p.id, { traits: [], textes: [], images: [] });
      carnet.modifierCarnet();
      miseEnPage();
      allerA(pages[0].id);
      dessinerPanneau();
      annoncer(`${pages.length} page${pages.length > 1 ? "s" : ""} ajoutée${pages.length > 1 ? "s" : ""}.`);
    } catch (e) { annoncer(e.message || "Ce PDF n'a pas pu être lu.", { erreur: true }); }
  }

  async function exporter() {
    try {
      annoncer("Préparation du PDF…");
      await carnet.enregistrer();
      const octets = await pdf.exporter(carnet);
      const r = await api.envoyer(`/api/notes/export?nom=${encodeURIComponent(carnet.carnet.titre)}`, octets);
      annoncer(r.message || "PDF exporté.");
    } catch (e) { annoncer(e.message || "L'export a échoué.", { erreur: true }); }
  }

  // --- Son : enregistrer, écouter ----------------------------------------------------------------------
  async function basculerEnregistrement() {
    if (enregistreur.actif) {
      boutonMicro.classList.remove("enregistre");
      boutonMicro.setAttribute("aria-label", "Enregistrer le son");
      try {
        const son = await enregistreur.arreter();
        if (!son) return;
        const nom = `${son.id}.webm`;
        await carnet.envoyerFichier(nom, son.blob);
        carnet.carnet.sons = [...(carnet.carnet.sons || []), { id: son.id, fichier: nom, debut: son.debut, duree: son.duree }];
        carnet.modifierCarnet();
        dessinerOutils();
        annoncer("Enregistrement gardé. Avec « Écouter », touche ce que tu as écrit pour réentendre ce moment.");
      } catch (e) { annoncer(e.message, { erreur: true }); }
      return;
    }
    try {
      await enregistreur.demarrer(nouvelId("s"));
      boutonMicro.classList.add("enregistre");
      boutonMicro.setAttribute("aria-label", "Arrêter l'enregistrement");
      annoncer("Enregistrement en cours : ce que tu écris est relié au son.");
    } catch (e) { annoncer(e.message, { erreur: true }); }
  }

  async function ecouterA(pid, x, y) {
    const c = carnet.charge(pid);
    const t = c?.traits.slice().reverse().find((tr) => tr.son && touche(tr, x, y, 6 / zoom));
    if (!t) { annoncer("Rien d'enregistré à cet endroit.", { erreur: true }); return; }
    const son = carnet.carnet.sons.find((s) => s.id === t.son);
    if (!son) return;
    try {
      const url = await carnet.url(son.fichier);
      lire(url, Math.max(0, (t.ts || 0) / 1000 - 2), son);
    } catch (e) { annoncer(e.message, { erreur: true }); }
  }

  function lire(url, depuis, son) {
    if (!enLecture) {
      const audio = new Audio();
      const temps = h("span", { class: "temps" });
      const bouton2 = h("button", { type: "button", class: "icone-seule", "aria-label": "Pause", surclick: () => (audio.paused ? audio.play() : audio.pause()) }, icone("pause"));
      audio.addEventListener("play", () => { bouton2.replaceChildren(icone("pause")); bouton2.setAttribute("aria-label", "Pause"); });
      audio.addEventListener("pause", () => { bouton2.replaceChildren(icone("lecture")); bouton2.setAttribute("aria-label", "Lecture"); });
      audio.addEventListener("timeupdate", () => { temps.textContent = `${duree(audio.currentTime)} / ${duree(audio.duration || son.duree / 1000)}`; });
      barreLecture.replaceChildren(bouton2, temps, h("button", { type: "button", class: "icone-seule", "aria-label": "Fermer la lecture",
        surclick: () => { audio.pause(); barreLecture.hidden = true; enLecture = null; } }, icone("croix")));
      enLecture = { audio };
    }
    const { audio } = enLecture;
    barreLecture.hidden = false;
    if (audio.src !== url) audio.src = url;
    audio.currentTime = depuis;
    audio.play().catch(() => annoncer("Lecture impossible.", { erreur: true }));
  }
  const duree = (s) => (Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "–");

  // --- Clavier ------------------------------------------------------------------------------------------
  function clavier(e) {
    if (e.target.closest("input, textarea, dialog")) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) refaire(); else annuler(); return; }
    if (ctrl && e.key.toLowerCase() === "y") { e.preventDefault(); refaire(); return; }
    if (ctrl && e.key.toLowerCase() === "c" && selection) { e.preventDefault(); copier(); return; }
    if (ctrl && e.key.toLowerCase() === "v" && pressePapier) { e.preventDefault(); coller(); return; }
    if (ctrl && e.key.toLowerCase() === "d" && selection) { e.preventDefault(); dupliquer(); return; }
    if ((e.key === "Delete" || e.key === "Backspace") && selection) { e.preventDefault(); supprimerSelection(); return; }
    if (e.key === "Escape") { abandonnerSelection(); if (!panneau.hidden) basculerPanneau(); return; }
    if (ctrl && (e.key === "+" || e.key === "=")) { e.preventDefault(); zoomerAutour(zoom * 1.2, innerWidth / 2, innerHeight / 2); return; }
    if (ctrl && e.key === "-") { e.preventDefault(); zoomerAutour(zoom / 1.2, innerWidth / 2, innerHeight / 2); return; }
    if (ctrl && e.key === "0") { e.preventDefault(); ajuste = true; ajusterZoom(); apresZoom(); return; }
    if (ctrl || e.altKey) return;
    const raccourcis = { p: "stylo", h: "surligneur", e: "gomme", l: "lasso", t: "texte" };
    if (raccourcis[e.key]) { choisirOutil(raccourcis[e.key]); return; }
    if (e.key === "PageDown") { allerA(carnet.carnet.pages[Math.min(pageCourante + 1, carnet.carnet.pages.length - 1)].id); e.preventDefault(); }
    if (e.key === "PageUp") { allerA(carnet.carnet.pages[Math.max(pageCourante - 1, 0)].id); e.preventDefault(); }
  }
  document.addEventListener("keydown", clavier);

  // --- Vie de l'éditeur ---------------------------------------------------------------------------------
  const redim = new ResizeObserver(() => {
    if (ajuste) ajusterZoom();
    apresZoom();
    if (selection) montrerSelection();
  });
  redim.observe(feuilles);
  const cache = () => { if (document.visibilityState === "hidden") carnet.enregistrer(); };
  document.addEventListener("visibilitychange", cache);
  // page changée dans une autre fenêtre : relue, sans gêner un geste en cours sur elle
  const libre = (pid) => !(action && action.pid === pid) && !(editionTexte && editionTexte.pid === pid);
  const oublier = contexte.surChangement((quoi, d) => {
    if (!quoi?.startsWith(`notes:${carnet.carnet.id}:`)) return;
    const pid = quoi.split(":")[2];
    carnet.recharger(pid, d?.rev, () => libre(pid)).then((remplace) => {
      if (!remplace) return;
      if (selection?.pid === pid) abandonnerSelection();
      repeindre(pid);
    }).catch(() => {});
  });

  dessinerOutils();
  majAnnuler();
  montrerEtat("enregistre");
  ajusterZoom();
  miseEnPage();
  rafraichirVisibles();
  feuilles.focus({ preventScroll: true });

  return {
    carnet,
    async demonter() {
      redim.disconnect();
      observateur.disconnect();
      document.removeEventListener("keydown", clavier);
      document.removeEventListener("visibilitychange", cache);
      oublier();
      if (enregistreur.actif) await basculerEnregistrement();
      enLecture?.audio.pause();
      if (minuteurPrefs) { clearTimeout(minuteurPrefs); enregistrerPrefs({ ...reglages }); }   // réglage changé à l'instant
      await carnet.fermer();
      for (const pid of [...vues.keys()]) liberer(pid);
      pdf.oublier(carnet.carnet.id);
    },
    // pour les essais : état interne visible sans rien modifier
    _essais: { get zoom() { return zoom; }, get outil() { return outil; }, get selection() { return selection; }, pileAnnuler, vues },
  };
}
