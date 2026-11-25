"""Clavier à l'écran et vrai clavier branché (signalé le 25/11 : Z13 détaché, clavier externe sur
un hub, le clavier à l'écran sortait quand même). Un faux /proc/bus/input/devices remplace celui du
PC ; il faut le labwc 0.7.4 de preparer.sh (méthode de saisie).

  1. vrai clavier branché, apparition permise (mode tablette) : un champ prend la main, rien ne sort ;
  2. plus de clavier : il sort dans le champ ;
  3. on branche un clavier pendant qu'il est sorti tout seul : il se range ;
  4. ouvert par le bouton de la barre : il reste, même avec un vrai clavier ;
  5. sorti tout seul, apparition plus permise (clavier rattaché) : il se range ;
  6. ouvert par le bouton, apparition plus permise : il se range aussi (le bouton disparaît)."""
import os
import sys
import tempfile

from outils import conclure
from smokybureau import clavier_ecran, commun
from gi.repository import Gio, GLib, Gtk

BOUTONS = """I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
H: Handlers=kbd event0
B: PROP=0
B: EV=3
B: KEY=10000000000000 0
"""
CLAVIER_HUB = """I: Bus=0003 Vendor=0c45 Product=7638 Version=0111
N: Name="SONiX USB Keyboard"
P: Phys=usb-0000:00:14.0-3.2/input0
H: Handlers=sysrq kbd leds event12
B: PROP=0
B: EV=120013
B: KEY=1000000000007 ff800000000007ff febeffdfffefffff fffffffffffffffe
B: MSC=10
B: LED=7
"""
faux = tempfile.NamedTemporaryFile("w", suffix="-devices", delete=False)
faux.close()
commun.PERIPHERIQUES = type(commun.PERIPHERIQUES)(faux.name)


def peripheriques(avec_clavier):
    with open(faux.name, "w") as f:
        f.write(BOUTONS + ("\n" + CLAVIER_HUB if avec_clavier else ""))


app = clavier_ecran.ClavierSession()
reglages = Gio.Settings.new("org.gnome.desktop.a11y.applications")
r = {}


def visible():
    return bool(app.fenetre and app.fenetre.get_visible())


def etapes():
    """Chaque étape : (action, délai avant la suivante en ms)."""
    yield (lambda: (peripheriques(True), reglages.set_boolean("screen-keyboard-enabled", True),
                    r["bouton"].grab_focus()), 800)
    yield (lambda: r["champ"].grab_focus(), 1200)
    yield (lambda: r.__setitem__("1 vrai clavier, champ", visible()), 10)
    yield (lambda: r["bouton"].grab_focus(), 800)
    yield (lambda: (peripheriques(False), r["champ"].grab_focus()), 1200)
    yield (lambda: r.__setitem__("2 sans clavier, champ", visible()), 10)
    yield (lambda: peripheriques(True), 3500)                          # branché pendant qu'il est sorti
    yield (lambda: r.__setitem__("3 clavier branché ensuite", visible()), 10)
    yield (lambda: app.montrer_main(), 3500)                           # bouton de la barre
    yield (lambda: r.__setitem__("4 ouvert à la main", visible()), 10)
    yield (lambda: (app.cacher(), r["bouton"].grab_focus()), 800)
    yield (lambda: (peripheriques(False), r["champ"].grab_focus()), 1200)
    yield (lambda: r.__setitem__("5a sorti tout seul", visible()), 10)
    yield (lambda: reglages.set_boolean("screen-keyboard-enabled", False), 800)
    yield (lambda: r.__setitem__("5b apparition plus permise", visible()), 10)
    yield (lambda: (reglages.set_boolean("screen-keyboard-enabled", True), app.montrer_main()), 800)
    yield (lambda: r.__setitem__("6a ouvert à la main", visible()), 10)
    yield (lambda: reglages.set_boolean("screen-keyboard-enabled", False), 800)
    yield (lambda: r.__setitem__("6b plus permis", visible()), 10)


suite = None


def avancer():
    try:
        action, delai = next(suite)
    except StopIteration:
        app.quit()
        return False
    action()
    GLib.timeout_add(delai, avancer)
    return False


def fenetre():
    global suite
    if not app.wl.gestion_saisie:
        print("SAUTÉ clavier de session et vrai clavier (ce labwc n'a pas de méthode de saisie)")
        app.quit()
        return False
    w = Gtk.Window(application=app, title="essai")
    boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    r["bouton"] = Gtk.Button(label="pas un champ")
    r["champ"] = Gtk.Entry()
    boite.append(r["bouton"])
    boite.append(r["champ"])
    w.set_child(boite)
    w.present()
    suite = etapes()
    GLib.timeout_add(800, avancer)
    return False


app.connect("activate", lambda *a: GLib.timeout_add(1000, fenetre))   # globales du moteur reçues
app.run(None)
os.unlink(faux.name)
resultats = {k: v for k, v in r.items() if k[0].isdigit()}
if not resultats:
    sys.exit(0)
attendu = {"1 vrai clavier, champ": False, "2 sans clavier, champ": True, "3 clavier branché ensuite": False,
           "4 ouvert à la main": True, "5a sorti tout seul": True, "5b apparition plus permise": False,
           "6a ouvert à la main": True, "6b plus permis": False}
conclure("clavier de session : rangé quand un vrai clavier est branché (même derrière un hub)",
         resultats == attendu, resultats)
