"""smoky-bureau-cmd — commandes du bureau Smoky (utilisées par les raccourcis clavier et la veille).

  smoky-bureau-cmd lanceur | panneau | verrouiller | veille-si-batterie
  smoky-bureau-cmd volume plus|moins|muet     micro muet     luminosite plus|moins
  smoky-bureau-cmd capture [zone]             ecran eteindre|allumer
"""
import os
import sys
import time
from pathlib import Path

from gi.repository import Gio, GLib

from . import commun


def bureau(methode, params=None, signature=None):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        r = bus.call_sync("fr.smoky.Bureau", "/fr/smoky/Bureau", "fr.smoky.Bureau", methode, params,
                          GLib.VariantType.new(signature) if signature else None,
                          Gio.DBusCallFlags.NONE, 3000, None)
        return r.unpack() if r else None
    except GLib.Error as e:
        print("bureau Smoky injoignable :", e.message, file=sys.stderr)
        return None


def bulle(genre, valeur):
    bureau("Bulle", GLib.Variant("(si)", (genre, int(valeur))))


def notifier(titre, corps, icone="dialog-information"):
    commun.commande("notify-send", "-a", "Smoky OS", "-i", icone, titre, corps)


def volume(action):
    cible = "@DEFAULT_AUDIO_SINK@"
    if action == "muet":
        commun.commande("wpctl", "set-mute", cible, "toggle")
    else:
        commun.commande("wpctl", "set-mute", cible, "0")
        commun.commande("wpctl", "set-volume", "-l", "1.0", cible, "5%+" if action == "plus" else "5%-")
    pourcent, muet = commun.volume()
    if pourcent is not None:
        bulle("volume", -1 if muet else pourcent)


def micro():
    commun.commande("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle")
    muet = "[MUTED]" in commun.commande("wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@")
    bulle("micro", -1 if muet else 100)


def luminosite(action):
    actuelle = commun.luminosite()
    if actuelle is None:
        return
    pas = 5 if actuelle <= 20 else 10          # pas fins en bas, là où l'œil est sensible
    nouvelle = commun.regler_luminosite(actuelle + (pas if action == "plus" else -pas))
    if nouvelle is not None:
        bulle("luminosite", nouvelle)


def capture(zone=False):
    dossier = Path(commun.commande("xdg-user-dir", "PICTURES").strip() or Path.home() / "Images") / "Captures d'écran"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / time.strftime("Capture du %Y-%m-%d à %H.%M.%S.png")
    args = ["grim"]
    if zone:
        geometrie = commun.commande("slurp", delai=120).strip()
        if not geometrie:
            return
        args += ["-g", geometrie]
    commun.commande(*args, str(fichier))
    if fichier.exists():
        commun.commande("sh", "-c", f'wl-copy < "{fichier}"')
        notifier("Capture d'écran", f"Enregistrée dans {dossier.name} (et copiée).", "camera-photo")


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    if not args:
        print(__doc__)
        return 2
    action, reste = args[0], args[1:]
    if action == "lanceur":
        bureau("Lanceur")
    elif action == "panneau":
        bureau("Panneau")
    elif action == "verrouiller":
        os.execvp("systemctl", ["systemctl", "--user", "start", "smoky-verrou.service"])
    elif action == "veille-si-batterie":
        if not commun.secteur():
            os.execvp("systemctl", ["systemctl", "suspend"])
    elif action == "volume" and reste:
        volume(reste[0])
    elif action == "micro":
        micro()
    elif action == "luminosite" and reste:
        luminosite(reste[0])
    elif action == "capture":
        capture(zone=bool(reste and reste[0] == "zone"))
    elif action == "ecran" and reste:
        bureau("Ecran", GLib.Variant("(b)", (reste[0] == "allumer",)), "(b)")
    else:
        print(__doc__)
        return 2
    return 0
