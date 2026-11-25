#!/usr/bin/env python3
"""Smoky OS 100 % maison — essai dans une machine virtuelle (QEMU + firmware UEFI OVMF), sans écran :
démarre l'OS, prend des captures, tape des commandes comme sur un clavier AZERTY."""
import json, os, shutil, socket, subprocess, sys, time
BRANCHEMENT = "--branchement" in sys.argv          # clavier branché seulement après le démarrage
sys.argv = [a for a in sys.argv if a != "--branchement"]

ICI = os.path.dirname(os.path.abspath(__file__))
T = "/tmp/smokyos-essai"
shutil.rmtree(T, ignore_errors=True); os.makedirs(T)
shutil.copy("/usr/share/OVMF/OVMF_VARS_4M.fd", f"{T}/vars.fd")
qemu = subprocess.Popen([
    # sans contrôleur PS/2 (i8042=off) : comme un PC récent, seul le clavier USB existe
    "qemu-system-x86_64", "-machine", "q35,i8042=off", "-m", "1024", "-display", "none", "-net", "none",
    "-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
    "-drive", f"if=pflash,format=raw,file={T}/vars.fd",
    # démarrage depuis une clé USB virtuelle (copie jetable : l'image reste intacte)
    "-device", "qemu-xhci", "-drive", f"if=none,id=cle,format=raw,snapshot=on,file={ICI}/construit/smokyos.img",
    "-device", "usb-storage,drive=cle", *([] if BRANCHEMENT else ["-device", "usb-kbd,id=clavier-usb"]),
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
attente = float(sys.argv[1]) if len(sys.argv) > 1 else 40
time.sleep(attente); capture("1-demarrage")
if BRANCHEMENT:                                  # branché, débranché, rebranché
    print(qmp("device_add", driver="usb-kbd", id="clavier-usb"))
    time.sleep(3)
    print(qmp("device_del", id="clavier-usb"))
    time.sleep(3)
    print(qmp("device_add", driver="usb-kbd", id="clavier-usb"))
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
qmp("quit")
qemu.wait(10)
print(open(f"{T}/serie.txt", errors="replace").read()[-300:])
