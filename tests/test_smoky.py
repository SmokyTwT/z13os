#!/usr/bin/env python3
"""Tests de l'appli Smoky : son serveur local, sa page, son lanceur.

Le serveur est lancé pour de vrai, dans un dossier personnel jetable, puis interrogé comme le
ferait sa page. Les commandes du système (asusctl, nmcli, systemctl, rpm-ostree, flatpak…)
sont remplacées par de fausses commandes qui notent ce qu'on leur demande : aucun test ne
touche la machine, et on voit exactement ce que chaque réglage lancerait.

On vérifie :
  * la sécurité : en-tête Host, code d'accès, requêtes venues d'une autre page, chemins qui
    sortent du dossier de l'appli, rien d'ouvert sur le réseau ;
  * les tâches : ce qui est enregistré se relit tel quel, même après un redémarrage ;
  * les réglages : chaque action lance la bonne commande, et refuse toute valeur imprévue ;
  * le remplacement de Smoky Center : mêmes commandes, mêmes fichiers que l'ancienne appli ;
  * la vie du serveur : il s'arrête tout seul quand plus aucune fenêtre n'existe ;
  * le lanceur (/usr/bin/smoky) et la page (aucun script en ligne, aucun fichier manquant).

  python3 tests/test_smoky.py                    arbre du dépôt (system_files/)
  SMOKY_RACINE=/ python3 tests/test_smoky.py     système installé ou image construite
"""
import http.client
import json
import os
import queue
import re
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
RACINE = Path(os.environ.get("SMOKY_RACINE") or Path(__file__).resolve().parent.parent / "system_files").resolve()
LANCER = RACINE / "usr/lib/smoky/lancer.py"
PAQUET = RACINE / "usr/lib/smoky/smoky"
PAGE = RACINE / "usr/share/smoky"
LIBEXEC = RACINE / "usr/libexec/smokyos"
LANCEUR = RACINE / "usr/bin/smoky"
ANCIEN_CENTER = LIBEXEC / "smoky-center.py"
# une image construite n'a ni session ni D-Bus : certaines commandes y répondent lentement
DELAI = float(os.environ.get("SMOKY_DELAI", "40"))

# --- Fausses commandes ---------------------------------------------------------------------------
# Un seul script, copié sous chaque nom. Il n'utilise que des commandes internes du shell (le PATH
# du serveur ne contient QUE ce dossier : une commande oubliée ici n'existe pas, elle ne peut donc
# pas partir vers la vraie machine).
FAUSSES = ("asusctl", "supergfxctl", "powerprofilesctl", "nmcli", "systemctl", "rpm-ostree", "flatpak", "gio",
           "efibootmgr", "mokutil", "notify-send", "systemd-run", "python3",
           "smoky-notes", "smoky-agenda", "smoky-mail", "smoky-home")
