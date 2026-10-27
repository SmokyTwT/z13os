#!/usr/bin/env python3
"""Smoky OS — donne automatiquement le style Smoky au logo de chaque appli.

Pour chaque appli installée (RPM, Flatpak, raccourci de jeu Steam…) dont le
logo n'a pas encore de version Smoky, ce script en fabrique une : le logo
d'origine en argent (contrastes conservés), posé sur le carré noir Smoky,
avec un halo et un trait néon à la couleur principale du logo d'origine.
Résultat : ~/.local/share/icons/Smoky-icons/apps/256/<nom>.png

Lancé à la connexion et dès qu'une appli est installée (smoky-autoicons.path).
"""
import colorsys
import configparser
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    sys.exit("python3-pillow manquant")

HOME = Path.home()
OUT_DIR = HOME / ".local/share/icons/Smoky-icons/apps/256"
SYSTEM_THEME = Path("/usr/share/icons/Smoky-icons")
APP_DIRS = [
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    HOME / ".local/share/flatpak/exports/share/applications",
    HOME / ".local/share/applications",
]
ICON_BASES = [
    HOME / ".local/share/icons",
    HOME / ".local/share/flatpak/exports/share/icons",
    Path("/var/lib/flatpak/exports/share/icons"),
    Path("/usr/share/icons"),
]
SIZES = ["512x512", "256x256", "scalable", "192x192", "128x128", "96x96", "64x64", "48x48"]
N = 256


# --- Recherche du logo d'origine -------------------------------------------------
def find_icon(name):
    if name.startswith("/"):
        return Path(name) if Path(name).is_file() else None
    for base in ICON_BASES:
        for size in SIZES:
            for ext in ("svg", "png"):
                p = base / "hicolor" / size / "apps" / f"{name}.{ext}"
                if p.is_file():
                    return p
    for ext in ("svg", "png", "xpm"):
        p = Path("/usr/share/pixmaps") / f"{name}.{ext}"
        if p.is_file():
            return p
    return None


def already_smoky(name):
    if name.startswith(("smokyos-", "smoky-")):       # nos logos faits main
        return True
    for d in ("apps/scalable", "apps/256"):
        for ext in ("svg", "png"):
            if (SYSTEM_THEME / d / f"{name}.{ext}").exists():
                return True
    return False


def load(path):
    if path.suffix == ".svg":
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            subprocess.run(["rsvg-convert", "-w", "192", "-h", "192", "-a", "-o", tmp.name, str(path)],
                           check=True, capture_output=True, timeout=20)
            return Image.open(tmp.name).convert("RGBA")
    return Image.open(path).convert("RGBA")


# --- Fabrication du logo Smoky ------------------------------------------------------
def accent_of(img):
    """Couleur principale du logo d'origine (pixels saturés), sinon argent."""
    small = img.resize((48, 48))
    r = g = b = w = 0.0
    for pr, pg, pb, pa in small.get_flattened_data():
        if pa < 128:
            continue
        h, s, v = colorsys.rgb_to_hsv(pr / 255, pg / 255, pb / 255)
        if s > 0.35 and v > 0.3:
            wt = s * v
            r, g, b, w = r + pr * wt, g + pg * wt, b + pb * wt, w + wt
    if w < 3:
        return (205, 205, 214)
    h, s, v = colorsys.rgb_to_hsv(r / w / 255, g / w / 255, b / w / 255)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, max(s, 0.65), max(v, 0.95))   # néon : couleur vive
    return (int(r2 * 255), int(g2 * 255), int(b2 * 255))


