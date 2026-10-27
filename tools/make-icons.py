#!/usr/bin/env python3
"""Génère les icônes « Smoky » des applis du dock (SVG 64×64).

Même style pour toutes : carré arrondi noir dégradé, liseré argenté, motif
argenté lumineux (halo flou + dégradé blanc → argent) et un petit trait néon
à la couleur de la marque. Ce sont des évocations stylisées, pas les logos
officiels. Usage : python3 make-icons.py DOSSIER
"""
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
FONT = "Inter, Adwaita Sans, Helvetica Neue, Arial, sans-serif"


def icon(name, glyph, accent, file=None):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2a2a2f"/><stop offset="1" stop-color="#070708"/>
    </linearGradient>
    <linearGradient id="ink" gradientUnits="userSpaceOnUse" x1="0" y1="14" x2="0" y2="46">
      <stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#b4b4be"/>
    </linearGradient>
    <radialGradient id="glow" cx=".5" cy=".45" r=".55">
      <stop offset="0" stop-color="#ffffff" stop-opacity=".18"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </radialGradient>
    <filter id="blur" filterUnits="userSpaceOnUse" x="0" y="0" width="64" height="64"><feGaussianBlur stdDeviation="1.5"/></filter>
    <filter id="sh" filterUnits="userSpaceOnUse" x="0" y="0" width="64" height="64"><feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity=".4"/></filter>
    <g id="glyph">{glyph}</g>
  </defs>
  <rect x="4" y="4" width="56" height="56" rx="12.5" fill="url(#bg)" filter="url(#sh)"/>
  <rect x="4" y="4" width="56" height="56" rx="12.5" fill="url(#glow)"/>
  <rect x="4.5" y="4.5" width="55" height="55" rx="12" fill="none" stroke="#fff" stroke-opacity=".16"/>
  <rect x="20" y="50" width="24" height="2.2" rx="1.1" fill="{accent}" filter="url(#blur)" opacity=".9"/>
  <rect x="22" y="50.4" width="20" height="1.4" rx=".7" fill="{accent}"/>
  <g filter="url(#blur)" opacity=".4"><use href="#glyph"/></g>
  <use href="#glyph"/>
