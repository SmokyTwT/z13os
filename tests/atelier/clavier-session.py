"""Clavier à l'écran de la session : on appuie sur ses vrais boutons, le texte doit arriver dans un
champ GTK qui a le clavier (majuscule, chiffre, symbole, espace, accent, ⌫, ⏎), puis ⌄ le range."""
from outils import appuyer, conclure
from smokybureau import clavier_ecran
from gi.repository import GLib, Gtk

app = clavier_ecran.ClavierSession()
r = {}


def fenetre():
    w = Gtk.Window(application=app, title="essai")
    r["champ"] = champ = Gtk.Entry()
    champ.connect("activate", lambda *a: r.setdefault("entree", champ.get_text()))
    w.set_child(champ)
    w.present()
    champ.grab_focus()
    GLib.timeout_add(1500, taper)
    return False


def taper():
    r["pret"] = bool(app.wl and app.wl.clavier)
    app.montrer_main()
    r["visible"] = app.fenetre.get_visible()
    for t in ["b", "⇧", "O", "n", "123", "1", "#+=", "€", "abc", " ", "àé", "é"]:
        appuyer(app.boite, t)
    app.appuyer("⌫")                          # touche à répétition : un geste, pas « clicked »
    for t in ["x", "⏎"]:
        appuyer(app.boite, t)
    GLib.timeout_add(800, verifier)
    return False


def verifier():
    r["texte"] = r["champ"].get_text()
    appuyer(app.boite, "⌄")
    r["range"] = not app.fenetre.get_visible()
    app.quit()
    return False


app.connect("activate", lambda *a: GLib.idle_add(fenetre))
app.run(None)
attendu = "bOn1€ x"
conclure("clavier de session : boutons → champ GTK",
         r.get("pret") and r.get("visible") and r.get("texte") == attendu and r.get("entree") == attendu
         and r.get("range"), {k: v for k, v in r.items() if k != "champ"})
