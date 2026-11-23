#!/usr/bin/python3 -I
"""Smoky OS — lanceur de smokybureau.bureau (code dans /usr/lib/smoky/smokybureau)."""
import os
import sys

sys.path.insert(0, os.environ.get("SMOKY_LIB", "/usr/lib/smoky"))
from smokybureau.bureau import main  # noqa: E402

main()
