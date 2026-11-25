"""Écran de verrouillage qui ne peut pas s'afficher en entier (panne simulée) : l'écran reste
verrouillé et l'écran de secours apparaît, avec le champ et le clavier tactile qui tape dedans."""
import os
import subprocess

from outils import appuyer, conclure
from smokybureau import verrou
from gi.repository import GLib


def panne(self, moniteur, principal):
    raise RuntimeError("panne simulée")


verrou.Verrou.fenetre_pour = panne
app = verrou.Verrou()
r = {}


def verifier():
    r["secours"] = app.secours
    r["fenetres"] = len(app.fenetres)
    for t in ["o", "k", "⇧", "Z"]:
        appuyer(app.fenetres[0], t)
    r["texte"] = app.mdp.get_text()
    subprocess.run(["grim", os.path.join(os.environ["ATELIER"], "captures", "verrou-secours.png")])
    app.verrou.unlock()                       # (le mot de passe passe par PAM : pas ici)
    return False


app.connect("activate", lambda *a: GLib.timeout_add(1500, verifier))
app.run([])
conclure("écran de verrouillage : écran de secours si l'affichage complet échoue",
         r.get("secours") is True and r.get("fenetres", 0) >= 1 and r.get("texte") == "okZ"
         and app.code == 0, {**r, "code": app.code})
