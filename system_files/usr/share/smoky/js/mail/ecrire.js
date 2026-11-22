// Smoky — Mail : écrire un mail (volet de droite). Un seul brouillon, enregistré tout seul pendant
// la frappe (une fenêtre fermée ne le perd pas). Les pièces jointes attendent l'envoi en mémoire
// vive, sur le PC ; 25 Mo en tout au plus.
import { h, icone, bouton, remplacer, annoncer, confirmer } from "/js/ui.js";
import { api } from "/js/app.js";
import { taille } from "/js/mail/outils.js";

const MAXI = 25_000_000;
const VIDE = { genre: "nouveau", compte: "", a: "", cc: "", objet: "", texte: "", en_reponse_a: "", references: "", transfert: "", pieces: [] };
const TITRES = { reponse: "réponse", "reponse-tous": "réponse à tous", transfert: "transfert" };

export function monterEcriture(zone, ctx) {
  const e = ctx.etat();
  const b = { ...VIDE, ...(ctx.brouillon() || {}) };
  b.pieces = Array.isArray(b.pieces) ? b.pieces.filter((p) => p && p.jeton).map((p) => ({ ...p })) : [];
  if (!e.comptes.some((c) => c.id === b.compte)) b.compte = e.comptes[0]?.id || "";
  let fini = false;          // volet refermé
  let envoi = false;         // envoi en cours
  let termine = false;       // envoyé ou supprimé : plus rien à enregistrer
  let minuterie = 0;

  const de = h("select", { id: "mail-de", class: "champ" }, e.comptes.map((c) =>
    h("option", { value: c.id, selected: c.id === b.compte, texte: c.nom ? `${c.nom} <${c.adresse}>` : c.adresse })));
  const a = h("input", { id: "mail-a", class: "champ", type: "text", value: b.a, autocomplete: "off", spellcheck: "false",
    placeholder: "adresse@exemple.fr, une autre…" });
  const cc = h("input", { id: "mail-cc", class: "champ", type: "text", value: b.cc, autocomplete: "off", spellcheck: "false" });
  const objet = h("input", { id: "mail-objet", class: "champ", type: "text", value: b.objet, maxlength: "300", autocomplete: "off" });
  const texte = h("textarea", { class: "champ texte-mail", "aria-label": "Texte du mail", lang: "fr", texte: b.texte });
  const ligne = (id, nom, champ, ...plus) => h("div", { class: "ligne-champ" }, h("label", { for: id, texte: nom }), champ, ...plus);
  const ligneCc = ligne("mail-cc", "Cc", cc);
  ligneCc.hidden = !b.cc;
  const boutonCc = h("button", { type: "button", class: "lien-discret", "aria-label": "Ajouter des destinataires en copie",
    hidden: !!b.cc, surclick: () => { ligneCc.hidden = false; boutonCc.hidden = true; cc.focus(); } }, "Cc");
  const listePieces = h("ul", { class: "pieces-envoi", "aria-label": "Pièces jointes" });
  const fichier = h("input", { type: "file", multiple: true, hidden: true, "aria-label": "Fichiers à joindre" });
  const statut = h("span", { class: "statut", role: "status" });
  const boutonEnvoyer = h("button", { type: "button", class: "bouton plein", title: "Envoyer (Ctrl + Entrée)", surclick: () => envoyer() }, "Envoyer");
  const formulaire = h("form", { class: "ecrire", "aria-label": "Écrire un mail" },
    h("div", { class: "haut" },
      h("button", { type: "button", class: "icone-seule retour", "aria-label": "Revenir à la liste", title: "Revenir à la liste (le brouillon reste)",
        surclick: ctx.allerListe }, icone("gauche")),
      h("h2", { texte: TITRES[b.genre] || "nouveau mail" })),
    e.comptes.length > 1 ? ligne("mail-de", "De", de) : null,
    ligne("mail-a", "À", a, boutonCc),
    ligneCc,
    ligne("mail-objet", "Objet", objet),
    texte,
    listePieces,
    h("div", { class: "pied" }, boutonEnvoyer, bouton("Joindre un fichier", { surClic: () => fichier.click() }), fichier, statut,
      h("button", { type: "button", class: "icone-seule", "aria-label": "Supprimer le brouillon", title: "Supprimer le brouillon",
        surclick: supprimer }, icone("poubelle"))));

  function dessinerPieces() {
    remplacer(listePieces,
      b.pieces.map((p) => h("li", {}, icone("trombone"), h("span", { class: "nom", texte: p.nom }),
        h("span", { class: "taille", texte: p.envoi ? "envoi…" : taille(p.taille) }),
        p.envoi ? null : h("button", { type: "button", class: "icone-seule", "aria-label": `Retirer ${p.nom}`, title: "Retirer",
          surclick: () => { b.pieces = b.pieces.filter((x) => x !== p); dessinerPieces(); planifier(); } }, icone("croix")))),
      b.transfert ? h("li", { class: "transfert" }, icone("trombone"), h("span", { texte: "Les pièces jointes du mail d'origine suivent." })) : null);
    listePieces.hidden = !b.pieces.length && !b.transfert;
  }

  async function joindre(fichiers) {
    for (const f of fichiers) {
      const total = b.pieces.reduce((n, p) => n + (p.taille || 0), 0);
      if (!f.size) { signaler(`${f.name} est vide.`); continue; }
      if (total + f.size > MAXI) { signaler(`${f.name} ne rentre pas : 25 Mo de pièces jointes en tout au plus.`); continue; }
      const attente = { nom: f.name, taille: f.size, envoi: true };
      b.pieces.push(attente);
      dessinerPieces();
      try {
        Object.assign(attente, await api.mettre(`/api/mail/pieces?nom=${encodeURIComponent(f.name)}`, f), { envoi: false });
      } catch (err) {
        b.pieces = b.pieces.filter((x) => x !== attente);
        if (!fini) signaler(`${f.name} : ${err.message}`);
      }
      if (fini) return;
      dessinerPieces();
      planifier();
    }
  }

  // --- le brouillon ---
  function valeurs() {
    return { genre: b.genre, compte: de.value || b.compte, a: a.value, cc: cc.value, objet: objet.value, texte: texte.value,
      en_reponse_a: b.en_reponse_a, references: b.references, transfert: b.transfert,
      pieces: b.pieces.filter((p) => p.jeton).map(({ jeton, nom, taille: t }) => ({ jeton, nom, taille: t })) };
  }
  const vide = (v) => !v.a.trim() && !v.cc.trim() && !v.objet.trim() && !v.texte.trim() && !v.pieces.length && !v.transfert && !v.en_reponse_a;
  let dernier = JSON.stringify(valeurs());
  function planifier() {
    clearTimeout(minuterie);
    minuterie = setTimeout(() => enregistrer(), 800);
  }
  function enregistrer(fermeture = false) {
    clearTimeout(minuterie);
    if (termine || envoi) return;
    const v = valeurs(), s = JSON.stringify(v);
    if (s === dernier) return;
    dernier = s;
    const brouillon = vide(v) ? null : v;
    ctx.brouillonChange(brouillon);
    // fenêtre qui se ferme : la demande doit partir quand même (« keepalive », 64 ko au plus)
    api.envoyer("/api/mail", { action: "brouillon", brouillon }, { keepalive: fermeture && s.length < 60000 }).then(
      () => { if (!fini && !statut.classList.contains("erreur")) statut.textContent = brouillon ? "Brouillon enregistré." : ""; },
      () => { if (!fini) signaler("Brouillon pas enregistré."); });
  }
  for (const c of [a, cc, objet, texte]) c.addEventListener("input", () => { statut.textContent = ""; statut.classList.remove("erreur"); planifier(); });
  de.addEventListener("change", planifier);
  const auRevoir = () => enregistrer(true);
  addEventListener("pagehide", auRevoir);

  // --- envoyer, supprimer ---
  // Ce qui empêche l'envoi s'écrit au pied du mail, à côté du bouton (une annonce le cacherait).
  function signaler(texte) {
    statut.textContent = texte;
    statut.classList.add("erreur");
  }
  async function envoyer() {
    if (envoi || termine) return;
    const v = valeurs();
    if (!v.a.trim()) { signaler("Indique au moins un destinataire."); a.focus(); return; }
    if (b.pieces.some((p) => p.envoi)) { signaler("Attends que les pièces jointes aient fini de se joindre."); return; }
    if (!v.objet.trim() && !(await confirmer({ titre: "Envoyer sans objet ?", texte: "Ton mail partira sans objet.", oui: "Envoyer" }))) {
      objet.focus();
      return;
    }
    envoi = true;
    clearTimeout(minuterie);
    boutonEnvoyer.disabled = true;
    boutonEnvoyer.textContent = "Envoi…";
    statut.textContent = "";
    let r = null;
    try {
      r = await api.envoyer("/api/mail", { action: "envoyer", compte: v.compte, a: v.a, cc: v.cc, objet: v.objet, texte: v.texte,
        pieces: v.pieces.map((p) => p.jeton), en_reponse_a: v.en_reponse_a, references: v.references, transfert: v.transfert });
    } catch (err) {
      if (fini) annoncer(err.message, { erreur: true }); else signaler(err.message);
    }
    envoi = false;
    if (r) {
      termine = true;
      ctx.brouillonChange(null);
      annoncer(r.message || "Mail envoyé.");
      ctx.relire();
      if (!fini) ctx.allerListe();
      return;
    }
    if (fini) { enregistrer(); return; }      // volet refermé pendant l'envoi raté : le brouillon reste
    boutonEnvoyer.disabled = false;
    boutonEnvoyer.textContent = "Envoyer";
  }

  async function supprimer() {
    if (!(await confirmer({ titre: "Supprimer ce brouillon ?", texte: "Ce que tu as écrit sera perdu.", oui: "Supprimer", danger: true }))) return;
    termine = true;
    clearTimeout(minuterie);
    ctx.brouillonChange(null);
    await ctx.agir({ action: "brouillon", brouillon: null }, "Brouillon supprimé.");
    if (!fini) ctx.allerListe();
  }

  formulaire.addEventListener("submit", (ev) => ev.preventDefault());      // Entrée dans un champ n'envoie pas
  formulaire.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); envoyer(); }
  });
  fichier.addEventListener("change", () => { const f = [...fichier.files]; fichier.value = ""; joindre(f); });
  // fichiers glissés sur le mail : joints
  formulaire.addEventListener("dragover", (ev) => {
    if (!ev.dataTransfer?.types.includes("Files")) return;
    ev.preventDefault();
    formulaire.classList.add("depot");
  });
  formulaire.addEventListener("dragleave", (ev) => { if (!formulaire.contains(ev.relatedTarget)) formulaire.classList.remove("depot"); });
  formulaire.addEventListener("drop", (ev) => {
    formulaire.classList.remove("depot");
    if (!ev.dataTransfer?.files.length) return;
    ev.preventDefault();
    joindre([...ev.dataTransfer.files]);
  });

  dessinerPieces();
  remplacer(zone, formulaire);
  if (!a.value.trim()) a.focus({ preventScroll: true });
  else {
    texte.focus({ preventScroll: true });
    texte.setSelectionRange(0, 0);
    texte.scrollTop = 0;
  }

  return {
    demonter() {
      fini = true;
      removeEventListener("pagehide", auRevoir);
      enregistrer();
    },
  };
}
