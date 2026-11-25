#!/usr/bin/env python3
"""Smoky OS 100 % maison — essai dans une machine virtuelle (QEMU + firmware UEFI OVMF), sans écran :
démarre l'OS, prend des captures, tape des commandes comme sur un clavier AZERTY."""
import json, os, shutil, socket, subprocess, sys, time
BRANCHEMENT = "--branchement" in sys.argv          # clavier branché seulement après le démarrage
SANS_PIT = "--sans-pit" in sys.argv                # comme un PC récent dont le firmware arrête le PIT
HUBS = 2 if "--hubs" in sys.argv else 1 if "--hub" in sys.argv else 0   # clavier derrière 1 ou 2 hubs
sys.argv = [a for a in sys.argv if a not in ("--branchement", "--sans-pit", "--hub", "--hubs")]
# où brancher le clavier : port 2 du contrôleur, ou port 3 d'un hub (lui-même sur le port 1 d'un autre hub)
CHEMIN = "2" if not HUBS else "2.3" if HUBS == 1 else "2.1.3"
CONCENTRATEURS = [] if not HUBS else ["-device", "usb-hub,bus=xhci.0,port=2"] + (
    ["-device", "usb-hub,bus=xhci.0,port=2.1"] if HUBS == 2 else [])
CLAVIER = {"driver": "usb-kbd", "id": "clavier-usb", "bus": "xhci.0", "port": CHEMIN}

ICI = os.path.dirname(os.path.abspath(__file__))
T = "/tmp/smokyos-essai"
shutil.rmtree(T, ignore_errors=True); os.makedirs(T)
shutil.copy("/usr/share/OVMF/OVMF_VARS_4M.fd", f"{T}/vars.fd")
qemu = subprocess.Popen([
    # sans contrôleur PS/2 (i8042=off) : comme un PC récent, seul le clavier USB existe
    "qemu-system-x86_64", "-machine", "q35,i8042=off" + (",pit=off,hpet=off" if SANS_PIT else ""), "-m", "1024", "-display", "none", "-net", "none",
    "-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
    "-drive", f"if=pflash,format=raw,file={T}/vars.fd",
    # démarrage depuis une clé USB virtuelle (copie jetable : l'image reste intacte)
    "-device", "qemu-xhci,id=xhci", "-drive", f"if=none,id=cle,format=raw,snapshot=on,file={ICI}/construit/smokyos.img",
    "-device", "usb-storage,bus=xhci.0,port=1,drive=cle", "-device", "usb-mouse,id=souris,bus=xhci.0,port=3",
    *CONCENTRATEURS,
    *([] if BRANCHEMENT else ["-device", f"usb-kbd,id=clavier-usb,bus=xhci.0,port={CHEMIN}"]),
    "-device", "virtio-vga", "-qmp", f"unix:{T}/qmp.sock,server,nowait", "-serial", f"file:{T}/serie.txt"],
    stderr=open(f"{T}/qemu.txt", "w"))
s = socket.socket(socket.AF_UNIX)
for _ in range(100):
    if qemu.poll() is not None: sys.exit("QEMU s'est arrêté au lancement")
    try:
        s.connect(f"{T}/qmp.sock"); break
    except OSError:
        time.sleep(0.2)
f = s.makefile("rw")
def qmp(cmd, **args):
    f.write(json.dumps({"execute": cmd, "arguments": args} if args else {"execute": cmd}) + "\n"); f.flush()
    while True:
        r = json.loads(f.readline())
        if "return" in r or "error" in r: return r
f.readline(); qmp("qmp_capabilities")
def capture(nom):
    qmp("screendump", filename=f"{T}/{nom}.ppm")
    subprocess.run(["convert", f"{T}/{nom}.ppm", "-resize", "50%", f"{T}/{nom}.png"])
def taper(touches):
    for t in touches:                           # seul clavier de la VM : le clavier USB
        qmp("send-key", keys=[{"type": "qcode", "data": t}]); time.sleep(0.15)
def combo(*touches):                            # touches enfoncées ensemble (Maj + chiffre, Alt + Tab…)
    qmp("send-key", keys=[{"type": "qcode", "data": k} for k in touches]); time.sleep(0.2)
def mot(texte):                                 # texte tapé sur un clavier AZERTY (lettres, chiffres, signes)
    azerty = {"a": "q", "z": "w", "q": "a", "w": "z", "m": "semicolon", " ": "spc", ",": "m", "*": "backslash",
              "(": "5", ")": "minus", "-": "6", "=": "equal"}
    for c in texte:
        if c.isdigit(): combo("shift", c)
        elif c == "+": combo("shift", "equal")
        else: combo(azerty.get(c, c))
