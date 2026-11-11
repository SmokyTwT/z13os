#!/usr/bin/env python3
"""Smoky OS — puce Intel seulement, même quand Windows est en mode « Ultimate ».

Le mode Ultimate d'Armoury Crate n'est pas un réglage de Windows : c'est un aiguillage
matériel (le « MUX ») enregistré dans le firmware du Z13. Il relie l'écran soit à la puce
Intel (valeur 1, « Optimus »), soit directement à la carte NVIDIA (valeur 0, « dGPU » =
Ultimate). Il reste donc en place quand on redémarre sur Smoky OS, et il ne change qu'à un
redémarrage : c'est pourquoi tout se joue ici, avant l'écran de connexion et à l'extinction.

  smokygpu.py demarrage   au démarrage (smoky-gpu.service) : si l'écran est relié à la NVIDIA,
                          on le rend à la puce Intel et on redémarre une fois, tout de suite.
  smokygpu.py windows     juste avant « Redémarrer sur Windows » (smoky-bootonce.sh) : si
                          Windows était en mode Ultimate, on le lui remet.
  smokygpu.py etat        affiche l'état, sans rien modifier (Smoky Center, dépannage).
  smokygpu.py note        message à afficher à la connexion, s'il y a du nouveau.
  smokygpu.py reessayer   (sudo) après deux essais ratés : autorise un nouvel essai au
                          prochain démarrage.

Garde-fous :
- un essai n'est lancé que s'il a d'abord été noté sur le disque (et relu) : sans cette
  trace on ne touche à rien, donc aucune boucle de redémarrages n'est possible ;
- jamais plus d'un redémarrage automatique par démarrage, et deux essais au plus tant que
  l'écran n'a pas été revu sur la puce Intel ;
- une valeur inattendue, un réglage absent ou une erreur = on ne touche à rien.
Réglages : /etc/smokyos/gpu.conf. Tous les cas sont rejoués par tests/test_gpu.py.
"""
import json
import os
import sys
import time
from pathlib import Path

# Emplacements (remplaçables pour les tests : aucun vrai firmware n'y est touché)
SYS = Path(os.environ.get("SMOKY_GPU_SYS", "/sys"))
FIRMWARE = SYS / "class/firmware-attributes"             # noyaux récents : asus-armoury/attributes/<réglage>/current_value
ANCIEN = SYS / "devices/platform/asus-nb-wmi"            # noyaux plus anciens : <réglage>
ETAT = Path(os.environ.get("SMOKY_GPU_ETAT", "/var/lib/smokyos/gpu.json"))
CONF = Path(os.environ.get("SMOKY_GPU_CONF", "/etc/smokyos/gpu.conf"))
SUPERGFX = Path(os.environ.get("SMOKY_GPU_SUPERGFX", "/etc/supergfxd.conf"))
BOOT_ID = Path(os.environ.get("SMOKY_GPU_BOOT_ID", "/proc/sys/kernel/random/boot_id"))

OPTIMUS, DGPU = 1, 0      # valeurs du MUX : écran sur la puce Intel / sur la carte NVIDIA (Ultimate)
GARDE = 180               # s : encore sur la NVIDIA moins de 3 min après un essai = essai raté
MAX_ESSAIS = 2            # essais au plus tant que l'écran n'a pas été revu sur la puce Intel


# --- Firmware --------------------------------------------------------------------------------
def _fichier(nom):
    try:
        recents = sorted(FIRMWARE.glob(f"asus*/attributes/{nom}/current_value"),
                         key=lambda f: (f.parts[-4] != "asus-armoury", str(f)))
    except OSError:
        recents = []
    for f in (*recents, ANCIEN / nom):
        if f.is_file():
            return f
    return None


def interface():
    f = _fichier("gpu_mux_mode")
    if f is None:
        return None
    return f.parts[-4] if FIRMWARE in f.parents else "asus-nb-wmi"


def lire(nom):
    """Valeur 0 ou 1 du réglage, None s'il est absent, illisible ou inattendu."""
    f = _fichier(nom)
    if f is None:
        return None
    try:
        v = f.read_text().strip()
    except (OSError, ValueError):
        return None
    return int(v) if v in ("0", "1") else None


