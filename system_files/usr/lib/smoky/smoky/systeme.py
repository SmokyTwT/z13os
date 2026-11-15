"""Réglages de la machine : batterie, énergie, écran, carte graphique, réseau, mises à jour…

Chaque action correspond à une commande précise, dans une liste fermée : la page ne peut
demander que ce qui est prévu ici, avec des valeurs vérifiées une à une.

Les fichiers de ~/.config/smoky (adaptive.json, focus.json, charge-once) sont partagés avec
les services de Smoky OS (smoky-adaptive, smoky-focus) : leurs noms et leurs clés ne changent pas.
"""
import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .commandes import BIN, detacher, lancer, lire, notifier
from .serveur import Erreur

DOSSIER = Path.home()
CFG = DOSSIER / ".config/smoky"
ADAPTATIF = CFG / "adaptive.json"
CONCENTRATION = CFG / "focus.json"
MAISON_JETON = DOSSIER / ".config/smoky-home/token"
MAISON_FOND = DOSSIER / ".config/autostart/smoky-home-bg.desktop"
OUTILS = os.environ.get("SMOKY_LIBEXEC", "/usr/libexec/smokyos")
BATTERIE = Path(os.environ.get("SMOKY_BATTERIE", "/sys/class/power_supply/BAT0"))
VPN = "Smoky VPN"
ADAPTATIF_DEFAUT = {"refresh": True, "tablet_mode": False, "vpn_auto": False, "tablet_open_notes": True}
PROFILS_CHROME = (".config/google-chrome", ".config/smoky-chrome", ".config/smoky-notes-chrome",
                  ".config/smoky-center-chrome", ".config/smoky-home-chrome")

# --- Réglages GNOME modifiables (liste fermée : rien d'autre ne peut être changé) -----------------
# nom : (schéma, clé, type GVariant, valeurs permises ; None = interrupteur oui/non)
GNOME = {
    "night_light": ("org.gnome.settings-daemon.plugins.color", "night-light-enabled", "b", None),
    "night_light_temp": ("org.gnome.settings-daemon.plugins.color", "night-light-temperature", "u", (2700, 3500, 4500)),
    "night_light_auto": ("org.gnome.settings-daemon.plugins.color", "night-light-schedule-automatic", "b", None),
    "ambient": ("org.gnome.settings-daemon.plugins.power", "ambient-enabled", "b", None),
    "rotation_lock": ("org.gnome.settings-daemon.peripherals.touchscreen", "orientation-lock", "b", None),
    "text_scale": ("org.gnome.desktop.interface", "text-scaling-factor", "d", (1.0, 1.1, 1.25)),
    "idle_delay": ("org.gnome.desktop.session", "idle-delay", "u", (120, 300, 600, 900, 0)),
    "sleep_battery": ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout", "i", (600, 900, 1800, 3600)),
    "sleep_ac": ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "s", ("suspend", "nothing")),
    "show_banners": ("org.gnome.desktop.notifications", "show-banners", "b", None),
    "lock_notifs": ("org.gnome.desktop.notifications", "show-in-lock-screen", "b", None),
    "lock_delay": ("org.gnome.desktop.screensaver", "lock-delay", "u", (0, 60, 300)),
    "recent_files": ("org.gnome.desktop.privacy", "remember-recent-files", "b", None),
    "old_trash": ("org.gnome.desktop.privacy", "remove-old-trash-files", "b", None),
    "old_temp": ("org.gnome.desktop.privacy", "remove-old-temp-files", "b", None),
    "camera_off": ("org.gnome.desktop.privacy", "disable-camera", "b", None),
    "location": ("org.gnome.system.location", "enabled", "b", None),
    "volume_boost": ("org.gnome.desktop.sound", "allow-volume-above-100-percent", "b", None),
    "event_sounds": ("org.gnome.desktop.sound", "event-sounds", "b", None),
    "dock_size": ("org.gnome.shell.extensions.dash-to-dock", "dash-max-icon-size", "i", (44, 52, 60)),
    "dock_fixed": ("org.gnome.shell.extensions.dash-to-dock", "dock-fixed", "b", None),
    "battery_pct": ("org.gnome.desktop.interface", "show-battery-percentage", "b", None),
    "hot_corner": ("org.gnome.desktop.interface", "enable-hot-corners", "b", None),
    "animations": ("org.gnome.desktop.interface", "enable-animations", "b", None),
    "tap_click": ("org.gnome.desktop.peripherals.touchpad", "tap-to-click", "b", None),
    "natural_scroll": ("org.gnome.desktop.peripherals.touchpad", "natural-scroll", "b", None),
}

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    Gio = None
_SCHEMAS = {}
# Ce serveur n'a pas de boucle GLib : sans elle, GSettings ne voit jamais les changements faits
# ailleurs (menu en haut à droite, Paramètres…). On traite donc les notifications en attente
# avant chaque lecture, sous verrou (plusieurs requêtes arrivent en même temps).
_VERROU_GNOME = threading.Lock()


