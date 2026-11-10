#!/usr/bin/env python3
"""Tests des serveurs locaux des applis Smoky (Notes, Center, Mail, Agenda).

Chaque serveur est lancé pour de vrai, dans un dossier personnel jetable, puis interrogé
comme le ferait sa page. On vérifie :
  * la sécurité : en-tête Host, jeton, chemins qui sortent du dossier de l'appli ;
  * les données : ce qui est enregistré se relit tel quel, aux mêmes endroits.

  python3 tests/test_serveurs.py                    arbre du dépôt (system_files/)
  SMOKY_RACINE=/ python3 tests/test_serveurs.py     système installé ou image construite

Aucune action qui touche la machine (redémarrage, mise à jour, réseau) n'est appelée.
"""
import http.client
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

RACINE = Path(os.environ.get("SMOKY_RACINE") or Path(__file__).resolve().parent.parent / "system_files").resolve()
LIBEXEC = RACINE / "usr/libexec"
SHARE = RACINE / "usr/share"
# une image construite n'a ni session ni D-Bus : certaines commandes y répondent lentement
DELAI = float(os.environ.get("SMOKY_DELAI", "40"))

APPLIS = {
    "notes": {"script": LIBEXEC / "smokynotes/server.py", "prefixe": "SMOKYNOTES", "page": SHARE / "smokynotes",
              "jeton": "smoky-notes.token", "api": "/api/notebooks", "statique": "/css/app.css"},
    "center": {"script": LIBEXEC / "smokyos/smoky-center.py", "prefixe": "SMOKYCENTER", "page": SHARE / "smoky-center",
               "jeton": "smoky-center.token", "api": "/api/state", "statique": "/app.js"},
    "mail": {"script": LIBEXEC / "smokymail/server.py", "prefixe": "SMOKYMAIL", "page": SHARE / "smokymail",
             "jeton": "smoky-mail.token", "api": "/api/state", "statique": "/app.js", "alias": "/mail"},
    "agenda": {"script": LIBEXEC / "smokyagenda/server.py", "prefixe": "SMOKYAGENDA", "page": SHARE / "smokyagenda",
               "jeton": "smoky-agenda.token", "api": "/api/state", "statique": "/app.js", "alias": "/agenda"},
}


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Serveur:
    """Un serveur d'appli lancé dans un dossier personnel jetable."""

    def __init__(self, nom):
        self.nom, self.conf = nom, APPLIS[nom]
        self.port = port_libre()
        self.base = Path(tempfile.mkdtemp(prefix=f"smoky-test-{nom}-"))
        self.home = self.base / "home"
        self.run = self.base / "run"
        self.home.mkdir()
        self.run.mkdir(mode=0o700)
        p = self.conf["prefixe"]
        env = {**os.environ, "HOME": str(self.home), "XDG_RUNTIME_DIR": str(self.run),
               "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_DATA_HOME": str(self.home / ".local/share"),
               f"{p}_PORT": str(self.port), f"{p}_APP": str(self.conf["page"]),
               "SMOKYNOTES_NOTES": str(self.home / "Notes"),
               "SMOKYMAIL_DATA": str(self.home / ".local/share/smoky-mail"),
               "SMOKYAGENDA_DATA": str(self.home / ".local/share/smoky-agenda"),
               "SMOKYAGENDA_EXAMS": str(SHARE / "smokyagenda/examens"),
               "SMOKY_MATIERES": str(SHARE / "smokyos/matieres.json"),
               # chemin réduit : les tests n'appellent jamais Claude Code, même s'il est installé ici
               "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
               "PYTHONDONTWRITEBYTECODE": "1"}
        for cle in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "DBUS_SESSION_BUS_ADDRESS"):
            env.pop(cle, None)
        self.journal = open(self.base / "serveur.log", "wb")
        self.proc = subprocess.Popen([sys.executable, str(self.conf["script"])], env=env, cwd=str(self.base),
                                     stdin=subprocess.DEVNULL, stdout=self.journal, stderr=self.journal)
        fichier = self.run / self.conf["jeton"]
        fin = time.time() + 20
        while time.time() < fin:
            if self.proc.poll() is not None:
                break
            if fichier.is_file() and fichier.stat().st_size and self._ouvert():
                self.fichier_jeton = fichier
                self.jeton = fichier.read_text()
                return
            time.sleep(0.05)
        self.stop()
        raise RuntimeError(f"{nom} : le serveur n'a pas démarré\n" + (self.base / "serveur.log").read_text(errors="replace")
                           if (self.base / "serveur.log").exists() else f"{nom} : le serveur n'a pas démarré")

    def _ouvert(self):
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
            return True
        except OSError:
            return False

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.journal.close()
        shutil.rmtree(self.base, ignore_errors=True)

    def req(self, methode, chemin, corps=None, jeton=True, hote=True, entetes=None):
        """→ (code, en-têtes en minuscules, corps). jeton : True = le bon, None = aucun, texte = celui-là."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=DELAI)
        try:
            c.putrequest(methode, chemin, skip_host=True, skip_accept_encoding=True)
            if hote is True:
                c.putheader("Host", f"127.0.0.1:{self.port}")
            elif hote:
                c.putheader("Host", hote)
            if jeton is True:
                c.putheader("X-Smoky-Token", self.jeton)
            elif jeton:
                c.putheader("X-Smoky-Token", jeton)
            if isinstance(corps, (dict, list)):
                corps = json.dumps(corps).encode()
                c.putheader("Content-Type", "application/json")
            elif isinstance(corps, str):
                corps = corps.encode()
            if corps is not None:
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

    def action(self, **a):
        """POST /api/action (Center, Mail, Agenda) → réponse JSON."""
        code, rep = self.json("POST", "/api/action", a)
        assert code == 200, f"{self.nom} action {a.get('action')} → {code}"
        return rep


class Base(unittest.TestCase):
    APPLI = None
    srv = None

    @classmethod
    def setUpClass(cls):
        if cls.APPLI:
            cls.srv = Serveur(cls.APPLI)

    @classmethod
    def tearDownClass(cls):
        if cls.srv:
            cls.srv.stop()


class Commun:
    """Vérifications identiques pour les quatre applis (héritées ci-dessous)."""

    def test_page_accueil(self):
        code, h, corps = self.srv.req("GET", "/", jeton=None)
        self.assertEqual(code, 200)
        self.assertTrue(h["content-type"].startswith("text/html"))
        self.assertIn(b"<html", corps.lower())
        self.assertNotIn(b"__SMOKY_TOKEN__", corps)
        self.assertNotIn(self.srv.jeton.encode(), corps, "le jeton ne doit jamais être écrit dans la page")
        self.assertIn("frame-ancestors 'none'", h["content-security-policy"])
        self.assertIn("default-src 'self'", h["content-security-policy"])
        self.assertEqual(h["x-frame-options"], "DENY")
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["cache-control"], "no-store")
        self.assertNotIn("access-control-allow-origin", h, "aucune autorisation CORS ne doit être donnée")

    def test_alias_de_la_page(self):
        alias = self.srv.conf.get("alias")
        if not alias:
            self.skipTest("pas d'alias pour cette appli")
        for chemin in (alias, alias + "/"):
            code, h, corps = self.srv.req("GET", chemin, jeton=None)
            self.assertEqual(code, 200, chemin)
            self.assertIn(b"<html", corps.lower())

    def test_fichier_statique(self):
        code, h, corps = self.srv.req("GET", self.srv.conf["statique"], jeton=None)
        self.assertEqual(code, 200)
        self.assertTrue(corps)
        self.assertRegex(h["content-type"], r"^text/(javascript|css)")

    def test_hote_refuse(self):
        for hote in ("evil.example", f"evil.example:{self.srv.port}", "127.0.0.1", "127.0.0.1:1",
                     f"[::1]:{self.srv.port}", f"127.0.0.1:{self.srv.port}.evil.example", None):
            with self.subTest(hote=hote):
                self.assertEqual(self.srv.req("GET", "/", jeton=None, hote=hote)[0], 403)
                self.assertEqual(self.srv.req("GET", self.srv.conf["api"], hote=hote)[0], 403,
                                 "même avec le bon jeton, un autre hôte est refusé")

    def test_localhost_accepte(self):
        self.assertEqual(self.srv.req("GET", "/", jeton=None, hote=f"localhost:{self.srv.port}")[0], 200)

    def test_api_sans_jeton(self):
        api = self.srv.conf["api"]
        self.assertEqual(self.srv.req("GET", api, jeton=None)[0], 403)
        self.assertEqual(self.srv.req("GET", api, jeton="x" * 32)[0], 403)
        self.assertEqual(self.srv.req("GET", api, jeton=self.srv.jeton[:-1])[0], 403)
        self.assertEqual(self.srv.req("GET", api)[0], 200)

    def test_api_repond_en_json(self):
        code, h, corps = self.srv.req("GET", self.srv.conf["api"])
        self.assertEqual(code, 200)
        self.assertTrue(h["content-type"].startswith("application/json"))
        json.loads(corps)

    def test_chemins_hors_du_dossier(self):
        for chemin in ("/../../../../etc/passwd", "/%2e%2e/%2e%2e/%2e%2e/etc/passwd", "//etc/passwd",
                       "/..%2f..%2f..%2fetc/passwd", "/css/../../../../etc/hostname", "/inexistant.js"):
            with self.subTest(chemin=chemin):
                code, _h, corps = self.srv.req("GET", chemin, jeton=None)
                self.assertEqual(code, 404)
                self.assertNotIn(b"root:", corps)

    def test_fichier_du_jeton(self):
        f = self.srv.fichier_jeton
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600, "le jeton n'est lisible que par toi")
        self.assertGreaterEqual(len(self.srv.jeton), 24)

    def test_ecriture_sans_jeton(self):
        if self.srv.nom == "notes":
            for methode, chemin in (("PUT", "/api/notebooks/abc"), ("DELETE", "/api/notebooks/abc"),
                                    ("POST", "/api/duplicate/abc/def")):
                self.assertEqual(self.srv.req(methode, chemin, {"id": "abc"}, jeton=None)[0], 403, methode)
                self.assertEqual(self.srv.req(methode, chemin, {"id": "abc"}, hote="evil.example")[0], 403, methode)
        else:
            self.assertEqual(self.srv.req("POST", "/api/action", {"action": "x"}, jeton=None)[0], 403)
            self.assertEqual(self.srv.req("POST", "/api/action", {"action": "x"}, hote="evil.example")[0], 403)
            self.assertEqual(self.srv.req("POST", "/api/autre", {"action": "x"})[0], 403)

    def test_requete_illisible_et_action_inconnue(self):
        if self.srv.nom == "notes":
            self.assertEqual(self.srv.req("POST", "/api/inconnu")[0], 404)
            return
        self.assertEqual(self.srv.req("POST", "/api/action", "pas du json{")[0], 400)
        rep = self.srv.action(action="cette-action-n-existe-pas")
        self.assertIs(rep["ok"], False)
        self.assertEqual(rep["message"], "Action inconnue.")


class TestNotes(Commun, Base):
    APPLI = "notes"

    def carnet(self, nid, titre="Carnet de test"):
        return {"id": nid, "version": 1, "title": titre, "cover": "ink", "created": 1, "updated": 1,
                "favorite": False, "folder": "Tests", "defaults": {"size": "a4", "template": "grid", "paper": "white"},
                "pages": [{"id": "p1", "w": 595, "h": 842, "template": "grid", "paper": "white", "bg": None,
                           "items": [{"type": "stroke", "pts": [[1, 2, 0.5], [3, 4, 0.7]], "texte": "éàü ✓"}],
                           "marked": False}]}

    def dossier(self):
        return self.srv.home / "Notes" / "Smoky Notes"

    def test_carnets_des_matieres(self):
        matieres = [m["nom"] for m in json.loads((SHARE / "smokyos/matieres.json").read_text())["matieres"]]
        code, carnets = self.srv.json("GET", "/api/notebooks")
        self.assertEqual(code, 200)
        titres = {c["title"] for c in carnets}
        self.assertTrue(set(matieres) <= titres, f"un carnet par matière : {sorted(set(matieres) - titres)}")
        for c in carnets:
            if c["title"] in matieres:
                self.assertEqual(c["folder"], c["title"])
                self.assertEqual(c["pages"], 1)
        self.assertTrue((self.dossier() / ".matieres-1").exists())

    def test_enregistrer_et_relire(self):
        nb = self.carnet("ntest-enregistrer")
        code, rep = self.srv.json("PUT", "/api/notebooks/ntest-enregistrer", nb)
        self.assertEqual(code, 200)
        self.assertIs(rep["ok"], True)
        self.assertIsInstance(rep["updated"], int)
        code, relu = self.srv.json("GET", "/api/notebooks/ntest-enregistrer")
        self.assertEqual(code, 200)
        self.assertEqual(relu, {**nb, "updated": rep["updated"]})
        d = self.dossier() / "ntest-enregistrer"
        self.assertEqual(json.loads((d / "notebook.json").read_text()), relu)
        meta = json.loads((d / "meta.json").read_text())
        self.assertEqual(meta, {"id": nb["id"], "title": nb["title"], "cover": "ink", "created": 1,
                                "updated": rep["updated"], "favorite": False, "folder": "Tests", "pages": 1})
        self.assertIn(meta, self.srv.json("GET", "/api/notebooks")[1])
        self.assertFalse(list(d.glob(".*.tmp")), "pas de fichier temporaire oublié")

    def test_identifiants_refuses(self):
        self.assertEqual(self.srv.req("PUT", "/api/notebooks/ntest-a", self.carnet("ntest-b"))[0], 400)
        self.assertEqual(self.srv.req("PUT", "/api/notebooks/MAJUSCULE", self.carnet("MAJUSCULE"))[0], 400)
        self.assertEqual(self.srv.req("GET", "/api/notebooks/MAJUSCULE")[0], 400)
        self.assertEqual(self.srv.req("GET", "/api/notebooks/ninexistant")[0], 404)
        self.assertEqual(self.srv.req("PUT", "/api/notebooks/%2e%2e%2f%2e%2e%2fx", self.carnet("x"))[0], 404)
        self.assertEqual(self.srv.req("PUT", "/api/notebooks/ntest-json", "pas du json{")[0], 400)

    def test_fichiers_joints(self):
        self.srv.req("PUT", "/api/notebooks/ntest-joints", self.carnet("ntest-joints"))
        image = bytes(range(256)) * 20
        self.assertEqual(self.srv.req("PUT", "/api/assets/ntest-joints/img-1.png", image)[0], 200)
        code, h, corps = self.srv.req("GET", "/api/assets/ntest-joints/img-1.png")
        self.assertEqual((code, corps, h["content-type"]), (200, image, "image/png"))
        self.assertEqual((self.dossier() / "ntest-joints/assets/img-1.png").read_bytes(), image)
        self.assertEqual(self.srv.req("GET", "/api/assets/ntest-joints/absent.png")[0], 404)
        self.assertEqual(self.srv.req("PUT", "/api/assets/ntest-joints/script.sh", b"x")[0], 404)
        self.assertEqual(self.srv.req("PUT", "/api/assets/ntest-joints/..%2f..%2fevil.png", b"x")[0], 404)

    def test_export_pdf(self):
        code, rep = self.srv.json("PUT", "/api/export/" + quote("Cours d'algèbre.pdf"), b"%PDF-1.7 test")
        self.assertEqual(code, 200)
        dest = self.srv.home / "Notes" / "PDF" / "Cours d'algèbre.pdf"
        self.assertEqual(rep, {"ok": True, "path": str(dest)})
        self.assertEqual(dest.read_bytes(), b"%PDF-1.7 test")
        self.assertEqual(self.srv.req("PUT", "/api/export/..%2f..%2fevil.pdf", b"x")[0], 404)
        self.assertEqual(self.srv.req("PUT", "/api/export/evil.sh", b"x")[0], 404)
        self.srv.req("PUT", "/api/export/..cache.pdf", b"x")
        self.assertFalse((self.srv.home / "Notes" / "cache.pdf").exists())
        self.assertFalse(any(p.name.startswith(".") for p in (self.srv.home / "Notes" / "PDF").iterdir()))

    def test_dupliquer_puis_supprimer(self):
        self.srv.req("PUT", "/api/notebooks/ntest-source", self.carnet("ntest-source"))
        self.assertEqual(self.srv.req("POST", "/api/duplicate/ntest-source/ntest-copie")[0], 200)
        self.assertEqual(self.srv.req("POST", "/api/duplicate/ntest-source/ntest-copie")[0], 409)
        self.assertEqual(self.srv.req("POST", "/api/duplicate/ninexistant/ntest-copie2")[0], 409)
        self.assertEqual(self.srv.req("POST", "/api/duplicate/ntest-source/MAUVAIS")[0], 400)
        self.assertTrue((self.dossier() / "ntest-copie/notebook.json").is_file())
        self.assertEqual(self.srv.json("DELETE", "/api/notebooks/ntest-copie"), (200, {"ok": True}))
        self.assertFalse((self.dossier() / "ntest-copie").exists())
        corbeille = list((self.dossier() / ".corbeille").glob("ntest-copie-*"))
        self.assertEqual(len(corbeille), 1, "un carnet supprimé va à la corbeille, il n'est pas détruit")
        self.assertTrue((corbeille[0] / "notebook.json").is_file())
        self.assertEqual(self.srv.req("GET", "/api/notebooks/ntest-copie")[0], 404)
        self.assertEqual(self.srv.json("DELETE", "/api/notebooks/ninexistant"), (200, {"ok": True}))

    def test_echeances_moodle(self):
        self.assertEqual(self.srv.json("GET", "/api/deadlines"), (200, []))
        f = self.srv.home / ".local/share/smoky-moodle/echeances.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('[{"titre": "TP BDR"}]')
        self.assertEqual(self.srv.json("GET", "/api/deadlines"), (200, [{"titre": "TP BDR"}]))
        f.unlink()

    def test_head(self):
        code, h, corps = self.srv.req("HEAD", "/", jeton=None)
        self.assertEqual((code, corps), (200, b""))
        self.assertGreater(int(h["content-length"]), 100)

    def test_routes_inconnues(self):
        self.assertEqual(self.srv.req("GET", "/api/inconnu")[0], 404)
        self.assertEqual(self.srv.req("PUT", "/api/inconnu", b"x")[0], 404)
        self.assertEqual(self.srv.req("DELETE", "/api/inconnu")[0], 404)


class TestCenter(Commun, Base):
    APPLI = "center"

    def test_etat(self):
        code, etat = self.srv.json("GET", "/api/state")
        self.assertEqual(code, 200)
        for cle in ("system", "image", "update_staged", "update", "gpu", "profile", "battery", "adaptive", "home",
                    "moodle", "vpn", "focus", "g", "jobs", "windows", "backup", "secureboot", "info", "storage"):
            self.assertIn(cle, etat)
        self.assertEqual(set(etat["adaptive"]), {"refresh", "tablet_mode", "vpn_auto", "tablet_open_notes"})
        self.assertEqual(set(etat["battery"]), {"capacity", "status", "limit"})
        self.assertEqual(etat["focus"], {"end": 0, "minutes": 0})

    def test_reglages_adaptatifs(self):
        self.assertEqual(self.srv.action(action="adaptive", refresh=False, tablet_mode=True, inconnu=True, vpn_auto="oui"),
                         {"ok": True})
        f = self.srv.home / ".config/smoky/adaptive.json"
        self.assertEqual(json.loads(f.read_text()),
                         {"refresh": False, "tablet_mode": True, "vpn_auto": False, "tablet_open_notes": True})
        self.assertEqual(self.srv.json("GET", "/api/state")[1]["adaptive"]["tablet_mode"], True)
        self.srv.action(action="adaptive", refresh=True, tablet_mode=False)

    def test_jeton_smoky_home(self):
        rep = self.srv.action(action="home_token", token="trop court")
        self.assertIs(rep["ok"], False)
        rep = self.srv.action(action="home_token", token="a" * 30 + "; rm -rf")
        self.assertIs(rep["ok"], False)
        self.assertEqual(self.srv.action(action="home_token", token="  " + "Ab0._-" * 10 + "\n"), {"ok": True})
        f = self.srv.home / ".config/smoky-home/token"
        self.assertEqual(f.read_text(), "Ab0._-" * 10)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertIs(self.srv.json("GET", "/api/state")[1]["home"]["token"], True)

    def test_valeurs_refusees(self):
        for a in ({"action": "gpu", "mode": "Autre"}, {"action": "battery", "limit": 50},
                  {"action": "profile", "name": "turbo"}, {"action": "focus_start", "minutes": 1},
                  {"action": "focus_start", "minutes": "25"}, {"action": "vpn", "on": "oui"}):
            with self.subTest(a=a):
                self.assertEqual(self.srv.action(**a), {"ok": False, "message": "Action inconnue."})
        rep = self.srv.action(action="vpn_import", content="ceci n'est pas un fichier WireGuard")
        self.assertIs(rep["ok"], False)
        rep = self.srv.action(action="gset", name="reglage-inexistant", value=True)
        self.assertIs(rep["ok"], False)

    def test_corps_json_non_objet(self):
        self.assertEqual(self.srv.json("POST", "/api/action", "[1, 2, 3]"), (200, {"ok": False}))
        self.assertEqual(self.srv.req("GET", "/api/state")[0], 200, "le serveur répond toujours ensuite")


class TestMail(Commun, Base):
    APPLI = "mail"

    def test_etat(self):
        code, etat = self.srv.json("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(etat["accounts"], [])
        self.assertEqual(etat["mails"], [])
        self.assertEqual(set(etat["settings"]), {"claude", "model", "ms_client_id"})
        self.assertEqual(set(etat["categories"]), {"important", "cours", "perso", "achats", "newsletters",
                                                    "notifications", "indesirable"})
        for cle in ("claude_state", "ms_flow", "models", "last_sync", "status", "sort_status"):
            self.assertIn(cle, etat)

    def test_dossier_prive(self):
        d = self.srv.home / ".local/share/smoky-mail"
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)

    def test_identifiant_microsoft(self):
        self.assertIs(self.srv.action(action="ms_client_id", client_id="n'importe quoi")["ok"], False)
        cid = "1234ABCD-12ab-34cd-56ef-1234567890ab"
        self.assertEqual(self.srv.action(action="ms_client_id", client_id=f"  {cid} "), {"ok": True})
        self.assertEqual(self.srv.json("GET", "/api/state")[1]["settings"]["ms_client_id"], cid.lower())
        f = self.srv.home / ".local/share/smoky-mail/settings.json"
        self.assertEqual(json.loads(f.read_text())["ms_client_id"], cid.lower())
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)

    def test_cles_de_mail_refusees(self):
        for k in ("", "a12345678", "../../etc:1", "a1234567:abc", None):
            with self.subTest(k=k):
                for action in ("open", "trash", "archive"):
                    rep = self.srv.action(action=action, k=k)
                    self.assertEqual(rep, {"ok": False, "message": "mail inconnu"})
                rep = self.srv.action(action="recategorize", k=k, category="cours")
                self.assertEqual(rep, {"ok": False, "message": "mail inconnu"})
        self.assertEqual(self.srv.action(action="recategorize", k="a1234567:1", category="inconnue"),
                         {"ok": False, "message": "Action inconnue."})

    def test_corps_json_non_objet(self):
        self.assertEqual(self.srv.json("POST", "/api/action", "[1, 2, 3]"), (200, {"ok": False}))


class TestAgenda(Commun, Base):
    APPLI = "agenda"

    def etat(self, semaine=None):
        code, etat = self.srv.json("GET", "/api/state" + (f"?week={semaine}" if semaine is not None else ""))
        self.assertEqual(code, 200)
        return etat

    def test_etat(self):
        etat = self.etat()
        for cle in ("week_start", "today", "now", "settings", "fixed", "plan", "tasks", "planned_by", "types", "days",
                    "models", "claude", "edt_ok", "export", "edt_file", "edt_error", "exams", "report", "gym_last",
                    "gym_default"):
            self.assertIn(cle, etat)
        self.assertEqual(etat["today"], date.today().isoformat())
        lundi = date.today() - timedelta(days=date.today().weekday())
        self.assertEqual(etat["week_start"], lundi.isoformat())
        self.assertEqual(etat["days"][0], "lundi")
        self.assertEqual(etat["export"], str(self.srv.home / "Notes" / "Planning Smoky.ics"))

    def test_semaines(self):
        lundi = date.today() - timedelta(days=date.today().weekday())
        self.assertEqual(self.etat(1)["week_start"], (lundi + timedelta(days=7)).isoformat())
        self.assertEqual(self.etat(-2)["week_start"], (lundi - timedelta(days=14)).isoformat())
        self.assertEqual(self.etat("abc")["week_start"], lundi.isoformat())

    def test_taches(self):
        self.assertIs(self.srv.action(action="add_task", title="   ")["ok"], False)
        self.assertEqual(self.srv.action(action="add_task", title="Réviser le TD de BDR", minutes=45,
                                         due=(date.today() + timedelta(days=3)).isoformat()), {"ok": True})
        taches = [t for t in self.etat()["tasks"] if t["title"] == "Réviser le TD de BDR"]
        self.assertEqual(len(taches), 1)
        t = taches[0]
        self.assertEqual((t["minutes"], t["done"]), (45, False))
        self.assertTrue(t["due"].startswith((date.today() + timedelta(days=3)).isoformat()))
        self.assertEqual(self.srv.action(action="toggle", id=t["id"]), {"ok": True})
        self.assertIs([x for x in self.etat()["tasks"] if x["id"] == t["id"]][0]["done"], True)
        self.assertEqual(self.srv.action(action="delete", id=t["id"]), {"ok": True})
        self.assertFalse([x for x in self.etat()["tasks"] if x["id"] == t["id"]])
        f = self.srv.home / ".local/share/smoky-agenda/agenda.json"
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)

    def test_evenements_et_blocs(self):
        jour = date.today()
        debut = datetime(jour.year, jour.month, jour.day, 10, 0)
        ok = {"title": "Rendez-vous de test", "type": "perso", "where": "B12",
              "start": debut.isoformat(timespec="minutes"), "end": (debut + timedelta(hours=1)).isoformat(timespec="minutes")}
        self.assertEqual(self.srv.action(action="add_event", **ok), {"ok": True})
        fixes = [e for e in self.etat()["fixed"] if e.get("title") == "Rendez-vous de test"]
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["where"], "B12")
        self.assertIs(self.srv.action(action="add_event", **{**ok, "end": ok["start"]})["ok"], False)
        self.assertIs(self.srv.action(action="add_event", title="sans date")["ok"], False)
        self.assertEqual(self.srv.action(action="add_block", **{**ok, "title": "Bloc de test", "type": "revision"}),
                         {"ok": True})
        blocs = [b for b in self.etat()["plan"] if b["title"] == "Bloc de test"]
        self.assertEqual(len(blocs), 1)
        self.assertEqual((blocs[0]["type"], blocs[0]["done"]), ("revision", False))
        export = self.srv.home / "Notes" / "Planning Smoky.ics"
        self.assertIn("BEGIN:VCALENDAR", export.read_text())
        for x in fixes + blocs:
            self.srv.action(action="delete", id=x["id"])
        self.assertFalse([b for b in self.etat()["plan"] if b["title"] == "Bloc de test"])

    def test_reglages(self):
        avant = self.etat()["settings"]
        rep = self.srv.action(action="settings", values={"wake": "23:30", "sleep": "07:00"})
        self.assertIs(rep["ok"], False)
        self.assertEqual(self.etat()["settings"], avant, "un réglage refusé ne change rien")
        self.assertIs(self.srv.action(action="settings", values={"ics_url": "ftp://exemple.fr/edt.ics"})["ok"], False)
        self.assertEqual(self.srv.action(action="settings", values={"block_min": 45, "wake": "06:45", "inconnu": 1,
                                                                    "subjects": ["BDR", " MNA ", ""]}), {"ok": True})
        apres = self.etat()["settings"]
        self.assertEqual((apres["block_min"], apres["wake"], apres["subjects"]), (45, "06:45", ["BDR", "MNA"]))
        self.assertNotIn("inconnu", apres)
        self.srv.action(action="settings", values={"block_min": avant["block_min"], "wake": avant["wake"],
                                                   "subjects": avant["subjects"]})

    def test_import_ics(self):
        self.assertEqual(self.srv.action(action="import_ics", content="ceci n'est pas un calendrier"),
                         {"ok": False, "message": "Ce fichier n'est pas un calendrier .ics."})
        vide = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"
        self.assertEqual(self.srv.action(action="import_ics", content=vide),
                         {"ok": False, "message": "Aucun cours trouvé dans ce fichier."})
        jour = date.today() + timedelta(days=1)
        cours = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:test-1\r\n"
                 f"DTSTART:{jour:%Y%m%d}T080000\r\nDTEND:{jour:%Y%m%d}T100000\r\n"
                 "SUMMARY:Algèbre - CM\r\nLOCATION:Amphi A\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        self.assertEqual(self.srv.action(action="import_ics", content=cours), {"ok": True, "message": "1 cours importé"})
        self.assertIs(self.etat()["edt_file"], True)
        semaine = 0 if jour.weekday() != 0 else 1
        self.assertTrue([e for e in self.etat(semaine)["fixed"] if "Algèbre" in e.get("title", "")])
        self.assertEqual(self.srv.action(action="remove_ics"), {"ok": True, "message": "Fichier retiré"})
        self.assertIs(self.etat()["edt_file"], False)

    def test_seances_de_salle(self):
        rep = self.srv.action(action="gym_log", date=date.today().isoformat(), block="Pecs et bras",
                              entries=[{"exercise": "Développé décliné", "kg": "42.5", "reps": 8},
                                       {"exercise": "Spider curl", "kg": 9999, "reps": 8},
                                       {"exercise": "", "kg": 10, "reps": 8}])
        self.assertEqual(rep, {"ok": True, "message": "Séance notée"})
        self.assertEqual(self.etat()["gym_last"],
                         {"Développé décliné": {"kg": 42.5, "reps": 8, "date": date.today().isoformat()}})
        self.assertIs(self.srv.action(action="gym_log", date="pas-une-date")["ok"], False)

    def test_valeurs_refusees(self):
        self.assertEqual(self.srv.action(action="open_notes", subject="Matière inconnue"),
                         {"ok": False, "message": "Matière inconnue."})
        for minutes in (1, 999, "25"):
            self.assertEqual(self.srv.action(action="focus", minutes=minutes), {"ok": False, "message": "Action inconnue."})

    def test_corps_json_non_objet(self):
        self.assertEqual(self.srv.json("POST", "/api/action", "[1, 2, 3]"), (200, {"ok": False}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
