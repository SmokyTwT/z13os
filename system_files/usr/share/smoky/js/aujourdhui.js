// Smoky — page « Aujourd'hui » : ce qu'il y a à faire, ta journée (agenda), l'état du PC, et les
// outils pas encore refaits.
import { h, icone, bouton, annoncer, confirmer, dateLongue, echeance } from "/js/ui.js";
import { api, tenter, ouvrirAncienne } from "/js/app.js";

const ETATS = { Charging: "en charge", Discharging: "sur batterie", Full: "pleine", "Not charging": "branchée, charge en pause" };

export async function monter(conteneur, contexte) {
  let taches = [];
  let systeme = {};
  let journee = [];             // ce que l'agenda prévoit aujourd'hui
  let maintenant = "";          // heure du PC, « AAAA-MM-JJTHH:MM »
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
  const jour = h("div", { class: "liste journee" });

  formulaire.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!titre.value.trim()) { titre.focus(); return; }
    const ok = await tenter(async () => { garder(await api.envoyer("/api/taches", { titre: titre.value, echeance: date.value || null })); changements++; });
    if (ok) { titre.value = ""; date.value = ""; trier(); dessinerTaches(); titre.focus(); }
  });

  // Range une tâche renvoyée par le serveur. Une relecture (prévenue par le serveur) a pu
  // l'apporter avant la réponse : on remplace alors celle qui porte le même numéro, sans doublon.
  function garder(recue) {
    const i = taches.findIndex((x) => x.id === recue.id);
    if (i >= 0) taches[i] = recue; else taches.push(recue);
  }

  function trier() {
    const cle = (t) => [t.faite ? 1 : 0, t.echeance ? 0 : 1, t.echeance || "", t.id];
    taches.sort((a, b) => { const x = cle(a), y = cle(b); for (let i = 0; i < x.length; i++) { if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; } return 0; });
  }

  function ligne(t) {
    const quand = t.echeance ? echeance(t.echeance) : null;
    return h("li", { class: t.faite ? "faite" : "" },
      h("button", { type: "button", class: "coche", role: "checkbox", "aria-checked": String(t.faite), "aria-label": t.faite ? `Remettre « ${t.titre} » à faire` : `Marquer « ${t.titre} » comme fait`,
        surclick: async () => {
          const ok = await tenter(async () => { garder(await api.envoyer(`/api/taches/${t.id}`, { faite: !t.faite })); changements++; });
          if (ok) { trier(); dessinerTaches(); }
        } }, icone("coche")),
      h("span", { class: "titre", texte: t.titre }),
      quand && !t.faite ? h("span", { class: quand.retard ? "quand retard" : "quand", texte: quand.retard ? `en retard, ${quand.texte}` : quand.texte }) : null,
      h("button", { type: "button", class: "oter", "aria-label": `Supprimer « ${t.titre} »`, title: "Supprimer",
        surclick: async () => {
          const ok = await tenter(async () => { await api.supprimer(`/api/taches/${t.id}`); changements++; }, { succes: "Tâche supprimée." });
          if (ok) { taches = taches.filter((x) => x.id !== t.id); dessinerTaches(); }
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

  // Ta journée : cours, examens, rendez-vous et blocs du planning ; ce qui est passé s'efface.
  function dessinerJournee() {
    const heure = (iso) => { const [hh, mm] = iso.slice(11, 16).split(":"); return `${Number(hh)} h${mm === "00" ? "" : ` ${mm}`}`; };
    const aVenir = journee.filter((x) => x.fin > maintenant);
    const montres = (aVenir.length ? aVenir : journee).slice(0, 7);
    const lignes = montres.map((x) => h("a", { href: "#/agenda", class: [x.fin <= maintenant || x.fait ? "passe" : "", x.debut <= maintenant && x.fin > maintenant ? "en-cours" : ""].join(" ").trim() || null },
      h("span", { class: "heure", texte: x.journee ? "journée" : heure(x.debut) }),
      h("span", { class: "quoi" }, h("span", { texte: x.genre === "devoir" ? `À rendre : ${x.titre}` : x.titre }),
        x.lieu && x.genre !== "devoir" ? h("span", { class: "discret petit", texte: x.lieu }) : null)));
    const reste = (aVenir.length ? aVenir : journee).length - montres.length;
    if (reste > 0) lignes.push(h("a", { href: "#/agenda", class: "discret" }, h("span", { texte: `Et ${reste} de plus dans l'agenda` })));
    if (!journee.length) lignes.push(h("a", { href: "#/agenda" }, h("span", { class: "secondaire", texte: "Rien de prévu aujourd'hui. Ouvrir l'agenda" }), icone("agenda")));
    else if (!aVenir.length) lignes.unshift(h("p", { class: "discret petit", texte: "C'est tout pour aujourd'hui." }));
    const place = [...jour.children].indexOf(document.activeElement);    // garder la place du clavier
    jour.replaceChildren(...lignes);
    if (place >= 0) jour.children[Math.min(place, jour.children.length - 1)]?.focus({ preventScroll: true });
  }

  // chaque minute, seulement « ta journée » (ce qui est passé s'efface) : les tâches ne bougent pas
  async function rafraichirJournee() {
    try {
      const r = await api.lire("/api/aujourdhui");
      journee = r.journee || []; maintenant = r.maintenant || "";
      dessinerJournee();
    } catch { /* on réessaiera à la prochaine minute */ }
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
      taches = r.taches; systeme = r.systeme; journee = r.journee || []; maintenant = r.maintenant || "";
      dessinerTaches(); dessinerJournee(); dessinerPc();
    } catch (e) { if (numero === relectures) annoncer(e.message, { erreur: true }); }
  }

  const anciennes = [["maison", "Maison"]];
  conteneur.replaceChildren(
    h("header", { class: "entete" }, h("h1", { texte: "aujourd'hui" }), h("p", { class: "sous", texte: dateLongue() })),
    h("div", { class: "corps deux" },
      h("section", { "aria-labelledby": "t-faire" }, h("h2", { id: "t-faire", texte: "à faire" }), formulaire, liste, bascule, faites),
      h("aside", { class: "cote" },
        h("section", { "aria-labelledby": "t-journee" }, h("h2", { id: "t-journee", texte: "ta journée" }), jour),
        h("section", {}, h("h2", { texte: "l'ordinateur" }), pc),
        h("section", {}, h("h2", { texte: "bientôt ici" }),
          h("p", { class: "discret petit", texte: "Maison est en train d'être refaite dans Smoky. D'ici là, l'ancienne appli s'ouvre dans sa propre fenêtre." }),
          h("div", { class: "liste" }, anciennes.map(([id, nom]) =>
            h("button", { type: "button", surclick: () => ouvrirAncienne(id) }, h("span", { texte: `Ouvrir ${nom}` }), icone("dehors"))))))));

  const visible = () => { if (document.visibilityState === "visible") charger(); };
  document.addEventListener("visibilitychange", visible);
  // tâches changées dans une autre fenêtre, agenda changé, ou état du PC changé (mise à jour prête…)
  const oublier = contexte.surChangement((quoi) => { if (["taches", "agenda", "systeme", ""].includes(quoi || "")) charger(); });
  const minute = setInterval(() => { if (document.visibilityState === "visible") rafraichirJournee(); }, 60000);
  await charger();
  return { demonter() { document.removeEventListener("visibilitychange", visible); clearInterval(minute); oublier(); } };
}
