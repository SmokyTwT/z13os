"""Clavier tactile de l'écran de connexion et du verrouillage : appuis sur ses vrais boutons dans un
champ de mot de passe GTK, ⏎ qui valide, champ bloqué pendant la vérification, centre qui remonte."""
from outils import appuyer, conclure
from smokybureau import clavier
from gi.repository import GLib, Gtk

r = {}


def essai(app):
    w = Gtk.ApplicationWindow(application=app)
    fond = Gtk.Overlay()
    fond.set_child(Gtk.Box(hexpand=True, vexpand=True))
    centre = Gtk.Box(valign=Gtk.Align.CENTER)
    champ = Gtk.PasswordEntry()
    centre.append(champ)
    fond.add_overlay(centre)
    w.set_child(fond)
    valide = []
    cl = clavier.ajouter(w, fond, champ, lambda: valide.append(champ.get_text()), centre)
    w.present()

    def taper():
        for t in ["m", "⇧", "O", "t", "123", "4", "#+=", "\\", "abc", " ", "àé", "é", "x", "⌫", "⏎"]:
            appuyer(cl, t)
        r.update(texte=champ.get_text(), valide=valide, marge=centre.get_margin_bottom(), visible=cl.get_visible())
        champ.set_sensitive(False)
        appuyer(cl, "a")
        r["bloque"] = champ.get_text()
        app.quit()
        return False
    GLib.timeout_add(500, taper)


app = Gtk.Application(application_id="fr.smoky.EssaiClavierConnexion")
app.connect("activate", essai)
app.run([])
attendu = "mOt4\\ é"
conclure("clavier de connexion : boutons → mot de passe",
         r.get("texte") == attendu and r.get("valide") == [attendu] and r.get("marge") == clavier.REMONTEE
         and r.get("bloque") == attendu, r)
