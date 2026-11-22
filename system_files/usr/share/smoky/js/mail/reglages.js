// Smoky — Mail : réglages (tes boîtes, notifications, règles de tri) et ajout d'une boîte.
// Un mot de passe ne fait que passer : la page l'envoie au serveur, qui le range dans le trousseau
// de GNOME après un essai de connexion ; le champ est vidé aussitôt. Le champ n'est pas un champ
// « mot de passe » pour le navigateur : il ne propose pas de l'enregistrer de son côté.
import { h, icone, bouton, interrupteur, rangee, remplacer, annoncer, confirmer } from "/js/ui.js";
import { api } from "/js/app.js";
import { quandCourt, demander, garderFocus } from "/js/mail/outils.js";

// Les pages d'aide s'ouvrent dans ton navigateur habituel (connecté à tes comptes), par le serveur
// qui ne connaît que ces quelques adresses.
function ouvrirPage(quoi) {
  api.envoyer("/api/ouvrir", { quoi }).then(() => annoncer("La page s'ouvre dans ton navigateur."),
    (err) => annoncer(err.message, { erreur: true }));
}

export function rangeesAjout(ctx) {
  const ajout = (genre, nom, aide) => rangee(nom, aide, h("button", { type: "button", class: "bouton", "aria-label": `Ajouter une boîte ${nom}`,
    surclick: () => ajouterBoite(genre, ctx) }, "Ajouter"));
  return [
    ajout("gmail", "Gmail", "Avec un mot de passe d'application de 16 lettres, créé sur ton compte Google."),
    ajout("outlook", "Outlook / Hotmail", "Connexion sur la page de Microsoft, avec un code à recopier."),
    ajout("uphf", "UPHF", "Ton adresse de l'université et le mot de passe de l'ENT."),
    ajout("autre", "Autre boîte", "N'importe quelle boîte IMAP, si tu connais l'adresse de ses serveurs."),
  ];
}

function quandReleve(ts) {
  const q = quandCourt(ts);
  return q.includes(" h ") ? `à ${q}` : q === "hier" ? "hier" : `le ${q}`;
}

export function monterReglages(zone, ctx) {
  function dessiner() {
    const e = ctx.etat();
    const nomCategorie = (id) => e.categories.find((c) => c.id === id)?.nom || id;
    const champId = h("input", { class: "champ", type: "text", value: e.reglages.microsoft, spellcheck: "false", autocomplete: "off",
      placeholder: "1234abcd-12ab-34cd-56ef-1234567890ab", "aria-label": "ID d'application Microsoft" });
    garderFocus(zone, () => remplacer(zone, h("div", { class: "reglages-mail" },
      h("div", { class: "haut" },
        h("button", { type: "button", class: "icone-seule retour", "aria-label": "Revenir à la liste", title: "Revenir à la liste",
          surclick: ctx.allerListe }, icone("gauche")),
        h("h2", { class: "titre-volet", texte: "réglages du mail" })),
      h("section", { class: "section" }, h("h2", { texte: "tes boîtes" }),
        h("div", { class: "groupe" }, e.comptes.map((c) => ligneCompte(c, e)), rangeesAjout(ctx))),
      h("section", { class: "section" }, h("h2", { texte: "notifications" }),
        h("div", { class: "groupe" }, rangee("Prévenir des nouveaux mails",
          "Seulement ceux de l'université et des personnes, jamais les pubs ni les newsletters. La relève passe toutes les 15 minutes (30 sur batterie), même Smoky fermé.",
          interrupteur({ coche: e.reglages.notifier, nom: "Prévenir des nouveaux mails",
            surChange: (v) => ctx.agir({ action: "reglages", notifier: v }, v ? "Notifications activées." : "Notifications coupées.") })))),
      h("section", { class: "section" }, h("h2", { texte: "tri" }),
        h("p", { class: "intro", texte: "Le tri se fait sur ce PC, d'après l'expéditeur et l'objet : aucun mail ne part vers un service. Pour corriger un tri, ouvre le mail et choisis « Changer » à côté de sa catégorie." }),
        e.regles.length ? h("div", { class: "groupe" }, e.regles.map((r) => rangee(r.expediteur, `Toujours dans ${nomCategorie(r.categorie)}.`,
          h("button", { type: "button", class: "bouton", "aria-label": `Oublier la règle de ${r.expediteur}`,
            surclick: () => ctx.agir({ action: "oublier_regle", expediteur: r.expediteur }) }, "Oublier"))))
          : h("p", { class: "vide", texte: "Aucune règle pour l'instant." })),
      e.reglages.microsoft || e.comptes.some((c) => c.genre === "outlook") ? h("section", { class: "section" }, h("h2", { texte: "outlook" }),
        h("div", { class: "groupe" }, rangee("ID d'application Microsoft", "Celui de ton inscription d'application, qui sert à te connecter à Outlook / Hotmail.",
          champId, bouton("Enregistrer", { surClic: () => ctx.agir({ action: "microsoft_id", id_appli: champId.value.trim() }, "Identifiant enregistré.") })))) : null)));
  }

  function ligneCompte(c, e) {
    const genre = e.genres[c.genre]?.nom || c.genre;
    const aide = c.probleme || [genre, c.envoi ? `envoi avec ${c.envoi}` : null,
      c.releve ? `relevée ${quandReleve(c.releve)}` : "première relève en cours"].filter(Boolean).join(", ") + ".";
    return h("div", { class: c.probleme ? "rangee alerte" : "rangee" },
      h("div", { class: "texte" }, h("div", { class: "nom", texte: c.nom ? `${c.nom} <${c.adresse}>` : c.adresse }), h("div", { class: "aide", texte: aide })),
      h("div", { class: "commande" },
        c.probleme ? h("button", { type: "button", class: "bouton", "aria-label": `Réparer ${c.adresse}`,
          surclick: () => ajouterBoite(c.auth === "microsoft" ? "outlook" : c.genre, ctx, c) }, c.auth === "microsoft" ? "Reconnecter" : "Remettre le mot de passe") : null,
        h("button", { type: "button", class: "bouton braise", "aria-label": `Retirer ${c.adresse}`, surclick: async () => {
          if (await confirmer({ titre: `Retirer ${c.adresse} ?`, texte: "Smoky oublie cette boîte et son mot de passe. Les mails restent sur le serveur, rien n'y est effacé.",
            oui: "Retirer", danger: true })) ctx.agir({ action: "retirer", id: c.id });
        } }, "Retirer")));
  }

  // pas de nouveau dessin sous tes doigts : un champ modifié et pas encore enregistré reste tel quel
  const enEdition = () => [...zone.querySelectorAll("input")].some((c) => c === document.activeElement && c.value !== c.defaultValue);
  dessiner();
  return {
    mettreAJour() { if (!enEdition()) dessiner(); },
  };
}

