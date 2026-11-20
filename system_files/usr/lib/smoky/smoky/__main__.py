"""Le serveur de Smoky :
    /usr/lib/smoky/lancer.py [--port N] [--page DOSSIER] [--arret-auto SECONDES [--profil DOSSIER]]
    /usr/lib/smoky/lancer.py --rappels     prépare les rappels de l'agenda puis s'arrête
                                           (smoky-agenda-reminders.service : chaque matin et à la connexion)

Le lanceur /usr/bin/smoky s'en charge ; le port et le code d'accès sont écrits dans
$XDG_RUNTIME_DIR/smoky/serveur.json (lisible par toi seul).
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from . import PORT, VERSION
from .agenda import Agenda, maintenant
from .base import Base
from .commandes import BIN, detacher, navigateur_ouvert
from .notes import CARNET_MAXI, FICHIER_MAXI, PAGE_MAXI, Notes
from .planning import iso
from .serveur import Appli, Erreur
from .systeme import Systeme
from .taches import Taches

# /usr/lib/smoky/smoky/__main__.py → /usr/share/smoky (pareil dans le dépôt, sous system_files/)
PAGE = Path(__file__).resolve().parents[3] / "share/smoky"

# Applis pas encore refaites dans Smoky : elles s'ouvrent à part, comme avant.
ANCIENNES = {"notes": "smoky-notes", "mail": "smoky-mail", "maison": "smoky-home"}
ANCIEN_AGENDA = Path(os.environ.get("SMOKY_ANCIEN_AGENDA", "/usr/libexec/smokyagenda/server.py"))   # variable : essais


def construire(page, port=PORT, arret_auto=None, jeton=None, base=None, present=None):
    appli = Appli(page, port, jeton=jeton, arret_auto=arret_auto, present=present)
    base = base or Base()
    taches = Taches(base)
    systeme = Systeme(prevenir=lambda quoi: appli.flux.publier("change", {"quoi": quoi}))
    agenda = Agenda(base, prevenir=lambda quoi: appli.flux.publier("change", {"quoi": quoi}))
    notes = Notes(base, prevenir=lambda quoi, **plus: appli.flux.publier("change", {"quoi": quoi, **plus}))

    def prevenir_taches(resultat):
        """Les autres fenêtres ouvertes relisent la liste (la page Agenda aussi : tâches à caser)."""
        appli.flux.publier("change", {"quoi": "taches"})
        agenda.taches_changees()
        return resultat

    @appli.route("GET", "/api/aujourdhui")
    def aujourdhui(requete):
        return {"taches": taches.liste(), "journee": agenda.journee(), "maintenant": iso(maintenant()),
                "systeme": systeme.resume(), "version": VERSION}

    @appli.route("POST", "/api/taches")
    def tache_creer(requete):
        return 201, prevenir_taches(taches.creer(requete.json()))

    @appli.route("POST", "/api/taches/<id>")
    def tache_modifier(requete):
        return prevenir_taches(taches.modifier(requete.morceaux["id"], requete.json()))

    @appli.route("DELETE", "/api/taches/<id>")
    def tache_supprimer(requete):
        return prevenir_taches(taches.supprimer(requete.morceaux["id"]))

    @appli.route("GET", "/api/agenda")
    def agenda_etat(requete):
        semaine = requete.params.get("semaine", ["0"])[-1]
        if not re.fullmatch(r"-?[0-9]{1,2}", semaine) or not -60 <= int(semaine) <= 60:
            raise Erreur(400, "Semaine invalide.")
        return agenda.etat(int(semaine))

    @appli.route("POST", "/api/agenda")
    def agenda_agir(requete):
        return agenda.agir(requete.json())

    # --- Notes : bibliothèque, carnets, pages, fichiers joints ---
    @appli.route("GET", "/api/notes")
    def notes_bibliotheque(requete):
        return notes.bibliotheque()

    @appli.route("POST", "/api/notes")
    def notes_agir(requete):
        return notes.agir(requete.json())

    @appli.route("POST", "/api/notes/export", corps_maxi=FICHIER_MAXI)
    def notes_exporter(requete):
        return notes.exporter(requete.params.get("nom", [""])[-1], requete.corps)

    @appli.route("GET", "/api/notes/<cid>")
    def notes_carnet(requete):
        return notes.carnet(requete.morceaux["cid"])

    @appli.route("PUT", "/api/notes/<cid>", corps_maxi=CARNET_MAXI)
    def notes_enregistrer_carnet(requete):
        return notes.enregistrer_carnet(requete.morceaux["cid"], requete.corps)

    @appli.route("GET", "/api/notes/<cid>/pages/<pid>")
    def notes_page(requete):
        return notes.page(requete.morceaux["cid"], requete.morceaux["pid"])

    @appli.route("PUT", "/api/notes/<cid>/pages/<pid>", corps_maxi=PAGE_MAXI)
    def notes_enregistrer_page(requete):
        return notes.enregistrer_page(requete.morceaux["cid"], requete.morceaux["pid"], requete.corps)

    @appli.route("GET", "/api/notes/<cid>/fichiers/<nom>")
    def notes_fichier(requete):
        return notes.lire_fichier(requete.morceaux["cid"], requete.morceaux["nom"])

    @appli.route("PUT", "/api/notes/<cid>/fichiers/<nom>", corps_maxi=FICHIER_MAXI)
    def notes_envoyer_fichier(requete):
        return notes.envoyer_fichier(requete.morceaux["cid"], requete.morceaux["nom"], requete.corps)

    @appli.route("GET", "/api/systeme")
    def systeme_etat(requete):
        return systeme.etat()

    @appli.route("POST", "/api/systeme")
    def systeme_agir(requete):
        return systeme.agir(requete.json())

    @appli.route("POST", "/api/ouvrir")
    def ouvrir(requete):
        quoi = requete.json().get("quoi")
        programme = ANCIENNES.get(quoi) if isinstance(quoi, str) else None
        if programme is None:
            raise Erreur(400, "Appli inconnue.")
        if not detacher(f"{BIN}/{programme}"):
            raise Erreur(502, "Cette appli n'a pas pu s'ouvrir.")
        return {}

    appli.base = base
    appli.agenda = agenda
    appli.notes = notes
    return appli


def rappels():
    """Chaque matin et à la connexion (smoky-agenda-reminders.timer) : relit l'emploi du temps et
    prépare les rappels des 36 prochaines heures. Tant que le nouvel agenda n'a pas ton emploi du
    temps, l'ancien Smoky Agenda continue de préparer les siens."""
    code = 0
    try:
        agenda = Agenda(Base())
        agenda.ramasser_telechargements()
        if agenda.reglages()["lien"]:
            agenda.rafraichir_lien(attendre=True, delai=20)
        print(f"smoky : {agenda.apres_changement()} rappel(s) préparé(s)")
        relais = agenda.prend_le_relais()
    except (OSError, RuntimeError, sqlite3.Error) as e:
        print(f"smoky : rappels impossibles ({e})", file=sys.stderr)
        code, relais = 1, False
    ancien = Path.home() / ".local/share/smoky-agenda/agenda.json"
    if not relais and ANCIEN_AGENDA.is_file() and ancien.is_file():
        try:
            subprocess.run([sys.executable, "-I", str(ANCIEN_AGENDA), "--reminders"], timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"smoky : rappels de l'ancien Agenda impossibles ({e})", file=sys.stderr)
    return code


def main(argv=None):
    p = argparse.ArgumentParser(prog="smoky", description="Serveur local de l'appli Smoky.")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--page", default=str(PAGE), help="dossier de la page (HTML, CSS, JS)")
    p.add_argument("--arret-auto", type=float, default=None, metavar="S",
                   help="s'arrêter quand plus aucune fenêtre n'est ouverte depuis S secondes")
    p.add_argument("--profil", default=None, metavar="DOSSIER",
                   help="dossier de profil du navigateur de l'appli : tant qu'il tourne, le serveur reste")
    p.add_argument("--rappels", action="store_true",
                   help="préparer les rappels de l'agenda (et le ménage pendant les cours), puis s'arrêter")
    args = p.parse_args(argv)
    if args.rappels:
        return rappels()
    present = (lambda: navigateur_ouvert(args.profil)) if args.profil else None
    try:
        appli = construire(args.page, args.port, arret_auto=args.arret_auto, present=present)
        appli.servir()
    except (OSError, RuntimeError, sqlite3.Error) as e:
        # port déjà pris, mémoire illisible ou venue d'une version plus récente…
        print(f"smoky : démarrage impossible ({e})", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
