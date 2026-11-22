// Smoky — Mail : ce que partagent la liste, la lecture, l'écriture et les réglages (dates, tailles,
// adresses, liens dans un texte, actions lancées depuis un dialogue).
import { h } from "/js/ui.js";
import { api } from "/js/app.js";

const JOUR_COURT = new Intl.DateTimeFormat("fr-FR", { weekday: "short" });
const JOUR_MOIS = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const AVEC_ANNEE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });
const LONGUE = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const LONGUE_ANNEE = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

export const heure = (d) => `${d.getHours()} h ${String(d.getMinutes()).padStart(2, "0")}`;
const debutDuJour = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

// Date d'un mail dans la liste : « 14 h 02 » aujourd'hui, « hier », « lun. » cette semaine,
// « 12 nov. » cette année, « 12 nov. 2025 » avant.  ts : secondes (comme le serveur)
export function quandCourt(ts, maintenant = new Date()) {
  const d = new Date(ts * 1000);
  const ecart = Math.round((debutDuJour(maintenant) - debutDuJour(d)) / 86400000);
  if (ecart === 0) return heure(d);
  if (ecart === 1) return "hier";
  if (ecart > 1 && ecart < 7) return JOUR_COURT.format(d);
  return (d.getFullYear() === maintenant.getFullYear() ? JOUR_MOIS : AVEC_ANNEE).format(d);
}

// « jeudi 20 novembre à 14 h 02 » (l'année seulement si ce n'est pas celle en cours)
export function quandLong(ts, maintenant = new Date()) {
  const d = new Date(ts * 1000);
  return `${(d.getFullYear() === maintenant.getFullYear() ? LONGUE : LONGUE_ANNEE).format(d)} à ${heure(d)}`;
}

export function taille(octets) {
  if (octets < 1000) return `${octets} o`;
  if (octets < 1_000_000) return `${Math.round(octets / 1000)} ko`;
  return `${(octets / 1_000_000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo`;
}

// « Nom <a@b.fr>, "Durand, Paul" <c@d.fr> ; e@f.fr » → ["Nom <a@b.fr>", "\"Durand, Paul\" <c@d.fr>", "e@f.fr"]
export function decouper(liste) {
  const sortie = [];
  let morceau = "", guillemets = false;
  for (const c of String(liste || "")) {
    if (c === '"') guillemets = !guillemets;
    if ((c === "," || c === ";") && !guillemets) { if (morceau.trim()) sortie.push(morceau.trim()); morceau = ""; continue; }
    morceau += c;
  }
  if (morceau.trim()) sortie.push(morceau.trim());
  return sortie;
}

// « Paul Durand <p@d.fr> » → « p@d.fr » (en minuscules)
export function adresseDe(texte) {
  const m = /<([^<>]+)>\s*$/.exec(texte);
  return (m ? m[1] : texte).trim().toLowerCase();
}

export function formater(nom, adresse) {
  if (!nom || nom.toLowerCase() === adresse.toLowerCase()) return adresse;
  return /[",;<>@()]/.test(nom) ? `"${nom.replace(/["\\]/g, "")}" <${adresse}>` : `${nom} <${adresse}>`;
}

// « Re : » / « Tr : » une seule fois, quelle que soit la langue du mail d'origine
export function prefixe(genre, objet) {
  const deja = genre === "Re" ? /^\s*(re|aw|sv)\s*:/i : /^\s*(tr|fwd?|wg)\s*:/i;
  return deja.test(objet) ? objet : `${genre} : ${objet}`;
}

// Un texte de mail, avec ses liens cliquables (ouverts dans le navigateur) et ses adresses mail
// (qui préparent un mail dans Smoky). Les lignes citées (« > … ») sont estompées.
const LIEN = /\bhttps?:\/\/[^\s<>"']+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b/g;
export function texteAvecLiens(texte, { ecrireA } = {}) {
  const morceaux = [];
  for (const ligne of String(texte || "").split("\n")) {
    const cible = /^\s*>/.test(ligne) ? h("span", { class: "cite" }) : null;
    const dans = cible ? [] : morceaux;
    let reste = 0;
    for (const m of ligne.matchAll(LIEN)) {
      let lien = m[0];
      const fin = /[.,;:!?)\]»]+$/.exec(lien);              // ponctuation de la phrase, pas du lien
      if (fin && !(fin[0].startsWith(")") && lien.includes("("))) lien = lien.slice(0, -fin[0].length);
      if (m.index > reste) dans.push(ligne.slice(reste, m.index));
      if (lien.includes("@") && !/^https?:/i.test(lien)) {
        dans.push(ecrireA ? h("a", { href: "#", class: "adresse-mail", surclick: (e) => { e.preventDefault(); ecrireA(lien); } }, lien) : lien);
      } else {
        dans.push(h("a", { href: lien, target: "_blank", rel: "noopener noreferrer" }, lien));
      }
      reste = m.index + lien.length;
    }
    if (reste < ligne.length) dans.push(ligne.slice(reste));
    if (cible) { cible.append(...dans); morceaux.push(cible); }
    morceaux.push("\n");
  }
  morceaux.pop();
  return morceaux;
}

// Action lancée depuis un dialogue : l'erreur s'écrit dans le dialogue (une annonce serait
// cachée derrière son voile). → la réponse, ou null
export async function demander(corps, zoneErreur) {
  zoneErreur.textContent = "";
  try {
    return await api.envoyer("/api/mail", corps);
  } catch (err) {
    zoneErreur.textContent = err.message || "Cette action a échoué.";
    return null;
  }
}

// Après un nouveau dessin d'une zone, le clavier revient sur la même commande (repérée par
// data-cle, son nom accessible ou son texte) : rien ne saute sous les doigts.
export function garderFocus(zone, dessiner) {
  const cleDe = (x) => x.dataset.cle || x.getAttribute("aria-label") || x.textContent.trim();
  const actif = document.activeElement;
  const cle = actif && actif !== zone && zone.contains(actif) ? cleDe(actif) : null;
  dessiner();
  if (!cle) return;
  [...zone.querySelectorAll("a, button, input, select, textarea")].find((x) => cleDe(x) === cle)?.focus({ preventScroll: true });
}
