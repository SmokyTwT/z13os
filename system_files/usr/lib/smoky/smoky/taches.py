"""« À faire » : les tâches de la page Aujourd'hui."""
import re
import time
from datetime import date

from .serveur import Erreur

TITRE_MAXI = 200


def _titre(valeur):
    if not isinstance(valeur, str) or not valeur.strip():
        raise Erreur(400, "Écris ce qu'il y a à faire.")
    titre = " ".join(valeur.split())
    if len(titre) > TITRE_MAXI:
        raise Erreur(400, f"Titre trop long ({TITRE_MAXI} caractères au plus).")
    return titre


def _echeance(valeur):
    if valeur in (None, ""):
        return None
    if not isinstance(valeur, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
        raise Erreur(400, "Date illisible.")
    try:
        date.fromisoformat(valeur)
    except ValueError:
        raise Erreur(400, "Cette date n'existe pas.") from None
    return valeur


class Taches:
    def __init__(self, base):
        self.base = base

    def liste(self):
        """À faire d'abord (échéance la plus proche en tête, sans date à la fin), puis les 20 dernières faites."""
        ouvertes = self.base.lire("SELECT id, titre, faite, echeance FROM taches WHERE faite = 0 "
                                  "ORDER BY echeance IS NULL, echeance, id")
        faites = self.base.lire("SELECT id, titre, faite, echeance FROM taches WHERE faite = 1 ORDER BY terminee DESC LIMIT 20")
        return [{**t, "faite": bool(t["faite"])} for t in ouvertes + faites]

    def _ligne(self, identifiant):
        # un numéro simple, en chiffres ordinaires, qui tient dans la base
        if not re.fullmatch(r"[1-9][0-9]{0,14}", str(identifiant), re.ASCII):
            raise Erreur(404, "Tâche introuvable.")
        tache = self.base.un("SELECT id, titre, faite, echeance, terminee FROM taches WHERE id = ?", (int(identifiant),))
        if tache is None:
            raise Erreur(404, "Tâche introuvable.")
        return {**tache, "faite": bool(tache["faite"])}

    def une(self, identifiant):
        tache = self._ligne(identifiant)
        del tache["terminee"]                         # détail interne : sert seulement à ranger les tâches faites
        return tache

    def creer(self, donnees):
        numero, _ = self.base.ecrire("INSERT INTO taches (titre, echeance, creee) VALUES (?, ?, ?)",
                                     (_titre(donnees.get("titre")), _echeance(donnees.get("echeance")), time.time()))
        return self.une(numero)

    def modifier(self, identifiant, donnees):
        tache = self._ligne(identifiant)
        terminee = tache.pop("terminee")
        if "titre" in donnees:
            tache["titre"] = _titre(donnees["titre"])
        if "echeance" in donnees:
            tache["echeance"] = _echeance(donnees["echeance"])
        if "faite" in donnees:
            if not isinstance(donnees["faite"], bool):
                raise Erreur(400, "Valeur refusée.")
            if donnees["faite"] != tache["faite"]:    # l'heure de fin ne bouge que quand on coche ou décoche
                terminee = time.time() if donnees["faite"] else None
            tache["faite"] = donnees["faite"]
        self.base.ecrire("UPDATE taches SET titre = ?, echeance = ?, faite = ?, terminee = ? WHERE id = ?",
                         (tache["titre"], tache["echeance"], int(tache["faite"]), terminee, tache["id"]))
        return tache

    def supprimer(self, identifiant):
        tache = self.une(identifiant)
        self.base.ecrire("DELETE FROM taches WHERE id = ?", (tache["id"],))
        return {}
