#!/usr/bin/env python3
"""L'appli Smoky dans un vrai navigateur.

Chrome est lancé sans fenêtre et piloté comme le ferait une main sur le pavé tactile : on ouvre
l'appli, on ajoute une tâche, on la coche, on change un réglage. On vérifie à chaque fois ce que
la page affiche ET ce que le serveur a vraiment fait (tâche enregistrée, commande lancée).
Toute erreur dans la console du navigateur, tout fichier manquant, tout blocage par les règles
de sécurité de la page fait échouer le test.

Le serveur tourne dans un dossier personnel jetable, avec les fausses commandes de test_smoky.py.

  python3 tests/test_smoky_page.py                       arbre du dépôt
  SMOKY_RACINE=/ python3 tests/test_smoky_page.py        image construite (son propre Chrome)
  SMOKY_CAPTURES=dossier python3 tests/test_smoky_page.py   garde une image de chaque écran
"""
import base64
import fcntl
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
import urllib.parse
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_smoky import Serveur, attendre  # noqa: E402  (mêmes serveur jetable et fausses commandes)
from test_agenda import MAINTENANT, examens_ics, semaine_type  # noqa: E402  (mêmes emplois du temps d'essai)

CAPTURES = os.environ.get("SMOKY_CAPTURES")


def trouver_chrome():
    candidats = [os.environ.get("SMOKY_CHROME"),
                 "/usr/lib/google/chrome/chrome",          # Smoky OS (Chrome y est déplacé)
                 "/opt/google/chrome/chrome",
                 shutil.which("google-chrome-stable"), shutil.which("google-chrome"),
                 shutil.which("chromium"), shutil.which("chromium-browser"),
                 *sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"), reverse=True),
                 *sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")), reverse=True)]
    for c in candidats:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


CHROME = trouver_chrome()


class ErreurNavigateur(Exception):
    pass


class Navigateur:
    """Chrome sans fenêtre, piloté par son protocole de débogage à travers deux tubes : aucun
    port n'est ouvert, même en local."""

    def __init__(self, binaire, dossier, taille=(1280, 800)):
        self.dossier = Path(dossier)
        vers_r, vers_w = os.pipe()                      # nos ordres → Chrome (qui les lit sur son descripteur 3)
        de_r, de_w = os.pipe()                          # Chrome → nous (il écrit sur son descripteur 4)
        a = fcntl.fcntl(vers_r, fcntl.F_DUPFD, 20)
        b = fcntl.fcntl(de_w, fcntl.F_DUPFD, 20)
        self.journal = open(self.dossier / "chrome.log", "wb")
        env = {**os.environ, "HOME": str(self.dossier), "XDG_CONFIG_HOME": str(self.dossier / "config"),
               "XDG_CACHE_HOME": str(self.dossier / "cache"), "XDG_RUNTIME_DIR": str(self.dossier)}
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        self.proc = subprocess.Popen(
            ["bash", "-c", f'exec "$0" "$@" 3<&{a} 4>&{b}', binaire,
             "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--remote-debugging-pipe",
             f"--user-data-dir={self.dossier / 'profil'}", "--no-first-run", "--no-default-browser-check",
             "--disable-background-networking", "--disable-component-update", "--disable-sync", "--mute-audio",
             "--force-dark-mode", f"--window-size={taille[0]},{taille[1]}",
             # micro factice accordé d'office (enregistrements des Notes), lecture du son sans geste
             "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required",
             "about:blank"],
            pass_fds=(a, b), stdin=subprocess.DEVNULL, stdout=self.journal, stderr=self.journal, env=env, cwd=str(self.dossier))
        for fd in (vers_r, de_w, a, b):
            os.close(fd)
        self.vers = os.fdopen(vers_w, "wb", buffering=0)
        self.de = os.fdopen(de_r, "rb", buffering=0)
        self.numero = 0
        self.reponses = {}
        self.evenements = []
        self.etat = threading.Condition()
        self.ferme = False
        self.cible = self.session = None
        self.dimensions = taille
        threading.Thread(target=self._lire, daemon=True).start()
        try:
            self.ordre("Target.getTargets", delai=60)       # Chrome est prêt quand il répond
            self.nouvel_onglet()
        except Exception:
            self.fermer()
            raise

    def nouvel_onglet(self):
        """Onglet tout neuf (rien de gardé de la page d'avant) ; l'ancien est fermé."""
        ancien = self.cible
        self.cible = self.ordre("Target.createTarget", url="about:blank")["targetId"]
        self.session = self.ordre("Target.attachToTarget", targetId=self.cible, flatten=True)["sessionId"]
        for domaine in ("Page", "Runtime", "Log", "Network"):
            self.ordre(f"{domaine}.enable", page=True)
        self.taille(*self.dimensions)
        if ancien:
            self.ordre("Target.closeTarget", targetId=ancien)
        else:                                              # l'onglet vide ouvert au lancement
            for c in self.ordre("Target.getTargets")["targetInfos"]:
                if c["type"] == "page" and c["targetId"] != self.cible:
                    self.ordre("Target.closeTarget", targetId=c["targetId"])
        self.oublier()

    # --- échanges avec Chrome ---
    def _lire(self):
        reste = b""
        while True:
            try:
                morceau = self.de.read(65536)
            except (OSError, ValueError):
                morceau = b""
            if not morceau:
                break
            reste += morceau
            *messages, reste = reste.split(b"\0")
            with self.etat:
                for brut in messages:
                    if not brut:
                        continue
                    m = json.loads(brut)
                    if "id" in m:
                        self.reponses[m["id"]] = m
                    else:
                        self.evenements.append(m)
                self.etat.notify_all()
        with self.etat:
            self.ferme = True
            self.etat.notify_all()

    def ordre(self, methode, page=False, delai=30, **parametres):
        with self.etat:
            self.numero += 1
            numero = self.numero
        message = {"id": numero, "method": methode, "params": parametres}
        if page:
            message["sessionId"] = self.session
        self.vers.write(json.dumps(message).encode() + b"\0")
        fin = time.monotonic() + delai
        with self.etat:
            while numero not in self.reponses:
                if self.ferme:
                    raise ErreurNavigateur(f"Chrome s'est arrêté pendant {methode}\n{self.texte_journal()}")
                if not self.etat.wait(max(0.01, fin - time.monotonic())) and time.monotonic() >= fin:
                    raise ErreurNavigateur(f"Chrome ne répond pas à {methode}\n{self.texte_journal()}")
            reponse = self.reponses.pop(numero)
        if "error" in reponse:
            raise ErreurNavigateur(f"{methode} : {reponse['error'].get('message')}")
        return reponse.get("result", {})

    def texte_journal(self):
        try:
            return (self.dossier / "chrome.log").read_text(errors="replace")[-3000:]
        except OSError:
            return ""

    # --- gestes ---
    def taille(self, largeur, hauteur):
        self.dimensions = (largeur, hauteur)
        self.ordre("Emulation.setDeviceMetricsOverride", page=True, width=largeur, height=hauteur, deviceScaleFactor=1, mobile=False)

    def aller(self, adresse):
        self.ordre("Page.navigate", page=True, url=adresse)

    def evaluer(self, expression):
        """Valeur d'une expression JavaScript dans la page (les promesses sont attendues)."""
        r = self.ordre("Runtime.evaluate", page=True, expression=expression, returnByValue=True, awaitPromise=True, userGesture=True)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise ErreurNavigateur(f"erreur dans la page : {d.get('exception', {}).get('description') or d.get('text')}")
        return r["result"].get("value")

    def attendre(self, expression, delai=20, quoi=None):
        """Attend que l'expression devienne vraie dans la page ; sinon échoue en montrant la page."""
        valeur = attendre(lambda: self._essayer(expression), delai, 0.05)
        if not valeur:
            texte = self._essayer("document.body ? document.body.innerText.slice(0, 1500) : '(pas de page)'")
            raise AssertionError(f"jamais vrai dans la page : {quoi or expression}\n--- page ---\n{texte}\n--- soucis ---\n{self.soucis()}")
        return valeur

    def _essayer(self, expression):
        try:
            return self.evaluer(expression)
        except ErreurNavigateur:
            return None

    def cliquer(self, texte, dans="document"):
        """Clique sur le bouton ou le lien qui porte exactement ce texte (ou ce nom accessible)."""
        trouve = self.evaluer(f"""(() => {{
            const voulu = {json.dumps(texte)};
            const e = [...{dans}.querySelectorAll("button, a, [role=switch], [role=checkbox]")].find((x) =>
                !x.disabled && (x.textContent.trim() === voulu || x.getAttribute("aria-label") === voulu));
            if (!e) return false;
            e.scrollIntoView({{ block: "center" }});
            e.click();
            return true;
        }})()""")
        if not trouve:
            raise AssertionError(f"rien à cliquer nommé « {texte} »\n--- page ---\n{self._essayer('document.body.innerText.slice(0, 1500)')}")

    def ecrire(self, selecteur, texte):
        """Saisit un texte dans un champ, comme au clavier (la page reçoit l'événement « input »)."""
        self.evaluer(f"""(() => {{
            const champ = document.querySelector({json.dumps(selecteur)});
            champ.focus();
            champ.value = {json.dumps(texte)};
            champ.dispatchEvent(new Event("input", {{ bubbles: true }}));
        }})()""")

    def touche(self, nom, code):
        for genre in ("keyDown", "keyUp"):
            self.ordre("Input.dispatchKeyEvent", page=True, type=genre, key=nom, code=nom, windowsVirtualKeyCode=code, nativeVirtualKeyCode=code,
                       **({"text": "\r"} if nom == "Enter" and genre == "keyDown" else {}))

    def texte(self):
        return self.evaluer("document.body.innerText")

    def capture(self, nom):
        if not CAPTURES:
            return
        Path(CAPTURES).mkdir(parents=True, exist_ok=True)
        image = self.ordre("Page.captureScreenshot", page=True, format="png")["data"]
        (Path(CAPTURES) / f"{nom}.png").write_bytes(base64.b64decode(image))

    # --- ce qui s'est mal passé dans la page ---
    def oublier(self):
        with self.etat:
            self.evenements.clear()

    def _du_onglet(self):
        """Événements de l'onglet en cours seulement (pas ceux, tardifs, d'un onglet déjà fermé)."""
        with self.etat:
            return [e for e in self.evenements if e.get("sessionId") == self.session]

    def soucis(self, tolerer=()):
        """Erreurs JavaScript, messages d'erreur de la console (dont les blocages CSP), fichiers
        non chargés, réponses en erreur."""
        evenements = self._du_onglet()
        adresses = {e["params"]["requestId"]: e["params"]["request"]["url"] for e in evenements if e["method"] == "Network.requestWillBeSent"}
        trouves = []
        for e in evenements:
            m, p = e["method"], e.get("params", {})
            if m == "Runtime.exceptionThrown":
                d = p["exceptionDetails"]
                trouves.append("exception : " + str(d.get("exception", {}).get("description") or d.get("text")))
            elif m == "Log.entryAdded" and p["entry"]["level"] == "error":
                trouves.append(f"console : {p['entry']['text']} ({p['entry'].get('url', '')})")
            elif m == "Runtime.consoleAPICalled" and p["type"] in ("error", "assert"):
                trouves.append("console.error : " + " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"]))
            elif m == "Network.loadingFailed" and not p.get("canceled") and p.get("errorText") != "net::ERR_ABORTED":
                trouves.append(f"chargement raté : {adresses.get(p['requestId'], '?')} ({p.get('errorText')})")
            elif m == "Network.responseReceived" and p["response"]["status"] >= 400:
                trouves.append(f"réponse {p['response']['status']} : {p['response']['url']}")
        return [t for t in trouves if not any(motif in t for motif in tolerer)]

    def demandes(self):
        """Adresses demandées par la page depuis le dernier oublier()."""
        return [e["params"]["request"]["url"] for e in self._du_onglet() if e["method"] == "Network.requestWillBeSent"]

    def fermer(self):
        if self.proc.poll() is None:
            try:
                self.ordre("Browser.close", delai=5)
            except (ErreurNavigateur, OSError, ValueError):
                pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for f in (self.vers, self.de, self.journal):
            try:
                f.close()
            except OSError:
                pass


