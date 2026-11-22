// Smoky — petites briques d'interface, sans bibliothèque.
//   h("div", {class: "x", surclick: f}, enfants…)   crée un élément
//   icone("notes")                                   dessin au trait (SVG)
//   interrupteur / segment / bouton / rangee         commandes des réglages
//   annoncer(texte) · confirmer({…})                 retours à l'utilisateur

const SVG = "http://www.w3.org/2000/svg";

export function h(balise, attributs, ...enfants) {
  const e = document.createElement(balise);
  for (const [nom, valeur] of Object.entries(attributs || {})) {
    if (valeur === false || valeur === null || valeur === undefined) continue;
    if (nom.startsWith("sur")) e.addEventListener(nom.slice(3), valeur);
    else if (nom === "class") e.className = valeur;
    else if (nom === "texte") e.textContent = valeur;
    else e.setAttribute(nom, valeur === true ? "" : valeur);
  }
  for (const enfant of enfants.flat(Infinity)) {
    if (enfant === null || enfant === undefined || enfant === false) continue;
    e.append(enfant instanceof Node ? enfant : document.createTextNode(String(enfant)));
  }
  return e;
}

// Dessins au trait (24 × 24, bouts ronds, comme les lettres des titres)
const TRACES = {
  smoky: "M5 16c0 2.2 2.4 3.5 5.2 3.5 3.3 0 5.6-1.6 5.6-4.1 0-5-9.2-2.6-9.2-7.4C6.6 5.700 8.800 4.500 11.600 4.500c2.300 0 4.300.900 5 2.500M17.500 9.500c2.200.400 2.900 2.600 1.300 3.900",
  aujourdhui: "M12 3.500v1.800M12 18.700v1.800M3.500 12h1.800M18.700 12h1.800M6 6l1.300 1.300M16.700 16.700 18 18M6 18l1.300-1.300M16.700 7.300 18 6M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  notes: "M4.500 19.500l1-4.200L16.200 4.600a1.900 1.900 0 0 1 2.700 0l.500.500a1.900 1.900 0 0 1 0 2.700L8.700 18.500l-4.200 1ZM14.500 6.300l3.200 3.200",
  agenda: "M5 6.500h14a1.500 1.500 0 0 1 1.500 1.500v10a1.500 1.500 0 0 1-1.500 1.500H5A1.500 1.500 0 0 1 3.500 18V8A1.500 1.500 0 0 1 5 6.500ZM3.500 10.500h17M8 4.500v3.500M16 4.500v3.500",
  mail: "M5 6h14a1.500 1.500 0 0 1 1.500 1.500v9A1.500 1.500 0 0 1 19 18H5a1.500 1.500 0 0 1-1.500-1.500v-9A1.500 1.500 0 0 1 5 6ZM4 7.500l8 6 8-6",
  maison: "M4 11.200 12 4.500l8 6.700M6 9.800V19h4.200v-5h3.600v5H18V9.800",
  systeme: "M5 7.500h9M18 7.500h1M5 16.500h1M10 16.500h9M16 5.500a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM8 14.500a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z",
  coche: "M5 12.500l4.500 4.500L19 7.500",
  croix: "M6.500 6.500l11 11M17.500 6.500l-11 11",
  dehors: "M9 6.500h8.500V15M17.500 6.500 7 17",
  gauche: "M14.500 6 8.500 12l6 6",
  droite: "M9.500 6l6 6-6 6",
  // Notes
  stylo: "M4.500 19.500l1-4.200L16.200 4.600a1.900 1.900 0 0 1 2.700 0l.500.500a1.900 1.900 0 0 1 0 2.700L8.700 18.500l-4.200 1ZM14.500 6.300l3.200 3.200",
  surligneur: "M5 19.500h6M8.300 16.700 6 14.400 14.600 5a1.800 1.800 0 0 1 2.600 0l2.400 2.400a1.800 1.800 0 0 1 0 2.600L10.200 18.600ZM11.300 7.900l4.800 4.800",
  gomme: "M8 19.500h11M4.800 14.300l8.600-8.600a2 2 0 0 1 2.800 0l3.100 3.100a2 2 0 0 1 0 2.800L13 18H8.500l-3.700-3.700ZM9.500 9.600l5.100 5.100",
  lasso: "M12 4.500c4.400 0 8 2.100 8 4.800s-3.600 4.800-8 4.800-8-2.100-8-4.800 3.600-4.800 8-4.800ZM7.300 13.300c-1.300 1.400-.900 3.600 1 4.200 1.600.500 2.600-.700 1.900-2.100",
  texte: "M5.500 7V5h13v2M12 5v14M9.500 19h5",
  laser: "M12 8.500a3.500 3.500 0 1 0 0 7 3.500 3.500 0 0 0 0-7ZM12 3.500v2.500M12 18v2.500M3.500 12H6M18 12h2.500",
  annuler: "M9 7.500 5 11.500l4 4M5.500 11.500h8.500a4.500 4.500 0 0 1 0 9H11",
  retablir: "M15 7.500l4 4-4 4M18.500 11.500H10a4.500 4.500 0 0 0 0 9h3",
  pages: "M5 4.500h5.500v6.500H5ZM13.500 4.500H19v6.500h-5.500ZM5 14h5.500v6.500H5ZM13.500 14H19v6.500h-5.500Z",
  plus: "M12 5v14M5 12h14",
  menu: "M6 12h.500M12 12h.500M18 12h.500",
  micro: "M12 4a2.500 2.500 0 0 0-2.500 2.500v5a2.500 2.500 0 0 0 5 0v-5A2.500 2.500 0 0 0 12 4ZM6.500 11.500a5.500 5.500 0 0 0 11 0M12 17v3.500",
  image: "M5 5h14v14H5ZM5 15.500l4-4 3.500 3.500 2.500-2.500 4 4M15 8.500h.010",
  signet: "M7 4.500h10v15l-5-3.500-5 3.500Z",
  ecouter: "M5 9.500h3l4-3.500v12l-4-3.500H5ZM15.500 9a4 4 0 0 1 0 6M17.500 6.500a7.500 7.500 0 0 1 0 11",
  doigt: "M9 11V5.500a1.500 1.500 0 0 1 3 0V10m0-1.500a1.500 1.500 0 0 1 3 0V11m0-1a1.500 1.500 0 0 1 3 0v4.500a5.500 5.500 0 0 1-5.500 5.500h-1A5.500 5.500 0 0 1 6 15l-1.500-3a1.500 1.500 0 0 1 2.600-1.500L9 13",
  poubelle: "M5 7h14M10 7V5h4v2M7 7l1 12.500h8L17 7",
  copier: "M8.500 8.500h10v11h-10ZM5.500 15.500v-11h10",
  pause: "M8.500 5.500v13M15.500 5.500v13",
  lecture: "M8 5.500v13l10-6.500Z",
  // Mail
  trombone: "M15.500 7.500 8.700 14.300a1.700 1.700 0 0 0 2.400 2.400l7-7a3.500 3.500 0 0 0-5-5l-7 7a5.300 5.300 0 0 0 7.500 7.500l6.200-6.200",
  repondre: "M10 7 5 11.500l5 4.500M5.500 11.500H13a6 6 0 0 1 6 6v1",
  transferer: "M14 7l5 4.500-5 4.500M18.500 11.500H11a6 6 0 0 0-6 6v1",
  archiver: "M4.500 5.500h15v4h-15ZM6 9.500V18.500h12V9.500M10 13h4",
  relever: "M18.800 9A7.500 7.500 0 0 0 5.400 9.200M5.200 15a7.500 7.500 0 0 0 13.400-.200M19 4.500V9h-4.500M5 19.500V15h4.500",
  ranger: "M4.500 7.500A1.500 1.500 0 0 1 6 6h3.800l2 2H18a1.500 1.500 0 0 1 1.500 1.500v7.500A1.500 1.500 0 0 1 18 18.500H6a1.500 1.500 0 0 1-1.500-1.500Z",
  loupe: "M10.500 5a5.500 5.500 0 1 0 0 11 5.500 5.500 0 0 0 0-11ZM14.500 14.500 19 19",
};

