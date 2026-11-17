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
};

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
