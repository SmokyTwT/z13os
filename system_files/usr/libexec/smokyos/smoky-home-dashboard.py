#!/usr/bin/env python3
"""Smoky Home : tableau de bord allégé, généré à partir des appareils connus de Home Assistant.

Robot : une tuile avec démarrer / pause / arrêt / retour à la base (la puissance d'aspiration en
la touchant),
puis seulement les réglages de nettoyage (mode, eau, serpillière, passages, tapis…) et la
batterie. Les dizaines de boutons techniques de l'intégration Xiaomi Home sont laissés de côté.
Lumières et enceintes : une tuile chacune.

Le fichier n'est réécrit que s'il vient de ce script : si tu modifies le tableau de bord dans
Smoky Home (« Prendre le contrôle », « Modifier »), il n'est plus jamais touché.
Code de sortie : 0 rien changé, 10 tableau de bord réécrit (le moteur doit le recharger).
"""
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".local/share/smoky-home"
STORE = DATA / ".storage"
TARGET = STORE / "lovelace"
STAMP = DATA / ".smoky-dashboard.sha256"
# réglages de nettoyage gardés (sur le nom de l'entité, sans accents)
KEEP = re.compile(r"suction|fan|aspir|puissan|mode|water|eau|mop|serpill|clean|nettoy|carpet|tapis|"
                  r"times|passage|repeat|route|intensit|level|niveau|edge|bord", re.I)
SKIP = re.compile(r"status|statut|locked|sleep|remote|listen|system|firmware|debug|reset|life|"
                  r"duree|left|restant|filter|filtre|brush|brosse", re.I)


def plain(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()


def load(name):
    try:
        return json.loads((STORE / name).read_text())["data"]
    except (OSError, ValueError, KeyError):
        return {}


def main():
    entities = [e for e in load("core.entity_registry").get("entities", [])
                if not e.get("disabled_by") and not e.get("hidden_by")]
    devices = {d["id"]: d for d in load("core.device_registry").get("devices", [])}
    if not entities:
        return 0

    def label(e):
        return e.get("name") or e.get("original_name") or e["entity_id"].split(".", 1)[1].replace("_", " ")

    cards = []
    for vac in (e for e in entities if e["entity_id"].startswith("vacuum.")):
        dev = devices.get(vac.get("device_id"), {})
        same = [e for e in entities if e.get("device_id") and e.get("device_id") == vac.get("device_id")]
        settings = [e["entity_id"] for e in same
                    if e["entity_id"].split(".")[0] in ("select", "number", "switch")
                    and e.get("entity_category") != "diagnostic"
                    and KEEP.search(plain(label(e))) and not SKIP.search(plain(label(e)))]
        battery = [e["entity_id"] for e in same if e["entity_id"].startswith("sensor.")
                   and re.search(r"batter", plain(label(e)) + e["entity_id"], re.I)][:1]
        cards.append({"type": "tile", "entity": vac["entity_id"],
                      "name": dev.get("name_by_user") or dev.get("name") or "Robot",
                      "vertical": False,
                      # puissance d'aspiration : en touchant la tuile (fenêtre détaillée du robot)
                      "features": [{"type": "vacuum-commands",
                                    "commands": ["start_pause", "stop", "return_home", "locate"]}]})
        if battery or settings:
            cards.append({"type": "entities", "title": "Réglages du nettoyage",
                          "entities": battery + settings[:12]})
    lights = [e["entity_id"] for e in entities if e["entity_id"].startswith("light.")]
    players = [e["entity_id"] for e in entities if e["entity_id"].startswith("media_player.")]
    if lights:
        cards.append({"type": "grid", "columns": 2, "square": False,
                      "cards": [{"type": "tile", "entity": l, "features": [{"type": "light-brightness"}]}
                                for l in lights]})
    for p in players:
        cards.append({"type": "media-control", "entity": p})
    if not cards:
        return 0

    config = {"title": "Smoky Home", "views": [{"title": "Maison", "path": "maison", "icon": "mdi:home",
                                                "type": "sections", "max_columns": 2,
                                                "sections": [{"type": "grid", "cards": [c]} for c in cards]}]}
    new = json.dumps({"version": 1, "minor_version": 1, "key": "lovelace", "data": {"config": config}},
                     ensure_ascii=False, indent=2)
    digest = hashlib.sha256(new.encode()).hexdigest()
    if TARGET.exists():
        cur = hashlib.sha256(TARGET.read_bytes()).hexdigest()
        last = STAMP.read_text().strip() if STAMP.exists() else ""
        if cur != last:            # tableau de bord modifié par toi (ou d'origine) : on ne touche à rien
            if last:
                return 0
            try:                   # premier passage : on ne remplace qu'un tableau de bord jamais modifié
                if json.loads(TARGET.read_text()).get("data", {}).get("config", {}).get("views"):
                    return 0
            except ValueError:
                return 0
        if cur == digest:
            return 0
    STORE.mkdir(parents=True, exist_ok=True)
    tmp = TARGET.with_suffix(".tmp")
    tmp.write_text(new)
    tmp.replace(TARGET)
    STAMP.write_text(digest)
    return 10


if __name__ == "__main__":
    sys.exit(main())