def souris(dx, dy):                             # déplacement relatif, en petits pas
    qmp("input-send-event", events=[{"type": "rel", "data": {"axis": "x", "value": dx}},
                                    {"type": "rel", "data": {"axis": "y", "value": dy}}]); time.sleep(0.25)
def aller(x, y):                                # coin en haut à gauche, puis la position voulue
    souris(-5000, -5000); time.sleep(2)         # la souris de QEMU rend le déplacement par paquets de 127
    souris(int(x), int(y)); time.sleep(1.5)
def bouton(enfonce):
    qmp("input-send-event", events=[{"type": "btn", "data": {"down": enfonce, "button": "left"}}]); time.sleep(0.25)
def cliquer(x, y):
    aller(x, y); bouton(True); bouton(False); time.sleep(0.4)
attente = float(sys.argv[1]) if len(sys.argv) > 1 else 40
time.sleep(attente); capture("1-demarrage")
if BRANCHEMENT:                                  # branché, débranché, rebranché
    print(qmp("device_add", **CLAVIER))
    time.sleep(3)
    print(qmp("device_del", id="clavier-usb"))
    time.sleep(3)
    print(qmp("device_add", **CLAVIER))
    time.sleep(3)
taper(["q", "i", "d", "e", "ret"]); time.sleep(6)             # « aide » sur un clavier AZERTY
taper(["semicolon", "e", "semicolon", "o", "i", "r", "e", "ret"]); time.sleep(6)   # « memoire »
taper(["s", "y", "s", "t", "e", "semicolon", "e", "ret"]); time.sleep(6)            # « systeme »
taper(["h", "e", "u", "r", "e", "ret"]); time.sleep(6)                                # « heure »
# Maj, Alt Gr et accent circonflexe (touche morte), par le clavier USB : la ligne doit montrer « A€êé »
for touches in (["shift", "q"], ["alt_r", "e"], ["bracket_left"], ["e"], ["2"]):
    qmp("send-key", keys=[{"type": "qcode", "data": k} for k in touches]); time.sleep(0.2)
taper(["ret"]); time.sleep(4)
capture("2-aide")
taper(["e", "f", "f", "q", "c", "e", "r", "ret"]); time.sleep(3)                  # « effacer »
taper(["u", "s", "b", "ret"]); time.sleep(4)                                       # « usb »
capture("3-usb")
taper(["b", "i", "l", "q", "n", "ret"]); time.sleep(4)                              # « bilan »
capture("4-bilan")
# 0.5 : fenêtres. Mise en page de smokyos.c, pour un écran de 1920 × 1080 (U = 0,9)
U = 1080 / 1200
carnet_x, carnet_w = (1920 - 1080 * U) / 2, 1080 * U
calc_x, calc_y, calc_w = min(max(carnet_x + carnet_w - 300 * U, 20), 1920 - 440 * U - 20), 220 * U, 440 * U
def touche_calc(k):                             # centre de la touche n° k de la calculatrice
    bw = (calc_w - 78 * U) / 4
    return calc_x + 24 * U + (k % 4) * (bw + 10 * U) + bw / 2, calc_y + 214 * U + (k // 4) * 80 * U + 35 * U
mot("effacer"); taper(["ret"]); time.sleep(2)
mot("calculatrice"); taper(["ret"]); time.sleep(4)
mot("12*(3+4)-2,5"); taper(["ret"]); time.sleep(3)          # au clavier : = 81,5
capture("5-calculatrice")
for k in (4, 15, 12, 19):                                    # à la souris : 7 + 1 = 8
    cliquer(*touche_calc(k))
time.sleep(2)
capture("6-calculatrice-souris")
aller(calc_x + 150 * U, calc_y + 25 * U); bouton(True)       # on la prend par sa barre de titre…
souris(-400, 120); time.sleep(1.5); bouton(False); time.sleep(3)   # …et on la pose ailleurs
combo("alt", "tab"); time.sleep(3)                           # le carnet repasse devant
capture("7-deplacee-alt-tab")
combo("alt", "tab"); time.sleep(1); combo("esc"); time.sleep(2)   # calculatrice devant, puis fermée
mot("notes"); taper(["ret"]); time.sleep(3)
mot("bonjour"); taper(["ret"]); mot("ca marche, 2+2=4"); time.sleep(2)
capture("8-notes")
combo("esc"); time.sleep(2); mot("notes"); taper(["ret"]); time.sleep(3)   # fermées puis rouvertes
capture("9-notes-rouvertes")
combo("esc"); time.sleep(1); mot("horloge"); taper(["ret"]); time.sleep(3)
combo("spc"); time.sleep(3.2)                                # chrono lancé
capture("10-horloge")
qmp("quit")
qemu.wait(10)
print(open(f"{T}/serie.txt", errors="replace").read()[-300:])
