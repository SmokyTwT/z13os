#!/usr/bin/env python3
"""Emballe chrome-theme/src en CRX3 signé (chrome-theme/smoky-theme.crx) + updates.xml.

  python3 tools/pack-chrome-theme.py CLE.pem

La clé privée (RSA 2048, jamais dans le dépôt) fixe l'identifiant de l'extension. Avec la même
clé, augmenter « version » dans manifest.json suffit. Avec une nouvelle clé, l'identifiant change :
remplacer aussi l'identifiant dans la politique ExtensionInstallForcelist (Chrome retire l'ancien
thème tout seul).
"""
import hashlib
import io
import json
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "chrome-theme"
BASE = "https://raw.githubusercontent.com/SmokyTwT/z13os/main/chrome-theme"


def pb_bytes(field, data):          # champ protobuf « bytes » (type 2)
    key, out, n = (field << 3) | 2, b"", len(data)
    for v in (key, n):
        while True:
            b = v & 0x7F
            v >>= 7
            out += bytes([b | (0x80 if v else 0)])
            if not v:
                break
    return out + data


def main(key):
    pub = subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-outform", "DER"],
                         capture_output=True, check=True).stdout
    crx_id = hashlib.sha256(pub).digest()[:16]
    ext_id = "".join("abcdefghijklmnop"[int(c, 16)] for c in crx_id.hex())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "src").rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(ROOT / "src").as_posix())
    archive = buf.getvalue()
    signed = pb_bytes(1, crx_id)                                   # SignedData { crx_id }
    msg = b"CRX3 SignedData\x00" + struct.pack("<I", len(signed)) + signed + archive
    sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key], input=msg,
                         capture_output=True, check=True).stdout
    header = pb_bytes(2, pb_bytes(1, pub) + pb_bytes(2, sig)) + pb_bytes(10000, signed)
    (ROOT / "smoky-theme.crx").write_bytes(b"Cr24" + struct.pack("<II", 3, len(header)) + header + archive)
    version = json.loads((ROOT / "src/manifest.json").read_text())["version"]
    (ROOT / "updates.xml").write_text(
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>\n"
        f"  <app appid='{ext_id}'>\n"
        f"    <updatecheck codebase='{BASE}/smoky-theme.crx' version='{version}' />\n"
        "  </app>\n</gupdate>\n")
    print(ext_id)


if __name__ == "__main__":
    main(sys.argv[1])