// replaceChildren / append écriraient « null » en toutes lettres : ceux-ci sautent les absents
export function remplacer(el, ...enfants) { el.replaceChildren(...enfants.flat().filter((x) => x != null && x !== false)); }
export function ajouter(el, ...enfants) { el.append(...enfants.flat().filter((x) => x != null && x !== false)); }

export function icone(nom) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.6");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const trait = document.createElementNS(SVG, "path");
  trait.setAttribute("d", TRACES[nom] || "");
  svg.append(trait);
  return svg;
}

export function bouton(texte, { genre = "", surClic, titre } = {}) {
  return h("button", { type: "button", class: `bouton ${genre}`.trim(), surclick: surClic, title: titre }, texte);
}

export function interrupteur({ coche, nom, surChange, inactif }) {
  const b = h("button", { type: "button", class: "interrupteur", role: "switch", "aria-checked": String(!!coche),
    "aria-label": nom, disabled: inactif });
  b.addEventListener("click", () => surChange(b.getAttribute("aria-checked") !== "true", b));
  return b;
}

// options : [[valeur, libellé], …] ; le choix est montré tout de suite (la page qui relit l'état
// réel du PC le corrige ensuite si la commande a échoué)
export function segment({ options, valeur, nom, surChange, inactif }) {
  const groupe = h("div", { class: "segment", role: "group", "aria-label": nom });
  for (const [v, libelle] of options) {
    const b = h("button", { type: "button", "aria-pressed": String(v === valeur), disabled: inactif,
      surclick: () => {
        if (v === valeur) return;
        valeur = v;
        for (const autre of groupe.children) autre.setAttribute("aria-pressed", String(autre === b));
        surChange(v, groupe);
      } }, libelle);
    groupe.append(b);
  }
  return groupe;
}