// --- ajouter une boîte ------------------------------------------------------------------------------
const TITRES = { gmail: "ajouter gmail", uphf: "ajouter ta boîte uphf", autre: "ajouter une boîte" };

export function ajouterBoite(genre, ctx, prerempli = {}) {
  if (genre === "outlook") { connecterOutlook(ctx); return; }
  const d = h("dialog", { class: "boite-mail", "aria-labelledby": "bm-titre" });
  const erreur = h("p", { class: "erreur", role: "alert" });
  const champ = (attributs) => h("input", { class: "champ", autocomplete: "off", spellcheck: "false", ...attributs });
  const etiquette = (nom, element, aide) => h("label", {}, h("span", { texte: nom }), element, aide ? h("small", { texte: aide }) : null);
  const adresse = champ({ type: "email", required: true, value: prerempli.adresse || "",
    placeholder: { gmail: "prenom.nom@gmail.com", uphf: "prenom.nom@uphf.fr" }[genre] || "toi@exemple.fr" });
  const nom = champ({ type: "text", maxlength: "100", value: prerempli.nom || "", placeholder: "Prénom Nom", spellcheck: null });
  const secret = champ({ type: "text", required: true, class: "champ secret" });
  const montrer = h("button", { type: "button", class: "lien-discret", "aria-pressed": "false", surclick: () => {
    const voir = montrer.getAttribute("aria-pressed") !== "true";
    montrer.setAttribute("aria-pressed", String(voir));
    secret.classList.toggle("secret", !voir);
    montrer.textContent = voir ? "Cacher" : "Montrer";
  } }, "Montrer");
  const envoiUphf = champ({ type: "text", inputmode: "numeric", maxlength: "40", placeholder: "12345678" });
  const imap = champ({ type: "text", placeholder: "imap.exemple.fr" });
  const smtp = champ({ type: "text", placeholder: "smtp.exemple.fr" });
  const port = h("select", { class: "champ" }, h("option", { value: "465", texte: "465 (chiffré dès le début)" }), h("option", { value: "587", texte: "587 (STARTTLS)" }));
  const identifiantEnvoi = champ({ type: "text", maxlength: "80", placeholder: "si différent de l'adresse" });
  const ajouter = h("button", { type: "submit", class: "bouton plein" }, "Ajouter");

  const explications = {
    gmail: h("ol", { class: "etapes" },
      h("li", {}, "Sur ton compte Google, active la validation en deux étapes, si ce n'est pas déjà fait."),
      h("li", {}, "Crée un mot de passe d'application nommé « Smoky » : Google affiche 16 lettres. ",
        h("button", { type: "button", class: "lien-discret", surclick: () => ouvrirPage("aide-gmail") }, "Ouvrir la page de Google")),
      h("li", {}, "Colle ces 16 lettres ci-dessous. Elles vont dans le trousseau de GNOME, jamais dans un fichier.")),
    uphf: h("p", { class: "secondaire", texte: "Ton adresse de l'université et le mot de passe de l'ENT. Pour envoyer, l'UPHF demande aussi ton numéro ENT (l'identifiant à chiffres)." }),
    autre: h("p", { class: "secondaire", texte: "Les adresses des serveurs sont dans l'aide de ta messagerie (réglages IMAP et SMTP). La connexion est toujours chiffrée." }),
  };
  // un même champ ne peut être qu'à un endroit : seules les étiquettes du genre choisi sont construites
  const champs = {
    gmail: () => [etiquette("Adresse Gmail", adresse), etiquette("Mot de passe d'application", secret), montrer, etiquette("Ton nom (vu par tes correspondants)", nom)],
    uphf: () => [etiquette("Adresse UPHF", adresse), etiquette("Mot de passe de l'ENT", secret), montrer,
      etiquette("Numéro ENT", envoiUphf, prerempli.envoi ? `Laisse vide pour garder ${prerempli.envoi}.` : "Sert seulement à envoyer."), etiquette("Ton nom (vu par tes correspondants)", nom)],
    autre: () => [etiquette("Adresse", adresse), etiquette("Mot de passe", secret), montrer, etiquette("Serveur IMAP (réception, port 993)", imap),
      etiquette("Serveur SMTP (envoi)", smtp), etiquette("Port d'envoi", port), etiquette("Identifiant d'envoi", identifiantEnvoi), etiquette("Ton nom", nom)],
  }[genre]();

  const formulaire = h("form", { method: "dialog" }, h("h2", { id: "bm-titre", texte: TITRES[genre] }), explications[genre], champs, erreur,
    h("div", { class: "boutons" }, bouton("Annuler", { surClic: () => d.close() }), ajouter));
  formulaire.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (ajouter.disabled) return;
    if (!adresse.value.trim()) { adresse.focus(); return; }
    if (!secret.value) { secret.focus(); return; }
    const corps = { action: "ajouter", genre, adresse: adresse.value.trim(), nom: nom.value.trim(), motdepasse: secret.value,
      identifiant_envoi: genre === "uphf" ? envoiUphf.value.trim() : genre === "autre" ? identifiantEnvoi.value.trim() : "",
      imap: imap.value.trim(), smtp: smtp.value.trim(), port_smtp: Number(port.value) };
    secret.value = "";                                   // la page ne le garde pas
    ajouter.disabled = true;
    ajouter.textContent = "Vérification…";
    const r = await demander(corps, erreur);
    corps.motdepasse = "";
    ajouter.disabled = false;
    ajouter.textContent = "Ajouter";
    if (!r) { secret.focus(); return; }
    d.close();
    annoncer(r.message);
    ctx.relire();
  });
  d.append(formulaire);
  d.addEventListener("close", () => { secret.value = ""; d.remove(); });
  document.body.append(d);
  d.showModal();
  (adresse.value ? secret : adresse).focus();
}

