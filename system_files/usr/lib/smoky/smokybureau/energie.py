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
from .ecran import choisir_frequence

DEFAUTS = {"refresh": True, "tablet_mode": False, "vpn_auto": False, "tablet_open_notes": True,
           "economie_batterie": True, "luminosite_batterie": True, "maison_batterie": True}
ETAT = commun.CONFIG / "adaptive-state.json"
CHARGE_UNE_FOIS = commun.CONFIG / "charge-once"
VPN = "Smoky VPN"
PPD = ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles")
PLAFOND_LUMIERE = 50


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
        self.verifier()

    def relire(self):
        tablette_avant = bool(self.conf.get("tablet_mode"))
        self.conf = commun.lire_json(commun.ADAPTIVE, DEFAUTS)
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
