"""Smoky OS — clavier à l'écran de la session (remplace Stevia).

Une bande en bas de l'écran (layer-shell, au-dessus des fenêtres, qui leur laisse la place) qui ne
prend jamais le clavier : le champ de texte de l'appli garde la main. Les touches partent par un
clavier virtuel Wayland avec sa propre disposition (un code par caractère) : ça marche dans toutes
les applis, Chrome compris, quelle que soit la disposition du vrai clavier.

Quand il apparaît :
  * toujours par le bouton clavier de la barre (`smoky-bureau-cmd clavier basculer`) ;
  * tout seul quand un champ de texte prend la main (méthode de saisie Wayland ; les applis GTK
    le disent), si le mode tablette est actif ou le clavier détaché : smoky-adaptive règle alors
    org.gnome.desktop.a11y.applications screen-keyboard-enabled.
⌄ le range. Rien ne tourne quand il est caché : il attend les événements.
"""
import ctypes

for _nom in ("libgtk4-layer-shell.so.0", "libgtk4-layer-shell.so"):   # doit précéder libwayland
    try:
        ctypes.CDLL(_nom)
        break
    except OSError:
        pass

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import commun, wayland  # noqa: E402

SCHEMA_A11Y = "org.gnome.desktop.a11y.applications"
LIBELLES = {"espace": " ", "⌄": "⌄"}


