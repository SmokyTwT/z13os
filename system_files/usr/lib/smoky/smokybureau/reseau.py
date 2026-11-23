"""Smoky OS — Wi-Fi pour les réglages rapides : liste des réseaux et connexion, par nmcli.

Le mot de passe d'un nouveau réseau passe par l'entrée standard de nmcli (--ask), jamais sur la
ligne de commande (visible par les autres programmes). Comme sous GNOME, c'est NetworkManager qui
le garde, dans sa configuration réservée à l'administrateur ; Smoky ne l'écrit nulle part.
Sans GTK : testable partout (tests/test_bureau.py).
"""
import subprocess

from . import commun


def decouper(ligne):
    """Découpe une ligne de « nmcli -t » : les « : » des noms de réseau sont échappés en « \\: »."""
    champs, courant, echappe = [], "", False
    for c in ligne:
        if echappe:
            courant += c
            echappe = False
        elif c == "\\":
            echappe = True
        elif c == ":":
            champs.append(courant)
            courant = ""
        else:
            courant += c
    champs.append(courant)
    return champs


def reseaux(rescanner=False):
    """Réseaux visibles, le plus fort d'abord, un seul par nom :
    [{"nom", "signal", "securite", "actif", "connu", "entreprise"}]."""
    sortie = commun.commande("nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                             "--rescan", "yes" if rescanner else "auto", delai=20)
    connus = {decouper(l)[0] for l in commun.commande("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show").splitlines()
              if l.endswith(":802-11-wireless")}
    vus = {}
    for ligne in sortie.splitlines():
        champs = decouper(ligne)
        if len(champs) < 4 or not champs[1]:
            continue
        actif, nom, signal, securite = champs[0] == "*", champs[1], champs[2], champs[3]
        r = {"nom": nom, "signal": int(signal) if signal.isdigit() else 0, "securite": securite.strip(),
             "actif": actif, "connu": nom in connus, "entreprise": "802.1X" in securite}
        if nom not in vus or r["actif"] or r["signal"] > vus[nom]["signal"] and not vus[nom]["actif"]:
            vus[nom] = r
    return sorted(vus.values(), key=lambda r: (not r["actif"], -r["signal"]))


def connecter(reseau, mot_de_passe=None):
    """Se connecte. Renvoie None si c'est fait, sinon un message à afficher."""
    if reseau["connu"]:
        args = ["nmcli", "connection", "up", "id", reseau["nom"]]
        entree = None
    else:
        args = ["nmcli", "--ask", "device", "wifi", "connect", reseau["nom"]]
        entree = (mot_de_passe or "") + "\n"
    try:
        r = subprocess.run(args, input=entree, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        return "Le Wi-Fi ne répond pas."
    if r.returncode == 0:
        return None
    if "Secrets were required" in r.stderr or "password" in r.stderr.lower() or "802-11-wireless-security" in r.stderr:
        return "Mot de passe incorrect."
    return "Connexion impossible."
