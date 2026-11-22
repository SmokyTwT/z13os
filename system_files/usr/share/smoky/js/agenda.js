// Smoky — page « Agenda » : la semaine en grille (cours, examens, rendez-vous, échéances Moodle)
// et le planning qui s'y glisse (révisions, salle, repas, courses, tâches). Réglages : #/agenda/reglages.
// Tout ce qui est affiché vient du serveur (smoky/agenda.py) ; la page ne calcule que la mise en page.
import { h, icone, bouton, interrupteur, segment, rangee, annoncer, confirmer } from "/js/ui.js";
import { api, tenter } from "/js/app.js";

const HEURE_PX = 52;                     // hauteur d'une heure dans la grille
const MOIS = new Intl.DateTimeFormat("fr-FR", { month: "long" });
const JOUR_COURT = new Intl.DateTimeFormat("fr-FR", { weekday: "short" });
const JOUR_LONG = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const JOUR_MOYEN = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
const ETROIT = matchMedia("(max-width: 900px)");

// --- petits calculs de dates (heure locale, « AAAA-MM-JJTHH:MM ») ---------------------------------
const dateDe = (iso) => { const [a, m, j] = iso.slice(0, 10).split("-").map(Number); return new Date(a, m - 1, j); };
const minutesDe = (iso) => Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16));
const quantieme = (d) => (d.getDate() === 1 ? "1er" : String(d.getDate()));
export function heureLisible(iso) {                // "08:00" → "8 h", "13:30" → "13 h 30"
  const m = minutesDe(iso);
  return `${Math.floor(m / 60)} h${m % 60 ? ` ${String(m % 60).padStart(2, "0")}` : ""}`;
}
export function duree(min) {
  if (min < 60) return `${min} min`;
  return `${Math.floor(min / 60)} h${min % 60 ? ` ${String(min % 60).padStart(2, "0")}` : ""}`;
}
export function titreSemaine(jours) {
  const a = dateDe(jours[0]), b = dateDe(jours[6]);
  return a.getMonth() === b.getMonth()
    ? `semaine du ${quantieme(a)} au ${quantieme(b)} ${MOIS.format(b)}`
    : `semaine du ${quantieme(a)} ${MOIS.format(a)} au ${quantieme(b)} ${MOIS.format(b)}`;
}
const dansJours = (iso, maintenant) => Math.round((dateDe(iso) - dateDe(maintenant)) / 86400000);
function quandRelatif(iso, maintenant) {
  const n = dansJours(iso, maintenant);
  return n === 0 ? "aujourd'hui" : n === 1 ? "demain" : `dans ${n} jours`;
}

// Couloirs : les éléments qui se chevauchent dans une journée se partagent la largeur.
function couloirs(liste) {
  const place = new Map();
  let groupe = [], fins = [], finGroupe = -1;
  const clore = () => { for (const e of groupe) place.get(e).n = fins.length; groupe = []; fins = []; };
  for (const e of liste) {
    if (e._s >= finGroupe) { clore(); finGroupe = -1; }
    let i = fins.findIndex((f) => f <= e._s);
    if (i < 0) { i = fins.length; fins.push(e._f); } else fins[i] = e._f;
    place.set(e, { i, n: 1 });
    groupe.push(e);
    finGroupe = Math.max(finGroupe, e._f);
  }
  clore();
  return place;
}

