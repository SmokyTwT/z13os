#!/usr/bin/env python3
"""Génère le thème de curseurs « Smoky » (format Xcursor) pour Smoky OS.

Pointeur : un point blanc lumineux, effet néon (halo doux en deux couches),
cerné d'un liseré sombre très fin pour rester visible sur les pages blanches.
Attente : une volute argentée qui tourne autour du point. Les autres curseurs (main, redimensionnement…)
sont hérités de WhiteSur-cursors (noir et blanc, assortis).
Usage : python3 make-cursors.py DOSSIER_DU_THEME [aperçu.png]
"""
import math
import os
import struct
import sys
from PIL import Image, ImageDraw, ImageFilter

SIZES = [24, 32, 48, 64, 96]   # tailles nominales (écran ×1 à ×3)
SS = 4                         # suréchantillonnage pour des bords lisses
OUT = sys.argv[1] if len(sys.argv) > 1 else "Smoky-cursors"


# --- Encodeur Xcursor ------------------------------------------------------------
def xcursor(frames):
    """frames : liste de (taille_nominale, image RGBA, xhot, yhot, délai_ms)."""
    header = 16
    toc = 12 * len(frames)
    pos = header + toc
    chunks, entries = [], []
    for nominal, img, xh, yh, delay in frames:
        w, h = img.size
        px = bytearray()
        for r, g, b, a in img.convert("RGBA").get_flattened_data():          # ARGB prémultiplié, petit-boutiste
            px += struct.pack("<I", (a << 24) | ((r * a // 255) << 16) | ((g * a // 255) << 8) | (b * a // 255))
        chunk = struct.pack("<9I", 36, 0xFFFD0002, nominal, 1, w, h, xh, yh, delay) + bytes(px)
        entries.append(struct.pack("<3I", 0xFFFD0002, nominal, pos))
        chunks.append(chunk)
        pos += len(chunk)
    return struct.pack("<4sIII", b"Xcur", header, 0x10000, len(frames)) + b"".join(entries) + b"".join(chunks)


# --- Dessins (repère 32×32, mis à l'échelle) ----------------------------------------
ARROW = [(3, 2), (3, 25), (8.6, 19.8), (12.4, 28.4), (16.4, 26.6), (12.7, 18.2), (20.2, 18.2)]


def canvas(n):
    return Image.new("RGBA", (n * SS, n * SS), (0, 0, 0, 0))


def glow(img, radius, alpha):
    """Halo blanc doux autour de la forme (comme les volutes du fond d'écran)."""
    a = img.split()[3].filter(ImageFilter.GaussianBlur(radius))
    halo = Image.new("RGBA", img.size, (255, 255, 255, 0))
    halo.putalpha(a.point(lambda v: int(v * alpha)))
    halo.alpha_composite(img)
    return halo


def arrow(n, offset=(0, 0)):
    s = n * SS / 32
    img = canvas(n)
    d = ImageDraw.Draw(img)
    pts = [((x + offset[0]) * s, (y + offset[1]) * s) for x, y in ARROW]
    d.polygon(pts, fill=(14, 14, 16, 255))
    d.line(pts + [pts[0]], fill=(236, 236, 242, 255), width=max(2, round(1.7 * s)), joint="curve")
    # reflet argenté sur le bord gauche
    d.line([pts[0], pts[1]], fill=(255, 255, 255, 255), width=max(2, round(1.9 * s)))
    return glow(img, 2.2 * s, 0.45)


def dot(n, r=3.3, ring=False):
    """Point blanc néon : cœur blanc, liseré sombre fin, double halo lumineux."""
    s = n * SS / 32
    c = 16 * s
    core = canvas(n)
    d = ImageDraw.Draw(core)
    if ring:   # survol d'un lien : anneau lumineux autour du point
        rr = (r + 4.2) * s
        d.ellipse([c - rr, c - rr, c + rr, c + rr], outline=(245, 245, 250, 230), width=max(2, round(1.3 * s)))
    edge = (r + 0.7) * s
    d.ellipse([c - edge, c - edge, c + edge, c + edge], fill=(10, 10, 12, 150))
    rc = r * s
    d.ellipse([c - rc, c - rc, c + rc, c + rc], fill=(255, 255, 255, 255))
    # néon : halo serré très lumineux + halo large plus doux
    a = core.split()[3]
    out = Image.new("RGBA", core.size, (255, 255, 255, 0))
    for radius, alpha in ((4.2 * s, 0.5), (2.0 * s, 0.9)):
        h = Image.new("RGBA", core.size, (255, 255, 255, 0))
        h.putalpha(a.filter(ImageFilter.GaussianBlur(radius)).point(lambda v, al=alpha: int(min(255, v * al * 1.6))))
        out.alpha_composite(h)
    out.alpha_composite(core)
    return out


def swirl(n, phase, cx=16, cy=16, r=9.5, width=3.2, small=False):
    """Anneau de fumée : arc argenté à traîne qui s'estompe, plus un halo."""
    s = n * SS / 32
    img = canvas(n)
    d = ImageDraw.Draw(img)
    steps = 48
    for i in range(steps):
        t = i / steps
        a0 = phase + t * 300
        alpha = int(255 * t ** 1.6)
        wid = max(1, round((width * (0.45 + 0.55 * t)) * s))
        # légère ondulation du rayon : effet volute
        rr = (r + 0.9 * math.sin(t * math.pi * 3 + math.radians(phase))) * s
        box = [cx * s - rr, cy * s - rr, cx * s + rr, cy * s + rr]
        d.arc(box, a0, a0 + 300 / steps + 2, fill=(240, 240, 246, alpha), width=wid)
    # tête lumineuse de la volute
    head = math.radians(phase + 300)
    hx, hy = cx * s + r * s * math.cos(head), cy * s + r * s * math.sin(head)
    hr = width * 0.75 * s
    d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255, 255))
    return glow(img, (1.6 if small else 2.4) * s, 0.6)


def down(img, n):
    return img.resize((n, n), Image.LANCZOS)


def write(name, frames, aliases=()):
    path = os.path.join(OUT, "cursors", name)
    with open(path, "wb") as f:
        f.write(xcursor(frames))
    for al in aliases:
        link = os.path.join(OUT, "cursors", al)
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(name, link)


def hot(n, x, y):
    return round(x * n / 32), round(y * n / 32)


os.makedirs(os.path.join(OUT, "cursors"), exist_ok=True)

# Pointeur : point blanc néon (point chaud au centre)
frames = []
for n in SIZES:
    xh, yh = hot(n, 16, 16)
    frames.append((n, down(dot(n), n), xh, yh, 0))
write("left_ptr", frames, ["default", "arrow", "top_left_arrow", "left-arrow"])

# Lien / bouton cliquable : point néon entouré d'un anneau
frames = []
for n in SIZES:
    xh, yh = hot(n, 16, 16)
    frames.append((n, down(dot(n, r=3.0, ring=True), n), xh, yh, 0))
write("hand2", frames, ["pointer", "hand1", "hand", "pointing_hand",
                        "9d800788f1b08800ae810202380a0822", "e29285e634086352946a0e7090d73106"])

# Attente : volute qui tourne (24 images, 40 ms → 1 tour / ~1 s)
NF = 24
frames = []
for n in SIZES:
    xh, yh = hot(n, 16, 16)
    for k in range(NF):
        frames.append((n, down(swirl(n, k * 360 / NF), n), xh, yh, 40))
write("watch", frames, ["wait", "clock"])

# Ouverture d'une appli : le point néon, entouré d'une volute qui tourne
frames = []
for n in SIZES:
    xh, yh = hot(n, 16, 16)
    for k in range(NF):
        img = dot(n)
        img.alpha_composite(swirl(n, k * 360 / NF, r=9.5, width=2.2, small=True))
        frames.append((n, down(img, n), xh, yh, 40))
write("left_ptr_watch", frames, ["progress", "half-busy",
                                 "00000000000000020006000e7e9ffc3f", "08e8e1c95fe2fc01f976f1e063a24ccd",
                                 "3ecb610c1bf2410f44200f48c40d3599"])

# Saisie de texte : barre argentée lumineuse
frames = []
for n in SIZES:
    s = n * SS / 32
    img = canvas(n)
    d = ImageDraw.Draw(img)
    w = max(2, round(1.8 * s))
    d.line([(16 * s, 7 * s), (16 * s, 25 * s)], fill=(14, 14, 16, 255), width=w + round(1.6 * s))
    d.line([(16 * s, 7 * s), (16 * s, 25 * s)], fill=(240, 240, 246, 255), width=w)
    for y in (7, 25):
        d.line([(12.5 * s, y * s), (19.5 * s, y * s)], fill=(14, 14, 16, 255), width=w + round(1.6 * s))
        d.line([(12.5 * s, y * s), (19.5 * s, y * s)], fill=(240, 240, 246, 255), width=w)
    xh, yh = hot(n, 16, 16)
    frames.append((n, down(glow(img, 2 * s, 0.5), n), xh, yh, 0))
write("xterm", frames, ["text", "ibeam"])

with open(os.path.join(OUT, "index.theme"), "w") as f:
    f.write("[Icon Theme]\nName=Smoky-cursors\nComment=Curseurs de Smoky OS : point blanc néon, attente en volute de fumée\nInherits=WhiteSur-cursors\n")

# Aperçu (planche) pour contrôle visuel, si demandé
if len(sys.argv) < 3:
    sys.exit(0)
sheet = Image.new("RGBA", (64 * 5 + 60, 84), (17, 17, 17, 255))
for i, img in enumerate([dot(64), dot(64, r=3.0, ring=True), swirl(64, 0)]):
    sheet.alpha_composite(down(img, 64), (10 + 74 * i, 10))
pw = dot(64)
pw.alpha_composite(swirl(64, 60, r=9.5, width=2.2, small=True))
sheet.alpha_composite(down(pw, 64), (232, 10))
white = Image.new("RGBA", (64, 64), (250, 250, 250, 255))   # sur une page blanche
white.alpha_composite(down(dot(64), 64))
sheet.alpha_composite(white, (306, 10))
sheet.save(sys.argv[2])
