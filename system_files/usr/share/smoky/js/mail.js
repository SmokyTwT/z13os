// Smoky — page « Mail » : toutes tes boîtes dans une seule liste, triée sur ce PC (université,
// personnes, achats, newsletters, notifications), la lecture à côté, l'écriture et les réglages.
//   #/mail[/<vue>[/<id>]]   vue : boite, non-lus ou une catégorie ; id : le mail ouvert
//   #/mail/ecrire           le brouillon en cours
//   #/mail/reglages         boîtes, notifications, règles de tri
// Tout vient du serveur (smoky/courrier.py) ; la page ne garde que ce qu'elle affiche.
import { h, icone, remplacer, annoncer, confirmer } from "/js/ui.js";
import { api, tenter } from "/js/app.js";
import { quandCourt, garderFocus } from "/js/mail/outils.js";
import { monterLecture } from "/js/mail/lecture.js";
import { monterEcriture } from "/js/mail/ecrire.js";
import { monterReglages, ajouterBoite, rangeesAjout } from "/js/mail/reglages.js";

const PAR_PAGE = 60;                       // comme le serveur
const RELEVE = 3 * 60 * 1000;              // page ouverte : une relève toutes les 3 minutes
const ETROIT = matchMedia("(max-width: 720px)");

export async function monter(conteneur, contexte) {
  let e = null;                 // dernier état reçu du serveur
  let messages = [];            // la liste affichée (première page et suites chargées)
  let suite = false;            // il reste des mails plus anciens
  let chargee = false;          // la liste affichée correspond à la vue, à la recherche et au filtre
  let voulus = PAR_PAGE;        // combien en relire (les suites déjà chargées restent affichées)
  let vue = "boite";            // boite, non-lus, une catégorie, ecrire ou reglages
  let vueListe = "boite";       // ce que montre la liste (ecrire et reglages gardent la précédente)
  let ouvert = null;            // id du mail ouvert
  let compte = "";              // filtre : une seule boîte
  let lectures = 0;             // numéro de la dernière relecture (une réponse en retard est ignorée)
  let brouillonLocal;           // le brouillon tel qu'enregistré d'ici (le serveur ne prévient pas pour lui)
  let panneau = null;           // ce qui occupe le volet de droite : { genre, id, objet }
  let derniereReleve = 0;       // quand cette page a demandé une relève
  const abonnes = new Set();    // dialogues qui suivent l'état (connexion Microsoft)

  // --- la charpente : construite une fois (le champ de recherche garde son curseur) ---
  const sous = h("p", { class: "sous" });
  const boutonReleve = h("button", { type: "button", class: "bouton", title: "Relever toutes les boîtes maintenant", hidden: true,
    surclick: () => relever(true) }, "Relever");
  const boutonEcrire = h("a", { class: "bouton plein", href: "#/mail/ecrire", hidden: true }, "Écrire");
  const entete = h("header", { class: "entete" }, h("div", {}, h("h1", { texte: "mail" }), sous),
    h("div", { class: "boutons" }, boutonReleve, boutonEcrire));
  const nav = h("nav", { class: "dossiers", "aria-label": "Dossiers du mail" });
  const recherche = h("input", { class: "champ recherche", type: "search", placeholder: "Chercher dans les mails",
    "aria-label": "Chercher dans les mails", autocomplete: "off", spellcheck: "false" });
  const filtre = h("div", { class: "filtre" });
  const alertes = h("div", { class: "alertes" });
  const liste = h("ul", { class: "messages", "aria-label": "Mails" });
  const plus = h("button", { type: "button", class: "bouton plus", hidden: true, surclick: () => chargerPlus() }, "Voir les plus anciens");
  const defile = h("div", { class: "defile" }, liste, plus);
  const colonne = h("section", { class: "liste-mails", "aria-label": "Liste des mails" },
    h("div", { class: "outils" }, recherche, filtre, alertes), defile);
  const lecteur = h("section", { class: "lecteur", "aria-label": "Lecture" });
  const volets = h("div", { class: "mail-volets" }, nav, colonne, lecteur);
  const accueil = h("div", { class: "corps mail-accueil" });
  const page = h("div", { class: "mail" }, entete);         // les volets (ou l'accueil) arrivent avec l'état
  conteneur.replaceChildren(page);

  // --- ce que les volets peuvent demander à la page ---
  const ctx = {
    etat: () => e,
    agir,
    relire,
    suivre: (f) => { abonnes.add(f); return () => abonnes.delete(f); },
    allerListe: () => { location.hash = `#/mail/${vueListe}`; },
    etroit: () => ETROIT.matches,
    marquerLu(id, lu) {
      const m = messages.find((x) => x.id === id);
      if (m && m.lu !== lu) { m.lu = lu; dessinerListe(); }
    },
    brouillon: () => (brouillonLocal !== undefined ? brouillonLocal : e?.brouillon || null),
    brouillonChange(b) { brouillonLocal = b; if (e) dessinerDossiers(); },
    // Répondre, transférer, écrire à une adresse : un nouveau brouillon (l'ancien, s'il a du contenu,
    // n'est remplacé qu'après confirmation), puis l'écriture
    async ecrire(b) {
      const actuel = ctx.brouillon();
      if (actuel && ["a", "cc", "objet", "texte"].some((k) => String(actuel[k] || "").trim()) &&
          !(await confirmer({ titre: "Remplacer le brouillon ?", texte: "Le mail que tu avais commencé sera perdu.", oui: "Remplacer", danger: true }))) {
        return;
      }
      brouillonLocal = b;
      api.envoyer("/api/mail", { action: "brouillon", brouillon: b }).catch((err) => annoncer(err.message, { erreur: true }));
      location.hash = "#/mail/ecrire";
    },
    ajouterBoite: (genre, prerempli) => ajouterBoite(genre, ctx, prerempli),
  };

  // --- échanges avec le serveur ---
  function adresseListe(avant) {
    const p = new URLSearchParams();
    if (vueListe !== "boite") p.set("categorie", vueListe);
    if (recherche.value.trim()) p.set("recherche", recherche.value.trim());
    if (compte) p.set("compte", compte);
    if (avant !== undefined) p.set("avant", String(avant));
    return `/api/mail?${p}`;
  }

  async function relire() {
    const numero = ++lectures;
    try {
      const etat = await api.lire(adresseListe());
      if (numero !== lectures) return;
      if (compte && !etat.comptes.some((c) => c.id === compte)) { compte = ""; return relire(); }   // boîte retirée
      let tous = etat.messages, reste = etat.suite;
      while (reste && tous.length < voulus) {          // les suites déjà affichées sont relues aussi
        const s = await api.lire(adresseListe(tous[tous.length - 1].date));
        if (numero !== lectures) return;
        tous = tous.concat(s.messages);
        reste = s.suite;
      }
      e = etat;
      messages = tous;
      suite = reste;
      chargee = true;
      dessiner();
      for (const f of abonnes) f(e);
    } catch (err) {
      if (numero === lectures) annoncer(err.message, { erreur: true });
    }
  }

  async function chargerPlus() {
    if (!messages.length) return;
    const numero = lectures;
    plus.disabled = true;
    try {
      const s = await api.lire(adresseListe(messages[messages.length - 1].date));
      if (numero !== lectures) return;                 // une relecture est passée entre-temps
      const connus = new Set(messages.map((m) => m.id));
      messages = messages.concat(s.messages.filter((m) => !connus.has(m.id)));
      suite = s.suite;
      voulus = messages.length;
      dessinerListe();
    } catch (err) {
      annoncer(err.message, { erreur: true });
    } finally {
      plus.disabled = false;
    }
  }

  async function agir(corps, succes) {
    let reponse = null;
    const ok = await tenter(async () => (reponse = await api.envoyer("/api/mail", corps)), { succes });
    relire();
    return ok ? reponse || {} : null;
  }

  // Relève de toutes les boîtes (le serveur prévient quand elle commence et quand elle finit).
  async function relever(demandee = false) {
    if (!e || !e.comptes.length || e.releve.en_cours) return;
    derniereReleve = Date.now();
    try {
      await api.envoyer("/api/mail", { action: "relever" });
    } catch (err) {
      if (demandee) annoncer(err.message, { erreur: true });
    }
  }
  const releveDue = () => e && e.comptes.length && !e.releve.en_cours && Date.now() - derniereReleve > RELEVE - 5000 &&
    Date.now() - e.releve.derniere * 1000 > RELEVE - 5000;

  // --- dessin ---
  function dessiner() {
    if (!e) return;
    dessinerEntete();
    if (!e.comptes.length) {
      page.classList.remove("lisant");
      panneau?.objet?.demonter?.();
      panneau = null;
      if (!accueil.firstChild) {
        remplacer(accueil, h("section", { class: "section" },
          h("h2", { texte: "ajoute tes boîtes" }),
          h("p", { class: "intro", texte: "Smoky relève tes boîtes et trie les mails sur ce PC : université, personnes, achats, newsletters, notifications. Rien ne part vers un service extérieur, et les mots de passe restent dans le trousseau de GNOME." }),
          h("div", { class: "groupe" }, rangeesAjout(ctx))));
      }
      if (accueil.parentNode !== page) page.replaceChildren(entete, accueil);
      return;
    }
    if (volets.parentNode !== page) page.replaceChildren(entete, volets);
    page.classList.toggle("lisant", vue === "ecrire" || vue === "reglages" || !!ouvert);
    dessinerDossiers();
    dessinerListe();
    afficherPanneau();
  }

  function dessinerEntete() {
    const nonLus = e.categories.filter((c) => c.id !== "indesirable").reduce((n, c) => n + c.non_lus, 0);
    const morceaux = [];
    if (!e.comptes.length) morceaux.push("aucune boîte pour l'instant");
    else {
      morceaux.push(nonLus ? `${nonLus} non lu${nonLus > 1 ? "s" : ""}` : "tout est lu");
      if (e.releve.en_cours) morceaux.push("relève en cours");
      else if (e.releve.derniere) {
        const q = quandCourt(e.releve.derniere);
        morceaux.push(q.includes(" h ") ? `relevé à ${q}` : `relevé ${q === "hier" ? "hier" : `le ${q}`}`);
      }
    }
    sous.textContent = morceaux.join(", ");
    boutonReleve.hidden = boutonEcrire.hidden = !e.comptes.length;
    boutonReleve.disabled = e.releve.en_cours;
    boutonReleve.textContent = e.releve.en_cours ? "Relève…" : "Relever";
    if (vue === "ecrire") boutonEcrire.setAttribute("aria-current", "page"); else boutonEcrire.removeAttribute("aria-current");
  }

  function dessinerDossiers() {
    const nonLus = e.categories.filter((c) => c.id !== "indesirable").reduce((n, c) => n + c.non_lus, 0);
    const courant = (id) => (vue !== "ecrire" && vue !== "reglages" && vueListe === id ? "page" : null);
    const lien = (id, nom, n) => h("a", { href: `#/mail/${id}`, "data-cle": `vue-${id}`, "aria-current": courant(id),
      "aria-label": n ? `${nom}, ${n} non lu${n > 1 ? "s" : ""}` : nom },
    h("span", { class: "nom", texte: nom }), n ? h("span", { class: "compte", texte: String(n) }) : null);
    const b = ctx.brouillon();
    garderFocus(nav, () => remplacer(nav,
      lien("boite", "Boîte de réception", nonLus),
      lien("non-lus", "Non lus", 0),
      h("p", { class: "titre-dossiers", texte: "Triés sur ce PC" }),
      e.categories.map((c) => lien(c.id, c.nom, c.non_lus)),
      b ? h("a", { href: "#/mail/ecrire", "data-cle": "brouillon", "aria-current": vue === "ecrire" ? "page" : null, class: "brouillon" },
        icone("stylo"), h("span", { class: "nom", texte: `Brouillon${b.objet ? ` : ${b.objet}` : ""}` })) : null,
      h("p", { class: "titre-dossiers", texte: "Boîtes" }),
      e.comptes.map((c) => h("button", { type: "button", class: "boite", "data-cle": `compte-${c.id}`, "aria-pressed": String(compte === c.id),
        title: c.probleme || (compte === c.id ? "Revoir toutes les boîtes" : `Seulement ${c.adresse}`),
        surclick: () => choisirCompte(compte === c.id ? "" : c.id) },
      h("span", { class: "nom", texte: c.adresse }), c.probleme ? h("span", { class: "souci", "aria-label": "Problème de relève" }) : null)),
      h("a", { href: "#/mail/reglages", "data-cle": "reglages", "aria-current": vue === "reglages" ? "page" : null, class: "reglages" },
        icone("systeme"), h("span", { class: "nom", texte: "Réglages" }))));
  }

  function choisirCompte(id) {
    compte = id;
    voulus = PAR_PAGE;
    chargee = false;
    defile.scrollTop = 0;
    dessiner();
    relire();
  }

  const nomCategorie = (id) => e.categories.find((c) => c.id === id)?.nom || "";
  function ligne(m) {
    const avecCategorie = vueListe === "boite" || vueListe === "non-lus" || recherche.value.trim();
    const quand = quandCourt(m.date);
    return h("li", {}, h("a", {
      class: m.lu ? "ligne-mail" : "ligne-mail non-lu", href: `#/mail/${vueListe}/${m.id}`, "data-cle": m.id,
      "aria-current": m.id === ouvert ? "true" : null,
      "aria-label": `${m.lu ? "" : "Non lu. "}${m.de || m.de_adresse}, ${m.objet}, ${quand}${m.pieces ? ", avec pièce jointe" : ""}`,
    },
    h("span", { class: "de", texte: m.de || m.de_adresse }),
    h("span", { class: "quand", texte: quand }),
    h("span", { class: "objet", texte: m.objet }),
    avecCategorie ? h("span", { class: "cat", texte: nomCategorie(m.categorie) }) : null,
    h("span", { class: "apercu" }, m.pieces ? icone("trombone") : null, h("span", { texte: m.apercu || " " }))));
  }

  function dessinerListe() {
    const c = compte && e.comptes.find((x) => x.id === compte);
    remplacer(filtre, c ? [h("span", { texte: `Seulement ${c.adresse}` }),
      h("button", { type: "button", class: "icone-seule", "aria-label": "Revoir toutes les boîtes", title: "Revoir toutes les boîtes",
        surclick: () => choisirCompte("") }, icone("croix"))] : null);
    filtre.hidden = !c;
    remplacer(alertes, e.comptes.filter((x) => x.probleme).map((x) => h("p", { class: "alerte-ligne", role: "status" },
      `${x.adresse} : ${x.probleme} `,
      h("button", { type: "button", "aria-label": `Réparer ${x.adresse}`, surclick: () => ajouterBoite(x.auth === "microsoft" ? "outlook" : x.genre, ctx, x) }, "Réparer"))));
    const cherche = recherche.value.trim();
    const vide = !chargee ? h("li", { class: "vide", texte: "…" })
      : cherche ? h("li", { class: "vide", texte: `Aucun mail ne correspond à « ${cherche} ».` })
        : vueListe === "boite" ? h("li", { class: "vide", texte: e.releve.en_cours && !e.releve.derniere ? "Première relève en cours…" : "Boîte vide : rien de nouveau." })
          : h("li", { class: "vide", texte: vueListe === "non-lus" ? "Tout est lu." : "Rien ici." });
    garderFocus(liste, () => remplacer(liste, messages.length ? messages.map(ligne) : vide));
    plus.hidden = !suite || !chargee;
  }

  // Le volet de droite : un mail, l'écriture, les réglages, ou rien.
  function afficherPanneau() {
    const genre = vue === "ecrire" ? "ecriture" : vue === "reglages" ? "reglages" : ouvert ? "lecture" : "vide";
    const id = genre === "lecture" ? ouvert : null;
    if (panneau && panneau.genre === genre && panneau.id === id) { panneau.objet?.mettreAJour?.(); return; }
    panneau?.objet?.demonter?.();
    panneau = { genre, id, objet: null };
    lecteur.scrollTop = 0;
    if (genre === "lecture") panneau.objet = monterLecture(lecteur, id, ctx);
    else if (genre === "ecriture") panneau.objet = monterEcriture(lecteur, ctx);
    else if (genre === "reglages") panneau.objet = monterReglages(lecteur, ctx);
    else remplacer(lecteur, h("div", { class: "lecteur-vide" }, icone("mail"), h("p", { texte: "Choisis un mail dans la liste." })));
  }

  // --- navigation ---
  function aller(s) {
    const [a = "", b = ""] = s || [];
    let v = a || "boite", id = null;
    if (v !== "ecrire" && v !== "reglages") {
      const connue = v === "boite" || v === "non-lus" || (e ? e.categories.some((c) => c.id === v) : /^[a-z]{3,20}$/.test(v));
      if (!connue) v = "boite";
      id = /^m[0-9a-f]{8}:[0-9]{1,10}$/.test(decodeURIComponent(b)) ? decodeURIComponent(b) : null;
      if (v !== vueListe) {
        vueListe = v;
        voulus = PAR_PAGE;
        chargee = false;
        defile.scrollTop = 0;
        relire();
      }
    }
    vue = v;
    ouvert = id;
    if (ETROIT.matches) conteneur.scrollTop = 0;
    dessiner();
  }

  let minuterieRecherche = 0;
  recherche.addEventListener("input", () => {
    clearTimeout(minuterieRecherche);
    minuterieRecherche = setTimeout(() => { voulus = PAR_PAGE; chargee = false; defile.scrollTop = 0; dessiner(); relire(); }, 250);
  });
  recherche.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && recherche.value) { ev.preventDefault(); recherche.value = ""; recherche.dispatchEvent(new Event("input")); }
  });
  // flèches haut et bas : d'un mail à l'autre dans la liste
  liste.addEventListener("keydown", (ev) => {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
    const liens = [...liste.querySelectorAll("a.ligne-mail")];
    const i = liens.indexOf(document.activeElement);
    if (i < 0) return;
    ev.preventDefault();
    liens[Math.max(0, Math.min(liens.length - 1, i + (ev.key === "ArrowDown" ? 1 : -1)))].focus();
  });

  // --- vie de la page ---
  const surTaille = () => dessiner();
  ETROIT.addEventListener("change", surTaille);
  const visible = () => {
    if (document.visibilityState !== "visible") return;
    relire();
    if (releveDue()) relever();
  };
  document.addEventListener("visibilitychange", visible);
  const minuteur = setInterval(() => { if (document.visibilityState === "visible" && releveDue()) relever(); }, 30000);
  const oublier = contexte.surChangement((quoi) => { if (quoi === "mail" || !quoi) relire(); });

  aller(contexte.suite);
  await relire();
  if (e && Date.now() - e.releve.derniere * 1000 > 60000) relever();     // à l'ouverture : relève, sauf si toute fraîche
  return {
    aller,
    demonter() {
      clearInterval(minuteur);
      clearTimeout(minuterieRecherche);
      ETROIT.removeEventListener("change", surTaille);
      document.removeEventListener("visibilitychange", visible);
      oublier();
      abonnes.clear();
      panneau?.objet?.demonter?.();
      panneau = null;
    },
  };
}

