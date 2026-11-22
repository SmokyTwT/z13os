#!/usr/bin/env python3
"""Le Mail de l'appli Smoky dans un vrai navigateur, contre les faux serveurs IMAP, SMTP et Microsoft
de test_mail.py (aucune vraie boîte n'est jamais contactée). On clique comme une main sur le pavé
tactile, et l'on vérifie ce que la page montre ET ce que les serveurs ont vraiment reçu.

  python3 tests/test_mail_page.py
  SMOKY_CAPTURES=dossier python3 tests/test_mail_page.py     garde une image de chaque écran
"""
import json
import shutil
import sys
import tempfile
import time
import unittest
from email import message_from_bytes, policy
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from faux_courrier import mail  # noqa: E402
from test_mail import GMAIL, MDP_GMAIL, PNG, AvecBoites  # noqa: E402
from test_smoky import attendre  # noqa: E402
from test_smoky_page import CHROME, Navigateur  # noqa: E402


@unittest.skipUnless(CHROME, "aucun Chrome ou Chromium trouvé (variable SMOKY_CHROME pour en désigner un)")
class TestMailDansLeNavigateur(AvecBoites):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dossier_nav = Path(tempfile.mkdtemp(prefix="smoky-mail-nav-"))
        cls.nav = Navigateur(CHROME, cls.dossier_nav)

    @classmethod
    def tearDownClass(cls):
        cls.nav.fermer()
        shutil.rmtree(cls.dossier_nav, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.nav.dimensions = (1280, 800)
        self.nav.nouvel_onglet()

    # --- aides ---
    def ouvrir(self, suite="/mail"):
        self.nav.aller(f"http://localhost:{self.srv.port}/smoky#k={self.srv.jeton}&a={suite}")
        self.nav.attendre("document.querySelector('.mail .entete h1') !== null", quoi="la page Mail s'affiche")

    def sans_souci(self, tolerer=()):
        self.assertEqual(self.nav.soucis(tolerer), [], "erreurs relevées dans le navigateur")
        dehors = [a for a in self.nav.demandes() if not a.startswith(f"http://localhost:{self.srv.port}/")]
        self.assertEqual(dehors, [], "la page ne contacte rien d'autre que le serveur local")

    def lignes(self):
        return self.nav.evaluer("[...document.querySelectorAll('.ligne-mail')].map((a) => [a.querySelector('.objet').textContent, a.classList.contains('non-lu')])")

    def attendre_lignes(self, objets, quoi=None):
        self.nav.attendre(f"JSON.stringify([...document.querySelectorAll('.ligne-mail .objet')].map((x) => x.textContent)) === {json.dumps(json.dumps(objets, ensure_ascii=False, separators=(",", ":")))}",
                          quoi=quoi or f"la liste montre {objets}")

    def annonce(self, texte):
        self.nav.attendre(f"[...document.querySelectorAll('.annonce')].some((a) => a.textContent.includes({json.dumps(texte)}))", quoi=f"annonce « {texte} »")

    def dialogue(self):
        return "document.querySelector('dialog[open]')"

    def deposer_quelques_mails(self):
        maintenant = time.time()
        self.imap.deposer(mail(de="Lina Martin <lina.martin@gmail.com>", objet="Ciné ce soir ?", texte="On se voit à 20 h ?\nhttps://cinema.example/seance",
                               date=maintenant - 60))
        self.imap.deposer(mail(de="Secrétariat <scolarite@uphf.fr>", objet="Inscriptions aux examens", texte="Les inscriptions ferment vendredi.",
                               date=maintenant - 3600, pieces=[("calendrier examens.pdf", b"%PDF-1.4 examens", "application/pdf")]))
        self.imap.deposer(mail(de="Amazon.fr <confirmation@amazon.fr>", objet="Votre commande", texte="Expédiée.", date=maintenant - 7200),
                          drapeaux=("\\Seen",))
        self.imap.deposer(mail(de="Le Monde <news@lemonde.fr>", objet="La lettre du jour", texte="Bonjour", date=maintenant - 86400 * 2,
                               entetes={"List-Unsubscribe": "<mailto:x@lemonde.fr>"}))

    # --- essais ---
    def test_premiere_boite(self):
        self.ouvrir()
        self.nav.attendre("document.body.innerText.includes('ajoute tes boîtes')", quoi="l'accueil sans boîte")
        self.nav.capture("mail-accueil")
        self.nav.cliquer("Ajouter une boîte Gmail")
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.innerText.includes('mot de passe d\\'application')")
        self.assertEqual(self.nav.evaluer("document.querySelectorAll('input[type=password]').length"), 0,
                         "pas de champ « mot de passe » : le navigateur ne propose pas de l'enregistrer")
        # la page d'aide de Google s'ouvre dans le navigateur habituel
        self.nav.cliquer("Ouvrir la page de Google", dans=self.dialogue())
        self.assertEqual(attendre(lambda: [c for c in self.srv.commandes() if c[0] == "gio"], 5),
                         [["gio", "open", "https://myaccount.google.com/apppasswords"]])
        # mauvais mot de passe : l'erreur s'affiche dans le dialogue, rien n'est gardé
        self.nav.ecrire("dialog[open] input[type=email]", GMAIL)
        self.nav.ecrire("dialog[open] input.secret", "mon-mot-de-passe-google")
        self.nav.capture("mail-ajout-gmail")
        self.nav.cliquer("Ajouter", dans=self.dialogue())
        self.nav.attendre(f"{self.dialogue()}.querySelector('.erreur').textContent.includes('mot de passe d\\'application (16 lettres)')",
                          quoi="le refus de Gmail expliqué dans le dialogue")
        self.assertEqual(self.nav.evaluer("document.querySelector('dialog[open] input.secret').value"), "", "le champ est vidé")
        self.assertEqual(self.trousseau(), {})
        # le bon (avec les espaces affichés par Google)
        self.imap.deposer(mail(de="Lina <lina@gmail.com>", objet="Bienvenue"))
        self.nav.ecrire("dialog[open] input.secret", "abcd efgh ijkl mnop")
        self.nav.ecrire("dialog[open] input[placeholder='Prénom Nom']", "Moi Essai")
        self.nav.cliquer("Ajouter", dans=self.dialogue())
        self.annonce(f"{GMAIL} ajoutée")
        self.nav.attendre("!document.querySelector('dialog')", quoi="le dialogue se ferme")
        self.attendre_lignes(["Bienvenue"])
        self.assertEqual(list(self.trousseau().values())[0]["secret"], MDP_GMAIL)
        self.assertNotIn(MDP_GMAIL.encode(), (self.srv.base / "donnees/smoky.db").read_bytes())
        self.nav.attendre("document.querySelector('.mail .sous').textContent.startsWith('1 non lu')")
        self.sans_souci(tolerer=("401",))

    def test_lire_un_mail(self):
        page = ('<html><head><style>p.note{color:#2a6}</style></head><body><p class="note">Bonjour <b>toi</b></p>'
                '<img src="cid:logo123"><img src="https://pisteur.example/p.gif"><script>alert(1)</script>'
                '<a href="https://www.uphf.fr/">le site</a></body></html>')
        uid = self.imap.deposer(mail(de="Prof Durand <prof@uphf.fr>", objet="Sujet du TP", texte="Bonjour toi\nhttps://moodle.example/tp", html=page,
                                     images=[("logo123", PNG)], pieces=[("sujet TP.pdf", b"%PDF-1.4 sujet", "application/pdf")],
                                     date=time.time() - 86400 * 3))
        self.deposer_quelques_mails()
        cid = self.ajouter_gmail()
        self.releve(5)
        self.ouvrir()
        self.attendre_lignes(["Ciné ce soir ?", "Inscriptions aux examens", "Votre commande", "La lettre du jour", "Sujet du TP"])
        self.assertEqual([non_lu for _o, non_lu in self.lignes()], [True, True, False, True, True])
        self.nav.capture("mail-liste")
        self.nav.evaluer("document.querySelector(`.ligne-mail[data-cle='" + f"{cid}:{uid}" + "']`).click()")
        self.nav.attendre("document.querySelector('.lettre iframe.feuille-lettre') !== null", quoi="le mail s'ouvre")
        cadre = self.nav.evaluer("(() => { const f = document.querySelector('iframe.feuille-lettre'); return [f.getAttribute('sandbox'), f.getAttribute('src')]; })()")
        self.assertEqual(cadre[0], "allow-popups allow-popups-to-escape-sandbox", "cadre sans script ni accès à l'appli")
        self.assertRegex(cadre[1], r"^/courrier/[A-Za-z0-9_-]{20,64}$")
        self.nav.attendre(f"[...document.querySelectorAll('.ligne-mail')].some((a) => a.dataset.cle === '{cid}:{uid}' && !a.classList.contains('non-lu'))",
                          quoi="le mail ouvert n'est plus « non lu » dans la liste")
        self.assertIn("\\Seen", self.imap.lettre(uid).drapeaux)
        self.assertEqual(self.nav.evaluer("document.querySelector('.pieces-mail a').getAttribute('download')"), "sujet TP.pdf")
        self.assertEqual(self.nav.evaluer("document.querySelector('.rangement').textContent"), "Université, trié par le PC. Changer")
        time.sleep(0.5)                            # le cadre se charge
        self.nav.capture("mail-lecture-html")
        self.assertTrue(any("/courrier/" in a for a in self.nav.demandes()), "le corps est demandé au serveur local")
        # le texte seul, liens cliquables
        self.nav.cliquer("Voir le texte seul")
        self.nav.attendre("document.querySelector('.texte-lettre a') !== null")
        self.assertEqual(self.nav.evaluer("[...document.querySelectorAll('.texte-lettre a')].map((a) => [a.getAttribute('href'), a.target, a.rel])"),
                         [["https://moodle.example/tp", "_blank", "noopener noreferrer"]])
        self.nav.capture("mail-lecture-texte")
        self.sans_souci()

    def ouvrir_ligne(self, objet):
        self.nav.evaluer(f"[...document.querySelectorAll('.ligne-mail')].find((a) => a.querySelector('.objet').textContent === {json.dumps(objet)}).click()")
        self.nav.attendre(f"document.querySelector('.lettre-tete h2') && document.querySelector('.lettre-tete h2').textContent === {json.dumps(objet)}",
                          quoi=f"« {objet} » s'ouvre")

    def dossier(self, cle):
        self.nav.evaluer(f"document.querySelector('.dossiers [data-cle={json.dumps(cle)}]').click()")

    def joindre(self, chemin):
        racine = self.nav.ordre("DOM.getDocument", page=True)["root"]["nodeId"]
        noeud = self.nav.ordre("DOM.querySelector", page=True, nodeId=racine, selector=".ecrire input[type=file]")["nodeId"]
        self.nav.ordre("DOM.setFileInputFiles", page=True, nodeId=noeud, files=[str(chemin)])

    def test_repondre_a_tous(self):
        uid = self.imap.deposer(mail(de="Prof Durand <prof@uphf.fr>", a=f"Moi <{GMAIL}>, Camille Roy <camille@uphf.fr>",
                                     objet="Rendu du TP", texte="Merci de rendre le TP avant vendredi.\nCordialement"))
        self.ajouter_gmail()
        self.releve(1)
        self.ouvrir()
        self.attendre_lignes(["Rendu du TP"])
        self.ouvrir_ligne("Rendu du TP")
        self.nav.cliquer("Répondre à tous")
        self.nav.attendre("document.querySelector('form.ecrire') !== null", quoi="l'écriture s'ouvre")
        champs = self.nav.evaluer("['#mail-a', '#mail-cc', '#mail-objet', '.texte-mail'].map((s) => document.querySelector(s).value)")
        self.assertEqual(champs[:3], ["Prof Durand <prof@uphf.fr>", "Camille Roy <camille@uphf.fr>", "Re : Rendu du TP"],
                         "réponse à l'expéditeur, les autres en copie, sans moi")
        self.assertRegex(champs[3], r"^\n\nLe .+, Prof Durand a écrit :\n> Merci de rendre le TP avant vendredi\.\n> Cordialement\n$")
        self.assertEqual(self.nav.evaluer("[document.activeElement.className, document.activeElement.selectionStart]"), ["champ texte-mail", 0],
                         "le curseur attend la réponse, au-dessus de la citation")
        self.nav.evaluer("(() => { const t = document.activeElement; t.setRangeText('Bonjour, voici mon rendu.', 0, 0, 'end');"
                         " t.dispatchEvent(new Event('input', { bubbles: true })); })()")
        self.nav.capture("mail-reponse")
        self.nav.cliquer("Envoyer")
        self.annonce("Mail envoyé.")
        self.nav.attendre("document.querySelector('form.ecrire') === null && location.hash === '#/mail/boite'", quoi="retour à la liste")
        [envoi] = self.smtp.recus
        m = message_from_bytes(envoi["donnees"], policy=policy.default)
        original = message_from_bytes(self.imap.lettre(uid).brut, policy=policy.default)
        self.assertEqual((m["To"], m["Cc"], m["Subject"], m["In-Reply-To"]),
                         ("Prof Durand <prof@uphf.fr>", "Camille Roy <camille@uphf.fr>", "Re : Rendu du TP", original["Message-ID"]))
        self.assertRegex(m.get_body(("plain",)).get_content().replace("\r\n", "\n"), r"^Bonjour, voici mon rendu\.\n\nLe .+, Prof Durand a écrit :\n> Merci")
        self.assertIsNone(self.etat()["brouillon"], "le brouillon s'efface une fois le mail parti")
        self.sans_souci()

    def test_brouillon_garde(self):
        self.ajouter_gmail()
        self.releve()
        self.ouvrir()
        self.nav.cliquer("Écrire")
        self.nav.attendre("document.querySelector('form.ecrire') !== null")
        self.assertEqual(self.nav.evaluer("document.activeElement.id"), "mail-a", "le curseur attend le destinataire")
        self.nav.ecrire("#mail-a", "lina@gmail.com")
        self.nav.ecrire("#mail-objet", "Idée de sortie")
        self.nav.ecrire(".texte-mail", "Et si on allait au ciné ?")
        self.nav.attendre("document.querySelector('.ecrire .statut').textContent === 'Brouillon enregistré.'")
        self.assertEqual({k: self.etat()["brouillon"][k] for k in ("a", "objet", "texte")},
                         {"a": "lina@gmail.com", "objet": "Idée de sortie", "texte": "Et si on allait au ciné ?"})
        # ailleurs, puis retour par le dossier « Brouillon »
        self.dossier("vue-universite")
        self.nav.attendre("document.querySelector('form.ecrire') === null && !!document.querySelector('.dossiers a.brouillon')")
        self.assertIn("Brouillon : Idée de sortie", self.nav.evaluer("document.querySelector('.dossiers a.brouillon').textContent"))
        self.dossier("brouillon")
        self.nav.attendre("document.querySelector('#mail-objet') && document.querySelector('#mail-objet').value === 'Idée de sortie'")
        # fenêtre fermée puis rouverte : toujours là
        self.nav.ecrire(".texte-mail", "Et si on allait au ciné samedi ?")
        self.nav.nouvel_onglet()
        attendre(lambda: (self.etat()["brouillon"] or {}).get("texte") == "Et si on allait au ciné samedi ?", 5)
        self.ouvrir("/mail/ecrire")
        self.nav.attendre("document.querySelector('.texte-mail') && document.querySelector('.texte-mail').value === 'Et si on allait au ciné samedi ?'",
                          quoi="le brouillon revient, même tapé juste avant de fermer")
        self.nav.cliquer("Supprimer le brouillon")
        self.nav.cliquer("Supprimer", dans=self.dialogue())
        self.annonce("Brouillon supprimé.")
        self.nav.attendre("document.querySelector('form.ecrire') === null && !document.querySelector('.dossiers a.brouillon')")
        self.assertIsNone(self.etat()["brouillon"])
        self.sans_souci()

    def test_joindre_et_envoyer(self):
        self.ajouter_gmail()
        self.releve()
        self.ouvrir("/mail/ecrire")
        self.nav.attendre("document.querySelector('form.ecrire') !== null")
        self.nav.cliquer("Envoyer")
        self.nav.attendre("document.querySelector('.ecrire .statut.erreur').textContent === 'Indique au moins un destinataire.'",
                          quoi="la raison s'écrit à côté du bouton")
        self.assertEqual(self.nav.evaluer("document.activeElement.id"), "mail-a")
        fichier = self.dossier_nav / "compte-rendu.pdf"
        fichier.write_bytes(b"%PDF-1.7 rendu")
        self.joindre(fichier)
        self.nav.attendre("[...document.querySelectorAll('.pieces-envoi li')].some((li) => li.textContent.includes('compte-rendu.pdf14 o'))",
                          quoi="la pièce jointe est prête")
        self.nav.ecrire("#mail-a", "prof@uphf.fr")
        self.nav.ecrire(".texte-mail", "Bonjour, ci-joint mon compte rendu.")
        self.nav.capture("mail-ecrire")
        self.nav.cliquer("Envoyer")
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.textContent.includes('Envoyer sans objet ?')")
        self.nav.cliquer("Annuler", dans=self.dialogue())
        self.nav.attendre("document.activeElement.id === 'mail-objet'", quoi="le curseur attend l'objet")
        self.nav.ecrire("#mail-objet", "Compte rendu")
        self.nav.cliquer("Envoyer")
        self.annonce("Mail envoyé.")
        m = message_from_bytes(self.smtp.recus[0]["donnees"], policy=policy.default)
        [piece] = list(m.iter_attachments())
        self.assertEqual((m["Subject"], piece.get_filename(), piece.get_payload(decode=True)), ("Compte rendu", "compte-rendu.pdf", b"%PDF-1.7 rendu"))
        self.sans_souci()

    def test_dossiers_recherche_et_clavier(self):
        self.deposer_quelques_mails()
        self.imap.deposer(mail(de="Gagnant <win@arnaque.example>", objet="Vous avez gagné", entetes={"X-Spam-Flag": "YES"}))
        self.ajouter_gmail()
        self.releve(4)
        self.ouvrir()
        boite = ["Ciné ce soir ?", "Inscriptions aux examens", "Votre commande", "La lettre du jour"]
        self.attendre_lignes(boite, quoi="l'indésirable n'est pas dans la boîte de réception")
        self.dossier("vue-universite")
        self.attendre_lignes(["Inscriptions aux examens"])
        self.assertEqual(self.nav.evaluer("[location.hash, document.querySelector('.dossiers [aria-current=page]').dataset.cle]"),
                         ["#/mail/universite", "vue-universite"])
        self.dossier("vue-indesirable")
        self.attendre_lignes(["Vous avez gagné"])
        self.dossier("vue-non-lus")
        self.attendre_lignes(["Ciné ce soir ?", "Inscriptions aux examens", "La lettre du jour"])
        self.dossier("vue-boite")
        self.attendre_lignes(boite)
        # recherche : le curseur reste dans le champ pendant que la liste change
        self.nav.ecrire("input.recherche", "ciné")
        self.attendre_lignes(["Ciné ce soir ?"])
        self.assertTrue(self.nav.evaluer("document.activeElement.classList.contains('recherche')"))
        self.nav.ecrire("input.recherche", "gagné")
        self.attendre_lignes(["Vous avez gagné"], quoi="la recherche fouille aussi l'indésirable")
        self.nav.touche("Escape", 27)
        self.attendre_lignes(boite)
        self.nav.ecrire("input.recherche", "rien de tel")
        self.nav.attendre("document.querySelector('.messages .vide') && document.querySelector('.messages .vide').textContent === 'Aucun mail ne correspond à « rien de tel ».'")
        self.nav.touche("Escape", 27)
        self.attendre_lignes(boite)
        # au clavier : flèches dans la liste, Entrée pour ouvrir
        self.nav.evaluer("document.querySelector('.ligne-mail').focus()")
        self.nav.touche("ArrowDown", 40)
        self.assertEqual(self.nav.evaluer("document.activeElement.querySelector('.objet').textContent"), "Inscriptions aux examens")
        self.nav.touche("Enter", 13)
        self.nav.attendre("document.querySelector('.lettre-tete h2') && document.querySelector('.lettre-tete h2').textContent === 'Inscriptions aux examens'")
        self.assertEqual(self.nav.evaluer("document.activeElement.querySelector('.objet').textContent"), "Inscriptions aux examens",
                         "le clavier reste dans la liste, prêt pour le mail suivant")
        self.sans_souci()

    def test_ranger_et_regles(self):
        self.imap.deposer(mail(de="Club <club@asso.fr>", objet="Réunion du club", entetes={"List-Id": "club"}))
        self.ajouter_gmail()
        self.releve(1)
        self.ouvrir()
        self.attendre_lignes(["Réunion du club"])
        self.ouvrir_ligne("Réunion du club")
        self.assertEqual(self.nav.evaluer("document.querySelector('.rangement').textContent"), "Newsletters, trié par le PC. Changer")
        self.nav.cliquer("Changer de catégorie")
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.classList.contains('ranger-mail')")
        self.nav.cliquer("Personnes", dans=self.dialogue())
        self.nav.cliquer("Aussi les prochains mails de club@asso.fr", dans=self.dialogue())
        self.nav.capture("mail-ranger")
        self.nav.cliquer("Ranger", dans=self.dialogue())
        self.annonce("Rangé dans Personnes, et les prochains de cet expéditeur aussi.")
        self.nav.attendre("document.querySelector('.rangement').textContent === 'Personnes, rangé par toi. Changer'")
        self.assertEqual(self.etat()["regles"], [{"expediteur": "club@asso.fr", "categorie": "personnes"}])
        self.dossier("reglages")
        self.nav.attendre("document.querySelector('.reglages-mail') && document.querySelector('.reglages-mail').innerText.includes('Toujours dans Personnes.')")
        self.nav.capture("mail-reglages")
        self.nav.cliquer("Oublier la règle de club@asso.fr")
        self.nav.attendre("document.querySelector('.reglages-mail').innerText.includes(\"Aucune règle pour l'instant.\")")
        self.assertEqual(self.etat()["regles"], [])
        self.sans_souci()

    def test_archiver_corbeille_non_lu(self):
        self.imap.deposer(mail(objet="Premier", date=time.time() - 120))
        b = self.imap.deposer(mail(objet="Second", date=time.time() - 60))
        self.ajouter_gmail()
        self.releve(2)
        self.ouvrir()
        self.attendre_lignes(["Second", "Premier"])
        self.ouvrir_ligne("Second")
        self.nav.cliquer("Marquer comme non lu")
        self.annonce("Marqué comme non lu.")
        self.nav.attendre("document.querySelector('.ligne-mail').classList.contains('non-lu')")
        self.assertNotIn("\\Seen", self.imap.lettre(b).drapeaux)
        self.nav.cliquer("Marquer comme lu")
        self.annonce("Marqué comme lu.")
        self.assertIn("\\Seen", self.imap.lettre(b).drapeaux)
        self.nav.cliquer("Archiver")
        self.annonce("Mail archivé.")
        self.attendre_lignes(["Premier"])
        self.assertEqual(self.nav.evaluer("location.hash"), "#/mail/boite")
        self.ouvrir_ligne("Premier")
        self.nav.cliquer("Mettre à la corbeille")
        self.annonce("Mail mis à la corbeille.")
        self.nav.attendre("document.querySelector('.messages .vide') && document.querySelector('.messages .vide').textContent === 'Boîte vide : rien de nouveau.'")
        rangés = [[message_from_bytes(x.brut, policy=policy.default)["Subject"] for x in self.imap.dossiers[d]] for d in ("INBOX", "Archive", "Trash")]
        self.assertEqual(rangés, [[], ["Second"], ["Premier"]])
        self.sans_souci()

    def test_reglages_et_retirer(self):
        self.ajouter_gmail()
        self.releve()
        self.ouvrir("/mail/reglages")
        self.nav.attendre("document.querySelector('.reglages-mail') !== null")
        self.assertIn("Gmail, relevée à", self.nav.evaluer("document.querySelector('.reglages-mail').innerText"))
        self.nav.cliquer("Prévenir des nouveaux mails")
        self.annonce("Notifications coupées.")
        self.nav.attendre("document.querySelector('[role=switch]').getAttribute('aria-checked') === 'false'")
        self.assertIs(self.etat()["reglages"]["notifier"], False)
        self.nav.cliquer(f"Retirer {GMAIL}")
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.innerText.includes('Les mails restent sur le serveur')")
        self.nav.cliquer("Retirer", dans=self.dialogue())
        self.annonce(f"{GMAIL} retirée de Smoky")
        self.nav.attendre("document.body.innerText.includes('ajoute tes boîtes')", quoi="retour à l'accueil, sans boîte")
        self.assertEqual(self.trousseau(), {})
        self.sans_souci()

    def test_outlook(self):
        self.imap.jetons["moi@outlook.fr"] = self.ms.jeton_acces
        self.imap.deposer(mail(a="moi@outlook.fr", objet="Bienvenue sur Outlook"))
        self.ouvrir()
        self.nav.attendre("document.body.innerText.includes('ajoute tes boîtes')")
        self.nav.cliquer("Ajouter une boîte Outlook / Hotmail")
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.innerText.includes('ID d\\'application (client)')")
        self.nav.capture("mail-outlook-appli")
        self.nav.ecrire("dialog[open] input", "pas-un-id")
        self.nav.cliquer("Continuer", dans=self.dialogue())
        self.nav.attendre(f"{self.dialogue()}.querySelector('.erreur').textContent.startsWith('Identifiant invalide')")
        self.nav.ecrire("dialog[open] input", "1234abcd-12ab-34cd-56ef-1234567890ab")
        self.nav.cliquer("Continuer", dans=self.dialogue())
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.innerText.includes('Obtenir un code')")
        self.nav.cliquer("Obtenir un code", dans=self.dialogue())
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.querySelector('.code') && {self.dialogue()}.querySelector('.code').textContent === 'ABCD-EFGH'",
                          quoi="le code à entrer sur la page de Microsoft")
        self.nav.capture("mail-outlook-code")
        self.nav.cliquer("Ouvrir la page de Microsoft", dans=self.dialogue())
        self.annonce("moi@outlook.fr ajoutée")
        self.nav.attendre("!document.querySelector('dialog')", quoi="le dialogue se ferme")
        self.attendre_lignes(["Bienvenue sur Outlook"])
        self.assertIn(["gio", "open", "https://microsoft.com/devicelogin"], self.srv.commandes())
        self.sans_souci(tolerer=("400",))

    def test_petit_ecran(self):
        self.nav.taille(600, 900)
        self.deposer_quelques_mails()
        self.ajouter_gmail()
        self.releve(4)
        self.ouvrir()
        self.attendre_lignes(["Ciné ce soir ?", "Inscriptions aux examens", "Votre commande", "La lettre du jour"])
        visibles = "['.mail > .entete', '.dossiers', '.liste-mails', '.lecteur'].map((s) => getComputedStyle(document.querySelector(s)).display !== 'none')"
        self.assertEqual(self.nav.evaluer(visibles), [True, True, True, False], "la liste seule")
        self.assertEqual(self.nav.evaluer("getComputedStyle(document.querySelector('.dossiers')).flexDirection"), "row", "les dossiers en bandeau")
        self.nav.capture("mail-petit-liste")
        self.ouvrir_ligne("Ciné ce soir ?")
        self.assertEqual(self.nav.evaluer(visibles), [False, False, False, True], "le mail seul")
        self.assertEqual(self.nav.evaluer("document.activeElement.textContent"), "Ciné ce soir ?", "le titre du mail reçoit le clavier")
        self.assertLessEqual(self.nav.evaluer("document.documentElement.scrollWidth"), 600, "rien ne dépasse sur le côté")
        self.nav.capture("mail-petit-lecture")
        self.nav.cliquer("Revenir à la liste")
        self.nav.attendre(f"JSON.stringify({visibles}) === '[true,true,true,false]'", quoi="retour à la liste")
        self.sans_souci()

    def test_nouveau_mail_en_direct(self):
        self.ajouter_gmail()
        self.releve()
        self.ouvrir()
        self.nav.attendre("document.querySelector('.messages .vide') && document.querySelector('.messages .vide').textContent === 'Boîte vide : rien de nouveau.'")
        self.imap.deposer(mail(objet="Tout frais"))
        self.nav.cliquer("Relever")
        self.attendre_lignes(["Tout frais"], quoi="le nouveau mail apparaît sans recharger la page")
        self.nav.attendre("document.querySelector('.mail .sous').textContent.startsWith('1 non lu')")
        self.sans_souci()

    def test_boite_a_reparer(self):
        self.ajouter_gmail()
        self.releve()
        self.imap.comptes[GMAIL] = "nouveaumotdepass"                 # mot de passe d'application révoqué
        self.reussir("relever")
        self.releve()
        self.ouvrir()
        self.nav.attendre("document.querySelector('.alertes') && document.querySelector('.alertes').innerText.includes('Gmail refuse la connexion')")
        self.assertTrue(self.nav.evaluer("!!document.querySelector('.dossiers .souci')"))
        self.nav.capture("mail-a-reparer")
        self.nav.cliquer(f"Réparer {GMAIL}")
        self.nav.attendre(f"{self.dialogue()} && {self.dialogue()}.querySelector('input[type=email]').value === {json.dumps(GMAIL)}")
        self.assertTrue(self.nav.evaluer("document.activeElement.classList.contains('secret')"), "le curseur attend le nouveau mot de passe")
        self.nav.ecrire("dialog[open] input.secret", "nouv eaum otde pass")
        self.nav.cliquer("Ajouter", dans=self.dialogue())
        self.annonce(f"{GMAIL} ajoutée")
        self.nav.attendre("document.querySelector('.alertes').innerText === '' && !document.querySelector('.dossiers .souci')", quoi="plus d'alerte")
        self.sans_souci()


if __name__ == "__main__":
    unittest.main(verbosity=1)