def ecrire(nom, valeur):
    """→ (réussi, message). Le firmware peut refuser : ce n'est jamais une erreur fatale."""
    f = _fichier(nom)
    if f is None:
        return False, "réglage absent"
    try:
        with open(f, "w") as sortie:
            sortie.write(f"{int(valeur)}\n")
        return True, ""
    except OSError as e:
        return False, f"{e.strerror or e} (erreur {e.errno})"


# --- Réglages et mémoire ---------------------------------------------------------------------
def lire_conf():
    conf = {"intel_auto": "oui", "windows_ultimate": "auto"}
    permis = {"intel_auto": ("oui", "non"), "windows_ultimate": ("auto", "oui", "non")}
    try:
        lignes = CONF.read_text().splitlines()
    except (OSError, ValueError):
        return conf
    for ligne in lignes:
        cle, egal, valeur = ligne.split("#", 1)[0].partition("=")
        cle, valeur = cle.strip().lower(), valeur.strip().lower()
        if egal and cle in permis and valeur in permis[cle]:
            conf[cle] = valeur
    return conf


def lire_etat():
    try:
        etat = json.loads(ETAT.read_text())
    except (OSError, ValueError):
        return {}
    return etat if isinstance(etat, dict) else {}


def ecrire_etat(etat):
    """→ True seulement si l'état est bien sur le disque (écrit, synchronisé, puis relu)."""
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        tmp = ETAT.with_name(ETAT.name + ".tmp")
        with open(tmp, "w") as f:
            json.dump(etat, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)           # lisible par Smoky Center, écrit par root seulement
        os.replace(tmp, ETAT)
        dossier = os.open(ETAT.parent, os.O_RDONLY)
        try:
            os.fsync(dossier)
        finally:
            os.close(dossier)
        return json.loads(ETAT.read_text()) == etat
    except (OSError, ValueError) as e:
        print(f"smokygpu : état non enregistré ({e})", file=sys.stderr)
        return False


def boot_id():
    try:
        return BOOT_ID.read_text().strip()
    except OSError:
        return ""