FAUSSE = r'''#!/bin/sh
# Fausse commande des tests de Smoky : note l'appel, répond ce qui est prévu, ne fait rien d'autre.
nom=${0##*/}
US=$(printf '\037')
ligne=$nom
for a in "$@"; do ligne="$ligne$US$a"; done
printf '%s\n' "$ligne" >> "$SMOKY_TEST_JOURNAL"
F=$SMOKY_TEST_FAUX
appel=$nom
[ $# -gt 0 ] && appel="$nom $*"
if [ -f "$F/attendre" ]; then
  while IFS= read -r motif; do
    case "$appel" in $motif) while [ ! -e "$F/continuer" ]; do /bin/sleep 0.05; done ;; esac
  done < "$F/attendre"
fi
if [ -f "$F/echecs" ]; then
  while IFS= read -r motif; do
    case "$appel" in $motif) echo "refus de la fausse commande"; exit 1 ;; esac
  done < "$F/echecs"
fi
case "$appel" in
  "supergfxctl -g") echo Integrated ;;
  "powerprofilesctl get") echo balanced ;;
  "nmcli -t -f NAME connection show") printf 'Box\nSmoky VPN\n' ;;
  "nmcli -t -f NAME connection show --active") echo Box ;;
  "nmcli connection import type wireguard file "*)
    for f in "$@"; do :; done            # dernier argument : le fichier à importer
    /usr/bin/stat -c %a "$f" > "$F/vpn-droits"
    while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$l"; done < "$f" > "$F/vpn-contenu" ;;
  "systemctl --user is-active smoky-home.service") echo inactive ;;
  "rpm-ostree status --json")
    if [ -e "$F/sans-maj" ]; then
      echo '{"deployments": [{"booted": true, "container-image-reference": "docker://exemple/smoky:essai"}]}'
    else
      echo '{"deployments": [{"staged": true}, {"booted": true, "container-image-reference": "docker://exemple/smoky:essai"}]}'
    fi ;;
  "efibootmgr") [ -e "$F/sans-windows" ] || printf 'BootCurrent: 0001\nBoot0001* Fedora\nBoot0003* Windows Boot Manager\n' ;;
  "mokutil --sb-state") echo "SecureBoot enabled" ;;
  python3\ *smoky-moodle.py\ status)
    if [ -e "$F/moodle-pause" ]; then echo '{"connected": true, "site": "Moodle d essai", "en_pause": true}'
    else echo '{"connected": true, "site": "Moodle d essai"}'; fi ;;
  python3\ *smoky-backup-status.py) echo '{"etat": "ok", "dernier": "hier"}' ;;
  python3\ -I\ *smokygpu.py\ etat) echo '{"mux": 1, "interface": "asus-armoury", "intel_auto": true}' ;;
esac
exit 0
'''
WIREGUARD = "[Interface]\nPrivateKey = cle-privee-d-essai\nAddress = 10.2.0.2/32\n\n[Peer]\nPublicKey = cle-publique\nEndpoint = 192.0.2.1:51820\n"


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_ouvert(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def attendre(condition, delai=10.0, pas=0.03):
    """Attend que condition() soit vraie ; → sa valeur (fausse si le délai est passé)."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        valeur = condition()
        if valeur:
            return valeur
        time.sleep(pas)
    return condition()


class Dossier:
    """Dossier personnel jetable + fausses commandes + journal de ce qu'elles ont reçu."""

    def __init__(self, prefixe="smoky-test-"):
        self.base = Path(tempfile.mkdtemp(prefix=prefixe))
        self.home, self.run, self.faux = self.base / "home", self.base / "run", self.base / "faux"
        self.home.mkdir()
        self.run.mkdir(mode=0o700)
        self.faux.mkdir()
        for nom in FAUSSES:
            (self.faux / nom).write_text(FAUSSE)
            (self.faux / nom).chmod(0o755)
        self.journal = self.base / "commandes.log"
        self.journal.touch()
        self.batterie = self.base / "batterie"
        self.batterie.mkdir()
        for nom, valeur in (("capacity", "76"), ("status", "Discharging"), ("charge_control_end_threshold", "80")):
            (self.batterie / nom).write_text(valeur + "\n")

    def env(self, fausses=True, **plus):
        env = {"HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.run),
               "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_DATA_HOME": str(self.home / ".local/share"),
               # fausses commandes seules, ou vraies commandes en lecture (état réel de la machine)
               "PATH": str(self.faux) if fausses else "/usr/bin:/bin:/usr/sbin:/sbin",
               "SMOKY_BIN": str(self.faux), "SMOKY_LIBEXEC": str(LIBEXEC), "SMOKY_BATTERIE": str(self.batterie),
               "SMOKY_TEST_JOURNAL": str(self.journal), "SMOKY_TEST_FAUX": str(self.faux),
               "GSETTINGS_BACKEND": "memory",          # les réglages GNOME restent dans la mémoire du serveur
               "SMOKY_MATIERES": str(RACINE / "usr/share/smokyos/matieres.json"),
               "SMOKY_MENAGE": str(LIBEXEC / "smoky-home-clean.py"),
               "TZ": "Europe/Paris", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        env.update({k: str(v) for k, v in plus.items()})
        return env

    # --- journal des fausses commandes ---
    def commandes(self):
        return [ligne.split("\x1f") for ligne in self.journal.read_text().splitlines() if ligne]

    def vider(self):
        open(self.journal, "w").close()

    def attendre_commandes(self, nombre, delai=10.0):
        attendre(lambda: len(self.commandes()) >= nombre, delai)
        time.sleep(0.15)                               # laisse une commande en trop se montrer
        return self.commandes()

    def regle(self, fichier, *motifs):
        """Écrit un fichier de consigne des fausses commandes (« echecs », « attendre »…)."""
        (self.faux / fichier).write_text("".join(m + "\n" for m in motifs))

    def oublier(self, *fichiers):
        for f in fichiers:
            (self.faux / f).unlink(missing_ok=True)

    def effacer(self):
        shutil.rmtree(self.base, ignore_errors=True)


class Serveur(Dossier):
    """Le serveur de Smoky, lancé dans un dossier personnel jetable."""

    def __init__(self, fausses=True, options=(), env=None, preparer=None, donnees=True, demarrer=True):
        super().__init__()
        self.port = port_libre()
        self.acces = self.run / "smoky/serveur.json"
        self.environnement = self.env(fausses, **(env or {}))
        if donnees:
            self.environnement["SMOKY_DONNEES"] = str(self.base / "donnees")
        self.options = list(options)
        self.proc = None
        if preparer:
            preparer(self)
        if demarrer:
            self.demarrer()

    def demarrer(self, doit_tenir=True):
        self.sortie = open(self.base / "serveur.log", "ab")
        self.proc = subprocess.Popen([sys.executable, "-I", "-B", str(LANCER), "--port", str(self.port), *self.options],
                                     env=self.environnement, cwd=str(self.base), stdin=subprocess.DEVNULL,
                                     stdout=self.sortie, stderr=self.sortie)
        if not doit_tenir:
            return
        if attendre(lambda: self.proc.poll() is not None or (self.acces.is_file() and self.acces.stat().st_size
                                                             and port_ouvert(self.port)), 20) and self.proc.poll() is None:
            self.jeton = json.loads(self.acces.read_text())["jeton"]
            return
        texte = self.texte_journal()
        self.stop()
        raise RuntimeError("le serveur de Smoky n'a pas démarré\n" + texte)

    def texte_journal(self):
        try:
            return (self.base / "serveur.log").read_text(errors="replace")
        except OSError:
            return ""

    def arreter(self, delai=8):
        """Arrêt propre (SIGTERM) → code de sortie."""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=delai)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.sortie.close()
        return self.proc.returncode if self.proc else None

    def stop(self):
        self.arreter()
        self.effacer()

    # --- requêtes ---
    def req(self, methode, chemin, corps=None, jeton=True, hote=True, entetes=None, delai=None):
        """→ (code, en-têtes en minuscules, corps). jeton : True = le bon, None = aucun, texte = celui-là."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=delai or DELAI)
        try:
            c.putrequest(methode, chemin, skip_host=True, skip_accept_encoding=True)
            if hote is True:
                c.putheader("Host", f"localhost:{self.port}")
            elif hote:
                c.putheader("Host", hote)
            if jeton is True:
                c.putheader("X-Smoky-Jeton", self.jeton)
            elif jeton:
                c.putheader("X-Smoky-Jeton", jeton)
            if isinstance(corps, (dict, list)):
                corps = json.dumps(corps).encode()
                c.putheader("Content-Type", "application/json")
            elif isinstance(corps, str):
                corps = corps.encode()
            if corps is not None and "Content-Length" not in (entetes or {}):
                c.putheader("Content-Length", str(len(corps)))
            for k, v in (entetes or {}).items():
                c.putheader(k, v)
            c.endheaders(corps)
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            c.close()

    def json(self, methode, chemin, corps=None, **kw):
        code, _h, data = self.req(methode, chemin, corps, **kw)
        return code, (json.loads(data) if data else None)

    def agir(self, action, **valeurs):
        """POST /api/systeme → (code, réponse)."""
        return self.json("POST", "/api/systeme", {"action": action, **valeurs})

    def etat(self):
        code, etat = self.json("GET", "/api/systeme")
        assert code == 200, f"GET /api/systeme → {code}"
        return etat


class Ecoute:
    """Une fenêtre de l'appli vue du serveur : la connexion /api/flux, lue en arrière-plan."""

    def __init__(self, srv, par_entete=False):
        self.evenements = queue.Queue()
        # connexion tenue à la main : il faut pouvoir la couper net, comme une fenêtre qu'on ferme
        self.s = socket.create_connection(("127.0.0.1", srv.port), timeout=30)
        chemin = "/api/flux" if par_entete else f"/api/flux?k={srv.jeton}"
        entetes = f"Host: localhost:{srv.port}\r\n" + (f"X-Smoky-Jeton: {srv.jeton}\r\n" if par_entete else "")
        self.s.sendall(f"GET {chemin} HTTP/1.1\r\n{entetes}\r\n".encode())
        self.f = self.s.makefile("rb")
        self.code = int(self.f.readline().split()[1])
        self.type = ""
        while (ligne := self.f.readline()) not in (b"\r\n", b"\n", b""):
            nom, _, valeur = ligne.decode("latin-1").partition(":")
            if nom.lower() == "content-type":
                self.type = valeur.strip()
        self.s.settimeout(None)
        self.fini = threading.Event()
        threading.Thread(target=self._lire, daemon=True).start()

    def _lire(self):
        nom, donnees = None, None
        try:
            while True:
                ligne = self.f.readline()
                if not ligne:
                    break
                ligne = ligne.decode("utf-8").rstrip("\n")
                if ligne.startswith("event: "):
                    nom = ligne[7:]
                elif ligne.startswith("data: "):
                    donnees = json.loads(ligne[6:])
                elif ligne == "" and nom:
                    self.evenements.put((nom, donnees))
                    nom, donnees = None, None
        except (OSError, ValueError):
            pass
        try:
            self.f.close()
        except OSError:
            pass
        self.fini.set()

    def attendre(self, nom, delai=10):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                recu = self.evenements.get(timeout=max(0.01, fin - time.monotonic()))
            except queue.Empty:
                break
            if recu[0] == nom:
                return recu[1]
        return None

    def fermer(self):
        try:
            self.s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.s.close()
        self.fini.wait(5)


class AvecServeur(unittest.TestCase):
    """Un serveur (à fausses commandes) partagé par les tests de la classe."""
    FAUSSES = True
    OPTIONS = ()
    srv = None

    @classmethod
    def setUpClass(cls):
        cls.srv = Serveur(fausses=cls.FAUSSES, options=cls.OPTIONS)

    @classmethod
    def tearDownClass(cls):
        if cls.srv:
            cls.srv.stop()

    def setUp(self):
        self.srv.oublier("echecs", "attendre", "continuer", "sans-maj", "sans-windows")
        self.srv.vider()

    def commandes_apres(self, nombre, delai=10):
        return self.srv.attendre_commandes(nombre, delai)

    def aucune_commande(self):
        time.sleep(0.2)
        self.assertEqual(self.srv.commandes(), [], "rien ne doit être lancé")


# =================================================================================================
class TestSecurite(AvecServeur):
    def test_page(self):
        for chemin in ("/", "/smoky"):
            code, h, corps = self.srv.req("GET", chemin, jeton=None)
            self.assertEqual(code, 200, chemin)
            self.assertTrue(h["content-type"].startswith("text/html"))
            self.assertIn(b"<html", corps.lower())
            self.assertNotIn(self.srv.jeton.encode(), corps, "le code d'accès ne doit jamais être écrit dans la page")
            csp = h["content-security-policy"]
            for regle in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
                          "frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'"):
                self.assertIn(regle, csp)
            # 'wasm-unsafe-eval' laisse seulement compiler du WebAssembly (les décodeurs d'images des PDF) :
            # jamais de texte transformé en code, jamais de script ni de style « en ligne »
            self.assertNotIn("unsafe", csp.replace("'wasm-unsafe-eval'", ""), "ni script ni style « en ligne »")
            self.assertNotRegex(csp, r"https?:|\*", "rien ne se charge depuis l'extérieur")
            self.assertEqual(h["x-frame-options"], "DENY")
            self.assertEqual(h["x-content-type-options"], "nosniff")
            self.assertEqual(h["referrer-policy"], "no-referrer")
            self.assertEqual(h["cross-origin-resource-policy"], "same-origin")
            self.assertNotIn("access-control-allow-origin", h, "aucune autorisation CORS ne doit être donnée")
            self.assertNotIn("set-cookie", h)

    def test_hote_refuse(self):
        p = self.srv.port
        for hote in ("evil.example", f"evil.example:{p}", "127.0.0.1", "localhost", "127.0.0.1:1", f"[::1]:{p}",
                     f"127.0.0.1:{p}.evil.example", f"localhost.evil.example:{p}", f"LOCALHOST:{p}", f"0.0.0.0:{p}", None):
            with self.subTest(hote=hote):
                self.assertEqual(self.srv.req("GET", "/", jeton=None, hote=hote)[0], 403)
                self.assertEqual(self.srv.req("GET", "/js/app.js", jeton=None, hote=hote)[0], 403)
                code, _h, corps = self.srv.req("GET", "/api/aujourdhui", hote=hote)
                self.assertEqual(code, 403, "même avec le bon code d'accès, un autre hôte est refusé")
                self.assertNotIn(b"taches", corps)

    def test_hotes_acceptes(self):
        for hote in (f"localhost:{self.srv.port}", f"127.0.0.1:{self.srv.port}"):
            self.assertEqual(self.srv.req("GET", "/", jeton=None, hote=hote)[0], 200, hote)
            self.assertEqual(self.srv.req("GET", "/api/aujourdhui", hote=hote)[0], 200, hote)

    def test_api_sans_code_d_acces(self):
        j = self.srv.jeton
        for mauvais in (None, "x" * 43, j[:-1], j + "x", j.upper() if j.upper() != j else j.lower(), "é" * 10, j + " x", f"{j},{j}"):
            with self.subTest(jeton=mauvais):
                for methode, chemin in (("GET", "/api/aujourdhui"), ("GET", "/api/systeme"), ("POST", "/api/taches"),
                                        ("POST", "/api/systeme"), ("DELETE", "/api/taches/1"), ("GET", "/api/flux"),
                                        ("POST", "/api/ouvrir"), ("GET", "/api/inconnu")):
                    code, _h, corps = self.srv.req(methode, chemin, {"action": "redemarrer"} if methode == "POST" else None,
                                                   jeton=mauvais)
                    self.assertEqual(code, 403, f"{methode} {chemin}")
                    self.assertEqual(json.loads(corps)["erreur"][:12], "Accès refusé")
        self.assertEqual(self.srv.req("GET", "/api/aujourdhui")[0], 200)
        self.aucune_commande()

    def test_code_dans_l_adresse_refuse_hors_flux(self):
        # seul /api/flux accepte le code dans l'adresse (EventSource ne sait pas envoyer d'en-tête)
        for methode, chemin in (("GET", "/api/aujourdhui"), ("GET", "/api/systeme"), ("POST", "/api/systeme"),
                                ("POST", "/api/flux"), ("DELETE", "/api/taches/1")):
            code = self.srv.req(methode, f"{chemin}?k={self.srv.jeton}", {"action": "redemarrer"} if methode == "POST" else None,
                                jeton=None)[0]
            self.assertEqual(code, 403, f"{methode} {chemin}")
        self.aucune_commande()

    def test_requete_venue_d_une_autre_page(self):
        p = self.srv.port
        refusees = ({"Origin": "http://evil.example"}, {"Origin": "null"}, {"Origin": f"https://localhost:{p}"},
                    {"Origin": f"http://localhost:{p + 1}"}, {"Origin": "http://localhost"}, {"Origin": ""},
                    {"Origin": f"http://localhost:{p}.evil.example"},
                    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                    {"Origin": f"http://localhost:{p}", "Sec-Fetch-Site": "cross-site"})
        for entetes in refusees:
            with self.subTest(entetes=entetes):
                self.assertEqual(self.srv.req("GET", "/api/aujourdhui", entetes=entetes)[0], 403)
                self.assertEqual(self.srv.req("POST", "/api/systeme", {"action": "redemarrer"}, entetes=entetes)[0], 403)
        for entetes in ({"Origin": f"http://localhost:{p}"}, {"Origin": f"http://127.0.0.1:{p}", "Sec-Fetch-Site": "same-origin"},
                        {"Sec-Fetch-Site": "none"}):
            with self.subTest(entetes=entetes):
                self.assertEqual(self.srv.req("GET", "/api/aujourdhui", entetes=entetes)[0], 200)
        self.aucune_commande()

    def test_options_refuse(self):
        for chemin in ("/", "/api/systeme"):
            code, h, _ = self.srv.req("OPTIONS", chemin, entetes={"Origin": "http://evil.example",
                                                                  "Access-Control-Request-Method": "POST",
                                                                  "Access-Control-Request-Headers": "x-smoky-jeton"})
            self.assertEqual(code, 403)
            self.assertFalse([n for n in h if n.startswith("access-control-")], "aucune autorisation CORS")

    def test_chemins_hors_du_dossier(self):
        for chemin in ("/../../../../etc/passwd", "/%2e%2e/%2e%2e/%2e%2e/etc/passwd", "//etc/passwd", "/etc/passwd",
                       "/..%2f..%2f..%2fetc/passwd", "/css/../../../../etc/hostname", "/css/%2e%2e/%2e%2e/index.html",
                       "/js/..%5c..%5cindex.html", "/.git/config", "/css/.cache", "/js/app.js%00.html", "/%00",
                       "/js/", "/js", "/css//smoky.css", "/inexistant.js", "/index.html/", "/%ff%fe",
                       "/js/app.js/../../../../../etc/passwd", "/smoky/../../etc/passwd"):
            with self.subTest(chemin=chemin):
                code, _h, corps = self.srv.req("GET", chemin, jeton=None)
                self.assertIn(code, (400, 404))
                self.assertNotIn(b"root:", corps)

    def test_liens_et_types_inattendus(self):
        """Un lien glissé dans le dossier de la page ne fait pas sortir du dossier ; un type de
        fichier imprévu (.py, .db, sans extension) n'est jamais servi."""
        page = Path(tempfile.mkdtemp(prefix="smoky-test-page-"))
        self.addCleanup(shutil.rmtree, page, True)
        dehors = Path(tempfile.mkdtemp(prefix="smoky-test-dehors-"))
        self.addCleanup(shutil.rmtree, dehors, True)
        (dehors / "secret.txt").write_text("secret hors du dossier")
        (page / "index.html").write_text("<!doctype html><html><body>essai</body></html>")
        (page / "ok.txt").write_text("servi")
        (page / "lien.txt").symlink_to(dehors / "secret.txt")
        (page / "dossier").symlink_to(dehors)
        (page / "interne.txt").symlink_to(page / "ok.txt")
        (page / "script.py").write_text("print(1)")
        (page / "base.db").write_text("x")
        (page / "sans-extension").write_text("x")
        (page / ".cache.txt").write_text("x")
        srv = Serveur(options=("--page", str(page)))
        self.addCleanup(srv.stop)
        self.assertEqual(srv.req("GET", "/ok.txt", jeton=None)[::2], (200, b"servi"))
        self.assertEqual(srv.req("GET", "/interne.txt", jeton=None)[::2], (200, b"servi"), "un lien qui reste dans le dossier est permis")
        for chemin in ("/lien.txt", "/dossier/secret.txt", "/script.py", "/base.db", "/sans-extension", "/.cache.txt"):
            with self.subTest(chemin=chemin):
                code, _h, corps = srv.req("GET", chemin, jeton=None)
                self.assertEqual(code, 404)
                self.assertNotIn(b"secret", corps)

    def test_fichiers_et_cache(self):
        code, h, corps = self.srv.req("GET", "/js/app.js", jeton=None)
        self.assertEqual(code, 200)
        self.assertTrue(h["content-type"].startswith("text/javascript"))
        self.assertEqual(corps, (PAGE / "js/app.js").read_bytes())
        self.assertEqual(h["cache-control"], "no-cache")
        code, h2, corps = self.srv.req("GET", "/js/app.js", jeton=None, entetes={"If-None-Match": h["etag"]})
        self.assertEqual((code, corps), (304, b""))
        self.assertEqual(self.srv.req("GET", "/js/app.js", jeton=None, entetes={"If-None-Match": '"autre"'})[0], 200)
        code, h, corps = self.srv.req("HEAD", "/css/smoky.css", jeton=None)
        self.assertEqual((code, corps), (200, b""))
        self.assertEqual(int(h["content-length"]), (PAGE / "css/smoky.css").stat().st_size)
        for methode in ("POST", "PUT", "DELETE"):
            self.assertEqual(self.srv.req(methode, "/js/app.js", "x", jeton=None)[0], 405, methode)

    def test_requetes_illisibles(self):
        self.assertEqual(self.srv.json("POST", "/api/taches", "pas du json{"), (400, {"erreur": "Requête illisible."}))
        for corps in ("[1, 2, 3]", '"texte"', "12", "null", b"\xff\xfe"):
            self.assertEqual(self.srv.req("POST", "/api/taches", corps)[0], 400, corps)
            self.assertEqual(self.srv.req("POST", "/api/systeme", corps)[0], 400, corps)
        self.assertEqual(self.srv.req("POST", "/api/taches", "{}", entetes={"Content-Length": "abc"})[0], 400)
        self.assertEqual(self.srv.req("POST", "/api/taches", "{}", entetes={"Content-Length": "-5"})[0], 413)
        self.assertEqual(self.srv.req("POST", "/api/taches", "{}", entetes={"Content-Length": "6000001"})[0], 413)
        self.assertEqual(self.srv.req("GET", "/api/inconnu")[0], 404)
        self.assertEqual(self.srv.req("PUT", "/api/taches", {})[0], 405)
        self.assertEqual(self.srv.req("DELETE", "/api/systeme")[0], 405)
        self.assertEqual(self.srv.req("GET", "/api/aujourdhui")[0], 200, "le serveur répond toujours ensuite")
        self.aucune_commande()

    def test_reponses_de_l_api(self):
        code, h, corps = self.srv.req("GET", "/api/aujourdhui")
        self.assertEqual(code, 200)
        self.assertTrue(h["content-type"].startswith("application/json"))
        self.assertEqual(h["cache-control"], "no-store")
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertNotIn("access-control-allow-origin", h)
        self.assertEqual(set(json.loads(corps)), {"taches", "journee", "maintenant", "systeme", "version"})

    def test_code_d_acces_et_dossiers(self):
        self.assertEqual(stat.S_IMODE(self.srv.acces.stat().st_mode), 0o600, "le code d'accès n'est lisible que par toi")
        self.assertEqual(stat.S_IMODE(self.srv.acces.parent.stat().st_mode), 0o700)
        acces = json.loads(self.srv.acces.read_text())
        self.assertEqual((acces["port"], acces["pid"]), (self.srv.port, self.srv.proc.pid))
        self.assertGreaterEqual(len(acces["jeton"]), 40)
        base = self.srv.base / "donnees/smoky.db"
        self.srv.json("POST", "/api/taches", {"titre": "pour que la mémoire soit écrite"})
        fichiers = sorted(base.parent.iterdir())
        self.assertIn(base, fichiers)
        for f in fichiers:                             # smoky.db et ses fichiers annexes (-wal, -shm)
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600, f"{f.name} : la mémoire de l'appli n'est lisible que par toi")
        self.assertEqual(stat.S_IMODE(base.parent.stat().st_mode), 0o700)
        self.assertNotIn(self.srv.jeton, self.srv.texte_journal(), "le code d'accès ne va pas dans le journal")

    def test_rien_sur_le_reseau(self):
        """Le serveur n'écoute que sur 127.0.0.1 : injoignable par une autre adresse de la machine."""
        ecoutes = set()
        for ligne in Path("/proc/net/tcp").read_text().splitlines()[1:] + (
                Path("/proc/net/tcp6").read_text().splitlines()[1:] if Path("/proc/net/tcp6").exists() else []):
            champs = ligne.split()
            adresse, port = champs[1].rsplit(":", 1)
            if champs[3] == "0A" and int(port, 16) == self.srv.port:          # 0A : en écoute
                ecoutes.add(adresse)
        self.assertEqual(ecoutes, {"0100007F"}, "une seule écoute, sur 127.0.0.1")

    def test_deux_codes_differents(self):
        autre = Serveur()
        self.addCleanup(autre.stop)
        self.assertNotEqual(autre.jeton, self.srv.jeton, "chaque lancement tire un nouveau code d'accès")
        self.assertEqual(self.srv.req("GET", "/api/aujourdhui", jeton=autre.jeton)[0], 403)