// Outlook / Hotmail : Microsoft n'accepte plus de mot de passe dans les applis de mail. La connexion
// se fait sur sa page, avec un code ; il faut pour cela un identifiant d'application (créé une fois).
function connecterOutlook(ctx) {
  const d = h("dialog", { class: "boite-mail", "aria-labelledby": "ms-titre" });
  const contenu = h("div", { class: "contenu" });
  const erreur = h("p", { class: "erreur", role: "alert" });
  let changerId = false;
  let suivi = ctx.etat().microsoft?.etat === "attente";     // une connexion lancée d'ici (ou en cours) : on montre sa fin
  let dessine = "";                                         // l'étape affichée (redessinée seulement si elle change)

  function dessiner() {
    const e = ctx.etat(), ms = e.microsoft || {};
    if (suivi && ms.etat === "fini") {
      annoncer(`${ms.adresse} ajoutée : la relève commence.`);
      d.close();
      return;
    }
    const etape = !e.reglages.microsoft || changerId ? "appli" : suivi && ms.etat === "attente" ? `code ${ms.code}`
      : `pret ${suivi && ms.etat === "erreur" ? ms.erreur : ""}`;
    if (etape === dessine) return;                          // rien de neuf : ce que tu tapes reste
    dessine = etape;
    const titre = h("h2", { id: "ms-titre", texte: "ajouter outlook" });
    if (!e.reglages.microsoft || changerId) {
      const champId = h("input", { class: "champ", type: "text", value: e.reglages.microsoft, spellcheck: "false", autocomplete: "off",
        placeholder: "1234abcd-12ab-34cd-56ef-1234567890ab" });
      const continuer = h("button", { type: "submit", class: "bouton plein" }, "Continuer");
      const f = h("form", { method: "dialog" }, titre,
        h("p", { texte: "Microsoft n'accepte plus les mots de passe dans les applis de mail : la connexion se fait sur sa page, une fois. Il faut pour cela un identifiant d'application, que tu crées toi-même, gratuitement :" }),
        h("ol", { class: "etapes" },
          h("li", {}, "Ouvre le portail Microsoft Entra avec ton compte, puis « Inscriptions d'applications » et « Nouvelle inscription ». Microsoft range ces inscriptions dans un « annuaire » : s'il n'en trouve pas, le portail propose d'en créer un. ",
            h("button", { type: "button", class: "lien-discret", surclick: () => ouvrirPage("aide-microsoft") }, "Ouvrir le portail")),
          h("li", {}, "Nom : Smoky. Types de comptes : ceux d'un annuaire organisationnel et les comptes Microsoft personnels. Pas d'adresse de redirection."),
          h("li", {}, "Dans « Authentification », active « Autoriser les flux clients publics »."),
          h("li", {}, "Copie l'« ID d'application (client) » et colle-le ici.")),
        h("label", {}, h("span", { texte: "ID d'application (client)" }), champId),
        erreur,
        h("div", { class: "boutons" }, bouton("Annuler", { surClic: () => d.close() }), continuer));
      f.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        continuer.disabled = true;
        const r = await demander({ action: "microsoft_id", id_appli: champId.value.trim() }, erreur);
        continuer.disabled = false;
        if (!r) return;
        changerId = false;
        await ctx.relire();
      });
      remplacer(contenu, f);
      champId.focus();
      return;
    }
    if (suivi && ms.etat === "attente") {
      remplacer(contenu, titre,
        h("p", { texte: "Sur la page de Microsoft, entre ce code, connecte-toi, puis accepte que Smoky lise et envoie tes mails :" }),
        h("p", { class: "code", texte: ms.code }),
        h("div", { class: "boutons centre" },
          bouton("Copier le code", { surClic: () => navigator.clipboard.writeText(ms.code).then(() => annoncer("Code copié."), () => {}) }),
          bouton("Ouvrir la page de Microsoft", { genre: "plein", surClic: () => ouvrirPage("microsoft-code") })),
        h("p", { class: "discret petit", texte: `La page : ${ms.adresse_page}, depuis n'importe quel appareil. Smoky attend ta réponse…` }),
        h("div", { class: "boutons" },
          bouton("Annuler la connexion", { surClic: async () => { suivi = false; await demander({ action: "microsoft_annuler" }, erreur); d.close(); } }),
          bouton("Fermer", { surClic: () => d.close() })));
      return;
    }
    const obtenir = h("button", { type: "button", class: "bouton plein", surclick: async () => {
      obtenir.disabled = true;
      const r = await demander({ action: "microsoft_debut" }, erreur);
      obtenir.disabled = false;
      if (!r) return;
      suivi = true;
      await ctx.relire();
    } }, "Obtenir un code");
    remplacer(contenu, titre,
      h("p", { texte: "Smoky demande un code à Microsoft. Tu l'entres sur la page de Microsoft, avec ton compte Outlook ou Hotmail, et la boîte s'ajoute toute seule." }),
      suivi && ms.etat === "erreur" ? h("p", { class: "erreur", texte: ms.erreur }) : null,
      erreur,
      h("div", { class: "boutons" },
        bouton("Changer d'identifiant d'application", { surClic: () => { changerId = true; erreur.textContent = ""; dessiner(); } }),
        bouton("Annuler", { surClic: () => d.close() }), obtenir));
    obtenir.focus();
  }

  const oublier = ctx.suivre(dessiner);
  d.append(contenu);
  d.addEventListener("close", () => { oublier(); d.remove(); });
  document.body.append(d);
  d.showModal();
  dessiner();
}