@unittest.skipUnless(CHROME, "aucun Chrome ou Chromium trouvé (variable SMOKY_CHROME pour en désigner un)")
class TestDansLeNavigateur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Serveur()
        try:
            cls.nav = Navigateur(CHROME, cls.srv.base)
        except Exception:
            cls.srv.stop()
            raise
        cls.adresse = f"http://localhost:{cls.srv.port}/smoky"

    @classmethod
    def tearDownClass(cls):
        cls.nav.fermer()
        cls.srv.stop()

    def setUp(self):
        self.srv.oublier("echecs", "attendre", "continuer", "sans-maj", "sans-windows")
        while taches := self.srv.json("GET", "/api/aujourdhui")[1]["taches"]:
            for t in taches:
                self.srv.req("DELETE", f"/api/taches/{t['id']}")
        shutil.rmtree(self.srv.home / ".config", ignore_errors=True)
        self.nav.dimensions = (1280, 800)
        self.nav.nouvel_onglet()
        self.srv.vider()

    def ouvrir(self, suite="", jeton=None):
        self.nav.aller(f"{self.adresse}#k={jeton or self.srv.jeton}{suite}")
        self.nav.attendre("document.querySelector('#page h1') !== null || document.querySelector('.ecran-plein') !== null", quoi="la page s'affiche")

    def sans_souci(self, tolerer=()):
        self.assertEqual(self.nav.soucis(tolerer), [], "erreurs relevées dans le navigateur")

    def taches(self):
        return self.srv.json("GET", "/api/aujourdhui")[1]["taches"]

    # ---------------------------------------------------------------------------------------------
    def test_ouverture(self):
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelector('#page h1')?.textContent === \"aujourd'hui\"")
        nav.attendre("document.querySelectorAll('.taches li').length > 0", quoi="la liste des tâches est dessinée")
        self.assertEqual(nav.evaluer("location.hash"), "#/aujourdhui", "le code d'accès ne reste pas dans l'adresse")
        self.assertNotIn(self.srv.jeton, nav.evaluer("location.href"))
        self.assertEqual(nav.evaluer("document.title"), "Aujourd'hui — Smoky")
        self.assertEqual(nav.evaluer("[...document.querySelectorAll('#rail a')].map((a) => a.textContent)"),
                         ["Aujourd'hui", "Notes", "Agenda", "Mail", "Maison", "Système"])
        self.assertEqual(nav.evaluer("document.querySelector('#rail a[aria-current]').textContent"), "Aujourd'hui")
        self.assertIn("Rien de noté", nav.texte())
        self.assertIn("76 %, sur batterie", nav.texte())
        # la police des titres est bien celle de l'appli (chargée depuis l'appli, pas une police de secours)
        nav.attendre("document.fonts.ready.then(() => document.fonts.check('300 40px Comfortaa'))", quoi="police Comfortaa chargée")
        self.assertIn("Comfortaa", nav.evaluer("getComputedStyle(document.querySelector('#page h1')).fontFamily"))
        # thème sombre, pas de défilement horizontal
        self.assertEqual(nav.evaluer("getComputedStyle(document.body).backgroundColor"), "rgb(9, 9, 10)")
        self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 1280)
        demandes = [d for d in nav.demandes() if not d.startswith("data:")]     # data: = dessins internes de Chrome (champ de date)
        self.assertTrue(demandes and all(d.startswith(f"http://localhost:{self.srv.port}/") for d in demandes),
                        f"la page ne demande rien hors de l'appli : {demandes}")
        self.assertFalse([d for d in demandes if self.srv.jeton in d and "/api/flux?" not in d], "le code d'accès ne voyage pas dans les adresses")
        nav.capture("aujourdhui-vide")
        self.sans_souci()

    def test_taches_au_clavier_et_a_la_souris(self):
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelector('form.ajout input[type=text]') !== null")
        # ajouter : texte, date, touche Entrée
        nav.ecrire("form.ajout input[type=text]", "Réviser l'électromagnétisme")
        nav.ecrire("form.ajout input[type=date]", "2031-05-20")
        nav.evaluer("document.querySelector('form.ajout input[type=text]').focus()")
        nav.touche("Enter", 13)
        nav.attendre("[...document.querySelectorAll('.taches li .titre')].some((t) => t.textContent === \"Réviser l'électromagnétisme\")")
        self.assertEqual([(t["titre"], t["echeance"], t["faite"]) for t in self.taches()], [("Réviser l'électromagnétisme", "2031-05-20", False)],
                         "la tâche est bien enregistrée par le serveur")
        # la tâche peut s'afficher (relecture prévenue par le serveur) juste avant la réponse à l'ajout
        nav.attendre("document.querySelector('form.ajout input[type=text]').value === ''", quoi="le champ est vidé pour la suivante")
        self.assertEqual(nav.evaluer("document.activeElement === document.querySelector('form.ajout input[type=text]')"), True)
        self.assertEqual(nav.evaluer("document.querySelector('.taches li .quand').textContent"), "20 mai 2031", "l'année est écrite quand ce n'est pas celle en cours")
        # deuxième tâche, par le bouton ; en retard
        nav.ecrire("form.ajout input[type=text]", "Rendre le TP de BDR")
        nav.ecrire("form.ajout input[type=date]", "2020-01-02")
        nav.cliquer("Ajouter")
        nav.attendre("document.querySelectorAll('.taches li .titre').length === 2")
        self.assertEqual(nav.evaluer("[...document.querySelectorAll('.taches li .titre')].map((t) => t.textContent)"),
                         ["Rendre le TP de BDR", "Réviser l'électromagnétisme"], "la plus urgente en premier")
        self.assertIn("en retard", nav.evaluer("document.querySelector('.taches li .quand').textContent"))
        nav.capture("aujourdhui-taches")
        # champ vide : rien n'est créé
        nav.cliquer("Ajouter")
        time.sleep(0.3)
        self.assertEqual(len(self.taches()), 2)
        # cocher
        nav.cliquer("Marquer « Rendre le TP de BDR » comme fait")
        nav.attendre("document.querySelector('.bascule') && !document.querySelector('.bascule').hidden")
        self.assertEqual({t["titre"]: t["faite"] for t in self.taches()}, {"Rendre le TP de BDR": True, "Réviser l'électromagnétisme": False})
        self.assertEqual(nav.evaluer("document.querySelector('.bascule').textContent"), "Voir ce qui est fait (1)")
        nav.cliquer("Voir ce qui est fait (1)")
        nav.attendre("[...document.querySelectorAll('ul[aria-label=Fait] li .titre')].map((t) => t.textContent).join() === 'Rendre le TP de BDR'")
        # décocher, puis supprimer
        nav.cliquer("Remettre « Rendre le TP de BDR » à faire")
        nav.attendre("document.querySelectorAll('ul[aria-label=\"À faire\"] li .titre').length === 2")
        nav.cliquer("Supprimer « Rendre le TP de BDR »")
        nav.attendre("document.querySelectorAll('.taches li .titre').length === 1")
        self.assertEqual([t["titre"] for t in self.taches()], ["Réviser l'électromagnétisme"])
        self.sans_souci()

    def test_une_tache_ne_s_affiche_qu_une_fois(self):
        """Machine lente : la relecture prévenue par le serveur arrive avant la réponse à l'ajout
        (ordre vu sur le build du 16/11). La tâche ne doit pas apparaître deux fois."""
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelector('form.ajout input[type=text]') !== null")
        time.sleep(0.5)                                  # le canal des annonces du serveur s'ouvre
        # les réponses aux ajouts, cochages et suppressions arrivent 0,8 s en retard ; les annonces du serveur, tout de suite
        nav.evaluer("""(() => { const vrai = window.fetch.bind(window);
            window.fetch = async (adresse, options = {}) => {
              const r = await vrai(adresse, options);
              if (options.method && options.method !== "GET") await new Promise((s) => setTimeout(s, 800));
              return r; }; })()""")
        compte = "[...document.querySelectorAll('.taches li .titre')].filter((t) => t.textContent === 'Une seule fois').length"
        nav.ecrire("form.ajout input[type=text]", "Une seule fois")
        nav.cliquer("Ajouter")
        nav.attendre(f"{compte} === 1 && document.querySelector('form.ajout input[type=text]').value === 'Une seule fois'",
                     quoi="la relecture affiche la tâche avant la réponse à l'ajout (la situation à risque se produit bien)")
        nav.attendre("document.querySelector('form.ajout input[type=text]').value === ''")
        time.sleep(1)                                    # laisse passer d'éventuelles relectures en retard
        self.assertEqual(nav.evaluer(compte), 1, "la tâche s'affiche une seule fois")
        nav.cliquer("Supprimer « Une seule fois »")
        nav.attendre(f"{compte} === 0", quoi="la tâche supprimée disparaît")
        time.sleep(1.2)
        self.assertEqual(nav.evaluer(compte), 0, "et ne revient pas")
        self.assertEqual(self.taches(), [])
        self.sans_souci()

    def test_un_titre_reste_du_texte(self):
        """Un titre qui ressemble à du code n'est jamais exécuté ni interprété par la page."""
        for titre in ('<img src=x onerror="window.piege=1">', '<script>window.piege=1</script>', '"><svg onload=window.piege=1>'):
            self.assertEqual(self.srv.json("POST", "/api/taches", {"titre": titre})[0], 201)
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.taches li .titre').length === 3")
        self.assertEqual(sorted(nav.evaluer("[...document.querySelectorAll('.taches li .titre')].map((t) => t.textContent)")),
                         sorted(['<img src=x onerror="window.piege=1">', '<script>window.piege=1</script>', '"><svg onload=window.piege=1>']))
        self.assertEqual(nav.evaluer("document.querySelectorAll('.taches img, .taches script, .taches svg:not([aria-hidden])').length"), 0)
        time.sleep(0.3)
        self.assertIsNone(nav.evaluer("window.piege ?? null"))
        self.sans_souci()

    def test_systeme_un_reglage_va_jusqu_a_la_commande(self):
        self.ouvrir()
        nav = self.nav
        nav.cliquer("Système")
        nav.attendre("document.querySelector('#page h1')?.textContent === 'système'")
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Énergie'")
        self.assertEqual(nav.evaluer("location.hash"), "#/systeme")
        self.assertEqual(nav.evaluer("document.querySelector('.grand-chiffre').textContent"), "76 %")
        self.assertEqual(nav.evaluer("document.querySelector('.section .intro').textContent"), "Sur batterie.")
        self.assertEqual(nav.evaluer("document.querySelector('[aria-label=\"Profil d\\'énergie\"] [aria-pressed=true]').textContent"), "Équilibré")
        self.assertEqual(nav.evaluer("document.querySelector('[aria-label=\"Limite de charge\"] [aria-pressed=true]').textContent"), "80 %")
        self.assertEqual(nav.evaluer("[...document.querySelectorAll('.sommaire a')].map((a) => a.textContent)"),
                         ["Énergie", "Écran", "Carte graphique", "Tablette et dock", "Notifications et concentration", "Confidentialité et VPN",
                          "Cours", "Maison", "Stockage et sauvegardes", "Mises à jour et démarrage"])
        nav.capture("systeme-energie")
        self.srv.vider()
        nav.cliquer("Performance", dans="document.querySelector('[aria-label=\"Profil d\\'énergie\"]')")
        self.assertTrue(attendre(lambda: ["powerprofilesctl", "set", "performance"] in self.srv.commandes(), 5))
        self.srv.vider()
        nav.cliquer("60 %")
        attendre(lambda: ["asusctl", "-c", "60"] in self.srv.commandes(), 5)
        self.assertIn(["asusctl", "-c", "60"], self.srv.commandes())
        nav.attendre("[...document.querySelectorAll('#annonces .annonce')].some((a) => a.textContent === 'Charge limitée à 60 %.')")
        # réglage adaptatif (un interrupteur) : écrit dans le fichier que lit le service smoky-adaptive
        nav.cliquer("Écran à 120 Hz sur secteur, 60 Hz sur batterie")
        fichier = self.srv.home / ".config/smoky/adaptive.json"
        self.assertTrue(attendre(lambda: fichier.exists() and json.loads(fichier.read_text())["refresh"] is False, 5))
        nav.attendre("document.querySelector('[aria-label=\"Écran à 120 Hz sur secteur, 60 Hz sur batterie\"]').getAttribute('aria-checked') === 'false'")
        self.sans_souci()

    def test_systeme_toutes_les_sections(self):
        self.ouvrir("&a=/systeme/maj")
        nav = self.nav
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Mises à jour et démarrage'", quoi="le lanceur peut ouvrir une section précise")
        self.assertEqual(nav.evaluer("location.hash"), "#/systeme/maj")
        self.assertIn("Nouvelle version téléchargée", nav.texte())
        self.assertIn("Redémarrer sur Windows", nav.texte())
        self.assertIn("Activé", nav.texte())
        nav.capture("systeme-maj")
        for section, titre, attendu in (("energie", "Énergie", "Limite de charge"), ("ecran", "Écran", None),
                                        ("graphique", "Carte graphique", "Sur Smoky OS, l'écran reste sur la puce Intel."),
                                        ("tablette", "Tablette et dock", "Mode tablette"), ("calme", "Notifications et concentration", "Lancer une session"),
                                        ("confidentialite", "Confidentialité et VPN", "L'activer tout seul sur les Wi-Fi ouverts"),
                                        ("cours", "Cours", "Moodle est connecté"), ("maison", "Maison", "Ouvrir Smoky Home"),
                                        ("stockage", "Stockage et sauvegardes", "Nettoyer"), ("maj", "Mises à jour et démarrage", "Réglages UEFI")):
            with self.subTest(section=section):
                nav.evaluer(f"location.hash = '#/systeme/{section}'")
                nav.attendre(f"document.querySelector('.section h2')?.textContent === {json.dumps(titre)}")
                self.assertEqual(nav.evaluer("document.querySelector('.sommaire a[aria-current]').textContent"), titre)
                if attendu:
                    self.assertIn(attendu, nav.texte())
                self.assertGreater(nav.evaluer("document.querySelector('.section').children.length"), 1, "la section n'est pas vide")
                self.assertTrue(nav.evaluer("[...document.querySelectorAll('.section h3')].every((t) => t.nextElementSibling?.classList.contains('groupe'))"),
                                "pas d'intertitre seul, sans réglage dessous")
                self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 1280, "pas de défilement horizontal")
                nav.capture(f"systeme-{section}")
        self.sans_souci()

    def test_action_grave_demande_confirmation(self):
        self.ouvrir("&a=/systeme/maj")
        nav = self.nav
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Mises à jour et démarrage'")
        self.srv.vider()
        nav.cliquer("Redémarrer sur Windows")
        nav.attendre("document.querySelector('dialog[open] h2')?.textContent === 'Redémarrer sur Windows maintenant ?'")
        nav.capture("systeme-confirmation")
        time.sleep(0.3)
        self.assertEqual([c for c in self.srv.commandes() if c[0] == "systemctl"], [], "rien n'est lancé avant ta réponse")
        nav.cliquer("Annuler", dans="document.querySelector('dialog[open]')")
        nav.attendre("document.querySelector('dialog') === null")
        time.sleep(0.3)
        self.assertEqual([c for c in self.srv.commandes() if c[0] == "systemctl"], [], "« Annuler » ne lance rien")
        # la touche Échap vaut « Annuler »
        nav.cliquer("Redémarrer")
        nav.attendre("document.querySelector('dialog[open]') !== null")
        nav.touche("Escape", 27)
        nav.attendre("document.querySelector('dialog') === null")
        time.sleep(0.3)
        self.assertEqual([c for c in self.srv.commandes() if c[0] == "systemctl"], [])
        # cette fois, oui
        nav.cliquer("Redémarrer sur Windows")
        nav.attendre("document.querySelector('dialog[open]') !== null")
        nav.cliquer("Redémarrer sur Windows", dans="document.querySelector('dialog[open]')")
        self.assertTrue(attendre(lambda: ["systemctl", "start", "smoky-windows.service"] in self.srv.commandes(), 5))
        self.assertNotIn(["systemctl", "reboot"], self.srv.commandes())
        self.sans_souci()

    def test_erreur_d_une_commande_affichee(self):
        self.ouvrir("&a=/systeme/energie")
        nav = self.nav
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Énergie'")
        self.srv.regle("echecs", "powerprofilesctl set *")
        nav.oublier()
        nav.cliquer("Économie")
        nav.attendre("document.querySelector('#annonces .annonce.erreur')?.textContent === \"Le profil d'énergie n'a pas pu être changé.\"")
        nav.attendre("document.querySelector('[aria-label=\"Profil d\\'énergie\"] [aria-pressed=true]').textContent === 'Équilibré'",
                     quoi="la page revient à ce que le PC a vraiment retenu")
        self.sans_souci(tolerer=("réponse 502", "status of 502"))

    def test_travail_long_et_page_prevenue(self):
        self.ouvrir("&a=/systeme/stockage")
        nav = self.nav
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Stockage et sauvegardes'")
        self.srv.regle("attendre", "flatpak update *")
        nav.cliquer("Mettre à jour les applis")
        nav.attendre("[...document.querySelectorAll('.section button')].some((b) => b.textContent === 'Mise à jour…' && b.disabled)",
                     quoi="le bouton montre que le travail est en cours")
        (self.srv.faux / "continuer").touch()
        # la page n'attend pas sa relecture de 20 s : le serveur la prévient
        nav.attendre("[...document.querySelectorAll('.section button')].some((b) => b.textContent === 'Mettre à jour les applis' && !b.disabled)", delai=8,
                     quoi="le bouton revient dès que le travail est fini")
        self.sans_souci()

    def test_anciennes_applis(self):
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('#rail a.ancienne').length === 2")
        for refaite in ("agenda", "notes"):
            self.assertFalse(nav.evaluer(f"document.querySelector('#rail a[data-page={refaite}]').classList.contains('ancienne')"),
                             f"{refaite} est refait dans Smoky")
        self.srv.vider()
        nav.cliquer("Maison", dans="document.querySelector('#rail')")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-home"]])
        self.assertEqual(nav.evaluer("location.hash"), "#/aujourdhui", "on reste sur la page ; l'ancienne appli s'ouvre à part")
        nav.attendre("[...document.querySelectorAll('#annonces .annonce')].some((a) => a.textContent === \"Maison s'ouvre dans sa fenêtre.\")")
        self.srv.vider()
        nav.cliquer("Ouvrir Mail")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-mail"]])
        for refaite in ("Ouvrir Agenda", "Ouvrir Notes"):
            self.assertNotIn(refaite, nav.texte())
        nav.cliquer("Notes", dans="document.querySelector('#rail')")
        nav.attendre("location.hash === '#/notes' && document.querySelector('#page h1')?.textContent === 'notes'", quoi="les Notes s'ouvrent dans l'appli")
        self.assertEqual(self.srv.commandes(), [["smoky-mail"]], "aucune ancienne appli lancée pour les Notes")
        self.sans_souci()

    def test_sans_code_d_acces(self):
        """Adresse ouverte à la main, sans passer par le lanceur (nouvel onglet : aucun code gardé)."""
        self.nav.aller(self.adresse)
        self.nav.attendre("document.querySelector('.ecran-plein h2')?.textContent === 'Ouvre Smoky depuis son icône'")
        self.assertEqual([d for d in self.nav.demandes() if "/api/" in d], [], "sans code, la page n'interroge même pas le serveur")
        self.sans_souci()

    def test_code_d_acces_perime(self):
        """Fenêtre restée ouverte alors que le serveur a été relancé : message clair, pas d'écran cassé."""
        self.ouvrir(jeton="x" * 43)
        self.nav.attendre("document.querySelector('.ecran-plein h2')?.textContent === 'Smoky a été relancé'")
        self.assertIn("ferme-la et rouvre Smoky", self.nav.texte())
        self.assertEqual(self.taches(), [])
        self.nav.capture("relance")

    def test_meme_onglet_garde_son_acces(self):
        """Recharger la page (F5) : le code d'accès de la fenêtre est gardé, la page revient telle quelle."""
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.taches li').length > 0")
        nav.evaluer("location.hash = '#/systeme/ecran'")
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Écran'")
        nav.ordre("Page.reload", page=True)
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Écran'", quoi="après rechargement, on retrouve la même section")
        self.assertEqual(nav.evaluer("location.hash"), "#/systeme/ecran")
        self.sans_souci()

    def test_les_connexions_ne_s_accumulent_pas(self):
        """Quitter la page puis y revenir, dix fois : Chrome n'ouvre que 6 connexions vers une même
        adresse ; si la page gardait la sienne à chaque fois, elle finirait par ne plus rien charger."""
        nav = self.nav
        for tour in range(10):
            nav.aller("about:blank")
            nav.attendre("location.href === 'about:blank'")
            nav.aller(f"{self.adresse}#k={self.srv.jeton}")
            nav.attendre("document.querySelectorAll('.taches li').length > 0", delai=10, quoi=f"la page se charge encore au tour {tour + 1}")
        # retour en arrière puis en avant (page remise par le navigateur) : elle fonctionne toujours
        nav.aller("about:blank")
        nav.attendre("location.href === 'about:blank'")
        # lancé juste après la réponse : sinon le changement de page coupe la réponse elle-même
        nav.evaluer("setTimeout(() => history.back(), 0), true")
        nav.attendre("document.querySelectorAll('.taches li').length > 0", quoi="page reprise après retour en arrière")
        self.assertEqual(self.srv.json("POST", "/api/taches", {"titre": "ajoutée pendant ce temps"})[0], 201)
        nav.evaluer("location.hash = '#/systeme/energie'")
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Énergie'")
        self.sans_souci()

    def test_serveur_arrete(self):
        """Le serveur s'arrête alors qu'une fenêtre est restée ouverte : message clair, pas de page morte."""
        srv = Serveur()
        self.addCleanup(srv.stop)
        nav = self.nav
        nav.aller(f"http://localhost:{srv.port}/smoky#k={srv.jeton}")
        nav.attendre("document.querySelectorAll('.taches li').length > 0")
        self.assertEqual(srv.arreter(), 0)
        nav.attendre("document.querySelector('.ecran-plein h2')?.textContent === \"Smoky s'est arrêté\"", delai=20)
        self.assertIn("rouvre Smoky depuis son icône", nav.texte())
        nav.oublier()
        time.sleep(4)
        self.assertEqual([d for d in nav.demandes() if "/api/" in d], [], "la page n'insiste pas auprès d'un serveur arrêté")

    def test_petit_ecran_et_mouvement_reduit(self):
        self.nav.taille(760, 1000)
        self.nav.ordre("Emulation.setEmulatedMedia", page=True, features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        self.addCleanup(lambda: self.nav.ordre("Emulation.setEmulatedMedia", page=True, features=[]))
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.taches li').length > 0")
        self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 760, "pas de défilement horizontal en demi-écran")
        self.assertTrue(nav.evaluer("document.body.classList.contains('calme')"), "animations coupées quand le système le demande")
        nav.capture("aujourdhui-etroit")
        nav.evaluer("location.hash = '#/systeme/energie'")
        nav.attendre("document.querySelector('.section h2')?.textContent === 'Énergie'")
        self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 760)
        # cibles tactiles : 44 px au moins pour ce qui se touche du doigt
        petits = nav.evaluer("""[...document.querySelectorAll('#rail a, .sommaire a, .segment button, .bouton, .interrupteur')]
            .filter((e) => e.offsetParent !== null).map((e) => [e.textContent.trim() || e.getAttribute('aria-label'), Math.round(e.getBoundingClientRect().height)])
            .filter(([, h]) => h < 44)""")
        self.assertEqual(petits, [], "commandes trop petites pour le doigt")
        nav.capture("systeme-etroit")
        self.sans_souci()

    def test_navigation_au_clavier(self):
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.taches li').length > 0")
        nav.evaluer("document.querySelector('#rail a').focus()")
        vus = []
        for _ in range(12):
            nav.touche("Tab", 9)
            vus.append(nav.evaluer("""(() => { const e = document.activeElement; const s = getComputedStyle(e);
                return [e.tagName, (e.textContent.trim() || e.getAttribute('aria-label') || e.placeholder || '').slice(0, 30),
                        s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0 || s.boxShadow !== 'none'
                        || getComputedStyle(e, '::before').outlineStyle !== 'none']; })()"""))
        self.assertIn("Nouvelle tâche", [v[1] for v in vus] + [nav.evaluer("document.querySelector('form.ajout input').getAttribute('aria-label')")])
        sans_repere = [v for v in vus if v[0] != "BODY" and not v[2]]
        self.assertEqual(sans_repere, [], "au clavier, l'élément actif doit toujours être repérable")
        self.sans_souci()


