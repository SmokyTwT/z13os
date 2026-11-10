#!/usr/bin/env python3
"""Résume les couches d'une image publiée (manifeste lu sur l'entrée standard).

  skopeo inspect --raw docker://ghcr.io/smokytwt/z13os:latest | python3 tests/image/couches.py

Les dernières couches sont celles de Smoky OS : tant que le socle est réutilisé, ce sont les
seules que le PC télécharge lors d'une mise à jour.
"""
import json
import sys

couches = json.load(sys.stdin).get("layers", [])
total = sum(c["size"] for c in couches)
print(f"{len(couches)} couches, {total / 1e9:.2f} Go au total (taille compressée)")
debut = max(0, len(couches) - 8)
for i, c in enumerate(couches[debut:], start=debut + 1):
    print(f"  couche {i:>3} : {c['size'] / 1e6:>8.1f} Mo")
