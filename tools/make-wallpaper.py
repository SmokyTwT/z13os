#!/usr/bin/env python3
"""Génère les fonds d'écran de Smoky OS : le mot « Smoky » qui part en fumée.

Le bas des lettres reste net ; en montant, elles se déforment (bruit fractal
« domain warping ») et laissent échapper des volutes. Noir, gris, blanc.
Usage : python3 make-wallpaper.py DOSSIER [police.otf]
"""
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1600, 1000           # calcul à 62,5 %, agrandi ensuite (la fumée est floue)
OUT_W, OUT_H = 2560, 1600
FONT = sys.argv[2] if len(sys.argv) > 2 else "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
rng = np.random.default_rng(2207)


def noise(sx, sy):
    gw, gh = max(2, int(W / sx)), max(2, int(H / sy))
    g = (rng.random((gh, gw)) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(g).resize((W, H), Image.BICUBIC), np.float32) / 255


def fbm(sx, sy, octaves=5):
    tot, amp, norm = 0.0, 1.0, 0.0
    for i in range(octaves):
        tot = tot + amp * noise(sx / 2 ** i, sy / 2 ** i)
        norm += amp
        amp *= 0.5
    return tot / norm


def sample(f, xs, ys):
    xs = np.clip(xs, 0, W - 1.001)
    ys = np.clip(ys, 0, H - 1.001)
    x0, y0 = xs.astype(int), ys.astype(int)
    fx, fy = xs - x0, ys - y0
    a = f[y0, x0] * (1 - fx) + f[y0, x0 + 1] * fx
    b = f[y0 + 1, x0] * (1 - fx) + f[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def blur(f, r):
    if r <= 0:
        return f
    img = Image.fromarray((np.clip(f, 0, 1) * 255).astype(np.uint8))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(r)), np.float32) / 255


# --- Le mot « Smoky » ---------------------------------------------------------
font = ImageFont.truetype(FONT, 300)
canvas = Image.new("L", (W, H), 0)
d = ImageDraw.Draw(canvas)
x0, y0, x1, y1 = d.textbbox((0, 0), "Smoky", font=font)
tx, ty = (W - (x1 - x0)) // 2 - x0, int(H * 0.56) - (y1 - y0) // 2 - y0
d.text((tx, ty), "Smoky", font=font, fill=255)
mask = np.asarray(canvas, np.float32) / 255
top, bottom = ty + y0, ty + y1                      # haut et bas des lettres

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
wx, wy = fbm(220, 300) - 0.5, fbm(220, 300) - 0.5
cx, cy = fbm(70, 140) - 0.5, fbm(70, 140) - 0.5    # petites volutes

# Hauteur relative dans les lettres : 0 en bas, 1 en haut, >1 au-dessus
h = np.clip((bottom - yy) / (bottom - top), 0, 3)

# Lettres : nettes en bas, de plus en plus ondulées vers le haut
amp = 0.6 + 7 * np.clip(h, 0, 1) ** 3
letters = sample(mask, xx + wx * amp + cx * amp * 0.6, yy + wy * amp * 0.5)
fade = 1 - 0.32 * np.clip(h - 0.55, 0, 1) ** 1.2 * (0.4 + 1.2 * fbm(30, 50))
letters = np.clip(letters * fade, 0, 1)

# Volutes : la fumée s'élève par petits pas depuis le haut des lettres,
# portée par un courant qui tourne lentement (advection), et s'estompe.
wx2, wy2 = fbm(160, 240) - 0.5, fbm(160, 240) - 0.5
edge = np.clip(mask - sample(mask, xx, yy - 6), 0, 1)        # bords supérieurs des lettres
source = blur(edge, 3.0) * (0.35 + 0.9 * fbm(25, 25))
smoke = np.zeros((H, W), np.float32)
puff = source.copy()
steps = 120
for i in range(steps):
    k = i / steps
    ang = k * 2.4
    ux = (wx * np.cos(ang) + wx2 * np.sin(ang)) * (4 + 13 * k)
    uy = (wy * np.cos(ang) + wy2 * np.sin(ang)) * (2 + 6 * k)
    puff = sample(puff, xx + ux, yy + 3 + uy)            # monte de 3 px par pas
    puff = blur(puff, 0.7 + 0.6 * k) * 0.993
    smoke += puff * min(1.0, k * 5) * (1 - k) ** 1.2   # somme : pas de rayures
smoke /= np.percentile(smoke, 99.7) + 1e-6
fibres = 1 - np.abs(fbm(45, 160, 6) * 2 - 1)             # filaments verticaux
smoke = smoke * (0.45 + 0.9 * fibres ** 1.6)
smoke = 0.62 * (1 - np.exp(-1.6 * smoke))          # douce, jamais blanche pure

smoke = smoke * (1 - mask)                          # la fumée ne recouvre pas les lettres
ink = np.clip(1 - (1 - letters) * (1 - smoke), 0, 1)   # fusion « écran »
halo = blur(mask, 60) * 0.25                         # lueur douce derrière


def render(bg_a, bg_b, ink_rgb, glow_rgb, path):
    t = (yy / H)[..., None]
    bg = np.array(bg_a) * (1 - t) + np.array(bg_b) * t
    g = halo[..., None]
    bg = bg * (1 - g) + np.array(glow_rgb) * g
    a = ink[..., None]
    rgb = bg * (1 - a) + np.array(ink_rgb) * a
    rgb += (rng.random((H, W, 1)) - 0.5) * 2.2         # grain anti-bandes
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    img.resize((OUT_W, OUT_H), Image.LANCZOS).save(path, optimize=True)


out = sys.argv[1] if len(sys.argv) > 1 else "."
render((22, 22, 25), (4, 4, 5), (242, 242, 245), (70, 70, 76), f"{out}/smokyos-dark.png")
render((236, 236, 238), (208, 208, 212), (28, 28, 32), (255, 255, 255), f"{out}/smokyos-light.png")
