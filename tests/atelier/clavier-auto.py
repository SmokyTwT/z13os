"""Apparition seule du clavier à l'écran : il sort quand un champ GTK prend la main, rentre quand un
bouton la reprend (méthode de saisie Wayland ; il faut le labwc 0.7.4 de preparer.sh)."""
import sys

from outils import conclure
from smokybureau import clavier_ecran
from gi.repository import Gio, GLib, Gtk

app = clavier_ecran.ClavierSession()
r = {}


def fenetre():
    if not app.wl.gestion_saisie:
        print("SAUTÉ clavier de session : apparition seule (ce labwc n'a pas de méthode de saisie)")
        app.quit()
        return False
    Gio.Settings.new("org.gnome.desktop.a11y.applications").set_boolean("screen-keyboard-enabled", True)
    w = Gtk.Window(application=app, title="essai")
    boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    r["bouton"] = bouton = Gtk.Button(label="pas un champ")
    r["champ"] = champ = Gtk.Entry()
    boite.append(bouton)
    boite.append(champ)
    w.set_child(boite)
    w.present()
    bouton.grab_focus()
    GLib.timeout_add(1500, prendre_champ)
    return False


def prendre_champ():
    r["avant"] = app.fenetre.get_visible()
    r["champ"].grab_focus()
    GLib.timeout_add(1000, taper)
    return False


def taper():
    r["avec_champ"] = app.fenetre.get_visible()
    app.wl.taper(*app.codes["é"])
    GLib.timeout_add(600, prendre_bouton)
    return False


def prendre_bouton():
    r["texte"] = r["champ"].get_text()
    r["bouton"].grab_focus()
    GLib.timeout_add(1200, fin)
    return False


def fin():
    r["avec_bouton"] = app.fenetre.get_visible()
    app.quit()
    return False


app.connect("activate", lambda *a: GLib.timeout_add(1000, fenetre))   # globales du moteur reçues
app.run(None)
if not r:
    sys.exit(0)
conclure("clavier de session : apparition seule (champ GTK)",
         r.get("avant") is False and r.get("avec_champ") and r.get("texte") == "é" and r.get("avec_bouton") is False,
         {k: v for k, v in r.items() if k not in ("champ", "bouton")})
