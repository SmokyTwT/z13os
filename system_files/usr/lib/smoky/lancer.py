#!/usr/bin/python3 -I
"""Point d'entrée du serveur de Smoky (lancé par /usr/bin/smoky).

« -I » : Python ne regarde ni le dossier courant, ni les modules installés dans ton dossier
personnel, ni PYTHONPATH. Un fichier « random.py » ou « json.py » posé dans ton dossier
personnel ne peut donc pas casser l'appli, ni se faire passer pour un de ses modules.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoky.__main__ import main  # noqa: E402  (après le réglage du chemin, exprès)

sys.exit(main())
