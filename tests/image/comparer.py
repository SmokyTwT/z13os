#!/usr/bin/env python3
"""Compare deux images Smoky OS : qu'est-ce qui change vraiment pour le PC ?

  comparer.py RACINE_ANCIENNE RACINE_NOUVELLE [PAQUETS_ANCIENS PAQUETS_NOUVEAUX]

Les racines sont deux images montées (podman image mount) ; les listes de paquets viennent de
« rpm -qa --qf '%{NAME} %{VERSION}-%{RELEASE}\\n' ». On ne regarde que ce qui est propre à
Smoky OS (fichiers Smoky, réglages de /etc, services, thèmes) : le reste appartient aux
paquets Fedora, résumés par la liste des paquets.

Sert à relire une modification de la construction avant de la publier : la sortie (Markdown)
est ajoutée au résumé du build GitHub. Ne bloque jamais une publication.
"""
import difflib
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

# zones propres à Smoky OS (dossiers entiers, ou fichiers dont le nom commence par un préfixe)
DOSSIERS = [
    "etc",
    "usr/libexec/smokyos", "usr/libexec/smokymail", "usr/libexec/smokyagenda", "usr/libexec/smokynotes",
    "usr/libexec/z13os",
    "usr/share/applications", "usr/share/smoky-center", "usr/share/smoky-home", "usr/share/smokyagenda",
    "usr/share/smokymail", "usr/share/smokynotes", "usr/share/smokyos", "usr/share/backgrounds/z13os",
    "usr/share/themes/Smoky", "usr/share/plymouth/themes/smoky", "usr/share/gnome-shell/extensions",
    "usr/share/icons/Smoky-icons", "usr/share/icons/Smoky-cursors",
    "usr/lib/systemd/system", "usr/lib/systemd/user", "usr/lib/modprobe.d", "usr/lib/sysctl.d", "usr/lib/tmpfiles.d",
]
PREFIXES = {"usr/bin": ("smoky-", "z13-"), "usr/share/glib-2.0/schemas": ("zz1-z13os",)}
FICHIERS = ["usr/lib/os-release", "usr/share/gnome-shell/gnome-shell-theme.gresource"]
# fichiers produits par les paquets à chaque installation : ils changent avec Fedora, pas avec Smoky OS
BRUIT = ("etc/ld.so.cache", "etc/selinux/", "etc/pki/", "etc/alternatives/", "etc/crypto-policies/",
         "etc/group", "etc/gshadow", "etc/passwd", "etc/shadow", "etc/subuid", "etc/subgid", "etc/.updated",
         "etc/dnf/", "etc/udev/hwdb.bin", "etc/machine-id")


def empreinte(p):
    st = os.lstat(p)
    if stat.S_ISLNK(st.st_mode):
        return "lien → " + os.readlink(p), ""
    if not stat.S_ISREG(st.st_mode):
        return "spécial", ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest(), oct(stat.S_IMODE(st.st_mode))


def inventaire(racine):
    racine = Path(racine)
    vus = {}

    def ajoute(p):
        rel = p.relative_to(racine).as_posix()
        if not rel.startswith(BRUIT):
            vus[rel] = empreinte(p)

    for d in DOSSIERS:
        base = racine / d
        if base.is_dir():
            for dossier, _sous, fichiers in os.walk(base):
                for nom in fichiers:
                    ajoute(Path(dossier) / nom)
                for nom in _sous:                       # liens vers des dossiers
                    if (Path(dossier) / nom).is_symlink():
                        ajoute(Path(dossier) / nom)
    for d, prefixes in PREFIXES.items():
        base = racine / d
        if base.is_dir():
            for p in base.iterdir():
                if p.name.startswith(prefixes):
                    ajoute(p)
    for f in FICHIERS:
        if (racine / f).exists() or (racine / f).is_symlink():
            ajoute(racine / f)
    return vus


def paquets(fichier):
    out = {}
    for ligne in Path(fichier).read_text().splitlines():
        nom, _, version = ligne.partition(" ")
        if nom:
            out[nom] = version
    return out