# =================================================================================================
class TestTaches(AvecServeur):
    def creer(self, **t):
        code, tache = self.srv.json("POST", "/api/taches", t)
        self.assertEqual(code, 201, tache)
        return tache

    def liste(self):
        return self.srv.json("GET", "/api/aujourdhui")[1]["taches"]

    def setUp(self):
        super().setUp()
        while taches := self.liste():                  # la liste ne montre que les 20 dernières tâches faites
            for t in taches:
                self.srv.req("DELETE", f"/api/taches/{t['id']}")

    def test_creer_relire_modifier_supprimer(self):
        t = self.creer(titre="  Réviser   l'électromagnétisme \n", echeance="2026-11-13")
        self.assertEqual(t, {"id": t["id"], "titre": "Réviser l'électromagnétisme", "faite": False, "echeance": "2026-11-13", "minutes": None})
        self.assertEqual(self.liste(), [t])
        code, t2 = self.srv.json("POST", f"/api/taches/{t['id']}", {"faite": True})
        self.assertEqual((code, t2["faite"]), (200, True))
        code, t3 = self.srv.json("POST", f"/api/taches/{t['id']}", {"titre": "Réviser MNA", "echeance": None})
        self.assertEqual(t3, {"id": t["id"], "titre": "Réviser MNA", "faite": True, "echeance": None, "minutes": None})
        self.assertEqual(self.liste(), [t3])
        self.assertEqual(self.srv.json("POST", f"/api/taches/{t['id']}", {"faite": False})[1]["faite"], False)
        self.assertEqual(self.srv.json("DELETE", f"/api/taches/{t['id']}"), (200, {}))
        self.assertEqual(self.liste(), [])
        self.assertEqual(self.srv.req("DELETE", f"/api/taches/{t['id']}")[0], 404)

    def test_ordre(self):
        sans = self.creer(titre="sans date")
        tard = self.creer(titre="plus tard", echeance="2027-01-10")
        tot = self.creer(titre="bientôt", echeance="2026-11-13")
        faite1 = self.creer(titre="faite en premier")
        faite2 = self.creer(titre="faite ensuite", echeance="2026-01-01")
        self.srv.json("POST", f"/api/taches/{faite1['id']}", {"faite": True})
        time.sleep(0.02)
        self.srv.json("POST", f"/api/taches/{faite2['id']}", {"faite": True})
        self.assertEqual([t["titre"] for t in self.liste()],
                         ["bientôt", "plus tard", "sans date", "faite ensuite", "faite en premier"],
                         "à faire : date la plus proche d'abord, sans date à la fin ; puis ce qui vient d'être fait")
        # corriger le titre d'une tâche déjà faite ne la fait pas remonter
        self.srv.json("POST", f"/api/taches/{faite1['id']}", {"titre": "faite en premier (corrigée)", "faite": True})
        self.assertEqual([t["titre"] for t in self.liste()][3:], ["faite ensuite", "faite en premier (corrigée)"])
        self.assertEqual({t["id"] for t in self.liste()}, {sans["id"], tard["id"], tot["id"], faite1["id"], faite2["id"]})

    def test_textes_gardes_tels_quels(self):
        for titre in ("'); DROP TABLE taches;--", '<script>alert(1)</script>', "été 🌫️ — 100 % « prêt »", "a" * 200,
                      "%s %d {0} \\n ${HOME} `id`", "عربى 日本語"):
            with self.subTest(titre=titre):
                self.assertEqual(self.creer(titre=titre)["titre"], titre)
        self.assertEqual(len(self.liste()), 6, "la table existe toujours")

    def test_valeurs_refusees(self):
        for corps in ({}, {"titre": ""}, {"titre": "   \n\t "}, {"titre": 12}, {"titre": None}, {"titre": ["a"]},
                      {"titre": "a" * 201}, {"titre": "ok", "echeance": "demain"}, {"titre": "ok", "echeance": "2026-02-30"},
                      {"titre": "ok", "echeance": "2026-13-01"}, {"titre": "ok", "echeance": "13/11/2026"},
                      {"titre": "ok", "echeance": 20261113}, {"titre": "ok", "echeance": "2026-11-13T10:00"},
                      {"titre": "ok", "echeance": "٢٠٢٦-١١-١٣"}):
            with self.subTest(corps=corps):
                code, rep = self.srv.json("POST", "/api/taches", corps)
                self.assertEqual(code, 400)
                self.assertTrue(rep["erreur"])
        self.assertEqual(self.liste(), [])
        t = self.creer(titre="valide")
        for corps in ({"faite": "oui"}, {"faite": 1}, {"faite": None}, {"titre": ""}, {"echeance": "hier"}):
            with self.subTest(corps=corps):
                self.assertEqual(self.srv.req("POST", f"/api/taches/{t['id']}", corps)[0], 400)
        self.assertEqual(self.liste(), [t], "une modification refusée ne change rien")
        for identifiant in ("0", "999999", "abc", "1.5", "-1", "1%20OR%201=1", "%27", "9" * 40, "9" * 19, f"0{t['id']}",
                            f"+{t['id']}", f"%20{t['id']}", f"{t['id']}%20", f"{t['id']}_0", "%D9%A1", f"{t['id']}.0"):
            with self.subTest(identifiant=identifiant):
                self.assertEqual(self.srv.req("POST", f"/api/taches/{identifiant}", {"faite": True})[0], 404)
                self.assertEqual(self.srv.req("DELETE", f"/api/taches/{identifiant}")[0], 404)
        self.assertEqual(self.liste(), [t])

    def test_les_autres_fenetres_sont_prevenues(self):
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        self.assertEqual(fenetre.attendre("bonjour"), {})
        t = self.creer(titre="vue ailleurs")
        self.assertEqual(fenetre.attendre("change"), {"quoi": "taches"}, "création annoncée")
        self.srv.json("POST", f"/api/taches/{t['id']}", {"faite": True})
        self.assertEqual(fenetre.attendre("change"), {"quoi": "taches"}, "modification annoncée")
        self.srv.req("DELETE", f"/api/taches/{t['id']}")
        self.assertEqual(fenetre.attendre("change"), {"quoi": "taches"}, "suppression annoncée")
        self.srv.req("POST", "/api/taches", {"titre": ""})
        self.assertIsNone(fenetre.attendre("change", delai=0.5), "une demande refusée n'annonce rien")

    def test_faites_limitees_aux_20_dernieres(self):
        for i in range(23):
            t = self.creer(titre=f"tâche {i:02d}")
            self.srv.json("POST", f"/api/taches/{t['id']}", {"faite": True})
        faites = self.liste()
        self.assertEqual(len(faites), 20)
        self.assertEqual(faites[0]["titre"], "tâche 22", "la dernière terminée en tête")

    def test_plusieurs_fenetres_a_la_fois(self):
        erreurs = []

        def travail(n):
            try:
                for i in range(15):
                    code, t = self.srv.json("POST", "/api/taches", {"titre": f"fenêtre {n} tâche {i}"})
                    assert code == 201, code
                    assert self.srv.req("POST", f"/api/taches/{t['id']}", {"faite": i % 2 == 0})[0] == 200
            except Exception as e:                    # noqa: BLE001 — tout échec compte
                erreurs.append(e)
        fils = [threading.Thread(target=travail, args=(n,)) for n in range(6)]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        self.assertEqual(erreurs, [])
        base = sqlite3.connect(self.srv.base / "donnees/smoky.db")
        self.addCleanup(base.close)
        self.assertEqual(base.execute("SELECT count(*), count(DISTINCT id) FROM taches").fetchone(), (90, 90))


class TestMemoire(unittest.TestCase):
    """La mémoire de l'appli (fichier SQLite) : emplacement, redémarrage, cas anormaux."""

    def test_les_taches_survivent_au_redemarrage(self):
        srv = Serveur()
        self.addCleanup(srv.stop)
        self.assertEqual(srv.json("POST", "/api/taches", {"titre": "garder ceci", "echeance": "2026-11-20"})[0], 201)
        self.assertEqual(srv.arreter(), 0, "arrêt propre")
        self.assertFalse(srv.acces.exists(), "le code d'accès est effacé à l'arrêt")
        ancien = srv.jeton
        srv.demarrer()
        self.assertNotEqual(srv.jeton, ancien)
        taches = srv.json("GET", "/api/aujourdhui")[1]["taches"]
        self.assertEqual([(t["titre"], t["echeance"], t["faite"]) for t in taches], [("garder ceci", "2026-11-20", False)])

    def test_emplacement_par_defaut(self):
        srv = Serveur(donnees=False)
        self.addCleanup(srv.stop)
        base = srv.home / ".local/share/smoky/smoky.db"
        self.assertTrue(base.is_file(), "sans réglage particulier : ~/.local/share/smoky/smoky.db")
        self.assertEqual(stat.S_IMODE(base.stat().st_mode), 0o600)
        lecture = sqlite3.connect(base)
        self.addCleanup(lecture.close)
        self.assertGreaterEqual(lecture.execute("PRAGMA user_version").fetchone()[0], 1)
        # rien d'autre n'est créé dans le dossier personnel au simple lancement
        crees = sorted(str(p.relative_to(srv.home)) for p in srv.home.rglob("*") if p.is_file())
        self.assertTrue(all(c.startswith(".local/share/smoky/smoky.db") for c in crees), crees)

    def test_les_anciennes_donnees_ne_sont_pas_touchees(self):
        """« Repartir de zéro » : la nouvelle appli ne lit ni ne modifie les données des anciennes."""
        def preparer(srv):
            for chemin in ("Notes/BDR/carnet.json", ".local/share/smoky-agenda/agenda.json", ".local/share/smoky-mail/mail.db",
                           ".config/smoky/adaptive.json", ".config/smoky-home/token"):
                f = srv.home / chemin
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('{"refresh": false}' if chemin.endswith("adaptive.json") else f"ancien contenu de {chemin}")
        srv = Serveur(donnees=False, preparer=preparer)
        self.addCleanup(srv.stop)
        avant = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in srv.home.rglob("*") if p.is_file() and "/smoky/smoky.db" not in str(p)}
        srv.json("POST", "/api/taches", {"titre": "nouvelle tâche"})
        srv.etat()
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in avant}, avant)

    def test_memoire_d_une_version_plus_recente(self):
        def preparer(srv):
            (srv.base / "donnees").mkdir()
            base = sqlite3.connect(srv.base / "donnees/smoky.db")
            base.execute("CREATE TABLE futur (x)")
            base.execute("PRAGMA user_version = 999")
            base.commit()
            base.close()
        srv = Serveur(preparer=preparer, demarrer=False)
        self.addCleanup(srv.stop)
        avant = (srv.base / "donnees/smoky.db").read_bytes()
        srv.demarrer(doit_tenir=False)
        self.assertEqual(srv.proc.wait(timeout=15), 1)
        srv.sortie.close()
        self.assertIn("démarrage impossible", srv.texte_journal())
        self.assertIn("version plus récente", srv.texte_journal())
        self.assertNotIn("Traceback", srv.texte_journal())
        self.assertEqual((srv.base / "donnees/smoky.db").read_bytes(), avant, "la mémoire n'est pas modifiée")
        self.assertFalse(port_ouvert(srv.port))

    def test_memoire_illisible(self):
        def preparer(srv):
            (srv.base / "donnees").mkdir()
            (srv.base / "donnees/smoky.db").write_bytes(b"ceci n'est pas une base SQLite, " * 200)
        srv = Serveur(preparer=preparer, demarrer=False)
        self.addCleanup(srv.stop)
        srv.demarrer(doit_tenir=False)
        self.assertEqual(srv.proc.wait(timeout=15), 1)
        srv.sortie.close()
        self.assertIn("démarrage impossible", srv.texte_journal())
        self.assertNotIn("Traceback", srv.texte_journal())
        self.assertTrue((srv.base / "donnees/smoky.db").read_bytes().startswith(b"ceci n'est pas"), "rien n'est effacé")

    def test_port_deja_pris(self):
        occupe = socket.socket()
        self.addCleanup(occupe.close)
        occupe.bind(("127.0.0.1", 0))
        occupe.listen(1)
        srv = Serveur(demarrer=False)
        self.addCleanup(srv.stop)
        srv.port = occupe.getsockname()[1]
        srv.demarrer(doit_tenir=False)
        self.assertEqual(srv.proc.wait(timeout=15), 1)
        srv.sortie.close()
        self.assertIn("démarrage impossible", srv.texte_journal())
        self.assertFalse(srv.acces.exists(), "pas de code d'accès écrit pour un serveur qui n'a pas démarré")

    def test_modules_pieges_dans_le_dossier_courant(self):
        """Un fichier random.py ou json.py posé là où l'appli est lancée ne doit pas être chargé."""
        def preparer(srv):
            for nom in ("random.py", "json.py", "queue.py", "smoky.py", "sqlite3.py"):
                (srv.base / nom).write_text('raise SystemExit("module piégé chargé")\n')
            (srv.home / "random.py").write_text('raise SystemExit("module piégé chargé")\n')
        srv = Serveur(preparer=preparer, env={"PYTHONPATH": "{base}"}, demarrer=False)
        srv.environnement["PYTHONPATH"] = f"{srv.base}:{srv.home}"
        self.addCleanup(srv.stop)
        srv.demarrer()
        self.assertEqual(srv.req("GET", "/api/aujourdhui")[0], 200)


