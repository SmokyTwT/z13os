#!/usr/bin/python3 -I
"""Smoky OS — adaptation automatique à la batterie (service smoky-adaptive).
Le code est dans /usr/lib/smoky/smokybureau/energie.py (bureau Smoky)."""
import os
import sys

sys.path.insert(0, os.environ.get("SMOKY_LIB", "/usr/lib/smoky"))
from smokybureau.energie import main  # noqa: E402

main()
