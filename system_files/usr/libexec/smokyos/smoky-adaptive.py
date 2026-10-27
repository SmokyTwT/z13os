#!/usr/bin/env python3
"""Smoky OS — adaptation automatique (service de session).

* Écran : fréquence maximale (120 Hz) sur secteur, 60 Hz sur batterie.
* Tablette : clavier détaché → grandes icônes dans le dock et clavier virtuel ;
  clavier rattaché → retour à la normale.
* VPN : sur un Wi-Fi ouvert (sans mot de passe), active la connexion « Smoky VPN ».

Réglages : ~/.config/smoky/adaptive.json (modifiés par Smoky Center), relus à chaud.
"""
import json
import subprocess
import threading
from pathlib import Path

from gi.repository import Gio, GLib

CONF = Path.home() / ".config/smoky/adaptive.json"
STATE = Path.home() / ".config/smoky/adaptive-state.json"
DEFAULTS = {"refresh": True, "tablet": True, "vpn_auto": False, "tablet_open_notes": True}
VPN_NAME = "Smoky VPN"


def load(path, default):
    try:
        return {**default, **json.loads(path.read_text())}
    except (OSError, ValueError):
        return dict(default)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))


def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def settings(schema):
    src = Gio.SettingsSchemaSource.get_default()
    return Gio.Settings.new(schema) if src.lookup(schema, True) else None


