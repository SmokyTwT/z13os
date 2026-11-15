// Smoky — page « Aujourd'hui » : ce qu'il y a à faire, l'état du PC, et les outils pas encore refaits.
import { h, icone, bouton, annoncer, confirmer, dateLongue, echeance } from "/js/ui.js";
import { api, tenter, ouvrirAncienne } from "/js/app.js";

const ETATS = { Charging: "en charge", Discharging: "sur batterie", Full: "pleine", "Not charging": "branchée, charge en pause" };

export async function monter(conteneur, contexte) {
  let taches = [];
  let systeme = {};
  let montrerFaites = false;
  // Une liste relue au serveur ne doit jamais effacer une tâche ajoutée pendant le trajet :
  // on compte les relectures lancées et les changements faits ici.
  let relectures = 0;
  let changements = 0;

  const liste = h("ul", { class: "taches", "aria-label": "À faire" });
  const faites = h("ul", { class: "taches", "aria-label": "Fait" });
  const bascule = h("button", { type: "button", class: "bascule", surclick: () => { montrerFaites = !montrerFaites; dessinerTaches(); } });
  const titre = h("input", { class: "champ", type: "text", maxlength: "200", placeholder: "Ajouter une tâche", "aria-label": "Nouvelle tâche", autocomplete: "off" });
  const date = h("input", { class: "champ", type: "date", "aria-label": "Date limite (facultatif)", title: "Date limite (facultatif)" });
  const formulaire = h("form", { class: "ajout" }, titre, date, h("button", { type: "submit", class: "bouton plein" }, "Ajouter"));
  const pc = h("div", { class: "liste" });

  formulaire.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!titre.value.trim()) { titre.focus(); return; }
    const ok = await tenter(async () => { taches.push(await api.envoyer("/api/taches", { titre: titre.value, echeance: date.value || null })); changements++; });
    if (ok) { titre.value = ""; date.value = ""; trier(); dessinerTaches(); titre.focus(); }
  });

  function trier() {
    const cle = (t) => [t.faite ? 1 : 0, t.echeance ? 0 : 1, t.echeance || "", t.id];
    taches.sort((a, b) => { const x = cle(a), y = cle(b); for (let i = 0; i < x.length; i++) { if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; } return 0; });
  }

  function ligne(t) {
    const quand = t.echeance ? echeance(t.echeance) : null;
    return h("li", { class: t.faite ? "faite" : "" },
      h("button", { type: "button", class: "coche", role: "checkbox", "aria-checked": String(t.faite), "aria-label": t.faite ? `Remettre « ${t.titre} » à faire` : `Marquer « ${t.titre} » comme fait`,
        surclick: async () => {
          const ok = await tenter(async () => { Object.assign(t, await api.envoyer(`/api/taches/${t.id}`, { faite: !t.faite })); changements++; });
          if (ok) { trier(); dessinerTaches(); }
        } }, icone("coche")),
      h("span", { class: "titre", texte: t.titre }),
      quand && !t.faite ? h("span", { class: quand.retard ? "quand retard" : "quand", texte: quand.retard ? `en retard, ${quand.texte}` : quand.texte }) : null,
      h("button", { type: "button", class: "oter", "aria-label": `Supprimer « ${t.titre} »`, title: "Supprimer",
        surclick: async () => {
          const ok = await tenter(async () => { await api.supprimer(`/api/taches/${t.id}`); changements++; }, { succes: "Tâche supprimée." });
          if (ok) { taches = taches.filter((x) => x !== t); dessinerTaches(); }
        } }, icone("croix")));
  }

  function dessinerTaches() {
    const ouvertes = taches.filter((t) => !t.faite), terminees = taches.filter((t) => t.faite);
    liste.replaceChildren(...(ouvertes.length ? ouvertes.map(ligne)
      : [h("li", { class: "vide", texte: terminees.length ? "Tout est fait." : "Rien de noté. Écris ta première tâche au-dessus : un devoir à rendre, une révision, une course." })]));
    bascule.hidden = !terminees.length;
    bascule.textContent = montrerFaites ? "Masquer ce qui est fait" : `Voir ce qui est fait (${terminees.length})`;
    faites.hidden = !montrerFaites || !terminees.length;
    faites.replaceChildren(...terminees.map(ligne));
  }

  function dessinerPc() {
    const lignes = [];
    if (systeme.niveau) lignes.push(h("div", {}, h("span", { texte: "Batterie" }), h("span", { class: "secondaire", texte: `${systeme.niveau} %, ${ETATS[systeme.etat] || systeme.etat}` })));
    if (systeme.maj_prete) {
      lignes.push(h("div", {}, h("span", { texte: "Mise à jour prête" }), bouton("Redémarrer", { genre: "plein", surClic: async () => {
        if (await confirmer({ titre: "Redémarrer maintenant ?", texte: "La mise à jour s'applique au redémarrage. Enregistre ton travail avant.", oui: "Redémarrer" })) {
          tenter(() => api.envoyer("/api/systeme", { action: "redemarrer" }));
        }
      } })));
    }
    lignes.push(h("button", { type: "button", surclick: () => { location.hash = "#/systeme"; } }, h("span", { texte: "Tous les réglages du PC" }), icone("systeme")));
    pc.replaceChildren(...lignes);
  }

  async function charger() {
    const numero = ++relectures, avant = changements;
    try {
      const r = await api.lire("/api/aujourdhui");
      if (numero !== relectures) return;                 // une relecture plus récente est partie
      if (avant !== changements) { charger(); return; }  // la liste a changé ici entre-temps : on relit
      taches = r.taches; systeme = r.systeme;
      dessinerTaches(); dessinerPc();
    } catch (e) { if (numero === relectures) annoncer(e.message, { erreur: true }); }
  }

  const anciennes = [["notes", "Notes"], ["agenda", "Agenda"], ["mail", "Mail"], ["maison", "Maison"]];
  conteneur.replaceChildren(
    h("header", { class: "entete" }, h("h1", { texte: "aujourd'hui" }), h("p", { class: "sous", texte: dateLongue() })),
    h("div", { class: "corps deux" },
      h("section", { "aria-labelledby": "t-faire" }, h("h2", { id: "t-faire", texte: "à faire" }), formulaire, liste, bascule, faites),
      h("aside", { class: "cote" },
        h("section", {}, h("h2", { texte: "l'ordinateur" }), pc),
        h("section", {}, h("h2", { texte: "bientôt ici" }),
          h("p", { class: "discret petit", texte: "Notes, Agenda, Mail et Maison sont en train d'être refaits dans Smoky. D'ici là, chaque ancienne appli s'ouvre dans sa propre fenêtre." }),
          h("div", { class: "liste" }, anciennes.map(([id, nom]) =>
            h("button", { type: "button", surclick: () => ouvrirAncienne(id) }, h("span", { texte: `Ouvrir ${nom}` }), icone("dehors"))))))));

  const visible = () => { if (document.visibilityState === "visible") charger(); };
  document.addEventListener("visibilitychange", visible);
  // tâches changées dans une autre fenêtre, ou état du PC changé (mise à jour prête…)
  const oublier = contexte.surChangement((quoi) => { if (quoi === "taches" || quoi === "systeme" || !quoi) charger(); });
  await charger();
  return { demonter() { document.removeEventListener("visibilitychange", visible); oublier(); } };
}
