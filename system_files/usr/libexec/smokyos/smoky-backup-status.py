#!/usr/bin/env python3
"""Sauvegardes (Déjà Dup) : date de la dernière sauvegarde réussie, et rappel si elle est trop ancienne.

  smoky-backup-status.py          état en JSON (pour Smoky Center)
  smoky-backup-status.py --check  notification si la dernière sauvegarde date de plus de 7 jours
                                  (une fois par jour au plus ; lancé chaque jour par un minuteur)
"""
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HOME = Path.home()
# Déjà Dup en Flatpak range ses réglages dans son dossier ; sinon, dans les réglages GNOME
KEYFILE = HOME / ".var/app/org.gnome.DejaDup/config/glib-2.0/settings/keyfile"
STAMP = HOME / ".config/smoky/rappel-sauvegarde"
MAX_DAYS = 7


def read_setting(key):
    try:
        m = re.search(rf"^{key}\s*=\s*'([^']*)'", KEYFILE.read_text(), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    try:
        r = subprocess.run(["gsettings", "get", "org.gnome.DejaDup", key], capture_output=True, text=True, timeout=5)
        return r.stdout.strip().strip("'") if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def status():
    raw = read_setting("last-backup")
    last = None
    if raw:
        try:
            last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except ValueError:
            last = None
    days = (datetime.now(timezone.utc) - last).days if last else None
    return {"last": last.astimezone().strftime("%Y-%m-%d %H:%M") if last else "", "days": days,
            "periodic": read_setting("periodic") == "true", "late": days is None or days > MAX_DAYS}


def check():
    st = status()
    if not st["late"] or (STAMP.exists() and STAMP.read_text().strip() == date.today().isoformat()):
        return 0
    body = ("Aucune sauvegarde n'a encore été faite : ouvre Smoky Center → Sauvegardes."
            if st["days"] is None else
            f"La dernière sauvegarde date de {st['days']} jours : branche-toi à Internet et lance-la depuis Smoky Center.")
    subprocess.run(["notify-send", "-a", "Smoky OS", "-i", "deja-dup", "Sauvegarde à faire", body], check=False)
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    STAMP.write_text(date.today().isoformat())
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check())
    print(json.dumps(status()))