# =================================================================================================
class TestSysteme(AvecServeur):
    """Chaque réglage lance la bonne commande, et rien d'autre."""

    def test_etat(self):
        etat = self.srv.etat()
        self.assertEqual(set(etat), {"image", "maj", "energie", "carte_graphique", "adaptatif", "maison", "cours", "vpn",
                                     "concentration", "gnome", "travaux", "windows", "sauvegarde", "demarrage_securise",
                                     "infos", "stockage"})
        self.assertEqual(etat["image"], "docker://exemple/smoky:essai")
        self.assertEqual(etat["maj"], {"prete": True, "en_cours": False, "resultat": ""})
        self.assertEqual(etat["energie"], {"niveau": "76", "etat": "Discharging", "limite": "80", "profil": "balanced"})
        self.assertEqual(etat["carte_graphique"], {"mode": "Integrated", "mux": {"mux": 1, "interface": "asus-armoury", "intel_auto": True}})
        self.assertEqual(etat["adaptatif"], {"refresh": True, "tablet_mode": False, "vpn_auto": False, "tablet_open_notes": True})
        self.assertEqual(etat["maison"], {"jeton": False, "arriere_plan": False, "active": False})
        self.assertEqual(etat["cours"], {"connected": True, "site": "Moodle d essai"})
        self.assertEqual(etat["vpn"], {"configure": True, "actif": False})
        self.assertEqual(etat["concentration"], {"end": 0, "minutes": 0})
        self.assertEqual(etat["travaux"], {"applis": {"en_cours": False, "resultat": ""}, "nettoyage": {"en_cours": False, "resultat": ""}})
        self.assertIs(etat["windows"], True)
        self.assertEqual(etat["sauvegarde"], {"etat": "ok", "dernier": "hier"})
        self.assertEqual(etat["demarrage_securise"], "on")
        self.assertEqual(set(etat["infos"]), {"systeme", "noyau", "memoire", "allume", "temperature"})
        self.assertEqual(set(etat["stockage"]), {"total", "libre", "utilise_pct", "corbeille", "cache"})
        self.assertTrue(0 <= etat["stockage"]["utilise_pct"] <= 100)
        # lire l'état ne lance que des lectures
        lues = {" ".join(c) for c in self.srv.commandes()}
        for commande in lues:
            self.assertRegex(commande, r"^(supergfxctl -g|powerprofilesctl get|nmcli -t -f NAME connection show( --active)?|"
                                       r"systemctl --user is-active smoky-home\.service|rpm-ostree status --json|efibootmgr|"
                                       r"mokutil --sb-state|python3 \S+/smoky-moodle\.py status|python3 \S+/smoky-backup-status\.py|"
                                       r"python3 -I \S+/smokygpu\.py etat)$")
        # résumé de la page Aujourd'hui : lecture de fichiers seulement
        self.srv.vider()
        self.assertEqual(self.srv.json("GET", "/api/aujourdhui")[1]["systeme"], {"niveau": "76", "etat": "Discharging", "maj_prete": True})
        self.aucune_commande()

    def test_actions_inconnues(self):
        for action in ("inconnue", "", None, 12, True, ["redemarrer"], {"a": 1}, "Redemarrer", "redemarrer ", "a.b", "a-b",
                       "_a_redemarrer", "__class__", "__init__", "agir", "etat", "image", "windows()", "mettre a jour",
                       "prevenir", "_limite_de_charge", "_nettoyer", "_mettre_a_jour", "_en_fond", "maj", "travaux",
                       "resume", "x" * 5000):
            with self.subTest(action=action):
                self.assertEqual(self.srv.json("POST", "/api/systeme", {"action": action}),
                                 (400, {"erreur": "Action inconnue."}))
        self.assertEqual(self.srv.json("POST", "/api/systeme", {}), (400, {"erreur": "Action inconnue."}))
        self.aucune_commande()

    def test_valeurs_refusees(self):
        refusees = [
            ("limite_de_charge", {"limite": 50}), ("limite_de_charge", {"limite": "80"}), ("limite_de_charge", {"limite": True}),
            ("limite_de_charge", {}), ("limite_de_charge", {"limite": 80.5}), ("limite_de_charge", {"limite": [80]}),
            ("limite_de_charge", {"limite": "80; reboot"}),
            ("profil", {"nom": "turbo"}), ("profil", {}), ("profil", {"nom": ["balanced"]}), ("profil", {"nom": "balanced; reboot"}),
            ("carte_graphique", {"mode": "Dedicated"}), ("carte_graphique", {"mode": "AsusMuxDgpu"}), ("carte_graphique", {"mode": "integrated"}),
            ("carte_graphique", {"mode": "Vfio"}), ("carte_graphique", {}),
            ("gnome", {"nom": "reglage-inexistant", "valeur": True}), ("gnome", {"nom": "night_light", "valeur": "oui"}),
            ("gnome", {"nom": "night_light", "valeur": 1}), ("gnome", {"nom": "night_light_temp", "valeur": 1000}),
            ("gnome", {"nom": "night_light_temp", "valeur": True}), ("gnome", {"nom": "text_scale", "valeur": 3.0}),
            ("gnome", {"nom": "sleep_ac", "valeur": "hibernate"}), ("gnome", {"nom": "idle_delay", "valeur": [300]}),
            ("gnome", {"nom": "idle_delay", "valeur": {"a": 1}}), ("gnome", {"valeur": True}), ("gnome", {"nom": "dock_size", "valeur": "52"}),
            ("gnome", {"nom": "org.gnome.desktop.interface", "valeur": True}),
            ("maison_jeton", {"jeton": "trop court"}), ("maison_jeton", {"jeton": "a" * 30 + "; rm -rf"}), ("maison_jeton", {}),
            ("maison_jeton", {"jeton": "a" * 601}), ("maison_jeton", {"jeton": "a" * 30 + "\nb"}), ("maison_jeton", {"jeton": "é" * 30}),
            ("maison_arriere_plan", {"actif": "oui"}), ("maison_arriere_plan", {"actif": 1}), ("maison_arriere_plan", {}),
            ("cours", {"quoi": "status"}), ("cours", {"quoi": "sync; reboot"}), ("cours", {}), ("cours", {"quoi": ["sync"]}),
            ("vpn_importer", {"contenu": "ceci n'est pas un fichier WireGuard"}), ("vpn_importer", {}),
            ("vpn_importer", {"contenu": "[Interface]\n"}), ("vpn_importer", {"contenu": WIREGUARD + "#" * 20000}),
            ("vpn", {"actif": "oui"}), ("vpn", {"actif": 1}), ("vpn", {}),
            ("concentration_debut", {"minutes": 4}), ("concentration_debut", {"minutes": 241}), ("concentration_debut", {"minutes": "25"}),
            ("concentration_debut", {"minutes": 25.5}), ("concentration_debut", {"minutes": True}), ("concentration_debut", {}),
            ("concentration_debut", {"minutes": -30}),
        ]
        for action, valeurs in refusees:
            with self.subTest(action=action, valeurs=str(valeurs)[:60]):
                code, rep = self.srv.agir(action, **valeurs)
                self.assertEqual(code, 400)
                self.assertTrue(rep["erreur"])
        self.aucune_commande()
        self.assertFalse((self.srv.home / ".config").exists(), "aucun fichier écrit par une demande refusée")

    def test_limite_de_charge(self):
        une_fois = self.srv.home / ".config/smoky/charge-once"
        une_fois.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.srv.home / ".config", True)
        une_fois.write_text("80")
        self.assertEqual(self.srv.agir("limite_de_charge", limite=60), (200, {"message": ""}))
        self.assertEqual(self.srv.commandes(), [["asusctl", "-c", "60"]])
        self.assertFalse(une_fois.exists(), "choisir une limite annule la « charge complète une fois »")
        # asusctl récent : la première écriture est refusée, la seconde passe
        self.srv.vider()
        self.srv.regle("echecs", "asusctl -c *")
        self.assertEqual(self.srv.agir("limite_de_charge", limite=100)[0], 200)
        self.assertEqual(self.srv.commandes(), [["asusctl", "-c", "100"], ["asusctl", "battery", "limit", "100"]])
        # asusctl ne répond pas du tout : on le dit
        self.srv.vider()
        self.srv.regle("echecs", "asusctl *")
        code, rep = self.srv.agir("limite_de_charge", limite=80)
        self.assertEqual(code, 502)
        self.assertIn("asusctl", rep["erreur"])

    def test_charge_complete_une_fois(self):
        self.addCleanup(shutil.rmtree, self.srv.home / ".config", True)
        code, rep = self.srv.agir("charge_complete_une_fois")
        self.assertEqual(code, 200)
        self.assertIn("80 %", rep["message"])
        self.assertEqual(self.srv.commandes(), [["asusctl", "-c", "100"]])
        self.assertEqual((self.srv.home / ".config/smoky/charge-once").read_text(), "80", "la limite d'avant est notée pour smoky-adaptive")
        # limite d'avant à 60 : c'est elle qui est notée ; à 100 (ou illisible) : 80
        for avant, notee in (("60", "60"), ("100", "80"), ("n'importe quoi", "80")):
            (self.srv.batterie / "charge_control_end_threshold").write_text(avant + "\n")
            self.srv.agir("charge_complete_une_fois")
            self.assertEqual((self.srv.home / ".config/smoky/charge-once").read_text(), notee, avant)
        (self.srv.batterie / "charge_control_end_threshold").write_text("80\n")
        # échec : rien n'est noté
        (self.srv.home / ".config/smoky/charge-once").unlink()
        self.srv.regle("echecs", "asusctl *")
        self.assertEqual(self.srv.agir("charge_complete_une_fois")[0], 502)
        self.assertFalse((self.srv.home / ".config/smoky/charge-once").exists())

    def test_profil_et_carte_graphique(self):
        for nom in ("power-saver", "balanced", "performance"):
            self.srv.vider()
            self.assertEqual(self.srv.agir("profil", nom=nom), (200, {"message": ""}))
            self.assertEqual(self.srv.commandes(), [["powerprofilesctl", "set", nom]])
        for mode in ("Integrated", "Hybrid"):
            self.srv.vider()
            code, rep = self.srv.agir("carte_graphique", mode=mode)
            self.assertEqual(code, 200)
            self.assertIn("session", rep["message"])
            self.assertEqual(self.srv.commandes(), [["supergfxctl", "-m", mode]])
        self.srv.regle("echecs", "powerprofilesctl *", "supergfxctl *")
        self.assertEqual(self.srv.agir("profil", nom="balanced")[0], 502)
        self.assertEqual(self.srv.agir("carte_graphique", mode="Hybrid"), (502, {"erreur": "refus de la fausse commande"}))

    def test_reglages_adaptatifs(self):
        self.addCleanup(shutil.rmtree, self.srv.home / ".config", True)
        self.assertEqual(self.srv.agir("adaptatif", refresh=False, tablet_mode=True, inconnu=True, vpn_auto="oui")[0], 200)
        f = self.srv.home / ".config/smoky/adaptive.json"
        self.assertEqual(json.loads(f.read_text()),
                         {"refresh": False, "tablet_mode": True, "vpn_auto": False, "tablet_open_notes": True},
                         "mêmes noms et mêmes clés qu'avant : le service smoky-adaptive lit ce fichier")
        self.assertEqual(self.srv.etat()["adaptatif"]["tablet_mode"], True)
        # un fichier abîmé ne bloque pas : valeurs par défaut
        f.write_text("{pas du json")
        self.assertEqual(self.srv.etat()["adaptatif"], {"refresh": True, "tablet_mode": False, "vpn_auto": False, "tablet_open_notes": True})
        f.write_text("[1, 2]")
        self.assertEqual(self.srv.agir("adaptatif", vpn_auto=True)[0], 200)
        self.assertEqual(json.loads(f.read_text())["vpn_auto"], True)
        self.srv.vider()
        self.aucune_commande()

    def test_reglages_gnome(self):
        disponibles = self.srv.etat()["gnome"]
        if "night_light" not in disponibles:            # réglage absent de cette machine : on le dit, sans rien casser
            code, rep = self.srv.agir("gnome", nom="night_light", valeur=True)
            self.assertEqual((code, rep["erreur"]), (502, "Réglage indisponible sur cette machine."))
        if not disponibles:
            self.skipTest("réglages GNOME absents ici (pas de GSettings pour ce Python) : écriture vérifiée dans l'image construite")
        essais = (("night_light", True), ("night_light_temp", 3500), ("text_scale", 1.25), ("idle_delay", 600),
                  ("sleep_battery", 1800), ("sleep_ac", "nothing"), ("lock_delay", 60), ("animations", False),
                  ("idle_delay", 0), ("text_scale", 1.0), ("text_scale", 1), ("night_light", False))
        for nom, valeur in essais:
            with self.subTest(nom=nom, valeur=valeur):
                if nom not in disponibles:
                    continue
                self.assertEqual(self.srv.agir("gnome", nom=nom, valeur=valeur), (200, {"message": ""}))
                self.assertEqual(self.srv.etat()["gnome"][nom], valeur)
        self.assertIn("text_scale", disponibles, "les réglages de base de GNOME doivent être là dès que GSettings existe")
        self.srv.vider()
        self.srv.agir("gnome", nom="animations", valeur=True)
        self.aucune_commande()

    def test_maison(self):
        self.addCleanup(shutil.rmtree, self.srv.home / ".config", True)
        jeton = "Ab0._-" * 10
        self.assertEqual(self.srv.agir("maison_jeton", jeton="  " + jeton + "\n"), (200, {"message": ""}))
        f = self.srv.home / ".config/smoky-home/token"
        self.assertEqual(f.read_text(), jeton)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        etat = self.srv.req("GET", "/api/systeme")[2]
        self.assertIs(json.loads(etat)["maison"]["jeton"], True)
        self.assertNotIn(jeton.encode(), etat, "le jeton de Smoky Home ne revient jamais vers la page")
        # un fichier laissé lisible par tous est refermé
        f.chmod(0o644)
        self.srv.agir("maison_jeton", jeton=jeton)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        # arrière-plan
        self.srv.vider()
        self.assertEqual(self.srv.agir("maison_arriere_plan", actif=True)[0], 200)
        auto = self.srv.home / ".config/autostart/smoky-home-bg.desktop"
        self.assertIn("Exec=systemctl --user start smoky-home.service", auto.read_text())
        self.assertEqual(self.commandes_apres(1), [["systemctl", "--user", "start", "smoky-home.service"]])
        self.assertIs(self.srv.etat()["maison"]["arriere_plan"], True)
        self.srv.vider()
        self.assertEqual(self.srv.agir("maison_arriere_plan", actif=False)[0], 200)
        self.assertFalse(auto.exists())
        self.assertEqual(self.commandes_apres(1), [["systemctl", "--user", "stop", "smoky-home.service"]])
        self.srv.vider()
        self.assertEqual(self.srv.agir("maison_ouvrir")[0], 200)
        self.assertEqual(self.commandes_apres(1), [["smoky-home"]])

    def test_cours_sauvegarde_logos(self):
        for quoi in ("connect", "sync", "disconnect"):
            self.srv.vider()
            self.assertEqual(self.srv.agir("cours", quoi=quoi)[0], 200)
            self.assertEqual(self.commandes_apres(1), [["python3", f"{LIBEXEC}/smoky-moodle.py", quoi]])
        self.srv.vider()
        self.assertEqual(self.srv.agir("sauvegarde_ouvrir")[0], 200)
        self.assertEqual(self.commandes_apres(1), [["flatpak", "run", "org.gnome.DejaDup"]])
        self.srv.vider()
        code, rep = self.srv.agir("logos")
        self.assertEqual((code, bool(rep["message"])), (200, True))
        self.assertEqual(self.commandes_apres(1), [["python3", f"{LIBEXEC}/smoky-autoicons.py"]])

    def test_vpn(self):
        self.addCleanup(shutil.rmtree, self.srv.home / ".config", True)
        self.assertEqual(self.srv.agir("vpn_importer", contenu=WIREGUARD), (200, {"message": ""}))
        fichier = str(self.srv.home / ".config/smoky/smokyvpn.conf")
        self.assertEqual(self.srv.commandes(), [
            ["nmcli", "connection", "delete", "id", "Smoky VPN"],
            ["nmcli", "connection", "import", "type", "wireguard", "file", fichier],
            ["nmcli", "connection", "modify", "smokyvpn", "connection.id", "Smoky VPN", "connection.autoconnect", "no"]])
        self.assertEqual((self.srv.faux / "vpn-droits").read_text().strip(), "600", "la clé privée n'est lisible que par toi")
        self.assertEqual((self.srv.faux / "vpn-contenu").read_text(), WIREGUARD)
        self.assertFalse(Path(fichier).exists(), "le fichier temporaire (clé privée) est effacé après l'import")
        # import refusé par NetworkManager : fichier effacé quand même, pas de renommage
        self.srv.vider()
        self.srv.regle("echecs", "nmcli connection import *")
        self.assertEqual(self.srv.agir("vpn_importer", contenu=WIREGUARD), (502, {"erreur": "refus de la fausse commande"}))
        self.assertFalse(Path(fichier).exists())
        self.assertEqual([c[2] for c in self.srv.commandes()], ["delete", "import"])
        self.srv.oublier("echecs")
        for actif, verbe in ((True, "up"), (False, "down")):
            self.srv.vider()
            self.assertEqual(self.srv.agir("vpn", actif=actif)[0], 200)
            self.assertEqual(self.srv.commandes(), [["nmcli", "connection", verbe, "id", "Smoky VPN"]])
        self.srv.regle("echecs", "nmcli connection up *")
        self.assertEqual(self.srv.agir("vpn", actif=True)[0], 502)

    def test_concentration(self):
        self.addCleanup(shutil.rmtree, self.srv.home / ".config", True)
        debut = time.time()
        self.assertEqual(self.srv.agir("concentration_debut", minutes=25), (200, {"message": ""}))
        commandes = self.commandes_apres(2)
        self.assertEqual(commandes[0], ["systemctl", "start", "--no-block", "smoky-focus@25.service"])
        self.assertEqual(commandes[1][:3], ["systemd-run", "--user", "--on-active=25m"])
        self.assertRegex(commandes[1][4], r"^smoky-focus-fin-\d+$")
        self.assertEqual(commandes[1][5], "notify-send")
        self.assertEqual(len(commandes), 2)
        f = self.srv.home / ".config/smoky/focus.json"
        note = json.loads(f.read_text())
        self.assertEqual(note["minutes"], 25, "mêmes clés qu'avant : smoky-focus et la barre du haut lisent ce fichier")
        self.assertAlmostEqual(note["end"], debut + 1500, delta=30)
        self.assertEqual(self.srv.etat()["concentration"]["minutes"], 25)
        self.srv.vider()
        self.assertEqual(self.srv.agir("concentration_fin")[0], 200)
        self.assertEqual(self.srv.commandes(), [["systemctl", "stop", "smoky-focus@25.service"]])
        self.assertFalse(f.exists())
        # démarrage refusé : rien n'est noté, pas de rappel programmé
        self.srv.vider()
        self.srv.regle("echecs", "systemctl start *")
        self.assertEqual(self.srv.agir("concentration_debut", minutes=50)[0], 502)
        self.assertFalse(f.exists())
        self.assertEqual(len(self.srv.attendre_commandes(1, 1)), 1)
        self.srv.oublier("echecs")
        # fichier abîmé ou trafiqué : aucune commande bizarre, le fichier est retiré
        for contenu in ('{"minutes": "25; reboot", "end": 9999999999}', '{"minutes": true}', '{"minutes": 100000}', "pas du json", "[25]"):
            f.write_text(contenu)
            self.srv.vider()
            self.assertEqual(self.srv.agir("concentration_fin")[0], 200, contenu)
            self.assertEqual(self.srv.commandes(), [], contenu)
            self.assertFalse(f.exists())
        # séance terminée (heure de fin passée) : l'état repart de zéro
        f.write_text(json.dumps({"end": time.time() - 5, "minutes": 25}))
        self.assertEqual(self.srv.etat()["concentration"], {"end": 0, "minutes": 0})
        f.write_text('{"end": "bientôt", "minutes": 25}')
        self.assertEqual(self.srv.etat()["concentration"], {"end": 0, "minutes": 0})

    def test_mises_a_jour_des_applis(self):
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        self.assertEqual(fenetre.attendre("bonjour"), {})
        self.srv.regle("attendre", "flatpak update *")
        self.assertEqual(self.srv.agir("applis_mettre_a_jour")[0], 200)
        self.assertEqual(self.commandes_apres(1), [["flatpak", "update", "-y", "--noninteractive"]])
        self.assertEqual(self.srv.etat()["travaux"]["applis"], {"en_cours": True, "resultat": ""})
        self.srv.vider()
        self.assertEqual(self.srv.agir("applis_mettre_a_jour")[0], 200)
        time.sleep(0.3)
        self.assertEqual([c for c in self.srv.commandes() if c[0] == "flatpak"], [], "un seul travail à la fois")
        (self.srv.faux / "continuer").touch()
        self.assertEqual(fenetre.attendre("change"), {"quoi": "systeme"}, "la page est prévenue quand le travail est fini")
        self.assertEqual(self.srv.etat()["travaux"]["applis"], {"en_cours": False, "resultat": "ok"})
        notif = [c for c in self.srv.attendre_commandes(1) if c[0] == "notify-send"]
        self.assertEqual(notif[0][5], "Applis à jour")
        # échec
        self.srv.vider()
        self.srv.regle("echecs", "flatpak update *")
        self.srv.agir("applis_mettre_a_jour")
        self.assertEqual(fenetre.attendre("change"), {"quoi": "systeme"})
        self.assertEqual(self.srv.etat()["travaux"]["applis"]["resultat"], "erreur")

    def test_nettoyage(self):
        h = self.srv.home
        self.addCleanup(lambda: [shutil.rmtree(h / d, True) for d in (".cache", ".config", "Documents", "Notes", ".local")])
        supprimes = (".cache/thumbnails/large/a.png", ".config/google-chrome/Default/Cache/x", ".config/google-chrome/Default/Code Cache/js/y",
                     ".config/google-chrome/Default/GPUCache/g", ".config/google-chrome/GrShaderCache/z", ".config/google-chrome/ShaderCache/s",
                     ".config/smoky-chrome/Default/Cache/x", ".config/smoky-notes-chrome/Default/GPUCache/g",
                     ".config/smoky-center-chrome/Default/Cache/c", ".config/smoky-home-chrome/Default/Code Cache/h")
        gardes = (".cache/autre/fichier", ".config/google-chrome/Default/Bookmarks", ".config/google-chrome/Default/Login Data",
                  ".config/google-chrome/Default/Cookies", ".config/smoky-chrome/Default/Preferences", "Documents/cours.pdf",
                  "Documents/dossier/examen.odt", "Notes/BDR/carnet.json", ".local/share/smoky-mail/mail.db",
                  ".config/smoky-home/token", ".config/smoky-mail-chrome/Default/Cache/pas-dans-la-liste")
        for chemin in supprimes + gardes:
            (h / chemin).parent.mkdir(parents=True, exist_ok=True)
            (h / chemin).write_text("x" * 100)
        # pièges : des liens vers tes documents, là où le nettoyage efface
        (h / ".cache/thumbnails/lien-vers-documents").symlink_to(h / "Documents")
        (h / ".config/smoky-notes-chrome/Default/Cache").symlink_to(h / "Documents")
        (h / ".config/smoky-home-chrome/GrShaderCache").symlink_to(h / "Notes")
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        self.assertEqual(self.srv.agir("nettoyer")[0], 200)
        self.assertEqual(fenetre.attendre("change"), {"quoi": "systeme"})
        for chemin in supprimes:
            self.assertFalse((h / chemin).exists(), f"aurait dû être effacé : {chemin}")
        for chemin in gardes:
            self.assertTrue((h / chemin).is_file(), f"ne devait PAS être effacé : {chemin}")
        commandes = self.srv.attendre_commandes(3)
        self.assertEqual(commandes[:2], [["gio", "trash", "--empty"], ["flatpak", "uninstall", "--unused", "-y", "--noninteractive"]])
        self.assertEqual(commandes[2][5], "Nettoyage terminé")
        resultat = self.srv.etat()["travaux"]["nettoyage"]
        self.assertIs(resultat["en_cours"], False)
        self.assertRegex(resultat["resultat"], r"^\d+(,\d)? (o|Ko|Mo|Go|To)$")

    def test_mise_a_jour_du_systeme(self):
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        self.assertEqual(self.srv.agir("mettre_a_jour")[0], 200)
        self.assertEqual(fenetre.attendre("change"), {"quoi": "systeme"})
        commandes = self.srv.attendre_commandes(3)
        self.assertEqual(commandes[:2], [["rpm-ostree", "upgrade"], ["rpm-ostree", "status", "--json"]])
        self.assertEqual(commandes[2][5], "Mise à jour prête")
        self.assertEqual(self.srv.etat()["maj"], {"prete": True, "en_cours": False, "resultat": "prete"})
        # rien de nouveau : pas de notification
        self.srv.vider()
        (self.srv.faux / "sans-maj").touch()
        self.srv.agir("mettre_a_jour")
        self.assertEqual(fenetre.attendre("change"), {"quoi": "systeme"})
        self.assertEqual(self.srv.etat()["maj"], {"prete": False, "en_cours": False, "resultat": "a_jour"})
        self.assertEqual([c for c in self.srv.attendre_commandes(2, 1) if c[0] == "notify-send"], [])
        self.assertIs(self.srv.json("GET", "/api/aujourdhui")[1]["systeme"]["maj_prete"], False)
        # téléchargement raté
        self.srv.vider()
        self.srv.regle("echecs", "rpm-ostree upgrade")
        self.srv.agir("mettre_a_jour")
        self.assertEqual(fenetre.attendre("change"), {"quoi": "systeme"})
        self.assertEqual(self.srv.etat()["maj"]["resultat"], "erreur")
        self.assertEqual([c[5] for c in self.srv.attendre_commandes(2) if c[0] == "notify-send"], ["Mise à jour impossible"])

    def test_redemarrages(self):
        self.assertEqual(self.srv.agir("redemarrer"), (200, {"message": ""}))
        self.assertEqual(self.srv.commandes(), [["systemctl", "reboot"]])
        self.srv.vider()
        self.assertEqual(self.srv.agir("uefi")[0], 200)
        self.assertEqual(self.srv.commandes(), [["systemctl", "start", "--no-block", "smoky-firmware.service"]])
        self.srv.vider()
        self.assertEqual(self.srv.agir("windows")[0], 200)
        self.assertEqual([c for c in self.srv.commandes() if c[0] != "efibootmgr"], [["systemctl", "start", "smoky-windows.service"]],
                         "Windows se choisit par le service prévu (GRUB), jamais par une écriture dans le firmware")
        self.srv.vider()
        self.srv.regle("echecs", "systemctl *")
        self.assertEqual(self.srv.agir("redemarrer")[0], 502)
        self.assertEqual(self.srv.agir("uefi")[0], 502)
        code, rep = self.srv.agir("windows")
        self.assertEqual(code, 502)
        self.assertIn("Windows Boot Manager", rep["erreur"], "en cas de refus, on explique comment faire à la main")
        for commande in self.srv.commandes():
            self.assertNotIn(commande[0], ("efibootmgr",), "l'entrée Windows n'est lue qu'une fois")

    def test_windows_absent(self):
        srv = Serveur(preparer=lambda s: (s.faux / "sans-windows").touch())
        self.addCleanup(srv.stop)
        self.assertIs(srv.etat()["windows"], False)
        srv.vider()
        self.assertEqual(srv.agir("windows"), (404, {"erreur": "Windows introuvable sur ce PC."}))
        self.assertEqual(srv.commandes(), [])

    def test_ouvrir_les_anciennes_applis(self):
        for quoi, programme in (("notes", "smoky-notes"), ("mail", "smoky-mail"), ("maison", "smoky-home")):
            self.srv.vider()
            self.assertEqual(self.srv.json("POST", "/api/ouvrir", {"quoi": quoi}), (200, {}))
            self.assertEqual(self.commandes_apres(1), [[programme]])
        self.srv.vider()
        # l'agenda est refait dans Smoky : l'ancien ne s'ouvre plus depuis l'appli
        for quoi in ("agenda", "center", "../../bin/sh", "", None, 3, ["notes"], {"a": 1}, "notes ", "smoky-notes", "/usr/bin/smoky-notes"):
            with self.subTest(quoi=quoi):
                self.assertEqual(self.srv.json("POST", "/api/ouvrir", {"quoi": quoi}), (400, {"erreur": "Appli inconnue."}))
        self.aucune_commande()


