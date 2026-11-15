"""Lancer des commandes système : jamais de commande libre, toujours un délai, jamais d'exception."""
import os
import subprocess
from pathlib import Path

# Dossier des lanceurs des autres applis Smoky (changé seulement par les tests)
BIN = os.environ.get("SMOKY_BIN", "/usr/bin")


def lancer(*args, delai=8, entree=None):
    """→ (code, sortie). Code 127 si la commande n'existe pas ou dépasse le délai."""
    try:
        r = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=delai, input=entree,
                           stdin=None if entree is not None else subprocess.DEVNULL)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 127, ""


def detacher(*args):
    """Lance sans attendre (ouvrir une appli, envoyer une notification)."""
    try:
        subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def lire(chemin, defaut=""):
    try:
        return Path(chemin).read_text().strip()
    except (OSError, ValueError):
        return defaut


def notifier(titre, texte, icone="dialog-information"):
    detacher("notify-send", "-a", "Smoky", "-i", icone, titre, texte)


def navigateur_ouvert(profil, proc="/proc"):
    """True si un navigateur tourne avec ce dossier de profil : une fenêtre de l'appli existe encore."""
    cible = f"--user-data-dir={profil}".encode()
    try:
        entrees = [e.name for e in os.scandir(proc) if e.name.isdigit()]
    except OSError:
        return True                                   # impossible de savoir : dans le doute, oui
    for pid in entrees:
        try:
            with open(f"{proc}/{pid}/cmdline", "rb") as f:
                ligne = f.read(16384)
        except OSError:
            continue                                  # processus terminé entre-temps
        ou = ligne.find(cible)
        # l'option entière, pas le début d'un autre dossier (« …/smoky-chrome-autre »)
        if ou >= 0 and ligne[ou + len(cible):ou + len(cible) + 1] in (b"", b"\0", b" "):
            return True
    return False
