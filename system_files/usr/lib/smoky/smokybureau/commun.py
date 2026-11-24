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


def alerte_batterie(niveau, en_charge, deja):
    """Quelle alerte donner ? (None, 'faible' à 15 %, 'critique' à 7 %), une seule fois par décharge.
    `deja` = ensemble des alertes déjà données ; renvoie (alerte, nouvel ensemble)."""
    if en_charge or niveau is None:
        return None, set()
    for nom, seuil in (("critique", 7), ("faible", 15)):
        if niveau <= seuil:
            if nom in deja:
                return None, deja
            return nom, deja | {nom, "faible"}
    return None, deja


def arguments_veille(r):
    """swayidle selon tes réglages (mêmes noms que sous GNOME) : écran éteint après `idle_delay`
    secondes (0 = jamais), verrouillage `lock_delay` secondes plus tard, mise en veille après
    `sleep_battery` sur batterie et `sleep_ac` sur secteur si leur type est « suspend »."""
    args = ["swayidle", "-w"]
    if r.get("idle_delay", 300) > 0:
        eteint = r.get("idle_delay", 300)
        args += ["timeout", str(eteint), "smoky-bureau-cmd ecran eteindre", "resume", "smoky-bureau-cmd ecran allumer",
                 "timeout", str(eteint + max(0, r.get("lock_delay", 0))), "smoky-bureau-cmd verrouiller"]
    if r.get("sleep_battery_type", "suspend") == "suspend" and r.get("sleep_battery", 900) > 0:
        args += ["timeout", str(r.get("sleep_battery", 900)), "smoky-bureau-cmd veille-si-batterie"]
    if r.get("sleep_ac_type", "nothing") == "suspend" and r.get("sleep_ac", 1800) > 0:
        args += ["timeout", str(r.get("sleep_ac", 1800)), "smoky-bureau-cmd veille-si-secteur"]
    return args + ["before-sleep", "smoky-bureau-cmd verrouiller"]


def arguments_nuit(r, lieu=None):
    """wlsunset selon tes réglages : température (K), et soit le lever et le coucher du soleil à
    l'endroit de ta météo (« automatique »), soit des heures fixes (20 h → 7 h par défaut)."""
    temperature = max(1900, min(6400, int(r.get("temperature", 3500))))
    args = ["wlsunset", "-T", "6500", "-t", str(temperature)]
    if r.get("automatique", True) and lieu and lieu.get("lat") is not None and lieu.get("lon") is not None:
        return args + ["-l", f"{float(lieu['lat']):.2f}", "-L", f"{float(lieu['lon']):.2f}"]

    def heure(h):
        h = float(h) % 24
        return f"{int(h):02d}:{round(h % 1 * 60) % 60:02d}"
    return args + ["-s", heure(r.get("debut", 20.0)), "-S", heure(r.get("fin", 7.0))]


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


# --- clavier tactile de la connexion et du verrouillage -----------------------------------------
# AZERTY. Chaque caractère imprimable d'un clavier (ASCII 32 à 126) est sur une des couches, pour
# qu'un mot de passe puisse toujours se taper au doigt.
COUCHES_CLAVIER = {
    "abc": ["a z e r t y u i o p", "q s d f g h j k l m", "⇧ w x c v b n ' ⌫", "123 àé espace . ⏎"],
    "ABC": ["A Z E R T Y U I O P", "Q S D F G H J K L M", "⇧ W X C V B N ' ⌫", "123 àé espace . ⏎"],
    "123": ["1 2 3 4 5 6 7 8 9 0", "@ # & _ - ( ) = % +", "#+= ! ? , ; : / * ⌫", "abc àé espace . ⏎"],
    "#+=": ["[ ] { } < > ^ ~ ` |", "\\ $ € £ § ° µ \" « »", "123 ' ! ? , ; : ⌫", "abc àé espace . ⏎"],
    "àé": ["é è ê ë à â ç ù û ü", "ô î ï œ æ É È À Ç Ê", "Ô Î Û Ë Ï Ü Œ Æ ⌫", "abc 123 espace . ⏎"],
}
TOUCHES_SPECIALES = {"⇧", "⌫", "⏎", "espace", "abc", "123", "#+=", "àé"}