def liste(titre, lignes, maxi=80):
    print(f"\n**{titre}** : {len(lignes)}")
    if lignes:
        print()
        for l in lignes[:maxi]:
            print(f"- `{l}`")
        if len(lignes) > maxi:
            print(f"- … et {len(lignes) - maxi} autres")


def details(racine_a, racine_b, chemins, maxi_octets=40_000, maxi_lignes=40):
    """Différences ligne à ligne des petits fichiers texte modifiés (repliées dans le résumé)."""
    for rel in chemins:
        fa, fb = Path(racine_a, rel), Path(racine_b, rel)
        if fa.is_symlink() or fb.is_symlink() or not (fa.is_file() and fb.is_file()):
            continue
        if max(fa.stat().st_size, fb.stat().st_size) > maxi_octets:
            continue
        try:
            ta, tb = fa.read_text(encoding="utf-8"), fb.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        diff = list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), "publiée", "nouvelle", lineterm="", n=1))
        if not diff:
            diff = [f"(mêmes lignes ; fin de fichier différente : {ta[-20:]!r} → {tb[-20:]!r})"]
        print(f"\n<details><summary><code>{rel}</code></summary>\n\n```diff")
        print("\n".join(l[:200] for l in diff[:maxi_lignes]))
        if len(diff) > maxi_lignes:
            print(f"… ({len(diff) - maxi_lignes} lignes de plus)")
        print("```\n\n</details>")


def demarrage(racine):
    out = []
    for img in sorted(Path(racine, "usr/lib/modules").glob("*/initramfs.img")):
        out.append(f"{img.parent.name} : {img.stat().st_size / 1e6:.0f} Mo")
    return out


def theme_connexion(racine):
    gr = Path(racine, "usr/share/gnome-shell/gnome-shell-theme.gresource")
    try:
        r = subprocess.run(["gresource", "list", str(gr)], capture_output=True, text=True, timeout=30)
        return sorted(r.stdout.split()) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main():
    if len(sys.argv) not in (3, 5):
        sys.exit(__doc__)
    a, b = inventaire(sys.argv[1]), inventaire(sys.argv[2])
    print("### Comparaison avec l'image publiée (parties propres à Smoky OS)")
    print(f"\n{len(a)} fichiers comparés dans l'image publiée, {len(b)} dans la nouvelle.")
    liste("Fichiers retirés", sorted(set(a) - set(b)))
    liste("Fichiers ajoutés", sorted(set(b) - set(a)))
    modifies = sorted(k for k in set(a) & set(b) if a[k][0] != b[k][0])
    liste("Contenu modifié", modifies)
    details(sys.argv[1], sys.argv[2], modifies)
    liste("Droits modifiés (contenu identique)",
          sorted(f"{k} : {a[k][1]} → {b[k][1]}" for k in set(a) & set(b) if a[k][0] == b[k][0] and a[k][1] != b[k][1]))
    print(f"\n**Image de démarrage** : publiée {demarrage(sys.argv[1]) or '?'} · nouvelle {demarrage(sys.argv[2]) or '?'}")
    ta, tb = theme_connexion(sys.argv[1]), theme_connexion(sys.argv[2])
    if ta is not None and tb is not None:
        print(f"\n**Thème de connexion** : {len(ta)} fichiers → {len(tb)} fichiers"
              + ("" if ta == tb else f" (différences : {sorted(set(ta) ^ set(tb))[:10]})"))
    if len(sys.argv) == 5:
        pa, pb = paquets(sys.argv[3]), paquets(sys.argv[4])
        liste("Paquets retirés", sorted(set(pa) - set(pb)))
        liste("Paquets ajoutés", sorted(set(pb) - set(pa)))
        maj = sorted(f"{k} : {pa[k]} → {pb[k]}" for k in set(pa) & set(pb) if pa[k] != pb[k])
        liste("Paquets mis à jour par Fedora entre les deux constructions", maj, maxi=15)
    print()


if __name__ == "__main__":
    main()
