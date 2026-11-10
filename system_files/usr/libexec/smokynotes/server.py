#!/usr/bin/env python3
"""Smoky Notes — petit serveur local (127.0.0.1 uniquement).

Sert l'interface web et enregistre les carnets dans ~/Notes/Smoky Notes/, dossier
synchronisé avec Google Drive. Seule la page servie ici peut écrire : jeton secret et
en-tête Host vérifiés à chaque requête (voir smokyos/smokyapp.py, commun aux applis Smoky).
"""
import json
import os
import re
import secrets
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smokyos"))
from smokyapp import MIME, Appli, Requete, servir  # noqa: E402

PORT = int(os.environ.get("SMOKYNOTES_PORT", "47813"))
APP_DIR = Path(os.environ.get("SMOKYNOTES_APP", "/usr/share/smokynotes")).resolve()
NOTES_ROOT = Path(os.environ.get("SMOKYNOTES_NOTES", Path.home() / "Notes")).resolve()
DATA_DIR = NOTES_ROOT / "Smoky Notes"
TRASH_DIR = DATA_DIR / ".corbeille"
CSP = ("default-src 'self'; img-src 'self' blob: data:; "
       "style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; media-src 'self' blob:; "
       "script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' blob: data:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
APPLI = Appli("notes", PORT, APP_DIR, CSP)

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ASSET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}\.(pdf|png|jpg|jpeg|webp|webm)$")
PDF_NAME_RE = re.compile(r"^[^/\\\x00]{1,120}\.pdf$")
MAX_BODY = 300 * 1024 * 1024  # 300 Mo (gros PDF de cours)


def write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Handler(Requete):
    """Routes de Smoky Notes (carnets, fichiers joints, export PDF)."""

    do_HEAD = Requete.do_GET

    def body(self):
        return self.corps(MAX_BODY)

    def route(self):
        return unquote(self.path.split("?", 1)[0])[5:]

    def do_PUT(self):
        if not self.api_ok():
            return self.fail(403, "refusé")
        try:
            return self.api_put(self.route())
        except ValueError as e:
            return self.fail(400, str(e))

    def do_DELETE(self):
        if not self.api_ok():
            return self.fail(403, "refusé")
        return self.api_delete(self.route())

    def do_POST(self):
        if not self.api_ok():
            return self.fail(403, "refusé")
        return self.api_post(self.route())

    # --- API ---------------------------------------------------------------
    def nb_dir(self, nid):
        if not ID_RE.match(nid):
            raise ValueError("identifiant invalide")
        return DATA_DIR / nid

    def api_get(self, route, requete=""):
        parts = route.split("/")
        try:
            if route == "deadlines":           # échéances Moodle (smoky-moodle)
                f = Path.home() / ".local/share/smoky-moodle/echeances.json"
                return self.send(200, f.read_bytes() if f.is_file() else b"[]")
            if route == "notebooks":
                out = []
                if DATA_DIR.is_dir():
                    for d in DATA_DIR.iterdir():
                        meta = d / "meta.json"
                        if d.is_dir() and ID_RE.match(d.name) and meta.is_file():
                            try:
                                out.append(json.loads(meta.read_text()))
                            except (OSError, ValueError):
                                pass
                return self.send(200, out)
            if parts[0] == "notebooks" and len(parts) == 2:
                f = self.nb_dir(parts[1]) / "notebook.json"
                if not f.is_file():
                    return self.fail(404, "carnet introuvable")
                return self.send(200, f.read_bytes())
            if parts[0] == "assets" and len(parts) == 3 and ASSET_RE.match(parts[2]):
                f = self.nb_dir(parts[1]) / "assets" / parts[2]
                if not f.is_file():
                    return self.fail(404, "fichier introuvable")
                return self.send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
        except ValueError as e:
            return self.fail(400, str(e))
        return self.fail(404, "route inconnue")

    def api_put(self, route):
        parts = route.split("/")
        if parts[0] == "notebooks" and len(parts) == 2:
            d = self.nb_dir(parts[1])
            nb = json.loads(self.body())
            if nb.get("id") != parts[1]:
                raise ValueError("identifiant incohérent")
            nb["updated"] = int(time.time() * 1000)
            meta = {k: nb.get(k) for k in ("id", "title", "cover", "created", "updated", "favorite", "folder")}
            meta["pages"] = len(nb.get("pages", []))
            write_atomic(d / "notebook.json", json.dumps(nb, separators=(",", ":")).encode())
            write_atomic(d / "meta.json", json.dumps(meta).encode())
            return self.send(200, {"ok": True, "updated": nb["updated"]})
        if parts[0] == "assets" and len(parts) == 3 and ASSET_RE.match(parts[2]):
            write_atomic(self.nb_dir(parts[1]) / "assets" / parts[2], self.body())
            return self.send(200, {"ok": True})
        if parts[0] == "export" and len(parts) == 2 and PDF_NAME_RE.match(parts[1]):
            name = parts[1].replace("..", "_").lstrip(".")
            dest = NOTES_ROOT / "PDF" / name
            write_atomic(dest, self.body())
            return self.send(200, {"ok": True, "path": str(dest)})
        return self.fail(404, "route inconnue")

    def api_post(self, route):
        parts = route.split("/")
        try:
            if parts[0] == "duplicate" and len(parts) == 3:
                src, dst = self.nb_dir(parts[1]), self.nb_dir(parts[2])
                if not src.is_dir() or dst.exists():
                    return self.fail(409, "copie impossible")
                shutil.copytree(src, dst)
                return self.send(200, {"ok": True})
        except ValueError as e:
            return self.fail(400, str(e))
        return self.fail(404, "route inconnue")

    def api_delete(self, route):
        parts = route.split("/")
        try:
            if parts[0] == "notebooks" and len(parts) == 2:
                d = self.nb_dir(parts[1])
                if d.is_dir():
                    TRASH_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(d), str(TRASH_DIR / f"{d.name}-{int(time.time())}"))
                return self.send(200, {"ok": True})
        except ValueError as e:
            return self.fail(400, str(e))
        return self.fail(404, "route inconnue")


