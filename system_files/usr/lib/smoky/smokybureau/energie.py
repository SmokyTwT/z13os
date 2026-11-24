"""Smoky OS — adaptation automatique à la batterie (service smoky-adaptive, même nom qu'avant).

Débranché :
  * profil « économie » (power-profiles-daemon, seul à changer de profil : décision 4) ;
  * écran à 60 Hz (120 Hz revient sur secteur) ;
  * luminosité plafonnée à 50 % si elle était plus haute ;
  * Smoky Home (Home Assistant) en pause : il ne sert à rien loin de la maison ;
  * après une charge à 100 % « pour cette fois », la limite habituelle revient.
Rebranché : tout ce qui avait été changé revient comme avant.
VPN : sur un Wi-Fi ouvert (sans mot de passe), active la connexion « Smoky VPN » si demandé.

Réglages : ~/.config/smoky/adaptive.json (mêmes clés qu'avant + nouvelles), relus à chaud.
"""
import subprocess
import threading

from gi.repository import Gio, GLib

from . import commun
from .ecran import choisir_frequence, ecran_integre

DEFAUTS = {"refresh": True, "tablet_mode": False, "vpn_auto": False, "tablet_open_notes": True,
           "economie_batterie": True, "luminosite_batterie": True, "maison_batterie": True}
ETAT = commun.CONFIG / "adaptive-state.json"
CHARGE_UNE_FOIS = commun.CONFIG / "charge-once"
VPN = "Smoky VPN"
PPD = ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles")
PLAFOND_LUMIERE = 50
PORTAIL_ESSAI = "http://fedoraproject.org/static/hotspot.txt"   # la page de connexion s'ouvre à sa place