</svg>
'''
    with open(os.path.join(OUT, file or f"smokyos-{name}.svg"), "w") as f:
        f.write(svg)


S = 'stroke="url(#ink)" fill="none" stroke-linecap="round" stroke-linejoin="round"'
F = 'fill="url(#ink)"'
TXT = f'text-anchor="middle" font-family="{FONT}" font-weight="800" fill="url(#ink)"'

icons = {
    # Chrome : anneau, pastille centrale et trois branches
    "chrome": ('<circle cx="32" cy="29" r="13.5" ' + S + ' stroke-width="3"/>'
               '<circle cx="32" cy="29" r="5.2" ' + F + '/>'
               '<path d="M32 23.8 H44.6 M27.5 31.6 L21.2 20.7 M36.5 31.6 L30.2 42.5" ' + S + ' stroke-width="2.6"/>', "#34a853"),
    # Netflix : N en trois rubans
    "netflix": ('<path d="M23 15 h6 v29 h-6 z M35 15 h6 v29 h-6 z" ' + F + '/>'
                '<path d="M23 15 h6 l12 29 h-6 z" ' + F + ' opacity=".8"/>', "#e50914"),
    # Disney+ : « D+ » arrondi avec un arc
    "disney": (f'<text x="29" y="38" {TXT} font-size="22">D</text>'
               f'<text x="42" y="31" {TXT} font-size="14">+</text>'
               '<path d="M14 30 C 20 14, 44 12, 50 24" ' + S + ' stroke-width="1.6" opacity=".8"/>', "#2f6bff"),
    # Prime Video : « prime » et sourire
    "prime": (f'<text x="32" y="31" {TXT} font-size="13.5" letter-spacing="-.3">prime</text>'
              '<path d="M18 36 C 26 42, 38 42, 46 35 M42.5 33.8 L46.5 35 L45 38.8" ' + S + ' stroke-width="2"/>', "#00a8e1"),
    # Spotify : disque argenté et trois ondes
    "spotify": ('<circle cx="32" cy="29" r="14" ' + F + '/>'
                '<path d="M22.5 25 C 28 23, 36 23.5, 41.5 26.5 M23.5 30 C 28.5 28.5, 35 29, 39.8 31.6 M24.5 34.8 C 28.7 33.8, 33.5 34.2, 37.5 36.2" '
                'stroke="#111" fill="none" stroke-width="2.4" stroke-linecap="round"/>', "#1db954"),
    # Google Drive : triangle en trois bandes
    "drive": ('<path d="M27 16 h10 l11 19 l-5 8.5 z" ' + F + ' opacity=".95"/>'
              '<path d="M27 16 l-11 19 l5 8.5 l11 -19 z" ' + F + ' opacity=".75"/>'
              '<path d="M21 43.5 h22 l5 -8.5 h-22 z" ' + F + ' opacity=".55"/>', "#fbbc04"),
    # Claude : soleil à rayons
    "claude": ("".join(
        f'<path d="M32 29 L{32 + 15 * c:.2f} {29 + 15 * s:.2f}" ' + S + f' stroke-width="{2.8 if i % 2 == 0 else 2}"/>'
        for i, (c, s) in enumerate(
            [(__import__("math").cos(a), __import__("math").sin(a))
             for a in [k * 3.14159265 / 6 + 0.2 for k in range(12)]]))
        + '<circle cx="32" cy="29" r="3.2" ' + F + '/>', "#d97757"),
    # Fichiers : dossier
    "files": ('<path d="M15 21 a3 3 0 0 1 3 -3 h8.5 l3.5 4 h16 a3 3 0 0 1 3 3 v15 a3 3 0 0 1 -3 3 h-28 a3 3 0 0 1 -3 -3 z" ' + F + '/>'
              '<path d="M15 26 h34" stroke="#111" stroke-width="1.6" opacity=".55"/>', "#c9c9d2"),
    # Terminal (Claude Code) : invite de commande et étincelle
    "terminal": ('<path d="M17 21 l9 8 l-9 8" ' + S + ' stroke-width="3.4"/>'
                 '<path d="M30 39 h14" ' + S + ' stroke-width="3.4"/>'
                 '<path d="M43 15 l1.4 3.6 l3.6 1.4 l-3.6 1.4 l-1.4 3.6 l-1.4 -3.6 l-3.6 -1.4 l3.6 -1.4 z" ' + F + '/>', "#ffffff"),
    # Paramètres : roue crantée
    "settings": ('<path d="M32 15.5 l3 0.4 l1 4.2 l3.4 1.6 l3.8 -2.1 l2.2 2.2 l-2.1 3.8 l1.6 3.4 l4.2 1 l0.4 3 l-0.4 3 l-4.2 1 l-1.6 3.4 l2.1 3.8 l-2.2 2.2 l-3.8 -2.1 l-3.4 1.6 l-1 4.2 l-3 0.4 l-3 -0.4 l-1 -4.2 l-3.4 -1.6 l-3.8 2.1 l-2.2 -2.2 l2.1 -3.8 l-1.6 -3.4 l-4.2 -1 l-0.4 -3 l0.4 -3 l4.2 -1 l1.6 -3.4 l-2.1 -3.8 l2.2 -2.2 l3.8 2.1 l3.4 -1.6 l1 -4.2 z" '
                 'transform="translate(0 -3)" ' + F + '/>'
                 '<circle cx="32" cy="29" r="5" fill="#141416"/>', "#c9c9d2"),
}

# Icônes déjà propres à Smoky OS (TF1+, M6+, Moodle, Smoky Notes)
icons["tf1"] = (f'<text x="32" y="36" {TXT} font-size="18" letter-spacing="-.5">TF1+</text>', "#3b82ff")
icons["m6"] = (f'<text x="32" y="36" {TXT} font-size="20" letter-spacing="-.5">M6+</text>', "#ff4d6d")
icons["moodle"] = ('<path d="M21 15 L32 9.5 L43 15 L32 20.5 Z" ' + F + '/>'
                   '<path d="M40.5 16.3 v6" ' + S + ' stroke-width="1.6"/>'
                   f'<text x="32" y="43" {TXT} font-size="30">m</text>', "#ff9a2e")
icons["notes"] = ('<path d="M14 42 C 20 28, 24 28, 26 36 S 32 44, 36 34 S 42 20, 46 24 C 50 27, 47 32, 44 30 C 41 28, 44 22, 49 18" ' + S + ' stroke-width="2.8"/>'
                  '<path d="M49 18 C 51 14, 48 11, 51 8" ' + S + ' stroke-width="1.6" opacity=".5"/>', "#ffffff")

# --- Autres applis du système (grille des applications) -----------------------------
D = 'fill="#141416"'   # « trou » sombre dans un motif plein
icons.update({
    "steam": ('<circle cx="32" cy="29" r="14" ' + S + ' stroke-width="2.8"/>'
              '<circle cx="37" cy="24.5" r="4.6" ' + S + ' stroke-width="2.4"/>'
              '<circle cx="25" cy="35" r="3.3" ' + F + '/><path d="M25 35 L33.6 27.6" ' + S + ' stroke-width="2.6"/>', "#66c0f4"),
    "software": ('<path d="M18 24 h28 l-2.5 19 a2 2 0 0 1 -2 1.7 h-19 a2 2 0 0 1 -2 -1.7 z" ' + F + '/>'
                 '<path d="M25 24 v-3 a7 7 0 0 1 14 0 v3" ' + S + ' stroke-width="2.6"/>', "#c9c9d2"),
    "texteditor": ('<path d="M19 13 h18 l8 8 v24 a2 2 0 0 1 -2 2 h-24 a2 2 0 0 1 -2 -2 v-30 a2 2 0 0 1 2 -2 z" ' + F + '/>'
                   '<path d="M23 25 h17 M23 30.5 h17 M23 36 h11" stroke="#141416" stroke-width="2" stroke-linecap="round"/>', "#c9c9d2"),
    "calculator": ('<rect x="19" y="13" width="26" height="33" rx="4" ' + F + '/>'
                   '<rect x="23" y="17" width="18" height="7" rx="1.5" ' + D + '/>'
                   + "".join(f'<circle cx="{x}" cy="{y}" r="2.2" {D}/>' for x in (26, 32, 38) for y in (30, 36.5, 42)), "#ff9a2e"),
    "calendar": ('<rect x="16" y="16" width="32" height="30" rx="4" ' + F + '/>'
                 '<rect x="16" y="16" width="32" height="8" rx="4" fill="#9a9aa4"/>'
                 '<path d="M23 13 v6 M41 13 v6" ' + S + ' stroke-width="2.6"/>'
                 + f'<text x="32" y="42" text-anchor="middle" font-family="{FONT}" font-weight="800" font-size="15" fill="#141416">27</text>', "#ff4d6d"),
    "clocks": ('<circle cx="32" cy="29" r="14" ' + S + ' stroke-width="2.8"/>'
               '<path d="M32 20 v9.5 l6 4" ' + S + ' stroke-width="2.6"/>', "#c9c9d2"),
    "weather": ('<circle cx="38" cy="22" r="6" ' + S + ' stroke-width="2.4"/>'
                '<path d="M20 41 a6 6 0 0 1 0 -12 a8.5 8.5 0 0 1 16.5 -1.5 a6.8 6.8 0 1 1 1.5 13.5 z" ' + F + '/>', "#ffd23a"),
    "maps": ('<path d="M16 19 l10 -4 l12 4 l10 -4 v26 l-10 4 l-12 -4 l-10 4 z" ' + F + ' opacity=".55"/>'
             '<path d="M32 15 a7 7 0 0 1 7 7 c0 6 -7 13 -7 13 s-7 -7 -7 -13 a7 7 0 0 1 7 -7 z" ' + F + '/>'
             '<circle cx="32" cy="22" r="2.6" ' + D + '/>', "#34a853"),
    "contacts": ('<circle cx="32" cy="22" r="7" ' + F + '/>'
                 '<path d="M18 44 a14 12 0 0 1 28 0 z" ' + F + '/>', "#c9c9d2"),
    "characters": (f'<text x="32" y="40" text-anchor="middle" font-family="{FONT}" font-weight="700" font-size="28" fill="url(#ink)">Ω</text>', "#c9c9d2"),
    "images": ('<rect x="15" y="15" width="34" height="28" rx="4" ' + S + ' stroke-width="2.6"/>'
               '<path d="M18 40 l9 -10 l6 6 l4 -4 l9 8 z" ' + F + '/>'
               '<circle cx="39" cy="22" r="3" ' + F + '/>', "#3b82ff"),
    "documents": ('<path d="M19 13 h18 l8 8 v24 a2 2 0 0 1 -2 2 h-24 a2 2 0 0 1 -2 -2 v-30 a2 2 0 0 1 2 -2 z" ' + F + '/>'
                  '<path d="M37 13 v8 h8" fill="#9a9aa4"/>'
                  f'<text x="31" y="40" text-anchor="middle" font-family="{FONT}" font-weight="800" font-size="10" fill="#141416">PDF</text>', "#ff4d6d"),
    "camera": ('<path d="M15 22 a3 3 0 0 1 3 -3 h6 l3 -4 h10 l3 4 h6 a3 3 0 0 1 3 3 v18 a3 3 0 0 1 -3 3 h-28 a3 3 0 0 1 -3 -3 z" ' + F + '/>'
               '<circle cx="32" cy="30.5" r="7.5" ' + D + '/><circle cx="32" cy="30.5" r="4.5" ' + F + '/>', "#c9c9d2"),
    "disk-usage": ('<circle cx="32" cy="29" r="14" ' + F + ' opacity=".5"/>'
                   '<path d="M32 29 v-14 a14 14 0 0 1 13.3 18.3 z" ' + F + '/>', "#2fd4a8"),
    "logs": ('<rect x="16" y="14" width="32" height="31" rx="4" ' + S + ' stroke-width="2.6"/>'
             '<path d="M22 22 h20 M22 28 h20 M22 34 h14 M22 40 h9" ' + S + ' stroke-width="2.2"/>', "#c9c9d2"),
    "monitor": ('<rect x="14" y="15" width="36" height="28" rx="4" ' + S + ' stroke-width="2.6"/>'
                '<path d="M18 32 h6 l3 -8 l5 14 l4 -10 l2 4 h8" ' + S + ' stroke-width="2.4"/>', "#2fd4a8"),
    "disks": ('<ellipse cx="32" cy="20" rx="14" ry="5" ' + F + '/>'
              '<path d="M18 20 v18 a14 5 0 0 0 28 0 v-18" ' + S + ' stroke-width="2.6"/>'
              '<path d="M18 29 a14 5 0 0 0 28 0" ' + S + ' stroke-width="2"/>', "#c9c9d2"),
    "extensions": ('<path d="M20 22 h7 a4 4 0 1 1 8 0 h7 v7 a4 4 0 1 1 0 8 v7 h-22 z" ' + F + '/>', "#3b82ff"),
    "firefox": ('<circle cx="32" cy="29" r="14" ' + S + ' stroke-width="2.8"/>'
                '<path d="M22 22 c2 -6 10 -9 16 -5 c-5 -1 -9 2 -9 6 c4 -2 9 0 10 5 c1 6 -5 10 -10 9 c5 -2 6 -7 3 -9" ' + S + ' stroke-width="2.4"/>', "#ff7139"),
    "tour": ('<circle cx="32" cy="29" r="14" ' + S + ' stroke-width="2.8"/>'
             '<path d="M32 18 l4 11 l-4 11 l-4 -11 z" ' + F + '/>', "#c9c9d2"),
    "help": ('<circle cx="32" cy="29" r="14" ' + S + ' stroke-width="2.8"/>'
             f'<text x="32" y="36" text-anchor="middle" font-family="{FONT}" font-weight="800" font-size="19" fill="url(#ink)">?</text>', "#3b82ff"),
    "rog": (f'<text x="32" y="35" text-anchor="middle" font-family="{FONT}" font-weight="800" font-size="16" fill="url(#ink)" letter-spacing="1">ROG</text>'
            '<path d="M17 39 h30" ' + S + ' stroke-width="1.4" opacity=".6"/>', "#ff2a3a"),
    "player": ('<circle cx="32" cy="29" r="14" ' + S + ' stroke-width="2.8"/>'
               '<path d="M28.5 22 l10 7 l-10 7 z" ' + F + '/>', "#a06bff"),
    "fonts": (f'<text x="32" y="38" text-anchor="middle" font-family="Georgia, serif" font-weight="700" font-size="22" fill="url(#ink)">Aa</text>', "#c9c9d2"),
    "connections": ('<rect x="13" y="16" width="22" height="16" rx="2.5" ' + S + ' stroke-width="2.4"/>'
                    '<rect x="29" y="25" width="22" height="16" rx="2.5" ' + F + '/>', "#3b82ff"),
    "scanner": ('<rect x="15" y="27" width="34" height="14" rx="3" ' + F + '/>'
                '<path d="M19 27 l4 -10 h18 l4 10" ' + S + ' stroke-width="2.4"/>'
                '<path d="M20 34 h24" stroke="#141416" stroke-width="2" stroke-linecap="round"/>', "#c9c9d2"),
})

FILES = {"notes": "smoky-notes.svg"}

os.makedirs(OUT, exist_ok=True)
for name, (glyph, accent) in icons.items():
    icon(name, glyph, accent, FILES.get(name))
print(f"{len(icons)} icônes générées dans {OUT}")
