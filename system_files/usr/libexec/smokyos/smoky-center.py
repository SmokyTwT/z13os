#!/usr/bin/env python3
"""Smoky Center — réglages de Smoky OS (serveur local, 127.0.0.1 uniquement).

Même protection que Smoky Notes : jeton secret dans la page + en-tête Host vérifié.
Chaque action correspond à une commande précise et vérifiée ; aucune commande libre.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
VPN = "Smoky VPN"
TOKEN = secrets.token_urlsafe(24)
# le code d'accès n'est plus écrit dans la page : le lanceur le lit ici (dossier privé de la session)
TOKEN_FILE = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "smoky-center.token"
UPDATE = {"running": False, "result": ""}
HOST_OK = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".png": "image/png"}
ADAPTIVE_DEFAULTS = {"refresh": True, "tablet_mode": False, "vpn_auto": False, "tablet_open_notes": True}


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


_OSTREE = {"at": 0, "image": "", "staged": False}


def ostree_status(fresh=False):
    """rpm-ostree status est lent : relu au plus une fois par minute (ou après une mise à jour)."""
    if fresh or time.time() - _OSTREE["at"] > 60:
        _, ost = run("rpm-ostree", "status", "--json", timeout=10)
        try:
            deps = json.loads(ost).get("deployments", [])
            booted = next((d for d in deps if d.get("booted")), {})
            _OSTREE.update(image=booted.get("container-image-reference", ""),
                           staged=any(d.get("staged") for d in deps))
        except ValueError:
            pass
        _OSTREE["at"] = time.time()
    return _OSTREE["image"], _OSTREE["staged"]


def staged_update():
    return ostree_status(fresh=True)[1]


def do_update():
    """Télécharge la nouvelle image Smoky OS ; elle s'applique au prochain redémarrage."""
    code, out = run("rpm-ostree", "upgrade", timeout=3600)
    if code != 0:
        UPDATE["result"] = "error"
        spawn("notify-send", "-a", "Smoky OS", "-i", "dialog-error", "Mise à jour impossible",
              "Vérifie la connexion internet et réessaie.")
    elif staged_update():
        UPDATE["result"] = "staged"
        spawn("notify-send", "-a", "Smoky OS", "-i", "system-reboot", "Mise à jour prête",
              "Redémarre quand tu veux pour l'appliquer (Smoky Center > Mises à jour).")
    else:
        UPDATE["result"] = "uptodate"
    UPDATE["running"] = False


# --- Réglages GNOME modifiables (liste fermée : rien d'autre ne peut être changé) -----------------
# nom : (schéma, clé, type GVariant, valeurs permises ; None = booléen)
GSET = {
    "night_light": ("org.gnome.settings-daemon.plugins.color", "night-light-enabled", "b", None),
    "night_light_temp": ("org.gnome.settings-daemon.plugins.color", "night-light-temperature", "u", (2700, 3500, 4500)),
    "night_light_auto": ("org.gnome.settings-daemon.plugins.color", "night-light-schedule-automatic", "b", None),
    "ambient": ("org.gnome.settings-daemon.plugins.power", "ambient-enabled", "b", None),
    "rotation_lock": ("org.gnome.settings-daemon.peripherals.touchscreen", "orientation-lock", "b", None),
    "text_scale": ("org.gnome.desktop.interface", "text-scaling-factor", "d", (1.0, 1.1, 1.25)),
    "idle_delay": ("org.gnome.desktop.session", "idle-delay", "u", (120, 300, 600, 900, 0)),
    "sleep_battery": ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout", "i", (600, 900, 1800, 3600)),
    "sleep_ac": ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "s", ("suspend", "nothing")),
    "show_banners": ("org.gnome.desktop.notifications", "show-banners", "b", None),
    "lock_notifs": ("org.gnome.desktop.notifications", "show-in-lock-screen", "b", None),
    "lock_delay": ("org.gnome.desktop.screensaver", "lock-delay", "u", (0, 60, 300)),
    "recent_files": ("org.gnome.desktop.privacy", "remember-recent-files", "b", None),
    "old_trash": ("org.gnome.desktop.privacy", "remove-old-trash-files", "b", None),
    "old_temp": ("org.gnome.desktop.privacy", "remove-old-temp-files", "b", None),
    "camera_off": ("org.gnome.desktop.privacy", "disable-camera", "b", None),
    "location": ("org.gnome.system.location", "enabled", "b", None),
    "volume_boost": ("org.gnome.desktop.sound", "allow-volume-above-100-percent", "b", None),
    "event_sounds": ("org.gnome.desktop.sound", "event-sounds", "b", None),
    "dock_size": ("org.gnome.shell.extensions.dash-to-dock", "dash-max-icon-size", "i", (44, 52, 60)),
    "dock_fixed": ("org.gnome.shell.extensions.dash-to-dock", "dock-fixed", "b", None),
    "battery_pct": ("org.gnome.desktop.interface", "show-battery-percentage", "b", None),
    "hot_corner": ("org.gnome.desktop.interface", "enable-hot-corners", "b", None),
    "animations": ("org.gnome.desktop.interface", "enable-animations", "b", None),
    "tap_click": ("org.gnome.desktop.peripherals.touchpad", "tap-to-click", "b", None),
    "natural_scroll": ("org.gnome.desktop.peripherals.touchpad", "natural-scroll", "b", None),
}

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    Gio = None
_SETTINGS = {}
# Ce serveur n'a pas de boucle GLib : sans elle, GSettings ne voit jamais les changements faits
# ailleurs (menu en haut à droite, Paramètres…) et affichait d'anciennes valeurs. On traite les
# notifications en attente avant chaque lecture, sous verrou (plusieurs requêtes en parallèle).
_GLOCK = threading.Lock()


