"""Le serveur de Smoky :
    /usr/lib/smoky/lancer.py [--port N] [--page DOSSIER] [--arret-auto SECONDES [--profil DOSSIER]]

Le lanceur /usr/bin/smoky s'en charge ; le port et le code d'accès sont écrits dans
$XDG_RUNTIME_DIR/smoky/serveur.json (lisible par toi seul).
"""
import argparse
import sqlite3
import sys
from pathlib import Path

from . import PORT, VERSION
from .base import Base
from .commandes import BIN, detacher, navigateur_ouvert
from .serveur import Appli, Erreur
from .systeme import Systeme
from .taches import Taches

# /usr/lib/smoky/smoky/__main__.py → /usr/share/smoky (pareil dans le dépôt, sous system_files/)
PAGE = Path(__file__).resolve().parents[3] / "share/smoky"

# Applis pas encore refaites dans Smoky : elles s'ouvrent à part, comme avant.
ANCIENNES = {"notes": "smoky-notes", "agenda": "smoky-agenda", "mail": "smoky-mail", "maison": "smoky-home"}


def construire(page, port=PORT, arret_auto=None, jeton=None, base=None, present=None):
    appli = Appli(page, port, jeton=jeton, arret_auto=arret_auto, present=present)
    base = base or Base()
    taches = Taches(base)
    systeme = Systeme(prevenir=lambda quoi: appli.flux.publier("change", {"quoi": quoi}))

    def prevenir_taches(resultat):
        """Les autres fenêtres ouvertes relisent la liste."""
        appli.flux.publier("change", {"quoi": "taches"})
        return resultat

    @appli.route("GET", "/api/aujourdhui")
    def aujourdhui(requete):
        return {"taches": taches.liste(), "systeme": systeme.resume(), "version": VERSION}

    @appli.route("POST", "/api/taches")
    def tache_creer(requete):
        return 201, prevenir_taches(taches.creer(requete.json()))

    @appli.route("POST", "/api/taches/<id>")
    def tache_modifier(requete):
        return prevenir_taches(taches.modifier(requete.morceaux["id"], requete.json()))

    @appli.route("DELETE", "/api/taches/<id>")
    def tache_supprimer(requete):
        return prevenir_taches(taches.supprimer(requete.morceaux["id"]))

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
    return appli


def main(argv=None):
    p = argparse.ArgumentParser(prog="smoky", description="Serveur local de l'appli Smoky.")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--page", default=str(PAGE), help="dossier de la page (HTML, CSS, JS)")
    p.add_argument("--arret-auto", type=float, default=None, metavar="S",
                   help="s'arrêter quand plus aucune fenêtre n'est ouverte depuis S secondes")
    p.add_argument("--profil", default=None, metavar="DOSSIER",
                   help="dossier de profil du navigateur de l'appli : tant qu'il tourne, le serveur reste")
    args = p.parse_args(argv)
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