class TestSystemeSansOutils(unittest.TestCase):
    def test_etat_sans_aucune_commande(self):
        """PC sans asusctl, supergfxctl, etc. (ou commandes en panne) : la page s'affiche quand même."""
        def preparer(srv):
            for nom in FAUSSES:
                (srv.faux / nom).unlink()
            shutil.rmtree(srv.batterie)
        srv = Serveur(preparer=preparer)
        self.addCleanup(srv.stop)
        etat = srv.etat()
        self.assertEqual(etat["energie"], {"niveau": "?", "etat": "?", "limite": "?", "profil": "?"})
        self.assertEqual(etat["carte_graphique"], {"mode": "?", "mux": {}})
        self.assertEqual((etat["image"], etat["maj"]["prete"], etat["windows"], etat["demarrage_securise"]), ("", False, False, ""))
        self.assertEqual((etat["cours"], etat["vpn"], etat["sauvegarde"]), ({"connected": False}, {"configure": False, "actif": False}, {}))
        self.assertEqual(srv.json("GET", "/api/aujourdhui")[1]["systeme"], {"niveau": "", "etat": "", "maj_prete": False})
        self.assertEqual(srv.agir("profil", nom="balanced")[0], 502)
        self.assertEqual(srv.agir("windows")[0], 404)

    def test_reponses_inattendues_des_commandes(self):
        """Des commandes qui répondent n'importe quoi ne font pas tomber la page."""
        def preparer(srv):
            for nom, sortie in (("rpm-ostree", '[1, 2, 3]'), ("python3", '"texte"'), ("nmcli", "\x00\xff"), ("efibootmgr", "Boot00ZZ* Windows Boot Manager"),
                                ("mokutil", ""), ("supergfxctl", "x" * 100000)):
                (srv.faux / nom).write_text("#!/bin/sh\nprintf '%s\\n' '" + sortie + "'\n")
        srv = Serveur(preparer=preparer)
        self.addCleanup(srv.stop)
        etat = srv.etat()
        self.assertEqual((etat["image"], etat["maj"]["prete"], etat["cours"], etat["sauvegarde"], etat["windows"]),
                         ("", False, {"connected": False}, {}, False))
        self.assertEqual(etat["carte_graphique"]["mux"], {})

    def test_etat_reel_de_la_machine(self):
        """Avec les vraies commandes (lecture seule) : l'état se lit sans erreur, ici comme dans l'image."""
        srv = Serveur(fausses=False, env={"SMOKY_BATTERIE": "/sys/class/power_supply/BAT0"})
        self.addCleanup(srv.stop)
        code, etat = srv.json("GET", "/api/systeme")
        self.assertEqual(code, 200)
        self.assertEqual(len(etat), 16)
        self.assertIsInstance(etat["gnome"], dict)
        self.assertEqual(set(etat["carte_graphique"]["mux"]) - {"mux", "interface", "nvidia_coupee", "intel_auto", "windows_ultimate",
                                                                "essais", "probleme", "dernier_basculement"}, set())
        if os.environ.get("SMOKY_RACINE") == "/":
            # dans l'image : Python du système, GSettings et les schémas GNOME sont là
            self.assertGreaterEqual(len(etat["gnome"]), 15, "réglages GNOME lisibles dans l'image")
            for nom in ("night_light", "text_scale", "idle_delay", "animations", "sleep_ac"):
                self.assertIn(nom, etat["gnome"])
            self.assertIn("intel_auto", etat["carte_graphique"]["mux"])

    def test_carte_graphique_mode_ultimate(self):
        """L'état de l'aiguillage graphique vient du vrai smokygpu.py, qui ne fait que lire."""
        faux = Path(tempfile.mkdtemp(prefix="smoky-test-gpu-"))
        self.addCleanup(shutil.rmtree, faux, True)
        mux = faux / "sys/class/firmware-attributes/asus-armoury/attributes/gpu_mux_mode/current_value"
        mux.parent.mkdir(parents=True)
        mux.write_text("0\n")
        memoire = faux / "gpu.json"
        memoire.write_text(json.dumps({"windows_ultimate": True, "essais": 2, "probleme": "Deux essais ratés."}))
        avant = (mux.stat().st_mtime_ns, memoire.stat().st_mtime_ns)
        srv = Serveur(fausses=False, env={"SMOKY_GPU_SYS": faux / "sys", "SMOKY_GPU_ETAT": memoire, "SMOKY_GPU_CONF": faux / "gpu.conf"})
        self.addCleanup(srv.stop)
        self.assertEqual(srv.etat()["carte_graphique"]["mux"],
                         {"mux": 0, "interface": "asus-armoury", "nvidia_coupee": None, "intel_auto": True, "windows_ultimate": True,
                          "essais": 2, "probleme": "Deux essais ratés.", "dernier_basculement": None})
        self.assertEqual((mux.read_text(), mux.stat().st_mtime_ns, memoire.stat().st_mtime_ns), ("0\n", *avant),
                         "Smoky lit l'état, il ne modifie rien")