class Adaptive:
    def __init__(self):
        self.conf = load(CONF, DEFAULTS)
        self.state = load(STATE, {"kbd_seen": False, "dock_size": None})
        self.system = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.on_battery = None
        self.tablet = None

        # Réglages modifiés par Smoky Center : relus immédiatement
        CONF.parent.mkdir(parents=True, exist_ok=True)
        self.mon = Gio.File.new_for_path(str(CONF)).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.mon.connect("changed", lambda *a: GLib.timeout_add(300, self.reload))

        # Secteur / batterie (UPower)
        self.system.signal_subscribe("org.freedesktop.UPower", "org.freedesktop.DBus.Properties",
                                     "PropertiesChanged", "/org/freedesktop/UPower", None,
                                     Gio.DBusSignalFlags.NONE, lambda *a: self.check_power())
        # Écran rebranché, changement de configuration : on réapplique
        self.session.signal_subscribe("org.gnome.Mutter.DisplayConfig", "org.gnome.Mutter.DisplayConfig",
                                      "MonitorsChanged", "/org/gnome/Mutter/DisplayConfig", None,
                                      Gio.DBusSignalFlags.NONE, lambda *a: GLib.timeout_add(1500, self.apply_refresh))
        # Réseau : nouvelle connexion → VPN si Wi-Fi ouvert
        self.system.signal_subscribe("org.freedesktop.NetworkManager", "org.freedesktop.NetworkManager",
                                     "StateChanged", "/org/freedesktop/NetworkManager", None,
                                     Gio.DBusSignalFlags.NONE, self.on_nm_state)

        self.check_power()
        self.check_keyboard()
        GLib.timeout_add_seconds(3, self.check_keyboard)

    def reload(self):
        self.conf = load(CONF, DEFAULTS)
        self.on_battery = None
        self.check_power()
        if not self.conf["tablet"] and self.tablet:
            self.set_tablet(False)
        return False

    # --- Écran 120 / 60 Hz ------------------------------------------------------------
    def check_power(self):
        try:
            v = self.system.call_sync("org.freedesktop.UPower", "/org/freedesktop/UPower",
                                      "org.freedesktop.DBus.Properties", "Get",
                                      GLib.Variant("(ss)", ("org.freedesktop.UPower", "OnBattery")),
                                      None, Gio.DBusCallFlags.NONE, 5000, None)
            batt = bool(v.unpack()[0])
        except GLib.Error:
            return
        if batt != self.on_battery:
            self.on_battery = batt
            self.apply_refresh()

    def apply_refresh(self):
        if not self.conf["refresh"] or self.on_battery is None:
            return False
        try:
            serial, monitors, logical, _ = self.session.call_sync(
                "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None,
                Gio.DBusCallFlags.NONE, 5000, None).unpack()
        except GLib.Error:
            return False
        chosen, changed = {}, False
        for (conn, _v, _p, _s), modes, _props in monitors:
            cur = next((m for m in modes if m[6].get("is-current")), None)
            if not cur:
                continue
            chosen[conn] = cur[0]
            if not conn.startswith("eDP"):                 # écran interne seulement
                continue
            same = [m for m in modes if m[1] == cur[1] and m[2] == cur[2]]
            if self.on_battery:
                target = min(same, key=lambda m: abs(m[3] - 60))
            else:
                target = max(same, key=lambda m: m[3])
            if target[0] != cur[0]:
                chosen[conn], changed = target[0], True
        if not changed:
            return False
        config = [(x, y, scale, transform, primary, [(c[0], chosen[c[0]], {}) for c in mons])
                  for x, y, scale, transform, primary, mons, _props in logical]
        try:
            self.session.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                                   "org.gnome.Mutter.DisplayConfig", "ApplyMonitorsConfig",
                                   GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, 1, config, {})),
                                   None, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as e:
            print("fréquence d'écran :", e.message)
        return False

    # --- Mode tablette ---------------------------------------------------------------------
    @staticmethod
    def keyboard_attached():
        """Clavier détachable du Z13 : périphérique USB ASUS (vendeur 0b05) qui gère des touches."""
        try:
            blocks = Path("/proc/bus/input/devices").read_text().split("\n\n")
        except OSError:
            return None
        return any("Bus=0003 Vendor=0b05" in b and "kbd" in b for b in blocks)

    def check_keyboard(self):
        attached = self.keyboard_attached()
        if attached and not self.state["kbd_seen"]:
            self.state["kbd_seen"] = True
            save(STATE, self.state)
        # Sans clavier ASUS jamais vu (autre PC, machine virtuelle) : on ne touche à rien
        if self.conf["tablet"] and self.state["kbd_seen"] and attached is not None:
            want = not attached
            if want != self.tablet:
                self.set_tablet(want)
        return True

    def set_tablet(self, on):
        first = self.tablet is None
        self.tablet = on
        dock = settings("org.gnome.shell.extensions.dash-to-dock")
        a11y = settings("org.gnome.desktop.a11y.applications")
        if on:
            if dock:
                if self.state.get("dock_size") is None:
                    self.state["dock_size"] = dock.get_int("dash-max-icon-size")
                    save(STATE, self.state)
                dock.set_int("dash-max-icon-size", 68)
            if a11y:
                a11y.set_boolean("screen-keyboard-enabled", True)
            if not first:
                threading.Thread(target=self.tablet_notice, daemon=True).start()
        else:
            if dock and self.state.get("dock_size"):
                dock.set_int("dash-max-icon-size", self.state["dock_size"])
                self.state["dock_size"] = None
                save(STATE, self.state)
            if a11y:
                a11y.set_boolean("screen-keyboard-enabled", False)

    def tablet_notice(self):
        if not self.conf.get("tablet_open_notes"):
            return
        out = run("notify-send", "-a", "Smoky OS", "-i", "smoky-notes", "-t", "8000",
                  "-A", "notes=Ouvrir Smoky Notes", "Mode tablette",
                  "Clavier détaché : grandes icônes et clavier à l'écran activés.")
        if out.strip() == "notes":
            subprocess.Popen(["/usr/bin/smoky-notes"])

    # --- VPN automatique sur les Wi-Fi ouverts -----------------------------------------------
    def on_nm_state(self, conn, sender, path, iface, signal, params):
        if params.unpack()[0] >= 60 and self.conf.get("vpn_auto"):     # 60+ : connecté
            GLib.timeout_add_seconds(4, self.maybe_vpn)

    def maybe_vpn(self):
        active = run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active")
        if f"{VPN_NAME}:" in active or "smoky-portail:" in active:
            return False
        wifi = run("nmcli", "-t", "-f", "ACTIVE,SECURITY", "device", "wifi", "list", "--rescan", "no")
        open_wifi = any(l.startswith("yes:") and l.split(":", 1)[1] in ("", "--") for l in wifi.splitlines())
        if open_wifi and f"{VPN_NAME}:" in run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"):
            run("nmcli", "connection", "up", "id", VPN_NAME)
        return False


if __name__ == "__main__":
    Adaptive()
    GLib.MainLoop().run()
