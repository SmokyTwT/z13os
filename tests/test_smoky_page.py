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
        self.assertEqual(nav.evaluer("document.querySelector('form.ajout input[type=text]').value"), "", "le champ est vidé pour la suivante")
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
        self.assertIn(["powerprofilesctl", "set", "performance"], self.srv.attendre_commandes(1))
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
        nav.attendre("document.querySelectorAll('#rail a.ancienne').length === 4")
        self.srv.vider()
        nav.cliquer("Notes", dans="document.querySelector('#rail')")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-notes"]])
        self.assertEqual(nav.evaluer("location.hash"), "#/aujourdhui", "on reste sur la page ; l'ancienne appli s'ouvre à part")
        nav.attendre("[...document.querySelectorAll('#annonces .annonce')].some((a) => a.textContent === \"Notes s'ouvre dans sa fenêtre.\")")
        self.srv.vider()
        nav.cliquer("Ouvrir Agenda")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-agenda"]])
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