# =================================================================================================
class AncienCenter(Dossier):
    """L'ancien Smoky Center, lancé avec les mêmes fausses commandes (pour comparer)."""

    def __init__(self):
        super().__init__("smoky-test-ancien-")
        self.port = port_libre()
        env = self.env(True, SMOKYCENTER_PORT=self.port, SMOKYCENTER_APP=RACINE / "usr/share/smoky-center")
        self.sortie = open(self.base / "serveur.log", "wb")
        self.proc = subprocess.Popen([sys.executable, "-B", str(ANCIEN_CENTER)], env=env, cwd=str(self.base),
                                     stdin=subprocess.DEVNULL, stdout=self.sortie, stderr=self.sortie)
        fichier = self.run / "smoky-center.token"
        if not attendre(lambda: self.proc.poll() is not None or (fichier.is_file() and fichier.stat().st_size and port_ouvert(self.port)), 20) \
                or self.proc.poll() is not None:
            texte = (self.base / "serveur.log").read_text(errors="replace")
            self.stop()
            raise RuntimeError("l'ancien Smoky Center n'a pas démarré\n" + texte)
        self.jeton = fichier.read_text()

    def action(self, **a):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=DELAI)
        try:
            c.request("POST", "/api/action", json.dumps(a), {"Host": f"127.0.0.1:{self.port}", "X-Smoky-Token": self.jeton,
                                                             "Content-Type": "application/json"})
            r = c.getresponse()
            return json.loads(r.read())
        finally:
            c.close()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.sortie.close()
        self.effacer()


