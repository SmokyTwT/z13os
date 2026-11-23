"""Smoky OS — bureau : ce que partagent la barre, le dock, l'énergie et le verrouillage.

Réglages, liste des applis du dock (avec la reprise unique du dock GNOME), fond d'écran,
batterie lue directement dans /sys (aucun processus lancé, aucun réveil inutile).
"""
import ast
import json
import os
import subprocess
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "smoky"
BUREAU = CONFIG / "bureau.json"
ADAPTIVE = CONFIG / "adaptive.json"
DOCK_DEFAUT = Path("/usr/share/smoky-bureau/dock.json")
FOND_DEFAUT = "/usr/share/backgrounds/z13os/smokyos.jpg"
SYS = Path(os.environ.get("SMOKY_SYS", "/sys"))
CSS = Path(os.environ.get("SMOKY_BUREAU_CSS", "/usr/share/smoky-bureau/bureau.css"))


def lire_json(chemin, defaut):
    try:
        donnees = json.loads(Path(chemin).read_text())
        return {**defaut, **donnees} if isinstance(defaut, dict) and isinstance(donnees, dict) else donnees
    except (OSError, ValueError):
        return dict(defaut) if isinstance(defaut, dict) else defaut


def ecrire_json(chemin, donnees):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text(json.dumps(donnees, indent=1, ensure_ascii=False))
    os.replace(tmp, chemin)


def commande(*args, delai=10):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=delai).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


# --- Dock ----------------------------------------------------------------------------------
def favoris_gnome():
    """Le dock de GNOME tel que tu l'avais réglé (liste vide si jamais réglé ou illisible)."""
    brut = commande("dconf", "read", "/org/gnome/shell/favorite-apps").strip()
    if brut.startswith("@as "):
        brut = brut[4:]
    try:
        liste = ast.literal_eval(brut) if brut else []
    except (ValueError, SyntaxError):
        return []
    return [x for x in liste if isinstance(x, str) and x.endswith(".desktop")]


def dock():
    """Applis du dock. Première fois : reprend le dock GNOME personnalisé, sinon celui de Smoky."""
    reglages = lire_json(BUREAU, {})
    if isinstance(reglages.get("dock"), list):
        return reglages["dock"]
    liste = favoris_gnome() or lire_json(DOCK_DEFAUT, {"dock": []}).get("dock", [])
    reglages["dock"] = liste
    reglages["dock_repris_de_gnome"] = bool(favoris_gnome())
    ecrire_json(BUREAU, reglages)
    return liste


def enregistrer_dock(liste):
    reglages = lire_json(BUREAU, {})
    reglages["dock"] = list(liste)
    ecrire_json(BUREAU, reglages)


# --- Fond d'écran ------------------------------------------------------------------------------
def fond_ecran():
    """Le fond choisi auparavant (réglage GNOME conservé dans ton profil), sinon celui de Smoky."""
    uri = commande("gsettings", "get", "org.gnome.desktop.background", "picture-uri-dark").strip().strip("'")
    if not uri.startswith("file://"):
        uri = commande("gsettings", "get", "org.gnome.desktop.background", "picture-uri").strip().strip("'")
    chemin = uri[len("file://"):] if uri.startswith("file://") else ""
    from urllib.parse import unquote
    chemin = unquote(chemin)
    return chemin if chemin and Path(chemin).is_file() else FOND_DEFAUT


# --- Énergie -----------------------------------------------------------------------------------
def _lire(chemin, defaut=""):
    try:
        return Path(chemin).read_text().strip()
    except OSError:
        return defaut


def batterie_dossier():
    for d in sorted((SYS / "class/power_supply").glob("BAT*")):
        if _lire(d / "type") == "Battery":
            return d
    return None


def secteur():
    """True si le chargeur est branché (ou s'il n'y a pas de batterie : PC fixe, machine virtuelle)."""
    for d in (SYS / "class/power_supply").glob("*"):
        if _lire(d / "type") == "Mains":
            return _lire(d / "online") == "1"
    return batterie_dossier() is None


class Batterie:
    """Niveau et temps restant, lissé sur quelques minutes pour ne pas sauter à chaque instant."""

    def __init__(self):
        self.watts_lisses = None

    def etat(self):
        d = batterie_dossier()
        if d is None:
            return None
        def nombre(nom):
            v = _lire(d / nom)
            return int(v) if v.lstrip("-").isdigit() else None
        niveau = nombre("capacity")
        statut = _lire(d / "status", "Unknown")
        puissance = nombre("power_now")
        energie = nombre("energy_now")
        if puissance is None and nombre("current_now") is not None and nombre("voltage_now"):
            puissance = abs(nombre("current_now")) * nombre("voltage_now") // 1_000_000
            if nombre("charge_now") is not None:
                energie = nombre("charge_now") * nombre("voltage_now") // 1_000_000
        restant = None
        if statut == "Discharging" and puissance and puissance > 500_000:
            w = puissance / 1e6
            self.watts_lisses = w if self.watts_lisses is None else 0.8 * self.watts_lisses + 0.2 * w
            if energie:
                restant = int(energie / 1e6 / self.watts_lisses * 60)
        else:
            self.watts_lisses = None
        return {"niveau": niveau, "statut": statut, "minutes": restant,
                "watts": round(self.watts_lisses, 1) if self.watts_lisses else None,
                "limite": nombre("charge_control_end_threshold")}


def duree(minutes):
    if minutes is None:
        return ""
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


# --- Luminosité (logind : aucun droit administrateur) -----------------------------------------
def retroeclairage():
    for d in sorted((SYS / "class/backlight").glob("*")):
        mx = _lire(d / "max_brightness")
        if mx.isdigit() and int(mx) > 0:
            return d
    return None


def luminosite():
    d = retroeclairage()
    if d is None:
        return None
    return round(100 * int(_lire(d / "brightness", "0")) / int(_lire(d / "max_brightness", "1")))


def regler_luminosite(pourcent):
    d = retroeclairage()
    if d is None:
        return None
    pourcent = max(3, min(100, int(pourcent)))           # jamais tout noir par erreur
    valeur = round(int(_lire(d / "max_brightness")) * pourcent / 100)
    commande("busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
             "org.freedesktop.login1.Session", "SetBrightness", "ssu", "backlight", d.name, str(valeur))
    return pourcent


# --- Son (PipeWire) ------------------------------------------------------------------------------
def volume():
    """(pourcent, muet) de la sortie son, ou (None, False) si pas de son."""
    sortie = commande("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    parts = sortie.split()
    try:
        return round(float(parts[1]) * 100), "[MUTED]" in sortie
    except (IndexError, ValueError):
        return None, False