def _pump():
    ctx = GLib.MainContext.default()
    for _ in range(200):
        if not ctx.iteration(False):
            break


def gsettings(schema):
    if Gio is None:
        return None
    if schema not in _SETTINGS:
        src = Gio.SettingsSchemaSource.get_default()
        _SETTINGS[schema] = Gio.Settings.new(schema) if src and src.lookup(schema, True) else None
    return _SETTINGS[schema]


def gset_state():
    out = {}
    if Gio is None:
        return out
    with _GLOCK:
        _pump()
        return _gset_read(out)


def _gset_read(out):
    for name, (schema, key, _t, _ok) in GSET.items():
        st = gsettings(schema)
        if st is not None and st.props.settings_schema.has_key(key):
            out[name] = st.get_value(key).unpack()
    return out


def gset_write(name, value):
    if Gio is None:
        return False
    with _GLOCK:
        _pump()
        return _gset_write(name, value)


def _gset_write(name, value):
    if name not in GSET or isinstance(value, (dict, list)):
        return False
    schema, key, typ, allowed = GSET[name]
    st = gsettings(schema)
    if st is None or not st.props.settings_schema.has_key(key):
        return False
    if allowed is None:
        if not isinstance(value, bool):
            return False
    else:
        match = [v for v in allowed if v == value and not isinstance(value, bool)]
        if not match:
            return False
        value = match[0]
    st.set_value(key, GLib.Variant(typ, value))
    Gio.Settings.sync()
    return True


# --- Stockage, applis, Windows ---------------------------------------------------------------
def human(n):
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024 or unit == "To":
            return f"{n:.0f} {unit}" if unit in ("o", "Ko") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


JOBS = {"apps": {"running": False, "result": ""}, "clean": {"running": False, "result": ""}}


def do_apps_update():
    code, _ = run("flatpak", "update", "-y", "--noninteractive", timeout=3600)
    JOBS["apps"].update(running=False, result="ok" if code == 0 else "error")
    spawn("notify-send", "-a", "Smoky OS", "-i", "system-software-update",
          "Applis à jour" if code == 0 else "Mise à jour des applis incomplète",
          "Spotify, Proton VPN et les autres applis sont à jour." if code == 0 else "Réessaie plus tard.")


CHROME_PROFILES = (".config/google-chrome", ".config/smoky-notes-chrome", ".config/smoky-center-chrome",
                   ".config/smoky-home-chrome")


