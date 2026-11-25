"""Écran de connexion qui ne peut pas s'afficher en entier (panne simulée dans construire) : l'écran
de secours apparaît, avec le champ, le clavier tactile qui tape dedans et les trois boutons."""
import os
import subprocess

from outils import appuyer, boutons, conclure
from smokybureau import connexion
from gi.repository import GLib


def panne(self, w):
    raise RuntimeError("panne simulée")


connexion.Connexion.construire = panne
app = connexion.Connexion()
r = {}


def verifier():
    r["secours"] = app.secours
    etiquettes = [b.get_label() for b in boutons(app.fenetre)]
    r["boutons"] = [e for e in ("Windows", "Redémarrer", "Éteindre", "⌨  Clavier") if e in etiquettes]
    for t in ["o", "k", "⇧", "Z"]:
        appuyer(app.fenetre, t)
    r["texte"] = app.mdp.get_text()
    subprocess.run(["grim", os.path.join(os.environ["ATELIER"], "captures", "connexion-secours.png")])
    app.quit()
    return False


app.connect("activate", lambda *a: GLib.timeout_add(800, verifier))
app.run([])
conclure("écran de connexion : écran de secours si l'affichage complet échoue",
         r.get("secours") is True and r.get("texte") == "okZ" and len(r.get("boutons", [])) == 4, r)
