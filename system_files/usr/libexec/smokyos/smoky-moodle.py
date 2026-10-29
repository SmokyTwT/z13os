#!/usr/bin/env python3
"""Smoky OS — Moodle → Smoky Notes et échéances.

  smoky-moodle.py connect            connexion (identifiant + mot de passe, ou page de l'université)
  smoky-moodle.py receive URL        reçoit l'accès après connexion par la page de l'université
  smoky-moodle.py sync               importe les nouveaux PDF de cours et met à jour les échéances
  smoky-moodle.py status             état (JSON)
  smoky-moodle.py disconnect         oublie l'accès

Les PDF arrivent dans Smoky Notes, un carnet par document, rangés dans le classeur de la
matière (Algèbre, Méca… : /usr/share/smokyos/matieres.json), sinon dans un classeur au nom
du cours. Rien n'est jamais modifié ni supprimé dans tes carnets existants. Le mot de passe
n'est jamais enregistré : seul le jeton d'accès Moodle l'est, dans le trousseau GNOME.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
STATE_DIR = HOME / ".local/share/smoky-moodle"
STATE = STATE_DIR / "state.json"
DEADLINES = STATE_DIR / "echeances.json"
NOTES = HOME / "Notes"
NOTEBOOKS = NOTES / "Smoky Notes"
SITE_FILE = Path("/etc/smokyos/moodle-url")
SUBJECTS_FILE = Path(os.environ.get("SMOKY_MATIERES", "/usr/share/smokyos/matieres.json"))
SERVICE = "moodle_mobile_app"
UA = "SmokyOS-Moodle/1.0"


# --- Outils ---------------------------------------------------------------------------
def run(args, **kw):
    """subprocess.run qui ne plante pas si l'outil est absent (renvoie un code 127)."""
    try:
        return subprocess.run(args, **kw)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", "")


def site():
    url = os.environ.get("SMOKY_MOODLE_URL") or (SITE_FILE.read_text().strip() if SITE_FILE.exists() else "https://moodle.uphf.fr/")
    p = urllib.parse.urlsplit(url)
    # le mot de passe et le jeton ne circulent qu'en HTTPS (HTTP seulement pour un test local)
    if p.scheme != "https" and p.hostname not in ("127.0.0.1", "localhost"):
        sys.exit("Adresse Moodle refusée : HTTPS obligatoire.")
    return f"{p.scheme}://{p.netloc}"


def same_site(url):
    """Le jeton n'est jamais envoyé à un autre site que Moodle (lien externe dans un cours…)."""
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(site())
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def notify(title, body, icon="smokyos-moodle"):
    run(["notify-send", "-a", "Smoky OS", "-i", icon, title, body], check=False)