def do_clean():
    """Corbeille, miniatures, caches de Chrome et moteurs Flatpak inutilisés (jamais tes fichiers)."""
    before = shutil.disk_usage(HOME).free
    run("gio", "trash", "--empty", timeout=120)
    shutil.rmtree(HOME / ".cache/thumbnails", ignore_errors=True)
    for d in CHROME_PROFILES:
        for sub in ("Default/Cache", "Default/Code Cache", "Default/GPUCache", "GrShaderCache", "ShaderCache"):
            shutil.rmtree(HOME / d / sub, ignore_errors=True)
    run("flatpak", "uninstall", "--unused", "-y", "--noninteractive", timeout=600)
    freed = max(0, shutil.disk_usage(HOME).free - before)
    JOBS["clean"].update(running=False, result=human(freed))
    spawn("notify-send", "-a", "Smoky OS", "-i", "user-trash", "Nettoyage terminé", f"{human(freed)} libérés.")


_WINDOWS = []


def windows_entry():
    if _WINDOWS:                                     # les entrées du firmware ne changent pas en cours de route
        return _WINDOWS[0]
    _, out = run("efibootmgr", timeout=5)
    m = re.search(r"^Boot([0-9A-Fa-f]{4})\*?\s+Windows Boot Manager", out, re.M)
    _WINDOWS.append(m.group(1) if m else None)
    return _WINDOWS[0]


_STORAGE = {"at": 0, "data": {}}


def storage():
    """Tailles des dossiers : coûteux, recalculé au plus toutes les 2 minutes."""
    du = shutil.disk_usage(HOME)
    if time.time() - _STORAGE["at"] > 120 or JOBS["clean"]["result"]:
        _STORAGE.update(at=time.time(), data={
            "trash": human(dir_size(HOME / ".local/share/Trash")),
            "cache": human(dir_size(HOME / ".cache") + sum(dir_size(HOME / d / "Default/Cache") for d in CHROME_PROFILES))})
    return {"total": human(du.total), "free": human(du.free),
            "used_pct": round(100 * (du.total - du.free) / du.total), **_STORAGE["data"]}


def sysinfo():
    mem = re.search(r"MemTotal:\s+(\d+)", read("/proc/meminfo"))
    up = float((read("/proc/uptime", "0").split() or ["0"])[0])
    temp = ""
    for z in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        if read(z / "type") in ("x86_pkg_temp", "TCPU", "acpitz"):
            t = read(z / "temp")
            if t.isdigit():
                temp = f"{int(t) // 1000} °C"
                break
    return {"kernel": os.uname().release.split("-")[0], "ram": human(int(mem.group(1)) * 1024) if mem else "?",
            "uptime": f"{int(up // 3600)} h {int(up % 3600 // 60):02d}", "temp": temp}


# --- État de la machine -------------------------------------------------------------------
_MOODLE = {"at": 0, "data": {"connected": False}}
_POOL = ThreadPoolExecutor(max_workers=8)


def moodle_status():
    """Lance Python + le trousseau : relu au plus toutes les 60 s (ou après une action Moodle)."""
    if time.time() - _MOODLE["at"] > 60:
        code, out = run("python3", f"{LIBEXEC}/smoky-moodle.py", "status", timeout=10)
        try:
            _MOODLE["data"] = json.loads(out) if code == 0 else {"connected": False}
        except ValueError:
            _MOODLE["data"] = {"connected": False}
        _MOODLE["at"] = time.time()
    return _MOODLE["data"]


