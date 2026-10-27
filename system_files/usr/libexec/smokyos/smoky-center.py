#!/usr/bin/env python3
"""Smoky Center — réglages de Smoky OS (serveur local, 127.0.0.1 uniquement).

Même protection que Smoky Notes : jeton secret dans la page + en-tête Host vérifié.
Chaque action correspond à une commande précise et vérifiée ; aucune commande libre.
"""
import json
import os
import re
import secrets
import subprocess
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

PORT = int(os.environ.get("SMOKYCENTER_PORT", "47814"))
APP_DIR = Path(os.environ.get("SMOKYCENTER_APP", "/usr/share/smoky-center")).resolve()
HOME = Path.home()
CFG = HOME / ".config/smoky"
ADAPTIVE = CFG / "adaptive.json"
FOCUS = CFG / "focus.json"
HOME_TOKEN = HOME / ".config/smoky-home/token"
HOME_BG = HOME / ".config/autostart/smoky-home-bg.desktop"
LIBEXEC = "/usr/libexec/smokyos"
IMAGE = "ghcr.io/smokytwt/z13os"
VPN = "Smoky VPN"
TOKEN = secrets.token_urlsafe(24)
HOST_OK = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".png": "image/png"}
ADAPTIVE_DEFAULTS = {"refresh": True, "tablet": True, "vpn_auto": False, "tablet_open_notes": True}


def run(*args, timeout=8):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def spawn(*args):
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def jload(path, default):
    try:
        return {**default, **json.loads(Path(path).read_text())}
    except (OSError, ValueError):
        return dict(default)


def jsave(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))


# --- État de la machine -------------------------------------------------------------------
def state():
    bat = "/sys/class/power_supply/BAT0"
    _, gpu = run("supergfxctl", "-g")
    _, profile = run("powerprofilesctl", "get")
    _, conns = run("nmcli", "-t", "-f", "NAME", "connection", "show")
    _, active = run("nmcli", "-t", "-f", "NAME", "connection", "show", "--active")
    _, home_active = run("systemctl", "--user", "is-active", "smoky-home.service")
    code, moodle = run("python3", f"{LIBEXEC}/smoky-moodle.py", "status", timeout=10)
    try:
        moodle = json.loads(moodle) if code == 0 else {"connected": False}
    except ValueError:
        moodle = {"connected": False}
    _, ost = run("rpm-ostree", "status", "--json", timeout=10)
    image, staged = "", False
    try:
        deps = json.loads(ost).get("deployments", [])
        booted = next((d for d in deps if d.get("booted")), {})
        image = booted.get("container-image-reference", "")
        staged = any(d.get("staged") for d in deps)
    except ValueError:
        pass
    focus = jload(FOCUS, {"end": 0, "minutes": 0})
    if focus["end"] < time.time():
        focus = {"end": 0, "minutes": 0}
    pretty = re.search(r'^PRETTY_NAME="?([^"\n]*)', read("/etc/os-release"), re.M)
    return {
        "system": pretty.group(1) if pretty else "Smoky OS", "image": image, "update_staged": staged,
        "nvidia": "z13os-nvidia" in image,
        "gpu": gpu or "?", "profile": profile or "?",
        "battery": {"capacity": read(f"{bat}/capacity", "?"), "status": read(f"{bat}/status", "?"),
                    "limit": read(f"{bat}/charge_control_end_threshold", "?")},
        "adaptive": jload(ADAPTIVE, ADAPTIVE_DEFAULTS),
        "home": {"token": HOME_TOKEN.exists(), "background": HOME_BG.exists(), "running": home_active == "active"},
        "moodle": moodle,
        "vpn": {"configured": VPN in conns.splitlines(), "active": VPN in active.splitlines()},
        "focus": focus,
    }