@unittest.skipUnless(CHROME, "aucun Chrome ou Chromium trouvé (variable SMOKY_CHROME pour en désigner un)")
class TestAgendaDansLeNavigateur(unittest.TestCase):
    """La page Agenda, à une heure figée : mardi 17 novembre 2026, 9 h (comme tests/test_agenda.py)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = Serveur(env={"SMOKY_MAINTENANT": MAINTENANT})
        try:
            cls.nav = Navigateur(CHROME, cls.srv.base)
        except Exception:
            cls.srv.stop()
            raise
        cls.adresse = f"http://localhost:{cls.srv.port}/smoky"

    @classmethod
    def tearDownClass(cls):
        cls.nav.fermer()
        cls.srv.stop()

    def setUp(self):
        # agenda vide à chaque essai : mémoire effacée, serveur relancé
        self.srv.arreter()
        shutil.rmtree(self.srv.environnement["SMOKY_DONNEES"], ignore_errors=True)
        self.srv.demarrer()
        self.nav.dimensions = (1280, 800)
        self.nav.nouvel_onglet()
        self.srv.vider()

    def ouvrir(self, suite="&a=/agenda"):
        self.nav.aller(f"{self.adresse}#k={self.srv.jeton}{suite}")
        self.nav.attendre("document.querySelector('#page h1') !== null", quoi="la page s'affiche")

    def agir(self, action, **valeurs):
        code, r = self.srv.json("POST", "/api/agenda", {"action": action, **valeurs})
        self.assertEqual(code, 200, r)
        return r

    def etat(self):
        return self.srv.json("GET", "/api/agenda")[1]

    def annonce(self, texte):
        self.nav.attendre(f"[...document.querySelectorAll('#annonces .annonce')].some((a) => a.textContent === {json.dumps(texte)})",
                          quoi=f"annonce « {texte} »")

    def toucher(self, selecteur, y):
        """Vrai clic (souris du protocole de débogage) à y pixels du haut de l'élément, ce point
        amené d'abord au milieu de l'écran (loin de la rangée des jours, qui reste en haut)."""
        x, y = self.nav.evaluer(f"""(() => {{ const e = document.querySelector({json.dumps(selecteur)});
            const page = document.querySelector('#page');
            page.scrollTop += e.getBoundingClientRect().top + {y} - innerHeight / 2;
            const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + {y}]; }})()""")
        for genre in ("mousePressed", "mouseReleased"):
            self.nav.ordre("Input.dispatchMouseEvent", page=True, type=genre, x=x, y=y, button="left", clickCount=1)

    def sans_souci(self, tolerer=()):
        self.assertEqual(self.nav.soucis(tolerer), [], "erreurs relevées dans le navigateur")
        texte = self.nav.texte()
        for mot in ("null", "undefined", "NaN", "[object"):
            self.assertNotIn(mot, texte, "une valeur absente s'affiche en toutes lettres")

    # ---------------------------------------------------------------------------------------------
    def test_importer_depuis_la_page(self):
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelector('.invitation') !== null", quoi="invitation à importer l'emploi du temps")
        fichier = self.srv.base / "ADECal.ics"
        fichier.write_text(semaine_type())
        objet = nav.ordre("Runtime.evaluate", page=True, expression="document.querySelector('.invitation input[type=file]')")["result"]["objectId"]
        nav.ordre("DOM.setFileInputFiles", page=True, files=[str(fichier)], objectId=objet)
        self.annonce("Emploi du temps importé : 10 cours.")
        nav.attendre("document.querySelectorAll('.element.cours').length === 10")
        self.assertFalse(nav.evaluer("!!document.querySelector('.invitation')"), "l'invitation disparaît")
        nav.capture("agenda")
        self.sans_souci()

    def test_semaine_et_detail(self):
        self.agir("importer", contenu=semaine_type())
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.element.cours').length === 10", quoi="les 10 cours de la semaine")
        self.assertEqual(nav.evaluer("document.querySelector('#page h1').textContent"), "agenda")
        self.assertEqual(nav.evaluer("document.querySelector('.entete .sous').textContent"), "semaine du 16 au 22 novembre")
        self.assertEqual(nav.evaluer("document.querySelector('.jour-tete[aria-current=date]').dataset.jour"), "2026-11-17")
        self.assertTrue(nav.evaluer("!!document.querySelector('.colonne.aujourdhui .maintenant')"), "ligne de l'heure actuelle")
        # placement : le cours de 14 h à 16 h, deux fois plus haut qu'une heure, 6 heures sous celui de 8 h
        haut = nav.evaluer("""[...document.querySelectorAll('.colonne.aujourdhui .element')].map((e) => [e.offsetTop, e.offsetHeight])""")
        self.assertEqual(len(haut), 2)
        heure = (haut[1][0] - haut[0][0]) / 6
        self.assertGreater(heure, 40)
        self.assertAlmostEqual(haut[1][1], 2 * heure, delta=4)
        self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 1280)
        nav.cliquer("Cours, BDR TD, mardi 17 novembre, 14 h à 16 h, B201")
        nav.attendre("document.querySelector('dialog.detail[open]') !== null")
        texte = nav.evaluer("document.querySelector('dialog.detail').innerText")
        for morceau in ("BDR TD", "mardi 17 novembre, de 14 h à 16 h", "B201", "Vient de ton emploi du temps."):
            self.assertIn(morceau, texte)
        self.assertNotIn("null", texte)
        self.assertNotIn("Retirer", texte, "un cours de l'emploi du temps ne se retire pas")
        nav.cliquer("Fermer", dans="document.querySelector('dialog.detail')")
        nav.attendre("document.querySelector('dialog.detail') === null")
        nav.cliquer("Semaine suivante")
        nav.attendre("document.querySelector('.entete .sous').textContent === 'semaine du 23 au 29 novembre'")
        self.assertEqual(nav.evaluer("document.querySelectorAll('.element').length"), 0)
        nav.cliquer("Semaine suivante")
        nav.attendre("document.querySelector('.entete .sous').textContent === 'semaine du 30 novembre au 6 décembre'")
        nav.cliquer("Cette semaine")
        nav.attendre("document.querySelectorAll('.element.cours').length === 10")
        # depuis un cours, ses notes : le classeur de la matière dans la page Notes
        nav.cliquer("Cours, BDR TD, mardi 17 novembre, 14 h à 16 h, B201")
        nav.attendre("document.querySelector('dialog.detail[open]') !== null")
        nav.cliquer("Ouvrir les notes de BDR", dans="document.querySelector('dialog.detail')")
        nav.attendre("location.hash === '#/notes/classeur/BDR' && document.querySelector('.entete .sous')?.textContent === 'classeur BDR'",
                     quoi="le classeur BDR s'ouvre dans les Notes")
        self.assertEqual(nav.evaluer("document.querySelector('#rail a[aria-current]').textContent"), "Notes")
        self.assertEqual(self.srv.commandes(), [], "aucune ancienne appli lancée")
        self.sans_souci()

    def test_planifier_et_cocher(self):
        self.agir("importer", contenu=semaine_type())
        self.agir("importer", contenu=examens_ics())
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.element.cours').length === 10")
        self.assertIn("Examen BDR", nav.evaluer("document.querySelector('.examens').innerText"))
        self.assertEqual(nav.evaluer("getComputedStyle(document.querySelector('.element.examen')).borderTopColor"), "rgb(243, 243, 246)",
                         "l'examen porte le trait lumineux")
        nav.cliquer("Planifier ma semaine")
        nav.attendre(r"[...document.querySelectorAll('#annonces .annonce')].some((a) => /^Semaine planifiée : \d+ blocs\.$/.test(a.textContent))")
        nav.attendre("document.querySelectorAll('.element.planifie').length > 20")
        self.assertIn("révisées sur", nav.evaluer("document.querySelector('.examens').innerText"), "bilan des révisions de l'examen")
        nav.capture("agenda-planifie")
        nom = nav.evaluer("document.querySelector('.element.revision').getAttribute('aria-label')")
        nav.cliquer(nom)
        nav.attendre("document.querySelector('dialog.detail[open]') !== null")
        nav.cliquer("C'est fait", dans="document.querySelector('dialog.detail')")
        nav.attendre(f"[...document.querySelectorAll('.element')].some((e) => e.getAttribute('aria-label') === {json.dumps(nom + ', fait')})",
                     quoi="le bloc est montré fait")
        self.assertEqual(len([x for x in self.etat()["elements"] if x.get("fait")]), 1)
        # une séance de salle : les charges se notent depuis son détail
        nav.cliquer(nav.evaluer("document.querySelector('.element.salle').getAttribute('aria-label')"))
        nav.attendre("document.querySelector('dialog.detail .salle') !== null")
        self.assertNotIn("null", nav.evaluer("document.querySelector('dialog.detail').innerText"))
        nav.evaluer("""(() => { const [kg, reps] = document.querySelectorAll('dialog.detail .exercice input');
            kg.value = '42.5'; reps.value = '10'; })()""")
        nav.cliquer("Noter la séance", dans="document.querySelector('dialog.detail')")
        nav.attendre("document.querySelector('dialog.detail') === null")
        self.assertEqual([v["kg"] for v in self.etat()["charges"].values()], [42.5])
        self.sans_souci()

    def test_planifier_avec_claude(self):
        from test_agenda import FAUX_CLAUDE                     # même faux Claude Code que les tests du serveur
        (self.srv.faux / "claude").write_text(FAUX_CLAUDE)
        (self.srv.faux / "claude").chmod(0o755)
        (self.srv.faux / "claude-connecte").touch()
        (self.srv.faux / "claude-lent").touch()                 # Claude met du temps : le message de départ passe d'abord
        self.addCleanup(lambda: [(self.srv.faux / f).unlink(missing_ok=True) for f in ("claude", "claude-connecte", "claude-reponse", "claude-lent")])
        blocs = [{"day": "2026-11-18", "start": "18:00", "end": "19:00", "type": "revision", "title": "Révision : BDR"}]
        (self.srv.faux / "claude-reponse").write_text(json.dumps({"is_error": False, "result": json.dumps({"blocks": blocs})}))
        self.agir("importer", contenu=semaine_type())
        self.ouvrir()
        nav = self.nav
        nav.attendre("[...document.querySelectorAll('button')].some((b) => b.textContent === 'Avec Claude')", quoi="bouton « Avec Claude » (compte connecté)")
        nav.cliquer("Avec Claude")
        self.annonce("Claude organise ta semaine. Cela peut prendre quelques minutes.")
        nav.attendre("[...document.querySelectorAll('button')].some((b) => b.textContent === 'Claude organise ta semaine…' && b.disabled)",
                     quoi="le bouton montre que Claude travaille")
        self.annonce("Claude a organisé ta semaine : 1 blocs.")
        nav.attendre("[...document.querySelectorAll('.element.revision')].some((e) => e.getAttribute('aria-label').startsWith('Révision, Révision : BDR, mercredi 18 novembre, 18 h'))")
        self.assertTrue(nav.evaluer("[...document.querySelectorAll('button')].some((b) => b.textContent === 'Avec Claude' && !b.disabled)"),
                        "le bouton revient une fois le travail fini")
        self.sans_souci()

    def test_ajouter(self):
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelector('.semaine') !== null")
        nav.cliquer("Ajouter")
        nav.attendre("document.querySelector('dialog.ajout-agenda[open]') !== null")
        self.assertEqual(nav.evaluer("document.activeElement.type"), "text", "le curseur est dans le nom")
        nav.ecrire("dialog.ajout-agenda input[type=text]", "Dentiste")
        nav.evaluer("""(() => { const d = document.querySelector('dialog.ajout-agenda');
            d.querySelector('input[type=date]').value = '2026-11-18';
            const [debut, fin] = d.querySelectorAll('input[type=time]'); debut.value = '17:00'; fin.value = '16:00'; })()""")
        nav.cliquer("Ajouter", dans="document.querySelector('dialog.ajout-agenda')")
        nav.attendre("document.querySelector('#annonces .annonce.erreur')?.textContent === 'La fin doit être après le début.'")
        self.assertTrue(nav.evaluer("!!document.querySelector('dialog.ajout-agenda[open]')"), "la fenêtre reste ouverte pour corriger")
        nav.evaluer("document.querySelectorAll('dialog.ajout-agenda input[type=time]')[1].value = '18:30'")
        nav.cliquer("Ajouter", dans="document.querySelector('dialog.ajout-agenda')")
        nav.attendre("document.querySelector('dialog.ajout-agenda') === null")
        nav.attendre("document.querySelectorAll('.element.perso').length === 1")
        [rdv] = [x for x in self.etat()["elements"] if x["genre"] == "perso"]
        self.assertEqual((rdv["titre"], rdv["debut"], rdv["fin"]), ("Dentiste", "2026-11-18T17:00", "2026-11-18T18:30"))
        # tâche à caser : les champs changent avec le genre choisi
        nav.cliquer("Ajouter")
        nav.cliquer("Tâche à caser", dans="document.querySelector('dialog.ajout-agenda')")
        nav.attendre("document.querySelector('dialog.ajout-agenda input[type=number]') !== null")
        self.assertEqual(nav.evaluer("[...document.querySelectorAll('dialog.ajout-agenda .segment [aria-pressed=true]')].map((b) => b.textContent)"),
                         ["Tâche à caser"], "le genre choisi est montré")
        self.assertEqual(nav.evaluer("document.querySelectorAll('dialog.ajout-agenda input[type=time]').length"), 0)
        nav.ecrire("dialog.ajout-agenda input[type=text]", "Préparer l'exposé")
        nav.cliquer("Ajouter", dans="document.querySelector('dialog.ajout-agenda')")
        nav.attendre("document.querySelector('dialog.ajout-agenda') === null")
        nav.attendre("[...document.querySelectorAll('.a-caser li')].some((l) => l.textContent.includes(\"Préparer l'exposé\"))")
        self.assertEqual([(t["titre"], t["minutes"]) for t in self.etat()["a_caser"]], [("Préparer l'exposé", 60)])
        # toucher un créneau vide : la fenêtre s'ouvre ce jour-là, à cette heure-là (la grille commence à 6 h)
        heure = nav.evaluer("parseFloat(getComputedStyle(document.querySelector('.semaine')).getPropertyValue('--heure'))")
        self.toucher(".colonne[data-jour='2026-11-19']", (18 - 6) * heure + 3)
        nav.attendre("document.querySelector('dialog.ajout-agenda[open]') !== null")
        valeurs = nav.evaluer("[...document.querySelectorAll('dialog.ajout-agenda input')].filter((c) => c.type === 'date' || c.type === 'time').map((c) => c.value)")
        self.assertEqual(valeurs, ["2026-11-19", "18:00", "19:00"])
        nav.touche("Escape", 27)
        nav.attendre("document.querySelector('dialog.ajout-agenda') === null")
        self.sans_souci(tolerer=("réponse 400", "status of 400"))

    def test_reglages(self):
        self.ouvrir("&a=/agenda/reglages")
        nav = self.nav
        nav.attendre("document.querySelector('.entete .sous')?.textContent === 'réglages'")
        nav.capture("agenda-reglages")
        nav.evaluer("""(() => { const c = document.querySelector('input[aria-label="Réveil"]'); c.dataset.avant = '1'; c.focus(); c.value = '06:30';
            c.dispatchEvent(new Event('change', { bubbles: true })); })()""")
        self.assertTrue(attendre(lambda: self.etat()["reglages"]["reveil"] == "06:30", 10), "réveil enregistré")
        nav.attendre("!document.querySelector('input[aria-label=\"Réveil\"]').dataset.avant", quoi="la page est redessinée après l'enregistrement")
        nav.attendre("document.activeElement?.getAttribute('aria-label') === 'Réveil' && document.activeElement.value === '06:30'",
                     quoi="le curseur reste dans le champ après l'enregistrement")
        nav.cliquer("Rappels")
        self.assertTrue(attendre(lambda: self.etat()["reglages"]["rappels"] is False, 10), "rappels coupés")
        nav.evaluer("""(() => { const c = document.querySelector('input[aria-label="Matières"]'); c.focus(); c.value = 'BDR, Anglais, en cours de fra'; })()""")
        self.agir("ajouter", genre="perso", titre="Dentiste", jour="2026-11-18", debut="17:00", fin="18:00")   # changé ailleurs
        time.sleep(1.5)
        self.assertEqual(nav.evaluer("document.querySelector('input[aria-label=\"Matières\"]').value"), "BDR, Anglais, en cours de fra",
                         "ce que tu tapes n'est pas effacé par une mise à jour venue d'ailleurs")
        nav.cliquer("Haiku")
        self.assertTrue(attendre(lambda: self.etat()["reglages"]["modele"] == "haiku", 10))
        nav.ecrire('input[aria-label="Lien iCal de l\'emploi du temps"]', "ftp://ent.exemple/edt.ics")
        nav.cliquer("Enregistrer")
        nav.attendre(f"document.querySelector('#annonces .annonce.erreur')?.textContent === {json.dumps('Le lien de l’emploi du temps doit commencer par https://'.replace('’', chr(39)))}")
        self.assertEqual(self.etat()["reglages"]["lien"], "")
        nav.cliquer("Revenir à la semaine")
        nav.attendre("document.querySelector('.entete .sous').textContent.startsWith('semaine du')")
        self.sans_souci(tolerer=("réponse 400", "status of 400"))

    def test_petit_ecran(self):
        self.agir("importer", contenu=semaine_type())
        self.nav.taille(760, 1000)
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.colonne').length === 1 && document.querySelectorAll('.element.cours').length === 2",
                     quoi="un seul jour à la fois")
        self.assertEqual(nav.evaluer("document.querySelector('.colonne').dataset.jour"), "2026-11-17", "aujourd'hui d'abord")
        nav.cliquer("mercredi 18 novembre")
        nav.attendre("document.querySelector('.colonne').dataset.jour === '2026-11-18'")
        self.assertEqual(nav.evaluer("document.querySelector('.jour-tete[aria-pressed=true]').dataset.jour"), "2026-11-18")
        self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 760, "pas de défilement horizontal")
        petits = nav.evaluer("""[...document.querySelectorAll('.bouton, .segment button, button.jour-tete')]
            .filter((e) => e.offsetParent !== null).map((e) => [e.textContent.trim() || e.getAttribute('aria-label'), Math.round(e.getBoundingClientRect().height)])
            .filter(([, h]) => h < 44)""")
        self.assertEqual(petits, [], "commandes trop petites pour le doigt")
        nav.capture("agenda-etroit")
        self.sans_souci()

    def test_au_clavier(self):
        self.agir("importer", contenu=semaine_type())
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.element.cours').length === 10")
        nav.evaluer("document.querySelector('#rail a').focus()")
        vus = []
        for _ in range(16):
            nav.touche("Tab", 9)
            vus.append(nav.evaluer("""(() => { const e = document.activeElement; const s = getComputedStyle(e);
                return [e.tagName, (e.getAttribute('aria-label') || e.textContent.trim()).slice(0, 40),
                        s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0 || s.boxShadow !== 'none']; })()"""))
        self.assertTrue([v for v in vus if v[1].startswith("Cours, ")], f"les cours se rejoignent au clavier : {vus}")
        self.assertEqual([v for v in vus if v[0] != "BODY" and not v[2]], [], "au clavier, l'élément actif doit toujours être repérable")
        nav.touche("Enter", 13)
        nav.attendre("document.querySelector('dialog.detail[open]') !== null", quoi="Entrée ouvre le détail")
        nav.touche("Escape", 27)
        nav.attendre("document.querySelector('dialog.detail') === null")
        self.sans_souci()

    def test_ta_journee_dans_aujourdhui(self):
        self.agir("importer", contenu=semaine_type())
        self.ouvrir("")
        nav = self.nav
        nav.attendre("document.querySelectorAll('.journee a').length === 2", quoi="les deux cours du jour")
        nav.capture("aujourdhui-journee")
        lignes = nav.evaluer(r"[...document.querySelectorAll('.journee a')].map((a) => [a.className, a.innerText.replace(/\s+/g, ' ').trim()])")
        self.assertEqual(lignes, [["en-cours", "8 h Analyse CM Amphi 1"], ["", "14 h BDR TD B201"]])
        nav.evaluer("document.querySelector('.journee a').click()")
        nav.attendre("location.hash === '#/agenda' && document.querySelector('#page h1')?.textContent === 'agenda'")
        self.assertEqual(nav.evaluer("document.querySelector('#rail a[aria-current]').textContent"), "Agenda")
        self.sans_souci()


def png(largeur, hauteur, couleur=(45, 111, 224)):
    """Une vraie image PNG unie."""
    def bloc(genre, donnees):
        return len(donnees).to_bytes(4, "big") + genre + donnees + zlib.crc32(genre + donnees).to_bytes(4, "big")
    lignes = b"".join(b"\0" + bytes(couleur) * largeur for _ in range(hauteur))
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", largeur.to_bytes(4, "big") + hauteur.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]))
            + bloc(b"IDAT", zlib.compress(lignes)) + bloc(b"IEND", b""))


def vague(x0, y0, n=50, pas=4, ampleur=10):
    """Un trait d'écriture : une vague de n points vers la droite."""
    return [(x0 + i * pas, y0 + math.sin(i / 3) * ampleur) for i in range(n)]