def state():
    bat = "/sys/class/power_supply/BAT0"
    # les commandes lentes tournent en même temps : la page se met à jour bien plus vite
    jobs = {k: _POOL.submit(f) for k, f in {
        "gpu": lambda: run("supergfxctl", "-g")[1],
        "profile": lambda: run("powerprofilesctl", "get")[1],
        "conns": lambda: run("nmcli", "-t", "-f", "NAME", "connection", "show")[1],
        "active": lambda: run("nmcli", "-t", "-f", "NAME", "connection", "show", "--active")[1],
        "home": lambda: run("systemctl", "--user", "is-active", "smoky-home.service")[1],
        "moodle": moodle_status, "ostree": ostree_status, "windows": windows_entry,
        "g": gset_state, "storage": lambda: storage(),
    }.items()}
    r = {k: f.result() for k, f in jobs.items()}
    gpu, profile, conns, active, home_active, moodle = r["gpu"], r["profile"], r["conns"], r["active"], r["home"], r["moodle"]
    image, staged = r["ostree"]
    focus = jload(FOCUS, {"end": 0, "minutes": 0})
    if focus["end"] < time.time():
        focus = {"end": 0, "minutes": 0}
    pretty = re.search(r'^PRETTY_NAME="?([^"\n]*)', read("/etc/os-release"), re.M)
    return {
        "system": pretty.group(1) if pretty else "Smoky OS", "image": image, "update_staged": staged,
        "update": dict(UPDATE),
        "gpu": gpu or "?", "profile": profile or "?",
        "battery": {"capacity": read(f"{bat}/capacity", "?"), "status": read(f"{bat}/status", "?"),
                    "limit": read(f"{bat}/charge_control_end_threshold", "?")},
        "adaptive": jload(ADAPTIVE, ADAPTIVE_DEFAULTS),
        "home": {"token": HOME_TOKEN.exists(), "background": HOME_BG.exists(), "running": home_active == "active"},
        "moodle": moodle,
        "vpn": {"configured": VPN in conns.splitlines(), "active": VPN in active.splitlines()},
        "focus": focus,
        "g": r["g"],
        "jobs": {k: dict(v) for k, v in JOBS.items()},
        "windows": r["windows"] is not None,
        "info": sysinfo(),
        "storage": r["storage"],
    }


# --- Actions ---------------------------------------------------------------------------------
def act(a):
    kind = a.get("action")
    if kind == "gpu" and a.get("mode") in ("Integrated", "Hybrid"):
        code, out = run("supergfxctl", "-m", a["mode"], timeout=30)
        return {"ok": code == 0, "message": "Déconnecte-toi puis reconnecte-toi pour appliquer." if code == 0 else out}
    if kind == "charge_once":
        # 100 % pour un trajet ; smoky-adaptive remet la limite habituelle au débranchement
        prev = read("/sys/class/power_supply/BAT0/charge_control_end_threshold", "80")
        prev = prev if prev in ("60", "80") else "80"
        code, _ = run("asusctl", "-c", "100")
        if code != 0:
            code, _ = run("asusctl", "battery", "limit", "100")
        if code == 0:
            CFG.mkdir(parents=True, exist_ok=True)
            (CFG / "charge-once").write_text(prev)
        return {"ok": code == 0}
    if kind == "battery" and a.get("limit") in (60, 80, 100):
        (CFG / "charge-once").unlink(missing_ok=True)
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
        _MOODLE["at"] = 0
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
    if kind == "gset":
        ok = gset_write(str(a.get("name")), a.get("value"))
        return {"ok": True} if ok else {"ok": False, "message": "Réglage indisponible sur cette machine."}
    if kind in ("apps_update", "clean"):
        job = JOBS["apps" if kind == "apps_update" else "clean"]
        if not job["running"]:
            job.update(running=True, result="")
            threading.Thread(target=do_apps_update if kind == "apps_update" else do_clean, daemon=True).start()
        return {"ok": True}
    if kind == "windows":
        if not windows_entry():
            return {"ok": False, "message": "Windows introuvable sur ce PC."}
        code, out = run("systemctl", "start", "--no-block", "smoky-windows.service", timeout=20)
        return {"ok": True} if code == 0 else {"ok": False, "message": out or "Redémarrage refusé."}
    if kind == "update":
        if not UPDATE["running"]:
            UPDATE.update(running=True, result="")
            threading.Thread(target=do_update, daemon=True).start()
        return {"ok": True}
    if kind == "reboot":
        return {"ok": run("systemctl", "reboot")[0] == 0}
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
            data = data.replace(b"__SMOKY_TOKEN__", b"")
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
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    # fichier écrit seulement une fois le port obtenu (une 2e copie ne l'écrase pas)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, TOKEN.encode())
    os.close(fd)
    srv.serve_forever()