def touche_clavier(texte, etat, touche):
    """Un appui sur le clavier tactile. etat = (couche, majuscules verrouillées).
    Renvoie (texte, etat, valider). ⇧ une fois : une majuscule ; deux fois : toutes.
    Après une lettre accentuée, retour aux lettres ; chiffres et symboles restent affichés."""
    couche, verrou = etat
    if touche == "⌫":
        return texte[:-1], etat, False
    if touche == "⏎":
        return texte, etat, True
    if touche == "⇧":
        if couche != "ABC":
            return texte, ("ABC", False), False
        return texte, (("ABC", True) if not verrou else ("abc", False)), False
    if touche in COUCHES_CLAVIER and touche != "ABC":
        return texte, (touche, False), False
    texte += " " if touche == "espace" else touche
    if (couche == "ABC" and not verrou) or couche == "àé":
        etat = ("abc", False)               # une majuscule, une lettre accentuée : puis les lettres
    return texte, etat, False


def claviers_physiques(texte=None):
    """Les vrais claviers branchés, d'après /proc/bus/input/devices, avec la règle d'udev
    (ID_INPUT_KEYBOARD) : toutes les touches d'Échap à D présentes. Les boutons (marche,
    volume, touches ASUS) n'en sont pas. None si on ne peut pas savoir."""
    if texte is None:
        try:
            texte = Path("/proc/bus/input/devices").read_text(errors="replace")
        except OSError:
            return None
    noms = []
    for bloc in texte.split("\n\n"):
        nom, touches = "", []
        for ligne in bloc.splitlines():
            if ligne.startswith("N: Name="):
                nom = ligne[8:].strip().strip('"')
            elif ligne.startswith("B: KEY="):
                touches = ligne[7:].split()
        try:
            if touches and int(touches[-1], 16) & 0xFFFFFFFE == 0xFFFFFFFE:
                noms.append(nom)
        except ValueError:
            pass
    return noms


# --- clavier à l'écran de la session (clavier_ecran.py) ------------------------------------------
# Mêmes couches que celui de la connexion, plus ce qui sert en écrivant : virgule sous la main,
# flèches, tabulation, et ⌄ pour le ranger.
COUCHES_SESSION = {
    "abc": ["a z e r t y u i o p", "q s d f g h j k l m", "⇧ w x c v b n ' ⌫", "123 àé , espace . ⏎ ⌄"],
    "ABC": ["A Z E R T Y U I O P", "Q S D F G H J K L M", "⇧ W X C V B N ' ⌫", "123 àé , espace . ⏎ ⌄"],
    "123": ["1 2 3 4 5 6 7 8 9 0", "@ # & _ - ( ) = % +", "#+= ! ? ; : / * \" ⌫", "abc ← espace → . ⏎ ⌄"],
    "#+=": ["[ ] { } < > ^ ~ ` |", "\\ $ € £ § ° µ ² « »", "123 ⇥ ' ! ? ; : ⌫", "abc ← espace → . ⏎ ⌄"],
    "àé": ["é è ê ë à â ç ù û ü", "ô î ï œ æ É È À Ç Ê", "Ô Î Û Ë Ï Ü Œ Æ ⌫", "abc 123 , espace . ⏎ ⌄"],
}
TOUCHES_ENVOYEES = {"⌫": "BackSpace", "⏎": "Return", "⇥": "Tab", "←": "Left", "→": "Right", " ": "space"}
TOUCHES_A_REPETER = {"⌫", "←", "→"}


def touche_session(etat, touche):
    """Un appui sur le clavier de la session → (nouvel état, à envoyer) ; à envoyer est un
    caractère, une touche de TOUCHES_ENVOYEES, « cacher », ou None (changement de couche)."""
    if touche == "⌄":
        return etat, "cacher"
    if touche in TOUCHES_ENVOYEES:
        return etat, touche
    texte, etat, _ = touche_clavier("", etat, touche)
    return etat, (texte or None)


def caracteres_session():
    """Tout ce que le clavier de la session peut envoyer, dans l'ordre des couches."""
    vus = []
    for rangees in COUCHES_SESSION.values():
        for t in " ".join(rangees).split(" "):
            c = " " if t == "espace" else t
            if (c in TOUCHES_ENVOYEES or c not in TOUCHES_SPECIALES | {"⌄"}) and c not in vus:
                vus.append(c)
    return vus


