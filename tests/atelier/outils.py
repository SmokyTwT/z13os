"""Petits outils communs aux essais de l'atelier (lancés par bureau.sh). GTK n'est chargé qu'au
premier usage : les modules Smoky doivent d'abord charger leurs bibliothèques Wayland (layer-shell,
session-lock), qui ne marchent que chargées avant GTK."""
import os
import sys

sys.path.insert(0, os.environ["SMOKY_LIB"])


def boutons(widget):
    """Tous les boutons sous `widget`, dans l'ordre."""
    from gi.repository import Gtk
    enfant = widget.get_first_child()
    while enfant:
        if isinstance(enfant, Gtk.Button):
            yield enfant
        yield from boutons(enfant)
        enfant = enfant.get_next_sibling()


def appuyer(widget, etiquette):
    """« Clique » le bouton qui porte cette étiquette (signal clicked, comme un doigt)."""
    for b in boutons(widget):
        if b.get_label() == etiquette:
            b.emit("clicked")
            return
    raise SystemExit(f"bouton introuvable : {etiquette!r}")


def conclure(nom, ok, details):
    print(f"{'OK ' if ok else 'KO '} {nom} {details}", flush=True)
    sys.exit(0 if ok else 1)
