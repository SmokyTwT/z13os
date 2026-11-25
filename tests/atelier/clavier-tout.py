"""Les 131 caractères du clavier de la session, tapés par le vrai clavier virtuel dans un champ GTK."""
from outils import conclure
from smokybureau import clavier_ecran, commun
from gi.repository import GLib, Gtk

app = clavier_ecran.ClavierSession()
attendu = "".join(c for c in commun.caracteres_session() if c not in commun.TOUCHES_ENVOYEES or c == " ")
r = {}


def fenetre():
    w = Gtk.Window(application=app, title="essai")
    r["champ"] = champ = Gtk.Entry()
    w.set_child(champ)
    w.present()
    champ.grab_focus()
    GLib.timeout_add(1500, taper)
    return False


def taper():
    for c in attendu:
        app.wl.taper(*app.codes[c])
    GLib.timeout_add(1500, fin)
    return False


def fin():
    r["texte"] = r["champ"].get_text()
    app.quit()
    return False


app.connect("activate", lambda *a: GLib.idle_add(fenetre))
app.run(None)
recu = r.get("texte", "")
ecarts = [(i, a, b) for i, (a, b) in enumerate(zip(attendu, recu)) if a != b][:6]
conclure("clavier de session : tous les caractères → champ GTK", recu == attendu,
         f"{len(recu)}/{len(attendu)} reçus, écarts {ecarts}")