def entier(v):
    """Nombre entier positif lu dans la mémoire ; tout le reste (texte, négatif, vrai/faux) vaut 0."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def veut_ultimate(conf, etat):
    """Faut-il remettre le mode Ultimate en repartant sur Windows ?"""
    if conf["windows_ultimate"] == "oui":
        return True
    return conf["windows_ultimate"] == "auto" and etat.get("windows_ultimate") is True


# --- Au démarrage ----------------------------------------------------------------------------
def corriger_supergfxd():
    """supergfxd ne doit pas croire qu'on veut la NVIDIA en direct (« AsusMuxDgpu ») : ce mode
    ne se choisit pas depuis Smoky OS, il ne peut venir que d'un passage en Ultimate."""
    try:
        conf = json.loads(SUPERGFX.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(conf, dict) or conf.get("mode") != "AsusMuxDgpu":
        return False
    conf["mode"] = "Integrated"
    try:
        tmp = SUPERGFX.with_name(SUPERGFX.name + ".smoky")
        tmp.write_text(json.dumps(conf, indent=2) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, SUPERGFX)
        return True
    except OSError:
        return False


def redemarrer():
    import signal
    import subprocess
    message = "Windows était en mode Ultimate : retour à la puce Intel, redémarrage…"
    try:
        subprocess.run(["plymouth", "display-message", f"--text={message}"], timeout=3,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = subprocess.run(["systemctl", "--no-block", "reboot"], timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"smokygpu : redémarrage impossible ({e})", file=sys.stderr)
        return False
    if r.returncode != 0:
        return False
    # Le service passe avant l'écran de connexion : on le retient jusqu'à l'arrêt du système
    # (qui met fin à cette attente : ce n'est pas une erreur).
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    time.sleep(float(os.environ.get("SMOKY_GPU_ATTENTE", "20")))
    return True


def demarrage():
    conf, etat, mux = lire_conf(), lire_etat(), lire("gpu_mux_mode")
    if mux is None:
        # PC sans cet aiguillage, ou réglage illisible : rien à faire, rien à écrire
        print("smokygpu : pas d'aiguillage graphique (MUX) lisible, rien à faire")
        return 0
    avant, maintenant, boot = dict(etat), int(time.time()), boot_id()
    etat["mux"] = mux

    if mux == OPTIMUS:
        # l'écran est sur la puce Intel : tout va bien
        if entier(etat.get("essai")):
            etat["dernier_basculement"] = etat["essai"]       # le retour à Intel a réussi
        for cle in ("essai", "essai_boot", "probleme"):
            etat.pop(cle, None)
        etat["essais"] = 0
        if corriger_supergfxd():
            print("smokygpu : mode « AsusMuxDgpu » retiré des réglages de supergfxd")
        if etat != avant:
            ecrire_etat(etat)
        print("smokygpu : écran relié à la puce Intel")
        return 0

    # mux == DGPU : Windows a laissé le mode Ultimate, l'écran est relié à la carte NVIDIA
    etat["windows_ultimate"] = True
    if boot and etat.get("essai_boot") == boot:
        # déjà demandé pendant ce démarrage (le firmware n'applique qu'au redémarrage)
        print("smokygpu : retour à la puce Intel déjà demandé, il attend le redémarrage")
        return 0
    if conf["intel_auto"] != "oui":
        etat["probleme"] = "Le retour automatique à la puce Intel est désactivé (/etc/smokyos/gpu.conf)."
        if etat != avant:
            ecrire_etat(etat)
        print("smokygpu : mode Ultimate laissé tel quel (intel_auto=non)")
        return 0
    en_attente = entier(etat.get("essai"))
    etat.pop("essai", None)
    etat.pop("essai_boot", None)
    if en_attente and abs(maintenant - en_attente) < GARDE:
        # on vient d'essayer et de redémarrer, et l'écran est toujours sur la NVIDIA :
        # pas de second redémarrage dans la foulée, on laisse arriver jusqu'au bureau
        etat["probleme"] = "L'écran est resté relié à la carte NVIDIA malgré un redémarrage."
        ecrire_etat(etat)
        print("smokygpu : toujours en mode Ultimate après un redémarrage, on n'insiste pas")
        return 0
    if entier(etat.get("essais")) >= MAX_ESSAIS:
        etat["probleme"] = ("Deux essais ratés : Smoky OS ne tente plus de revenir tout seul à la puce Intel. "
                            "Repasse Windows en mode Standard, ou lance : sudo python3 /usr/libexec/smokyos/smokygpu.py reessayer")
        if etat != avant:
            ecrire_etat(etat)
        print("smokygpu : deux essais ratés, plus de tentative automatique")
        return 0

    # L'essai est noté AVANT de toucher au firmware : c'est cette trace qui empêche toute boucle.
    etat["essai"], etat["essai_boot"] = maintenant, boot
    etat["essais"] = entier(etat.get("essais")) + 1
    etat.pop("probleme", None)
    if not ecrire_etat(etat):
        print("smokygpu : impossible de noter l'essai sur le disque, on ne touche à rien")
        return 0
    reussi, message = ecrire("gpu_mux_mode", OPTIMUS)
    if not reussi:
        # rien n'a changé dans le firmware : ce n'est pas un essai, et il n'y a pas de redémarrage
        etat.pop("essai", None)
        etat.pop("essai_boot", None)
        etat["essais"] -= 1
        etat["probleme"] = f"Le firmware a refusé de rendre l'écran à la puce Intel : {message}."
        ecrire_etat(etat)
        print(f"smokygpu : écriture refusée ({message})")
        return 0
    print("smokygpu : écran rendu à la puce Intel, redémarrage")
    if not redemarrer():
        etat["probleme"] = "Le changement est enregistré : redémarre Smoky OS pour revenir à la puce Intel."
        ecrire_etat(etat)
    return 0


# --- En repartant sur Windows ----------------------------------------------------------------
def windows():
    conf, etat, mux = lire_conf(), lire_etat(), lire("gpu_mux_mode")
    if mux is None or not veut_ultimate(conf, etat):
        return 0
    boot = boot_id()
    # Cas rare : le retour à Intel a été demandé pendant ce démarrage mais le PC n'a pas redémarré.
    # Le firmware affiche encore « NVIDIA » alors qu'il appliquera « Intel » : il faut réécrire.
    intel_en_attente = bool(boot) and etat.get("essai_boot") == boot
    if mux == DGPU and not intel_en_attente:
        return 0                          # déjà relié à la NVIDIA : Windows retrouvera Ultimate tel quel
    if boot and etat.get("remis_boot") == boot:
        return 0                          # déjà fait pendant ce démarrage
    if lire("dgpu_disable") == 1:
        ecrire("dgpu_disable", 0)         # le firmware refuse Ultimate tant que la NVIDIA est coupée
    reussi, message = False, ""
    for _ in range(6):
        reussi, message = ecrire("gpu_mux_mode", DGPU)
        if reussi:
            break
        time.sleep(float(os.environ.get("SMOKY_GPU_PAUSE", "0.5")))
    if reussi:
        etat["remis_boot"] = boot
        etat.pop("probleme_windows", None)
        if intel_en_attente:              # l'essai de ce démarrage est annulé
            etat.pop("essai", None)
            etat.pop("essai_boot", None)
            etat["essais"] = max(0, entier(etat.get("essais")) - 1)
        print("smokygpu : mode Ultimate remis pour Windows")
    else:
        etat["probleme_windows"] = f"Mode Ultimate non remis pour Windows : {message}."
        print(f"smokygpu : mode Ultimate non remis ({message})")
    ecrire_etat(etat)
    return 0


def reessayer():
    etat = lire_etat()
    for cle in ("essai", "essai_boot", "probleme"):
        etat.pop(cle, None)
    etat["essais"] = 0
    if not ecrire_etat(etat):
        print("À lancer avec sudo : sudo python3 /usr/libexec/smokyos/smokygpu.py reessayer", file=sys.stderr)
        return 1
    print("C'est noté : au prochain démarrage, Smoky OS réessaiera de revenir à la puce Intel.")
    return 0


# --- Lecture seule ---------------------------------------------------------------------------
def resume():
    """État pour Smoky Center et le dépannage. Ne modifie rien."""
    conf, etat, mux = lire_conf(), lire_etat(), lire("gpu_mux_mode")
    return {
        "mux": mux,                                    # None : pas d'aiguillage ; 1 : Intel ; 0 : NVIDIA (Ultimate)
        "interface": interface(),
        "nvidia_coupee": lire("dgpu_disable"),
        "intel_auto": conf["intel_auto"] == "oui",
        "windows_ultimate": veut_ultimate(conf, etat),
        "essais": entier(etat.get("essais")),
        "probleme": (etat.get("probleme") if mux == DGPU else None) or etat.get("probleme_windows"),
        "dernier_basculement": entier(etat.get("dernier_basculement")) or None,
    }


def note():
    """Texte à afficher une fois à la connexion (rien si rien de nouveau)."""
    conf, etat, mux = lire_conf(), lire_etat(), lire("gpu_mux_mode")
    marque = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "smoky" / "gpu-note"
    try:
        vu = marque.read_text().strip()
    except (OSError, ValueError):
        vu = ""
    if mux == DGPU and etat.get("probleme"):
        cle, texte = f"probleme:{boot_id()}", f"L'écran est relié à la carte NVIDIA (mode Ultimate de Windows). {etat['probleme']}"
    elif entier(etat.get("dernier_basculement")):
        cle = f"basculement:{etat['dernier_basculement']}"
        texte = "Windows était en mode Ultimate : Smoky OS a redémarré une fois pour repasser sur la puce Intel."
        if veut_ultimate(conf, etat):
            texte += " Le mode Ultimate sera remis quand tu passeras par « Redémarrer sur Windows » (Smoky Center)."
    else:
        return 0
    if cle == vu:
        return 0
    try:
        marque.parent.mkdir(parents=True, exist_ok=True)
        marque.write_text(cle)
    except OSError:
        pass
    print(texte)
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(line_buffering=True)    # chaque ligne part tout de suite au journal
    except (AttributeError, ValueError):
        pass
    action = argv[1] if len(argv) > 1 else ""
    if action == "demarrage":
        return demarrage()
    if action == "windows":
        return windows()
    if action == "etat":
        print(json.dumps(resume(), ensure_ascii=False, indent=1))
        return 0
    if action == "note":
        return note()
    if action == "reessayer":
        return reessayer()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
