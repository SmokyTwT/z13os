#!/usr/bin/env python3
"""Ménage pendant les cours : lancé par Smoky Agenda (minuteur au début du premier cours du jour).

Démarre Smoky Home si besoin, puis lance le robot s'il est sur sa base, assez chargé et pas déjà
passé aujourd'hui. Utilise le jeton d'accès relié dans Smoky Center (~/.config/smoky-home/token).
"""
import json
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

HA = "http://127.0.0.1:8123"
TOKEN = Path.home() / ".config/smoky-home/token"
DONE = Path.home() / ".config/smoky/menage-du-jour"
DOCKED = {"docked", "idle", "charging"}


def notify(title, body):
    subprocess.run(["notify-send", "-a", "Smoky Home", "-i", "smoky-home", title, body], check=False)


def api(path, token, body=None):
    req = urllib.request.Request(HA + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"null")


def up():
    try:
        urllib.request.urlopen(HA + "/", timeout=3)
        return True
    except OSError:
        return False


def main():
    if DONE.exists() and DONE.read_text().strip() == date.today().isoformat():
        return 0                                       # déjà fait aujourd'hui
    if not TOKEN.exists():
        notify("Ménage pendant les cours", "Relie d'abord Smoky Home dans Smoky Center → Maison.")
        return 1
    token = TOKEN.read_text().strip()
    if not up():                                       # moteur arrêté : on le démarre (3 min au plus)
        subprocess.run(["systemctl", "--user", "start", "smoky-home.service"], check=False)
        for _ in range(90):
            if up():
                break
            time.sleep(2)
        time.sleep(20)                                 # le temps que l'intégration du robot se connecte
    try:
        vacuums = [s for s in api("/api/states", token) if s["entity_id"].startswith("vacuum.")]
    except OSError:
        notify("Ménage pendant les cours", "Smoky Home ne répond pas : le robot n'a pas été lancé.")
        return 1
    started = []
    for v in vacuums:
        battery = v["attributes"].get("battery_level")
        if v["state"] not in DOCKED or (isinstance(battery, (int, float)) and battery < 40):
            continue
        try:
            api("/api/services/vacuum/start", token, {"entity_id": v["entity_id"]})
            started.append(v["attributes"].get("friendly_name", "Robot"))
        except OSError:
            pass
    if started:
        DONE.parent.mkdir(parents=True, exist_ok=True)
        DONE.write_text(date.today().isoformat())
        notify("Ménage lancé pendant ton cours", "Le robot nettoie la chambre pendant que tu n'y es pas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
