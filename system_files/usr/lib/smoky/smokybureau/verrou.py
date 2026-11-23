"""Smoky OS — écran de verrouillage : l'heure, la date, la batterie, et ton mot de passe.

Protocole de verrouillage sûr (ext-session-lock, via gtk4-layer-shell) : tant que le mot de
passe n'est pas vérifié, le moteur d'affichage ne montre rien d'autre, même si ce programme
plante (smoky-verrou.sh lance alors swaylock pour te laisser déverrouiller).
Le mot de passe est vérifié par PAM, comme à la connexion ; il n'est jamais écrit nulle part.

Codes de sortie : 0 déverrouillé, 2 verrouillage refusé (déjà verrouillé…), autre = plantage.
"""
import ctypes
import os
import pwd
import socket
import threading
import time

for _nom in ("libgtk4-layer-shell.so.0", "libgtk4-layer-shell.so"):
    try:
        ctypes.CDLL(_nom)
        break
    except OSError:
        pass

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4SessionLock", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4SessionLock as SL  # noqa: E402

from . import commun  # noqa: E402

MOIS_LONGS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
              "octobre", "novembre", "décembre"]
JOURS_LONGS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def prevenir_systemd(message):
    """sd_notify : dit à systemd que l'écran est verrouillé (la mise en veille peut continuer)."""
    adresse = os.environ.get("NOTIFY_SOCKET")
    if not adresse:
        return
    if adresse.startswith("@"):
        adresse = "\0" + adresse[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as s:
        try:
            s.connect(adresse)
            s.sendall(message.encode())
        except OSError:
            pass


def verifier_mot_de_passe(utilisateur, mot_de_passe):
    import pam
    p = pam.pam()
    ok = p.authenticate(utilisateur, mot_de_passe, service="smoky-verrou")
    return ok, p.reason


class Verrou(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="fr.smoky.Verrou", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.code = 0
        self.utilisateur = pwd.getpwuid(os.getuid()).pw_name
        self.fenetres = []
        self.batterie = commun.Batterie()

    def do_activate(self):
        self.hold()
        css = Gtk.CssProvider()
        css.load_from_path(str(commun.CSS))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if not SL.is_supported():
            self.terminer(2)
            return
        self.verrou = SL.Instance.new()
        self.verrou.connect("locked", lambda *a: prevenir_systemd("READY=1"))
        self.verrou.connect("failed", lambda *a: self.terminer(2))
        self.verrou.connect("unlocked", lambda *a: self.terminer(0))
        if not self.verrou.lock():
            self.terminer(2)
            return
        moniteurs = Gdk.Display.get_default().get_monitors()
        for i in range(moniteurs.get_n_items()):
            self.fenetre_pour(moniteurs.get_item(i), principal=(i == 0))
        self.tic()

    def fenetre_pour(self, moniteur, principal):
        w = Gtk.Window(application=self)
        w.add_css_class("smoky-verrou")
        fond = Gtk.Overlay()
        image = Gtk.Picture.new_for_filename(commun.fond_ecran())
        image.set_content_fit(Gtk.ContentFit.COVER)
        fond.set_child(image)
        fond.add_overlay(Gtk.Box(css_classes=["verrou-voile"], hexpand=True, vexpand=True))
        if principal:
            centre = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER,
                             valign=Gtk.Align.CENTER, css_classes=["verrou"])
            self.heure = Gtk.Label(css_classes=["verrou-heure"])
            self.date = Gtk.Label(css_classes=["verrou-date"])
            self.etat = Gtk.Label(css_classes=["verrou-etat"])
            self.mdp = Gtk.PasswordEntry(placeholder_text="Mot de passe", show_peek_icon=True,
                                         css_classes=["verrou-mdp"], width_request=320)
            self.mdp.connect("activate", lambda *a: self.essayer())
            self.message = Gtk.Label(css_classes=["verrou-message"])
            for x in (self.heure, self.date, self.etat, self.mdp, self.message):
                centre.append(x)
            fond.add_overlay(centre)
        w.set_child(fond)
        self.verrou.assign_window_to_monitor(w, moniteur)
        w.present()
        if principal:
            self.mdp.grab_focus()
        self.fenetres.append(w)

    def tic(self):
        t = time.localtime()
        self.heure.set_label(f"{t.tm_hour:02d}:{t.tm_min:02d}")
        self.date.set_label(f"{JOURS_LONGS[t.tm_wday].capitalize()} {t.tm_mday} {MOIS_LONGS[t.tm_mon - 1]}")
        e = self.batterie.etat()
        if e and e["niveau"] is not None:
            charge = " · en charge" if e["statut"] == "Charging" else ""
            self.etat.set_label(f"Batterie {e['niveau']} %{charge}")
        GLib.timeout_add_seconds(60 - t.tm_sec, self.tic)
        return False

    def essayer(self):
        mot_de_passe = self.mdp.get_text()
        if not mot_de_passe:
            return
        self.mdp.set_sensitive(False)
        self.message.set_label("Vérification…")

        def travail():
            try:
                ok, raison = verifier_mot_de_passe(self.utilisateur, mot_de_passe)
            except Exception as e:          # module PAM absent ou cassé : ne jamais déverrouiller
                ok, raison = False, str(e)
            GLib.idle_add(self.resultat, ok, raison)
        threading.Thread(target=travail, daemon=True).start()

    def resultat(self, ok, raison):
        if ok:
            self.verrou.unlock()
            return False
        self.mdp.set_text("")
        self.mdp.set_sensitive(True)
        self.mdp.grab_focus()
        self.message.set_label("Mot de passe incorrect")
        print("échec de déverrouillage :", raison, flush=True)
        return False

    def terminer(self, code):
        self.code = code
        self.quit()


def main():
    os.environ.setdefault("GDK_BACKEND", "wayland")
    app = Verrou()
    app.run([])
    raise SystemExit(app.code)


if __name__ == "__main__":
    main()