# Carnets des matières (liste commune à Smoky OS) : un classeur par matière, où arrivent
# aussi les cours Moodle de la matière. Créés une fois ; un carnet supprimé ne revient pas.
SUBJECTS_FILE = Path(os.environ.get("SMOKY_MATIERES", "/usr/share/smokyos/matieres.json"))
COVERS = ["ink", "slate", "ember", "sage", "graphite", "ash", "ivory", "onyx"]
PAGE_A4 = (595, 842)


def _key(title):
    t = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    return t.lower().strip()


def subjects():
    try:
        return [(m["nom"], m.get("papier", "grid")) for m in json.loads(SUBJECTS_FILE.read_text())["matieres"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def seed_subjects():
    subj = subjects()
    names = {_key(t): t for t, _ in subj}
    metas = {}
    for meta in DATA_DIR.glob("*/meta.json"):
        try:
            metas[meta.parent] = json.loads(meta.read_text())
        except (OSError, ValueError):
            pass
    # v1 rangeait les carnets des matières dans un classeur « Cours » : chacun passe dans le sien
    for d, meta in metas.items():
        t = names.get(_key(meta.get("title")))
        if meta.get("folder") == "Cours" and t:
            try:
                nb = json.loads((d / "notebook.json").read_text())
                nb["folder"] = meta["folder"] = t
                write_atomic(d / "notebook.json", json.dumps(nb, separators=(",", ":")).encode())
                write_atomic(d / "meta.json", json.dumps(meta).encode())
            except (OSError, ValueError):
                pass
    marker = DATA_DIR / ".matieres-1"
    if marker.exists():
        return
    have = {_key(m.get("title")) for m in metas.values()}
    now = int(time.time() * 1000)
    for i, (title, template) in enumerate(subj):
        if _key(title) in have:
            continue
        nid = f"n{now + i:x}-{secrets.token_hex(3)}"
        d = DATA_DIR / nid
        page = {"id": f"p{now + i:x}-{secrets.token_hex(3)}", "w": PAGE_A4[0], "h": PAGE_A4[1],
                "template": template, "paper": "white", "bg": None, "items": [], "marked": False}
        nb = {"id": nid, "version": 1, "title": title, "cover": COVERS[i % len(COVERS)],
              "created": now + i, "updated": now + i, "favorite": False, "folder": title,
              "defaults": {"size": "a4", "template": template, "paper": "white"}, "pages": [page]}
        meta = {k: nb[k] for k in ("id", "title", "cover", "created", "updated", "favorite", "folder")}
        meta["pages"] = 1
        write_atomic(d / "notebook.json", json.dumps(nb, separators=(",", ":")).encode())
        write_atomic(d / "meta.json", json.dumps(meta).encode())
    marker.touch()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        seed_subjects()
    except OSError as e:
        print(f"Carnets des matières non créés : {e}", file=sys.stderr)
    print(f"Smoky Notes : http://127.0.0.1:{PORT}/ — carnets dans {DATA_DIR}", file=sys.stderr)
    servir(APPLI, Handler)


if __name__ == "__main__":
    main()
