"""Notes de Smoky : des carnets à écrire au stylet.

Ils sont rangés dans ~/Notes/Carnets, donc synchronisés avec Google Drive comme tout le dossier
Notes. Un dossier par carnet :
  carnet.json          titre, classeur, couverture, papier par défaut, liste des pages (sans leur
                       contenu), enregistrements audio
  pages/<page>.json    ce qui est écrit sur la page : traits, textes, images
  fichiers/            PDF annotés, images, enregistrements audio
Écrire sur une page ne réécrit que le petit fichier de cette page (rapide, et peu à synchroniser).
Un carnet supprimé part dans Carnets/.corbeille, d'où il se restaure.
Les carnets de l'ancien Smoky Notes (Notes/Smoky Notes) ne sont ni lus ni modifiés.
"""
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from .serveur import Brut, Erreur

FORMAT = 1
ID_CARNET = re.compile(r"c[0-9a-z]{6,12}-[0-9a-f]{4,8}")
ID_PAGE = re.compile(r"p[0-9a-z]{4,24}(-[0-9a-z]{2,12})?")
REV = re.compile(r"[0-9a-z-]{4,32}")
ID_SON = re.compile(r"s[0-9a-z]{4,24}(-[0-9a-z]{2,12})?")
NOM_FICHIER = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\.(pdf|png|jpg|jpeg|webp|webm|ogg)")
TYPES_FICHIERS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp", ".webm": "audio/webm", ".ogg": "audio/ogg"}
SIGNATURES = {".pdf": (b"%PDF-",), ".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
              ".webp": (b"RIFF",), ".webm": (b"\x1a\x45\xdf\xa3",), ".ogg": (b"OggS",)}
FICHIER_MAXI = 250_000_000            # un gros PDF de cours, ou deux heures d'enregistrement
PAGE_MAXI = 12_000_000                # une page très chargée (des milliers de traits)
CARNET_MAXI = 2_000_000               # liste des pages d'un carnet de plusieurs milliers de pages

# Formats (en points PDF : 1/72 de pouce), modèles et couleurs de papier, couvertures
FORMATS = {"a4": (595.28, 841.89), "a4-paysage": (841.89, 595.28), "ecran": (841.89, 526.18)}
MODELES = ["vierge", "ligne", "carreaux", "points", "seyes", "cornell", "portees"]
COULEURS = ["blanc", "ivoire", "cendre", "fumee"]
COUVERTURES = ["fumee", "argent", "onyx", "ivoire", "ardoise", "encre", "sauge", "braise"]
MATIERES = Path(os.environ.get("SMOKY_MATIERES", "/usr/share/smokyos/matieres.json"))


def dossier_notes():
    """~/Notes/Carnets (SMOKY_NOTES remplace ~/Notes pour les essais)."""
    return Path(os.environ.get("SMOKY_NOTES") or (Path.home() / "Notes")) / "Carnets"


def matieres():
    """Matières communes à Smoky OS, avec le papier conseillé pour chacune."""
    try:
        lues = json.loads(MATIERES.read_text())["matieres"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    papiers = {"grid": "carreaux", "lined": "ligne", "seyes": "seyes", "dots": "points", "blank": "vierge"}
    return [{"nom": m["nom"], "modele": papiers.get(m.get("papier"), "carreaux")}
            for m in lues if isinstance(m, dict) and isinstance(m.get("nom"), str)][:30]


def _propre(texte, maxi):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(texte)).strip()[:maxi]


