"""Smoky OS — écran de connexion (lancé par greetd, sous le compte « greetd »).

Il montre ton compte, demande le mot de passe et le transmet à greetd, qui le vérifie par
PAM (et déverrouille le trousseau). Il ne voit jamais ton mot de passe ailleurs que dans le champ,
et ne l'écrit nulle part. Boutons : Windows (redémarrage sur Windows, comme dans l'appli Smoky),
Redémarrer, Éteindre ; chacun se confirme d'un second appui et dit à l'écran s'il a échoué.
Un clavier tactile (clavier.py) permet de se connecter clavier détaché.

Protocole greetd : messages JSON précédés de leur longueur (entier 32 bits, ordre de la machine).
"""
import os
import pwd
import subprocess
import syslog
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import clavier, commun  # noqa: E402
from .greetd import Greetd  # noqa: E402

# L'écran de connexion tourne dans le domaine SELinux de greetd (xdm_t), qui n'a pas le droit de
# démarrer un service. Pour Windows, il dépose donc une demande dans son propre dossier ; un service
# système la voit (smoky-windows-connexion.path), la retire, lance smoky-bootonce.sh et laisse le
# résultat dans ETAT_WINDOWS (« en cours », ou la raison d'un échec ; sinon le PC redémarre).
DEMANDE_WINDOWS = Path("/var/lib/greetd/smoky-windows")
ETAT_WINDOWS = Path("/var/lib/greetd/smoky-windows.etat")
ESSAI = Path("/etc/smokyos/essai-connexion")     # machine virtuelle de test seulement (voir essai_automatique)

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
        clavier.ajouter(w, fond, self.mdp, self.essayer, centre)    # clavier tactile : connexion clavier détaché
        w.set_child(fond)
        w.present()
        w.fullscreen()
        self.mdp.grab_focus()
        self.tic()
        # repère pour l'essai de démarrage : la sortie de l'écran de connexion ne va pas au journal,
        # on y écrit donc directement (syslog → journald)
        syslog.openlog("smoky-connexion")
        syslog.syslog(syslog.LOG_INFO, "écran de connexion Smoky affiché")
        GLib.timeout_add_seconds(3, self.essai_automatique)

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
        self.confirmer = None
        bouton.set_label(texte)
        if texte == "Windows":
            self.windows()
            return
        self.message.set_label("Redémarrage…" if texte == "Redémarrer" else "Extinction…")
        self.lancer(cmd, texte)

    def lancer(self, cmd, texte):
        """Lance la commande ; si elle échoue, la raison s'affiche sous le mot de passe."""
        def travail():
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                erreur = None if r.returncode == 0 else \
                    ((r.stderr or r.stdout).strip().splitlines() or [f"échec (code {r.returncode})"])[-1]
            except (OSError, subprocess.TimeoutExpired) as e:
                erreur = str(e)
            if erreur:
                GLib.idle_add(self.fin_action, texte, erreur)
        threading.Thread(target=travail, daemon=True).start()

    def fin_action(self, texte, resultat):
        syslog.syslog(syslog.LOG_WARNING, f"bouton {texte} : {resultat}")
        self.message.set_label(f"{texte} : {resultat}")
        return False

    def windows(self):
        self.message.set_label("Redémarrage sur Windows…")
        self.depuis = time.time()
        try:
            DEMANDE_WINDOWS.write_text(f"{int(self.depuis)}\n")
        except OSError as e:
            # dossier absent ou refusé : l'ancienne voie (service démarré directement, règle polkit)
            syslog.syslog(syslog.LOG_WARNING, f"bouton Windows : demande impossible ({e}), essai direct")
            self.lancer(["systemctl", "start", "smoky-windows.service"], "Windows")
            return
        self.attente = 0
        GLib.timeout_add_seconds(1, self.suivre_windows)

    def suivre_windows(self):
        self.attente += 1
        try:
            if ETAT_WINDOWS.stat().st_mtime >= self.depuis - 1:
                etat = ETAT_WINDOWS.read_text().strip()
                if etat and etat != "en cours":
                    self.fin_action("Windows", etat)
                    return False
        except OSError:
            pass
        if self.attente >= 20 and DEMANDE_WINDOWS.exists():
            try:
                DEMANDE_WINDOWS.unlink()
            except OSError:
                pass
            self.fin_action("Windows", "demande pas prise en compte (service smoky-windows-connexion arrêté)")
            return False
        if self.attente >= 150:
            self.fin_action("Windows", "pas de réponse")
            return False
        return True

    def essai_automatique(self):
        """Machine virtuelle de test seulement : appuie sur « Windows » pour vérifier que l'écran de
        connexion en a le droit (le résultat va au journal). Jamais sur un vrai PC : il faut à la fois
        ce fichier, déposé par l'essai de démarrage, et une machine QEMU."""
        try:
            qemu = "QEMU" in Path("/sys/class/dmi/id/sys_vendor").read_text()
            demande = ESSAI.read_text().strip()
        except OSError:
            return False
        if qemu and demande == "windows":
            self.windows()
        return False

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