# --- Actions ---------------------------------------------------------------------------------
def act(a):
    kind = a.get("action")
    if kind == "gpu" and a.get("mode") in ("Integrated", "Hybrid"):
        code, out = run("supergfxctl", "-m", a["mode"], timeout=30)
        return {"ok": code == 0, "message": "Déconnecte-toi puis reconnecte-toi pour appliquer." if code == 0 else out}
    if kind == "battery" and a.get("limit") in (60, 80, 100):
        code, _ = run("asusctl", "-c", str(a["limit"]))
        if code != 0:
            code, _ = run("asusctl", "battery", "limit", str(a["limit"]))
        return {"ok": code == 0}
    if kind == "profile" and a.get("name") in ("power-saver", "balanced", "performance"):
        return {"ok": run("powerprofilesctl", "set", a["name"])[0] == 0}
    if kind == "adaptive":
        cfg = jload(ADAPTIVE, ADAPTIVE_DEFAULTS)
        for k in ADAPTIVE_DEFAULTS:
            if isinstance(a.get(k), bool):
                cfg[k] = a[k]
        jsave(ADAPTIVE, cfg)
        return {"ok": True}
    if kind == "home_token":
        tok = str(a.get("token", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{20,600}", tok):
            return {"ok": False, "message": "Jeton invalide : copie-le en entier depuis Smoky Home."}
        HOME_TOKEN.parent.mkdir(parents=True, exist_ok=True)
        HOME_TOKEN.touch(mode=0o600)
        HOME_TOKEN.write_text(tok)
        return {"ok": True}
    if kind == "home_background":
        if a.get("on"):
            HOME_BG.parent.mkdir(parents=True, exist_ok=True)
            HOME_BG.write_text("[Desktop Entry]\nType=Application\nName=Smoky Home (arrière-plan)\n"
                               "Exec=systemctl --user start smoky-home.service\nNoDisplay=true\n")
            spawn("systemctl", "--user", "start", "smoky-home.service")
        else:
            HOME_BG.unlink(missing_ok=True)
            spawn("systemctl", "--user", "stop", "smoky-home.service")
        return {"ok": True}
    if kind == "home_open":
        spawn("/usr/bin/smoky-home")
        return {"ok": True}
    if kind in ("moodle_connect", "moodle_sync", "moodle_disconnect"):
        spawn("python3", f"{LIBEXEC}/smoky-moodle.py", kind.split("_")[1])
        return {"ok": True}
    if kind == "vpn_import":
        conf = str(a.get("content", ""))
        if "[Interface]" not in conf or "[Peer]" not in conf or len(conf) > 20000:
            return {"ok": False, "message": "Ce n'est pas un fichier de configuration WireGuard (.conf)."}
        run("nmcli", "connection", "delete", "id", VPN)
        tmp = CFG / "smokyvpn.conf"
        CFG.mkdir(parents=True, exist_ok=True)
        tmp.touch(mode=0o600)
        tmp.write_text(conf)
        code, out = run("nmcli", "connection", "import", "type", "wireguard", "file", str(tmp), timeout=20)
        tmp.unlink(missing_ok=True)
        if code != 0:
            return {"ok": False, "message": out or "Import refusé par NetworkManager."}
        run("nmcli", "connection", "modify", "smokyvpn", "connection.id", VPN, "connection.autoconnect", "no")
        return {"ok": True}
    if kind == "vpn" and isinstance(a.get("on"), bool):
        code, out = run("nmcli", "connection", "up" if a["on"] else "down", "id", VPN, timeout=30)
        return {"ok": code == 0, "message": out}
    if kind == "focus_start" and isinstance(a.get("minutes"), int) and 5 <= a["minutes"] <= 240:
        m = a["minutes"]
        code, out = run("systemctl", "start", "--no-block", f"smoky-focus@{m}.service", timeout=20)
        if code != 0:
            return {"ok": False, "message": out or "Démarrage refusé."}
        jsave(FOCUS, {"end": time.time() + m * 60, "minutes": m})
        spawn("systemd-run", "--user", f"--on-active={m}m", "--unit", f"smoky-focus-fin-{int(time.time())}",
              "notify-send", "-a", "Smoky OS", "-i", "alarm-symbolic", "Pause méritée ☕",
              f"{m} minutes de concentration terminées. Les sites sont de nouveau accessibles.")
        return {"ok": True}
    if kind == "focus_stop":
        f = jload(FOCUS, {"minutes": 0})
        if f.get("minutes"):
            run("systemctl", "stop", f"smoky-focus@{int(f['minutes'])}.service", timeout=20)
        FOCUS.unlink(missing_ok=True)
        return {"ok": True}
    if kind == "backup_open":
        spawn("flatpak", "run", "org.gnome.DejaDup")
        return {"ok": True}
    if kind == "icons_regen":
        spawn("python3", f"{LIBEXEC}/smoky-autoicons.py")
        return {"ok": True}
    if kind == "nvidia" and isinstance(a.get("on"), bool):
        target = f"{IMAGE}-nvidia:latest" if a["on"] else f"{IMAGE}:latest"
        spawn("sh", "-c",
              f'rpm-ostree rebase "ostree-unverified-registry:{target}" '
              '&& notify-send -a "Smoky OS" -i system-reboot "Pilote graphique prêt" "Redémarre le PC pour terminer." '
              '|| notify-send -a "Smoky OS" -i dialog-error "Changement de pilote échoué" "Rien n\'a été modifié."')
        return {"ok": True, "message": "Téléchargement en cours (plusieurs minutes) : une notification te préviendra."}
    return {"ok": False, "message": "Action inconnue."}


class Handler(BaseHTTPRequestHandler):
    server_version = "SmokyCenter/1.0"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def ok_host(self):
        return self.headers.get("Host", "") in HOST_OK

    def ok_api(self):
        return self.ok_host() and secrets.compare_digest(self.headers.get("X-Smoky-Token", ""), TOKEN)

    def do_GET(self):
        if not self.ok_host():
            return self.send(403, {"error": "hôte refusé"})
        path = unquote(self.path.split("?", 1)[0])
        if path == "/api/state":
            return self.send(200, state()) if self.ok_api() else self.send(403, {"error": "refusé"})
        target = (APP_DIR / (path.lstrip("/") or "index.html")).resolve()
        if APP_DIR not in target.parents or not target.is_file():
            return self.send(404, {"error": "introuvable"})
        data = target.read_bytes()
        if target.name == "index.html":
            data = data.replace(b"__SMOKY_TOKEN__", TOKEN.encode())
        csp = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send(200, data, MIME.get(target.suffix, "application/octet-stream"),
                  {"Content-Security-Policy": csp, "X-Frame-Options": "DENY"})

    def do_POST(self):
        if not self.ok_api() or self.path != "/api/action":
            return self.send(403, {"error": "refusé"})
        try:
            a = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 100000)))
        except ValueError:
            return self.send(400, {"error": "requête illisible"})
        self.send(200, act(a))


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