export async function monter(conteneur, contexte) {
  let e = null;                 // état de la semaine affichée (serveur)
  let decalage = 0;             // 0 = cette semaine
  let vue = "semaine";          // ou "reglages"
  let jourEtroit = null;        // jour montré sur petit écran (AAAA-MM-JJ)
  let dejaDefile = false;       // la grille a déjà été amenée à l'heure actuelle
  let resultatVu = null;        // dernier résultat de Claude déjà annoncé (null : pas encore lu)
  let relectures = 0;

  // l'en-tête ne se reconstruit pas : le grand titre ne s'anime qu'une fois, à l'ouverture
  const sous = h("p", { class: "sous" });
  const droite = h("div");
  const corps = h("div", { class: "corps" });
  const page = h("div", { class: "agenda" },
    h("header", { class: "entete" }, h("div", {}, h("h1", { texte: "agenda" }), sous), droite), corps);
  conteneur.replaceChildren(page);

  // externe : relecture qui ne vient pas d'une action faite ici (autre fenêtre, lien relu…)
  async function relire({ externe = false } = {}) {
    const numero = ++relectures;
    try {
      const etat = await api.lire(`/api/agenda?semaine=${decalage}`);
      if (numero !== relectures) return;
      e = etat;
      const r = e.claude_travail && e.claude_travail.resultat;
      const quand = r ? r.quand : 0;
      if (resultatVu !== null && quand > resultatVu) annoncer(r.message, { erreur: !r.ok });
      resultatVu = quand;
      if (externe && vue === "reglages" && enEdition()) return;     // pas de nouveau dessin sous tes doigts
      dessiner();
    } catch (err) { if (numero === relectures) annoncer(err.message, { erreur: true }); }
  }

  // un champ « en cours » : sa valeur n'est pas celle dessinée, et elle n'a pas encore été envoyée
  const CHAMPS = "input:not([type=file]), textarea";
  const envoyes = new Set();               // noms des champs dont la valeur vient d'être envoyée
  const enCours = (c) => c.value !== c.defaultValue && !envoyes.has(cleDe(c));
  function enEdition() {
    const a = document.activeElement;
    return !!a && page.contains(a) && a.matches(CHAMPS) && enCours(a);
  }

  async function agir(corps, succes) {
    let reponse = null;
    const ok = await tenter(async () => (reponse = await api.envoyer("/api/agenda", corps)), { succes });
    await relire();
    return ok ? reponse || {} : null;
  }

  function cleDe(x) { return x.getAttribute("aria-label") || x.textContent.trim(); }
  // Tout est redessiné à chaque relecture, sans rien perdre : la place du clavier (et du curseur
  // dans le champ), et ce que tu étais en train d'écrire ailleurs sans l'avoir encore enregistré.
  function dessiner() {
    if (!e) return;
    const actif = document.activeElement;
    const dans = actif && actif !== page && page.contains(actif);
    const cle = dans ? cleDe(actif) : "";
    const curseur = dans && typeof actif.selectionStart === "number" ? [actif.selectionStart, actif.selectionEnd] : null;
    const brouillons = [...page.querySelectorAll(CHAMPS)].filter(enCours).map((c) => [cleDe(c), c.value]);
    envoyes.clear();
    if (vue === "reglages") dessinerReglages(); else dessinerSemaine();
    const champs = [...page.querySelectorAll(CHAMPS)];
    for (const [k, v] of brouillons) { const c = champs.find((x) => cleDe(x) === k); if (c) c.value = v; }
    if (!cle) return;
    const c = [...page.querySelectorAll("button, input, textarea, a")].find((x) => cleDe(x) === cle);
    c?.focus({ preventScroll: true });
    if (c && curseur) { try { c.setSelectionRange(...curseur); } catch { /* champ sans curseur */ } }
  }

  // --- La semaine -------------------------------------------------------------------------------------
  function dessinerSemaine() {
    const aujourdHui = e.maintenant.slice(0, 10);
    if (!jourEtroit || !e.jours.includes(jourEtroit)) jourEtroit = e.jours.includes(aujourdHui) ? aujourdHui : e.jours[0];
    const enCours = e.claude_travail && e.claude_travail.en_cours;

    const navigation = h("div", { class: "nav-semaine", role: "group", "aria-label": "Changer de semaine" },
      h("button", { type: "button", class: "bouton rond", "aria-label": "Semaine précédente", title: "Semaine précédente",
        surclick: () => changerSemaine(decalage - 1) }, icone("gauche")),
      decalage !== 0 ? bouton("Cette semaine", { surClic: () => changerSemaine(0) }) : null,
      h("button", { type: "button", class: "bouton rond", "aria-label": "Semaine suivante", title: "Semaine suivante",
        surclick: () => changerSemaine(decalage + 1) }, icone("droite")));

    const passee = decalage < 0;
    const actions = h("div", { class: "boutons actions" },
      passee ? null : bouton("Planifier ma semaine", { genre: "plein", titre: "Place révisions, salle, repas, courses et tâches dans tes créneaux libres. Ce que tu as ajouté toi-même ne bouge pas.",
        surClic: () => agir({ action: "planifier", semaine: decalage }) }),
      e.claude && !passee ? h("button", { type: "button", class: "bouton", disabled: enCours,
        title: "Claude organise la semaine avec ton compte Claude. Il reçoit seulement ta semaine (cours, tâches, réglages).",
        surclick: () => agir({ action: "planifier", semaine: decalage, claude: true }) }, enCours ? "Claude organise ta semaine…" : "Avec Claude") : null,
      bouton("Ajouter", { surClic: () => ajouter() }),
      h("a", { class: "bouton", href: "#/agenda/reglages" }, "Réglages"));

    sous.textContent = titreSemaine(e.jours);
    droite.replaceChildren(navigation);
    corps.className = "corps large";
    // replaceChildren écrirait « null » en toutes lettres : on ne garde que les blocs présents
    corps.replaceChildren(...[actions, bandeauEmploiDuTemps(), blocExamens(), grille(aujourdHui), legende(), blocACaser()].filter(Boolean));
    if (!dejaDefile && decalage === 0) {         // première ouverture : l'heure actuelle doit être visible
      dejaDefile = true;
      const ligne = page.querySelector(".maintenant");
      if (ligne) requestAnimationFrame(() => { if (ligne.getBoundingClientRect().bottom > innerHeight - 40) ligne.scrollIntoView({ block: "center" }); });
    }
  }

  function changerSemaine(n) {
    decalage = Math.max(-60, Math.min(60, n));
    jourEtroit = null;
    relire();
  }

  function bandeauEmploiDuTemps() {
    const t = e.edt;
    if (t.cours || t.lien) {
      return t.erreur ? h("p", { class: "alerte-ligne", role: "status" }, `Emploi du temps : ${t.erreur}. `,
        h("a", { href: "#/agenda/reglages", texte: "Vérifier le lien" })) : null;
    }
    return h("section", { class: "invitation", "aria-labelledby": "t-edt" },
      h("h2", { id: "t-edt", texte: "ton emploi du temps" }),
      h("p", { class: "secondaire" }, "Sur l'ENT, ouvre l'emploi du temps (ADE) et exporte-le en fichier .ics : il apparaît ici tout seul dès qu'il arrive dans Téléchargements. Tu peux aussi coller le lien iCal dans les réglages : les cours se mettent alors à jour d'eux-mêmes."),
      h("div", { class: "boutons" },
        boutonImport("Importer un fichier .ics"),
        h("a", { class: "bouton", href: "#/agenda/reglages" }, "Coller le lien"),
        t.ancien ? bouton("Reprendre celui de l'ancien Agenda", { genre: "plein", surClic: () => agir({ action: "reprendre_ancien" }) }) : null));
  }

  function boutonImport(texte) {
    const fichier = h("input", { type: "file", accept: ".ics,text/calendar", hidden: true });
    fichier.addEventListener("change", async () => {
      const f = fichier.files[0];
      fichier.value = "";
      if (!f) return;
      if (f.size > 5 * 1024 * 1024) { annoncer("Ce fichier est trop gros pour un emploi du temps (5 Mo au plus).", { erreur: true }); return; }
      agir({ action: "importer", contenu: await f.text() });
    });
    return h("span", {}, fichier, bouton(texte, { surClic: () => fichier.click() }));
  }

  function blocExamens() {
    const proches = e.examens.filter((x) => dansJours(x.debut, e.maintenant) <= 21);
    if (!proches.length) return null;
    return h("section", { class: "examens", "aria-labelledby": "t-examens" },
      h("h2", { id: "t-examens", texte: "examens" }),
      h("ul", {}, proches.map((x) => {
        const b = e.bilan.find((y) => y.examen === x.id);
        const quand = `${JOUR_LONG.format(dateDe(x.debut))}${x.journee ? "" : `, ${heureLisible(x.debut)}`}`;
        return h("li", {},
          h("div", { class: "quoi" }, h("span", { class: "nom", texte: x.titre }),
            h("span", { class: "secondaire", texte: `${quand}${x.lieu ? `, ${x.lieu}` : ""}` })),
          h("span", { class: "dans", texte: quandRelatif(x.debut, e.maintenant) }),
          b && b.prevues ? revise(b) : h("span", { class: "discret petit", texte: b ? "Aucune révision prévue pour l'instant." : "" }));
      })));
  }

  function revise(b) {
    const barre = h("i");
    barre.style.width = `${Math.min(100, Math.round((100 * b.faites) / b.prevues))}%`;
    return h("div", { class: "revise" },
      h("span", { class: "secondaire", texte: `${duree(b.faites)} révisées sur ${duree(b.prevues)} prévues` }),
      h("div", { class: "jauge", "aria-hidden": "true" }, barre),
      b.manquees ? h("span", { class: "discret petit", texte: `${duree(b.manquees)} manquées` }) : null);
  }

  function grille(aujourdHui) {
    const r = e.reglages;
    const parJour = new Map(e.jours.map((j) => [j, []]));
    const journees = new Map(e.jours.map((j) => [j, []]));
    let debutGrille = Math.max(0, Math.floor(Number(r.reveil.slice(0, 2))) * 60 - 60);
    let finGrille = Math.min(24 * 60, Math.ceil((Number(r.coucher.slice(0, 2)) * 60 + Number(r.coucher.slice(3))) / 60) * 60);
    for (const x of e.elements) {
      for (const j of e.jours) {
        const s0 = `${j}T00:00`, s1 = `${j}T24:00`;
        if (x.fin <= s0 || x.debut >= s1) continue;
        if (x.journee) { journees.get(j).push(x); continue; }
        const s = x.debut < s0 ? 0 : minutesDe(x.debut), f = x.fin > s1 || x.fin.slice(0, 10) > j ? 24 * 60 : minutesDe(x.fin);
        parJour.get(j).push({ ...x, _s: s, _f: Math.max(f, s + 15) });
        debutGrille = Math.min(debutGrille, Math.floor(s / 60) * 60);
        finGrille = Math.max(finGrille, Math.ceil(f / 60) * 60);
      }
    }
    const px = HEURE_PX / 60;
    const hauteur = (finGrille - debutGrille) * px;
    const etroit = ETROIT.matches;
    const vus = etroit ? [jourEtroit] : e.jours;          // petit écran : un jour à la fois

    const tete = h("div", { class: "tete-jours" }, etroit ? null : h("span"),
      e.jours.map((j) => {
        const contenu = [h("span", { class: "nom-jour", texte: JOUR_COURT.format(dateDe(j)).replace(".", "") }),
          h("span", { class: "num-jour", texte: String(dateDe(j).getDate()) })];
        const commun = { class: "jour-tete", "data-jour": j, "aria-current": j === aujourdHui ? "date" : null };
        return etroit
          ? h("button", { ...commun, type: "button", "aria-pressed": String(j === jourEtroit), "aria-label": JOUR_LONG.format(dateDe(j)),
            surclick: () => { jourEtroit = j; dessiner(); } }, contenu)
          : h("div", commun, contenu);
      }));

    const avecJournees = vus.some((j) => journees.get(j).length);
    const ligneJournees = avecJournees ? h("div", { class: "journees" }, h("span", { class: "discret petit", texte: "journée" }),
      vus.map((j) => h("div", { class: "jour-col", "data-jour": j }, journees.get(j).map((x) => element(x))))) : null;

    const heures = h("div", { class: "heures", style: null });
    heures.style.height = `${hauteur}px`;
    for (let m = debutGrille; m < finGrille; m += 60) {
      const repere = h("span", { texte: `${m / 60} h` });
      repere.style.top = `${(m - debutGrille) * px}px`;
      heures.append(repere);
    }
    const colonnes = vus.map((j) => {
      const col = h("div", { class: "colonne jour-col", "data-jour": j, "aria-label": JOUR_LONG.format(dateDe(j)), role: "group" });
      col.style.height = `${hauteur}px`;
      if (j === aujourdHui) col.classList.add("aujourdhui");
      const liste = parJour.get(j).sort((a, b) => a._s - b._s || b._f - a._f);
      const place = couloirs(liste);
      for (const x of liste) {
        const { i, n } = place.get(x);
        const b = element(x);
        b.style.top = `${(x._s - debutGrille) * px}px`;
        b.style.height = `${Math.max(20, (x._f - x._s) * px - 2)}px`;
        b.style.left = `calc(${(100 * i) / n}% + 2px)`;
        b.style.width = `calc(${100 / n}% - 4px)`;
        if ((x._f - x._s) * px < 38) b.classList.add("court");
        col.append(b);
      }
      if (j === aujourdHui) {
        const m = minutesDe(e.maintenant);
        if (m >= debutGrille && m <= finGrille) {
          const ligne = h("div", { class: "maintenant", "aria-hidden": "true" });
          ligne.style.top = `${(m - debutGrille) * px}px`;
          col.append(ligne);
        }
      }
      // toucher un créneau vide : ajouter à ce moment-là
      col.addEventListener("click", (ev) => {
        if (ev.target !== col) return;
        const minute = Math.min(finGrille - 60, Math.max(debutGrille, Math.round((debutGrille + ev.offsetY / px) / 30) * 30));
        const hh = (x) => `${String(Math.floor(x / 60)).padStart(2, "0")}:${String(x % 60).padStart(2, "0")}`;
        ajouter({ jour: j, debut: hh(minute), fin: hh(Math.min(minute + 60, 23 * 60 + 59)) });
      });
      return col;
    });
    const zone = h("div", { class: etroit ? "semaine un-jour" : "semaine" },
      tete, ligneJournees, h("div", { class: "corps-grille" }, heures, colonnes));
    zone.style.setProperty("--heure", `${HEURE_PX}px`);
    return zone;
  }

  const LIBELLES = () => e.genres;
  function element(x) {
    const genre = LIBELLES()[x.genre] || "";
    const titre = x.genre === "devoir" ? `À rendre : ${x.titre}` : x.titre;
    const horaire = x.journee ? "toute la journée" : `${heureLisible(x.debut)} à ${heureLisible(x.fin)}`;
    const b = h("button", { type: "button", class: `element ${x.genre} ${x.fait ? "fait" : ""} ${x.source === "plan" ? "planifie" : ""}`.trim(),
      "aria-label": `${genre}, ${x.titre}, ${JOUR_LONG.format(dateDe(x.debut))}, ${horaire}${x.lieu ? `, ${x.lieu}` : ""}${x.fait ? ", fait" : ""}`,
      surclick: (ev) => { ev.stopPropagation(); detail(x); } },
      h("span", { class: "t", texte: titre }),
      x.journee ? null : h("span", { class: "h", texte: `${x.debut.slice(11, 16)}${x.lieu ? `  ${x.lieu}` : ""}` }));
    return b;
  }

  function legende() {
    return h("p", { class: "legende", "aria-hidden": "true" },
      [["cours", "cours"], ["examen", "examen"], ["perso", "rendez-vous"], ["devoir", "à rendre"], ["revision", "planifié par le PC"], ["fait", "fait"]]
        .map(([c, t]) => h("span", {}, h("i", { class: `pastille ${c}` }), t)));
  }

  function blocACaser() {
    if (!e.a_caser.length) return null;
    return h("section", { class: "a-caser", "aria-labelledby": "t-caser" },
      h("h2", { id: "t-caser", texte: "à caser" }),
      h("ul", {}, e.a_caser.map((t) => h("li", {},
        h("span", { class: "nom", texte: t.titre }),
        h("span", { class: "secondaire", texte: `${duree(t.minutes)}${t.echeance ? `, avant ${JOUR_MOYEN.format(dateDe(t.echeance))}` : ""}` }),
        h("span", { class: t.creneau ? "secondaire" : "discret", texte: t.creneau ? `casée ${JOUR_LONG.format(dateDe(t.creneau))} à ${heureLisible(t.creneau)}` : "pas encore casée" })))));
  }

  // --- Détail d'un élément ------------------------------------------------------------------------------
  function detail(x) {
    const genre = e.genres[x.genre] || "";
    const d = h("dialog", { class: "detail", "aria-labelledby": "d-titre" });
    const fermer = () => { d.close(); d.remove(); };   // retiré tout de suite : pas de menu fermé qui traîne
    const minutes = (minutesDe(x.fin) - minutesDe(x.debut) + 1440) % 1440 || 60;
    const boutons = [];
    if (x.source === "plan") {
      boutons.push(bouton(x.fait ? "Remettre à faire" : "C'est fait", { genre: x.fait ? "" : "plein",
        surClic: async () => { fermer(); await agir({ action: "basculer", id: x.id }); } }));
    }
    if (x.genre === "revision" && !x.fait && x.fin > e.maintenant) {
      const m = Math.max(5, Math.min(minutes, 240));
      boutons.push(bouton(`Concentration ${m} min`, { titre: "Bloque les sites qui distraient pendant ce temps.",
        surClic: async () => { fermer(); await tenter(() => api.envoyer("/api/systeme", { action: "concentration_debut", minutes: m }),
          { succes: "Concentration lancée : les sites qui distraient sont bloqués." }); } }));
    }
    if (x.matiere && e.reglages.matieres.includes(x.matiere)) {
      boutons.push(bouton(`Ouvrir les notes de ${x.matiere}`, { surClic: () => { fermer(); location.hash = `#/notes/classeur/${encodeURIComponent(x.matiere)}`; } }));
    }
    if (x.source === "plan" || x.source === "toi") {
      boutons.push(bouton("Retirer", { genre: "braise", surClic: async () => {
        fermer();
        if (await confirmer({ titre: `Retirer « ${x.titre} » ?`, texte: x.source === "toi" ? "Il disparaît de ton agenda." : "Le prochain « Planifier » pourra remettre un bloc à cet endroit.", oui: "Retirer", danger: true })) {
          agir({ action: "supprimer", id: x.id });
        }
      } }));
    }
    boutons.push(bouton("Fermer", { surClic: fermer }));
    d.append(...[                         // append écrirait « null » en toutes lettres : on filtre
      h("p", { class: "genre", texte: x.genre === "devoir" ? "À rendre sur Moodle" : genre }),
      h("h2", { id: "d-titre", class: "titre-libre", texte: x.titre }),
      h("p", { class: "quand", texte: `${JOUR_LONG.format(dateDe(x.debut))}, ${x.journee ? "toute la journée" : `de ${heureLisible(x.debut)} à ${heureLisible(x.fin)}`}` }),
      x.lieu ? h("p", { class: "lieu", texte: x.lieu }) : null,
      x.genre === "salle" ? carnetSalle(x, fermer) : x.notes ? h("p", { class: "notes", texte: x.notes }) : null,
      x.source === "edt" ? h("p", { class: "discret petit", texte: "Vient de ton emploi du temps." }) : null,
      x.source === "moodle" ? h("p", { class: "discret petit", texte: "Échéance relevée par Smoky Moodle." }) : null,
      h("div", { class: "boutons" }, boutons)].filter(Boolean));
    d.addEventListener("close", () => d.remove());
    document.body.append(d);
    d.showModal();
  }

  function carnetSalle(x, fermer) {
    const exercices = (x.notes || "").split("\n").map((l) => l.trim()).filter(Boolean);
    if (!exercices.length) return null;
    const lignes = exercices.map((ex) => {
      const dernier = e.charges[ex];
      const kg = h("input", { class: "champ court", type: "number", min: "0", max: "500", step: "0.5", inputmode: "decimal", "aria-label": `${ex} : charge en kilos`, value: dernier ? String(dernier.kg) : "" });
      const reps = h("input", { class: "champ court", type: "number", min: "1", max: "100", step: "1", inputmode: "numeric", "aria-label": `${ex} : répétitions`, value: dernier ? String(dernier.reps) : "" });
      return { ex, kg, reps, ligne: h("div", { class: "exercice" }, h("span", { class: "nom", texte: ex }), kg, h("span", { class: "discret", texte: "kg" }), reps, h("span", { class: "discret", texte: "reps" })) };
    });
    return h("div", { class: "salle" },
      h("p", { class: "discret petit", texte: "Charges de la dernière fois, à corriger si besoin." }),
      lignes.map((l) => l.ligne),
      h("div", { class: "boutons" }, bouton("Noter la séance", { surClic: async () => {
        const entrees = lignes.filter((l) => l.kg.value !== "" && l.reps.value !== "")
          .map((l) => ({ exercice: l.ex, kg: Number(l.kg.value), reps: Number(l.reps.value) }));
        if (!entrees.length) { annoncer("Remplis au moins un exercice.", { erreur: true }); return; }
        if (await agir({ action: "seance", id: x.id, entrees })) fermer();
      } })));
  }

  // --- Ajouter -------------------------------------------------------------------------------------------
  function ajouter(prerempli = {}) {
    const jourDefaut = prerempli.jour || (e.jours.includes(e.maintenant.slice(0, 10)) ? e.maintenant.slice(0, 10) : e.jours[0]);
    let genre = prerempli.genre || "perso";
    const d = h("dialog", { class: "ajout-agenda", "aria-labelledby": "a-titre" });
    const champs = h("div", { class: "champs" });
    const titre = h("input", { class: "champ", type: "text", maxlength: "120", autocomplete: "off" });
    const lieu = h("input", { class: "champ", type: "text", maxlength: "120", autocomplete: "off" });
    const jour = h("input", { class: "champ", type: "date", value: jourDefaut });
    const debut = h("input", { class: "champ", type: "time", value: prerempli.debut || "18:00" });
    const fin = h("input", { class: "champ", type: "time", value: prerempli.fin || "19:00" });
    const matiere = h("select", { class: "champ" }, e.reglages.matieres.map((m) => h("option", { value: m, texte: m })));
    const minutes = h("input", { class: "champ court", type: "number", min: "10", max: "480", step: "5", value: "60", inputmode: "numeric" });
    const avant = h("input", { class: "champ", type: "date" });
    const etiquette = (texte, champ) => h("label", {}, h("span", { texte }), champ);

    // un même champ ne peut être qu'à un endroit : on ne construit que les étiquettes du genre choisi
    function remplir() {
      const quand = () => [etiquette("Jour", jour), etiquette("Début", debut), etiquette("Fin", fin)];
      champs.replaceChildren(...{
        perso: () => [etiquette("Quoi", titre), ...quand(), etiquette("Où (facultatif)", lieu)],
        revision: () => [etiquette("Matière", matiere), ...quand()],
        examen: () => [etiquette("Intitulé", titre), ...quand(), etiquette("Salle (facultatif)", lieu)],
        tache: () => [etiquette("Quoi", titre), etiquette("Durée en minutes", minutes), etiquette("À faire avant le (facultatif)", avant),
          h("p", { class: "discret petit", texte: "Elle sera casée dans un créneau libre au prochain « Planifier ma semaine », et apparaît aussi dans Aujourd'hui." })],
      }[genre]());
      titre.placeholder = { perso: "Dentiste, réunion de projet…", examen: "Examen de BDR", tache: "Préparer l'exposé d'anglais" }[genre] || "";
    }
    const choix = segment({ options: [["perso", "Rendez-vous"], ["revision", "Révision"], ["examen", "Examen"], ["tache", "Tâche à caser"]],
      valeur: genre, nom: "Que veux-tu ajouter ?", surChange: (v) => { genre = v; remplir(); } });
    remplir();
    const formulaire = h("form", { method: "dialog" },
      h("h2", { id: "a-titre", texte: "ajouter" }), choix, champs,
      h("div", { class: "boutons" }, bouton("Annuler", { surClic: () => d.close() }), h("button", { type: "submit", class: "bouton plein" }, "Ajouter")));
    formulaire.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const corps = genre === "tache"
        ? { action: "ajouter", genre, titre: titre.value, minutes: Number(minutes.value), echeance: avant.value || null }
        : { action: "ajouter", genre, titre: titre.value, lieu: lieu.value, matiere: matiere.value, jour: jour.value, debut: debut.value, fin: fin.value };
      if (genre !== "revision" && !titre.value.trim()) { titre.focus(); return; }
      if (await agir(corps)) d.close();
    });
    d.append(formulaire);
    d.addEventListener("close", () => d.remove());
    document.body.append(d);
    d.showModal();
    (genre === "revision" ? matiere : titre).focus();
  }

  // --- Réglages de l'agenda ------------------------------------------------------------------------------
  function dessinerReglages() {
    const r = e.reglages, t = e.edt;
    // champ : celui dont la valeur part (au prochain dessin, il montre ce que le serveur a retenu)
    const regler = (valeurs, succes, champ) => { if (champ) envoyes.add(cleDe(champ)); return agir({ action: "regler", valeurs }, succes); };
    const heure = (cle, nom, aide) => {
      const c = h("input", { class: "champ", type: "time", value: r[cle], "aria-label": nom });
      c.addEventListener("change", () => { if (c.value) regler({ [cle]: c.value }, undefined, c); });
      return rangee(nom, aide, c);
    };
    const nombre = (cle, nom, aide, unite, min, max) => {
      const c = h("input", { class: "champ court", type: "number", min: String(min), max: String(max), value: String(r[cle]), inputmode: "numeric", "aria-label": nom });
      c.addEventListener("change", () => { const v = Number(c.value); if (Number.isInteger(v)) regler({ [cle]: v }, undefined, c); });
      return rangee(nom, aide, c, unite ? h("span", { class: "discret", texte: unite }) : null);
    };

    const lien = h("input", { class: "champ", type: "url", value: r.lien, placeholder: "https://…", autocomplete: "off", spellcheck: "false", "aria-label": "Lien iCal de l'emploi du temps" });
    const etatEdt = t.erreur ? `Lien illisible : ${t.erreur}.` : t.cours ? `${t.cours} cours connus${t.lien ? ", relus toutes les 6 heures" : ""}.` : "Aucun cours pour l'instant.";
    const matieres = h("input", { class: "champ", type: "text", value: r.matieres.join(", "), "aria-label": "Matières", spellcheck: "false" });
    matieres.addEventListener("change", () => regler({ matieres: matieres.value.split(",").map((x) => x.trim()).filter(Boolean) }, undefined, matieres));
    const programme = h("textarea", { class: "champ zone", rows: "10", spellcheck: "false", "aria-label": "Programme de salle",
      texte: r.programme || e.programme_defaut });      // texte de départ = valeur dessinée (defaultValue)
    programme.addEventListener("change", () => regler({ programme: programme.value }, "Programme enregistré.", programme));
    const jours = e.noms_jours.map((n, i) => [i, n[0].toUpperCase() + n.slice(1, 3)]);

    sous.textContent = "réglages";
    droite.replaceChildren(h("a", { class: "bouton", href: "#/agenda" }, "Revenir à la semaine"));
    corps.className = "corps reglages-agenda";
    corps.replaceChildren(
        h("section", { class: "section" }, h("h2", { texte: "emploi du temps" }),
          h("p", { class: "intro", texte: "Sur l'ENT : Emploi du temps (ADE), puis exporter l'agenda. Copie le lien iCal ici, ou importe le fichier .ics (un fichier plus récent dans Téléchargements est repris tout seul)." }),
          h("div", { class: "groupe" },
            rangee("Lien iCal", etatEdt, lien, bouton("Enregistrer", { surClic: () => regler({ lien: lien.value.trim() }, undefined, lien) })),
            rangee("Fichier .ics", t.fichier ? "Un fichier est importé." : "Aucun fichier importé.", boutonImport(t.fichier ? "Remplacer le fichier" : "Importer un fichier"),
              t.fichier ? bouton("Retirer", { surClic: () => agir({ action: "retirer_fichier" }) }) : null),
            rangee("Relire maintenant", "Reprend le lien et regarde dans Téléchargements.", bouton("Relire", { surClic: () => agir({ action: "actualiser" }) })),
            t.ancien ? rangee("Ancien Agenda", "Reprendre le lien et le fichier de l'ancien Smoky Agenda.", bouton("Reprendre", { surClic: () => agir({ action: "reprendre_ancien" }) })) : null)),
        h("section", { class: "section" }, h("h2", { texte: "ta journée" }),
          h("div", { class: "groupe" },
            heure("reveil", "Réveil", "Rien n'est planifié avant."), heure("coucher", "Coucher", "Ni après."),
            heure("dejeuner", "Déjeuner"), heure("diner", "Dîner"),
            nombre("repas_min", "Durée d'un repas", null, "min", 15, 120),
            nombre("trajet_min", "Trajet avant et après les cours", "Temps laissé libre autour des cours et des examens.", "min", 0, 120))),
        h("section", { class: "section" }, h("h2", { texte: "révisions" }),
          h("div", { class: "groupe" },
            nombre("revision_semaine_min", "En semaine", "Par jour. Moitié plus la semaine d'un examen.", "min", 0, 600),
            nombre("revision_weekend_min", "Le week-end", "Par jour.", "min", 0, 600),
            nombre("bloc_min", "Durée d'un bloc", "Suivi de 10 minutes de pause.", "min", 20, 120),
            rangee("Matières", "Séparées par des virgules. Les examens qui approchent passent en premier.", matieres))),
        h("section", { class: "section" }, h("h2", { texte: "salle de sport" }),
          h("div", { class: "groupe" },
            nombre("salle_par_semaine", "Séances par semaine", "Jamais deux jours de suite, si possible pas un jour d'examen.", null, 0, 7),
            nombre("salle_min", "Durée d'une séance", null, "min", 30, 240),
            heure("salle_des", "Pas avant"), heure("salle_avant", "Finie avant"),
            rangee("Programme", "Une séance par paragraphe : la première ligne est son nom, puis un exercice par ligne. Les séances se suivent d'une semaine à l'autre.", programme))),
        h("section", { class: "section" }, h("h2", { texte: "courses" }),
          h("div", { class: "groupe" },
            rangee("Jour", null, segment({ options: jours, valeur: r.courses_jour, nom: "Jour des courses", surChange: (v) => regler({ courses_jour: v }) })),
            heure("courses_heure", "Heure idéale"),
            nombre("courses_min", "Durée", null, "min", 15, 240))),
        h("section", { class: "section" }, h("h2", { texte: "rappels" }),
          h("div", { class: "groupe" },
            rangee("Rappels", "Une notification avant chaque cours, examen et bloc du planning.",
              interrupteur({ coche: r.rappels, nom: "Rappels", surChange: (v) => regler({ rappels: v }) })),
            nombre("rappel_avant", "Combien de temps avant", null, "min", 0, 120),
            rangee("Ménage pendant les cours", "Le robot part 10 minutes après le début du premier cours d'une heure ou plus de la journée (Smoky Home).",
              interrupteur({ coche: r.menage_pendant_cours, nom: "Ménage pendant les cours", surChange: (v) => regler({ menage_pendant_cours: v }) })))),
        h("section", { class: "section" }, h("h2", { texte: "claude" }),
          h("p", { class: "intro", texte: e.claude ? "Claude est connecté : le bouton « Avec Claude » organise ta semaine avec ton compte. Il reçoit seulement la semaine à organiser." : "Pour planifier avec Claude, connecte d'abord ton compte Claude dans Smoky Mail (Réglages)." }),
          h("div", { class: "groupe" },
            rangee("Modèle", null, segment({ options: Object.entries(e.modeles).map(([k, v]) => [k, v.split(" (")[0]]), valeur: r.modele, nom: "Modèle de Claude",
              surChange: (v) => regler({ modele: v }) })))));
  }

  // --- Vie de la page -----------------------------------------------------------------------------------
  function aller(suite) {
    vue = suite[0] === "reglages" ? "reglages" : "semaine";
    document.title = vue === "reglages" ? "Réglages de l'agenda — Smoky" : "Agenda — Smoky";
    page.parentElement && (page.parentElement.scrollTop = 0);
    dessiner();
  }
  const surTaille = () => dessiner();
  ETROIT.addEventListener("change", surTaille);
  const visible = () => { if (document.visibilityState === "visible") relire({ externe: true }); };
  document.addEventListener("visibilitychange", visible);
  // chaque minute : la ligne de l'heure avance, l'emploi du temps relu en arrière-plan apparaît
  const minute = setInterval(() => { if (document.visibilityState === "visible" && vue === "semaine") relire({ externe: true }); }, 60000);
  const oublier = contexte.surChangement((quoi) => { if (quoi === "agenda" || quoi === "taches" || !quoi) relire({ externe: true }); });
  vue = contexte.suite && contexte.suite[0] === "reglages" ? "reglages" : "semaine";
  await relire();
  return {
    aller,
    demonter() { ETROIT.removeEventListener("change", surTaille); document.removeEventListener("visibilitychange", visible); clearInterval(minute); oublier(); },
  };
}

export const _essais = { couloirs };    // pour les essais de la page