@unittest.skipUnless(ANCIEN_CENTER.is_file(), "l'ancien Smoky Center n'est plus là : comparaison sans objet")
class TestRemplaceSmokyCenter(unittest.TestCase):
    """La page Système remplace Smoky Center : pour chaque réglage, la nouvelle appli doit lancer
    exactement les mêmes commandes et écrire les mêmes fichiers que l'ancienne."""

    # (ancienne action, ses valeurs) ↔ (nouvelle action, ses valeurs)
    PAIRES = [
        (("battery", {"limit": 60}), ("limite_de_charge", {"limite": 60})),
        (("battery", {"limit": 100}), ("limite_de_charge", {"limite": 100})),
        (("charge_once", {}), ("charge_complete_une_fois", {})),
        (("battery", {"limit": 80}), ("limite_de_charge", {"limite": 80})),
        (("profile", {"name": "power-saver"}), ("profil", {"nom": "power-saver"})),
        (("profile", {"name": "performance"}), ("profil", {"nom": "performance"})),
        (("gpu", {"mode": "Hybrid"}), ("carte_graphique", {"mode": "Hybrid"})),
        (("gpu", {"mode": "Integrated"}), ("carte_graphique", {"mode": "Integrated"})),
        (("adaptive", {"refresh": False, "vpn_auto": True, "inconnu": 1}), ("adaptatif", {"refresh": False, "vpn_auto": True, "inconnu": 1})),
        (("home_token", {"token": "Ab0._-" * 10}), ("maison_jeton", {"jeton": "Ab0._-" * 10})),
        (("home_background", {"on": True}), ("maison_arriere_plan", {"actif": True})),
        (("home_background", {"on": False}), ("maison_arriere_plan", {"actif": False})),
        (("moodle_connect", {}), ("cours", {"quoi": "connect"})),
        (("moodle_sync", {}), ("cours", {"quoi": "sync"})),
        (("moodle_disconnect", {}), ("cours", {"quoi": "disconnect"})),
        (("vpn_import", {"content": WIREGUARD}), ("vpn_importer", {"contenu": WIREGUARD})),
        (("vpn", {"on": True}), ("vpn", {"actif": True})),
        (("vpn", {"on": False}), ("vpn", {"actif": False})),
        (("focus_start", {"minutes": 25}), ("concentration_debut", {"minutes": 25})),
        (("focus_stop", {}), ("concentration_fin", {})),
        (("focus_stop", {}), ("concentration_fin", {})),
        (("backup_open", {}), ("sauvegarde_ouvrir", {})),
        (("icons_regen", {}), ("logos", {})),
        (("apps_update", {}), ("applis_mettre_a_jour", {})),
        (("clean", {}), ("nettoyer", {})),
        (("update", {}), ("mettre_a_jour", {})),
        (("windows", {}), ("windows", {})),
        (("firmware", {}), ("uefi", {})),
        (("reboot", {}), ("redemarrer", {})),
    ]
    # refus : les deux doivent dire non, sans rien lancer
    REFUS = [
        (("battery", {"limit": 50}), ("limite_de_charge", {"limite": 50})),
        (("profile", {"name": "turbo"}), ("profil", {"nom": "turbo"})),
        (("gpu", {"mode": "AsusMuxDgpu"}), ("carte_graphique", {"mode": "AsusMuxDgpu"})),
        (("home_token", {"token": "trop court"}), ("maison_jeton", {"jeton": "trop court"})),
        (("vpn_import", {"content": "pas un fichier WireGuard"}), ("vpn_importer", {"contenu": "pas un fichier WireGuard"})),
        (("vpn", {"on": "oui"}), ("vpn", {"actif": "oui"})),
        (("focus_start", {"minutes": 1}), ("concentration_debut", {"minutes": 1})),
        (("focus_start", {"minutes": "25"}), ("concentration_debut", {"minutes": "25"})),
        (("gset", {"name": "inexistant", "value": True}), ("gnome", {"nom": "inexistant", "valeur": True})),
        (("inconnue", {}), ("inconnue", {})),
    ]

    def paire(self, tout_echoue=False):
        ancien, nouveau = AncienCenter(), Serveur()
        self.addCleanup(ancien.stop)
        self.addCleanup(nouveau.stop)
        for d in (ancien, nouveau):                    # même dossier personnel de départ
            for chemin in (".cache/thumbnails/a.png", ".config/google-chrome/Default/Cache/x", ".config/google-chrome/Default/Bookmarks",
                           ".config/smoky-notes-chrome/GrShaderCache/s", "Documents/cours.pdf", ".local/share/Trash/files/vieux"):
                (d.home / chemin).parent.mkdir(parents=True, exist_ok=True)
                (d.home / chemin).write_text("x" * 50)
            if tout_echoue:
                d.regle("echecs", "*")
        return ancien, nouveau

    @staticmethod
    def normaliser(d):
        """Commandes reçues, sans ce qui diffère par nature (dossier jetable, heure, texte des notifications)."""
        lignes = []
        for c in d.commandes():
            c = [a.replace(str(d.home), "~").replace(str(LIBEXEC), "LIBEXEC").replace("/usr/libexec/smokyos", "LIBEXEC") for a in c]
            c = [re.sub(r"^smoky-focus-fin-\d+$", "smoky-focus-fin-N", a) for a in c]
            if c[0] == "notify-send":                  # même icône et même titre ; le nom de l'appli et la phrase ont changé
                c = ["notify-send", c[4], c[5]]
            lignes.append(c)
        return lignes

    @staticmethod
    def fichiers(d):
        """Contenu du dossier personnel (hors mémoire propre à chaque appli)."""
        arbre = {}
        for p in sorted(d.home.rglob("*")):
            relatif = str(p.relative_to(d.home))
            if p.is_symlink() or not p.is_file():
                continue
            contenu = p.read_text(errors="replace").replace(str(d.home), "~")
            if relatif == ".config/smoky/focus.json":
                contenu = json.loads(contenu)
                contenu["end"] = round(contenu["end"] / 60)        # même minute de fin
                contenu = json.dumps(contenu, sort_keys=True)
            elif relatif.endswith(".json"):
                contenu = json.dumps(json.loads(contenu), sort_keys=True)
            arbre[relatif] = (contenu, stat.S_IMODE(p.stat().st_mode))
        return arbre

    def stables(self, *dossiers, calme=0.3):
        """Attend que plus aucune commande n'arrive (travaux en arrière-plan compris)."""
        def compte():
            return [len(d.commandes()) for d in dossiers]
        avant, depuis = compte(), time.monotonic()
        fin = time.monotonic() + 15
        while time.monotonic() < fin and time.monotonic() - depuis < calme:
            time.sleep(0.03)
            if compte() != avant:
                avant, depuis = compte(), time.monotonic()

    def comparer(self, ancien, nouveau, paires, attendu=None):
        for (action_a, valeurs_a), (action_n, valeurs_n) in paires:
            with self.subTest(ancienne=action_a, nouvelle=action_n, valeurs=str(valeurs_n)[:50]):
                ancien.vider()
                nouveau.vider()
                rep_a = ancien.action(action=action_a, **valeurs_a)
                code_n, _rep_n = nouveau.agir(action_n, **valeurs_n)
                self.stables(ancien, nouveau)
                if self.normaliser(nouveau) != self.normaliser(ancien):     # machine lente : on laisse une seconde chance
                    self.stables(ancien, nouveau, calme=2.5)
                self.assertEqual(code_n == 200, rep_a.get("ok") is True, f"ancienne : {rep_a} ; nouvelle : {code_n}")
                if attendu is not None:
                    self.assertEqual(code_n == 200, attendu)
                self.assertEqual(self.normaliser(nouveau), self.normaliser(ancien), "mêmes commandes, dans le même ordre")
                self.assertEqual(self.fichiers(nouveau), self.fichiers(ancien), "mêmes fichiers dans le dossier personnel")

    def test_memes_commandes_et_memes_fichiers(self):
        ancien, nouveau = self.paire()
        self.comparer(ancien, nouveau, self.PAIRES, attendu=True)

    def test_memes_refus(self):
        ancien, nouveau = self.paire()
        self.comparer(ancien, nouveau, self.REFUS, attendu=False)
        self.assertEqual(nouveau.commandes(), [])

    def test_memes_reactions_quand_tout_echoue(self):
        ancien, nouveau = self.paire(tout_echoue=True)
        sans_commande = {"adaptive", "home_token", "home_background", "moodle_connect", "moodle_sync", "moodle_disconnect",
                         "focus_stop", "backup_open", "icons_regen", "apps_update", "clean", "update"}
        self.comparer(ancien, nouveau, [p for p in self.PAIRES if p[0][0] not in sans_commande])
        # ces actions-là répondent « d'accord » tout de suite (travail détaché ou en arrière-plan) : mêmes suites
        self.comparer(ancien, nouveau, [p for p in self.PAIRES if p[0][0] in sans_commande], attendu=True)

    def test_memes_reglages_gnome_acceptes(self):
        ancien, nouveau = self.paire()
        sys.path.insert(0, str(PAQUET.parent))
        try:
            from smoky.systeme import GNOME
        finally:
            sys.path.pop(0)
        candidats = (True, False, 0, 1, 60, 300, 600, 900, 1800, 2700, 3500, 44, 52, 1.0, 1.1, 1.25, 2.0, "suspend", "nothing",
                     "hibernate", "", None, [1], {"a": 1})
        differences = []
        for nom in [*GNOME, "inexistant", "org.gnome.desktop.interface"]:
            for valeur in candidats:
                rep_a = ancien.action(action="gset", name=nom, value=valeur)
                code_n, _ = nouveau.agir("gnome", nom=nom, valeur=valeur)
                if (code_n == 200) != (rep_a.get("ok") is True):
                    differences.append((nom, valeur, rep_a, code_n))
        self.assertEqual(differences, [], "un réglage accepté par l'une des applis et refusé par l'autre")
        self.assertEqual(nouveau.commandes(), [])


# =================================================================================================
class TestVieDuServeur(unittest.TestCase):
    """Le serveur ne tourne que tant qu'une fenêtre de l'appli existe (batterie)."""
    ARRET = "1.5"

    def serveur(self, *options):
        srv = Serveur(options=("--arret-auto", self.ARRET, *options))
        self.addCleanup(srv.stop)
        return srv

    def faux_navigateur(self, profil):
        """Un processus dont la ligne de commande ressemble à celle de Chrome ouvert sur l'appli."""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", f"--user-data-dir={profil}"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def test_s_arrete_sans_fenetre(self):
        srv = self.serveur()
        self.assertEqual(srv.proc.wait(timeout=10), 0)
        self.assertFalse(srv.acces.exists(), "le code d'accès est effacé")
        self.assertFalse(port_ouvert(srv.port))

    def test_reste_tant_qu_une_fenetre_ecoute(self):
        srv = self.serveur()
        fenetre = Ecoute(srv)
        self.assertEqual((fenetre.code, fenetre.type), (200, "text/event-stream; charset=utf-8"))
        self.assertEqual(fenetre.attendre("bonjour"), {})
        time.sleep(4)
        self.assertIsNone(srv.proc.poll(), "une fenêtre est ouverte : le serveur reste")
        self.assertEqual(srv.req("GET", "/api/aujourdhui")[0], 200)
        fenetre.fermer()
        debut = time.monotonic()
        self.assertEqual(srv.proc.wait(timeout=10), 0, "dernière fenêtre fermée : le serveur s'arrête")
        self.assertLess(time.monotonic() - debut, 4, "la fermeture d'une fenêtre est remarquée tout de suite")

    def test_reste_tant_que_le_navigateur_tourne(self):
        """Chrome peut endormir une page et couper sa connexion : tant que Chrome tourne, on reste."""
        profil = Path(tempfile.mkdtemp(prefix="smoky-test-profil-"))
        self.addCleanup(shutil.rmtree, profil, True)
        navigateur = self.faux_navigateur(profil)
        srv = self.serveur("--profil", str(profil))
        time.sleep(4.5)
        self.assertIsNone(srv.proc.poll(), "le navigateur de l'appli tourne : le serveur reste")
        navigateur.kill()
        navigateur.wait()
        self.assertEqual(srv.proc.wait(timeout=10), 0, "navigateur fermé : le serveur s'arrête")

    def test_un_autre_navigateur_ne_compte_pas(self):
        profil = Path(tempfile.mkdtemp(prefix="smoky-test-profil-"))
        self.addCleanup(shutil.rmtree, profil, True)
        self.faux_navigateur(f"{profil}-autre")          # autre dossier, qui commence pareil
        self.faux_navigateur(profil.parent / "ailleurs")
        srv = self.serveur("--profil", str(profil))
        self.assertEqual(srv.proc.wait(timeout=10), 0)

    def test_sans_arret_auto_le_serveur_reste(self):
        srv = Serveur()
        self.addCleanup(srv.stop)
        time.sleep(2.5)
        self.assertIsNone(srv.proc.poll())

    def test_arret_demande(self):
        srv = Serveur()
        self.addCleanup(srv.stop)
        fenetre = Ecoute(srv, par_entete=True)
        self.addCleanup(fenetre.fermer)
        self.assertEqual(fenetre.attendre("bonjour"), {})
        srv.proc.send_signal(signal.SIGTERM)
        self.assertEqual(fenetre.attendre("arret"), {}, "les fenêtres ouvertes sont prévenues")
        self.assertEqual(srv.proc.wait(timeout=10), 0)
        self.assertFalse(srv.acces.exists())
        self.assertTrue(fenetre.fini.wait(5), "la connexion de la fenêtre est fermée")

    def test_beaucoup_de_fenetres_qui_vont_et_viennent(self):
        srv = self.serveur()
        permanente = Ecoute(srv)
        self.addCleanup(permanente.fermer)
        for _ in range(30):
            e = Ecoute(srv)
            self.assertEqual(e.code, 200)
            e.fermer()
        connexions = []
        for _ in range(25):                             # connexions ouvertes qui n'envoient rien
            s = socket.create_connection(("127.0.0.1", srv.port), timeout=2)
            connexions.append(s)
        self.assertEqual(srv.req("GET", "/api/aujourdhui")[0], 200, "le serveur répond toujours")
        for s in connexions:
            s.close()
        self.assertIsNone(srv.proc.poll())
        self.assertNotIn("Traceback", srv.texte_journal())


# =================================================================================================
NAVIGATEUR = r'''#!/bin/sh
# Faux Chrome des tests : note ses options ; la première fenêtre reste « ouverte » jusqu'à ce
# qu'on lui demande de se fermer, les suivantes rendent la main tout de suite (comme Chrome
# quand l'appli est déjà ouverte).
D=$SMOKY_TEST_FAUX
n=0
while [ -e "$D/navigateur-$n.log" ]; do n=$((n + 1)); done
for a in "$@"; do printf '%s\n' "$a"; done > "$D/navigateur-$n.tmp"
mv "$D/navigateur-$n.tmp" "$D/navigateur-$n.log"
if mkdir "$D/fenetre" 2>/dev/null; then
  while [ ! -e "$D/fermer" ]; do sleep 0.05; done
  rmdir "$D/fenetre"
fi
exit 0
'''


