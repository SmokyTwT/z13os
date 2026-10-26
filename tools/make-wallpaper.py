#!/usr/bin/env python3
"""Génère les fonds d'écran « fumée » de Smoky OS (clair et sombre).

Bruit fractal + déformation (domain warping) étiré verticalement pour
imiter des volutes qui montent. Usage : python3 make-wallpaper.py DOSSIER
"""
import sys
import numpy as np
from PIL import Image

W, H = 1280, 800          # calcul en demi-résolution, agrandi ensuite (fumée = flou)
OUT_W, OUT_H = 2560, 1600
rng = np.random.default_rng(1309)


def noise(scale_x, scale_y):
    """Bruit lisse : grille aléatoire agrandie en bicubique."""
    gw, gh = max(2, int(W / scale_x)), max(2, int(H / scale_y))
    g = (rng.random((gh, gw)) * 255).astype(np.uint8)
    img = Image.fromarray(g).resize((W, H), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32) / 255.0


def fbm(scale_x, scale_y, octaves=5):
    total, amp, norm = 0.0, 1.0, 0.0
    for i in range(octaves):
        total = total + amp * noise(scale_x / 2 ** i, scale_y / 2 ** i)
        norm += amp
        amp *= 0.5
    return total / norm


def sample(field, xs, ys):
    """Lecture bilinéaire de field aux coordonnées (xs, ys)."""
    xs = np.clip(xs, 0, W - 1.001)
    ys = np.clip(ys, 0, H - 1.001)
    x0, y0 = xs.astype(int), ys.astype(int)
    fx, fy = xs - x0, ys - y0
    a = field[y0, x0] * (1 - fx) + field[y0, x0 + 1] * fx
    b = field[y0 + 1, x0] * (1 - fx) + field[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

# Déformation en deux passes : volutes qui s'enroulent
wx, wy = fbm(260, 520), fbm(260, 520)
x1, y1 = xx + (wx - 0.5) * 260, yy + (wy - 0.5) * 140
wx2, wy2 = sample(fbm(160, 320), x1, y1), sample(fbm(160, 320), x1, y1)
x2, y2 = x1 + (wx2 - 0.5) * 180, y1 + (wy2 - 0.5) * 90

# Filaments : bruit étiré verticalement, crêtes accentuées
base = sample(fbm(90, 360, 6), x2, y2)
ridges = 1.0 - np.abs(base * 2.0 - 1.0)
density = np.clip((ridges - 0.62) * 2.6, 0, 1) ** 1.8

# Deux colonnes de fumée qui montent en ondulant vers la droite
def column(cx, slope, width, strength):
    t = 1.0 - yy / H                                 # 0 en bas, 1 en haut
    center = cx + slope * t * W + np.sin(t * 5.0 + cx / 97) * 60
    d = (xx - center) / (width * (0.6 + t))          # s'élargit en montant
    rise = np.clip(t * 2.2, 0, 1) * np.clip((1.05 - t) * 1.6, 0, 1)   # naît en bas, s'évanouit en haut
    return strength * np.exp(-d * d) * rise

band = np.maximum(column(0.32 * W, 0.26, 120, 1.0), column(0.72 * W, 0.10, 90, 0.55))
smoke = 1.0 - np.exp(-(density * band * 2.2 + band * 0.12))   # saturation douce


def render(bg_a, bg_b, smoke_rgb, alpha, path):
    t = ((xx / W) * 0.6 + (1 - yy / H) * 0.4)[..., None]
    bg = np.array(bg_a) * (1 - t) + np.array(bg_b) * t
    s = (smoke * alpha)[..., None]
    rgb = bg * (1 - s) + np.array(smoke_rgb) * s
    grain = (rng.random((H, W, 1)) - 0.5) * 2.0       # léger grain anti-bandes
    img = np.clip(rgb + grain, 0, 255).astype(np.uint8)
    Image.fromarray(img).resize((OUT_W, OUT_H), Image.LANCZOS).save(path, optimize=True)


out = sys.argv[1] if len(sys.argv) > 1 else "."
render((4, 4, 5), (26, 26, 29), (236, 236, 240), 0.95, f"{out}/smokyos-dark.png")
render((246, 246, 247), (214, 214, 218), (40, 40, 46), 0.62, f"{out}/smokyos-light.png")
