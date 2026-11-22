// Smoky — la coquille de l'appli : rail de navigation, pages, échanges avec le serveur local.
// Chaque page est un module chargé à la demande (js/aujourdhui.js, js/systeme.js…) qui exporte
//   monter(conteneur, contexte) → { demonter() }
import { h, icone, annoncer } from "/js/ui.js";

// --- Code d'accès : passé une fois dans l'adresse (#k=…), gardé pour cette fenêtre seulement ---
// Le lanceur peut aussi demander une page précise (#k=…&a=/systeme/maison).
const JETON = (() => {
  const dans = /[#&]k=([\w-]+)/.exec(location.hash);
  if (dans) {
    const aller = /[#&]a=(\/[a-z0-9/-]{1,60})/.exec(location.hash);
    sessionStorage.setItem("smoky-jeton", dans[1]);
    history.replaceState(null, "", location.pathname + "#" + (aller ? aller[1] : "/aujourdhui"));
  }
  return sessionStorage.getItem("smoky-jeton") || "";
})();

export class ErreurSmoky extends Error {}

// corps : objet (envoyé en JSON) ou Blob/ArrayBuffer (envoyé tel quel) ; brut : réponse en Blob
async function appeler(methode, chemin, corps, { brut = false, keepalive = false } = {}) {
  let reponse;
  const octets = corps instanceof Blob || corps instanceof ArrayBuffer || ArrayBuffer.isView(corps);
  try {
    reponse = await fetch(chemin, {
      method: methode, cache: "no-store", keepalive,
      headers: { "X-Smoky-Jeton": JETON, ...(corps && !octets ? { "Content-Type": "application/json" } : {}),
        ...(octets ? { "Content-Type": "application/octet-stream" } : {}) },
      body: corps ? (octets ? corps : JSON.stringify(corps)) : undefined,
    });
  } catch {
    throw new ErreurSmoky("Smoky ne répond plus. Ferme la fenêtre et rouvre l'appli.");
  }
  if (brut && reponse.ok) return reponse.blob();
  let donnees = {};
  try { donnees = await reponse.json(); } catch { /* réponse vide */ }
  if (reponse.status === 403) { ecranFerme(); throw new ErreurSmoky(donnees.erreur || "Accès refusé."); }
  if (reponse.status === 413) throw new ErreurSmoky(donnees.erreur || "Fichier trop gros.");
  if (!reponse.ok) throw new ErreurSmoky(donnees.erreur || "Cette action a échoué.");
  return donnees;
}

export const api = {
  lire: (chemin) => appeler("GET", chemin),
  envoyer: (chemin, corps = {}, options) => appeler("POST", chemin, corps, options),   // keepalive : part même si la page se ferme
  mettre: (chemin, corps, options) => appeler("PUT", chemin, corps, options),   // JSON ou octets
  octets: (chemin) => appeler("GET", chemin, undefined, { brut: true }),           // → Blob
  supprimer: (chemin) => appeler("DELETE", chemin),
};

// Lance une action et dit ce qui s'est passé ; → true si elle a réussi.
export async function tenter(action, { succes } = {}) {
  try {
    const r = await action();
    annoncer((r && r.message) || succes);
    return true;
  } catch (e) {
    annoncer(e instanceof ErreurSmoky ? e.message : "Erreur inattendue dans Smoky.", { erreur: true });
    if (!(e instanceof ErreurSmoky)) console.error(e);
    return false;
  }
}

// --- Pages -------------------------------------------------------------------------------------
// « ancienne » : pas encore refaite dans Smoky ; l'ancienne appli s'ouvre à part.
const PAGES = [
  { id: "aujourdhui", nom: "Aujourd'hui", module: "/js/aujourdhui.js" },
  { id: "notes", nom: "Notes", module: "/js/notes.js" },
  { id: "agenda", nom: "Agenda", module: "/js/agenda.js" },
  { id: "mail", nom: "Mail", module: "/js/mail.js" },
  { id: "maison", nom: "Maison", ancienne: true },
  { id: "systeme", nom: "Système", module: "/js/systeme.js" },
];

const rail = document.getElementById("rail");
const page = document.getElementById("page");
let montee = null;           // { id, demonter }
const ecouteurs = new Set(); // fonctions prévenues quand le serveur signale un changement

export async function ouvrirAncienne(id) {
  const p = PAGES.find((x) => x.id === id);
  await tenter(() => api.envoyer("/api/ouvrir", { quoi: id }), { succes: `${p.nom} s'ouvre dans sa fenêtre.` });
}

function dessinerRail() {
  rail.replaceChildren(h("div", { class: "marque", title: "Smoky" }, icone("smoky")));
  for (const p of PAGES) {
    const lien = h("a", { href: `#/${p.id}`, "data-page": p.id, class: p.ancienne ? "ancienne" : "",
      title: p.ancienne ? `${p.nom} : l'ancienne appli s'ouvre à part` : null }, icone(p.id), p.nom);
    if (p.ancienne) lien.addEventListener("click", (e) => { e.preventDefault(); ouvrirAncienne(p.id); });
    rail.append(lien);
  }
}

async function afficher() {
  const [, id = "aujourdhui", ...suite] = location.hash.split("/");
  const cible = PAGES.find((p) => p.id === id && p.module) || PAGES[0];
  for (const a of rail.querySelectorAll("a")) {
    if (a.dataset.page === cible.id) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  if (montee && montee.id === cible.id) { montee.aller?.(suite); return; }
  montee?.demonter?.();
  montee = null;
  page.replaceChildren();
  page.scrollTop = 0;
  try {
    const module = await import(cible.module);
    const vie = await module.monter(page, { suite, surChangement: (f) => { ecouteurs.add(f); return () => ecouteurs.delete(f); } });
    montee = { id: cible.id, ...vie };
    document.title = `${cible.nom} — Smoky`;
  } catch (e) {
    console.error(e);
    page.replaceChildren(h("div", { class: "ecran-plein" }, h("h2", { texte: "Cette page ne s'ouvre pas" }),
      h("p", { class: "secondaire", texte: "Ferme Smoky et rouvre-le. Si cela continue, lance smoky-diagnostic dans un terminal." })));
  }
}

// La fenêtre ne peut plus servir : le serveur a été relancé (autre code d'accès) ou s'est arrêté.
function ecranFerme(titre = "Smoky a été relancé", texte = "Cette fenêtre date d'avant : ferme-la et rouvre Smoky depuis son icône.") {
  if (document.body.dataset.ferme) return;
  document.body.dataset.ferme = "1";
  fermerFlux();
  montee?.demonter?.();
  montee = null;
  page.replaceChildren(h("div", { class: "ecran-plein" }, h("h2", { texte: titre }), h("p", { class: "secondaire", texte })));
}

// --- Événements du serveur : tant que cette connexion existe, le serveur sait que la fenêtre est là ---
let flux = null;
let rates = 0;               // essais de connexion ratés à la suite

function fermerFlux() { flux?.close(); flux = null; }

function ecouterServeur() {
  if (!JETON || flux || document.body.dataset.ferme) return;
  flux = new EventSource(`/api/flux?k=${encodeURIComponent(JETON)}`);
  flux.addEventListener("open", () => { rates = 0; });
  flux.addEventListener("change", (e) => {
    let d = {};
    try { d = JSON.parse(e.data) || {}; } catch { /* ignoré */ }
    for (const f of ecouteurs) f(typeof d.quoi === "string" ? d.quoi : "", d);   // d : le détail (rev d'une page des Notes…)
  });
  flux.addEventListener("arret", () => { fermerFlux(); serveurParti(); });
  // Le navigateur réessaie tout seul (sortie de veille…). S'il n'y arrive vraiment plus, on
  // arrête d'insister et on vérifie si le serveur est encore là.
  flux.addEventListener("error", () => { if (++rates >= 4) { fermerFlux(); serveurParti(); } });
}

async function serveurParti() {
  await new Promise((suite) => setTimeout(suite, 1200));       // un arrêt demandé prend un instant
  try {
    await appeler("GET", "/api/aujourdhui");                    // code refusé : « Smoky a été relancé »
    rates = 0;
    ecouterServeur();                                           // il répond : fausse alerte
  } catch {
    ecranFerme("Smoky s'est arrêté", "Ferme cette fenêtre et rouvre Smoky depuis son icône.");
  }
}

// Page mise de côté par le navigateur (puis reprise) : on libère la connexion, puis on la rouvre.
addEventListener("pagehide", fermerFlux);
addEventListener("pageshow", (e) => {
  if (!e.persisted) return;
  ecouterServeur();
  for (const f of ecouteurs) f("");                             // l'état a pu changer entre-temps
});

if (!JETON) {
  dessinerRail();
  page.replaceChildren(h("div", { class: "ecran-plein" }, h("h2", { texte: "Ouvre Smoky depuis son icône" }),
    h("p", { class: "secondaire", texte: "Cette adresse ne suffit pas : l'appli se lance depuis le dock ou la grille des applis." })));
} else {
  // le réglage « Animations » de Smoky OS coupe aussi celles de l'appli
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) document.body.classList.add("calme");
  dessinerRail();
  // un changement de page à la fois : la page qui part a fini de se monter (et de s'enregistrer)
  // avant que la suivante arrive ; chaque tour relit l'adresse du moment, les clics rapides se tassent
  let file = Promise.resolve();
  const suivre = () => { file = file.then(afficher, afficher); };
  addEventListener("hashchange", suivre);
  suivre();
  ecouterServeur();
}
