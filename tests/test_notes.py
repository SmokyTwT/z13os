#!/usr/bin/env python3
"""Notes de l'appli Smoky, vues par leurs adresses /api/notes : carnets rangés dans
~/Notes/Carnets (bibliothèque, pages, fichiers joints, corbeille, export PDF, réglages des outils).

Le serveur tourne dans un dossier personnel jetable (voir test_smoky.py).

  python3 tests/test_notes.py
  SMOKY_RACINE=/ python3 tests/test_notes.py      image construite
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_smoky import PAGE, RACINE, Ecoute, Serveur  # noqa: E402

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" \
      b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def trait(n=5, x=10.0):
    return {"id": f"t{n}", "outil": "stylo", "couleur": "#141417", "largeur": 2,
            "points": [v for i in range(n) for v in (x + i * 3, 20 + i, 0.5)]}


class AvecServeur(unittest.TestCase):
    def setUp(self):
        self.srv = Serveur()
        self.addCleanup(self.srv.stop)
        self.racine = self.srv.home / "Notes" / "Carnets"

    def agir(self, action, **valeurs):
        return self.srv.json("POST", "/api/notes", {"action": action, **valeurs})

    def reussir(self, action, **valeurs):
        code, r = self.agir(action, **valeurs)
        self.assertEqual(code, 200, r)
        return r

    def creer(self, titre="Algèbre", **valeurs):
        return self.reussir("creer", titre=titre, **valeurs)["carnet"]

    def bibliotheque(self):
        code, b = self.srv.json("GET", "/api/notes")
        self.assertEqual(code, 200, b)
        return b

    def mettre(self, chemin, corps, **kw):
        return self.srv.json("PUT", chemin, corps, **kw)


class TestBibliotheque(AvecServeur):
    def test_vide_au_depart(self):
        b = self.bibliotheque()
        self.assertEqual((b["carnets"], b["corbeille"], b["preferences"], b["dossier"], b["ancien"]), ([], [], {}, "Notes/Carnets", False))
        self.assertEqual([m["nom"] for m in b["matieres"]][:3], ["Magnéto", "MNA", "Algèbre"])
        self.assertTrue(all(m["modele"] in b["modeles"] for m in b["matieres"]))
        self.assertEqual(len(b["couvertures"]), 8)
        self.assertEqual(b["formats"]["a4"], [595.28, 841.89])
        self.assertFalse(self.racine.exists(), "rien n'est créé tant qu'il n'y a pas de carnet")
        self.assertGreater(self.bibliotheque()["instant"], b["instant"], "chaque lecture est datée (la page garde la plus récente)")

    def test_creer(self):
        c = self.creer("Algèbre linéaire", classeur="Algèbre", couverture="encre", papier={"format": "a4-paysage", "modele": "seyes", "couleur": "ivoire"})
        self.assertRegex(c["id"], r"^c[0-9a-z]{6,12}-[0-9a-f]{4,8}$")
        self.assertEqual((c["titre"], c["classeur"], c["couverture"], c["favori"]), ("Algèbre linéaire", "Algèbre", "encre", False))
        [p] = c["pages"]
        self.assertEqual((p["w"], p["h"], p["modele"], p["couleur"], p["signet"]), (841.89, 595.28, "seyes", "ivoire", False))
        d = self.racine / c["id"]
        self.assertEqual(sorted(x.name for x in d.iterdir()), ["carnet.json", "fichiers", "pages"])
        [r] = self.bibliotheque()["carnets"]
        self.assertEqual((r["id"], r["pages"], r["pdf"], r["papier"]["modele"]), (c["id"], 1, False, "seyes"))
        self.assertLess(abs(r["modifie"] / 1000 - time.time()), 60)
        self.assertEqual(self.creer("Cours", vide=True)["pages"], [], "un carnet vide attend les pages d'un PDF")

    def test_creer_refuse(self):
        for valeurs, message in (({"titre": "  "}, "Donne un nom au carnet."), ({"titre": None}, "Donne un nom au carnet."),
                                 ({"couverture": "rose"}, "Couverture inconnue."), ({"papier": {"modele": "papyrus"}}, "Papier inconnu."),
                                 ({"papier": {"format": "a3"}}, "Papier inconnu."), ({"papier": {"couleur": "rose"}}, "Papier inconnu."),
                                 ({"classeur": 3}, "Classeur invalide.")):
            with self.subTest(valeurs=valeurs):
                self.assertEqual(self.agir("creer", **{"titre": "x", **valeurs}), (400, {"erreur": message}))
        for corps in ({"action": "inconnue"}, {"action": "__init__"}, {"action": "_dossier"}, {"action": 1}, {}):
            with self.subTest(corps=corps):
                self.assertEqual(self.srv.json("POST", "/api/notes", corps)[0], 400)
        self.assertEqual(self.bibliotheque()["carnets"], [])

    def test_titres_nettoyes(self):
        c = self.creer("  Cours\x1b[31m\nde méca  ", classeur=" Méca\t")
        self.assertEqual((c["titre"], c["classeur"]), ("Cours [31m de méca", "Méca"))
        self.assertEqual(len(self.creer("x" * 300)["titre"]), 100)

    def test_ranger_renommer_favori_couverture(self):
        c = self.creer()
        self.assertEqual(self.reussir("renommer", id=c["id"], titre="Algèbre 2")["carnet"]["titre"], "Algèbre 2")
        self.assertEqual(self.reussir("classer", id=c["id"], classeur="Algèbre")["carnet"]["classeur"], "Algèbre")
        self.assertEqual(self.reussir("classer", id=c["id"], classeur="")["carnet"]["classeur"], "")
        self.assertTrue(self.reussir("favori", id=c["id"], favori=True)["carnet"]["favori"])
        self.assertEqual(self.reussir("couverture", id=c["id"], couverture="braise")["carnet"]["couverture"], "braise")
        [r] = self.bibliotheque()["carnets"]
        self.assertEqual((r["titre"], r["favori"], r["couverture"]), ("Algèbre 2", True, "braise"))
        for action, valeurs, attendu in (("renommer", {"titre": ""}, 400), ("favori", {"favori": "oui"}, 400), ("couverture", {"couverture": "x"}, 400),
                                         ("renommer", {"id": "c0000000-0000", "titre": "x"}, 404), ("renommer", {"id": "../../etc", "titre": "x"}, 404),
                                         ("renommer", {"id": None, "titre": "x"}, 404)):
            with self.subTest(action=action, valeurs=valeurs):
                self.assertEqual(self.agir(action, **{"id": c["id"], **valeurs})[0], attendu)

    def test_dupliquer(self):
        c = self.creer("Méca")
        pid = c["pages"][0]["id"]
        self.assertEqual(self.mettre(f"/api/notes/{c['id']}/pages/{pid}", {"traits": [trait()]})[0], 200)
        copie = self.reussir("dupliquer", id=c["id"])["carnet"]
        self.assertNotEqual(copie["id"], c["id"])
        self.assertEqual(copie["titre"], "Méca (copie)")
        self.assertEqual(self.srv.json("GET", f"/api/notes/{copie['id']}/pages/{pid}")[1]["traits"], [trait()])
        self.assertEqual(len(self.bibliotheque()["carnets"]), 2)

    def test_corbeille(self):
        c = self.creer("Brouillon")
        self.assertEqual(self.reussir("supprimer", id=c["id"])["message"], "Carnet mis à la corbeille.")
        b = self.bibliotheque()
        self.assertEqual(b["carnets"], [])
        [jete] = b["corbeille"]
        self.assertRegex(jete["id"], rf"^{c['id']}-\d{{10}}$")
        self.assertEqual(jete["titre"], "Brouillon")
        self.assertEqual(self.reussir("restaurer", id=jete["id"])["id"], c["id"], "il revient sous son numéro")
        self.assertEqual([x["id"] for x in self.bibliotheque()["carnets"]], [c["id"]])
        # restauré alors qu'un carnet porte déjà son numéro : il en prend un autre, rien n'est écrasé
        self.reussir("supprimer", id=c["id"])
        jete = self.bibliotheque()["corbeille"][0]["id"]
        (self.racine / c["id"]).mkdir()
        (self.racine / c["id"] / "carnet.json").write_text(json.dumps({"id": c["id"], "titre": "Autre", "pages": []}))
        nouveau = self.reussir("restaurer", id=jete)["id"]
        self.assertNotEqual(nouveau, c["id"])
        self.assertEqual(sorted(x["titre"] for x in self.bibliotheque()["carnets"]), ["Autre", "Brouillon"])
        # la place qu'il prendrait dans la corbeille est déjà occupée (même numéro jeté à la même seconde,
        # revenu d'un autre appareil par la synchro) : il en prend une autre, rien n'est écrasé
        maintenant = int(time.time())
        for t in range(maintenant, maintenant + 3):
            occupe = self.racine / ".corbeille" / f"{nouveau}-{t}"
            occupe.mkdir(parents=True, exist_ok=True)
            (occupe / "carnet.json").write_text(json.dumps({"id": nouveau, "titre": "Occupant", "pages": []}))
        self.reussir("supprimer", id=nouveau)
        self.assertEqual(sorted(x["titre"] for x in self.bibliotheque()["corbeille"]), ["Brouillon", "Occupant", "Occupant", "Occupant"])
        for x in self.bibliotheque()["corbeille"]:
            self.reussir("effacer", id=x["id"]) if x["titre"] == "Occupant" else None
        self.reussir("restaurer", id=self.bibliotheque()["corbeille"][0]["id"])
        # effacer pour de bon
        self.reussir("supprimer", id=nouveau)
        jete = self.bibliotheque()["corbeille"][0]["id"]
        self.assertEqual(self.reussir("effacer", id=jete)["message"], "Carnet effacé définitivement.")
        self.assertEqual(self.bibliotheque()["corbeille"], [])
        for mauvais in ("../x", f"{c['id']}", f"{jete}/../..", "", None):
            with self.subTest(id=mauvais):
                self.assertEqual(self.agir("effacer", id=mauvais), (404, {"erreur": "Introuvable dans la corbeille."}))
                self.assertEqual(self.agir("restaurer", id=mauvais)[0], 404)
        self.assertTrue((self.racine / c["id"] / "carnet.json").is_file(), "« effacer » ne touche jamais un carnet hors de la corbeille")

    def test_carnet_illisible_ignore(self):
        c = self.creer("Bon")
        abime = self.racine / "c0000000a-abcd"
        abime.mkdir()
        (abime / "carnet.json").write_text("{pas du json")
        (self.racine / "pas-un-carnet").mkdir()
        self.assertEqual([x["id"] for x in self.bibliotheque()["carnets"]], [c["id"]])
        self.assertEqual(self.srv.json("GET", "/api/notes/c0000000a-abcd"), (500, {"erreur": "Ce carnet est illisible."}))

    def test_ancien_smoky_notes_jamais_touche(self):
        ancien = self.srv.home / "Notes" / "Smoky Notes" / "nb1"
        ancien.mkdir(parents=True)
        (ancien / "notebook.json").write_text('{"title": "Ancien"}')
        avant = (ancien / "notebook.json").stat().st_mtime_ns
        c = self.creer()
        self.reussir("supprimer", id=c["id"])
        b = self.bibliotheque()
        self.assertEqual(b["carnets"], [], "les carnets de l'ancien Smoky Notes ne sont pas repris (repartir de zéro)")
        self.assertTrue(b["ancien"], "la page peut rappeler où ils sont")
        self.assertEqual(((ancien / "notebook.json").read_text(), (ancien / "notebook.json").stat().st_mtime_ns), ('{"title": "Ancien"}', avant))

    def test_preferences(self):
        r = self.reussir("preferences", valeurs={"outil": "surligneur", "doigt": True, "stylo": {"couleur": "#2D6FE0", "largeur": 3.4},
                                                 "gomme": {"largeur": 30, "precise": True}, "texte": {"largeur": 99}, "inconnu": 1, "formes": "oui"})
        attendu = {"outil": "surligneur", "doigt": True, "stylo": {"couleur": "#2d6fe0", "largeur": 3.4}, "gomme": {"largeur": 30.0, "precise": True}}
        self.assertEqual(r["preferences"], attendu)
        self.assertEqual(self.bibliotheque()["preferences"], attendu)
        self.assertEqual(self.agir("preferences", valeurs="x")[0], 400)

    def test_fenetres_prevenues(self):
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        fenetre.attendre("bonjour")
        c = self.creer()
        self.assertEqual(fenetre.attendre("change"), {"quoi": "notes"})
        pid = c["pages"][0]["id"]
        self.mettre(f"/api/notes/{c['id']}/pages/{pid}", {"traits": [trait()]})
        self.assertEqual(fenetre.attendre("change"), {"quoi": f"notes:{c['id']}:{pid}"})
        # la marque choisie par l'éditeur accompagne l'annonce : il y reconnaît son propre enregistrement
        self.mettre(f"/api/notes/{c['id']}/pages/{pid}", {"traits": [trait()], "rev": "rmwp2zob4-1gwrhu"})
        self.assertEqual(fenetre.attendre("change"), {"quoi": f"notes:{c['id']}:{pid}", "rev": "rmwp2zob4-1gwrhu"})
        self.reussir("preferences", valeurs={"outil": "gomme"})
        self.assertIsNone(fenetre.attendre("change", delai=0.5), "les réglages des outils n'agitent pas les autres fenêtres")


class TestPages(AvecServeur):
    def setUp(self):
        super().setUp()
        self.c = self.creer()
        self.base = f"/api/notes/{self.c['id']}"
        self.pid = self.c["pages"][0]["id"]

    def test_ecrire_et_relire(self):
        self.assertEqual(self.srv.json("GET", f"{self.base}/pages/{self.pid}")[1], {"format": 1, "traits": [], "textes": [], "images": []})
        page = {"traits": [trait(), trait(8, 40)], "textes": [{"id": "x1", "x": 10, "y": 10, "taille": 14, "couleur": "#141417", "texte": "Théorème"}], "images": []}
        code, r = self.mettre(f"{self.base}/pages/{self.pid}", page)
        self.assertEqual(code, 200, r)
        self.assertEqual(self.srv.json("GET", f"{self.base}/pages/{self.pid}")[1], {"format": 1, **page})
        fichier = self.racine / self.c["id"] / "pages" / f"{self.pid}.json"
        self.assertTrue(fichier.is_file())
        self.assertEqual(list(fichier.parent.glob(".*")), [], "aucun fichier temporaire laissé (écriture d'un coup)")
        self.assertEqual(self.mettre(f"{self.base}/pages/{self.pid}", {**page, "rev": "r1a2b3"})[0], 200)
        self.assertEqual(self.srv.json("GET", f"{self.base}/pages/{self.pid}")[1]["rev"], "r1a2b3", "la marque de version est gardée")
        for rev in ("", "x", "R1A2B3", "../..", 12, "a" * 33):
            with self.subTest(rev=rev):
                self.assertEqual(self.mettre(f"{self.base}/pages/{self.pid}", {**page, "rev": rev}), (400, {"erreur": "Page illisible."}))

    def test_pages_refusees(self):
        for page, message in (([], "Page illisible."), ({"traits": "x"}, "Page illisible."), ({"traits": [1]}, "Page illisible."),
                              ({"traits": [{"points": [1, 2]}]}, "Trait illisible."), ({"traits": [{"points": [1, 2, "3"]}]}, "Trait illisible."),
                              ({"traits": [{"points": [1, 2, True]}]}, "Trait illisible."), ({"traits": [{}]}, "Trait illisible."),
                              ({"images": [{"fichier": "../x.png"}]}, "Image illisible."), ({"images": [{"x": 1}]}, "Image illisible.")):
            with self.subTest(page=page):
                self.assertEqual(self.mettre(f"{self.base}/pages/{self.pid}", page), (400, {"erreur": message}))
        self.assertEqual(self.srv.req("PUT", f"{self.base}/pages/{self.pid}", "{pas du json")[0], 400)
        self.assertEqual(self.mettre(f"{self.base}/pages/pinconnue123", {"traits": []}), (404, {"erreur": "Cette page n'est plus dans le carnet."}))
        self.assertEqual(self.mettre(f"{self.base}/pages/..%2f..%2fcarnet", {"traits": []})[0], 404)
        self.assertEqual(self.srv.req("PUT", f"{self.base}/pages/{self.pid}", "{}", entetes={"Content-Length": "12000001"})[0], 413)
        self.assertEqual(self.srv.json("GET", f"{self.base}/pages/{self.pid}")[1]["traits"], [], "rien d'abîmé n'a été écrit")

    def test_liste_des_pages(self):
        nouvelle = {"id": "pabcdef12-xy", "w": 595.28, "h": 841.89, "modele": "carreaux", "couleur": "fumee", "signet": True}
        code, r = self.mettre(self.base, {"pages": [self.c["pages"][0], nouvelle], "papier": {"format": "a4", "modele": "carreaux", "couleur": "fumee"}})
        self.assertEqual(code, 200, r)
        c = self.srv.json("GET", self.base)[1]
        self.assertEqual([p["id"] for p in c["pages"]], [self.pid, "pabcdef12-xy"])
        self.assertEqual((c["pages"][1]["signet"], c["papier"]["modele"]), (True, "carreaux"))
        self.assertEqual(self.mettre(f"{self.base}/pages/pabcdef12-xy", {"traits": [trait()]})[0], 200)
        # page retirée du carnet : son fichier part avec elle
        self.assertEqual(self.mettre(self.base, {"pages": [self.c["pages"][0]]})[0], 200)
        self.assertFalse((self.racine / self.c["id"] / "pages" / "pabcdef12-xy.json").exists())
        mauvais = {"id": "pzz", "w": 595, "h": 842}
        for pages, message in (([nouvelle, nouvelle], "Page invalide."), ([mauvais], "Page invalide."), ([{**nouvelle, "w": 20}], "Taille de page invalide."),
                               ([{**nouvelle, "modele": "x"}], "Papier inconnu."), ("x", "Liste de pages invalide."),
                               ([{**nouvelle, "fond": {"pdf": "absent.pdf", "page": 0}}], "Le PDF de cette page n'a pas été envoyé."),
                               ([{**nouvelle, "fond": {"pdf": "../x.pdf", "page": 0}}], "Fond de page invalide."),
                               ([{**nouvelle, "fond": {"pdf": "a.png", "page": 0}}], "Fond de page invalide.")):
            with self.subTest(message=message, pages=str(pages)[:60]):
                self.assertEqual(self.mettre(self.base, {"pages": pages}), (400, {"erreur": message}))
        self.assertEqual(self.mettre(self.base, {"titre": ""}), (400, {"erreur": "Donne un nom au carnet."}))
        self.assertEqual(self.mettre(self.base, {"sons": [{"id": "x"}]}), (400, {"erreur": "Enregistrement invalide."}))

    def test_pdf_joint(self):
        nom = "0123456789abcdef01234567.pdf"
        self.assertEqual(self.srv.req("PUT", f"{self.base}/fichiers/{nom}", PDF)[0], 200)
        code, h, corps = self.srv.req("GET", f"{self.base}/fichiers/{nom}")
        self.assertEqual((code, corps, h["content-type"], h["cache-control"], h["x-content-type-options"]),
                         (200, PDF, "application/pdf", "no-store", "nosniff"))
        page = {"id": "ppdf00001-aa", "w": 595, "h": 842, "modele": "vierge", "couleur": "blanc", "fond": {"pdf": nom, "page": 0}}
        self.assertEqual(self.mettre(self.base, {"pages": [page]})[0], 200)
        [r] = self.bibliotheque()["carnets"]
        self.assertTrue(r["pdf"])
        for nom2, contenu, attendu in (("faux.pdf", b"GIF89a", 400), ("image.png", PDF, 400), ("image.png", PNG, 200),
                                       ("../evil.pdf", PDF, 404), ("x.exe", b"MZ", 404), ("MAJ.pdf", PDF, 404), (".cache.pdf", PDF, 404)):
            with self.subTest(nom=nom2):
                self.assertEqual(self.srv.req("PUT", f"{self.base}/fichiers/{nom2}", contenu)[0], attendu)
        self.assertEqual(self.srv.req("GET", f"{self.base}/fichiers/absent.pdf")[0], 404)
        self.assertEqual(self.srv.req("PUT", f"{self.base}/fichiers/gros.pdf", "x", entetes={"Content-Length": "250000001"})[0], 413)

    def test_sons(self):
        nom = "s1a2b3c4-x9.webm"
        self.assertEqual(self.srv.req("PUT", f"{self.base}/fichiers/{nom}", b"\x1a\x45\xdf\xa3" + b"\x00" * 20)[0], 200)
        son = {"id": "s1a2b3c4-x9", "fichier": nom, "debut": int(time.time() * 1000), "duree": 65000}
        self.assertEqual(self.mettre(self.base, {"sons": [son]})[0], 200)
        self.assertEqual(self.srv.json("GET", self.base)[1]["sons"], [son])

    def test_export_pdf(self):
        code, r = self.srv.json("POST", "/api/notes/export?nom=" + "Cours%20d'alg%C3%A8bre", PDF)
        self.assertEqual(code, 200, r)
        cible = self.srv.home / "Notes" / "PDF" / "Cours d'algèbre.pdf"
        self.assertEqual((r["message"], cible.read_bytes()), ("PDF enregistré dans Notes/PDF/Cours d'algèbre.pdf.", PDF))
        code, r = self.srv.json("POST", "/api/notes/export?nom=..%2F..%2Fevil", PDF)
        self.assertEqual(code, 200)
        self.assertTrue(Path(r["chemin"]).parent == self.srv.home / "Notes" / "PDF", "jamais en dehors de Notes/PDF")
        self.assertEqual(self.srv.json("POST", "/api/notes/export?nom=x", b"pas un pdf")[0], 400)


class TestServeurNotes(unittest.TestCase):
    """Ce que les Notes demandent au serveur lui-même : PDF.js servi, politique de sécurité."""

    @classmethod
    def setUpClass(cls):
        cls.srv = Serveur()

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_bibliotheques_pdf_servies(self):
        for chemin, genre in (("/vendor/pdf.min.mjs", "text/javascript"), ("/vendor/pdf.worker.min.mjs", "text/javascript"),
                              ("/vendor/pdf-lib.min.js", "text/javascript"), ("/vendor/pdfjs/cmaps/UniJIS-UCS2-H.bcmap", "application/octet-stream"),
                              ("/vendor/pdfjs/standard_fonts/FoxitSerif.pfb", "application/octet-stream"),
                              ("/vendor/pdfjs/wasm/openjpeg.wasm", "application/wasm")):
            with self.subTest(chemin=chemin):
                code, h, corps = self.srv.req("GET", chemin, jeton=None)
                self.assertEqual(code, 200)
                self.assertTrue(h["content-type"].startswith(genre))
                self.assertEqual(corps, (PAGE / chemin.lstrip("/")).read_bytes())
        self.assertEqual(self.srv.req("GET", "/vendor/README.md", jeton=None)[0], 404, "les fichiers de licence ne sont pas servis (type inconnu)")

    def test_versions_figees(self):
        lisezmoi = (PAGE / "vendor/README.md").read_text()
        self.assertRegex(lisezmoi, r"pdfjs-dist 6\.3\.289")
        self.assertRegex(lisezmoi, r"pdf-lib 1\.17\.1")

    def test_politique_de_securite(self):
        code, h, _ = self.srv.req("GET", "/smoky", jeton=None)
        csp = h["content-security-policy"]
        self.assertIn("script-src 'self' 'wasm-unsafe-eval';", csp)
        self.assertIn("worker-src 'self';", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotRegex(csp, r"'unsafe-eval'")


class TestMoodleEnPause(unittest.TestCase):
    """Moodle est en pause (22/11/2026) : rien n'est importé, ni cours ni échéances, en attendant que la
    partie Cours de l'appli Smoky soit refaite. Le fichier de pause est dans l'image."""

    def charger(self, pause):
        chemin = RACINE / "usr/libexec/smokyos/smoky-moodle.py"
        chargeur = importlib.machinery.SourceFileLoader("smoky_moodle_pause", str(chemin))
        m = importlib.util.module_from_spec(importlib.util.spec_from_loader("smoky_moodle_pause", chargeur))
        chargeur.exec_module(m)
        m.PAUSE = pause
        m.STATE = Path(tempfile.mkdtemp()) / "state.json"
        self.addCleanup(shutil.rmtree, m.STATE.parent, ignore_errors=True)
        m.DEADLINES = m.STATE.parent / "echeances.json"
        m.token_get = lambda: "jeton"
        m.notify = lambda *a, **k: None

        self.appels = []

        def reseau(*a, **k):                  # Moodle injoignable ; on note qu'il a été appelé
            self.appels.append(a)
            raise RuntimeError("hors ligne")
        m.ws = m.http = m.zenity = reseau
        return m

    def test_le_fichier_de_pause_est_dans_l_image(self):
        self.assertTrue((RACINE / "usr/share/smokyos/moodle-en-pause").is_file())

    def test_rien_n_est_importe(self):
        m = self.charger(RACINE / "usr/share/smokyos/moodle-en-pause")
        for commande in (["sync"], ["connect"], ["receive", "moodlemobile://token=abc"]):
            with self.subTest(commande=commande):
                self.assertEqual(m.main(["smoky-moodle.py", *commande]), 0)
        self.assertEqual(self.appels, [], "Moodle n'est pas contacté")
        self.assertFalse(m.STATE.exists(), "rien n'est écrit")
        sortie = io.StringIO()
        sys.stdout, avant = sortie, sys.stdout
        try:
            m.main(["smoky-moodle.py", "status"])
        finally:
            sys.stdout = avant
        self.assertTrue(json.loads(sortie.getvalue())["en_pause"], "la page Système peut le dire")

    def test_sans_pause_la_synchro_repart(self):
        m = self.charger(Path(tempfile.gettempdir()) / "pas-de-pause-ici")
        self.assertEqual(m.main(["smoky-moodle.py", "sync"]), 1, "Moodle injoignable : échec signalé")
        self.assertTrue(self.appels, "sans le fichier de pause, la synchronisation contacte Moodle")


class TestInstallation(unittest.TestCase):
    """Les Notes quittent l'ancienne appli : raccourcis, dock, mode tablette."""

    def test_raccourcis(self):
        smoky = (RACINE / "usr/share/applications/smoky.desktop").read_text()
        self.assertIn("[Desktop Action notes]\nName=Notes\nExec=/usr/bin/smoky --aller /notes\n", smoky)
        self.assertIn("Actions=notes;agenda;mail;systeme;", smoky)
        self.assertRegex(smoky, r"Keywords=[^\n]*;notes;", "chercher « notes » dans GNOME trouve l'appli Smoky")
        ancien = (RACINE / "usr/share/applications/smoky-notes.desktop").read_text()
        self.assertIn("Name=Smoky Notes (ancien)\n", ancien)
        self.assertIn("Exec=/usr/bin/smoky-notes\n", ancien, "l'ancien reste lançable (carnets d'avant), sous le même nom de fichier")
        # dock Smoky par défaut : construit par build_files/smoky.sh (dépôt), écrit dans dock.json (image)
        source, image = RACINE.parent / "build_files/smoky.sh", RACINE / "usr/share/smoky-bureau/dock.json"
        if source.is_file():
            import re
            favoris = " ".join(re.findall(r"DOCK\+?=\(([^)]*)\)", source.read_text())).split()
        else:
            import json
            favoris = json.loads(image.read_text())["dock"]
        self.assertEqual(favoris[0], "smoky.desktop")
        self.assertNotIn("smoky-notes.desktop", favoris, "plus d'icône à part dans le dock par défaut")

    def test_mode_tablette_ouvre_les_nouvelles_notes(self):
        adaptatif = (RACINE / "usr/lib/smoky/smokybureau/energie.py").read_text()     # service smoky-adaptive
        self.assertIn('subprocess.Popen(["/usr/bin/smoky", "--aller", "/notes"])', adaptatif)
        self.assertNotIn("/usr/bin/smoky-notes", adaptatif)

    def test_dock(self):
        """L'icône de l'ancien Smoky Notes quitte le dock une fois ; Smoky prend sa place s'il n'y est pas."""
        script = (RACINE / "usr/libexec/z13os/user-setup.sh").read_text()
        debut = script.index('MARK="$HOME/.config/smoky/setup-notes-dans-smoky"')
        bloc = script[debut:script.index("\nfi\n", debut) + 4]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "bin").mkdir()
            (d / "bin/dconf").write_text('#!/bin/bash\ncat "$HOME/dock"\n')
            (d / "bin/gsettings").write_text('#!/bin/bash\nprintf %s "$4" > "$HOME/dock"\n')
            for f in ("dconf", "gsettings"):
                (d / "bin" / f).chmod(0o755)
            for avant, apres in (("['smoky.desktop', 'smoky-notes.desktop', 'google-chrome.desktop']", "['smoky.desktop', 'google-chrome.desktop']"),
                                 ("['google-chrome.desktop', 'smoky-notes.desktop', 'smoky-mail.desktop']", "['google-chrome.desktop', 'smoky.desktop', 'smoky-mail.desktop']"),
                                 ("['smoky-notes.desktop', 'smoky.desktop']", "['smoky.desktop']"),
                                 ("['smoky-notes.desktop']", "['smoky.desktop']"),
                                 ("['google-chrome.desktop']", "['google-chrome.desktop']")):
                with self.subTest(avant=avant):
                    (d / ".config/smoky/setup-notes-dans-smoky").unlink(missing_ok=True)
                    (d / "dock").write_text(avant)
                    env = {**os.environ, "HOME": str(d), "PATH": f"{d / 'bin'}:/usr/bin:/bin"}
                    subprocess.run(["bash", "-c", bloc], env=env, check=True)
                    self.assertEqual((d / "dock").read_text(), apres)
                    self.assertTrue((d / ".config/smoky/setup-notes-dans-smoky").exists())
                    (d / "dock").write_text("['smoky-notes.desktop']")
                    subprocess.run(["bash", "-c", bloc], env=env, check=True)
                    self.assertEqual((d / "dock").read_text(), "['smoky-notes.desktop']", "une seule fois : remis à la main, il reste")


if __name__ == "__main__":
    unittest.main(verbosity=1)