def zenity(*args):
    r = run(["zenity", *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"files": {}, "notified": []}


def save_state(st):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    os.replace(tmp, STATE)


# --- Matières --------------------------------------------------------------------------------
def plain(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def subject_for(course):
    """Matière d'un cours Moodle d'après son nom (« ALGEBRE LINEAIRE S1 » → Algèbre), sinon None."""
    try:
        matieres = json.loads(SUBJECTS_FILE.read_text())["matieres"]
    except (OSError, ValueError, KeyError):
        return None
    names = " ".join(plain(course.get(k)) for k in ("shortname", "fullname", "displayname"))
    names = re.sub(r"[^a-z0-9]+", " ", names)
    for m in matieres:
        for mot in m.get("mots", []):
            if re.search(r"(?<![a-z0-9])" + re.escape(plain(mot)), names):
                return m["nom"]
    return None


def set_folder(nid, folder, only_from):
    """Range un carnet importé avant les matières dans le classeur de sa matière, s'il est encore
    dans le classeur d'origine (un carnet que tu as déplacé toi-même ne bouge pas)."""
    d = NOTEBOOKS / nid
    try:
        nb, meta = json.loads((d / "notebook.json").read_text()), json.loads((d / "meta.json").read_text())
    except (OSError, ValueError):
        return
    if nb.get("folder") != only_from or only_from == folder:
        return
    nb["folder"] = meta["folder"] = folder
    for name, obj in (("notebook.json", nb), ("meta.json", meta)):
        tmp = d / f".{name}.tmp"
        tmp.write_text(json.dumps(obj, separators=(",", ":")))
        os.replace(tmp, d / name)


# --- Jeton (trousseau GNOME, sinon fichier privé) ------------------------------------------
def token_set(tok):
    host = urllib.parse.urlsplit(site()).netloc
    r = run(["secret-tool", "store", "--label=Smoky OS – Moodle", "service", "smoky-moodle", "site", host],
                       input=tok, text=True, capture_output=True)
    if r.returncode != 0:                                  # pas de trousseau : fichier lisible par toi seul
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        f = STATE_DIR / "token"
        f.touch(mode=0o600)
        f.write_text(tok)


def token_get():
    host = urllib.parse.urlsplit(site()).netloc
    r = run(["secret-tool", "lookup", "service", "smoky-moodle", "site", host], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    f = STATE_DIR / "token"
    return f.read_text().strip() if f.exists() else None


def token_clear():
    host = urllib.parse.urlsplit(site()).netloc
    run(["secret-tool", "clear", "service", "smoky-moodle", "site", host], check=False)
    (STATE_DIR / "token").unlink(missing_ok=True)


# --- API Moodle (services web de l'appli mobile officielle) ----------------------------------
MAX_DOWNLOAD = 200 * 1024 * 1024        # un PDF de cours plus gros est ignoré


def http(url, data=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(MAX_DOWNLOAD + 1)
    if len(body) > MAX_DOWNLOAD:
        raise ValueError("fichier trop volumineux")
    return body


def ws(token, fn, **params):
    q = {"wstoken": token, "wsfunction": fn, "moodlewsrestformat": "json"}
    for k, v in params.items():
        q[k] = v
    out = json.loads(http(site() + "/webservice/rest/server.php", urllib.parse.urlencode(q).encode()))
    if isinstance(out, dict) and out.get("exception"):
        raise RuntimeError(out.get("message") or out.get("errorcode"))
    return out


# --- Connexion ------------------------------------------------------------------------------
def connect():
    code, out = zenity("--forms", "--title=Connecter Moodle", "--width=420",
                       f"--text=Connexion à {site()}\n(ton mot de passe sert une seule fois et n'est pas enregistré)",
                       "--add-entry=Identifiant", "--add-password=Mot de passe")
    if code != 0:
        return 1
    user, _, pwd = out.partition("|")
    q = urllib.parse.urlencode({"username": user, "password": pwd, "service": SERVICE})
    try:
        res = json.loads(http(f"{site()}/login/token.php?{q}"))
    except Exception as e:
        zenity("--error", "--width=420", f"--text=Moodle injoignable : {e}")
        return 1
    if res.get("token"):
        token_set(res["token"])
        zenity("--info", "--width=420", "--text=✅ Moodle est connecté. Tes cours arrivent dans Smoky Notes.")
        return sync()
    # Connexion unique de l'université (CAS…) : on passe par la page de connexion officielle
    passport = secrets.token_hex(8)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "passport").write_text(passport)
    launch = f"{site()}/admin/tool/mobile/launch.php?service={SERVICE}&passport={passport}&urlscheme=moodlemobile"
    zenity("--info", "--width=460", "--ok-label=Ouvrir la page",
           f"--text=Moodle répond : « {res.get('error', 'connexion refusée')} ».\n\n"
           "Si ton identifiant et ton mot de passe sont bons, c'est que l'université utilise sa propre page "
           "de connexion. Elle va s'ouvrir : connecte-toi normalement, Smoky OS récupère l'accès tout seul.")
    subprocess.Popen(["xdg-open", launch])
    return 0


def receive(url):
    """Retour de la page de connexion : moodlemobile://token=BASE64(signature:::jeton[:::jeton privé])."""
    m = re.search(r"token=([A-Za-z0-9+/=_-]+)", url)
    if not m:
        notify("Moodle", "Réponse de connexion illisible.")
        return 1
    raw = base64.b64decode(m.group(1) + "===").decode(errors="replace")
    parts = raw.split(":::")
    if len(parts) < 2:
        notify("Moodle", "Réponse de connexion illisible.")
        return 1
    passport_file = STATE_DIR / "passport"
    passport = passport_file.read_text().strip() if passport_file.exists() else ""
    expected = hashlib.md5((site() + "/" + passport).encode()).hexdigest()
    expected2 = hashlib.md5((site() + passport).encode()).hexdigest()
    if parts[0] not in (expected, expected2):                 # la réponse doit venir de notre demande
        notify("Moodle", "Connexion refusée : la réponse ne correspond pas à la demande.")
        return 1
    passport_file.unlink(missing_ok=True)
    token_set(parts[1])
    notify("Moodle connecté", "Tes cours arrivent dans Smoky Notes.")
    return sync()


# --- Création des carnets (même format que Smoky Notes) -------------------------------------
def uid(prefix):
    return prefix + format(int(time.time() * 1000), "x") + "-" + secrets.token_hex(4)


def pdf_pages(path):
    out = run(["pdfinfo", "-f", "1", "-l", "100000", str(path)], capture_output=True, text=True).stdout
    sizes = []
    for line in out.splitlines():
        m = re.match(r"Page\s+\d+\s+size:\s+([\d.]+) x ([\d.]+)", line)
        if m:
            sizes.append((round(float(m.group(1))), round(float(m.group(2)))))
    if not sizes:
        n = re.search(r"^Pages:\s+(\d+)", out, re.M)
        sizes = [(595, 842)] * int(n.group(1) if n else 1)
    return sizes


def create_notebook(pdf_bytes, title, folder):
    nid = uid("n")
    d = NOTEBOOKS / nid
    (d / "assets").mkdir(parents=True)
    asset = hashlib.sha256(pdf_bytes).hexdigest()[:24] + ".pdf"
    (d / "assets" / asset).write_bytes(pdf_bytes)
    now = int(time.time() * 1000)
    pages = [{"id": uid("p"), "w": w, "h": h, "template": "blank", "paper": "white",
              "bg": {"type": "pdf", "asset": asset, "page": i}, "items": [], "marked": False}
             for i, (w, h) in enumerate(pdf_pages(d / "assets" / asset))]
    nb = {"id": nid, "version": 1, "title": title, "cover": "slate", "created": now, "updated": now,
          "favorite": False, "folder": folder, "source": "moodle",
          "defaults": {"size": "a4", "template": "lined", "paper": "white"}, "pages": pages}
    meta = {k: nb[k] for k in ("id", "title", "cover", "created", "updated", "favorite", "folder")}
    meta["pages"] = len(pages)
    (d / "notebook.json").write_text(json.dumps(nb, separators=(",", ":")))
    (d / "meta.json").write_text(json.dumps(meta))
    return nid


def notebook_untouched(nid):
    try:
        nb = json.loads((NOTEBOOKS / nid / "notebook.json").read_text())
        return all(not p.get("items") for p in nb.get("pages", []))
    except (OSError, ValueError):
        return False


# --- Synchronisation --------------------------------------------------------------------------
def sync():
    token = token_get()
    if not token:
        return 0
    st = load_state()
    try:
        info = ws(token, "core_webservice_get_site_info")
        courses = ws(token, "core_enrol_get_users_courses", userid=info["userid"])
    except Exception as e:
        print(f"Moodle : {e}", file=sys.stderr)
        return 1
    added = []
    subjects = st.setdefault("subjects", {})          # id du cours → matière (pour Smoky Agenda)
    for c in courses:
        subject = subject_for(c)
        subjects[str(c["id"])] = subject
        course_folder = re.sub(r"\s+", " ", c.get("shortname") or c.get("fullname") or "Cours").strip()[:60]
        folder = subject or course_folder
        try:
            sections = ws(token, "core_course_get_contents", courseid=c["id"])
        except Exception as e:
            print(f"{folder} : {e}", file=sys.stderr)
            continue
        for sec in sections:
            for mod in sec.get("modules", []):
                for f in mod.get("contents") or []:
                    if f.get("type") != "file" or not f.get("filename", "").lower().endswith(".pdf"):
                        continue
                    key = f.get("fileurl", "").split("?")[0]
                    if not same_site(key):
                        continue
                    known = st["files"].get(key)
                    if known and known["mtime"] >= f.get("timemodified", 0):
                        set_folder(known["notebook"], folder, course_folder)   # importés avant les matières
                        continue
                    url = f["fileurl"] + ("&" if "?" in f["fileurl"] else "?") + "token=" + token
                    try:
                        data = http(url, timeout=180)
                    except Exception as e:
                        print(f"{f['filename']} : {e}", file=sys.stderr)
                        continue
                    if not data.startswith(b"%PDF"):
                        continue
                    title = f["filename"][:-4]
                    if known and notebook_untouched(known["notebook"]):   # pas encore annoté : on remplace
                        shutil.rmtree(NOTEBOOKS / known["notebook"], ignore_errors=True)
                    elif known:
                        title += " (nouvelle version)"
                    nid = create_notebook(data, title, folder)
                    st["files"][key] = {"mtime": f.get("timemodified", 0), "notebook": nid}
                    added.append(f"{folder} — {title}")
    deadlines(token, st)
    save_state(st)
    if added:
        notify("Nouveaux cours dans Smoky Notes",
               "\n".join(added[:6]) + (f"\n… et {len(added) - 6} autres" if len(added) > 6 else ""))
    print(f"{len(added)} document(s) importé(s)")
    return 0


def ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def deadlines(token, st):
    now = int(time.time())
    try:
        res = ws(token, "core_calendar_get_action_events_by_timesort", timesortfrom=now - 86400, limitnum=50)
    except Exception as e:
        print(f"échéances : {e}", file=sys.stderr)
        return
    subjects = st.get("subjects", {})
    events = [{"id": e["id"], "name": e.get("activityname") or e.get("name", ""),
               "course": (e.get("course") or {}).get("fullname", ""), "time": e.get("timesort", 0),
               "subject": subjects.get(str((e.get("course") or {}).get("id"))) or subject_for(e.get("course") or {}),
               "url": e.get("url", "")} for e in res.get("events", [])]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DEADLINES.write_text(json.dumps(events, ensure_ascii=False, indent=1))
    # fichier agenda (importable dans n'importe quel agenda, synchronisé avec Google Drive)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Smoky OS//Moodle//FR"]
    for e in events:
        t = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(e["time"]))
        lines += ["BEGIN:VEVENT", f"UID:moodle-{e['id']}@smokyos", f"DTSTAMP:{t}", f"DTSTART:{t}", f"DTEND:{t}",
                  f"SUMMARY:{ics_escape(e['name'])}", f"DESCRIPTION:{ics_escape(e['course'])}", f"URL:{re.sub(r'[\s;,]', '', e['url'])}",
                  "BEGIN:VALARM", "TRIGGER:-PT24H", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(e['name'])}",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    NOTES.mkdir(exist_ok=True)
    (NOTES / "Moodle - échéances.ics").write_text("\r\n".join(lines) + "\r\n")
    # rappel la veille (et le jour même), une seule fois par échéance
    for e in events:
        left = e["time"] - now
        if 0 < left <= 36 * 3600 and e["id"] not in st["notified"]:
            when = time.strftime("%A %d à %Hh%M", time.localtime(e["time"]))
            notify(f"À rendre : {e['name']}", f"{e['course']}\n{when}", icon="appointment-soon")
            st["notified"].append(e["id"])
    st["notified"] = st["notified"][-200:]


def status():
    st = load_state()
    ev = json.loads(DEADLINES.read_text()) if DEADLINES.exists() else []
    print(json.dumps({"connected": bool(token_get()), "site": site(), "documents": len(st["files"]),
                      "deadlines": ev[:10]}, ensure_ascii=False))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "sync"
    if cmd == "connect":
        return connect()
    if cmd == "receive" and len(argv) > 2:
        return receive(argv[2])
    if cmd == "sync":
        return sync()
    if cmd == "status":
        return status()
    if cmd == "disconnect":
        token_clear()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
