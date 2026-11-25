"""Bouton « Windows » de l'écran de connexion : deux appuis, demande déposée, réponse d'un service
simulé affichée ; puis l'ancienne voie (service direct) quand le dossier manque, erreur affichée."""
import tempfile
from pathlib import Path

from outils import boutons, conclure
from smokybureau import connexion
from gi.repository import GLib

dossier = Path(tempfile.mkdtemp())
connexion.DEMANDE_WINDOWS = dossier / "smoky-windows"
connexion.ETAT_WINDOWS = dossier / "smoky-windows.etat"
app = connexion.Connexion()
r = {}


def service_simule():
    r["demande"] = connexion.DEMANDE_WINDOWS.exists()
    connexion.DEMANDE_WINDOWS.unlink()
    connexion.ETAT_WINDOWS.write_text("en cours\n")
    GLib.timeout_add(1200, lambda: connexion.ETAT_WINDOWS.write_text("Windows introuvable\n") and False)
    return False


def verifier():
    r["message"] = app.message.get_label()
    connexion.DEMANDE_WINDOWS = dossier / "absent" / "smoky-windows"
    app.windows()
    GLib.timeout_add(3000, fin)
    return False


def fin():
    r["repli"] = app.message.get_label()
    app.quit()
    return False


def demarrer():
    bouton = [b for b in boutons(app.fenetre) if b.get_label() == "Windows"][0]
    bouton.emit("clicked")
    r["confirmer"] = bouton.get_label()
    bouton.emit("clicked")
    GLib.timeout_add(500, service_simule)
    GLib.timeout_add(4500, verifier)
    return False


app.connect("activate", lambda *a: GLib.timeout_add(300, demarrer))
app.run([])
conclure("écran de connexion : bouton Windows",
         r.get("confirmer") == "Confirmer" and r.get("demande") is True
         and r.get("message") == "Windows : Windows introuvable" and r.get("repli", "").startswith("Windows : "), r)
