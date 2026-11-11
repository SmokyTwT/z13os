#!/usr/bin/env python3
"""Compare les mesures de démarrage de deux images (relevées par tests/image/demarrer.sh).

  python3 tests/image/mesures.py DOSSIER_PUBLIEE DOSSIER_NOUVELLE     tableau comparatif
  python3 tests/image/mesures.py --verifier                           auto-contrôle de la lecture

Chaque dossier contient mesures-1.txt (1er démarrage) et mesures-2.txt (2e démarrage, celui de
tous les jours). Les durées viennent d'une petite machine virtuelle : seul l'écart entre les
deux images a un sens, pas les valeurs elles-mêmes.
"""
import re
import sys
from pathlib import Path


def secondes(texte):
    """« 1min 2.5s », « 850ms », « 3.2s » → secondes (None si illisible)."""
    total, vu = 0.0, False
    for valeur, unite in re.findall(r"([\d.]+)\s*(min|ms|s|h)\b", texte):
        try:
            total += float(valeur) * {"h": 3600, "min": 60, "s": 1, "ms": 0.001}[unite]
            vu = True
        except ValueError:
            return None
    return total if vu else None


def lire(fichier):
    """Fichier de mesures → dictionnaire (valeurs absentes = None / listes vides)."""
    m = {"total": None, "noyau": None, "initrd": None, "systeme": None, "graphique": None, "memoire": None,
         "disponible": None, "processus": None, "services": [], "echecs": [], "longs": [], "gros": [],
         "ecran_lance": None, "ecran_affiche": None, "arret": None, "retards": []}
    try:
        lignes = Path(fichier).read_text(errors="replace").splitlines()
    except OSError:
        return None
    section = ""
    for ligne in lignes:
        if ligne.startswith("== "):
            section = ligne[3:].split(" (")[0].strip()
            continue
        if not ligne.strip():
            continue
        if section == "durée":
            if "Startup finished in" in ligne:
                corps, _, total = ligne.partition("=")
                m["total"] = secondes(total)
                for cle, nom in (("noyau", "kernel"), ("initrd", "initrd"), ("systeme", "userspace")):
                    trouve = re.search(r"((?:[\d.]+(?:min|ms|s|h)\s*)+)\(" + nom + r"\)", corps)
                    if trouve:
                        m[cle] = secondes(trouve.group(1))
            elif "reached after" in ligne:
                m["graphique"] = secondes(ligne.split("reached after", 1)[1])
        elif section.startswith("services les plus longs"):
            trouve = re.match(r"\s*((?:[\d.]+(?:min|ms|s|h)\s+)+)(\S+)", ligne)
            if trouve and secondes(trouve.group(1)) is not None:
                m["longs"].append((trouve.group(2), secondes(trouve.group(1))))
        elif section == "services qui tournent":
            m["services"] += ligne.split()
        elif section == "services en échec":
            m["echecs"] += ligne.split()
        elif section == "mémoire":
            champs = ligne.split()
            if champs and champs[0] == "Mem:" and len(champs) >= 7:
                m["memoire"], m["disponible"] = int(champs[2]), int(champs[6])
        elif section == "processus les plus gros":
            champs = ligne.split(None, 1)
            if len(champs) == 2:
                try:
                    m["gros"].append((champs[1], float(champs[0])))
                except ValueError:
                    pass
        elif section == "nombre de processus":
            if ligne.strip().isdigit():
                m["processus"] = int(ligne.strip())
        elif section == "écran de connexion":
            mot, _, valeur = ligne.partition(" ")
            if mot in ("lancé", "affiché"):
                try:
                    m["ecran_lance" if mot == "lancé" else "ecran_affiche"] = float(valeur)
                except ValueError:
                    pass
        elif section == "arrêt":
            if ligne.startswith("durée "):
                try:
                    m["arret"] = float(ligne.split()[-1])
                except ValueError:
                    pass
            elif ligne.startswith("retard : "):
                m["retards"].append(ligne[len("retard : "):])
    return m


def fmt(v, unite="s"):
    if v is None:
        return "—"
    return f"{v:.1f} {unite}" if isinstance(v, float) else f"{v} {unite}".strip()


def ecart(a, b, unite="s"):
    if a is None or b is None:
        return ""
    d = b - a
    if abs(d) < (0.05 if isinstance(d, float) else 1):
        return "="
    return f"{d:+.1f} {unite}" if isinstance(d, float) else f"{d:+d} {unite}".strip()