# Touches « ordinaires » d'un clavier (codes evdev) : on n'utilise qu'elles, pour que Chrome, qui
# déduit aussi le nom de la touche (KeyboardEvent.code) du code, ne voie jamais un Ctrl, un Échap
# ou une touche inconnue. Lettres et chiffres gardent leur place ; le reste va sur les 4 niveaux
# (rien, Maj, Alt Gr, Maj + Alt Gr) des touches de ponctuation, puis des chiffres et des lettres.
_LETTRES = dict(zip("qwertyuiop", range(16, 26))) | dict(zip("asdfghjkl", range(30, 39))) \
    | dict(zip("zxcvbnm", range(44, 51)))
_CHIFFRES = dict(zip("1234567890", range(2, 12)))
_PONCTUATION = [12, 13, 26, 27, 39, 40, 41, 43, 51, 52, 53, 86]
_SPECIALES_EVDEV = {"⌫": 14, "⇥": 15, "⏎": 28, " ": 57, "←": 105, "→": 106}
MAJ, ALTGR = 0x1, 0x80                       # Shift et Mod5 (Alt Gr = LevelThree, voir la keymap)
_NIVEAUX = (0, MAJ, ALTGR, MAJ | ALTGR)


def _nom_symbole(c):
    if c in TOUCHES_ENVOYEES:
        return TOUCHES_ENVOYEES[c]
    if c.isascii() and c.isalnum():
        return c                                 # a…z, A…Z, 0…9 : leur propre nom
    return f"U{ord(c):04X}"                      # le reste par son point de code Unicode


def keymap_clavier(caracteres):
    """Disposition XKB du clavier à l'écran : le moteur d'affichage la passe à l'appli, qui
    retrouve le caractère quelle que soit la disposition du vrai clavier.
    Renvoie (texte de la keymap, {caractère: (code evdev, modificateurs)})."""
    cases = {}                                   # code evdev → [symbole par niveau]
    codes = {}

    def poser(c, code, niveau):
        cases.setdefault(code, [None] * 4)[niveau] = c
        codes[c] = (code, _NIVEAUX[niveau])

    restants = []
    for c in dict.fromkeys(caracteres):
        if c in _SPECIALES_EVDEV:
            codes[c] = (_SPECIALES_EVDEV[c], 0)
        elif c in _LETTRES:
            poser(c, _LETTRES[c], 0)
        elif c.lower() in _LETTRES and c.isupper():
            poser(c, _LETTRES[c.lower()], 1)
        elif c in _CHIFFRES:
            poser(c, _CHIFFRES[c], 0)
        else:
            restants.append(c)
    libres = [(code, n) for n in range(4) for code in _PONCTUATION] + \
             [(code, n) for n in range(1, 4) for code in _CHIFFRES.values()] + \
             [(code, n) for n in range(2, 4) for code in _LETTRES.values()]
    libres = [(code, n) for code, n in libres if cases.get(code, [None] * 4)[n] is None]
    if len(restants) > len(libres):
        raise ValueError("trop de caractères pour une seule disposition")
    for c, (code, n) in zip(restants, libres):
        poser(c, code, n)
    symboles = "".join(
        f"  key <K{code}> {{ type= \"FOUR_LEVEL\", [ {', '.join(_nom_symbole(x) if x else 'NoSymbol' for x in niv)} ] }};\n"
        for code, niv in sorted(cases.items()))
    symboles += "".join(f"  key <K{code}> {{ [ {_nom_symbole(c)} ] }};\n" for c, code in _SPECIALES_EVDEV.items()
                        if c in codes)
    tous = sorted(set(cases) | {code for c, code in _SPECIALES_EVDEV.items() if c in codes} | {100})
    texte = ("xkb_keymap {\n"
             "xkb_keycodes \"smoky\" {\n  minimum = 8;\n  maximum = 255;\n"
             + "".join(f"  <K{code}> = {code + 8};\n" for code in tous) +
             "};\n"
             "xkb_types \"smoky\" { include \"complete\" };\n"
             "xkb_compatibility \"smoky\" { include \"complete\" };\n"
             "xkb_symbols \"smoky\" {\n"
             + symboles +
             "  key <K100> { [ ISO_Level3_Shift ] };\n"      # Alt Gr : jamais appuyée, elle lie LevelThree à Mod5
             "  modifier_map Mod5 { <K100> };\n"
             "};\n};\n")
    return texte, codes
