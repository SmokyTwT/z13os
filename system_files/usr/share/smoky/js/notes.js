// Smoky — page « Notes » : la bibliothèque des carnets (#/notes, #/notes/favoris,
// #/notes/classeur/<nom>, #/notes/corbeille) et l'éditeur d'un carnet (#/notes/c/<id>).
import { annoncer } from "/js/ui.js";
import { api } from "/js/app.js";
import { monterBibliotheque } from "/js/notes/bibliotheque.js";
import { monterEditeur } from "/js/notes/editeur.js";

// L'éditeur enregistre le carnet en partant : si l'on revient aux Notes avant la fin, on attend
// que ce soit écrit pour ne pas relire une version d'avant.
let fermeture = Promise.resolve();

export async function monter(conteneur, contexte) {
  await fermeture;
  let courant = null;                 // { genre: "bibliotheque" | "editeur", id?, objet }
  let file = Promise.resolve();       // les changements de vue passent un par un (l'éditeur enregistre en partant)
  let prefs = null;

  const lirePrefs = async () => {
    if (!prefs) prefs = (await api.lire("/api/notes")).preferences || {};
    return prefs;
  };
  const enregistrerPrefs = (valeurs) => {
    prefs = valeurs;
    api.envoyer("/api/notes", { action: "preferences", valeurs }).catch(() => {});
  };

  function lire(suite) {
    if (suite[0] === "c" && suite[1]) return { genre: "editeur", id: decodeURIComponent(suite[1]) };
    if (suite[0] === "corbeille") return { genre: "bibliotheque", vue: "corbeille" };
    if (suite[0] === "favoris") return { genre: "bibliotheque", vue: "favoris" };
    if (suite[0] === "classeur" && suite[1]) return { genre: "bibliotheque", vue: "tous", classeur: decodeURIComponent(suite[1]) };
    return { genre: "bibliotheque", vue: "tous", classeur: null };
  }

  async function afficher(suite) {
    const voulu = lire(suite);
    if (courant?.genre === "bibliotheque" && voulu.genre === "bibliotheque") {
      courant.objet.aller(voulu.vue, voulu.classeur);
      return;
    }
    if (courant?.genre === "editeur" && voulu.genre === "editeur" && courant.id === voulu.id) return;
    if (courant) {
      const ancien = courant;
      courant = null;
      await ancien.objet.demonter();
    }
    if (voulu.genre === "editeur") {
      document.title = "Notes — Smoky";
      try {
        const objet = await monterEditeur(conteneur, {
          carnetId: voulu.id, prefs: await lirePrefs(), enregistrerPrefs, contexte,
          surRetour: () => { location.hash = "#/notes"; },
        });
        courant = { genre: "editeur", id: voulu.id, objet };
        document.title = `${objet.carnet.carnet.titre} — Smoky`;
      } catch (e) {
        annoncer(e.message || "Ce carnet ne s'ouvre pas.", { erreur: true });
        location.hash = "#/notes";
      }
      return;
    }
    document.title = "Notes — Smoky";
    courant = { genre: "bibliotheque", objet: monterBibliotheque(conteneur, {
      vue: voulu.vue, classeur: voulu.classeur, contexte,
      surOuvrir: (id) => { location.hash = `#/notes/c/${encodeURIComponent(id)}`; },
    }) };
  }

  const aller = (suite) => { file = file.then(() => afficher(suite)).catch((e) => annoncer(e.message, { erreur: true })); return file; };
  await aller(contexte.suite || []);
  return {
    aller,
    demonter() {
      fermeture = (async () => {
        await file;
        if (courant) { const c = courant; courant = null; await c.objet.demonter(); }
      })().catch((e) => annoncer(e.message || "Le carnet n'a pas pu être enregistré.", { erreur: true }));
      return fermeture;
    },
  };
}
