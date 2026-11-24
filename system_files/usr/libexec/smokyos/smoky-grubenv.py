#!/usr/bin/python3 -I
"""Smoky OS — écrit une variable dans le bloc d'environnement de GRUB (grubenv), comme
« grub2-editenv FICHIER set CLÉ=VALEUR », pour les images où grub2-editenv n'est pas installé.

Format : en-tête « # GRUB Environment Block », les commentaires qui le suivent (GRUB 2.12 ajoute
un avertissement), une ligne clé=valeur par variable, puis des « # » jusqu'à 1024 octets tout
juste (GRUB réécrit ce bloc sur place : la taille ne doit pas changer). Le fichier est remplacé
d'un coup (écrit à côté puis renommé)."""
import os
import sys

TAILLE = 1024
ENTETE = "# GRUB Environment Block\n"


def lire(chemin):
    """→ (commentaires, variables) ; le remplissage final (« #### » sans fin de ligne) est ignoré."""
    commentaires, variables = [], {}
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            lignes = f.read().split("\n")
    except FileNotFoundError:
        return commentaires, variables
    for ligne in lignes[:-1]:                    # la dernière « ligne » est le remplissage
        if ligne == ENTETE.strip() or not ligne:
            continue
        if ligne.startswith("#"):
            commentaires.append(ligne)
        elif "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            variables[cle] = valeur
    return commentaires, variables


def ecrire(chemin, commentaires, variables):
    corps = ENTETE + "".join(c + "\n" for c in commentaires) + "".join(f"{c}={v}\n" for c, v in variables.items())
    if len(corps.encode()) > TAILLE:
        raise SystemExit("grubenv plein")
    corps += "#" * (TAILLE - len(corps.encode()))
    with open(chemin + ".new", "w", encoding="utf-8") as f:
        f.write(corps)
        f.flush()
        os.fsync(f.fileno())
    os.rename(chemin + ".new", chemin)


def main(args):
    if len(args) != 2 or "=" not in args[1] or "\n" in args[1]:
        raise SystemExit("usage : smoky-grubenv.py FICHIER CLÉ=VALEUR")
    chemin, (cle, valeur) = args[0], args[1].split("=", 1)
    commentaires, variables = lire(chemin)
    variables[cle] = valeur
    ecrire(chemin, commentaires, variables)


if __name__ == "__main__":
    main(sys.argv[1:])
