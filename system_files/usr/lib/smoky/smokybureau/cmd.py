"""smoky-bureau-cmd — commandes du bureau Smoky (utilisées par les raccourcis clavier et la veille).

  smoky-bureau-cmd lanceur | panneau | verrouiller | veille-si-batterie
  smoky-bureau-cmd volume plus|moins|muet     micro muet     luminosite plus|moins
  smoky-bureau-cmd capture [zone]             ecran eteindre|allumer
  smoky-bureau-cmd veille-lancer | nuit-lancer | preparer-labwc DOSSIER   (services du bureau)
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


LIEU_DEFAUT = {"lat": 50.36, "lon": 3.52}    # Valenciennes ; « lieu » dans ~/.config/smoky/bureau.json


def reglage(schema, cle, defaut):
    """Un réglage de ton profil (mêmes noms que sous GNOME, voir fr.smoky.bureau-compat.gschema.xml)."""
    source = Gio.SettingsSchemaSource.get_default()
    s = source.lookup(schema, True) if source else None
    if s is None or not s.has_key(cle):
        return defaut
    return Gio.Settings.new(schema).get_value(cle).unpack()


def reglages_veille():
    puissance = "org.gnome.settings-daemon.plugins.power"
    return {"idle_delay": reglage("org.gnome.desktop.session", "idle-delay", 300),
            "lock_delay": reglage("org.gnome.desktop.screensaver", "lock-delay", 0),
            "sleep_battery": reglage(puissance, "sleep-inactive-battery-timeout", 900),
            "sleep_battery_type": reglage(puissance, "sleep-inactive-battery-type", "suspend"),
            "sleep_ac": reglage(puissance, "sleep-inactive-ac-timeout", 1800),
            "sleep_ac_type": reglage(puissance, "sleep-inactive-ac-type", "nothing")}


def reglages_nuit():
    couleur = "org.gnome.settings-daemon.plugins.color"
    return {"temperature": reglage(couleur, "night-light-temperature", 3500),
            "automatique": reglage(couleur, "night-light-schedule-automatic", True),
            "debut": reglage(couleur, "night-light-schedule-from", 20.0),
            "fin": reglage(couleur, "night-light-schedule-to", 7.0)}


def preparer_labwc(dossier):
    """Pavé tactile de labwc selon tes réglages (toucher pour cliquer, défilement naturel)."""
    import re
    rc = Path(dossier) / "rc.xml"
    if not rc.is_file():
        return
    pave = "org.gnome.desktop.peripherals.touchpad"
    oui = lambda v: "yes" if v else "no"                                       # noqa: E731
    texte = rc.read_text()
    texte = re.sub(r"<tap>\w+</tap>", f"<tap>{oui(reglage(pave, 'tap-to-click', True))}</tap>", texte)
    texte = re.sub(r"<naturalScroll>\w+</naturalScroll>",
                   f"<naturalScroll>{oui(reglage(pave, 'natural-scroll', True))}</naturalScroll>", texte)
    rc.write_text(texte)


def bulle(genre, valeur):
    bureau("Bulle", GLib.Variant("(si)", (genre, int(valeur))))


def notifier(titre, corps, icone="dialog-information"):
    commun.commande("notify-send", "-a", "Smoky OS", "-i", icone, titre, corps)


def volume(action):
    cible = "@DEFAULT_AUDIO_SINK@"
    limite = "1.5" if reglage("org.gnome.desktop.sound", "allow-volume-above-100-percent", False) else "1.0"
    if action == "muet":
        commun.commande("wpctl", "set-mute", cible, "toggle")
    else:
        commun.commande("wpctl", "set-mute", cible, "0")
        commun.commande("wpctl", "set-volume", "-l", limite, cible, "5%+" if action == "plus" else "5%-")
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
    elif action == "veille-si-secteur":
        if commun.secteur():
            os.execvp("systemctl", ["systemctl", "suspend"])
    elif action == "veille-lancer":
        args = commun.arguments_veille(reglages_veille())
        os.execvp(args[0], args)
    elif action == "nuit-lancer":
        lieu = commun.lire_json(commun.BUREAU, {}).get("lieu") or LIEU_DEFAUT
        args = commun.arguments_nuit(reglages_nuit(), lieu)
        os.execvp(args[0], args)
    elif action == "preparer-labwc" and reste:
        preparer_labwc(reste[0])
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