@unittest.skipUnless(shutil.which("pgrep") and Path("/usr/bin/python3").exists(), "pgrep ou /usr/bin/python3 absent")
class TestLanceur(unittest.TestCase):
    def setUp(self):
        self.d = Dossier("smoky-test-lanceur-")
        self.addCleanup(self.d.effacer)
        self.port = port_libre()
        navigateur = self.d.faux / "faux-chrome"
        navigateur.write_text(NAVIGATEUR)
        navigateur.chmod(0o755)
        (self.d.faux / "bin").mkdir()
        for nom in ("notify-send",):                   # seule fausse commande visible du lanceur
            shutil.copy(self.d.faux / nom, self.d.faux / "bin" / nom)
        self.env = self.d.env(False, SMOKY_PORT=self.port, SMOKY_NAVIGATEUR=navigateur, SMOKY_DONNEES=self.d.base / "donnees")
        self.env["PATH"] = f"{self.d.faux / 'bin'}:/usr/bin:/bin"
        self.lances = []
        self.addCleanup(self.tout_arreter)

    def tout_arreter(self):
        (self.d.faux / "fermer").touch()
        for p in self.lances:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        acces = self.d.run / "smoky/serveur.json"
        if acces.exists():
            try:
                os.kill(json.loads(acces.read_text())["pid"], signal.SIGTERM)
            except (OSError, ValueError, KeyError):
                pass

    def lancer(self, *args):
        with open(self.d.base / "lanceur.log", "ab") as sortie:
            p = subprocess.Popen(["bash", str(LANCEUR), *args], env=self.env, cwd=str(self.d.base), stdin=subprocess.DEVNULL,
                                 stdout=sortie, stderr=sortie)
        self.lances.append(p)
        return p

    def options(self, numero):
        f = self.d.faux / f"navigateur-{numero}.log"
        self.assertTrue(attendre(f.exists, 20), f"le navigateur n° {numero} n'a pas été lancé")
        return f.read_text().splitlines()

    def test_ouvre_la_fenetre_puis_arrete_le_serveur(self):
        premier = self.lancer()
        options = self.options(0)
        acces = json.loads((self.d.run / "smoky/serveur.json").read_text())
        self.assertEqual(acces["port"], self.port)
        self.assertIn(f"--app=http://localhost:{self.port}/smoky#k={acces['jeton']}", options)
        self.assertIn(f"--user-data-dir={self.d.home}/.config/smoky-chrome", options)
        for option in ("--class=smoky", "--ozone-platform-hint=auto", "--force-dark-mode", "--no-first-run"):
            self.assertIn(option, options)
        # le serveur répond, avec ce code d'accès
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/aujourdhui", headers={"Host": f"localhost:{self.port}", "X-Smoky-Jeton": acces["jeton"]})
        self.assertEqual(c.getresponse().status, 200)
        c.close()
        serveur = Path(f"/proc/{acces['pid']}/cmdline").read_bytes().split(b"\0")
        self.assertIn(b"-I", serveur, "Python isolé : ni dossier courant, ni modules du dossier personnel")
        self.assertIn(f"--profil={self.d.home}/.config/smoky-chrome".encode(), [b"=".join(serveur[i:i + 2]) for i in range(len(serveur) - 1)])
        # deuxième lancement, appli déjà ouverte : même serveur, même code, page demandée
        second = self.lancer("--aller", "/systeme/maison")
        options2 = self.options(1)
        self.assertIn(f"--app=http://localhost:{self.port}/smoky#k={acces['jeton']}&a=/systeme/maison", options2)
        self.assertEqual(second.wait(timeout=10), 0)
        self.assertTrue(port_ouvert(self.port), "le second lancement ne coupe pas le serveur du premier")
        self.assertIsNone(premier.poll())
        # fermeture de la fenêtre : le lanceur arrête le serveur qu'il avait démarré
        (self.d.faux / "fermer").touch()
        self.assertEqual(premier.wait(timeout=15), 0)
        self.assertTrue(attendre(lambda: not port_ouvert(self.port), 10), "serveur arrêté à la fermeture")
        self.assertTrue(attendre(lambda: not (self.d.run / "smoky/serveur.json").exists(), 5))
        self.assertEqual(self.d.commandes(), [], "aucune notification d'erreur")

    def test_page_demandee_invalide(self):
        for i, args in enumerate((("--aller", "/x&k=intrus"), ("--aller", "../../etc/passwd"), ("--aller", "/Systeme"),
                                  ("--aller", "/a" * 40), ("--aller",), ("--aller", "https://exemple.fr/"))):
            with self.subTest(args=args):
                p = self.lancer(*args)
                options = self.options(i)
                app = [o for o in options if o.startswith("--app=")]
                self.assertEqual(len(app), 1)
                self.assertRegex(app[0], rf"^--app=http://localhost:{self.port}/smoky#k=[\w-]+$", "la demande invalide est ignorée")
                for a in args:
                    self.assertNotIn(a, options, "rien de la demande invalide n'est transmis au navigateur")
                if i:
                    self.assertEqual(p.wait(timeout=10), 0)

    def test_options_transmises_au_navigateur(self):
        self.lancer("--aller", "/systeme", "--force-device-scale-factor=1.5")
        options = self.options(0)
        self.assertIn("--force-device-scale-factor=1.5", options)
        self.assertRegex([o for o in options if o.startswith("--app=")][0], r"&a=/systeme$")

    def test_serveur_qui_ne_demarre_pas(self):
        self.env["SMOKY_DONNEES"] = "/proc/dossier-impossible/smoky"
        debut = time.monotonic()
        p = self.lancer()
        self.assertEqual(p.wait(timeout=20), 1)
        self.assertLess(time.monotonic() - debut, 6, "le lanceur n'attend pas un serveur qui est déjà retombé")
        self.assertFalse((self.d.faux / "navigateur-0.log").exists(), "pas de fenêtre vide")
        notifs = self.d.attendre_commandes(1)
        self.assertEqual((notifs[0][0], notifs[0][5]), ("notify-send", "Smoky ne démarre pas"))

    def test_port_pris_par_autre_chose(self):
        occupe = socket.socket()
        self.addCleanup(occupe.close)
        occupe.bind(("127.0.0.1", self.port))
        occupe.listen(5)
        p = self.lancer()
        self.assertEqual(p.wait(timeout=20), 1)
        self.assertFalse((self.d.faux / "navigateur-0.log").exists())
        self.assertEqual(self.d.attendre_commandes(1)[0][5], "Smoky ne démarre pas")


# =================================================================================================
class TestPage(unittest.TestCase):
    """La page elle-même : rien d'« en ligne », rien d'extérieur, rien de manquant."""

    @classmethod
    def setUpClass(cls):
        # vendor/ : pdf.js et pdf-lib, bibliothèques tierces figées (vérifiées par tests/test_notes.py)
        cls.fichiers = sorted(p for p in PAGE.rglob("*") if p.is_file() and "vendor" not in p.relative_to(PAGE).parts)
        cls.js = [p for p in cls.fichiers if p.suffix == ".js"]
        cls.srv = Serveur()

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_tous_les_fichiers_sont_servis(self):
        types = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
                 ".woff2": "font/woff2", ".txt": "text/plain", ".png": "image/png", ".webp": "image/webp"}
        self.assertGreaterEqual(len(self.fichiers), 10)
        for p in self.fichiers:
            with self.subTest(fichier=str(p.relative_to(PAGE))):
                self.assertIn(p.suffix, types, "type de fichier que le serveur ne sait pas servir")
                code, h, corps = self.srv.req("GET", "/" + str(p.relative_to(PAGE)), jeton=None)
                self.assertEqual(code, 200)
                self.assertTrue(h["content-type"].startswith(types[p.suffix]))
                self.assertEqual(corps, p.read_bytes())

    def test_rien_en_ligne_dans_la_page(self):
        html = (PAGE / "index.html").read_text()
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)", "pas de script écrit dans la page (interdit par la CSP)")
        self.assertNotRegex(html, r"<style|\sstyle=", "pas de style écrit dans la page")
        self.assertNotRegex(html, r"\son[a-z]+\s*=", "pas de gestionnaire d'événement dans le HTML")
        self.assertNotRegex(html, r"javascript:", "pas d'adresse javascript:")
        for lien in re.findall(r'(?:src|href)="([^"]+)"', html):
            self.assertTrue(lien.startswith("/") and not lien.startswith("//"), lien)
            self.assertTrue((PAGE / lien.lstrip("/")).is_file(), f"fichier manquant : {lien}")

    def test_rien_ne_vient_de_l_exterieur(self):
        for p in self.fichiers:
            if p.suffix in (".jpg", ".png", ".webp", ".woff2") or p.name.endswith("LICENCE.txt") or p.name == "LISEZ-MOI.txt":
                continue
            texte = p.read_text().replace("http://www.w3.org/2000/svg", "")
            with self.subTest(fichier=p.name):
                self.assertNotRegex(texte, r"""(https?:)?//[a-z0-9.-]+\.[a-z]{2,}""", "aucune adresse extérieure dans la page")
                self.assertNotRegex(texte, r"@import", "pas de feuille de style importée")

    def test_javascript_sans_ecriture_dangereuse(self):
        for p in self.js:
            texte = p.read_text()
            with self.subTest(fichier=p.name):
                for interdit in (r"\binnerHTML\b", r"\bouterHTML\b", r"insertAdjacentHTML", r"document\.write", r"\beval\s*\(",
                                 r"new\s+Function", r"setTimeout\s*\(\s*[\"'`]", r"setInterval\s*\(\s*[\"'`]", r"\bsrcdoc\b",
                                 r"localStorage", r"document\.cookie"):
                    self.assertNotRegex(texte, interdit)

    def test_modules_et_images_existent(self):
        for p in self.js:
            for cible in re.findall(r'''(?:from\s+|import\s*\(\s*)["'](/[^"']+)["']''', p.read_text()):
                self.assertTrue((PAGE / cible.lstrip("/")).is_file(), f"{p.name} importe {cible}, absent")
        modules = re.findall(r'module:\s*"(/js/[a-z]+\.js)"', (PAGE / "js/app.js").read_text())
        self.assertGreaterEqual(len(modules), 2)
        for cible in modules:
            self.assertTrue((PAGE / cible.lstrip("/")).is_file(), f"page {cible} absente")
        for cible in re.findall(r'url\(\s*["\']?([^"\')]+)', (PAGE / "css/smoky.css").read_text()):
            self.assertTrue(cible.startswith("/") and (PAGE / cible.lstrip("/")).is_file(), f"smoky.css : {cible} absent")

    def test_la_page_et_le_serveur_parlent_des_memes_actions(self):
        # actions de /api/systeme (toutes les pages), de /api/agenda (page Agenda) et de /api/notes
        # (page Notes, js/notes.js et js/notes/) : listes fermées des deux côtés ; la page Agenda lance
        # aussi la concentration, une action du système
        agenda_js = (PAGE / "js/agenda.js").read_text()
        vers_systeme = set(re.findall(r'"/api/systeme",\s*\{\s*action:\s*"([a-z_]+)"', agenda_js))
        cote_page_agenda = set(re.findall(r'action:\s*"([a-z_]+)"', agenda_js)) - vers_systeme
        cote_page, cote_page_notes = set(vers_systeme), set()
        for p in self.js:
            actions = set(re.findall(r'action:\s*"([a-z_]+)"', p.read_text()))
            if p.name == "notes.js" or p.parent.name == "notes":
                self.assertNotIn("/api/systeme", p.read_text(), f"{p.name} : les Notes ne parlent qu'à /api/notes")
                cote_page_notes |= actions
            elif p.name != "agenda.js":
                cote_page |= actions
        for page_, fichier in ((cote_page, "systeme.py"), (cote_page_agenda, "agenda.py"), (cote_page_notes, "notes.py")):
            with self.subTest(serveur=fichier):
                cote_serveur = set(re.findall(r"def _a_([a-z_]+)\(", (PAQUET / fichier).read_text()))
                self.assertEqual(page_ - cote_serveur, set(), "la page demande une action que le serveur ne connaît pas")
                self.assertEqual(cote_serveur - page_, set(), "le serveur accepte une action que la page n'utilise pas")
                self.assertGreaterEqual(len(cote_serveur), 10)
        self.assertIn("concentration_debut", vers_systeme)
        # réglages GNOME : même liste des deux côtés
        sys.path.insert(0, str(PAQUET.parent))
        try:
            from smoky.systeme import GNOME
        finally:
            sys.path.pop(0)
        systeme_js = (PAGE / "js/systeme.js").read_text()
        cites = set(re.findall(r'"([a-z_]+)"', systeme_js)) & set(GNOME)
        self.assertEqual(set(GNOME) - cites, set(), "réglage GNOME accepté par le serveur mais absent de la page")

    def test_les_adresses_de_l_api_existent(self):
        routes = ("/api/aujourdhui", "/api/taches", "/api/systeme", "/api/agenda", "/api/notes", "/api/ouvrir", "/api/flux")
        for p in self.js:
            for adresse in re.findall(r'''["'`](/api/[a-z]+)''', p.read_text()):
                self.assertIn(adresse, routes, f"{p.name} appelle {adresse}")
        for route in routes[:5]:
            self.assertNotEqual(self.srv.req("GET", route)[0], 404, route)

    def test_police_et_licence(self):
        self.assertTrue((PAGE / "polices/comfortaa-LICENCE.txt").read_text().count("SIL OPEN FONT LICENSE") >= 1,
                        "la police Comfortaa est distribuée avec sa licence")
        self.assertEqual((PAGE / "polices/comfortaa.woff2").read_bytes()[:4], b"wOF2")

    def test_raccourci_et_icone(self):
        raccourci = (RACINE / "usr/share/applications/smoky.desktop").read_text()
        self.assertIn("Exec=/usr/bin/smoky\n", raccourci)
        # Chrome nomme la fenêtre d'après l'hôte et le chemin de la page : le serveur et le lanceur doivent s'y tenir
        self.assertIn("StartupWMClass=chrome-localhost__smoky-Default\n", raccourci)
        self.assertIn('--app="http://localhost:$PORT/smoky#', LANCEUR.read_text())
        icone = re.search(r"^Icon=(.+)$", raccourci, re.M).group(1)
        self.assertTrue((RACINE / f"usr/share/icons/hicolor/scalable/apps/{icone}.svg").is_file()
                        or list((RACINE / "usr/share/icons").rglob(f"{icone}.png")), f"icône {icone} absente")
        self.assertEqual(self.srv.req("GET", "/smoky", jeton=None)[0], 200)


if __name__ == "__main__":
    unittest.main(verbosity=1)
