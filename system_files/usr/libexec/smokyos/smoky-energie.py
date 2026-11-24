#!/usr/bin/env python3
"""Smoky OS — mesure d'énergie, en lecture seule (lancée par « smoky-diagnostic --energie »).

  smoky-diagnostic --energie [SECONDES]   consommation moyenne, autonomie, réglages, ce qui travaille
  sudo smoky-diagnostic --energie-paquet   les états de repos du processeur entier (20 s)

Pendant la mesure : sur batterie, écran allumé, sans toucher au PC. Rien n'est modifié.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BATTERIE = Path(os.environ.get("SMOKY_BATTERIE", "/sys/class/power_supply/BAT0"))
PMC = Path("/sys/kernel/debug/pmc_core/package_cstate_show")


def lire(chemin, defaut=""):
    try:
        return Path(chemin).read_text().strip()
    except (OSError, ValueError):
        return defaut


def nombre(nom):
    v = lire(BATTERIE / nom)
    return int(v) if v.isdigit() else None


def commande(*args, delai=8):
    if not shutil.which(args[0]):
        return ""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=delai).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def fr(x, chiffres=1):
    return f"{x:.{chiffres}f}".replace(".", ",")


def duree(minutes):
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def puissance():
    """Watts consommés à cet instant (None si inconnu)."""
    p = nombre("power_now")
    if p is None and nombre("current_now") is not None and nombre("voltage_now"):
        p = nombre("current_now") * nombre("voltage_now") // 1_000_000
    return p / 1e6 if p else None


def energie():
    """(Wh restants, Wh d'une batterie pleine)."""
    e, f = nombre("energy_now"), nombre("energy_full")
    if e is None and nombre("charge_now") is not None:
        u = nombre("voltage_min_design") or nombre("voltage_now") or 0
        e, f = nombre("charge_now") * u // 1_000_000, (nombre("charge_full") or 0) * u // 1_000_000
    return (e / 1e6 if e else None), (f / 1e6 if f else None)


# --- ce qui travaille : temps processeur par programme ------------------------------------------------
def temps_processeur():
    """{pid: (nom, tics)} de tous les processus visibles."""
    sortie = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            brut = Path(d, "stat").read_text()
        except OSError:
            continue
        nom = brut[brut.find("(") + 1:brut.rfind(")")]
        champs = brut[brut.rfind(")") + 2:].split()
        try:
            sortie[d] = (nom, int(champs[11]) + int(champs[12]))
        except (IndexError, ValueError):
            continue
    return sortie


def cstates():
    """{nom de l'état de repos: µs cumulées sur tous les cœurs}."""
    total = {}
    for etat in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpuidle/state[0-9]*"):
        nom, t = lire(f"{etat}/name"), lire(f"{etat}/time")
        if nom and t.isdigit():
            total[nom] = total.get(nom, 0) + int(t)
    return total


def paquet():
    """{« Package C10 » : µs} (pmc_core, lisible par root seulement)."""
    sortie = {}
    for ligne in lire(PMC).splitlines():
        m = re.match(r"\s*(Package C\d+\w*)\s*:\s*(\d+)", ligne)
        if m:
            sortie[m.group(1)] = int(m.group(2))
    return sortie


# --- réglages qui comptent pour l'autonomie -------------------------------------------------------------
def frequence_ecran():
    """Hz de l'écran intégré, demandé au moteur d'affichage (wlr-randr, bureau Smoky)."""
    import json
    try:
        sorties = json.loads(commande("wlr-randr", "--json") or "[]")
    except ValueError:                                  # pas de session (sudo, console) : on s'en passe
        return "?"
    for s in sorties:
        mode = next((m for m in s.get("modes", []) if m.get("current")), None)
        if mode and s.get("name", "").startswith("eDP"):
            return f"{mode['refresh']:.0f} Hz ({mode['width']} × {mode['height']})"
    return "?"


def reglages():
    lignes = []
    lumiere = glob.glob("/sys/class/backlight/*/brightness")
    if lumiere:
        b, m = lire(lumiere[0]), lire(Path(lumiere[0]).with_name("max_brightness"))
        if b.isdigit() and m.isdigit() and int(m):
            auto = commande("gsettings", "get", "org.gnome.settings-daemon.plugins.power", "ambient-enabled")
            lignes.append(f"écran : luminosité {100 * int(b) // int(m)} %, luminosité automatique : {'oui' if auto == 'true' else 'non' if auto else '?'}, "
                          f"fréquence {frequence_ecran()}")
    clavier = glob.glob("/sys/class/leds/*kbd_backlight/brightness")
    if clavier:
        lignes.append(f"rétroéclairage du clavier : {lire(clavier[0])} sur {lire(Path(clavier[0]).with_name('max_brightness'))}")
    profil = commande("powerprofilesctl", "get") or "?"
    lignes.append(f"profil d'énergie : {profil} (power-profiles-daemon, seul à le changer)")
    cpu = "/sys/devices/system/cpu/cpu0/cpufreq"
    turbo = lire("/sys/devices/system/cpu/intel_pstate/no_turbo")
    maxi = lire(f"{cpu}/scaling_max_freq")
    lignes.append(f"processeur : préférence {lire(f'{cpu}/energy_performance_preference', '?')}, "
                  f"turbo {'coupé' if turbo == '1' else 'actif' if turbo == '0' else '?'}, régulateur {lire(f'{cpu}/scaling_governor', '?')}, "
                  f"fréquence max {f'{int(maxi) // 1000} MHz' if maxi.isdigit() else '?'}")
    lignes.append(f"profil du firmware : {lire('/sys/firmware/acpi/platform_profile', '?')} "
                  f"(choix : {lire('/sys/firmware/acpi/platform_profile_choices', '?')})")
    asusd = lire("/etc/asusd/asusd.ron")
    reglages_asus = [l.strip().rstrip(",") for l in asusd.splitlines() if re.search(r"platform_profile|change_|charge_control|epp", l)]
    if reglages_asus:
        lignes.append("asusd : " + " ; ".join(reglages_asus)[:400])
    politique = lire("/sys/module/pcie_aspm/parameters/policy", "?")
    journal_lisible = bool(commande("journalctl", "-k", "-b", "-n", "1", "--no-pager", "-o", "cat"))
    noyau = commande("journalctl", "-k", "-b", "--no-pager", "-o", "cat", "-g", "ASPM", delai=10) if journal_lisible else ""
    interdit = "oui" if "FADT declares the system doesn't support PCIe ASPM" in noyau else "non" if journal_lisible else "? (journal illisible)"
    lignes.append(f"PCIe ASPM (veille des liaisons) : politique {politique} ; interdit par le firmware : {interdit}")
    for p in glob.glob("/sys/bus/pci/devices/*"):
        if lire(f"{p}/vendor") == "0x10de" and lire(f"{p}/class").startswith("0x03"):
            lignes.append(f"carte NVIDIA : {lire(f'{p}/power/runtime_status', '?')} / {lire(f'{p}/power_state', '?')}")
            break
    else:
        lignes.append("carte NVIDIA : retirée du bus (éteinte)")
    for interface in commande("iw", "dev").split("Interface ")[1:]:
        nom = interface.split()[0]
        lignes.append(f"Wi-Fi ({nom}) : économie d'énergie {commande('iw', 'dev', nom, 'get', 'power_save').replace('Power save: ', '') or '?'}")
    for rf in glob.glob("/sys/class/rfkill/rfkill*"):
        if lire(f"{rf}/type") == "bluetooth":
            lignes.append(f"Bluetooth : {'coupé' if lire(f'{rf}/soft') == '1' or lire(f'{rf}/hard') == '1' else 'allumé'}")
            break
    maison = commande("systemctl", "--user", "is-active", "smoky-home.service")
    lignes.append(f"Smoky Home (Home Assistant) : {'en marche' if maison == 'active' else 'arrêté'}")
    return lignes


# --- mesures ---------------------------------------------------------------------------------------------
def mesure(secondes):
    print(f"Smoky OS : mesure d'énergie du {time.strftime('%d/%m/%Y %H:%M')} (lecture seule)")
    statut = lire(BATTERIE / "status", "?")
    if not BATTERIE.is_dir():
        print("\nPas de batterie trouvée : rien à mesurer ici.")
        print("\n== Réglages\n" + "\n".join(reglages()))
        return
    if statut != "Discharging":
        print(f"\nLe PC est branché ({statut}) : la consommation ne se mesure que sur batterie.")
        print("Débranche le chargeur, attends une minute, puis relance « smoky-diagnostic --energie ».")
        print("\n== Réglages\n" + "\n".join(reglages()))
        return
    print(f"Mesure pendant {secondes} s : ne touche à rien, laisse l'écran allumé…", flush=True)
    avant_proc, avant_c, avant_p, debut = temps_processeur(), cstates(), paquet(), time.monotonic()
    points = []
    while time.monotonic() - debut < secondes:
        w = puissance()
        if w:
            points.append(w)
        time.sleep(1)
    duree_s = time.monotonic() - debut
    apres_proc, apres_c, apres_p = temps_processeur(), cstates(), paquet()

    print("\n== Consommation")
    restant, pleine = energie()
    limite = nombre("charge_control_end_threshold")
    if points:
        moyenne = sum(points) / len(points)
        print(f"moyenne : {fr(moyenne)} W (de {fr(min(points))} à {fr(max(points))} W, {len(points)} lectures)")
        print(f"batterie : {lire(BATTERIE / 'capacity', '?')} %"
              + (f", {fr(restant)} Wh restants sur {fr(pleine)} Wh" if restant and pleine else "")
              + (f", limite de charge {limite} %" if limite else ""))
        if restant:
            print(f"à ce rythme : environ {duree(int(restant / moyenne * 60))} restantes")
        if pleine:
            print(f"batterie pleine (100 %) : environ {duree(int(pleine / moyenne * 60))}"
                  + (f" ; chargée jusqu'à {limite} % : environ {duree(int(pleine * limite / 100 / moyenne * 60))}" if limite and limite < 100 else ""))
    else:
        print("la batterie ne donne pas sa consommation (power_now absent)")

    print("\n== Réglages")
    print("\n".join(reglages()))

    print("\n== Repos des cœurs pendant la mesure")
    cpus = len(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpuidle"))
    if cpus and duree_s:
        parts = sorted(((n, (apres_c[n] - avant_c.get(n, 0)) / (cpus * duree_s * 1e6)) for n in apres_c), key=lambda x: -x[1])
        print(", ".join(f"{n} {100 * p:.0f} %" for n, p in parts if p >= 0.005) or "?")
        print("(au repos, un bon réglage laisse les cœurs plus de 90 % du temps dans l'état le plus profond)")
    if avant_p and apres_p:
        print("\n== Repos du processeur entier (paquet)")
        print(", ".join(f"{n.replace('Package ', '')} {100 * (apres_p[n] - avant_p.get(n, 0)) / (duree_s * 1e6):.0f} %" for n in apres_p))
    elif os.geteuid() != 0:
        print("\nPour voir le repos du processeur entier (le plus parlant) : sudo smoky-diagnostic --energie-paquet")

    print("\n== Ce qui a travaillé pendant la mesure (temps de processeur)")
    hertz = os.sysconf("SC_CLK_TCK")
    par_nom = {}
    for pid, (nom, tics) in apres_proc.items():
        delta = tics - avant_proc.get(pid, (nom, 0))[1]
        if delta > 0:
            t, n = par_nom.get(nom, (0, 0))
            par_nom[nom] = (t + delta, n + 1)
    for nom, (tics, n) in sorted(par_nom.items(), key=lambda x: -x[1][0])[:12]:
        print(f"  {fr(tics / hertz, 2):>6} s  {nom}{f' ({n})' if n > 1 else ''}")


def mesure_paquet(secondes=20):
    if os.geteuid() != 0:
        print("À lancer avec sudo : sudo smoky-diagnostic --energie-paquet")
        sys.exit(1)
    if not PMC.exists():
        print("Compteurs du processeur introuvables (pmc_core) : rien à mesurer ici.")
        return
    print(f"Smoky OS : repos du processeur entier pendant {secondes} s (ne touche à rien, écran allumé)…", flush=True)
    avant, debut = paquet(), time.monotonic()
    time.sleep(secondes)
    apres, ecoule = paquet(), time.monotonic() - debut
    print(", ".join(f"{n.replace('Package ', '')} {100 * (apres[n] - avant.get(n, 0)) / (ecoule * 1e6):.0f} %" for n in apres))
    print("(au repos, écran allumé, un PC bien réglé passe la majorité du temps en C8 ou C10 ;"
          " bloqué en C2 ou C3, un périphérique l'empêche de dormir)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--paquet":
        mesure_paquet()
    else:
        secondes = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60
        mesure(max(2, min(secondes, 600)))