class ClavierSession(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="fr.smoky.Clavier")
        self.etat = ("abc", False)
        self.fenetre = self.wl = None
        self.ouvert_a_la_main = False          # ouvert par le bouton : ne se range pas tout seul
        self.range_a_la_main = False           # rangé par ⌄ pendant qu'un champ a la main
        self.attente_cacher = self.repetition = 0
        self.keymap, self.codes = commun.keymap_clavier(commun.caracteres_session())

    # --- démarrage -------------------------------------------------------------------------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        for nom, rappel in (("basculer", self.basculer), ("montrer", self.montrer_main), ("cacher", self.cacher)):
            action = Gio.SimpleAction.new(nom, None)
            action.connect("activate", lambda *_a, f=rappel: f())
            self.add_action(action)
        self.hold()                            # reste là, caché, en attendant qu'on l'appelle

    def do_activate(self):
        if self.fenetre:
            return
        css = Gtk.CssProvider()
        css.load_from_path(str(commun.CSS))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        w = self.fenetre = Gtk.Window(application=self, css_classes=["smoky-clavier"])
        LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY)
        LS.set_namespace(w, "smoky-clavier")
        for bord in (LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(w, bord, True)
        LS.auto_exclusive_zone_enable(w)       # les fenêtres remontent au-dessus du clavier
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)   # ne prend jamais le clavier au champ de texte
        self.boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                             css_classes=["clavier", "clavier-session"])
        w.set_child(self.boite)
        self.dessiner()
        self.reglages = None
        source = Gio.SettingsSchemaSource.get_default()
        if source is not None and source.lookup(SCHEMA_A11Y, True) is not None:
            self.reglages = Gio.Settings.new(SCHEMA_A11Y)
        self.connecter()

    def connecter(self):
        try:
            self.wl = wayland.ClientClavier(self.keymap, quand_saisie=self.saisie)
        except (OSError, KeyError) as e:
            print("clavier à l'écran : moteur d'affichage injoignable :", e, flush=True)
            self.quit()
            return
        GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, self.wl.fileno(),
                              GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR, self.lire)

    def lire(self, *_):
        if not self.wl.lire():                 # moteur d'affichage parti : systemd relance si besoin
            self.quit()
            return False
        return True

    # --- dessin --------------------------------------------------------------------------------
    def dessiner(self):
        while (enfant := self.boite.get_first_child()):
            self.boite.remove(enfant)
        couche, verrou = self.etat
        rangees = commun.COUCHES_SESSION[couche]
        for n, rangee in enumerate(rangees):
            derniere = n == len(rangees) - 1
            ligne = Gtk.Box(spacing=6, homogeneous=not derniere)
            for touche in rangee.split(" "):
                texte = "⇪" if touche == "⇧" and verrou else LIBELLES.get(touche, touche)
                b = Gtk.Button(label=texte, css_classes=["touche"], can_focus=False, focus_on_click=False,
                               hexpand=not derniere or touche == "espace")
                if touche in commun.TOUCHES_SPECIALES or touche in commun.TOUCHES_A_REPETER or touche in ("⌄", "⇥"):
                    b.add_css_class("speciale")
                if touche == "⏎":
                    b.add_css_class("entree")
                if touche == "⇧" and couche == "ABC":
                    b.add_css_class("actif")
                if touche in commun.TOUCHES_A_REPETER:
                    self.repeter_si_maintenue(b, touche)
                else:
                    b.connect("clicked", lambda _b, t=touche: self.appuyer(t))
                ligne.append(b)
            self.boite.append(ligne)

    def repeter_si_maintenue(self, bouton, touche):
        """⌫ et les flèches : un appui tape tout de suite, maintenu il répète."""
        geste = Gtk.GestureClick(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        geste.connect("pressed", lambda *a: self.debut_repetition(touche))
        geste.connect("released", lambda *a: self.fin_repetition())
        geste.connect("stopped", lambda *a: self.fin_repetition())
        bouton.add_controller(geste)

    def debut_repetition(self, touche):
        self.fin_repetition()
        self.appuyer(touche)
        self.repetition = GLib.timeout_add(450, self.repeter, touche, True)

    def repeter(self, touche, premiere):
        self.appuyer(touche)
        if premiere:                           # puis plus vite tant que c'est maintenu
            self.repetition = GLib.timeout_add(70, self.repeter, touche, False)
            return False
        return True

    def fin_repetition(self):
        if self.repetition:
            GLib.source_remove(self.repetition)
            self.repetition = 0

    # --- frappe ----------------------------------------------------------------------------------
    def appuyer(self, touche):
        avant = self.etat
        self.etat, envoi = commun.touche_session(self.etat, touche)
        if envoi == "cacher":
            self.range_a_la_main = bool(self.wl and self.wl.saisie_active)
            self.cacher()
        elif envoi:
            code = self.codes.get(envoi)
            if code and self.wl:
                self.wl.taper(code)
        if self.etat != avant:
            self.dessiner()

    # --- apparition ------------------------------------------------------------------------------
    def automatique(self):
        try:
            return bool(self.reglages and self.reglages.get_boolean("screen-keyboard-enabled"))
        except GLib.Error:
            return False

    def saisie(self, actif):
        """Un champ de texte prend (True) ou rend (False) la main."""
        if self.attente_cacher:
            GLib.source_remove(self.attente_cacher)
            self.attente_cacher = 0
        if actif:
            if self.automatique() and not self.range_a_la_main:
                self.montrer()
        else:
            self.range_a_la_main = False
            if not self.ouvert_a_la_main:      # le champ suivant reprend souvent la main aussitôt
                self.attente_cacher = GLib.timeout_add(300, self.cacher_apres_attente)

    def cacher_apres_attente(self):
        self.attente_cacher = 0
        self.cacher()
        return False

    def montrer(self):
        if self.fenetre and not self.fenetre.get_visible():
            self.etat = ("abc", False)
            self.dessiner()
            self.fenetre.present()

    def montrer_main(self):
        self.ouvert_a_la_main = True
        self.montrer()

    def cacher(self):
        self.ouvert_a_la_main = False
        self.fin_repetition()
        if self.fenetre:
            self.fenetre.set_visible(False)

    def basculer(self):
        if self.fenetre and self.fenetre.get_visible():
            self.cacher()
        else:
            self.montrer_main()


def main():
    ClavierSession().run(None)
