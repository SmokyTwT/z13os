#!/usr/bin/env python3
"""Mail de l'appli Smoky, vu par ses adresses /api/mail, contre de faux serveurs IMAP, SMTP et Microsoft
(locaux, en TLS, certificats d'essai) et un faux trousseau. Aucune vraie boîte n'est jamais contactée.

  python3 tests/test_mail.py
  SMOKY_RACINE=/ python3 tests/test_mail.py      image construite
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from email import message_from_bytes, policy
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from faux_courrier import FAUX_TROUSSEAU, FauxIMAP, FauxMicrosoft, FauxSMTP, certificats, mail  # noqa: E402
from test_smoky import LANCER, RACINE, Ecoute, Serveur, attendre  # noqa: E402

GMAIL, MDP_GMAIL = "moi@gmail.com", "abcdefghijklmnop"
UPHF, MDP_UPHF = "prenom.nom@uphf.fr", "mdp-ent-été"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000") + b"\0" * 20


@unittest.skipUnless(shutil.which("openssl"), "openssl absent (certificats d'essai)")
class AvecBoites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dossier_certs = Path(tempfile.mkdtemp(prefix="smoky-certs-"))
        cls.ca, cls.cert, cls.cle = certificats(cls.dossier_certs)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dossier_certs, ignore_errors=True)

    def setUp(self):
        self.imap = FauxIMAP(self.cert, self.cle, {GMAIL: MDP_GMAIL})
        # UPHF : pas de dossiers « spéciaux » annoncés, pas de MOVE (comme bien des serveurs d'université)
        self.imap_uphf = FauxIMAP(self.cert, self.cle, {UPHF: MDP_UPHF}, dossiers={"Trash": "", "Sent": ""}, capacites=("UIDPLUS",))
        self.smtp = FauxSMTP(self.cert, self.cle, {GMAIL: MDP_GMAIL, "12345@uphf.fr": MDP_UPHF})
        self.smtp_outlook = FauxSMTP(self.cert, self.cle, {}, tls="starttls")
        self.ms = FauxMicrosoft(self.cert, self.cle)
        for s in (self.imap, self.imap_uphf, self.smtp, self.smtp_outlook, self.ms):
            self.addCleanup(s.arreter)
        self.srv = Serveur(preparer=self.preparer, env={"SMOKY_MAIL_CA": self.ca})
        self.addCleanup(self.srv.stop)

    def preparer(self, srv):
        (srv.faux / "secret-tool").write_text(FAUX_TROUSSEAU.format(python=sys.executable))
        (srv.faux / "secret-tool").chmod(0o755)

        def serveur(s, tls="ssl"):
            return {"hote": "localhost", "port": s.port, "tls": tls}
        surcharges = {
            "gmail": {"imap": serveur(self.imap), "smtp": serveur(self.smtp)},
            "uphf": {"imap": serveur(self.imap_uphf), "smtp": serveur(self.smtp)},
            "outlook": {"imap": serveur(self.imap), "smtp": serveur(self.smtp_outlook, "starttls")},
            "microsoft": f"https://localhost:{self.ms.port}",
        }
        (srv.base / "serveurs.json").write_text(json.dumps(surcharges))
        srv.environnement["SMOKY_MAIL_SERVEURS"] = str(srv.base / "serveurs.json")

    # --- aides ---
    def agir(self, action, **valeurs):
        return self.srv.json("POST", "/api/mail", {"action": action, **valeurs})

    def reussir(self, action, **valeurs):
        code, r = self.agir(action, **valeurs)
        self.assertEqual(code, 200, r)
        return r

    def etat(self, **params):
        code, r = self.srv.json("GET", "/api/mail?" + urllib.parse.urlencode(params))
        self.assertEqual(code, 200, r)
        return r

    def releve(self, attendu=None):
        """Attend la fin de la relève (et, si dit, ce nombre de mails dans la liste)."""
        def fini():
            e = self.etat()
            return e if not e["releve"]["en_cours"] and all(c["releve"] or c["probleme"] for c in e["comptes"]) and \
                (attendu is None or len(e["messages"]) == attendu) else None
        e = attendre(fini, 15, 0.1)
        self.assertTrue(e, f"relève jamais finie : {self.etat()}")
        return e

    def ajouter_gmail(self, **plus):
        r = self.reussir("ajouter", genre="gmail", adresse=GMAIL, nom="Moi Essai", motdepasse="abcd efgh ijkl mnop", **plus)
        return r["id"]

    def trousseau(self):
        f = self.srv.faux / "trousseau.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def message(self, ident):
        return next(m for m in self.etat(recherche="")["messages"] if m["id"] == ident)


class TestBoites(AvecBoites):
    def test_ajouter_gmail(self):
        self.imap.deposer(mail(objet="Premier mail"))
        cid = self.ajouter_gmail()
        self.assertRegex(cid, r"^m[0-9a-f]{8}$")
        e = self.releve(1)
        self.assertEqual([(c["adresse"], c["genre"], c["auth"], c["nom"]) for c in e["comptes"]], [(GMAIL, "gmail", "motdepasse", "Moi Essai")])
        # le mot de passe : dans le trousseau seulement (espaces de Google retirés), jamais dans la mémoire ni la page
        self.assertEqual(self.trousseau()[f"service smoky quoi mail-motdepasse compte {cid}"]["secret"], MDP_GMAIL)
        base = (self.srv.base / "donnees/smoky.db").read_bytes()
        self.assertNotIn(MDP_GMAIL.encode(), base)
        self.assertNotIn(MDP_GMAIL, json.dumps(self.etat()))
        self.assertTrue((self.srv.base / "donnees/mail-actif").exists(), "la relève de fond peut tourner")
        # la relève lit sans rien marquer « lu » (dossier ouvert en lecture seule, BODY.PEEK)
        commandes = [c for _q, c, _a in self.imap.journal]
        self.assertIn("EXAMINE", commandes)
        self.assertNotIn("UID STORE", commandes)
        self.assertNotIn("\\Seen", self.imap.lettre(1).drapeaux)

    def test_mauvais_mot_de_passe(self):
        code, r = self.agir("ajouter", genre="gmail", adresse=GMAIL, motdepasse="mon-mot-de-passe-google")
        self.assertEqual((code, r), (401, {"erreur": "Gmail refuse la connexion : il faut un mot de passe d'application (16 lettres), "
                                                     "pas ton mot de passe Google."}))
        self.assertEqual(self.trousseau(), {}, "rien n'est gardé d'un essai raté")
        self.assertEqual(self.etat()["comptes"], [])

    def test_trousseau_ferme(self):
        (self.srv.faux / "trousseau-ferme").touch()
        code, r = self.agir("ajouter", genre="gmail", adresse=GMAIL, motdepasse=MDP_GMAIL)
        self.assertEqual(code, 503)
        self.assertIn("trousseau GNOME ne répond pas", r["erreur"])
        self.assertEqual(self.etat()["comptes"], [])
        self.assertEqual([p.name for p in self.srv.base.rglob("*") if MDP_GMAIL.encode() in (p.read_bytes() if p.is_file() else b"")], [],
                         "sans trousseau, le mot de passe n'est écrit nulle part")

    def test_refus(self):
        for valeurs, attendu in (({"genre": "gmail", "adresse": "pas-une-adresse", "motdepasse": "x"}, "Adresse mail invalide."),
                                 ({"genre": "gmail", "adresse": GMAIL, "motdepasse": ""}, "Mot de passe manquant."),
                                 ({"genre": "outlook", "adresse": "a@outlook.fr", "motdepasse": "x"}, "Genre de boîte inconnu."),
                                 ({"genre": "pop3", "adresse": GMAIL, "motdepasse": "x"}, "Genre de boîte inconnu."),
                                 ({"genre": "autre", "adresse": "a@b.fr", "motdepasse": "x", "imap": "imap b.fr", "smtp": "s.b.fr"},
                                  "Serveurs IMAP / SMTP invalides."),
                                 ({"genre": "autre", "adresse": "a@b.fr", "motdepasse": "x", "imap": "imap.b.fr", "smtp": "smtp.b.fr",
                                   "port_smtp": 25}, "Port d'envoi accepté : 465 ou 587 (connexion chiffrée).")):
            with self.subTest(valeurs=valeurs):
                self.assertEqual(self.agir("ajouter", **valeurs), (400, {"erreur": attendu}))
        for corps in ({"action": "inconnue"}, {"action": "__init__"}, {"action": "_releve"}, {}, {"action": 3}):
            with self.subTest(corps=corps):
                self.assertEqual(self.srv.json("POST", "/api/mail", corps)[0], 400)

    def test_retirer(self):
        cid = self.ajouter_gmail()
        self.imap.deposer(mail())
        self.reussir("relever")
        self.releve(1)
        r = self.reussir("retirer", id=cid)
        self.assertEqual(r["message"], f"{GMAIL} retirée de Smoky (les mails restent sur le serveur).")
        self.assertEqual((self.etat()["comptes"], self.etat()["messages"], self.trousseau()), ([], [], {}))
        self.assertFalse((self.srv.base / "donnees/mail-actif").exists())
        self.assertEqual(len(self.imap.dossiers["INBOX"]), 1, "rien n'est supprimé sur le serveur")
        self.assertEqual(self.agir("retirer", id=cid)[0], 404)

    def test_pages_d_aide(self):
        for quoi, adresse in (("aide-gmail", "https://myaccount.google.com/apppasswords"),
                              ("microsoft-code", "https://microsoft.com/devicelogin")):
            self.srv.vider()
            self.assertEqual(self.srv.json("POST", "/api/ouvrir", {"quoi": quoi}), (200, {}))
            self.assertEqual(attendre(lambda: [c for c in self.srv.commandes() if c[0] == "gio"], 5), [["gio", "open", adresse]],
                             "ouverte dans le navigateur habituel")
        self.srv.vider()
        for quoi in ("https://pisteur.example/", "aide", "AIDE-GMAIL", "aide-gmail ", ["aide-gmail"]):
            self.assertEqual(self.srv.json("POST", "/api/ouvrir", {"quoi": quoi}), (400, {"erreur": "Appli inconnue."}))
        self.assertEqual(self.srv.commandes(), [], "seulement les pages connues")

    def test_ancien_smoky_mail_jamais_lu(self):
        ancien = self.srv.home / ".local/share/smoky-mail"
        ancien.mkdir(parents=True)
        (ancien / "accounts.json").write_text(json.dumps({"accounts": [{"id": "a1234abcd", "email": "vieux@gmail.com"}]}))
        (self.srv.faux / "trousseau.json").write_text(json.dumps(
            {"service smoky-mail kind password:a1234abcd": {"secret": "vieux-secret", "etiquette": "Smoky Mail"}}))
        self.assertEqual(self.etat()["comptes"], [], "repartir de zéro : les boîtes de l'ancien Smoky Mail ne sont pas reprises")
        self.ajouter_gmail()
        self.assertIn("service smoky-mail kind password:a1234abcd", self.trousseau(), "ses secrets restent où ils sont")


class TestReleve(AvecBoites):
    def test_tri_sur_le_pc(self):
        maintenant = time.time()
        envois = [
            ("Secrétariat INSA <scolarite@uphf.fr>", "Inscriptions aux examens", {}, "universite"),
            ("Moodle UPHF <noreply@moodle.example>", "Nouveau devoir", {}, "universite"),
            ("Amazon.fr <confirmation@amazon.fr>", "Votre commande", {}, "achats"),
            ("Colis <info@example.com>", "Votre colis est en livraison", {}, "achats"),
            ("Le Monde <news@lemonde.fr>", "La lettre du jour", {"List-Unsubscribe": "<mailto:x@lemonde.fr>"}, "newsletters"),
            ("Instagram <no-reply@mail.instagram.com>", "Nouvelle connexion", {}, "notifications"),
            ("Robot <robot@exemple.fr>", "Réponse automatique", {"Auto-Submitted": "auto-replied"}, "notifications"),
            ("Lina Martin <lina.martin@gmail.com>", "Ciné ce soir ?", {}, "personnes"),
            ("Gagnant <win@arnaque.example>", "Vous avez gagné", {"X-Spam-Flag": "YES"}, "indesirable"),
        ]
        for i, (de, objet, entetes, _cat) in enumerate(envois):
            self.imap.deposer(mail(de=de, objet=objet, entetes=entetes, date=maintenant - i * 60))
        self.ajouter_gmail()
        e = self.releve(8)
        self.assertEqual([m["objet"] for m in e["messages"]], [x[1] for x in envois[:8]], "du plus récent au plus ancien ; l'indésirable à part")
        tous = {m["objet"]: m["categorie"] for m in e["messages"] + self.etat(categorie="indesirable")["messages"]}
        self.assertEqual(tous, {x[1]: x[3] for x in envois})
        self.assertTrue(all(m["classe_par"] == "pc" for m in e["messages"]))
        compte = {c["id"]: (c["total"], c["non_lus"]) for c in e["categories"]}
        self.assertEqual(compte, {"universite": (2, 2), "personnes": (1, 1), "achats": (2, 2), "newsletters": (1, 1),
                                  "notifications": (2, 2), "indesirable": (1, 1)})
        self.assertEqual([m["objet"] for m in self.etat(categorie="universite")["messages"]], ["Inscriptions aux examens", "Nouveau devoir"])
        self.assertEqual([m["objet"] for m in self.etat(recherche="ciné")["messages"]], ["Ciné ce soir ?"], "recherche sans tenir compte de la casse")
        self.assertEqual([m["objet"] for m in self.etat(recherche="lina soir")["messages"]], ["Ciné ce soir ?"], "plusieurs mots : tous")
        self.assertEqual(self.etat(recherche="100%_")["messages"], [], "les % et _ tapés sont des lettres, pas des jokers")
        self.assertEqual(len(self.etat(categorie="non-lus")["messages"]), 8, "les non lus, sans l'indésirable")
        for mauvais in ({"categorie": "spam"}, {"compte": "../x"}, {"avant": "hier"}):
            with self.subTest(mauvais=mauvais):
                self.assertEqual(self.srv.json("GET", "/api/mail?" + urllib.parse.urlencode(mauvais))[0], 400)

    def test_suite_de_la_liste(self):
        for i in range(70):
            self.imap.deposer(mail(objet=f"Mail {i:02d}", date=time.time() - i * 60))
        self.ajouter_gmail()
        e = self.releve(60)
        self.assertTrue(e["suite"])
        reste = self.etat(avant=e["messages"][-1]["date"])
        self.assertEqual(([m["objet"] for m in reste["messages"]], reste["suite"]), ([f"Mail {i:02d}" for i in range(60, 70)], False))

    def test_lu_ailleurs_et_disparus(self):
        a = self.imap.deposer(mail(objet="A"))
        b = self.imap.deposer(mail(objet="B"))
        self.ajouter_gmail()
        self.releve(2)
        self.imap.lettre(a).drapeaux.add("\\Seen")                 # lu sur le téléphone
        self.imap.dossiers["INBOX"].remove(self.imap.lettre(b))     # archivé sur le webmail
        self.imap.deposer(mail(objet="C"))
        self.reussir("relever")
        e = self.releve(2)
        self.assertEqual({m["objet"]: m["lu"] for m in e["messages"]}, {"A": True, "C": False})

    def test_boite_renumerotee(self):
        self.imap.deposer(mail(objet="Avant"))
        self.ajouter_gmail()
        self.releve(1)
        self.imap.validite += 1
        self.imap.dossiers["INBOX"].clear()
        self.imap.suivant = 1                                         # les numéros (UID) repartent de 1
        self.imap.deposer(mail(objet="Après"))
        self.reussir("relever")
        self.assertEqual([m["objet"] for m in self.releve(1)["messages"]], ["Après"], "UIDVALIDITY changé : la liste repart de zéro")

    def test_probleme_de_releve(self):
        cid = self.ajouter_gmail()
        self.releve()
        self.imap.comptes[GMAIL] = "nouveau-mot-de-passe"            # mot de passe d'application révoqué
        self.reussir("relever")
        e = self.releve()
        self.assertEqual(e["comptes"][0]["probleme"], "Gmail refuse la connexion : il faut un mot de passe d'application (16 lettres), "
                                                      "pas ton mot de passe Google.")
        # la rajouter (même adresse) la répare sans doublon
        self.imap.comptes[GMAIL] = MDP_GMAIL
        self.assertEqual(self.ajouter_gmail(), cid)
        self.assertEqual([c["probleme"] for c in self.releve()["comptes"]], [""])

    def test_notifications_de_fond(self):
        self.imap.deposer(mail(de="Prof <prof@uphf.fr>", objet="Ancien"))
        self.ajouter_gmail()
        self.releve(1)

        def releve_de_fond():
            r = subprocess.run([sys.executable, "-I", "-B", str(LANCER), "--courrier"], env=self.srv.environnement,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            return [c for c in self.srv.commandes() if c[0] == "notify-send"]
        self.srv.vider()
        self.assertEqual(releve_de_fond(), [], "rien de neuf, aucune notification")
        self.imap.deposer(mail(de="Prof Durand <prof@uphf.fr>", objet="Rendu du TP"))
        self.imap.deposer(mail(de="Promo <promo@boutique.fr>", objet="Soldes", entetes={"List-Id": "promo"}))
        self.imap.deposer(mail(de="Lina <lina@gmail.com>", objet="Coucou", ), drapeaux=("\\Seen",))
        notes = releve_de_fond()
        self.assertEqual([c[-2:] for c in notes], [["Mail de Prof Durand", "Rendu du TP"]],
                         "seulement le nouveau mail non lu d'une personne ou de l'université")
        self.assertIn("string:desktop-entry:smoky", notes[0])
        self.srv.vider()
        self.assertEqual(releve_de_fond(), [], "un mail n'est signalé qu'une fois")
        self.reussir("reglages", notifier=False)
        self.imap.deposer(mail(de="Prof <prof@uphf.fr>", objet="Encore"))
        self.assertEqual(releve_de_fond(), [], "notifications coupées dans les réglages")

    def test_fenetres_prevenues(self):
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        fenetre.attendre("bonjour")
        self.ajouter_gmail()
        self.assertEqual(fenetre.attendre("change"), {"quoi": "mail"})


class TestLecture(AvecBoites):
    def preparer_mail_html(self):
        page = ('<html><head><meta http-equiv="refresh" content="0;url=https://pisteur.example/"><style>p.note{color:#123456}</style>'
                '<link rel="stylesheet" href="https://pisteur.example/s.css"><script>alert(1)</script></head>'
                '<body onload="alert(2)"><p style="color:red">Bonjour <b>toi</b></p>'
                '<img src="https://pisteur.example/p.gif"><img src="cid:logo123">'
                '<a href="javascript:alert(3)">piège</a> <a href="https://www.uphf.fr/">site</a>'
                '<iframe src="https://pisteur.example/">contenu du cadre</iframe><form action="https://x.example/"><input name=a></form>'
                '<script type="text/javascript">alert(4)</script><object data="x.swf">objet</object></body></html>')
        return self.imap.deposer(mail(de="Prof <prof@uphf.fr>", objet="Sujet du TP", texte="Bonjour toi (texte)", html=page,
                                      images=[("logo123", PNG)], pieces=[("sujet TP n°2.pdf", b"%PDF-1.4 sujet", "application/pdf")]))

    def test_ouvrir(self):
        uid = self.preparer_mail_html()
        cid = self.ajouter_gmail()
        self.releve(1)
        mid = f"{cid}:{uid}"
        code, m = self.srv.json("GET", f"/api/mail/{mid}")
        self.assertEqual(code, 200, m)
        self.assertEqual((m["objet"], m["de"], m["de_adresse"], m["texte"].strip()), ("Sujet du TP", "Prof", "prof@uphf.fr", "Bonjour toi (texte)"))
        self.assertIn("\\Seen", self.imap.lettre(uid).drapeaux, "ouvert = lu, sur le serveur aussi")
        self.assertTrue(self.message(mid)["lu"])
        [piece] = m["pieces"]
        self.assertEqual((piece["nom"], piece["taille"]), ("sujet TP n°2.pdf", len(b"%PDF-1.4 sujet")))
        # le corps : servi à part, sous une adresse tirée au sort, sans code d'accès, sans rien de dangereux
        self.assertRegex(m["corps"], r"^/courrier/[A-Za-z0-9_-]{20,64}$")
        code, h, corps = self.srv.req("GET", m["corps"], jeton=None)
        self.assertEqual(code, 200)
        csp = h["content-security-policy"]
        for morceau in ("default-src 'none'", "img-src data:", "sandbox allow-popups allow-popups-to-escape-sandbox", "frame-ancestors 'self'"):
            self.assertIn(morceau, csp)
        self.assertNotIn("allow-scripts", csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertEqual((h["x-frame-options"], h["cache-control"], h["referrer-policy"]), ("SAMEORIGIN", "no-store", "no-referrer"))
        texte = corps.decode()
        for interdit in ("<script", "alert(1)", "alert(4)", "onload", "http-equiv", "<link", "javascript:", "<iframe", "contenu du cadre",
                         "<object", "<form", "pisteur.example/\""):
            self.assertNotIn(interdit, texte, interdit)
        self.assertIn('<img src="data:image/png;base64,', texte, "l'image jointe s'affiche (cid: devenu data:)")
        self.assertIn('<base target="_blank">', texte, "les liens s'ouvrent dans le navigateur")
        self.assertIn('<a href="https://www.uphf.fr/">site</a>', texte)
        self.assertIn('style="color:red"', texte, "la mise en page du mail reste")
        self.assertIn("<style>p.note{color:#123456}</style>", texte, "ses styles d'en-tête aussi")
        self.assertEqual((m["categorie"], m["classe_par"], m["images_distantes"]), ("universite", "pc", True))
        # la pièce jointe : téléchargée, jamais affichée
        code, h, contenu = self.srv.req("GET", piece["adresse"], jeton=None)
        self.assertEqual((code, contenu, h["content-type"]), (200, b"%PDF-1.4 sujet", "application/octet-stream"))
        self.assertEqual(h["content-disposition"], "attachment; filename=\"sujet TP n_2.pdf\"; filename*=UTF-8''sujet%20TP%20n%C2%B02.pdf")
        # adresses inconnues, appel venu d'ailleurs
        for adresse in ("/courrier/" + "x" * 30, m["corps"] + "/9", m["corps"] + "x", "/courrier/../api/mail"):
            with self.subTest(adresse=adresse):
                self.assertEqual(self.srv.req("GET", adresse, jeton=None)[0], 404)
        self.assertEqual(self.srv.req("GET", m["corps"], jeton=None, entetes={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.srv.req("GET", m["corps"], jeton=None, hote="pisteur.example")[0], 403)
        self.assertEqual(self.srv.req("POST", m["corps"], jeton=None)[0], 405)

    def test_page_principale_peut_l_afficher(self):
        code, h, _ = self.srv.req("GET", "/smoky", jeton=None)
        self.assertIn("frame-src 'self'", h["content-security-policy"])

    def test_mail_disparu(self):
        uid = self.imap.deposer(mail())
        cid = self.ajouter_gmail()
        self.releve(1)
        self.imap.dossiers["INBOX"].clear()
        code, r = self.srv.json("GET", f"/api/mail/{cid}:{uid}")
        self.assertEqual((code, r), (404, {"erreur": "Ce mail n'est plus dans la boîte de réception."}))
        for mid in ("m00000000:1", "pas-un-id", f"{cid}:99999"):
            self.assertEqual(self.srv.json("GET", f"/api/mail/{mid}")[0], 404)

    def test_non_lu(self):
        uid = self.imap.deposer(mail(), drapeaux=("\\Seen",))
        cid = self.ajouter_gmail()
        self.releve(1)
        self.reussir("non_lu", id=f"{cid}:{uid}")
        self.assertNotIn("\\Seen", self.imap.lettre(uid).drapeaux)
        self.assertFalse(self.message(f"{cid}:{uid}")["lu"])
        self.reussir("lu", id=f"{cid}:{uid}")
        self.assertIn("\\Seen", self.imap.lettre(uid).drapeaux)


class TestRanger(AvecBoites):
    def test_archiver_et_corbeille_gmail(self):
        a, b = self.imap.deposer(mail(objet="A")), self.imap.deposer(mail(objet="B"))
        cid = self.ajouter_gmail()
        self.releve(2)
        self.assertEqual(self.reussir("archiver", id=f"{cid}:{a}")["message"], "Mail archivé.")
        self.assertEqual(self.reussir("corbeille", id=f"{cid}:{b}")["message"], "Mail mis à la corbeille.")
        self.assertEqual(([len(self.imap.dossiers[d]) for d in ("INBOX", "Archive", "Trash")]), [0, 1, 1])
        self.assertIn("UID MOVE", [c for _q, c, _a in self.imap.journal])
        self.assertEqual(self.etat()["messages"], [])

    def test_serveur_sans_move_ni_dossiers_speciaux(self):
        a, b = self.imap_uphf.deposer(mail(objet="A")), self.imap_uphf.deposer(mail(objet="B"))
        r = self.reussir("ajouter", genre="uphf", adresse=UPHF, motdepasse=MDP_UPHF, identifiant_envoi="12345")
        cid = r["id"]
        self.releve(2)
        self.reussir("archiver", id=f"{cid}:{a}")
        self.reussir("corbeille", id=f"{cid}:{b}")
        self.assertEqual([len(self.imap_uphf.dossiers[d]) for d in ("INBOX", "Archives", "Trash")], [0, 1, 1],
                         "dossier Archives créé ; corbeille trouvée par son nom")
        commandes = [c for _q, c, _a in self.imap_uphf.journal]
        self.assertIn("UID COPY", commandes)
        self.assertIn("UID EXPUNGE", commandes, "seul le mail rangé est effacé de la boîte (UIDPLUS)")
        self.assertNotIn("EXPUNGE", commandes)

    def test_mot_de_passe_accentue(self):
        self.imap_uphf.deposer(mail())
        self.reussir("ajouter", genre="uphf", adresse=UPHF, motdepasse=MDP_UPHF)
        self.assertIn("AUTHENTICATE", [c for _q, c, _a in self.imap_uphf.journal], "« é » : connexion PLAIN en UTF-8")
        self.releve(1)


class TestClasser(AvecBoites):
    def test_classer_et_regle(self):
        a = self.imap.deposer(mail(de="Club <club@asso.fr>", objet="Réunion", entetes={"List-Id": "club"}))
        cid = self.ajouter_gmail()
        self.releve(1)
        self.assertEqual(self.message(f"{cid}:{a}")["categorie"], "newsletters")
        r = self.reussir("classer", id=f"{cid}:{a}", categorie="personnes")
        self.assertEqual(r["message"], "Rangé dans Personnes.")
        self.assertEqual((self.message(f"{cid}:{a}")["categorie"], self.message(f"{cid}:{a}")["classe_par"]), ("personnes", "toi"))
        b = self.imap.deposer(mail(de="Club <club@asso.fr>", objet="Sortie", entetes={"List-Id": "club"}))
        self.reussir("relever")
        self.releve(2)
        self.assertEqual(self.message(f"{cid}:{b}")["categorie"], "newsletters", "sans « toujours », le suivant est trié par le PC")
        r = self.reussir("classer", id=f"{cid}:{b}", categorie="universite", toujours=True)
        self.assertEqual(r["message"], "Rangé dans Université, et les prochains de cet expéditeur aussi.")
        self.assertEqual(self.etat()["regles"], [{"expediteur": "club@asso.fr", "categorie": "universite"}])
        self.assertEqual(self.message(f"{cid}:{a}")["categorie"], "personnes", "un mail classé à la main garde ton choix")
        c = self.imap.deposer(mail(de="Club <CLUB@asso.fr>", objet="Gala", entetes={"List-Id": "club"}))
        self.reussir("relever")
        self.releve(3)
        self.assertEqual((self.message(f"{cid}:{c}")["categorie"], self.message(f"{cid}:{c}")["classe_par"]), ("universite", "regle"))
        self.reussir("oublier_regle", expediteur="club@asso.fr")
        self.assertEqual(self.etat()["regles"], [])
        self.assertEqual(self.agir("oublier_regle", expediteur="club@asso.fr")[0], 404)
        self.assertEqual(self.agir("classer", id=f"{cid}:{a}", categorie="spam")[0], 400)


class TestEcrire(AvecBoites):
    def test_envoyer_avec_pieces(self):
        cid = self.ajouter_gmail()
        code, p = self.srv.json("PUT", "/api/mail/pieces?nom=" + urllib.parse.quote("compte-rendu TP.pdf"), b"%PDF-1.7 rendu")
        self.assertEqual(code, 201, p)
        self.assertRegex(p["jeton"], r"^[0-9a-f]{24}$")
        r = self.reussir("envoyer", compte=cid, a="Prof Durand <prof@uphf.fr>; ami@gmail.com", cc="lina@gmail.com",
                         objet="Rendu du TP\r\nBcc: espion@x.fr", texte="Bonjour,\nvoici mon rendu.\n", pieces=[p["jeton"]],
                         en_reponse_a="<abc@uphf.fr>", references="<zzz@uphf.fr>")
        self.assertEqual(r["message"], "Mail envoyé.")
        [envoi] = self.smtp.recus
        self.assertEqual((envoi["qui"], envoi["de"], sorted(envoi["a"])), (GMAIL, GMAIL, ["ami@gmail.com", "lina@gmail.com", "prof@uphf.fr"]))
        m = message_from_bytes(envoi["donnees"], policy=policy.default)
        self.assertEqual((m["From"], m["To"], m["Cc"]), ("Moi Essai <moi@gmail.com>", "Prof Durand <prof@uphf.fr>, ami@gmail.com", "lina@gmail.com"))
        self.assertEqual(m["Subject"], "Rendu du TP Bcc: espion@x.fr", "pas d'en-tête glissé par un retour à la ligne")
        self.assertIsNone(m["Bcc"])
        self.assertEqual((m["In-Reply-To"], m["References"]), ("<abc@uphf.fr>", "<zzz@uphf.fr> <abc@uphf.fr>"))
        self.assertIn("voici mon rendu.", m.get_body(("plain",)).get_content())
        [piece] = list(m.iter_attachments())
        self.assertEqual((piece.get_filename(), piece.get_content_type(), piece.get_payload(decode=True)),
                         ("compte-rendu TP.pdf", "application/pdf", b"%PDF-1.7 rendu"))
        self.assertEqual(self.imap.dossiers["Sent"], [], "Gmail range lui-même ses envoyés")
        self.assertEqual(self.agir("envoyer", compte=cid, a="x@y.fr", pieces=[p["jeton"]])[0], 410, "pièce jointe envoyée puis effacée")

    def test_uphf_identifiant_d_envoi_et_copie_envoyee(self):
        r = self.reussir("ajouter", genre="uphf", adresse=UPHF, nom="Prénom Nom", motdepasse=MDP_UPHF, identifiant_envoi="12345")
        self.assertEqual(self.etat()["comptes"][0]["envoi"], "12345@uphf.fr")
        self.reussir("ajouter", genre="uphf", adresse=UPHF, nom="Prénom Nom", motdepasse=MDP_UPHF)
        self.assertEqual(self.etat()["comptes"][0]["envoi"], "12345@uphf.fr", "mot de passe remis : le numéro ENT reste")
        self.reussir("envoyer", compte=r["id"], a="prof@uphf.fr", objet="Absence", texte="Bonjour")
        self.assertEqual(self.smtp.recus[0]["qui"], "12345@uphf.fr", "à l'UPHF, l'envoi se fait avec le numéro ENT")
        self.assertEqual([a for v, a in self.smtp.journal if v == "AUTH"], ["PLAIN"], "mot de passe accentué : AUTH PLAIN en UTF-8")
        [copie] = self.imap_uphf.dossiers["Sent"]
        self.assertIn("\\Seen", copie.drapeaux)
        self.assertIn(b"Subject: Absence", copie.brut)

    def test_refus_a_l_envoi(self):
        cid = self.ajouter_gmail()
        for valeurs, code, message in (({"a": ""}, 400, "Indique au moins un destinataire."),
                                       ({"a": "pas une adresse"}, 400, "Adresse invalide : pas une adresse."),
                                       ({"a": "ok@uphf.fr, faux@, \"Nom, Prénom\" <np@uphf.fr>"}, 400, "Adresse invalide : faux@."),
                                       ({"a": "x@y.fr", "pieces": ["0" * 24]}, 410, "Une pièce jointe n'est plus là : rajoute-la.")):
            with self.subTest(valeurs=valeurs):
                self.assertEqual(self.agir("envoyer", compte=cid, objet="x", texte="x", **valeurs), (code, {"erreur": message}))
        self.smtp.refus_destinataires = {"inconnu@uphf.fr"}
        self.assertEqual(self.agir("envoyer", compte=cid, a="inconnu@uphf.fr", objet="x", texte="x"),
                         (400, {"erreur": "Le serveur refuse ces destinataires : vérifie les adresses. Rien n'a été envoyé."}))
        self.smtp.comptes[GMAIL] = "autre"
        self.assertEqual(self.agir("envoyer", compte=cid, a="a@b.fr", objet="x", texte="x"),
                         (401, {"erreur": "Le serveur d'envoi refuse la connexion : vérifie le mot de passe. Rien n'a été envoyé."}))
        self.assertEqual(self.smtp.recus, [])

    def test_transferer_avec_les_pieces(self):
        uid = self.imap.deposer(mail(objet="Planning", pieces=[("planning.pdf", b"%PDF planning", "application/pdf")]))
        cid = self.ajouter_gmail()
        self.releve(1)
        self.reussir("envoyer", compte=cid, a="lina@gmail.com", objet="Tr : Planning", texte="Pour toi", transfert=f"{cid}:{uid}")
        m = message_from_bytes(self.smtp.recus[0]["donnees"], policy=policy.default)
        [piece] = list(m.iter_attachments())
        self.assertEqual((piece.get_filename(), piece.get_payload(decode=True)), ("planning.pdf", b"%PDF planning"))

    def test_trop_lourd(self):
        cid = self.ajouter_gmail()
        self.assertEqual(self.srv.req("PUT", "/api/mail/pieces?nom=gros.bin", "x", entetes={"Content-Length": "25000001"})[0], 413)
        jetons = [self.srv.json("PUT", "/api/mail/pieces?nom=a.bin", b"x" * 13_000_000)[1]["jeton"] for _ in range(2)]
        self.assertEqual(self.agir("envoyer", compte=cid, a="a@b.fr", pieces=jetons),
                         (413, {"erreur": "Pièces jointes trop lourdes : 25 Mo en tout au plus."}))
        self.assertEqual(self.srv.req("PUT", "/api/mail/pieces?nom=vide.txt", b"")[0], 400)

    def test_brouillon(self):
        self.assertIsNone(self.etat()["brouillon"])
        self.reussir("brouillon", brouillon={"compte": "m12345678", "a": "lina@gmail.com", "objet": "Idée", "texte": "Et si…",
                                             "pieces": [{"jeton": "a" * 24, "nom": "x.pdf", "taille": 3}, {"jeton": "../x"}]})
        b = self.etat()["brouillon"]
        self.assertEqual((b["a"], b["objet"], b["texte"], b["pieces"]), ("lina@gmail.com", "Idée", "Et si…",
                                                                        [{"jeton": "a" * 24, "nom": "x.pdf", "taille": 3}]))
        self.reussir("brouillon", brouillon=None)
        self.assertIsNone(self.etat()["brouillon"])
        self.assertEqual(self.agir("brouillon", brouillon="texte")[0], 400)


class TestOutlook(AvecBoites):
    def test_connexion_microsoft(self):
        code, r = self.agir("microsoft_debut")
        self.assertEqual((code, r), (400, {"erreur": "Renseigne d'abord l'identifiant d'application Microsoft."}))
        self.assertEqual(self.agir("microsoft_id", id_appli="pas-un-id")[0], 400)
        self.reussir("microsoft_id", id_appli="1234ABCD-12ab-34cd-56ef-1234567890ab")
        self.assertEqual(self.etat()["reglages"]["microsoft"], "1234abcd-12ab-34cd-56ef-1234567890ab")
        self.imap.jetons["moi@outlook.fr"] = self.ms.jeton_acces
        self.imap.deposer(mail(a="moi@outlook.fr", objet="Bienvenue sur Outlook"))
        self.reussir("microsoft_debut")
        e = self.etat()
        self.assertEqual((e["microsoft"]["etat"], e["microsoft"]["code"], e["microsoft"]["adresse_page"]),
                         ("attente", "ABCD-EFGH", "https://microsoft.com/devicelogin"))
        e = attendre(lambda: (lambda x: x if x["microsoft"]["etat"] != "attente" else None)(self.etat()), 15, 0.2)
        self.assertEqual((e["microsoft"]["etat"], e["microsoft"]["adresse"]), ("fini", "moi@outlook.fr"), e["microsoft"])
        [c] = e["comptes"]
        self.assertEqual((c["adresse"], c["genre"], c["auth"], c["nom"]), ("moi@outlook.fr", "outlook", "microsoft", "Moi Essai"))
        self.assertEqual(self.trousseau()[f"service smoky quoi mail-jeton-microsoft compte {c['id']}"]["secret"], "renouveau-1",
                         "seul le jeton de renouvellement est gardé, dans le trousseau")
        self.assertEqual([m["objet"] for m in self.releve(1)["messages"]], ["Bienvenue sur Outlook"])
        self.assertIn((None, "AUTHENTICATE", "XOAUTH2"), self.imap.journal, "connexion par jeton, jamais par mot de passe")
        self.assertNotIn("LOGIN", [c for _q, c, _a in self.imap.journal])
        # serveur relancé : le jeton d'accès (en mémoire) est perdu, le jeton de renouvellement sert
        self.srv.arreter()
        self.srv.demarrer()
        self.imap.jetons["moi@outlook.fr"] = None
        avant = len(self.ms.demandes)

        def renouvele():
            self.imap.jetons["moi@outlook.fr"] = self.ms.jeton_acces
            return any(d[1].get("grant_type") == "refresh_token" for d in self.ms.demandes[avant:])
        self.reussir("relever")
        attendre(renouvele, 10, 0.05)

        # la première relève a pu partir avant que le faux serveur connaisse le nouveau jeton :
        # on relève jusqu'à ce que le compte n'ait plus de problème (10 s au plus)
        def sans_probleme():
            self.reussir("relever")
            return [c["probleme"] for c in self.releve()["comptes"]] == [""]
        self.assertTrue(attendre(sans_probleme, 10, 0.3), self.releve()["comptes"])
        # l'envoi passe par STARTTLS puis XOAUTH2
        self.smtp_outlook.jetons["moi@outlook.fr"] = self.ms.jeton_acces
        self.reussir("envoyer", compte=c["id"], a="ami@gmail.com", objet="Test", texte="Salut")
        self.assertEqual(self.smtp_outlook.recus[0]["qui"], "moi@outlook.fr")
        self.assertEqual([v for v, _ in self.smtp_outlook.journal][:4], ["EHLO", "STARTTLS", "EHLO", "AUTH"])

    def test_outlook_coupe_l_envoi(self):
        self.reussir("microsoft_id", id_appli="1234abcd-12ab-34cd-56ef-1234567890ab")
        self.imap.jetons["moi@outlook.fr"] = self.ms.jeton_acces
        self.reussir("microsoft_debut")
        e = attendre(lambda: (lambda x: x if x["microsoft"]["etat"] == "fini" else None)(self.etat()), 15, 0.2)
        self.smtp_outlook.refus_auth = "535 5.7.139 Authentication unsuccessful, SmtpClientAuthentication is disabled for the Mailbox."
        code, r = self.agir("envoyer", compte=e["comptes"][0]["id"], a="ami@gmail.com", objet="x", texte="x")
        self.assertEqual(code, 502)
        self.assertIn("Outlook a coupé l'envoi depuis les applis de messagerie", r["erreur"])

    def test_annuler(self):
        self.reussir("microsoft_id", id_appli="1234abcd-12ab-34cd-56ef-1234567890ab")
        self.ms.attente = 99
        self.reussir("microsoft_debut")
        self.reussir("microsoft_annuler")
        self.assertEqual(self.etat()["microsoft"]["etat"], "repos")
        time.sleep(1.5)
        self.assertEqual(self.etat()["comptes"], [])


class TestInstallation(unittest.TestCase):
    def test_raccourcis_et_dock(self):
        smoky = (RACINE / "usr/share/applications/smoky.desktop").read_text()
        self.assertIn("[Desktop Action mail]\nName=Mail\nExec=/usr/bin/smoky --aller /mail\n", smoky)
        self.assertIn("Actions=notes;agenda;mail;systeme;", smoky)
        self.assertRegex(smoky, r"Keywords=[^\n]*;mail;", "chercher « mail » dans GNOME trouve l'appli Smoky")
        ancien = (RACINE / "usr/share/applications/smoky-mail.desktop").read_text()
        self.assertIn("Name=Smoky Mail (ancien)\n", ancien)
        self.assertIn("Exec=/usr/bin/smoky-mail\n", ancien, "l'ancien reste lançable, sous le même nom de fichier")
        self.assertNotIn("Email", ancien, "il ne se présente plus comme l'appli de mail")
        # dock Smoky par défaut : construit par build_files/smoky.sh (dépôt), écrit dans dock.json (image)
        source, image = RACINE.parent / "build_files/smoky.sh", RACINE / "usr/share/smoky-bureau/dock.json"
        if source.is_file():
            import re
            favoris = " ".join(re.findall(r"DOCK\+?=\(([^)]*)\)", source.read_text())).split()
        else:
            import json
            favoris = json.loads(image.read_text())["dock"]
        self.assertEqual(favoris[0], "smoky.desktop")
        self.assertNotIn("smoky-mail.desktop", favoris, "plus d'icône à part dans le dock par défaut")

    def test_dock(self):
        """L'icône de l'ancien Smoky Mail quitte le dock une fois ; Smoky prend sa place s'il n'y est pas."""
        script = (RACINE / "usr/libexec/z13os/user-setup.sh").read_text()
        debut = script.index('MARK="$HOME/.config/smoky/setup-mail-dans-smoky"')
        bloc = script[debut:script.index("\nfi\n", debut) + 4]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "bin").mkdir()
            (d / "bin/dconf").write_text('#!/bin/bash\ncat "$HOME/dock"\n')
            (d / "bin/gsettings").write_text('#!/bin/bash\nprintf %s "$4" > "$HOME/dock"\n')
            for f in ("dconf", "gsettings"):
                (d / "bin" / f).chmod(0o755)
            for avant, apres in (("['smoky.desktop', 'z13-whatsapp.desktop', 'smoky-mail.desktop', 'z13-drive.desktop']",
                                  "['smoky.desktop', 'z13-whatsapp.desktop', 'z13-drive.desktop']"),
                                 ("['google-chrome.desktop', 'smoky-mail.desktop']", "['google-chrome.desktop', 'smoky.desktop']"),
                                 ("['smoky-mail.desktop', 'smoky.desktop']", "['smoky.desktop']"),
                                 ("['smoky-mail.desktop']", "['smoky.desktop']"),
                                 ("['google-chrome.desktop']", "['google-chrome.desktop']")):
                with self.subTest(avant=avant):
                    (d / ".config/smoky/setup-mail-dans-smoky").unlink(missing_ok=True)
                    (d / "dock").write_text(avant)
                    env = {**os.environ, "HOME": str(d), "PATH": f"{d / 'bin'}:/usr/bin:/bin"}
                    subprocess.run(["bash", "-c", bloc], env=env, check=True)
                    self.assertEqual((d / "dock").read_text(), apres)
                    self.assertTrue((d / ".config/smoky/setup-mail-dans-smoky").exists())
                    (d / "dock").write_text("['smoky-mail.desktop']")
                    subprocess.run(["bash", "-c", bloc], env=env, check=True)
                    self.assertEqual((d / "dock").read_text(), "['smoky-mail.desktop']", "une seule fois : remis à la main, il reste")

    def test_releve_de_fond_installee(self):
        unites = RACINE / "usr/lib/systemd/user"
        service, minuteur = (unites / "smoky-courrier.service").read_text(), (unites / "smoky-courrier.timer").read_text()
        self.assertIn("ExecStart=/usr/bin/python3 -I /usr/lib/smoky/lancer.py --courrier", service)
        self.assertIn("ConditionPathExists=%h/.local/share/smoky/mail-actif", service, "seulement une fois une boîte ajoutée")
        self.assertIn("OnUnitActiveSec=15min", minuteur)
        ancien = (unites / "smoky-mail.service").read_text()
        self.assertIn("ConditionPathExists=!%h/.local/share/smoky/mail-actif", ancien,
                      "l'ancien Smoky Mail se tait dès que le nouveau relève (pas de notifications en double)")


if __name__ == "__main__":
    unittest.main(verbosity=1)
