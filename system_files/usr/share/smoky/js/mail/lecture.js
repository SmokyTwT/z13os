// Smoky — Mail : la lecture d'un mail (volet de droite). Le HTML du mail s'affiche dans un cadre
// isolé, servi par le serveur sous une adresse tirée au sort : ni script, ni accès à l'appli,
// ni image chargée de l'extérieur (pas de mouchard). Les pièces jointes se téléchargent.
import { h, icone, bouton, interrupteur, remplacer, annoncer } from "/js/ui.js";
import { api } from "/js/app.js";
import { quandLong, taille, decouper, adresseDe, formater, prefixe, texteAvecLiens, demander } from "/js/mail/outils.js";

const PAR = { pc: "trié par le PC", regle: "rangé par ta règle", toi: "rangé par toi" };

export function monterLecture(zone, id, ctx) {
  let fini = false;
  let m = null;                  // le mail ouvert (réponse du serveur)
  let voirTexte = false;         // texte seul plutôt que la mise en page du mail
  let lu = true;
  const article = h("article", { class: "lettre" });
  const tete = h("header", { class: "lettre-tete" });
  const pieces = h("div");
  const corps = h("div", { class: "corps-lettre" });

  remplacer(zone, h("div", { class: "lecteur-vide" }, h("p", { class: "discret", texte: "Ouverture du mail…" })));
  api.lire(`/api/mail/${encodeURIComponent(id)}`).then((r) => {
    if (fini) return;
    m = r;
    voirTexte = !m.corps;
    ctx.marquerLu(id, true);
    article.replaceChildren(tete, pieces, corps);
    remplacer(zone, article);
    dessinerTete();
    dessinerPieces();
    dessinerCorps();
    if (ctx.etroit()) tete.querySelector("h2")?.focus({ preventScroll: true });
  }, (err) => {
    if (fini) return;
    remplacer(zone, h("div", { class: "lecteur-vide" }, h("p", { texte: err.message }),
      bouton("Revenir à la liste", { surClic: ctx.allerListe })));
  });

  const outil = (nom, texte, surClic, classe = "") => h("button", { type: "button", class: `icone-seule ${classe}`.trim(), "aria-label": texte, title: texte,
    surclick: surClic }, icone(nom));

  function dessinerTete() {
    const e = ctx.etat();
    const moi = new Set(e.comptes.map((c) => c.adresse.toLowerCase()));
    const expediteur = adresseDe(m.repondre_a || m.de_adresse);
    const autres = [...decouper(m.a), ...decouper(m.cc)].map(adresseDe).filter((x) => !moi.has(x) && x !== expediteur);
    const categorie = e.categories.find((c) => c.id === m.categorie)?.nom || m.categorie;
    remplacer(tete,
      h("div", { class: "haut" },
        outil("gauche", "Revenir à la liste", ctx.allerListe, "retour"),
        h("h2", { class: "titre-libre", tabindex: "-1", texte: m.objet })),
      h("div", { class: "expediteur" },
        h("span", { class: "nom", texte: m.de || m.de_adresse }),
        m.de && m.de.toLowerCase() !== m.de_adresse ? h("span", { class: "adresse", texte: m.de_adresse }) : null,
        h("span", { class: "date", texte: quandLong(m.date) })),
      m.a || m.cc ? h("p", { class: "destinataires" }, m.a ? `À : ${m.a}` : null, m.a && m.cc ? h("br") : null, m.cc ? `Cc : ${m.cc}` : null) : null,
      h("div", { class: "actions-lettre" },
        h("button", { type: "button", class: "bouton", surclick: () => repondre(false) }, icone("repondre"), "Répondre"),
        autres.length ? h("button", { type: "button", class: "bouton", surclick: () => repondre(true) }, "Répondre à tous") : null,
        h("button", { type: "button", class: "bouton", surclick: transferer }, icone("transferer"), "Transférer"),
        h("span", { class: "pousse" }),
        outil("archiver", "Archiver", archiver),
        outil("poubelle", "Mettre à la corbeille", corbeille),
        outil(lu ? "mail" : "coche", lu ? "Marquer comme non lu" : "Marquer comme lu", basculerLu)),
      h("p", { class: "rangement" }, `${categorie}, ${PAR[m.classe_par] || PAR.pc}. `,
        h("button", { type: "button", "aria-label": "Changer de catégorie", surclick: rangerDans }, "Changer")));
  }

  function dessinerPieces() {
    remplacer(pieces, m.pieces.length ? h("ul", { class: "pieces-mail", "aria-label": "Pièces jointes" }, m.pieces.map((p) =>
      h("li", {}, h("a", { href: p.adresse, download: p.nom, title: `Télécharger ${p.nom}` },
        icone("trombone"), h("span", { class: "nom", texte: p.nom }), h("span", { class: "taille", texte: taille(p.taille) }))))) : null);
  }

  function dessinerCorps() {
    const bascule = m.corps ? h("div", { class: "vue-lettre" },
      m.images_distantes && !voirTexte ? h("span", { class: "discret petit", texte: "Images venues d'internet non chargées : elles servent souvent à savoir si tu as lu le mail." }) : null,
      h("button", { type: "button", class: "lien-discret", surclick: () => { voirTexte = !voirTexte; dessinerCorps(); } },
        voirTexte ? "Voir la mise en page du mail" : "Voir le texte seul")) : null;
    const contenu = !voirTexte
      ? h("iframe", { class: "feuille-lettre", src: m.corps, sandbox: "allow-popups allow-popups-to-escape-sandbox",
        referrerpolicy: "no-referrer", title: `Contenu du mail : ${m.objet}` })
      : h("div", { class: "texte-lettre" }, m.texte.trim() ? texteAvecLiens(m.texte.trim(), { ecrireA }) : h("span", { class: "discret", texte: "Ce mail n'a pas de texte." }));
    remplacer(corps, bascule, contenu);
  }

  // --- répondre, transférer ---
  function citation() {
    const texte = m.texte.length > 20000 ? `${m.texte.slice(0, 20000)}\n[…]` : m.texte;
    return `Le ${quandLong(m.date)}, ${m.de || m.de_adresse} a écrit :\n` +
      texte.trimEnd().split("\n").map((l) => (l.startsWith(">") ? `>${l}` : `> ${l}`)).join("\n");
  }

  function repondre(tous) {
    const moi = new Set(ctx.etat().comptes.map((c) => c.adresse.toLowerCase()));
    const a = m.repondre_a || formater(m.de, m.de_adresse);
    const vus = new Set(decouper(a).map(adresseDe));
    const cc = tous ? [...decouper(m.a), ...decouper(m.cc)].filter((x) => {
      const ad = adresseDe(x);
      if (moi.has(ad) || vus.has(ad)) return false;
      vus.add(ad);
      return true;
    }).join(", ") : "";
    ctx.ecrire({ genre: tous ? "reponse-tous" : "reponse", compte: m.compte, a, cc, objet: prefixe("Re", m.objet),
      texte: `\n\n${citation()}\n`, en_reponse_a: m.message_id, references: m.references, transfert: "", pieces: [] });
  }

  function transferer() {
    const entete = ["---------- Mail transféré ----------", `De : ${formater(m.de, m.de_adresse)}`, `Date : ${quandLong(m.date)}`,
      `Objet : ${m.objet}`, m.a ? `À : ${m.a}` : null, m.cc ? `Cc : ${m.cc}` : null].filter(Boolean).join("\n");
    ctx.ecrire({ genre: "transfert", compte: m.compte, a: "", cc: "", objet: prefixe("Tr", m.objet),
      texte: `\n\n${entete}\n\n${m.texte.slice(0, 190000)}`, en_reponse_a: "", references: "", transfert: m.pieces.length ? m.id : "", pieces: [] });
  }

  function ecrireA(adresse) {
    ctx.ecrire({ genre: "nouveau", compte: m.compte, a: adresse, cc: "", objet: "", texte: "", en_reponse_a: "", references: "", transfert: "", pieces: [] });
  }

  // --- ranger ---
  async function archiver() { if (await ctx.agir({ action: "archiver", id: m.id })) ctx.allerListe(); }
  async function corbeille() { if (await ctx.agir({ action: "corbeille", id: m.id })) ctx.allerListe(); }

  async function basculerLu() {
    const r = lu ? await ctx.agir({ action: "non_lu", id: m.id }, "Marqué comme non lu.")
      : await ctx.agir({ action: "lu", id: m.id }, "Marqué comme lu.");
    if (!r || fini) return;
    lu = !lu;
    ctx.marquerLu(m.id, lu);
    dessinerTete();
    tete.querySelector(`[aria-label="${lu ? "Marquer comme non lu" : "Marquer comme lu"}"]`)?.focus();
  }

  // Changer la catégorie d'un mail (et, si tu veux, celle des prochains du même expéditeur).
  function rangerDans() {
    const e = ctx.etat();
    let choisie = m.categorie, toujours = false;
    const d = h("dialog", { class: "ranger-mail", "aria-labelledby": "r-titre" });
    const erreur = h("p", { class: "erreur", role: "alert" });
    const choix = h("div", { class: "choix-categorie", role: "radiogroup", "aria-label": "Catégorie" });
    for (const c of e.categories) {
      choix.append(h("button", { type: "button", role: "radio", "aria-checked": String(c.id === choisie), surclick: (ev) => {
        choisie = c.id;
        for (const b of choix.children) b.setAttribute("aria-checked", String(b === ev.currentTarget));
      } }, c.nom));
    }
    const regle = interrupteur({ coche: false, nom: `Aussi les prochains mails de ${m.de_adresse}`,
      surChange: (v, b) => { toujours = v; b.setAttribute("aria-checked", String(v)); } });
    const ranger = h("button", { type: "submit", class: "bouton plein" }, "Ranger");
    const formulaire = h("form", { method: "dialog" },
      h("h2", { id: "r-titre", texte: "ranger ce mail" }),
      h("p", { texte: `Le tri se fait sur ce PC. Ce mail de ${m.de || m.de_adresse} va dans :` }),
      choix,
      h("div", { class: "rangee" },
        h("div", { class: "texte" }, h("div", { class: "nom", texte: "Aussi les prochains" }),
          h("div", { class: "aide", texte: `Les mails de ${m.de_adresse} iront toujours là.` })),
        h("div", { class: "commande" }, regle)),
      erreur,
      h("div", { class: "boutons" }, bouton("Annuler", { surClic: () => d.close() }), ranger));
    formulaire.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      ranger.disabled = true;
      const r = await demander({ action: "classer", id: m.id, categorie: choisie, toujours }, erreur);
      ranger.disabled = false;
      if (!r) return;
      d.close();
      annoncer(r.message);
      if (fini) return;
      m.categorie = choisie;
      m.classe_par = "toi";
      dessinerTete();
      ctx.relire();
    });
    d.append(formulaire);
    d.addEventListener("close", () => d.remove());
    document.body.append(d);
    d.showModal();
    choix.querySelector('[aria-checked="true"]')?.focus();
  }

  return {
    demonter() { fini = true; },
  };
}
