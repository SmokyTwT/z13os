"""Smoky OS — clavier tactile intégré à l'écran de connexion et à l'écran de verrouillage.

Il écrit directement dans le champ du mot de passe, sans dépendre d'aucun autre programme : il
marche donc clavier détaché, avant toute session. AZERTY, majuscules, chiffres, symboles et
lettres accentuées (couches dans commun.COUCHES_CLAVIER). Il est affiché d'office, se cache dès
qu'on tape sur un vrai clavier, et le bouton « Clavier » le remontre.
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import commun  # noqa: E402

REMONTEE = 380        # place laissée en bas au centre de l'écran quand le clavier est affiché
TOUCHES_DE_FRAPPE = (Gdk.KEY_BackSpace, Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_Tab)


class ClavierEcran(Gtk.Box):
    def __init__(self, champ, valider):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["clavier"],
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        self.champ, self.valider = champ, valider
        self.etat = ("abc", False)
        self.dessiner()

    def dessiner(self):
        while (enfant := self.get_first_child()):
            self.remove(enfant)
        couche, verrou = self.etat
        for rangee in commun.COUCHES_CLAVIER[couche]:
            ligne = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
            for touche in rangee.split(" "):
                texte = {"espace": " ", "⇧": "⇪" if verrou else "⇧"}.get(touche, touche)
                b = Gtk.Button(label=texte, css_classes=["touche"], can_focus=False, focus_on_click=False)
                if touche in commun.TOUCHES_SPECIALES:
                    b.add_css_class("speciale")
                if touche == "espace":
                    b.add_css_class("large")
                if touche == "⏎":
                    b.add_css_class("entree")
                if touche == "⇧" and couche == "ABC":
                    b.add_css_class("actif")
                b.connect("clicked", lambda _b, t=touche: self.appuyer(t))
                ligne.append(b)
            self.append(ligne)

    def appuyer(self, touche):
        if not self.champ.get_sensitive():           # vérification en cours
            return
        avant, ancien = self.etat, self.champ.get_text()
        texte, self.etat, valider = commun.touche_clavier(ancien, self.etat, touche)
        if texte != ancien:
            self.champ.set_text(texte)
            self.champ.set_position(-1)
        if self.etat != avant:
            self.dessiner()
        if valider:
            self.valider()


def ajouter(fenetre, superposition, champ, valider, centre=None):
    """Pose le clavier en bas de l'écran, au-dessus des boutons, avec un bouton « Clavier » pour le
    montrer ou le cacher ; le bloc du centre remonte pour rester visible. Renvoie le clavier."""
    clavier = ClavierEcran(champ, valider)
    clavier.set_margin_bottom(96)
    superposition.add_overlay(clavier)

    def montrer(visible):
        clavier.set_visible(visible)
        if centre is not None:
            centre.set_margin_bottom(REMONTEE if visible else 0)

    bouton = Gtk.Button(label="⌨  Clavier", css_classes=["action", "bouton-clavier"], halign=Gtk.Align.START,
                        valign=Gtk.Align.END, can_focus=False, focus_on_click=False)
    bouton.set_margin_start(26)
    bouton.set_margin_bottom(26)
    bouton.connect("clicked", lambda *a: montrer(not clavier.get_visible()))
    superposition.add_overlay(bouton)

    def touche_physique(_controleur, valeur, _code, _modificateurs):
        if Gdk.keyval_to_unicode(valeur) or valeur in TOUCHES_DE_FRAPPE:
            montrer(False)                            # un vrai clavier sert : on libère l'écran
        return False

    touches = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    touches.connect("key-pressed", touche_physique)
    fenetre.add_controller(touches)
    montrer(True)
    return clavier
