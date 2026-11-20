// Smoky — Notes : un carnet ouvert. Ses pages sont chargées quand on s'en approche, et chaque page
// modifiée part toute seule au serveur 0,7 s après le dernier coup de stylo (une à la fois, dans
// l'ordre ; en cas d'échec, nouvel essai quelques secondes plus tard, rien n'est perdu).
import { api } from "/js/app.js";

export const nouvelId = (prefixe) => {
  const a = crypto.getRandomValues(new Uint32Array(2));
  return `${prefixe}${Date.now().toString(36)}-${a[0].toString(36).slice(0, 6)}${(a[1] % 1296).toString(36)}`;
};

export const pageVide = () => ({ traits: [], textes: [], images: [] });

// Nom d'un fichier joint tiré de son contenu : le même PDF importé deux fois n'est gardé qu'une fois.
export async function nomFichier(blob, extension) {
  const empreinte = new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()));
  return [...empreinte.slice(0, 12)].map((o) => o.toString(16).padStart(2, "0")).join("") + extension;
}

export class CarnetOuvert {
  constructor(carnet, { surEtat = () => {} } = {}) {
    this.carnet = carnet;                 // { id, titre, papier, pages: [{ id, w, h, modele, couleur, fond?, signet }], sons }
    this.contenus = new Map();            // id de page → { traits, textes, images }
    this.attentes = new Map();            // id de page → chargement en cours
    this.sales = new Set();               // pages à enregistrer
    this.revs = new Map();                // id de page → marque de la version qu'on a (lue ou envoyée)
    this.tours = new Map();               // id de page → nombre de changements faits ici
    this.carnetSale = false;              // liste des pages, papier, sons à enregistrer
    this.minuteur = 0;
    this.envoi = null;
    this.surEtat = surEtat;
    this.urls = new Map();                // fichier joint → adresse blob: (images, sons)
    this.ferme = false;
  }

  get base() { return `/api/notes/${encodeURIComponent(this.carnet.id)}`; }

  page(pid) { return this.carnet.pages.find((p) => p.id === pid); }
  index(pid) { return this.carnet.pages.findIndex((p) => p.id === pid); }

  // Contenu d'une page (chargé une fois) → Promise
  contenu(pid) {
    if (this.contenus.has(pid)) return Promise.resolve(this.contenus.get(pid));
    if (!this.attentes.has(pid)) {
      this.attentes.set(pid, api.lire(`${this.base}/pages/${encodeURIComponent(pid)}`).then((c) => {
        const propre = { traits: c.traits || [], textes: c.textes || [], images: c.images || [] };
        if (!this.contenus.has(pid)) { this.contenus.set(pid, propre); this.revs.set(pid, c.rev || ""); }
        return this.contenus.get(pid);
      }).finally(() => this.attentes.delete(pid)));
    }
    return this.attentes.get(pid);
  }

  // Contenu déjà là (sans attendre) ou null
  charge(pid) { return this.contenus.get(pid) || null; }

  // Une page a changé sur le disque (annonce du serveur). L'écho de notre propre enregistrement est
  // reconnu à sa marque et ignoré. Sinon la page est relue en arrière-plan, l'ancien contenu restant
  // utilisable ; elle n'est remplacée que si rien n'a bougé ici entre-temps et si peutRemplacer()
  // le permet (aucun geste en cours dessus). → true si le contenu a été remplacé.
  async recharger(pid, rev, peutRemplacer = () => true) {
    if ((rev && this.revs.get(pid) === rev) || !this.contenus.has(pid) || this.sales.has(pid)) return false;
    const tour = this.tours.get(pid) || 0;
    const c = await api.lire(`${this.base}/pages/${encodeURIComponent(pid)}`);
    if (this.sales.has(pid) || (this.tours.get(pid) || 0) !== tour || !this.contenus.has(pid)) return false;
    if ((c.rev && c.rev === this.revs.get(pid)) || !peutRemplacer()) return false;
    this.contenus.set(pid, { traits: c.traits || [], textes: c.textes || [], images: c.images || [] });
    this.revs.set(pid, c.rev || "");
    return true;
  }

  modifier(pid) {
    if (!this.contenus.has(pid)) this.contenus.set(pid, pageVide());
    this.tours.set(pid, (this.tours.get(pid) || 0) + 1);
    this.sales.add(pid);
    this.planifier();
  }

  modifierCarnet() {
    this.carnetSale = true;
    this.planifier();
  }

  planifier(delai = 700) {
    clearTimeout(this.minuteur);
    this.surEtat("modifie");
    this.minuteur = setTimeout(() => this.enregistrer(), delai);
  }

  aEnregistrer() { return this.carnetSale || this.sales.size > 0; }

  // Envoie tout ce qui est en attente. La liste des pages part avant les pages elles-mêmes (le
  // serveur refuse une page qui n'est pas encore dans le carnet).
  async enregistrer() {
    clearTimeout(this.minuteur);
    if (this.envoi) return this.envoi.then(() => (this.aEnregistrer() ? this.enregistrer() : undefined));
    if (!this.aEnregistrer()) return undefined;
    this.surEtat("en_cours");
    this.envoi = (async () => {
      try {
        if (this.carnetSale) {
          this.carnetSale = false;
          const { pages, papier, sons } = this.carnet;
          try {
            await api.mettre(this.base, { pages, papier, sons: sons || [] });
          } catch (e) { this.carnetSale = true; throw e; }
        }
        for (const pid of [...this.sales]) {
          this.sales.delete(pid);
          if (!this.page(pid)) continue;                 // page retirée entre-temps
          const c = this.contenus.get(pid);
          const rev = nouvelId("r");
          this.revs.set(pid, rev);
          try {
            await api.mettre(`${this.base}/pages/${encodeURIComponent(pid)}`, { traits: c.traits, textes: c.textes, images: c.images, rev });
          } catch (e) { this.sales.add(pid); throw e; }
        }
        this.surEtat(this.aEnregistrer() ? "modifie" : "enregistre");
      } catch (e) {
        this.surEtat("erreur", e.message);
        if (!this.ferme) this.minuteur = setTimeout(() => this.enregistrer(), 4000);
      }
    })();
    // ce qui a changé pendant l'envoi a déjà relancé son propre minuteur (modifier → planifier)
    try { await this.envoi; } finally { this.envoi = null; }
    return undefined;
  }

  async envoyerFichier(nom, blob) {
    await api.mettre(`${this.base}/fichiers/${encodeURIComponent(nom)}`, blob);
  }

  async octets(nom) {
    return api.octets(`${this.base}/fichiers/${encodeURIComponent(nom)}`);
  }

  // Adresse locale (blob:) d'une image ou d'un son du carnet, gardée tant que le carnet est ouvert
  async url(nom) {
    if (!this.urls.has(nom)) this.urls.set(nom, this.octets(nom).then((b) => URL.createObjectURL(b)));
    return this.urls.get(nom);
  }

  async fermer() {
    this.ferme = true;
    clearTimeout(this.minuteur);
    try { await this.enregistrer(); } finally {
      for (const u of this.urls.values()) u.then((x) => URL.revokeObjectURL(x)).catch(() => {});
      this.urls.clear();
    }
  }
}