def _rattraper():
    contexte = GLib.MainContext.default()
    for _ in range(200):
        if not contexte.iteration(False):
            break


def _schema(nom):
    if nom not in _SCHEMAS:
        source = Gio.SettingsSchemaSource.get_default()
        _SCHEMAS[nom] = Gio.Settings.new(nom) if source and source.lookup(nom, True) else None
    return _SCHEMAS[nom]


def gnome_lire():
    valeurs = {}
    if Gio is None:
        return valeurs
    with _VERROU_GNOME:
        _rattraper()
        for nom, (schema, cle, _type, _permis) in GNOME.items():
            reglages = _schema(schema)
            if reglages is not None and reglages.props.settings_schema.has_key(cle):
                valeurs[nom] = reglages.get_value(cle).unpack()
    return valeurs


def gnome_valeur(nom, valeur):
    """Valeur vérifiée, prête à écrire ; lève Erreur si elle n'est pas dans la liste permise."""
    if nom not in GNOME or isinstance(valeur, (dict, list)):
        raise Erreur(400, "Réglage inconnu.")
    permis = GNOME[nom][3]
    if permis is None:
        if not isinstance(valeur, bool):
            raise Erreur(400, "Valeur refusée pour ce réglage.")
        return valeur
    trouve = [v for v in permis if v == valeur and not isinstance(valeur, bool)]
    if not trouve:
        raise Erreur(400, "Valeur refusée pour ce réglage.")
    return trouve[0]


def gnome_ecrire(nom, valeur):
    valeur = gnome_valeur(nom, valeur)
    if Gio is None:
        return False
    schema, cle, type_variant, _permis = GNOME[nom]
    with _VERROU_GNOME:
        _rattraper()
        reglages = _schema(schema)
        if reglages is None or not reglages.props.settings_schema.has_key(cle):
            return False
        reglages.set_value(cle, GLib.Variant(type_variant, valeur))
        Gio.Settings.sync()
    return True


# --- Petits outils ---------------------------------------------------------------------------
def taille(n):
    for unite in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024 or unite == "To":
            return f"{n:.0f} {unite}" if unite in ("o", "Ko") else f"{n:.1f} {unite}".replace(".", ",")
        n /= 1024


def poids_dossier(chemin):
    total = 0
    for racine, _dossiers, fichiers in os.walk(chemin):
        for f in fichiers:
            try:
                total += os.lstat(os.path.join(racine, f)).st_size
            except OSError:
                pass
    return total


def charger(chemin, defaut):
    try:
        lu = json.loads(Path(chemin).read_text())
        return {**defaut, **lu} if isinstance(lu, dict) else dict(defaut)
    except (OSError, ValueError):
        return dict(defaut)


