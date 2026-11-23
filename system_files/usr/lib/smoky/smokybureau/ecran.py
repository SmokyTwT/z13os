"""Smoky OS — fréquence de l'écran intégré (60 Hz sur batterie, la plus haute sur secteur),
par wlr-randr. Sans GLib : testable partout (tests/test_bureau.py)."""
import json

from . import commun


def ecran_integre():
    """(nom, mode actuel, modes) de l'écran intégré, d'après wlr-randr ; None si introuvable."""
    try:
        sorties = json.loads(commun.commande("wlr-randr", "--json") or "[]")
    except ValueError:
        return None
    for s in sorties:
        if s.get("enabled") and (s["name"].startswith("eDP") or len(sorties) == 1):
            modes = s.get("modes", [])
            actuel = next((m for m in modes if m.get("current")), None)
            return s["name"], actuel, modes
    return None


def choisir_frequence(batterie):
    e = ecran_integre()
    if not e or not e[1]:
        return
    nom, actuel, modes = e
    memes = [m for m in modes if (m["width"], m["height"]) == (actuel["width"], actuel["height"])]
    if batterie:
        cibles = [m for m in memes if m["refresh"] >= 59] or memes
        cible = min(cibles, key=lambda m: m["refresh"])
    else:
        cible = max(memes, key=lambda m: m["refresh"])
    if abs(cible["refresh"] - actuel["refresh"]) > 0.5:
        commun.commande("wlr-randr", "--output", nom, "--mode",
                        f"{cible['width']}x{cible['height']}@{cible['refresh']:.3f}Hz")