def _ecrire(chemin, donnees):
    """Écrit d'un coup : le fichier n'est jamais vu à moitié (ni par la page, ni par la synchro)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(f".{chemin.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "wb") as f:
        f.write(donnees)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, chemin)


def _nombre(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


# Réglages des outils de l'éditeur (gardés d'une fois sur l'autre) : valeurs permises
OUTILS = {"stylo", "surligneur", "gomme", "lasso", "texte", "laser"}
COULEUR = re.compile(r"#[0-9a-f]{6}")
LARGEURS = {"stylo": (0.5, 8), "surligneur": (4, 40), "gomme": (2, 60), "texte": (8, 48)}


class Notes:
    def __init__(self, base=None, prevenir=None):
        self.base = base
        self.prevenir = prevenir or (lambda quoi, **plus: None)
        self.verrou = threading.RLock()

    @property
    def racine(self):
        return dossier_notes()

    # --- Chemins vérifiés -------------------------------------------------------------------------
    def _dossier(self, cid, existe=True):
        if not isinstance(cid, str) or not ID_CARNET.fullmatch(cid):
            raise Erreur(404, "Carnet introuvable.")
        d = self.racine / cid
        if existe and not (d / "carnet.json").is_file():
            raise Erreur(404, "Carnet introuvable.")
        return d

    def _lire(self, d):
        try:
            carnet = json.loads((d / "carnet.json").read_text())
        except (OSError, ValueError):
            raise Erreur(500, "Ce carnet est illisible.") from None
        if not isinstance(carnet, dict):
            raise Erreur(500, "Ce carnet est illisible.")
        return carnet

    def _enregistrer(self, d, carnet):
        _ecrire(d / "carnet.json", json.dumps(carnet, ensure_ascii=False, separators=(",", ":")).encode())

    def _modifie(self, d):
        """Dernière modification (ms) : le carnet ou l'une de ses pages."""
        dates = []
        for p in (d / "carnet.json", d / "pages"):
            try:
                dates.append(p.stat().st_mtime)
            except OSError:
                pass
        return int(max(dates, default=0) * 1000)

    def _resume(self, d, carnet):
        pages = carnet.get("pages") or []
        premiere = pages[0] if pages and isinstance(pages[0], dict) else {}
        return {"id": carnet.get("id"), "titre": carnet.get("titre", ""), "classeur": carnet.get("classeur", ""),
                "couverture": carnet.get("couverture", "fumee"), "favori": bool(carnet.get("favori")),
                "cree": carnet.get("cree", 0), "modifie": self._modifie(d), "pages": len(pages),
                "papier": {k: premiere.get(k) for k in ("w", "h", "modele", "couleur")},
                "pdf": bool(premiere.get("fond"))}

    # --- Bibliothèque -----------------------------------------------------------------------------
    def bibliotheque(self):
        # instant : quand le dossier a été lu ; la page garde la lecture la plus récente même si deux
        # réponses lui arrivent dans le désordre
        instant = time.monotonic_ns()
        carnets, corbeille = [], []
        racine = self.racine
        if racine.is_dir():
            for d in racine.iterdir():
                if d.is_dir() and ID_CARNET.fullmatch(d.name) and (d / "carnet.json").is_file():
                    try:
                        carnets.append(self._resume(d, self._lire(d)))
                    except Erreur:
                        pass
            jetes = racine / ".corbeille"
            if jetes.is_dir():
                for d in jetes.iterdir():
                    m = re.fullmatch(r"(c[0-9a-z]{6,12}-[0-9a-f]{4,8})-(\d{10})", d.name)
                    if m and d.is_dir() and (d / "carnet.json").is_file():
                        try:
                            r = self._resume(d, self._lire(d))
                        except Erreur:
                            continue
                        corbeille.append({**r, "id": d.name, "jete": int(m.group(2)) * 1000})
        carnets.sort(key=lambda c: c["modifie"], reverse=True)
        corbeille.sort(key=lambda c: c["jete"], reverse=True)
        return {"carnets": carnets, "corbeille": corbeille, "matieres": matieres(), "couvertures": COUVERTURES,
                "modeles": MODELES, "couleurs": COULEURS, "formats": {k: list(v) for k, v in FORMATS.items()},
                "dossier": "Notes/Carnets", "preferences": self.preferences(), "ancien": self._ancien(), "instant": instant}

    def _ancien(self):
        """Des carnets attendent dans l'ancien Smoky Notes (Notes/Smoky Notes) : la page le rappelle.
        Seul le dossier est regardé ; rien n'y est lu ni changé."""
        try:
            return any(True for _ in (self.racine.parent / "Smoky Notes").iterdir())
        except OSError:
            return False

    def preferences(self):
        lues = self.base.reglage("notes.preferences", {}) if self.base else {}
        return lues if isinstance(lues, dict) else {}

    def _a_preferences(self, a):
        """Outil choisi, couleurs et épaisseurs, écriture au doigt… : retrouvés à la prochaine ouverture."""
        v = a.get("valeurs")
        if not isinstance(v, dict) or self.base is None:
            raise Erreur(400, "Réglages invalides.")
        propres = {}
        if v.get("outil") in OUTILS:
            propres["outil"] = v["outil"]
        for cle in ("doigt", "formes", "gribouillis"):
            if isinstance(v.get(cle), bool):
                propres[cle] = v[cle]
        for outil, (lo, hi) in LARGEURS.items():
            r = v.get(outil)
            if not isinstance(r, dict):
                continue
            propre = {}
            if isinstance(r.get("couleur"), str) and COULEUR.fullmatch(r["couleur"].lower()):
                propre["couleur"] = r["couleur"].lower()
            if _nombre(r.get("largeur"), lo, hi):
                propre["largeur"] = round(float(r["largeur"]), 2)
            if outil == "gomme" and isinstance(r.get("precise"), bool):
                propre["precise"] = r["precise"]
            if propre:
                propres[outil] = propre
        self.base.regler("notes.preferences", propres)
        return {"preferences": propres}

    def agir(self, a):
        action = a.get("action") if isinstance(a, dict) else None
        fonction = getattr(self, f"_a_{action}", None) if isinstance(action, str) and re.fullmatch(r"[a-z_]+", action) else None
        if fonction is None:
            raise Erreur(400, "Action inconnue.")
        with self.verrou:
            resultat = fonction(a)
        if action != "preferences":
            self.prevenir("notes")
        return resultat

    @staticmethod
    def _titre(v, defaut=None):
        titre = _propre(v, 100) if isinstance(v, str) else ""
        if not titre and defaut is None:
            raise Erreur(400, "Donne un nom au carnet.")
        return titre or defaut

    @staticmethod
    def _classeur(v):
        if v is None:
            return ""
        if not isinstance(v, str):
            raise Erreur(400, "Classeur invalide.")
        return _propre(v, 60)

    @staticmethod
    def _papier(v):
        v = v if isinstance(v, dict) else {}
        papier = {"format": v.get("format", "a4"), "modele": v.get("modele", "ligne"), "couleur": v.get("couleur", "blanc")}
        if papier["format"] not in FORMATS or papier["modele"] not in MODELES or papier["couleur"] not in COULEURS:
            raise Erreur(400, "Papier inconnu.")
        return papier

    def _nouvel_id(self):
        return f"c{int(time.time() * 1000):x}"[:13] + "-" + secrets.token_hex(3)

    def _a_creer(self, a):
        """Nouveau carnet, une première page sur le papier choisi (ou les pages d'un PDF, envoyé ensuite)."""
        couverture = a.get("couverture", "fumee")
        if couverture not in COUVERTURES:
            raise Erreur(400, "Couverture inconnue.")
        papier = self._papier(a.get("papier"))
        cid = self._nouvel_id()
        while (self.racine / cid).exists():
            cid = self._nouvel_id()
        w, h = FORMATS[papier["format"]]
        maintenant = int(time.time() * 1000)
        pages = [] if a.get("vide") is True else [
            {"id": f"p{maintenant:x}-{secrets.token_hex(3)}", "w": w, "h": h, "modele": papier["modele"],
             "couleur": papier["couleur"], "signet": False}]
        carnet = {"format": FORMAT, "id": cid, "titre": self._titre(a.get("titre")), "classeur": self._classeur(a.get("classeur")),
                  "couverture": couverture, "favori": False, "cree": maintenant, "papier": papier, "pages": pages, "sons": []}
        d = self.racine / cid
        (d / "pages").mkdir(parents=True)
        (d / "fichiers").mkdir()
        self._enregistrer(d, carnet)
        return {"carnet": carnet}

    def _modifier(self, a, champ, valeur):
        d = self._dossier(a.get("id"))
        carnet = self._lire(d)
        carnet[champ] = valeur
        self._enregistrer(d, carnet)
        return {"carnet": self._resume(d, carnet)}

    def _a_renommer(self, a):
        return self._modifier(a, "titre", self._titre(a.get("titre")))

    def _a_classer(self, a):
        return self._modifier(a, "classeur", self._classeur(a.get("classeur")))

    def _a_favori(self, a):
        if not isinstance(a.get("favori"), bool):
            raise Erreur(400, "Valeur refusée.")
        return self._modifier(a, "favori", a["favori"])

    def _a_couverture(self, a):
        if a.get("couverture") not in COUVERTURES:
            raise Erreur(400, "Couverture inconnue.")
        return self._modifier(a, "couverture", a["couverture"])

    def _a_dupliquer(self, a):
        source = self._dossier(a.get("id"))
        cid = self._nouvel_id()
        cible = self.racine / cid
        shutil.copytree(source, cible, ignore=shutil.ignore_patterns(".*.tmp"))
        carnet = self._lire(cible)
        carnet.update({"id": cid, "titre": f"{carnet.get('titre', '')} (copie)"[:100], "favori": False,
                       "cree": int(time.time() * 1000)})
        self._enregistrer(cible, carnet)
        return {"carnet": self._resume(cible, carnet)}

    def _a_supprimer(self, a):
        """À la corbeille (jamais effacé d'un coup) : il se restaure tel quel."""
        d = self._dossier(a.get("id"))
        jetes = self.racine / ".corbeille"
        jetes.mkdir(parents=True, exist_ok=True)
        quand = int(time.time())
        while (jetes / f"{d.name}-{quand}").exists():     # jeté, restauré puis rejeté dans la même seconde
            quand += 1
        os.replace(d, jetes / f"{d.name}-{quand}")
        return {"message": "Carnet mis à la corbeille."}

    def _jete(self, nom):
        if not isinstance(nom, str) or not re.fullmatch(r"c[0-9a-z]{6,12}-[0-9a-f]{4,8}-\d{10}", nom):
            raise Erreur(404, "Introuvable dans la corbeille.")
        d = self.racine / ".corbeille" / nom
        if not (d / "carnet.json").is_file():
            raise Erreur(404, "Introuvable dans la corbeille.")
        return d

    def _a_restaurer(self, a):
        d = self._jete(a.get("id"))
        cid = d.name.rsplit("-", 1)[0]
        cible = self.racine / cid
        if cible.exists():                              # un carnet du même numéro existe déjà : nouveau numéro
            cid = self._nouvel_id()
            cible = self.racine / cid
            os.replace(d, cible)
            carnet = self._lire(cible)
            carnet["id"] = cid
            self._enregistrer(cible, carnet)
        else:
            os.replace(d, cible)
        return {"message": "Carnet restauré.", "id": cid}

    def _a_effacer(self, a):
        """Efface pour de bon un carnet de la corbeille (la page demande confirmation avant)."""
        shutil.rmtree(self._jete(a.get("id")))
        return {"message": "Carnet effacé définitivement."}

    # --- Un carnet ----------------------------------------------------------------------------------
    def carnet(self, cid):
        d = self._dossier(cid)
        carnet = self._lire(d)
        return {**carnet, "modifie": self._modifie(d)}

    def _verifier_pages(self, pages, d):
        if not isinstance(pages, list) or len(pages) > 5000:
            raise Erreur(400, "Liste de pages invalide.")
        vues, propres = set(), []
        for p in pages:
            if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not ID_PAGE.fullmatch(p["id"]) or p["id"] in vues:
                raise Erreur(400, "Page invalide.")
            vues.add(p["id"])
            if not _nombre(p.get("w"), 50, 5000) or not _nombre(p.get("h"), 50, 5000):
                raise Erreur(400, "Taille de page invalide.")
            if p.get("modele", "vierge") not in MODELES or p.get("couleur", "blanc") not in COULEURS:
                raise Erreur(400, "Papier inconnu.")
            page = {"id": p["id"], "w": round(float(p["w"]), 2), "h": round(float(p["h"]), 2),
                    "modele": p.get("modele", "vierge"), "couleur": p.get("couleur", "blanc"), "signet": bool(p.get("signet"))}
            fond = p.get("fond")
            if fond is not None:
                if (not isinstance(fond, dict) or not isinstance(fond.get("pdf"), str) or not NOM_FICHIER.fullmatch(fond["pdf"])
                        or not fond["pdf"].endswith(".pdf") or not isinstance(fond.get("page"), int) or isinstance(fond.get("page"), bool)
                        or not 0 <= fond["page"] < 100000):
                    raise Erreur(400, "Fond de page invalide.")
                if not (d / "fichiers" / fond["pdf"]).is_file():
                    raise Erreur(400, "Le PDF de cette page n'a pas été envoyé.")
                page["fond"] = {"pdf": fond["pdf"], "page": fond["page"]}
            propres.append(page)
        return propres

    def _verifier_sons(self, sons, d):
        if not isinstance(sons, list) or len(sons) > 1000:
            raise Erreur(400, "Enregistrements invalides.")
        propres = []
        for s in sons:
            if (not isinstance(s, dict) or not isinstance(s.get("id"), str) or not ID_SON.fullmatch(s["id"])
                    or not isinstance(s.get("fichier"), str) or not NOM_FICHIER.fullmatch(s["fichier"])
                    or not _nombre(s.get("debut"), 0, 1e14) or not _nombre(s.get("duree"), 0, 86_400_000)):
                raise Erreur(400, "Enregistrement invalide.")
            propres.append({"id": s["id"], "fichier": s["fichier"], "debut": int(s["debut"]), "duree": int(s["duree"])})
        return propres

    def enregistrer_carnet(self, cid, corps):
        """L'éditeur envoie la liste des pages (ordre, papier, signets), le papier par défaut et les
        enregistrements ; titre, classeur, couverture et favori passent par la bibliothèque."""
        d = self._dossier(cid)
        try:
            recu = json.loads(corps)
        except (ValueError, UnicodeDecodeError):
            raise Erreur(400, "Carnet illisible.") from None
        if not isinstance(recu, dict):
            raise Erreur(400, "Carnet illisible.")
        with self.verrou:
            carnet = self._lire(d)
            if "pages" in recu:
                carnet["pages"] = self._verifier_pages(recu["pages"], d)
            if "papier" in recu:
                carnet["papier"] = self._papier(recu["papier"])
            if "sons" in recu:
                carnet["sons"] = self._verifier_sons(recu["sons"], d)
            if "titre" in recu:
                carnet["titre"] = self._titre(recu["titre"])
            self._enregistrer(d, carnet)
            # les pages retirées du carnet : leur fichier part aussi (il n'est plus référencé)
            gardees = {p["id"] for p in carnet["pages"]}
            for f in (d / "pages").glob("p*.json"):
                if f.stem not in gardees:
                    f.unlink(missing_ok=True)
        self.prevenir(f"notes:{cid}")
        return {"modifie": self._modifie(d)}

    def page(self, cid, pid):
        d = self._dossier(cid)
        if not isinstance(pid, str) or not ID_PAGE.fullmatch(pid):
            raise Erreur(404, "Page introuvable.")
        try:
            return json.loads((d / "pages" / f"{pid}.json").read_text())
        except FileNotFoundError:
            return {"format": FORMAT, "traits": [], "textes": [], "images": []}
        except (OSError, ValueError):
            raise Erreur(500, "Cette page est illisible.") from None

    @staticmethod
    def _verifier_page(page):
        """Forme générale seulement : la page est écrite par l'éditeur de Smoky, ceci protège le fichier
        d'un envoi abîmé sans ralentir l'enregistrement d'une page très chargée."""
        if not isinstance(page, dict):
            raise Erreur(400, "Page illisible.")
        propre = {"format": FORMAT}
        # rev : marque de cette version, choisie par l'éditeur qui l'envoie ; il reconnaît ainsi l'écho
        # de son propre enregistrement parmi les changements annoncés aux fenêtres
        rev = page.get("rev")
        if rev is not None:
            if not isinstance(rev, str) or not REV.fullmatch(rev):
                raise Erreur(400, "Page illisible.")
            propre["rev"] = rev
        for cle in ("traits", "textes", "images"):
            liste = page.get(cle, [])
            if not isinstance(liste, list) or len(liste) > 100_000 or not all(isinstance(x, dict) for x in liste):
                raise Erreur(400, "Page illisible.")
            propre[cle] = liste
        for t in propre["traits"]:
            points = t.get("points")
            if (not isinstance(points, list) or len(points) % 3 or len(points) > 300_000
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in points)):
                raise Erreur(400, "Trait illisible.")
        for im in propre["images"]:
            if not isinstance(im.get("fichier"), str) or not NOM_FICHIER.fullmatch(im["fichier"]):
                raise Erreur(400, "Image illisible.")
        return propre

    def enregistrer_page(self, cid, pid, corps):
        d = self._dossier(cid)
        if not isinstance(pid, str) or not ID_PAGE.fullmatch(pid):
            raise Erreur(404, "Page introuvable.")
        try:
            page = self._verifier_page(json.loads(corps))
        except (ValueError, UnicodeDecodeError):
            raise Erreur(400, "Page illisible.") from None
        with self.verrou:
            if pid not in {p.get("id") for p in self._lire(d).get("pages", []) if isinstance(p, dict)}:
                raise Erreur(404, "Cette page n'est plus dans le carnet.")
            _ecrire(d / "pages" / f"{pid}.json", json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode())
        self.prevenir(f"notes:{cid}:{pid}", **({"rev": page["rev"]} if "rev" in page else {}))
        return {"modifie": self._modifie(d)}

    # --- Fichiers joints ------------------------------------------------------------------------------
    def _fichier(self, cid, nom):
        d = self._dossier(cid)
        if not isinstance(nom, str) or not NOM_FICHIER.fullmatch(nom):
            raise Erreur(404, "Fichier introuvable.")
        return d / "fichiers" / nom

    def lire_fichier(self, cid, nom):
        chemin = self._fichier(cid, nom)
        try:
            return Brut(chemin.read_bytes(), TYPES_FICHIERS[chemin.suffix])
        except OSError:
            raise Erreur(404, "Fichier introuvable.") from None

    def envoyer_fichier(self, cid, nom, corps):
        chemin = self._fichier(cid, nom)
        if not corps.startswith(SIGNATURES[chemin.suffix]):
            raise Erreur(400, "Ce fichier n'est pas ce qu'annonce son nom.")
        if chemin.exists() and chemin.stat().st_size == len(corps):
            return {"ok": True}                       # même fichier déjà là (nom tiré de son contenu)
        _ecrire(chemin, corps)
        return {"ok": True}

    def exporter(self, nom, corps):
        """PDF préparé par la page (pdf-lib) → ~/Notes/PDF/<nom>.pdf (remplace l'export précédent du même nom)."""
        if not isinstance(nom, str):
            raise Erreur(400, "Nom de fichier invalide.")
        nom = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]+', " ", nom).strip(" .")[:120] or "Carnet"
        if not corps.startswith(b"%PDF-"):
            raise Erreur(400, "Ce n'est pas un PDF.")
        dossier = self.racine.parent / "PDF"
        cible = dossier / f"{nom}.pdf"
        _ecrire(cible, corps)
        return {"message": f"PDF enregistré dans Notes/PDF/{cible.name}.", "chemin": str(cible)}