def enregistrer(chemin, donnees):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(donnees, indent=1))
    os.replace(tmp, chemin)


def _json(texte):
    try:
        lu = json.loads(texte)
        return lu if isinstance(lu, dict) else {}
    except ValueError:
        return {}


class Systeme:
    """État et actions. Les lectures lentes sont gardées en mémoire quelques dizaines de secondes."""

    def __init__(self, prevenir=None):
        self.prevenir = prevenir or (lambda *a: None)      # prévient la page qu'un travail est fini
        self.maj = {"en_cours": False, "resultat": ""}
        self.travaux = {"applis": {"en_cours": False, "resultat": ""}, "nettoyage": {"en_cours": False, "resultat": ""}}
        self._image = {"a": 0.0, "image": "", "prete": False}
        self._cours = {"a": 0.0, "donnees": {"connected": False}}
        self._stockage = {"a": 0.0, "donnees": {}}
        self._windows = []
        self._securise = []
        self._gardes = {}                                   # nom → (instant, valeur) des lectures lentes
        self._bassin = ThreadPoolExecutor(max_workers=8)

    # --- lectures ---
    def _garde(self, nom, duree, lecture):
        """Valeur gardée en mémoire « duree » secondes : inutile de relancer un programme à chaque rafraîchissement."""
        connu = self._gardes.get(nom)
        if connu and time.time() - connu[0] < duree:
            return connu[1]
        valeur = lecture()
        self._gardes[nom] = (time.time(), valeur)
        return valeur

    def image(self, frais=False):
        """rpm-ostree status est lent : relu au plus une fois par minute (ou après une mise à jour)."""
        if frais or time.time() - self._image["a"] > 60:
            _code, sortie = lancer("rpm-ostree", "status", "--json", delai=10)
            deploiements = _json(sortie).get("deployments", [])
            if isinstance(deploiements, list) and deploiements:
                actuel = next((d for d in deploiements if isinstance(d, dict) and d.get("booted")), {})
                self._image.update(image=actuel.get("container-image-reference", ""),
                                   prete=any(isinstance(d, dict) and d.get("staged") for d in deploiements))
            self._image["a"] = time.time()
        return self._image["image"], self._image["prete"]

    def cours(self):
        """Lance Python et le trousseau : relu au plus toutes les 60 s (ou après une action)."""
        if time.time() - self._cours["a"] > 60:
            code, sortie = lancer("python3", f"{OUTILS}/smoky-moodle.py", "status", delai=10)
            self._cours.update(a=time.time(), donnees=(_json(sortie) or {"connected": False}) if code == 0 else {"connected": False})
        return self._cours["donnees"]

    def windows(self):
        if not self._windows:                          # les entrées du firmware ne changent pas en cours de route
            _code, sortie = lancer("efibootmgr", delai=5)
            trouve = re.search(r"^Boot([0-9A-Fa-f]{4})\*?\s+Windows Boot Manager", sortie, re.M)
            self._windows.append(trouve.group(1) if trouve else None)
        return self._windows[0]

    def demarrage_securise(self):
        """« on », « off » ou « » (inconnu) ; ne change pas sans redémarrer, donc lu une fois."""
        if not self._securise:
            _code, sortie = lancer("mokutil", "--sb-state", delai=5)
            self._securise.append("on" if "enabled" in sortie else "off" if "disabled" in sortie else "")
        return self._securise[0]

    def stockage(self):
        """Tailles des dossiers : coûteux, recalculé au plus toutes les 2 minutes."""
        disque = shutil.disk_usage(DOSSIER)
        if time.time() - self._stockage["a"] > 120:
            self._stockage.update(a=time.time(), donnees={
                "corbeille": taille(poids_dossier(DOSSIER / ".local/share/Trash")),
                "cache": taille(poids_dossier(DOSSIER / ".cache") + sum(poids_dossier(DOSSIER / d / "Default/Cache") for d in PROFILS_CHROME))})
        return {"total": taille(disque.total), "libre": taille(disque.free),
                "utilise_pct": round(100 * (disque.total - disque.free) / disque.total), **self._stockage["donnees"]}

    @staticmethod
    def infos():
        memoire = re.search(r"MemTotal:\s+(\d+)", lire("/proc/meminfo"))
        allume = float((lire("/proc/uptime", "0").split() or ["0"])[0])
        temperature = ""
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            if lire(zone / "type") in ("x86_pkg_temp", "TCPU", "acpitz"):
                t = lire(zone / "temp")
                if t.isdigit():
                    temperature = f"{int(t) // 1000} °C"
                    break
        nom = re.search(r'^PRETTY_NAME="?([^"\n]*)', lire("/etc/os-release"), re.M)
        return {"systeme": nom.group(1) if nom else "Smoky OS", "noyau": os.uname().release.split("-")[0],
                "memoire": taille(int(memoire.group(1)) * 1024) if memoire else "?",
                "allume": f"{int(allume // 3600)} h {int(allume % 3600 // 60):02d}", "temperature": temperature}

    @staticmethod
    def carte_graphique_mux():
        """État de l'aiguillage graphique (mode Ultimate de Windows), lu par smokygpu.py."""
        code, sortie = lancer("python3", "-I", f"{OUTILS}/smokygpu.py", "etat", delai=8)
        return _json(sortie) if code == 0 else {}

    def etat(self):
        # les commandes lentes tournent en même temps : la page se met à jour bien plus vite
        lectures = {
            "mode_graphique": lambda: lancer("supergfxctl", "-g")[1],
            "mux": lambda: self._garde("mux", 60, self.carte_graphique_mux),
            "profil": lambda: lancer("powerprofilesctl", "get")[1],
            "connexions": lambda: lancer("nmcli", "-t", "-f", "NAME", "connection", "show")[1],
            "actives": lambda: lancer("nmcli", "-t", "-f", "NAME", "connection", "show", "--active")[1],
            "maison": lambda: lancer("systemctl", "--user", "is-active", "smoky-home.service")[1],
            "cours": self.cours, "image": self.image, "windows": self.windows,
            "sauvegarde": lambda: self._garde("sauvegarde", 300, lambda: _json(lancer("python3", f"{OUTILS}/smoky-backup-status.py", delai=10)[1])),
            "securise": self.demarrage_securise, "gnome": gnome_lire, "stockage": self.stockage,
        }
        r = {nom: tache.result() for nom, tache in {n: self._bassin.submit(f) for n, f in lectures.items()}.items()}
        image, prete = r["image"]
        concentration = charger(CONCENTRATION, {"end": 0, "minutes": 0})
        if not isinstance(concentration.get("end"), (int, float)) or concentration["end"] < time.time():
            concentration = {"end": 0, "minutes": 0}
        return {
            "image": image,
            "maj": {"prete": prete, **self.maj},
            "energie": {"niveau": lire(BATTERIE / "capacity", "?"), "etat": lire(BATTERIE / "status", "?"),
                        "limite": lire(BATTERIE / "charge_control_end_threshold", "?"), "profil": r["profil"] or "?"},
            "carte_graphique": {"mode": r["mode_graphique"] or "?", "mux": r["mux"]},
            "adaptatif": charger(ADAPTATIF, ADAPTATIF_DEFAUT),
            "maison": {"jeton": MAISON_JETON.exists(), "arriere_plan": MAISON_FOND.exists(), "active": r["maison"] == "active"},
            "cours": r["cours"],
            "vpn": {"configure": VPN in r["connexions"].splitlines(), "actif": VPN in r["actives"].splitlines()},
            "concentration": concentration,
            "gnome": r["gnome"],
            "travaux": {nom: dict(t) for nom, t in self.travaux.items()},
            "windows": r["windows"] is not None,
            "sauvegarde": r["sauvegarde"], "demarrage_securise": r["securise"],
            "infos": self.infos(),
            "stockage": r["stockage"],
        }

    def resume(self):
        """Quelques chiffres pour la page Aujourd'hui (lecture de fichiers seulement : instantané)."""
        return {"niveau": lire(BATTERIE / "capacity", ""), "etat": lire(BATTERIE / "status", ""),
                "maj_prete": self._image["prete"]}

    # --- travaux longs (en arrière-plan ; la page est prévenue à la fin) ---
    def _mettre_a_jour(self):
        """Télécharge la nouvelle image Smoky OS ; elle s'applique au prochain redémarrage."""
        code, _sortie = lancer("rpm-ostree", "upgrade", delai=3600)
        if code != 0:
            self.maj["resultat"] = "erreur"
            notifier("Mise à jour impossible", "Vérifie la connexion internet et réessaie.", "dialog-error")
        elif self.image(frais=True)[1]:
            self.maj["resultat"] = "prete"
            notifier("Mise à jour prête", "Redémarre quand tu veux pour l'appliquer (Smoky > Système).", "system-reboot")
        else:
            self.maj["resultat"] = "a_jour"
        self.maj["en_cours"] = False
        self.prevenir("systeme")

    def _mettre_a_jour_applis(self):
        code, _sortie = lancer("flatpak", "update", "-y", "--noninteractive", delai=3600)
        self.travaux["applis"].update(en_cours=False, resultat="ok" if code == 0 else "erreur")
        notifier("Applis à jour" if code == 0 else "Mise à jour des applis incomplète",
                 "Proton VPN, mpv et les autres applis sont à jour." if code == 0 else "Réessaie plus tard.",
                 "system-software-update")
        self.prevenir("systeme")

    def _nettoyer(self):
        """Corbeille, miniatures, caches de Chrome et moteurs Flatpak inutilisés (jamais tes fichiers)."""
        avant = shutil.disk_usage(DOSSIER).free
        lancer("gio", "trash", "--empty", delai=120)
        shutil.rmtree(DOSSIER / ".cache/thumbnails", ignore_errors=True)
        for profil in PROFILS_CHROME:
            for sous in ("Default/Cache", "Default/Code Cache", "Default/GPUCache", "GrShaderCache", "ShaderCache"):
                shutil.rmtree(DOSSIER / profil / sous, ignore_errors=True)
        lancer("flatpak", "uninstall", "--unused", "-y", "--noninteractive", delai=600)
        libere = max(0, shutil.disk_usage(DOSSIER).free - avant)
        self.travaux["nettoyage"].update(en_cours=False, resultat=taille(libere))
        self._stockage["a"] = 0.0
        notifier("Nettoyage terminé", f"{taille(libere)} libérés.", "user-trash")
        self.prevenir("systeme")

    def _en_fond(self, etat, travail):
        if not etat["en_cours"]:
            etat.update(en_cours=True, resultat="")
            threading.Thread(target=travail, daemon=True).start()

    # --- actions ---
    def agir(self, a):
        """a : {"action": nom, …}. → {"message": texte éventuel}. Lève Erreur si refusé ou raté."""
        action = a.get("action")
        fonction = getattr(self, f"_a_{action}", None) if isinstance(action, str) and re.fullmatch(r"[a-z_]+", action) else None
        if fonction is None:
            raise Erreur(400, "Action inconnue.")
        return {"message": fonction(a) or ""}

    @staticmethod
    def _limite_de_charge(valeur):
        code, _ = lancer("asusctl", "-c", str(valeur))
        if code != 0:                                      # asusctl récent : autre écriture
            code, _ = lancer("asusctl", "battery", "limit", str(valeur))
        if code != 0:
            raise Erreur(502, "La limite de charge n'a pas pu être changée (asusctl ne répond pas).")

    def _a_limite_de_charge(self, a):
        if a.get("limite") not in (60, 80, 100) or isinstance(a.get("limite"), bool):
            raise Erreur(400, "Limite refusée : 60, 80 ou 100.")
        (CFG / "charge-once").unlink(missing_ok=True)
        self._limite_de_charge(a["limite"])

    def _a_charge_complete_une_fois(self, a):
        # 100 % pour un trajet ; smoky-adaptive remet la limite habituelle au débranchement
        avant = lire(BATTERIE / "charge_control_end_threshold", "80")
        avant = avant if avant in ("60", "80") else "80"
        self._limite_de_charge(100)
        CFG.mkdir(parents=True, exist_ok=True)
        (CFG / "charge-once").write_text(avant)
        return f"Charge à 100 % cette fois-ci ; la limite reviendra à {avant} % au débranchement."

    def _a_profil(self, a):
        if a.get("nom") not in ("power-saver", "balanced", "performance"):
            raise Erreur(400, "Profil inconnu.")
        if lancer("powerprofilesctl", "set", a["nom"])[0] != 0:
            raise Erreur(502, "Le profil d'énergie n'a pas pu être changé.")

    def _a_carte_graphique(self, a):
        if a.get("mode") not in ("Integrated", "Hybrid"):
            raise Erreur(400, "Mode inconnu.")
        code, sortie = lancer("supergfxctl", "-m", a["mode"], delai=30)
        if code != 0:
            raise Erreur(502, sortie or "La carte graphique n'a pas pu être changée.")
        return "Ferme ta session puis rouvre-la pour appliquer."

    def _a_adaptatif(self, a):
        reglages = charger(ADAPTATIF, ADAPTATIF_DEFAUT)
        for cle in ADAPTATIF_DEFAUT:
            if isinstance(a.get(cle), bool):
                reglages[cle] = a[cle]
        enregistrer(ADAPTATIF, reglages)

    def _a_gnome(self, a):
        if not gnome_ecrire(str(a.get("nom")), a.get("valeur")):
            raise Erreur(502, "Réglage indisponible sur cette machine.")

    def _a_maison_jeton(self, a):
        jeton = str(a.get("jeton", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{20,600}", jeton):
            raise Erreur(400, "Jeton invalide : copie-le en entier depuis Smoky Home.")
        MAISON_JETON.parent.mkdir(parents=True, exist_ok=True)
        MAISON_JETON.touch(mode=0o600)
        os.chmod(MAISON_JETON, 0o600)
        MAISON_JETON.write_text(jeton)

    def _a_maison_arriere_plan(self, a):
        if not isinstance(a.get("actif"), bool):
            raise Erreur(400, "Valeur refusée.")
        if a["actif"]:
            MAISON_FOND.parent.mkdir(parents=True, exist_ok=True)
            MAISON_FOND.write_text("[Desktop Entry]\nType=Application\nName=Smoky Home (arrière-plan)\n"
                                   "Exec=systemctl --user start smoky-home.service\nNoDisplay=true\n")
            detacher("systemctl", "--user", "start", "smoky-home.service")
        else:
            MAISON_FOND.unlink(missing_ok=True)
            detacher("systemctl", "--user", "stop", "smoky-home.service")

    def _a_cours(self, a):
        if a.get("quoi") not in ("connect", "sync", "disconnect"):
            raise Erreur(400, "Action inconnue.")
        self._cours["a"] = 0.0
        detacher("python3", f"{OUTILS}/smoky-moodle.py", a["quoi"])

    def _a_vpn_importer(self, a):
        contenu = str(a.get("contenu", ""))
        if "[Interface]" not in contenu or "[Peer]" not in contenu or len(contenu) > 20000:
            raise Erreur(400, "Ce n'est pas un fichier de configuration WireGuard (.conf).")
        lancer("nmcli", "connection", "delete", "id", VPN)
        tmp = CFG / "smokyvpn.conf"
        CFG.mkdir(parents=True, exist_ok=True)
        tmp.touch(mode=0o600)
        os.chmod(tmp, 0o600)
        tmp.write_text(contenu)
        code, sortie = lancer("nmcli", "connection", "import", "type", "wireguard", "file", str(tmp), delai=20)
        tmp.unlink(missing_ok=True)
        if code != 0:
            raise Erreur(502, sortie or "Import refusé par NetworkManager.")
        lancer("nmcli", "connection", "modify", "smokyvpn", "connection.id", VPN, "connection.autoconnect", "no")

    def _a_vpn(self, a):
        if not isinstance(a.get("actif"), bool):
            raise Erreur(400, "Valeur refusée.")
        code, sortie = lancer("nmcli", "connection", "up" if a["actif"] else "down", "id", VPN, delai=30)
        if code != 0:
            raise Erreur(502, sortie or "Le VPN n'a pas répondu.")

    def _a_concentration_debut(self, a):
        minutes = a.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 5 <= minutes <= 240:
            raise Erreur(400, "Durée refusée : entre 5 et 240 minutes.")
        code, sortie = lancer("systemctl", "start", "--no-block", f"smoky-focus@{minutes}.service", delai=20)
        if code != 0:
            raise Erreur(502, sortie or "Démarrage refusé.")
        enregistrer(CONCENTRATION, {"end": time.time() + minutes * 60, "minutes": minutes})
        detacher("systemd-run", "--user", f"--on-active={minutes}m", "--unit", f"smoky-focus-fin-{int(time.time())}",
                 "notify-send", "-a", "Smoky OS", "-i", "alarm-symbolic", "Pause méritée ☕",
                 f"{minutes} minutes de concentration terminées. Les sites sont de nouveau accessibles.")

    def _a_concentration_fin(self, a):
        minutes = charger(CONCENTRATION, {"minutes": 0}).get("minutes")
        if isinstance(minutes, int) and not isinstance(minutes, bool) and 5 <= minutes <= 240:
            lancer("systemctl", "stop", f"smoky-focus@{minutes}.service", delai=20)
        CONCENTRATION.unlink(missing_ok=True)

    def _a_sauvegarde_ouvrir(self, a):
        detacher("flatpak", "run", "org.gnome.DejaDup")

    def _a_logos(self, a):
        detacher("python3", f"{OUTILS}/smoky-autoicons.py")
        return "Logos en cours de mise à jour."

    def _a_applis_mettre_a_jour(self, a):
        self._en_fond(self.travaux["applis"], self._mettre_a_jour_applis)

    def _a_nettoyer(self, a):
        self._en_fond(self.travaux["nettoyage"], self._nettoyer)

    def _a_mettre_a_jour(self, a):
        self._en_fond(self.maj, self._mettre_a_jour)

    def _a_redemarrer(self, a):
        if lancer("systemctl", "reboot")[0] != 0:
            raise Erreur(502, "Le redémarrage a été refusé.")

    def _a_windows(self, a):
        if not self.windows():
            raise Erreur(404, "Windows introuvable sur ce PC.")
        # on attend le résultat : si le firmware refuse, on le dit au lieu de ne rien faire
        code, _ = lancer("systemctl", "start", "smoky-windows.service", delai=30)
        if code not in (0, 127):
            raise Erreur(502, "Le firmware ASUS refuse de choisir Windows à l'avance : redémarre, appuie sur "
                              "Échap au logo ROG et choisis Windows Boot Manager.")

    def _a_uefi(self, a):                              # redémarrer directement dans les réglages UEFI (BIOS)
        code, sortie = lancer("systemctl", "start", "--no-block", "smoky-firmware.service", delai=20)
        if code != 0:
            raise Erreur(502, sortie or "Redémarrage refusé : appuie sur F2 au démarrage.")

    def _a_maison_ouvrir(self, a):
        detacher(f"{BIN}/smoky-home")
