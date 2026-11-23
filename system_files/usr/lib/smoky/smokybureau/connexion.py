"""Smoky OS — écran de connexion (lancé par greetd, sous le compte « greetd »).

Il montre ton compte, demande le mot de passe et le transmet à greetd, qui le vérifie par
PAM (et déverrouille le trousseau). Il ne voit jamais ton mot de passe ailleurs que dans le champ,
et ne l'écrit nulle part. Boutons : Windows (redémarrage sur Windows, comme dans l'appli Smoky),
Redémarrer, Éteindre.

Protocole greetd : messages JSON précédés de leur longueur (entier 32 bits, ordre de la machine).
"""
import os
import pwd
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import commun  # noqa: E402
from .greetd import Greetd  # noqa: E402

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]


def comptes():
    """Les comptes de personnes (UID 1000 et plus, avec un vrai shell), le premier d'abord."""
    liste = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(("nologin", "false")):
            liste.append((p.pw_name, (p.pw_gecos.split(",")[0] or p.pw_name)))
    return sorted(liste, key=lambda c: pwd.getpwnam(c[0]).pw_uid)


class Connexion(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="fr.smoky.Connexion", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.comptes = comptes()
        self.confirmer = None

    def do_activate(self):
        css = Gtk.CssProvider()
        css.load_from_path(str(commun.CSS))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        w = self.fenetre = Gtk.ApplicationWindow(application=self, title="Smoky")
        w.add_css_class("smoky-connexion")
        fond = Gtk.Overlay()
        image = Gtk.Picture.new_for_filename(commun.FOND_DEFAUT)
        image.set_content_fit(Gtk.ContentFit.COVER)
        fond.set_child(image)
        fond.add_overlay(Gtk.Box(css_classes=["verrou-voile"], hexpand=True, vexpand=True))
        centre = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER,
                         valign=Gtk.Align.CENTER, css_classes=["verrou"])
        self.heure = Gtk.Label(css_classes=["verrou-heure"])
        self.date = Gtk.Label(css_classes=["verrou-date"])
        centre.append(self.heure)
        centre.append(self.date)
        nom, affiche = self.comptes[0] if self.comptes else ("", "Aucun compte")
        self.utilisateur = nom
        initiale = Gtk.Label(label=(affiche[:1] or "?").upper(), css_classes=["avatar"], halign=Gtk.Align.CENTER)
        centre.append(initiale)
        if len(self.comptes) > 1:
            choix = Gtk.DropDown.new_from_strings([a for _n, a in self.comptes])
            choix.connect("notify::selected", lambda d, *_: setattr(self, "utilisateur", self.comptes[d.get_selected()][0]))
            centre.append(choix)
        else:
            centre.append(Gtk.Label(label=affiche, css_classes=["verrou-nom"]))
        self.mdp = Gtk.PasswordEntry(placeholder_text="Mot de passe", show_peek_icon=True,
                                     css_classes=["verrou-mdp"], width_request=320)
        self.mdp.connect("activate", lambda *a: self.essayer())
        centre.append(self.mdp)
        self.message = Gtk.Label(css_classes=["verrou-message"])
        centre.append(self.message)
        fond.add_overlay(centre)
        bas = Gtk.Box(spacing=8, halign=Gtk.Align.END, valign=Gtk.Align.END, css_classes=["connexion-actions"])
        for texte, cmd in (("Windows", ["systemctl", "start", "--no-block", "smoky-windows.service"]),
                           ("Redémarrer", ["systemctl", "reboot"]), ("Éteindre", ["systemctl", "poweroff"])):
            b = Gtk.Button(label=texte, css_classes=["action"])
            b.connect("clicked", lambda _b, c=cmd, t=texte: self.action(_b, c, t))
            bas.append(b)
        fond.add_overlay(bas)
        w.set_child(fond)
        w.present()
        w.fullscreen()
        self.mdp.grab_focus()
        self.tic()
        print("écran de connexion Smoky affiché", flush=True)     # repère de l'essai de démarrage

    def tic(self):
        t = time.localtime()
        self.heure.set_label(f"{t.tm_hour:02d}:{t.tm_min:02d}")
        self.date.set_label(f"{JOURS[t.tm_wday].capitalize()} {t.tm_mday} {MOIS[t.tm_mon - 1]}")
        GLib.timeout_add_seconds(60 - t.tm_sec, self.tic)
        return False

    def action(self, bouton, cmd, texte):
        if self.confirmer is not bouton:              # deuxième appui pour confirmer
            self.confirmer = bouton
            bouton.set_label("Confirmer")
            GLib.timeout_add_seconds(4, lambda: (bouton.set_label(texte), setattr(self, "confirmer", None))[1])
            return
        subprocess.Popen(cmd)

    def essayer(self):
        mot_de_passe = self.mdp.get_text()
        if not mot_de_passe or not self.utilisateur:
            return
        self.mdp.set_sensitive(False)
        self.message.set_label("Connexion…")

        def travail():
            try:
                erreur = Greetd().connecter(self.utilisateur, mot_de_passe)
            except (OSError, KeyError, ValueError, ConnectionError) as e:
                erreur = f"Connexion impossible ({e})"
            GLib.idle_add(self.resultat, erreur)
        threading.Thread(target=travail, daemon=True).start()

    def resultat(self, erreur):
        if erreur is None:
            self.quit()                 # labwc se ferme avec nous, greetd ouvre ta session
            return False
        self.mdp.set_text("")
        self.mdp.set_sensitive(True)
        self.mdp.grab_focus()
        self.message.set_label(erreur)
        return False


def main():
    os.environ.setdefault("GDK_BACKEND", "wayland")
    Connexion().run([])


if __name__ == "__main__":
    main()