def comparer(dossier_a, dossier_b):
    sortie = ["### Démarrage : image publiée → nouvelle image", "",
              "Machine virtuelle de test (2 cœurs, 4 Go) : seul l'écart compte, pas les valeurs.", "", "```"]
    for n, titre in ((2, "2e démarrage (celui de tous les jours)"), (1, "1er démarrage (après une mise à jour)")):
        a, b = lire(Path(dossier_a) / f"mesures-{n}.txt"), lire(Path(dossier_b) / f"mesures-{n}.txt")
        if not a or not b:
            sortie.append(f"{titre} : mesures indisponibles ({'publiée' if not a else 'nouvelle'})")
            continue
        sortie.append(f"{titre:<44}{'publiée':>10}{'nouvelle':>11}   écart")
        for libelle, cle, unite in (("  écran de connexion affiché à", "ecran_affiche", "s"), ("  écran de connexion lancé à", "ecran_lance", "s"),
                                    ("  démarrage terminé (total)", "total", "s"), ("    dont noyau", "noyau", "s"),
                                    ("    dont image de démarrage", "initrd", "s"), ("    dont système", "systeme", "s"),
                                    ("  arrêt", "arret", "s"), ("  mémoire utilisée", "memoire", "Mo"), ("  processus", "processus", "")):
            sortie.append(f"{libelle:<44}{fmt(a[cle], unite):>10}{fmt(b[cle], unite):>11}   {ecart(a[cle], b[cle], unite)}")
        sa, sb = set(a["services"]), set(b["services"])
        sortie.append(f"{'  services qui tournent':<44}{len(sa):>10}{len(sb):>11}   {ecart(len(sa), len(sb), '')}")
        if sb - sa:
            sortie.append("    en plus  : " + " ".join(sorted(sb - sa)))
        if sa - sb:
            sortie.append("    en moins : " + " ".join(sorted(sa - sb)))
        if set(a["echecs"]) != set(b["echecs"]):
            sortie.append(f"  services en échec : {' '.join(a['echecs']) or 'aucun'} → {' '.join(b['echecs']) or 'aucun'}")
        for retard in b["retards"]:
            sortie.append(f"  arrêt retardé par : {retard}")
        if n == 2:
            avant = dict(a["longs"])
            sortie.append("  services les plus longs à démarrer (nouvelle image ; entre parenthèses : image publiée)")
            for nom, duree in b["longs"][:12]:
                sortie.append(f"    {duree:6.2f} s  {nom}" + (f"  ({avant[nom]:.2f} s)" if nom in avant else "  (absent)"))
        sortie.append("")
    sortie.append("```")
    return "\n".join(sortie)


EXEMPLE = """== durée
Startup finished in 1.137s (kernel) + 2.631s (initrd) + 1min 5.940s (userspace) = 1min 9.708s
graphical.target reached after 15.901s in userspace.
== services les plus longs à démarrer
6.412s NetworkManager-wait-online.service
 850ms firewalld.service
1min 2.100s lent.service
== chaîne critique (ce qui retarde l'écran de connexion)
graphical.target @15.901s
== services qui tournent
gdm.service polkit.service
== services en échec
mcelog.service
== mémoire (Mo)
               total        used        free      shared  buff/cache   available
Mem:            3905         812        2101          12        1200        3093
Swap:           3904           0        3904
== processus les plus gros (Mo)
  212.5 gnome-shell
== nombre de processus
143
== écran de connexion (secondes depuis le lancement du noyau)
lancé 3.2
affiché 6.9
== arrêt
durée 48
retard : user@1000.service: State 'stop-sigterm' timed out. Killing.
"""


def verifier():
    import tempfile
    assert secondes("1min 2.5s") == 62.5 and secondes("850ms") == 0.85 and secondes("rien") is None
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "mesures-2.txt").write_text(EXEMPLE)
        m = lire(Path(d) / "mesures-2.txt")
        assert (m["noyau"], m["initrd"], m["systeme"]) == (1.137, 2.631, 65.94), m
        assert abs(m["total"] - 69.708) < 1e-6 and m["graphique"] == 15.901, m
        assert m["longs"] == [("NetworkManager-wait-online.service", 6.412), ("firewalld.service", 0.85), ("lent.service", 62.1)], m["longs"]
        assert (m["memoire"], m["disponible"], m["processus"]) == (812, 3093, 143), m
        assert m["services"] == ["gdm.service", "polkit.service"] and m["echecs"] == ["mcelog.service"]
        assert m["gros"] == [("gnome-shell", 212.5)]
        assert (m["ecran_lance"], m["ecran_affiche"], m["arret"]) == (3.2, 6.9, 48.0), m
        assert m["retards"] == ["user@1000.service: State 'stop-sigterm' timed out. Killing."], m["retards"]
        assert lire(Path(d) / "absent.txt") is None
        texte = comparer(d, d)
        assert "1er démarrage (après une mise à jour) : mesures indisponibles" in texte and "69.7 s" in texte, texte
        assert "arrêt retardé par : user@1000.service" in texte and "6.9 s" in texte, texte
    print("mesures.py : lecture vérifiée")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--verifier":
        verifier()
    elif len(sys.argv) == 3:
        print(comparer(sys.argv[1], sys.argv[2]))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