@unittest.skipUnless(CHROME, "aucun Chrome ou Chromium trouvé (variable SMOKY_CHROME pour en désigner un)")
class TestNotesDansLeNavigateur(unittest.TestCase):
    """La page Notes : bibliothèque, éditeur au stylet, PDF importé puis exporté, son relié à
    l'écriture. Le stylet est simulé par le protocole de débogage (pointeur « pen », avec sa
    pression), les doigts par de vrais événements tactiles. Chaque geste est vérifié jusque sur le
    disque (Notes/Carnets du dossier personnel jetable)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = Serveur()
        try:
            cls.nav = Navigateur(CHROME, cls.srv.base)
        except Exception:
            cls.srv.stop()
            raise
        cls.adresse = f"http://localhost:{cls.srv.port}/smoky"

    @classmethod
    def tearDownClass(cls):
        cls.nav.fermer()
        cls.srv.stop()

    def setUp(self):
        # bibliothèque vide et réglages des outils oubliés à chaque essai
        self.srv.arreter()
        shutil.rmtree(self.srv.environnement["SMOKY_DONNEES"], ignore_errors=True)
        shutil.rmtree(self.srv.home / "Notes", ignore_errors=True)
        self.srv.demarrer()
        self.nav.dimensions = (1280, 800)
        self.nav.nouvel_onglet()
        self.srv.vider()

    # --- aides ---------------------------------------------------------------------------------------
    def ouvrir(self, suite="&a=/notes"):
        self.nav.aller(f"{self.adresse}#k={self.srv.jeton}{suite}")
        self.nav.attendre("document.querySelector('#page h1, .editeur .feuilles') !== null", quoi="la page s'affiche")

    def creer(self, titre="Algèbre", **valeurs):
        code, r = self.srv.json("POST", "/api/notes", {"action": "creer", "titre": titre, **valeurs})
        self.assertEqual(code, 200, r)
        return r["carnet"]

    def prete(self, pid):
        self.nav.attendre(f"document.querySelector('.feuille[data-page=\"{pid}\"]')?.dataset.prete === '1'", quoi=f"la page {pid} est prête")

    def editeur(self, carnet):
        """Ouvre le carnet ; → l'identifiant de sa première page, prête à recevoir l'encre."""
        self.ouvrir(f"&a=/notes/c/{carnet['id']}")
        pid = carnet["pages"][0]["id"]
        self.prete(pid)
        return pid

    def feuille(self, pid):
        """[gauche, haut, largeur, hauteur] de la page à l'écran."""
        return self.nav.evaluer(f"""(() => {{ const r = document.querySelector('.feuille[data-page="{pid}"]').getBoundingClientRect();
            return [r.left, r.top, r.width, r.height]; }})()""")

    def stylo(self, points, pression=0.6, genre="pen"):
        """Un geste au stylet (ou à la souris) : appui, glissé point par point, relâché."""
        nav = self.nav
        (x0, y0), (x1, y1) = points[0], points[-1]
        nav.ordre("Input.dispatchMouseEvent", page=True, type="mouseMoved", x=x0, y=y0, pointerType=genre)
        nav.ordre("Input.dispatchMouseEvent", page=True, type="mousePressed", x=x0, y=y0, button="left", buttons=1, clickCount=1,
                  pointerType=genre, force=pression)
        for x, y in points[1:]:
            nav.ordre("Input.dispatchMouseEvent", page=True, type="mouseMoved", x=x, y=y, button="left", buttons=1, pointerType=genre, force=pression)
        nav.ordre("Input.dispatchMouseEvent", page=True, type="mouseReleased", x=x1, y=y1, button="left", buttons=0, clickCount=1,
                  pointerType=genre, force=0)

    def doigts(self, etapes):
        """Gestes aux doigts : chaque étape donne les doigts posés ; une étape vide les lève tous."""
        avant = 0
        for pts in etapes:
            genre = "touchEnd" if not pts else "touchStart" if len(pts) > avant else "touchMove"
            self.nav.ordre("Input.dispatchTouchEvent", page=True, type=genre,
                           touchPoints=[{"x": x, "y": y, "id": i, "radiusX": 6, "radiusY": 6, "force": 1} for i, (x, y) in enumerate(pts)])
            avant = len(pts)

    def raccourci(self, touche, code, ctrl=False, maj=False):
        for genre in ("keyDown", "keyUp"):
            self.nav.ordre("Input.dispatchKeyEvent", page=True, type=genre, key=touche.upper() if maj else touche, code=f"Key{touche.upper()}",
                           windowsVirtualKeyCode=code, nativeVirtualKeyCode=code, modifiers=(2 if ctrl else 0) | (8 if maj else 0))

    def page_serveur(self, cid, pid):
        return self.srv.json("GET", f"/api/notes/{cid}/pages/{pid}")[1]

    def carnet_serveur(self, cid):
        return self.srv.json("GET", f"/api/notes/{cid}")[1]

    def carnets(self):
        return self.srv.json("GET", "/api/notes")[1]["carnets"]

    def enregistre(self, lire, condition, quoi):
        """Attend que ce qui est enregistré remplisse la condition ; → ce qui a été lu."""
        dernier = {}

        def essai():
            dernier["v"] = lire()
            return condition(dernier["v"])
        if not attendre(essai, 10, 0.1):
            self.fail(f"jamais enregistré : {quoi}\n{json.dumps(dernier.get('v'), ensure_ascii=False)[:900]}")
        return dernier["v"]

    def annonce(self, texte):
        self.nav.attendre(f"[...document.querySelectorAll('#annonces .annonce')].some((a) => a.textContent === {json.dumps(texte)})",
                          quoi=f"annonce « {texte} »")

    def encre(self, pid, x, y, largeur=595.28):
        """Opacité de l'encre (0 à 255) autour du point (x, y) de la page, en points PDF."""
        return self.nav.evaluer(f"""(() => {{ const c = document.querySelector('.feuille[data-page="{pid}"] canvas.encre');
            const s = c.width / {largeur}; const d = c.getContext('2d').getImageData(Math.round({x} * s) - 3, Math.round({y} * s) - 3, 7, 7).data;
            let m = 0; for (let i = 3; i < d.length; i += 4) m = Math.max(m, d[i]); return m; }})()""")

    def ids(self, page):
        return [t["id"] for t in page["traits"]]

    def retarder_envois(self, secondes):
        """Les pages envoyées au serveur (PUT …/pages/…) mettent `secondes` à partir, comme sur une
        connexion lente ; les lectures passent tout de suite. → fonction qui arrête le retard."""
        nav = self.nav
        nav.ordre("Fetch.enable", page=True, patterns=[{"urlPattern": "*/api/notes/*/pages/*", "requestStage": "Request"}])
        fini = threading.Event()
        vus = set()

        def relayer():
            while not fini.is_set():
                with nav.etat:
                    pauses = [e for e in nav.evenements if e["method"] == "Fetch.requestPaused" and e["params"]["requestId"] not in vus]
                for e in pauses:
                    vus.add(e["params"]["requestId"])
                    lent = e["params"]["request"]["method"] == "PUT"
                    threading.Timer(secondes if lent else 0, lambda r=e["params"]["requestId"]: nav.ordre(
                        "Fetch.continueRequest", page=True, requestId=r)).start()
                time.sleep(0.02)
        threading.Thread(target=relayer, daemon=True).start()

        def arreter():
            fini.set()
            nav.ordre("Fetch.disable", page=True)
        return arreter

    def sans_souci(self, tolerer=()):
        self.assertEqual(self.nav.soucis(tolerer), [], "erreurs relevées dans le navigateur")
        texte = self.nav.texte()
        for mot in ("null", "undefined", "NaN", "[object"):
            self.assertNotIn(mot, texte, "une valeur absente s'affiche en toutes lettres")

    # ---------------------------------------------------------------------------------------------
    def test_premier_carnet(self):
        ancien = self.srv.home / "Notes" / "Smoky Notes" / "nb1"
        ancien.mkdir(parents=True)
        (ancien / "notebook.json").write_text("{}")
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelector('.invitation h2')?.textContent === 'ton premier carnet'", quoi="invitation au premier carnet")
        nav.attendre("document.querySelector('.anciens-carnets h2')?.textContent === \"carnets d'avant\"", quoi="rappel des carnets d'avant")
        nav.capture("notes-vide")
        self.srv.vider()
        nav.cliquer("Ouvrir l'ancien Smoky Notes")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-notes"]])
        self.annonce("L'ancien Smoky Notes s'ouvre dans sa fenêtre.")
        nav.cliquer("Nouveau carnet", dans="document.querySelector('.invitation')")
        nav.attendre("document.querySelector('dialog.nouveau-carnet[open]') !== null")
        self.assertEqual(nav.evaluer("document.activeElement.getAttribute('aria-label')"), "Nom du carnet", "le curseur est dans le nom")
        # une matière choisie comme classeur donne son nom au carnet et son papier habituel (Algèbre : quadrillé)
        nav.evaluer("""(() => { const c = document.querySelector('dialog.nouveau-carnet input[aria-label="Classeur"]');
            c.value = 'Algèbre'; c.dispatchEvent(new Event('change')); })()""")
        self.assertEqual(nav.evaluer("document.querySelector('dialog.nouveau-carnet input[aria-label=\"Nom du carnet\"]').value"), "Algèbre")
        self.assertEqual(nav.evaluer("[...document.querySelectorAll('dialog.nouveau-carnet [aria-pressed=true]')].map((b) => b.textContent || b.getAttribute('aria-label'))"),
                         ["Quadrillé", "Blanc", "A4", "Couverture Fumée"])
        nav.cliquer("Ivoire", dans="document.querySelector('dialog.nouveau-carnet')")
        nav.cliquer("Couverture Encre", dans="document.querySelector('dialog.nouveau-carnet')")
        self.assertEqual(nav.evaluer("document.querySelector('.apercu-papier').dataset.modele"), "carreaux", "l'aperçu montre le papier choisi")
        nav.capture("notes-nouveau")
        nav.cliquer("Créer", dans="document.querySelector('dialog.nouveau-carnet')")
        nav.attendre("location.hash.startsWith('#/notes/c/') && document.querySelector('.titre-carnet')?.value === 'Algèbre'", quoi="le carnet s'ouvre")
        [c] = self.carnets()
        self.assertEqual((c["titre"], c["classeur"], c["couverture"], c["papier"]["modele"], c["papier"]["couleur"]),
                         ("Algèbre", "Algèbre", "encre", "carreaux", "ivoire"))
        self.assertEqual(self.carnet_serveur(c["id"])["papier"], {"format": "a4", "modele": "carreaux", "couleur": "ivoire"})
        nav.cliquer("Revenir aux carnets")
        nav.attendre("location.hash === '#/notes' && document.querySelectorAll('.carnet').length === 1")
        self.assertEqual(nav.evaluer("document.querySelector('.carnet .ouvrir').getAttribute('aria-label')"), "Ouvrir Algèbre, Algèbre, 1 page, à l'instant")
        self.assertFalse(nav.evaluer("!!document.querySelector('.invitation')"))
        self.sans_souci()

    def test_ecrire_annuler_retablir(self):
        c = self.creer("Méca")
        pid = self.editeur(c)
        nav = self.nav
        x, y, w, _ = self.feuille(pid)
        z = w / 595.28
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        self.stylo(vague(x + 100, y + 150))
        self.stylo([(x + 100 + i * 4, y + 220) for i in range(40)], pression=0.9)
        t1, t2 = self.enregistre(lire, lambda p: len(p["traits"]) == 2, "les deux traits")["traits"]
        self.assertEqual((t1["outil"], t1["couleur"], t1["largeur"]), ("stylo", "#141417", 2))
        self.assertAlmostEqual(t1["points"][0], 100 / z, delta=1.5, msg="les points sont dans l'unité de la page, pas de l'écran")
        self.assertAlmostEqual(t1["points"][1], 150 / z, delta=1.5)
        self.assertTrue(all(abs(p - 0.6) < 0.05 for p in t1["points"][2::3]), "la pression du stylet est gardée")
        self.assertTrue(all(abs(p - 0.9) < 0.05 for p in t2["points"][2::3]))
        self.assertGreater(self.encre(pid, 180 / z, 220 / z), 200, "le trait est peint")
        self.assertEqual(nav.evaluer("document.querySelector('.etat-enregistrement').textContent"), "Enregistré")
        nav.capture("notes-editeur")
        nav.cliquer("Annuler")
        self.enregistre(lire, lambda p: self.ids(p) == [t1["id"]], "annulé : il reste le premier trait")
        self.raccourci("z", 90, ctrl=True)
        self.enregistre(lire, lambda p: p["traits"] == [], "Ctrl+Z : page vide")
        self.assertLess(self.encre(pid, 180 / z, 220 / z), 30, "la page est effacée à l'écran aussi")
        self.raccourci("z", 90, ctrl=True, maj=True)
        self.enregistre(lire, lambda p: self.ids(p) == [t1["id"]], "Ctrl+Maj+Z : rétabli")
        nav.cliquer("Rétablir")
        self.enregistre(lire, lambda p: self.ids(p) == [t1["id"], t2["id"]], "tout rétabli")
        self.assertTrue(nav.evaluer("document.querySelector('[aria-label=\"Rétablir\"]').disabled"))
        self.sans_souci()

    def test_surligneur_et_gommes(self):
        c = self.creer("Bio")
        pid = self.editeur(c)
        nav = self.nav
        x, y, w, _ = self.feuille(pid)
        z = w / 595.28
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        nav.cliquer("Surligneur")
        self.stylo([(x + 80 + i * 6, y + 300) for i in range(40)])
        [s] = self.enregistre(lire, lambda p: len(p["traits"]) == 1, "trait de surligneur")["traits"]
        self.assertEqual((s["outil"], s["couleur"], s["largeur"]), ("surligneur", "#ffe45c", 14))
        # la gomme « trait entier » efface tout ce qu'elle touche
        nav.cliquer("Gomme")
        self.assertEqual(self.feuille(pid)[:2], [x, y], "changer d'outil ne déplace pas la page sous le stylet")
        self.stylo([(x + 150, y + 280 + i * 4) for i in range(12)])
        self.enregistre(lire, lambda p: p["traits"] == [], "surligneur gommé")
        nav.cliquer("Annuler")
        self.enregistre(lire, lambda p: self.ids(p) == [s["id"]], "gomme annulée")
        # la gomme précise coupe le trait là où elle passe
        nav.cliquer("Stylo")
        self.stylo([(x + 80 + i * 6, y + 420) for i in range(50)])
        trait = self.enregistre(lire, lambda p: len(p["traits"]) == 2, "trait au stylo")["traits"][1]
        nav.cliquer("Gomme")
        nav.cliquer("Précise")
        self.assertEqual(nav.evaluer("document.querySelector('.bascule-mode').getAttribute('aria-pressed')"), "true")
        self.stylo([(x + 250, y + 395 + i * 5) for i in range(11)])
        p = self.enregistre(lire, lambda p: len(p["traits"]) == 3, "trait coupé en deux")
        gauche, droite = sorted((t for t in p["traits"] if t["outil"] == "stylo"), key=lambda t: t["points"][0])
        self.assertLess(max(gauche["points"][0::3]), 250 / z - 3)
        self.assertGreater(min(droite["points"][0::3]), 250 / z + 3)
        self.assertLess(self.encre(pid, 250 / z, 420 / z), 30, "le passage de la gomme est vide à l'écran")
        nav.cliquer("Annuler")
        self.enregistre(lire, lambda p: sorted(self.ids(p)) == sorted([s["id"], trait["id"]]), "coupe annulée : le trait revient entier")
        self.enregistre(lambda: self.srv.json("GET", "/api/notes")[1]["preferences"], lambda r: r.get("gomme", {}).get("precise") is True,
                        "la gomme précise est retenue pour la prochaine fois")
        # un réglage changé juste avant de quitter le carnet est gardé aussi
        nav.cliquer("Précise")
        nav.cliquer("Revenir aux carnets")
        self.enregistre(lambda: self.srv.json("GET", "/api/notes")[1]["preferences"], lambda r: r.get("gomme", {}).get("precise") is False,
                        "réglage changé à l'instant de partir")
        self.sans_souci()

    def test_lasso(self):
        c = self.creer("Chimie")
        pid = self.editeur(c)
        nav = self.nav
        x, y, w, _ = self.feuille(pid)
        z = w / 595.28
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        self.stylo(vague(x + 200, y + 200, n=20))
        [t] = self.enregistre(lire, lambda p: len(p["traits"]) == 1, "trait")["traits"]
        nav.cliquer("Lasso")
        cx, cy = x + 240, y + 200
        self.stylo([(cx + 90 * math.cos(a * math.pi / 10), cy + 50 * math.sin(a * math.pi / 10)) for a in range(21)])
        nav.attendre("document.querySelector('.boite-selection') !== null && document.querySelector('.menu-selection') !== null", quoi="sélection et son menu")
        nav.capture("notes-lasso")
        # glisser la sélection : 80 px à droite, 60 px plus bas
        bx, by = nav.evaluer("(() => { const r = document.querySelector('.boite-selection').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        self.stylo([(bx + i * 8, by + i * 6) for i in range(11)])
        p = self.enregistre(lire, lambda p: p["traits"] and abs(p["traits"][0]["points"][0] - t["points"][0] - 80 / z) < 1.5, "trait déplacé")
        self.assertAlmostEqual(p["traits"][0]["points"][1] - t["points"][1], 60 / z, delta=1.5)
        self.assertEqual(p["traits"][0]["id"], t["id"], "c'est le même trait, déplacé")
        nav.cliquer("Supprimer la sélection")
        self.enregistre(lire, lambda p: p["traits"] == [], "sélection supprimée")
        self.raccourci("z", 90, ctrl=True)
        self.enregistre(lire, lambda p: self.ids(p) == [t["id"]], "suppression annulée")
        self.sans_souci()

    def test_texte(self):
        c = self.creer("Maths")
        pid = self.editeur(c)
        nav = self.nav
        x, y, w, _ = self.feuille(pid)
        z = w / 595.28
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        nav.cliquer("Texte")
        self.stylo([(x + 120, y + 300)] * 2, genre="mouse")
        nav.attendre("document.activeElement?.classList.contains('zone-texte')", quoi="zone de texte prête")
        nav.ordre("Input.insertText", page=True, text="Théorème de Pythagore")
        nav.touche("Escape", 27)
        [t] = self.enregistre(lire, lambda p: len(p["textes"]) == 1, "texte")["textes"]
        self.assertEqual((t["texte"], t["taille"], t["couleur"]), ("Théorème de Pythagore", 16, "#141417"))
        self.assertAlmostEqual(t["x"], 120 / z, delta=1.5)
        # un deuxième texte, puis toucher ailleurs : le deuxième est gardé (pas perdu en ouvrant le troisième)
        self.stylo([(x + 120, y + 400)] * 2, genre="mouse")
        nav.attendre("document.activeElement?.classList.contains('zone-texte') && document.activeElement.value === ''")
        nav.ordre("Input.insertText", page=True, text="a² + b² = c²")
        self.stylo([(x + 120, y + 520)] * 2, genre="mouse")
        nav.attendre("document.querySelectorAll('.zone-texte').length === 1 && document.activeElement.value === ''", quoi="une seule zone ouverte, la nouvelle")
        nav.touche("Escape", 27)
        self.enregistre(lire, lambda p: sorted(x["texte"] for x in p["textes"]) == sorted(["a² + b² = c²", "Théorème de Pythagore"]), "deux textes")
        # retoucher un texte le rouvre ; vidé, il disparaît
        self.stylo([(x + 124, y + 300)] * 2, genre="mouse")
        nav.attendre("document.activeElement?.value === 'Théorème de Pythagore'", quoi="le texte se rouvre")
        nav.evaluer("document.activeElement.value = ''")
        nav.touche("Escape", 27)
        self.enregistre(lire, lambda p: [x["texte"] for x in p["textes"]] == ["a² + b² = c²"], "texte vidé, retiré")
        self.sans_souci()

    def test_pages_et_signets(self):
        c = self.creer("Physique")
        self.editeur(c)
        nav = self.nav
        lire = lambda: self.carnet_serveur(c["id"])  # noqa: E731

        def menu(entree):
            nav.cliquer("Plus d'options")
            nav.attendre("document.querySelector('dialog.menu-notes[open]') !== null")
            nav.cliquer(entree, dans="document.querySelector('dialog.menu-notes')")
        menu("Ajouter une page après celle-ci")
        p1, p2 = self.enregistre(lire, lambda x: len(x["pages"]) == 2, "page ajoutée")["pages"]
        self.assertEqual((p2["modele"], p2["couleur"], p2["w"]), (p1["modele"], p1["couleur"], p1["w"]), "même papier que la page d'avant")
        nav.attendre("document.querySelector('.numero-page').textContent === '2 / 2'", quoi="la nouvelle page est à l'écran")
        menu("Poser un signet sur cette page")
        self.annonce("Signet posé sur la page 2.")
        self.enregistre(lire, lambda x: x["pages"][1]["signet"] is True, "signet")
        menu("Quadrillé")
        self.enregistre(lire, lambda x: x["pages"][1]["modele"] == "carreaux", "papier de la page changé")
        nav.cliquer("Pages")
        nav.attendre("document.querySelectorAll('.miniature').length === 2")
        self.assertEqual(nav.evaluer("[...document.querySelectorAll('.miniature')].map((b) => b.getAttribute('aria-label'))"),
                         ["Aller à la page 1", "Aller à la page 2 (signet)"])
        nav.cliquer("Signets")
        nav.attendre("document.querySelectorAll('.miniature').length === 1")
        nav.capture("notes-pages")
        nav.cliquer("Signets")
        nav.cliquer("Aller à la page 1")
        nav.attendre("document.querySelector('.numero-page').textContent === '1 / 2'")
        nav.cliquer("Aller à la page 2 (signet)")
        nav.attendre("document.querySelector('.numero-page').textContent === '2 / 2'")
        self.prete(p2["id"])
        # une page écrite ne part qu'après confirmation, avec son fichier
        x, y, _, _ = self.feuille(p2["id"])
        self.stylo(vague(x + 100, y + 120))
        self.enregistre(lambda: self.page_serveur(c["id"], p2["id"]), lambda p: len(p["traits"]) == 1, "page 2 écrite")
        fichier = self.srv.home / "Notes" / "Carnets" / c["id"] / "pages" / f"{p2['id']}.json"
        self.assertTrue(fichier.is_file())
        menu("Supprimer cette page")
        nav.attendre("document.querySelector('dialog[open] h2')?.textContent === 'Supprimer la page 2 ?'")
        nav.cliquer("Supprimer la page", dans="document.querySelector('dialog[open]')")
        self.enregistre(lire, lambda x: [p["id"] for p in x["pages"]] == [p1["id"]], "page supprimée")
        self.assertFalse(fichier.exists(), "son fichier part avec elle")
        menu("Supprimer cette page")
        self.annonce("Un carnet garde au moins une page.")
        self.sans_souci()

    def pdf_d_essai(self, pages=2):
        """Un vrai PDF A4 de deux pages, fabriqué par Chrome lui-même."""
        html = ("<style>@page { size: A4; margin: 0 } body { margin: 0; font: 46px sans-serif; color: #000 }"
                " section { padding: 70px } section + section { break-before: page }</style>"
                + "".join(f"<section><h1>Chapitre {i + 1}</h1><p>Énergie cinétique</p></section>" for i in range(pages)))
        self.nav.aller("data:text/html;charset=utf-8," + urllib.parse.quote(html))
        self.nav.attendre("document.readyState === 'complete' && document.querySelectorAll('section').length > 0")
        donnees = base64.b64decode(self.nav.ordre("Page.printToPDF", page=True, preferCSSPageSize=True)["data"])
        fichier = self.srv.base / "cours de méca.pdf"
        fichier.write_bytes(donnees)
        return fichier

    def test_pdf_importe_annote_exporte(self):
        fichier = self.pdf_d_essai()
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelector('.invitation') !== null")
        objet = nav.ordre("Runtime.evaluate", page=True, expression="document.querySelector('.notes-biblio input[type=file]')")["result"]["objectId"]
        nav.ordre("DOM.setFileInputFiles", page=True, files=[str(fichier)], objectId=objet)
        nav.attendre("location.hash.startsWith('#/notes/c/') && document.querySelector('.feuille') !== null", delai=30, quoi="le PDF devient un carnet")
        [c] = self.carnets()
        self.assertEqual((c["titre"], c["pages"], c["pdf"]), ("cours de méca", 2, True))
        p1, p2 = self.carnet_serveur(c["id"])["pages"]
        self.assertEqual(([p1["fond"]["page"], p2["fond"]["page"]], p1["fond"]["pdf"]), ([0, 1], p2["fond"]["pdf"]))
        self.assertRegex(p1["fond"]["pdf"], r"^[0-9a-f]{24}\.pdf$")
        self.assertEqual((round(p1["w"]), round(p1["h"])), (595, 842), "format de la page du PDF (A4)")
        garde = self.srv.home / "Notes" / "Carnets" / c["id"] / "fichiers" / p1["fond"]["pdf"]
        self.assertEqual(garde.read_bytes(), fichier.read_bytes(), "le PDF est gardé tel quel")
        nav.attendre(f"""(() => {{ const c = document.querySelector('.feuille[data-page="{p1['id']}"] canvas.fond'); if (!c || !c.width) return false;
            const d = c.getContext('2d').getImageData(0, 0, c.width, Math.round(c.height / 4)).data;
            let sombres = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 90 && d[i + 1] < 90 && d[i + 2] < 90) sombres++;
            return sombres > 400; }})()""", delai=30, quoi="la page du PDF est peinte (titre en noir)")
        nav.capture("notes-pdf")
        # annoter la première page, puis exporter le carnet
        self.prete(p1["id"])
        x, y, w, _ = self.feuille(p1["id"])
        z = w / p1["w"]
        self.stylo([(x + 100 + i * 5, y + 420) for i in range(60)], pression=0.8)
        self.enregistre(lambda: self.page_serveur(c["id"], p1["id"]), lambda p: len(p["traits"]) == 1, "annotation")
        nav.cliquer("Plus d'options")
        nav.cliquer("Exporter en PDF (dans Notes/PDF)", dans="document.querySelector('dialog.menu-notes')")
        self.annonce("PDF enregistré dans Notes/PDF/cours de méca.pdf.")
        exporte = (self.srv.home / "Notes" / "PDF" / "cours de méca.pdf").read_bytes()
        self.assertEqual(exporte[:5], b"%PDF-")
        # relu par PDF.js : deux pages, le texte du cours y est encore, l'annotation aussi, là où elle a été écrite
        relu = nav.evaluer(f"""(async () => {{
            const pdfjs = await import('/vendor/pdf.min.mjs');
            pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdf.worker.min.mjs';
            const octets = Uint8Array.from(atob({json.dumps(base64.b64encode(exporte).decode())}), (c) => c.charCodeAt(0));
            const doc = await pdfjs.getDocument({{ data: octets, isEvalSupported: false }}).promise;
            const page = await doc.getPage(1);
            const texte = (await page.getTextContent()).items.map((i) => i.str).join(' ');
            const vue = page.getViewport({{ scale: 1 }});
            const toile = document.createElement('canvas');
            toile.width = Math.round(vue.width); toile.height = Math.round(vue.height);
            await page.render({{ canvasContext: toile.getContext('2d'), viewport: vue }}).promise;
            const encre = (x, y) => {{ const d = toile.getContext('2d').getImageData(Math.round(x), Math.round(y) - 4, 1, 9).data;
                let s = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 110 && d[i + 1] < 110 && d[i + 2] < 110) s++; return s; }};
            return {{ pages: doc.numPages, texte, ecrit: encre({250 / z}, {420 / z}), vide: encre({250 / z}, {520 / z}) }};
        }})()""")
        self.assertEqual(relu["pages"], 2)
        self.assertIn("Chapitre 1", relu["texte"])
        self.assertGreater(relu["ecrit"], 0, "l'annotation est dans le PDF exporté")
        self.assertEqual(relu["vide"], 0)
        self.sans_souci()

    def test_bibliotheque(self):
        self.creer("Algèbre linéaire", classeur="Algèbre")
        self.creer("Brouillon")
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.carnet').length === 2")

        def menu(titre, entree):
            nav.cliquer(f"Options de {titre}")
            nav.attendre("document.querySelector('dialog.menu-notes[open]') !== null")
            nav.cliquer(entree, dans="document.querySelector('dialog.menu-notes')")

        def resume(titre):
            return next((x for x in self.carnets() if x["titre"] == titre), None)
        menu("Brouillon", "Ajouter aux favoris")
        self.enregistre(lambda: resume("Brouillon"), lambda x: x["favori"], "favori")
        nav.attendre("document.querySelectorAll('.carnet .favori').length === 1")
        nav.cliquer("Favoris")
        nav.attendre("location.hash === '#/notes/favoris' && document.querySelectorAll('.carnet').length === 1")
        nav.cliquer("Tous")
        nav.attendre("location.hash === '#/notes' && document.querySelectorAll('.carnet').length === 2")
        menu("Brouillon", "Renommer")
        nav.attendre("document.querySelector('dialog.demande[open]') !== null")
        nav.ecrire("dialog.demande input", "Brouillon de méca")
        nav.cliquer("Renommer", dans="document.querySelector('dialog.demande')")
        self.enregistre(lambda: resume("Brouillon de méca"), lambda x: x is not None, "renommé")
        nav.attendre("[...document.querySelectorAll('.carnet .titre')].some((t) => t.textContent === 'Brouillon de méca')")
        menu("Brouillon de méca", "Ranger dans un classeur")
        nav.ecrire("dialog.demande input", "MNA")
        nav.cliquer("Ranger", dans="document.querySelector('dialog.demande')")
        self.enregistre(lambda: resume("Brouillon de méca"), lambda x: x["classeur"] == "MNA", "rangé")
        menu("Brouillon de méca", "Couverture Braise")
        self.enregistre(lambda: resume("Brouillon de méca"), lambda x: x["couverture"] == "braise", "couverture")
        menu("Brouillon de méca", "Dupliquer")
        self.enregistre(self.carnets, lambda x: len(x) == 3, "dupliqué")
        nav.attendre("document.querySelectorAll('.carnet').length === 3")
        nav.ecrire("input.recherche", "méca")
        nav.attendre("document.querySelectorAll('.carnet').length === 2", quoi="la recherche filtre")
        self.assertTrue(nav.evaluer("document.activeElement.classList.contains('recherche')"), "le curseur reste dans la recherche")
        nav.ecrire("input.recherche", "")
        nav.attendre("document.querySelectorAll('.carnet').length === 3")
        nav.capture("notes-bibliotheque")
        corbeille_1 = "[...document.querySelectorAll('.segment button')].some((b) => b.textContent === 'Corbeille (1)')"
        menu("Brouillon de méca (copie)", "Mettre à la corbeille")
        self.annonce("Carnet mis à la corbeille.")
        nav.attendre(f"document.querySelectorAll('.carnet').length === 2 && {corbeille_1}")
        nav.cliquer("Corbeille (1)")
        nav.attendre("document.querySelectorAll('.liste-corbeille li').length === 1")
        nav.cliquer("Restaurer")
        nav.attendre("document.querySelector('.vide-liste')?.textContent === 'La corbeille est vide.'")
        nav.cliquer("Tous")
        nav.attendre("document.querySelectorAll('.carnet').length === 3")
        menu("Brouillon de méca (copie)", "Mettre à la corbeille")
        nav.attendre(corbeille_1)
        nav.cliquer("Corbeille (1)")
        nav.attendre("document.querySelectorAll('.liste-corbeille li').length === 1")
        nav.cliquer("Effacer")
        nav.attendre("document.querySelector('dialog[open] h2')?.textContent.startsWith('Effacer « Brouillon de méca (copie) »')")
        nav.cliquer("Effacer", dans="document.querySelector('dialog[open]')")
        nav.attendre("document.querySelector('.vide-liste')?.textContent === 'La corbeille est vide.'")
        self.assertEqual(self.srv.json("GET", "/api/notes")[1]["corbeille"], [])
        self.sans_souci()

    def test_classeurs(self):
        for i in range(4):
            self.creer(f"Algèbre {i + 1}", classeur="Algèbre")
        for i in range(2):
            self.creer(f"BDR {i + 1}", classeur="BDR")
        self.creer("Idées")
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('section.classeur').length === 3", quoi="derniers carnets, classeurs, sans classeur")
        self.assertEqual(nav.evaluer("[...document.querySelectorAll('section.classeur h2')].map((h) => h.textContent)"),
                         ["derniers carnets", "classeurs", "sans classeur"])
        self.assertEqual(sorted(nav.evaluer("[...document.querySelectorAll('.dossier .ouvrir')].map((a) => a.getAttribute('aria-label'))")),
                         ["Classeur Algèbre, 4 carnets", "Classeur BDR, 2 carnets"])
        nav.capture("notes-classeurs")
        nav.evaluer("[...document.querySelectorAll('.dossier .ouvrir')].find((a) => a.getAttribute('aria-label').startsWith('Classeur Algèbre')).click()")
        nav.attendre("location.hash === '#/notes/classeur/Alg%C3%A8bre' && document.querySelectorAll('.carnet').length === 4")
        self.assertEqual(nav.evaluer("document.querySelector('.entete .sous').textContent"), "classeur Algèbre")
        nav.cliquer("Nouveau carnet")
        nav.attendre("document.querySelector('dialog.nouveau-carnet[open]') !== null")
        self.assertEqual(nav.evaluer("document.querySelector('dialog.nouveau-carnet input[aria-label=\"Classeur\"]').value"), "Algèbre",
                         "un carnet créé depuis un classeur y est rangé")
        nav.touche("Escape", 27)
        nav.attendre("document.querySelector('dialog.nouveau-carnet') === null")
        nav.cliquer("Tous les carnets")
        nav.attendre("location.hash === '#/notes' && document.querySelectorAll('section.classeur').length === 3")
        # un classeur sans carnet (venu de l'agenda) invite à en créer un
        nav.evaluer("location.hash = '#/notes/classeur/Optique'")
        nav.attendre("document.querySelector('.vide-liste')?.textContent === 'Ce classeur est vide.'")
        self.assertIn("Nouveau carnet dans Optique", nav.texte())
        self.sans_souci()

    def test_petit_ecran(self):
        c = self.creer("Algèbre", classeur="Algèbre")
        self.nav.taille(760, 1000)
        self.ouvrir()
        nav = self.nav
        nav.attendre("document.querySelectorAll('.carnet').length === 1")
        self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 760, "pas de défilement horizontal")
        petits = nav.evaluer("""[...document.querySelectorAll('.bouton, .segment button, .carnet .options')]
            .filter((e) => e.offsetParent !== null).map((e) => [e.textContent.trim() || e.getAttribute('aria-label'), Math.round(e.getBoundingClientRect().height)])
            .filter(([, h]) => h < 44)""")
        self.assertEqual(petits, [], "commandes trop petites pour le doigt")
        nav.capture("notes-etroit")
        nav.evaluer(f"location.hash = '#/notes/c/{c['id']}'")
        self.prete(c["pages"][0]["id"])
        self.assertLessEqual(nav.evaluer("document.documentElement.scrollWidth"), 760)
        petits = nav.evaluer("""[...document.querySelectorAll('.barre-notes button')]
            .filter((e) => e.offsetParent !== null).map((e) => [e.textContent.trim() || e.getAttribute('aria-label'), Math.round(e.getBoundingClientRect().height)])
            .filter(([, h]) => h < 44)""")
        self.assertEqual(petits, [], "outils trop petits pour le doigt")
        dehors = nav.evaluer("""[...document.querySelectorAll('.barre-notes .rangee-haut button, .barre-notes > * > .icone-seule')]
            .filter((e) => e.getBoundingClientRect().right > innerWidth + 0.5).map((e) => e.getAttribute('aria-label'))""")
        self.assertEqual(dehors, [], "toute la barre tient dans la fenêtre")
        place = self.feuille(c["pages"][0]["id"])
        for outil in ("Gomme", "Lasso", "Surligneur", "Stylo"):
            nav.cliquer(outil)
            self.assertEqual(self.feuille(c["pages"][0]["id"]), place, f"{outil} : la page ne bouge pas en changeant d'outil")
        x, _, w, _ = self.feuille(c["pages"][0]["id"])
        self.assertGreater(w, 560, "la page prend la largeur disponible")
        self.assertLessEqual(x + w, 760, "la page entière est visible en largeur")
        nav.capture("notes-editeur-etroit")
        self.sans_souci()

    def test_doigts(self):
        c = self.creer("Méca")
        pid = self.editeur(c)
        nav = self.nav
        nav.cliquer("Plus d'options")
        nav.cliquer("Ajouter une page après celle-ci", dans="document.querySelector('dialog.menu-notes')")
        nav.evaluer("document.querySelector('.feuilles').scrollTop = 0")
        x, y, w, _ = self.feuille(pid)
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        # un doigt fait défiler, sans écrire
        avant = nav.evaluer("document.querySelector('.feuilles').scrollTop")
        self.doigts([[(x + 300, y + 560)], [(x + 300, y + 480)], [(x + 300, y + 400)], [(x + 300, y + 320)], []])
        self.assertGreater(nav.evaluer("document.querySelector('.feuilles').scrollTop"), avant + 150, "la page a défilé")
        self.assertEqual(lire()["traits"], [], "le doigt n'écrit pas (sauf réglage « Écrire au doigt »)")
        # le défilement continue sur sa lancée puis s'arrête
        self.assertTrue(attendre(lambda: (lambda a: (time.sleep(0.25), nav.evaluer("document.querySelector('.feuilles').scrollTop") == a)[1])(
            nav.evaluer("document.querySelector('.feuilles').scrollTop")), 8), "l'élan s'arrête")
        nav.evaluer("document.querySelector('.feuilles').scrollTop = 0")
        x, y, w, _ = self.feuille(pid)
        self.stylo(vague(x + 100, y + 150))
        # la main posée juste après le stylet (la paume) ne fait rien : ni défilement, ni annulation
        self.doigts([[(x + 300, y + 300), (x + 420, y + 300)], []])
        self.doigts([[(x + 300, y + 500)], [(x + 300, y + 400)], [(x + 300, y + 300)], []])
        self.assertEqual(nav.evaluer("document.querySelector('.feuilles').scrollTop"), 0, "la paume ne fait pas défiler")
        [t] = self.enregistre(lire, lambda p: len(p["traits"]) == 1, "trait au stylet")["traits"]
        time.sleep(0.8)                                   # la paume n'est plus ignorée
        self.assertEqual(self.ids(lire()), [t["id"]], "la paume n'a rien annulé")
        self.doigts([[(x + 300, y + 300), (x + 420, y + 300)], []])
        self.enregistre(lire, lambda p: p["traits"] == [], "toucher à deux doigts : annulé")
        self.doigts([[(x + 300, y + 300), (x + 420, y + 300), (x + 360, y + 380)], []])
        self.enregistre(lire, lambda p: self.ids(p) == [t["id"]], "toucher à trois doigts : rétabli")
        # avec « Écrire au doigt », un doigt écrit
        nav.cliquer("Écrire au doigt")
        self.doigts([[(x + 100 + i * 5, y + 260)] for i in range(30)] + [[]])
        self.enregistre(lire, lambda p: len(p["traits"]) == 2, "trait au doigt")
        self.sans_souci()

    def test_son_relie_a_l_ecriture(self):
        c = self.creer("Cours magistral")
        pid = self.editeur(c)
        nav = self.nav
        x, y, _, _ = self.feuille(pid)
        nav.cliquer("Enregistrer le son")
        self.annonce("Enregistrement en cours : ce que tu écris est relié au son.")
        time.sleep(1.5)
        self.stylo(vague(x + 100, y + 200))
        time.sleep(1)
        nav.cliquer("Arrêter l'enregistrement")
        self.annonce("Enregistrement gardé. Avec « Écouter », touche ce que tu as écrit pour réentendre ce moment.")
        [son] = self.enregistre(lambda: self.carnet_serveur(c["id"]), lambda x: len(x.get("sons", [])) == 1, "enregistrement")["sons"]
        self.assertGreater(son["duree"], 2000)
        fichier = self.srv.home / "Notes" / "Carnets" / c["id"] / "fichiers" / son["fichier"]
        self.assertEqual(fichier.read_bytes()[:4], b"\x1a\x45\xdf\xa3", "un vrai fichier WebM")
        [t] = self.enregistre(lambda: self.page_serveur(c["id"], pid), lambda p: len(p["traits"]) == 1, "trait")["traits"]
        self.assertEqual(t["son"], son["id"])
        self.assertGreater(t["ts"], 1000, "le moment de l'enregistrement où le trait a été écrit")
        nav.cliquer("Écouter")
        self.stylo([(x + 100, y + 200)] * 2)
        nav.attendre("!document.querySelector('.barre-lecture').hidden", quoi="la lecture commence au moment du trait")
        nav.cliquer("Fermer la lecture")
        self.sans_souci()

    def test_rien_ne_se_perd_en_changeant_de_page(self):
        c = self.creer("Méca")
        pid = self.editeur(c)
        nav = self.nav
        x, y, w, _ = self.feuille(pid)
        z = w / 595.28
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        self.stylo(vague(x + 100, y + 150))
        nav.cliquer("Agenda", dans="document.querySelector('#rail')")          # avant que l'enregistrement ne parte de lui-même
        nav.attendre("document.querySelector('#page h1')?.textContent === 'agenda'")
        self.enregistre(lire, lambda p: len(p["traits"]) == 1, "enregistré en quittant le carnet")
        nav.evaluer(f"location.hash = '#/notes/c/{c['id']}'")
        self.prete(pid)
        self.assertGreater(self.encre(pid, 180 / z, 150 / z), 150, "le trait est là au retour")
        # partir et revenir aussitôt, l'envoi étant lent : le carnet n'est relu qu'une fois enregistré
        x, y, w, _ = self.feuille(pid)
        self.addCleanup(self.retarder_envois(1.5))
        self.stylo(vague(x + 100, y + 300))
        nav.evaluer(f"location.hash = '#/agenda'; setTimeout(() => {{ location.hash = '#/notes/c/{c['id']}'; }}, 0); true")
        nav.attendre(f"location.hash === '#/notes/c/{c['id']}'")
        self.prete(pid)
        self.assertGreater(self.encre(pid, 180 / z, 300 / z), 150, "le deuxième trait est là aussi")
        self.enregistre(lire, lambda p: len(p["traits"]) == 2, "les deux traits")
        self.sans_souci()

    def test_formes_et_gribouillis(self):
        c = self.creer("Géométrie")
        pid = self.editeur(c)
        nav = self.nav
        x, y, w, _ = self.feuille(pid)
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        # un rectangle tremblé, le stylet gardé immobile une demi-seconde au bout : rectangle parfait
        tour = [(x + 100 + i * 12, y + 100 + (i % 2)) for i in range(16)] + [(x + 290 + (i % 2), y + 100 + i * 8) for i in range(16)]
        tour += [(x + 290 - i * 12, y + 228 + (i % 2)) for i in range(16)] + [(x + 100 + (i % 2), y + 228 - i * 8) for i in range(17)]
        nav.ordre("Input.dispatchMouseEvent", page=True, type="mousePressed", x=tour[0][0], y=tour[0][1], button="left", buttons=1, clickCount=1, pointerType="pen", force=0.5)
        for px, py in tour[1:]:
            nav.ordre("Input.dispatchMouseEvent", page=True, type="mouseMoved", x=px, y=py, button="left", buttons=1, pointerType="pen", force=0.5)
        time.sleep(0.8)
        nav.ordre("Input.dispatchMouseEvent", page=True, type="mouseReleased", x=tour[-1][0], y=tour[-1][1], button="left", buttons=0, clickCount=1, pointerType="pen")
        [r] = self.enregistre(lire, lambda p: len(p["traits"]) == 1, "forme")["traits"]
        self.assertEqual((r.get("forme"), r.get("ferme")), ("rectangle", True))
        self.assertLessEqual(len(r["points"]) // 3, 5, "quatre coins, pas des dizaines de points tremblés")
        # un mot, puis un gribouillis dessus : le mot part, le gribouillis ne reste pas
        self.stylo(vague(x + 100, y + 400, n=30))
        mot = self.enregistre(lire, lambda p: len(p["traits"]) == 2, "mot écrit")["traits"][1]
        zigzag = [(x + 95 + (i % 2) * 130, y + 385 + i * 1.5) for i in range(24)]
        self.stylo([pt for a, b in zip(zigzag, zigzag[1:]) for pt in [(a[0] + (b[0] - a[0]) * k / 6, a[1] + (b[1] - a[1]) * k / 6) for k in range(6)]])
        self.enregistre(lire, lambda p: self.ids(p) == [r["id"]], "gribouillis : le mot est effacé, rien d'autre")
        nav.cliquer("Annuler")
        self.enregistre(lire, lambda p: sorted(self.ids(p)) == sorted([r["id"], mot["id"]]), "annulé : le mot revient")
        self.sans_souci()

    def test_image_copier_coller_zoom_clavier(self):
        c = self.creer("TP")
        pid = self.editeur(c)
        nav = self.nav
        lire = lambda: self.page_serveur(c["id"], pid)  # noqa: E731
        image = self.srv.base / "schéma.png"
        image.write_bytes(png(120, 60))
        objet = nav.ordre("Runtime.evaluate", page=True, expression="document.querySelector('.editeur input[type=file][accept^=\"image\"]')")["result"]["objectId"]
        nav.ordre("DOM.setFileInputFiles", page=True, files=[str(image)], objectId=objet)
        [im] = self.enregistre(lire, lambda p: len(p["images"]) == 1, "image insérée")["images"]
        self.assertEqual((im["w"], im["h"]), (90, 45), "taille naturelle (75 %), proportions gardées")
        self.assertEqual(self.srv.req("GET", f"/api/notes/{c['id']}/fichiers/{im['fichier']}")[2], image.read_bytes())
        nav.attendre("document.querySelector('.boite-selection') !== null", quoi="l'image arrive sélectionnée")
        self.assertEqual(nav.evaluer("document.querySelector('.outil[aria-pressed=true]').getAttribute('aria-label')"), "Lasso")
        # copier, coller : une seconde image, décalée
        self.raccourci("c", 67, ctrl=True)
        self.raccourci("v", 86, ctrl=True)
        a, b = self.enregistre(lire, lambda p: len(p["images"]) == 2, "image collée")["images"]
        self.assertEqual(a["fichier"], b["fichier"], "le même fichier, pas une copie")
        self.assertNotEqual((a["x"], a["y"]), (b["x"], b["y"]))
        # raccourcis des outils, zoom au clavier
        nav.evaluer("document.querySelector('.feuilles').focus()")
        for touche, code, nom in (("h", 72, "Surligneur"), ("e", 69, "Gomme"), ("t", 84, "Texte"), ("p", 80, "Stylo")):
            self.raccourci(touche, code)
            self.assertEqual(nav.evaluer("document.querySelector('.outil[aria-pressed=true]').getAttribute('aria-label')"), nom)
        largeur = self.feuille(pid)[2]
        for _ in range(2):
            nav.ordre("Input.dispatchKeyEvent", page=True, type="keyDown", key="+", code="Equal", windowsVirtualKeyCode=187, modifiers=2)
            nav.ordre("Input.dispatchKeyEvent", page=True, type="keyUp", key="+", code="Equal", windowsVirtualKeyCode=187, modifiers=2)
        nav.attendre(f"document.querySelector('.feuille').getBoundingClientRect().width > {largeur * 1.3}", quoi="Ctrl + agrandit")
        self.raccourci("0", 48, ctrl=True)
        nav.attendre(f"Math.abs(document.querySelector('.feuille').getBoundingClientRect().width - {largeur}) < 1", quoi="Ctrl+0 : page en largeur")
        self.sans_souci()

    def test_change_ailleurs(self):
        c = self.creer("Méca")
        pid = self.editeur(c)
        trait = {"id": "tailleurs1", "outil": "stylo", "couleur": "#d4392f", "largeur": 3, "points": [v for i in range(30) for v in (60 + i * 5, 300, 0.5)]}
        self.assertEqual(self.srv.json("PUT", f"/api/notes/{c['id']}/pages/{pid}", {"traits": [trait]})[0], 200)
        self.nav.attendre(f"""(() => {{ const c = document.querySelector('.feuille[data-page="{pid}"] canvas.encre'); const s = c.width / 595.28;
            return c.getContext('2d').getImageData(Math.round(130 * s), Math.round(300 * s), 1, 1).data[3] > 150; }})()""",
                          quoi="un trait écrit dans une autre fenêtre apparaît")
        self.sans_souci()


if __name__ == "__main__":
    unittest.main(verbosity=1)