def ok(*args):
    try:
        return subprocess.run(args, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class Adaptation:
    def __init__(self):
        self.conf = commun.lire_json(commun.ADAPTIVE, DEFAUTS)
        self.etat = commun.lire_json(ETAT, {})
        self.systeme = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.batterie = None
        commun.CONFIG.mkdir(parents=True, exist_ok=True)
        self.moniteur = Gio.File.new_for_path(str(commun.ADAPTIVE)).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.moniteur.connect("changed", lambda *a: GLib.timeout_add(300, self.relire))
        self.systeme.signal_subscribe("org.freedesktop.UPower", "org.freedesktop.DBus.Properties",
                                      "PropertiesChanged", "/org/freedesktop/UPower", None,
                                      Gio.DBusSignalFlags.NONE, lambda *a: self.verifier())
        self.systeme.signal_subscribe("org.freedesktop.NetworkManager", "org.freedesktop.NetworkManager",
                                      "StateChanged", "/org/freedesktop/NetworkManager", None,
                                      Gio.DBusSignalFlags.NONE, self.reseau_change)
        self.capteur = False
        self.alertes = set()
        self.batterie_etat = commun.Batterie()
        # clavier détaché (Z13 en tablette) : le clavier à l'écran s'active tout seul. On regarde
        # /dev/input : un clavier branché ou retiré y ajoute ou y retire un fichier.
        self.clavier_branche = self.clavier_present()
        self.attente_clavier = 0
        self.entrees = Gio.File.new_for_path("/dev/input").monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.entrees.connect("changed", lambda *a: self.planifier_clavier())
        self.appliquer_tablette()
        self.verifier()
        GLib.timeout_add_seconds(60, self.surveiller_niveau)
        self.systeme.signal_subscribe("org.freedesktop.NetworkManager", "org.freedesktop.DBus.Properties",
                                      "PropertiesChanged", "/org/freedesktop/NetworkManager", None,
                                      Gio.DBusSignalFlags.NONE, self.connectivite)
        self.portail_signale = False

    # --- batterie faible : prévenir avant qu'il ne soit trop tard ---------------------------------
    def surveiller_niveau(self):
        e = self.batterie_etat.etat()
        if e:
            alerte, self.alertes = commun.alerte_batterie(e["niveau"], e["statut"] != "Discharging", self.alertes)
            reste = f" Environ {commun.duree(e['minutes'])} restantes." if e.get("minutes") else ""
            if alerte == "faible":
                commun.commande("notify-send", "-a", "Smoky OS", "-i", "battery-caution", "Batterie faible",
                                f"{e['niveau']} %.{reste} Branche le chargeur bientôt.")
            elif alerte == "critique":
                commun.commande("notify-send", "-a", "Smoky OS", "-u", "critical", "-i", "battery-empty",
                                "Batterie presque vide", f"{e['niveau']} %.{reste} Enregistre ton travail et branche le chargeur.")
        return True

    # --- Wi-Fi d'hôtel ou de gare : page de connexion à valider ------------------------------------
    def connectivite(self, conn, expediteur, chemin, interface, signal, params):
        changes = params.unpack()[1]
        if "Connectivity" not in changes:
            return
        if changes["Connectivity"] == 2 and not self.portail_signale:         # 2 = portail captif
            self.portail_signale = True
            threading.Thread(target=self.proposer_portail, daemon=True).start()
        elif changes["Connectivity"] == 4:                                     # 4 = internet complet
            self.portail_signale = False

    def proposer_portail(self):
        reponse = commun.commande("notify-send", "-a", "Smoky OS", "-i", "network-wireless", "-t", "15000",
                                  "-A", "ouvrir=Ouvrir la page", "Wi-Fi à valider",
                                  "Ce réseau demande d'accepter ses conditions avant d'aller sur internet.", delai=20)
        if reponse.strip() == "ouvrir":
            subprocess.Popen(["xdg-open", PORTAIL_ESSAI])

    # --- mode tablette : clavier à l'écran (smoky-clavier-ecran) et rotation de l'écran ---------
    ROTATIONS = {"normal": "normal", "left-up": "90", "right-up": "270", "bottom-up": "180"}

    @staticmethod
    def clavier_present():
        noms = commun.claviers_physiques()
        return True if noms is None else bool(noms)    # dans le doute : comme avant (clavier là)

    def planifier_clavier(self):
        if not self.attente_clavier:                 # plusieurs fichiers bougent d'un coup : on attend 1 s
            self.attente_clavier = GLib.timeout_add(1000, self.revoir_clavier)

    def revoir_clavier(self):
        self.attente_clavier = 0
        present = self.clavier_present()
        if present != self.clavier_branche:
            self.clavier_branche = present
            self.appliquer_tablette()              # clavier détaché = tablette : clavier à l'écran et rotation
        return False

    def appliquer_clavier_ecran(self):
        """Clavier à l'écran tout seul dans les champs de texte : en mode tablette, ou clavier détaché
        (le bouton de la barre apparaît aussi : il sert dans Chrome, qui ne signale pas ses champs)."""
        actif = bool(self.conf.get("tablet_mode")) or not self.clavier_branche
        commun.commande("gsettings", "set", "org.gnome.desktop.a11y.applications", "screen-keyboard-enabled",
                        "true" if actif else "false")

    def appliquer_tablette(self):
        """Mode tablette (réglages rapides) ou clavier détaché, comme Windows sur le Z13 : clavier à
        l'écran tout seul et rotation de l'écran (sauf rotation verrouillée dans Système)."""
        tablette = bool(self.conf.get("tablet_mode")) or not self.clavier_branche
        self.appliquer_clavier_ecran()
        if tablette and not self.capteur:
            try:
                self.systeme.call_sync("net.hadess.SensorProxy", "/net/hadess/SensorProxy", "net.hadess.SensorProxy",
                                       "ClaimAccelerometer", None, None, Gio.DBusCallFlags.NONE, 3000, None)
                self.capteur = True
                self.abonnement = self.systeme.signal_subscribe(
                    "net.hadess.SensorProxy", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                    "/net/hadess/SensorProxy", None, Gio.DBusSignalFlags.NONE, lambda *a: self.tourner())
                self.tourner()
            except GLib.Error:
                pass                                  # pas d'accéléromètre (machine virtuelle…)
        elif not tablette and self.capteur:
            self.systeme.signal_unsubscribe(self.abonnement)
            try:
                self.systeme.call_sync("net.hadess.SensorProxy", "/net/hadess/SensorProxy", "net.hadess.SensorProxy",
                                       "ReleaseAccelerometer", None, None, Gio.DBusCallFlags.NONE, 3000, None)
            except GLib.Error:
                pass
            self.capteur = False
            self.tourner("normal")

    def tourner(self, sens=None):
        if sens is None and self.rotation_bloquee():
            return
        if sens is None:
            try:
                v = self.systeme.call_sync("net.hadess.SensorProxy", "/net/hadess/SensorProxy",
                                           "org.freedesktop.DBus.Properties", "Get",
                                           GLib.Variant("(ss)", ("net.hadess.SensorProxy", "AccelerometerOrientation")),
                                           None, Gio.DBusCallFlags.NONE, 3000, None)
                sens = v.unpack()[0]
            except GLib.Error:
                return
        transformation = self.ROTATIONS.get(sens)
        e = ecran_integre()
        if transformation and e:
            commun.commande("wlr-randr", "--output", e[0], "--transform", transformation)

    @staticmethod
    def rotation_bloquee():
        source = Gio.SettingsSchemaSource.get_default()
        schema = "org.gnome.settings-daemon.peripherals.touchscreen"
        if source is None or source.lookup(schema, True) is None:
            return False
        return Gio.Settings.new(schema).get_boolean("orientation-lock")

    def relire(self):
        tablette_avant = bool(self.conf.get("tablet_mode"))
        self.conf = commun.lire_json(commun.ADAPTIVE, DEFAUTS)
        if bool(self.conf.get("tablet_mode")) != tablette_avant:
            self.appliquer_tablette()
        if self.conf.get("tablet_mode") and not tablette_avant and self.conf.get("tablet_open_notes"):
            threading.Thread(target=self.proposer_notes, daemon=True).start()
        if self.batterie is not None and self.conf.get("refresh"):
            choisir_frequence(self.batterie)
        return False

    def sur_batterie(self):
        try:
            v = self.systeme.call_sync("org.freedesktop.UPower", "/org/freedesktop/UPower",
                                       "org.freedesktop.DBus.Properties", "Get",
                                       GLib.Variant("(ss)", ("org.freedesktop.UPower", "OnBattery")),
                                       None, Gio.DBusCallFlags.NONE, 5000, None)
            return bool(v.unpack()[0])
        except GLib.Error:
            return None

    def verifier(self):
        b = self.sur_batterie()
        if b is None or b == self.batterie:
            return
        premier = self.batterie is None
        self.batterie = b
        if self.conf.get("refresh"):
            choisir_frequence(b)
        if not premier or b:            # au démarrage sur batterie : on applique aussi
            threading.Thread(target=self.changement, args=(b,), daemon=True).start()

    # --- profil d'énergie ------------------------------------------------------------------
    def profil(self, nouveau=None):
        try:
            if nouveau:
                self.systeme.call_sync(PPD[0], PPD[1], "org.freedesktop.DBus.Properties", "Set",
                                       GLib.Variant("(ssv)", (PPD[0], "ActiveProfile", GLib.Variant("s", nouveau))),
                                       None, Gio.DBusCallFlags.NONE, 5000, None)
                return nouveau
            v = self.systeme.call_sync(PPD[0], PPD[1], "org.freedesktop.DBus.Properties", "Get",
                                       GLib.Variant("(ss)", (PPD[0], "ActiveProfile")), None,
                                       Gio.DBusCallFlags.NONE, 5000, None)
            return v.unpack()[0]
        except GLib.Error:
            return None

    def changement(self, batterie):
        if batterie:
            actuel = self.profil()
            if self.conf.get("economie_batterie") and actuel and actuel != "power-saver":
                self.etat["profil_avant"] = actuel
                self.profil("power-saver")
            lum = commun.luminosite()
            if self.conf.get("luminosite_batterie") and lum and lum > PLAFOND_LUMIERE:
                self.etat["lumiere_avant"] = lum
                commun.regler_luminosite(PLAFOND_LUMIERE)
            if self.conf.get("maison_batterie") and ok("systemctl", "--user", "is-active", "-q", "smoky-home.service"):
                if ok("systemctl", "--user", "stop", "smoky-home.service"):
                    self.etat["maison_arretee"] = True
            if CHARGE_UNE_FOIS.exists():
                avant = CHARGE_UNE_FOIS.read_text().strip() or "80"
                if avant.isdigit() and (ok("asusctl", "battery", "limit", avant) or ok("asusctl", "-c", avant)):
                    CHARGE_UNE_FOIS.unlink(missing_ok=True)
                    commun.commande("notify-send", "-a", "Smoky OS", "-i", "battery", "Batterie",
                                    f"Charge complète terminée : limite remise à {avant} % pour préserver la batterie.")
        else:
            avant = self.etat.pop("profil_avant", None)
            if avant and self.profil() == "power-saver":
                self.profil(avant)
            lum = self.etat.pop("lumiere_avant", None)
            if lum and (commun.luminosite() or 0) <= PLAFOND_LUMIERE:
                commun.regler_luminosite(lum)
            if self.etat.pop("maison_arretee", False):
                ok("systemctl", "--user", "start", "smoky-home.service")
        commun.ecrire_json(ETAT, self.etat)

    # --- mode tablette : les notes à portée de doigt ------------------------------------------
    def proposer_notes(self):
        reponse = commun.commande("notify-send", "-a", "Smoky OS", "-i", "smoky-appli", "-t", "8000",
                                  "-A", "notes=Ouvrir les notes", "Mode tablette",
                                  "Grandes icônes dans le dock.", delai=12)
        if reponse.strip() == "notes":
            subprocess.Popen(["/usr/bin/smoky", "--aller", "/notes"])     # les Notes, dans l'appli Smoky

    # --- VPN sur les Wi-Fi ouverts ------------------------------------------------------------
    def reseau_change(self, conn, expediteur, chemin, interface, signal, params):
        if params.unpack()[0] >= 60 and self.conf.get("vpn_auto"):
            GLib.timeout_add_seconds(4, self.peut_etre_vpn)

    def peut_etre_vpn(self):
        actives = commun.commande("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active")
        if f"{VPN}:" in actives or "smoky-portail:" in actives:
            return False
        wifi = commun.commande("nmcli", "-t", "-f", "ACTIVE,SECURITY", "device", "wifi", "list", "--rescan", "no")
        ouvert = any(l.startswith("yes:") and l.split(":", 1)[1] in ("", "--") for l in wifi.splitlines())
        if ouvert and f"{VPN}:" in commun.commande("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"):
            commun.commande("nmcli", "connection", "up", "id", VPN)
        return False


def main():
    Adaptation()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
