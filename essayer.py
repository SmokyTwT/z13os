#!/usr/bin/env python3
"""Braise — essai dans une machine virtuelle (QEMU + firmware UEFI OVMF), sans écran :
démarre Braise, prend des captures, tape des commandes comme sur un clavier AZERTY."""
import json, os, shutil, socket, subprocess, sys, time

ICI = os.path.dirname(os.path.abspath(__file__))
T = "/tmp/braise-essai"
shutil.rmtree(T, ignore_errors=True); os.makedirs(T)
shutil.copy("/usr/share/OVMF/OVMF_VARS_4M.fd", f"{T}/vars.fd")
qemu = subprocess.Popen([
    "qemu-system-x86_64", "-machine", "q35", "-m", "1024", "-display", "none", "-net", "none",
    "-drive", "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
    "-drive", f"if=pflash,format=raw,file={T}/vars.fd",
    "-drive", f"format=raw,snapshot=on,file={ICI}/construit/braise.img",   # copie jetable : l image reste intacte
    "-device", "virtio-vga", "-qmp", f"unix:{T}/qmp.sock,server,nowait", "-serial", f"file:{T}/serie.txt"])
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
    for t in touches:
        qmp("send-key", keys=[{"type": "qcode", "data": t}]); time.sleep(0.15)
attente = float(sys.argv[1]) if len(sys.argv) > 1 else 40
time.sleep(attente); capture("1-demarrage")
taper(["q", "i", "d", "e", "ret"]); time.sleep(6)             # « aide » sur un clavier AZERTY
taper(["semicolon", "e", "semicolon", "o", "i", "r", "e", "ret"]); time.sleep(6)   # « memoire »
capture("2-aide")
qmp("quit")
qemu.wait(10)
print(open(f"{T}/serie.txt", errors="replace").read()[-300:])
