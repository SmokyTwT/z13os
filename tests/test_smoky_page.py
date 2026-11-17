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
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest
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
             "--force-dark-mode", f"--window-size={taille[0]},{taille[1]}", "about:blank"],
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

    def soucis(self, tolerer=()):
        """Erreurs JavaScript, messages d'erreur de la console (dont les blocages CSP), fichiers
        non chargés, réponses en erreur."""
        with self.etat:
            evenements = list(self.evenements)
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
        with self.etat:
            return [e["params"]["request"]["url"] for e in self.evenements if e["method"] == "Network.requestWillBeSent"]

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
        nav.attendre("document.querySelectorAll('#rail a.ancienne').length === 3")
        self.assertFalse(nav.evaluer("document.querySelector('#rail a[data-page=agenda]').classList.contains('ancienne')"),
                         "l'agenda est refait dans Smoky")
        self.srv.vider()
        nav.cliquer("Notes", dans="document.querySelector('#rail')")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-notes"]])
        self.assertEqual(nav.evaluer("location.hash"), "#/aujourdhui", "on reste sur la page ; l'ancienne appli s'ouvre à part")
        nav.attendre("[...document.querySelectorAll('#annonces .annonce')].some((a) => a.textContent === \"Notes s'ouvre dans sa fenêtre.\")")
        self.srv.vider()
        nav.cliquer("Ouvrir Mail")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-mail"]])
        self.assertNotIn("Ouvrir Agenda", nav.texte())
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