export function rangee(nom, aide, ...commandes) {
  return h("div", { class: "rangee" },
    h("div", { class: "texte" }, h("div", { class: "nom", texte: nom }), aide ? h("div", { class: "aide" }, aide) : null),
    h("div", { class: "commande" }, commandes));
}

export function annoncer(texte, { erreur = false, duree = 4200 } = {}) {
  if (!texte) return;
  const zone = document.getElementById("annonces");
  const a = h("div", { class: erreur ? "annonce erreur" : "annonce", texte });
  zone.replaceChildren(a);                       // une seule annonce à la fois : la dernière compte
  setTimeout(() => a.remove(), erreur ? duree * 1.8 : duree);
}

// Question avant une action qui ne se rattrape pas. → Promise<boolean>
export function confirmer({ titre, texte, oui, danger = false }) {
  return new Promise((resoudre) => {
    const d = h("dialog", {},
      h("h2", { texte: titre }),
      h("p", { texte }),
      h("div", { class: "boutons" },
        bouton("Annuler", { surClic: () => d.close("non") }),
        bouton(oui, { genre: danger ? "braise" : "plein", surClic: () => d.close("oui") })));
    d.addEventListener("close", () => { d.remove(); resoudre(d.returnValue === "oui"); });
    document.body.append(d);
    d.showModal();
  });
}

const JOURS = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const COURT = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
const AVEC_ANNEE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });

export function dateLongue(d = new Date()) { return JOURS.format(d); }

// "2026-11-14" → { texte: "sam. 14 nov.", retard: false } ; aujourd'hui / demain / hier en clair ;
// l'année n'est écrite que si ce n'est pas celle en cours ("20 mai 2031")
export function echeance(iso, maintenant = new Date()) {
  const [a, m, j] = iso.split("-").map(Number);
  const jour = new Date(a, m - 1, j);
  const debut = new Date(maintenant.getFullYear(), maintenant.getMonth(), maintenant.getDate());
  const ecart = Math.round((jour - debut) / 86400000);
  const texte = ecart === 0 ? "aujourd'hui" : ecart === 1 ? "demain" : ecart === -1 ? "hier"
    : (jour.getFullYear() === maintenant.getFullYear() ? COURT : AVEC_ANNEE).format(jour);
  return { texte, retard: ecart < 0 };
}

export function isoDuJour(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