def remove_plate(img):
    """Si le logo est posé sur son propre fond (carré, rond, uni ou en dégradé),
    on retire ce fond pour ne garder que le motif : remplissage depuis les bords,
    qui suit les dégradés doucement (sinon : carré gris dans le carré noir)."""
    from collections import deque
    w, h = img.size
    px = img.load()
    inset = max(3, int(min(w, h) * 0.07))
    seeds = [(w // 2, inset), (w // 2, h - 1 - inset), (inset, h // 2), (w - 1 - inset, h // 2)]
    seeds = [p for p in seeds if px[p][3] > 220]
    if len(seeds) < 3:
        return img                                    # pas de fond plein autour du motif
    filled = bytearray(w * h)
    q = deque()
    for x, y in seeds:
        filled[y * w + x] = 1
        q.append((x, y, px[x, y]))
    seed_cols = [px[p] for p in seeds]
    while q:
        x, y, c = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not filled[ny * w + nx]:
                n = px[nx, ny]
                if n[3] > 200 and sum(abs(n[k] - c[k]) for k in range(3)) < 24 \
                        and min(sum(abs(n[k] - sc[k]) for k in range(3)) for sc in seed_cols) < 170:
                    filled[ny * w + nx] = 1
                    q.append((nx, ny, n))
    opaque = sum(1 for y in range(h) for x in range(w) if px[x, y][3] > 200)
    if sum(filled) < 0.25 * max(1, opaque):
        return img                                    # trop petit : ce n'est pas un fond
    mask = Image.frombytes("L", (w, h), bytes(v * 255 for v in filled))
    near = mask.filter(ImageFilter.MaxFilter(7)).load()
    for y in range(h):
        for x in range(w):
            if filled[y * w + x]:
                px[x, y] = px[x, y][:3] + (0,)
            elif near[x, y]:
                r, g, b, a = px[x, y]
                plate_like = min(sum(abs((r, g, b)[k] - sc[k]) for k in range(3)) for sc in seed_cols) < 90
                if a < 200 or plate_like:              # bord du fond, ombre, anticrénelage
                    px[x, y] = (r, g, b, 0)
    # bord extérieur du fond (liseré, ombre) : on enlève ce qui touche l'extérieur et n'est pas du motif
    edge = Image.new("L", (w, h), 0)
    ImageDraw.Draw(edge).rectangle([0, 0, w - 1, h - 1], outline=255, width=max(2, inset // 2))
    e = edge.load()
    for y in range(h):
        for x in range(w):
            if e[x, y]:
                px[x, y] = px[x, y][:3] + (0,)
    return img


def silver(img):
    """Version argentée : on étire la luminosité du logo vers 110–255."""
    bbox = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    img = remove_plate(img)
    bbox = img.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    img.thumbnail((118, 118), Image.LANCZOS)
    px = list(img.get_flattened_data())
    lums = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b, a in px if a > 40]
    lo, hi = (min(lums), max(lums)) if lums else (0, 255)
    span = max(30.0, hi - lo)
    out = []
    for r, g, b, a in px:
        t = ((0.3 * r + 0.59 * g + 0.11 * b) - lo) / span
        v = int(110 + 145 * max(0.0, min(1.0, t)) ** 0.85)
        out.append((v, v, min(255, v + 6), a))
    res = Image.new("RGBA", img.size)
    res.putdata(out)
    # léger dégradé vertical : plus lumineux en haut, comme les logos Smoky
    shade = Image.linear_gradient("L").resize(img.size).point(lambda x: 255 - x // 5)
    alpha = res.getchannel("A")
    res = Image.composite(res, Image.new("RGBA", img.size, (0, 0, 0, 0)), alpha)
    dark = Image.new("RGBA", img.size, (0, 0, 0, 255))
    res = Image.composite(res, Image.alpha_composite(dark, res), shade)
    res.putalpha(alpha)
    return res


def squircle_base(accent):
    base = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    grad = Image.linear_gradient("L").resize((N, N))
    top, bot = (42, 42, 47), (7, 7, 8)
    fill = Image.merge("RGB", [grad.point(lambda y, a=top[i], b=bot[i]: int(a + (b - a) * y / 255)) for i in range(3)])
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle([16, 16, 240, 240], radius=50, fill=255)
    shadow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    shadow.putalpha(mask.filter(ImageFilter.GaussianBlur(5)).point(lambda a: a * 100 // 255))
    base.alpha_composite(shadow, (0, 4))
    body = fill.convert("RGBA")
    body.putalpha(mask)
    base.alpha_composite(body)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([18, 18, 238, 238], radius=48, outline=(255, 255, 255, 42), width=3)
    # trait néon à la couleur de l'appli
    line = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(line).rounded_rectangle([86, 199, 170, 206], radius=4, fill=accent + (255,))
    glow = line.filter(ImageFilter.GaussianBlur(6))
    base.alpha_composite(glow)
    base.alpha_composite(line)
    return base


def smoky_icon(src):
    accent = accent_of(src)
    out = squircle_base(accent)
    logo = silver(src)
    x, y = (N - logo.width) // 2, 112 - logo.height // 2
    halo = Image.new("RGBA", (N, N), (255, 255, 255, 0))
    mask = Image.new("L", (N, N), 0)
    mask.paste(logo.getchannel("A"), (x, y))
    halo.putalpha(mask.filter(ImageFilter.GaussianBlur(7)).point(lambda a: a * 70 // 255))
    out.alpha_composite(halo)
    out.alpha_composite(logo, (x, y))
    return out


# --- Parcours des applis --------------------------------------------------------------
def desktop_icons():
    for d in APP_DIRS:
        if not d.is_dir():
            continue
        for f in d.glob("*.desktop"):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("NoDisplay", "false").lower() == "true" or not e.get("Icon"):
                continue
            yield e.get("Icon").strip()


def main():
    # Pas d'index.theme ici : celui du système (/usr/share/icons/Smoky-icons) déclare
    # déjà apps/256, et GTK cherche ce dossier dans ~/.local/share/icons aussi.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made = 0
    for name in sorted(set(desktop_icons())):
        if name.startswith("/") or already_smoky(name):
            continue
        dest = OUT_DIR / f"{name}.png"
        src = find_icon(name)
        if not src or (dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime):
            continue
        try:
            smoky_icon(load(src)).save(dest)
            made += 1
        except Exception as e:  # un logo illisible ne doit pas bloquer les autres
            print(f"{name} : {e}", file=sys.stderr)
    if made:
        os.utime(OUT_DIR.parent.parent)          # signale le changement aux applis
        # GNOME Shell recharge les logos quand le thème d'icônes change
        cur = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "icon-theme"],
                             capture_output=True, text=True).stdout.strip().strip("'")
        if cur == "Smoky-icons":
            subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", "WhiteSur"], check=False)
            subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", "Smoky-icons"], check=False)
    print(f"{made} logo(s) Smoky créé(s)")


if __name__ == "__main__":
    if len(sys.argv) == 3:            # test : smoky-autoicons.py entrée.png sortie.png
        smoky_icon(Image.open(sys.argv[1]).convert("RGBA")).save(sys.argv[2])
    else:
        main()
