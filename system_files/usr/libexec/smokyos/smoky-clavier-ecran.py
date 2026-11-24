#!/usr/bin/python3 -I
"""Smoky OS — lanceur du clavier à l'écran de la session (code : smokybureau/clavier_ecran.py)."""
import os
import sys

sys.path.insert(0, os.environ.get("SMOKY_LIB", "/usr/lib/smoky"))
from smokybureau.clavier_ecran import main  # noqa: E402

main()
