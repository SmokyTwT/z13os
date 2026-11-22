"""Mail de l'appli Smoky : tes boîtes (Gmail, Outlook, UPHF, ou tout serveur IMAP) dans une seule liste.

- Les boîtes sont rangées dans smoky.db, sans aucun secret. Le mot de passe (Gmail : mot de passe
  d'application ; UPHF : celui de l'ENT) ou le jeton de connexion Microsoft (Outlook) va dans le
  trousseau GNOME, jamais dans un fichier, et n'est jamais renvoyé à la page.
- Connexions toujours chiffrées, certificats vérifiés : IMAP sur 993, SMTP sur 465 ou 587 (STARTTLS).
- Tri sur le PC seulement : aucun mail ne part vers un service. L'expéditeur, les listes de
  diffusion, les messages automatiques et les mots de l'objet décident ; tes propres choix
  (« toujours pour cet expéditeur ») passent avant.
- Lecture : le corps d'un mail est servi à part (/courrier/<clé>), sous une adresse tirée au sort,
  dans un cadre isolé de l'appli : aucun script, aucune image ni police venues d'ailleurs (pas de
  pisteurs), aucun formulaire. Les pièces jointes se téléchargent, elles ne s'ouvrent jamais ici.
- Relève : quand la page s'ouvre, toutes les 3 min tant qu'elle est affichée, et en arrière-plan
  toutes les 15 min (lancer.py --courrier ; 30 min sur batterie). Une seule relève à la fois.

L'ancien Smoky Mail n'est jamais lu : ses boîtes se rajoutent ici de zéro (choix du 22/11/2026).
"""
import base64
import email
import email.errors
import email.header
import email.policy
import email.utils
import fcntl
import html
import imaplib
import json
import mimetypes
import os
import re
import secrets
import smtplib
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from .commandes import detacher
from .serveur import Erreur

GARDES = 500                    # mails gardés par boîte (les plus récents)
NOUVEAUX = 80                   # nouveaux mails relevés au plus par passage et par boîte
JOURS = 60                      # la relève regarde les 60 derniers jours de la boîte de réception
LECTURE_COMPLETE = 1_500_000    # au-delà, la relève ne lit que l'en-tête (le reste à l'ouverture)
EXTRAIT = 600                   # début du texte gardé (liste, recherche, tri)
PAR_PAGE = 60                   # mails par page de la liste
PIECES_MAXI = 25_000_000        # pièces jointes d'un envoi, en tout (limite de Gmail)
LECTURES = 8                    # mails ouverts gardés en mémoire (corps et pièces jointes)
DUREE_LECTURE = 1800            # une adresse /courrier/<clé> vaut 30 min

CATEGORIES = {
    "universite": "Université",
    "personnes": "Personnes",
    "achats": "Achats et factures",
    "newsletters": "Newsletters",
    "notifications": "Notifications",
    "indesirable": "Indésirable",
}
A_SIGNALER = ("universite", "personnes")          # catégories qui méritent une notification

GENRES = {
    "gmail": {"nom": "Gmail", "auth": "motdepasse",
              "imap": {"hote": "imap.gmail.com", "port": 993, "tls": "ssl"},
              "smtp": {"hote": "smtp.gmail.com", "port": 465, "tls": "ssl"}},
    "outlook": {"nom": "Outlook / Hotmail", "auth": "microsoft",
                "imap": {"hote": "outlook.office365.com", "port": 993, "tls": "ssl"},
                "smtp": {"hote": "smtp-mail.outlook.com", "port": 587, "tls": "starttls"}},
    "uphf": {"nom": "UPHF", "auth": "motdepasse",
             "imap": {"hote": "mail.uphf.fr", "port": 993, "tls": "ssl"},
             "smtp": {"hote": "smtp.uphf.fr", "port": 465, "tls": "ssl"}},
    "autre": {"nom": "Autre boîte", "auth": "motdepasse", "imap": None, "smtp": None},
}
CONSOMMATEUR_MS = re.compile(r"@(outlook|hotmail|live|msn)\.[a-z.]+$", re.I)   # Outlook.com, pas Microsoft 365
DOMAINES_UNIVERSITE = re.compile(r"(^|\.)(uphf\.fr|insa-hdf\.fr|univ-valenciennes\.fr|univ-[a-z-]+\.fr|[a-z-]*\.univ-[a-z-]+\.fr|"
                                 r"etu\.[a-z.-]+\.fr|crous-[a-z-]+\.fr|campusfrance\.org|parcoursup\.fr)$")
MARCHANDS = re.compile(r"(^|\.)(amazon\.[a-z.]+|cdiscount\.com|fnac\.com|darty\.com|boulanger\.com|leboncoin\.fr|vinted\.[a-z]+|"
                       r"laposte\.(fr|net)|colissimo\.fr|chronopost\.fr|mondialrelay\.(fr|com)|ups\.com|dhl\.[a-z.]+|dpd\.[a-z.]+|"
                       r"paypal\.[a-z.]+|sncf(-connect)?\.com|sncf\.fr|ubereats\.com|deliveroo\.fr|aliexpress\.com|temu\.com|"
                       r"apple\.com|steampowered\.com|ikea\.com|decathlon\.(fr|com))$")
MOTS_ACHAT = re.compile(r"\b(commande|order|livraison|livr[ée]|exp[ée]di|colis|facture|invoice|re[çc]u|receipt|paiement|"
                        r"remboursement|abonnement|votre achat|billet|e-billet)\b", re.I)
SANS_REPONSE = re.compile(r"(^|[._-])(no-?reply|ne-?pas-?repondre|noreply|donotreply|notifications?|alerts?|mailer-daemon|"
                          r"postmaster|bounces?|automated|robot)([._+-]|@)", re.I)

ID_COMPTE = re.compile(r"m[0-9a-f]{8}")
ID_MESSAGE = re.compile(r"(m[0-9a-f]{8}):([0-9]{1,10})")
ADRESSE = re.compile(r"[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+")
HOTE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", re.I)
JETON_PIECE = re.compile(r"[0-9a-f]{24}")

MS_AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0"
MS_SCOPES = "openid email offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send"


# --- petits outils ---------------------------------------------------------------------------------
def contexte_tls():
    """Certificats vérifiés toujours ; SMOKY_MAIL_CA : autorité des essais (serveurs locaux)."""
    ctx = ssl.create_default_context(cafile=os.environ.get("SMOKY_MAIL_CA") or None)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def surcharges():
    """Essais seulement : serveurs locaux à la place de ceux de Gmail, Outlook, UPHF, Microsoft."""
    chemin = os.environ.get("SMOKY_MAIL_SERVEURS")
    if not chemin:
        return {}
    try:
        return json.loads(Path(chemin).read_text())
    except (OSError, ValueError):
        return {}


def adresse_microsoft():
    return surcharges().get("microsoft") or MS_AUTH


def decoder(valeur):
    """En-tête lisible (=?utf-8?…?=, caractères de contrôle retirés)."""
    if valeur is None:
        return ""
    try:
        texte = str(email.header.make_header(email.header.decode_header(str(valeur))))
    except (ValueError, LookupError, email.errors.HeaderParseError):
        texte = str(valeur)
    return re.sub(r"[\x00-\x1f\x7f]+", " ", texte).strip()


def html_en_texte(source):
    source = re.sub(r"(?is)<(script|style|head|title)\b.*?</\1\s*>", " ", source)
    source = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>|</li>|</table>", "\n", source)
    source = re.sub(r"<[^>]+>", " ", source)
    source = html.unescape(source)
    source = re.sub(r"[ \t\r\f\v ]+", " ", source)
    return re.sub(r"\n\s*\n+", "\n\n", source).strip()


def corps(message):
    """(texte, html) d'un message analysé."""
    texte = page = ""
    for genre in ("plain", "html"):
        try:
            partie = message.get_body(preferencelist=(genre,))
            if partie is not None:
                contenu = partie.get_content()
                if genre == "plain":
                    texte = contenu
                else:
                    page = contenu
        except (LookupError, ValueError, AssertionError, KeyError, UnicodeError):
            pass
    if not texte and page:
        texte = html_en_texte(page)
    return texte, page


def pieces_jointes(message):
    """[(nom, type, contenu)] des pièces jointes nommées."""
    sortie = []
    for partie in message.iter_attachments():
        nom = decoder(partie.get_filename() or "")
        if not nom:
            continue
        try:
            contenu = partie.get_payload(decode=True) or b""
        except (ValueError, TypeError):
            contenu = b""
        sortie.append((nom[:200], partie.get_content_type(), contenu))
    return sortie[:40]


def analyser(brut):
    return email.message_from_bytes(brut, policy=email.policy.default)


def en_tete(message, nom):
    try:
        return decoder(message.get(nom, ""))
    except (ValueError, TypeError, email.errors.HeaderParseError, IndexError):
        return ""


def adresses(liste):
    """« Nom <a@b.fr>, c@d.fr ; e@f.fr » → [(nom, adresse)] valides ; la première mauvaise est citée."""
    sortie = []
    for morceau in re.split(r"[,;](?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", str(liste or "")):   # virgules hors guillemets
        if not morceau.strip():
            continue
        nom, adresse = email.utils.parseaddr(morceau)
        if not ADRESSE.fullmatch(adresse.strip()):
            raise Erreur(400, f"Adresse invalide : {morceau.strip()[:80]}.")
        sortie.append((nom.strip()[:100], adresse.strip()))
    return sortie


def ensemble_uid(uids):
    """[1, 2, 3, 7] → « 1:3,7 » (commande IMAP courte)."""
    uids = sorted(set(uids))
    morceaux, debut = [], None
    for i, u in enumerate(uids):
        if debut is None:
            debut = u
        if i + 1 == len(uids) or uids[i + 1] != u + 1:
            morceaux.append(str(debut) if debut == u else f"{debut}:{u}")
            debut = None
    return ",".join(morceaux)


def quoter(nom):
    """Nom de dossier IMAP entre guillemets."""
    return '"' + nom.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sur_batterie():
    secteur = batterie = False
    for s in Path("/sys/class/power_supply").glob("*"):
        try:
            genre = (s / "type").read_text().strip()
            if genre == "Mains" and (s / "online").read_text().strip() == "1":
                secteur = True
            batterie = batterie or genre == "Battery"
        except OSError:
            continue
    return batterie and not secteur


# --- trousseau GNOME ------------------------------------------------------------------------------
def secret_garder(compte_id, quoi, valeur, etiquette):
    """Dans le trousseau, jamais ailleurs : sans trousseau, rien n'est gardé."""
    try:
        r = subprocess.run(["secret-tool", "store", f"--label={etiquette}", "service", "smoky", "quoi", f"mail-{quoi}",
                            "compte", compte_id], input=valeur, text=True, capture_output=True, timeout=20)
        ok = r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:
        raise Erreur(503, "Le trousseau GNOME ne répond pas : rien n'a été gardé. Ouvre ta session normalement, puis recommence.")


def secret_lire(compte_id, quoi):
    try:
        r = subprocess.run(["secret-tool", "lookup", "service", "smoky", "quoi", f"mail-{quoi}", "compte", compte_id],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout


def secret_oublier(compte_id, quoi):
    try:
        subprocess.run(["secret-tool", "clear", "service", "smoky", "quoi", f"mail-{quoi}", "compte", compte_id],
                       capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass


# --- tri sur le PC ----------------------------------------------------------------------------------
def trier(entetes, regles):
    """Catégorie d'un mail, sans rien envoyer nulle part. → (catégorie, classé par)."""
    expediteur = entetes["de_adresse"].lower()
    if expediteur in regles:
        return regles[expediteur], "regle"
    domaine = expediteur.rsplit("@", 1)[-1]
    if entetes.get("spam"):
        return "indesirable", "pc"
    if DOMAINES_UNIVERSITE.search(domaine) or re.search(r"\bmoodle\b", entetes["de_nom"], re.I):
        return "universite", "pc"
    if MARCHANDS.search(domaine) or MOTS_ACHAT.search(entetes["objet"]):
        return "achats", "pc"
    if entetes.get("liste"):
        return "newsletters", "pc"
    if entetes.get("auto") or SANS_REPONSE.search(expediteur):
        return "notifications", "pc"
    return "personnes", "pc"


def resume(uid, message, lu, taille=0):
    """Ce que la liste garde d'un mail (sans son corps entier)."""
    texte, _ = corps(message)
    nom, adresse = email.utils.parseaddr(en_tete(message, "From"))
    try:
        date = email.utils.parsedate_to_datetime(message.get("Date")).timestamp()
    except (TypeError, ValueError, IndexError, AttributeError):
        date = time.time()
    auto = message.get("Auto-Submitted", "no").strip().lower() not in ("", "no") or \
        message.get("Precedence", "").strip().lower() in ("bulk", "junk", "auto_reply") or bool(message.get("X-Autoreply"))
    spam = message.get("X-Spam-Flag", "").strip().upper() == "YES" or message.get("X-Spam-Status", "").lower().startswith("yes")
    return {"uid": uid, "date": date, "de_nom": (nom or adresse)[:120], "de_adresse": adresse.lower()[:200],
            "a": en_tete(message, "To")[:500], "cc": en_tete(message, "Cc")[:500],
            "objet": (en_tete(message, "Subject") or "(sans objet)")[:300], "extrait": re.sub(r"\s+", " ", texte).strip()[:EXTRAIT],
            "lu": int(bool(lu)), "pieces": json.dumps([n for n, _t, _c in pieces_jointes(message)][:20], ensure_ascii=False),
            "liste": int(bool(message.get("List-Unsubscribe") or message.get("List-Id"))), "auto": int(auto), "spam": spam,
            "message_id": (message.get("Message-ID") or "").strip()[:300], "taille": taille}


# --- lecture sûre du HTML d'un mail -------------------------------------------------------------------
CSP_COURRIER = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'self'; sandbox allow-popups allow-popups-to-escape-sandbox")
ENTREE_COURRIER = ('<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
                   '<base target="_blank"><style>html{background:#fff;color:#141417;color-scheme:light}'
                   'body{margin:0;padding:22px 26px;font:15px/1.55 system-ui,sans-serif;overflow-wrap:anywhere}'
                   'img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap}</style></head><body>')


def html_sur(source, message):
    """Le HTML d'un mail, prêt pour le cadre isolé : sans script, sans cadre ni objet, sans
    redirection, sans lien javascript: ; les images jointes (cid:) deviennent des data: ; le reste
    des protections vient de la politique du cadre (CSP_COURRIER) et de son « sandbox »."""
    s = re.sub(r"(?is)<(script|iframe|frame|frameset|object|embed|applet|noscript|template|title)\b.*?</\1\s*>", "", source)
    s = re.sub(r"(?is)<(script|iframe|frame|object|embed|applet|meta|link|base|form|/form)\b[^>]*>", "", s)
    s = re.sub(r"(?is)\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", s)
    s = re.sub(r"(?is)(href|src|action|background)\s*=\s*([\"']?)\s*(javascript|vbscript|data:text|file):[^\"'>\s]*\2", r"\1=\2#\2", s)
    images = {}
    for partie in message.walk():
        cid = (partie.get("Content-ID") or "").strip().strip("<>")
        if cid and partie.get_content_maintype() == "image":
            try:
                contenu = partie.get_payload(decode=True) or b""
            except (ValueError, TypeError):
                continue
            if len(contenu) <= 5_000_000:
                images[cid] = f"data:{partie.get_content_type()};base64,{base64.b64encode(contenu).decode()}"

    def remplacer(m):
        return m.group(1) + images.get(m.group(3), "") + m.group(4)
    s = re.sub(r"(?i)(src\s*=\s*([\"']))cid:([^\"']+)([\"'])", remplacer, s)
    styles = ""
    debut = re.search(r"(?i)<body[^>]*>", s)
    if debut:                           # l'en-tête part, sauf ses styles (la mise en page du mail en dépend)
        styles = "".join(re.findall(r"(?is)<style\b[^>]*>.*?</style\s*>", s[:debut.start()]))
        s = s[debut.end():]
    s = re.sub(r"(?is)</body>.*$", "", s)
    return (ENTREE_COURRIER + styles + s + "</body></html>").encode("utf-8")


# --- connexion IMAP -----------------------------------------------------------------------------------
class Boite:
    """with Boite(compte, courrier) as b : une connexion chiffrée à la boîte, fermée en sortant."""

    def __init__(self, compte, courrier):
        self.compte, self.courrier, self.imap = compte, courrier, None

    def __enter__(self):
        c = self.compte
        imap = c["serveurs"]["imap"]
        try:
            self.imap = imaplib.IMAP4_SSL(imap["hote"], int(imap["port"]), ssl_context=contexte_tls(), timeout=40)
        except ssl.SSLCertVerificationError:
            raise Erreur(502, f"{imap['hote']} présente un certificat non valable : connexion refusée.") from None
        except (OSError, imaplib.IMAP4.error) as e:
            raise Erreur(502, f"Serveur {imap['hote']} injoignable ({type(e).__name__}).") from None
        try:
            if c["auth"] == "microsoft":
                chaine = f"user={c['adresse']}\x01auth=Bearer {self.courrier.jeton_microsoft(c)}\x01\x01".encode()
                self.imap.authenticate("XOAUTH2", lambda _defi: chaine)
            else:
                identifiant = c["serveurs"].get("identifiant") or c["adresse"]
                motdepasse = secret_lire(c["id"], "motdepasse")
                if not motdepasse:
                    raise Erreur(401, f"{c['adresse']} : mot de passe introuvable dans le trousseau. Rajoute la boîte.")
                if motdepasse.isascii():
                    self.imap.login(identifiant, motdepasse)
                else:
                    self.imap.authenticate("PLAIN", lambda _defi: f"\0{identifiant}\0{motdepasse}".encode("utf-8"))
        except imaplib.IMAP4.error as e:
            self.fermer()
            raise Erreur(401, self.refus(str(e))) from None
        try:                                          # capacités annoncées une fois connecté (MOVE, UIDPLUS…)
            typ, donnees = self.imap.capability()
            if typ == "OK" and donnees and donnees[-1]:
                self.imap.capabilities = tuple(donnees[-1].decode(errors="replace").upper().split())
        except (imaplib.IMAP4.error, OSError):
            pass
        return self

    def refus(self, detail):
        c = self.compte
        if c["genre"] == "gmail":
            return "Gmail refuse la connexion : il faut un mot de passe d'application (16 lettres), pas ton mot de passe Google."
        if c["genre"] == "uphf":
            return "L'UPHF refuse la connexion : vérifie ton adresse prenom.nom@uphf.fr et ton mot de passe de l'ENT."
        if c["auth"] == "microsoft":
            return "Outlook refuse la connexion : vérifie que l'accès IMAP est permis dans les réglages d'Outlook.com, puis reconnecte la boîte."
        return f"Connexion refusée par le serveur ({detail[:120]})."

    def fermer(self):
        try:
            self.imap.logout()
        except (imaplib.IMAP4.error, OSError, AttributeError):
            pass

    def __exit__(self, *exc):
        self.fermer()

    def choisir(self, dossier="INBOX", lecture_seule=True):
        typ, _ = self.imap.select(quoter(dossier) if dossier != "INBOX" else dossier, readonly=lecture_seule)
        if typ != "OK":
            raise Erreur(502, f"Dossier {dossier} introuvable sur le serveur.")
        _typ, donnees = self.imap.response("UIDVALIDITY")
        return (donnees[0] or b"0").decode() if donnees and donnees[0] else "0"

    def uids_depuis(self, jours):
        t = time.gmtime(time.time() - jours * 86400)        # date IMAP, mois en anglais quelle que soit la langue
        depuis = f"{t.tm_mday:02d}-{('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[t.tm_mon - 1]}-{t.tm_year}"
        typ, donnees = self.imap.uid("SEARCH", None, "SINCE", depuis)
        return [int(x) for x in (donnees[0] or b"").split()] if typ == "OK" and donnees else []

    def drapeaux(self, uids):
        """{uid: (lu, taille)} pour ces mails."""
        sortie = {}
        if not uids:
            return sortie
        typ, donnees = self.imap.uid("FETCH", ensemble_uid(uids), "(UID FLAGS RFC822.SIZE)")
        for ligne in donnees or []:
            texte = (ligne[0] if isinstance(ligne, tuple) else ligne or b"").decode(errors="replace")
            m = re.search(r"UID (\d+)", texte)
            if m:
                taille = re.search(r"RFC822\.SIZE (\d+)", texte)
                sortie[int(m.group(1))] = ("\\Seen" in texte, int(taille.group(1)) if taille else 0)
        return sortie

    def bruts(self, uids, quoi="BODY.PEEK[]"):
        """{uid: octets} (message entier, ou en-tête seulement)."""
        sortie = {}
        for i in range(0, len(uids), 20):
            typ, donnees = self.imap.uid("FETCH", ensemble_uid(uids[i:i + 20]), f"(UID {quoi})")
            for morceau in donnees or []:
                if isinstance(morceau, tuple) and len(morceau) == 2:
                    m = re.search(rb"UID (\d+)", morceau[0])
                    if m:
                        sortie[int(m.group(1))] = morceau[1]
        return sortie

    def marquer(self, uid, drapeau, mettre=True):
        self.imap.uid("STORE", str(uid), "+FLAGS" if mettre else "-FLAGS", f"({drapeau})")

    def dossiers(self):
        """[(drapeaux, nom)] annoncés par le serveur."""
        typ, donnees = self.imap.list()
        sortie = []
        for ligne in donnees or []:
            if not isinstance(ligne, bytes):
                continue
            m = re.match(rb'\(([^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?:"((?:[^"\\]|\\.)*)"|(\S+))\s*$', ligne)
            if m:
                nom = (m.group(2) if m.group(2) is not None else m.group(3)).decode(errors="replace")
                sortie.append((m.group(1).decode(errors="replace").lower(), nom.replace('\\"', '"').replace("\\\\", "\\")))
        return sortie

    def dossier_special(self, drapeaux, noms, creer=None):
        """Dossier « spécial » (\\Trash, \\Archive, \\Sent…) annoncé par le serveur, sinon par son nom,
        sinon créé (creer) s'il le faut."""
        liste = self.dossiers()
        for d in drapeaux:
            for flags, nom in liste:
                if d in flags.split():
                    return nom
        for flags, nom in liste:
            if nom.rsplit("/", 1)[-1].lower() in noms and "\\noselect" not in flags:
                return nom
        if creer:
            self.imap.create(quoter(creer))
            self.imap.subscribe(quoter(creer))
            return creer
        return None

    def deplacer(self, uid, cible):
        capacites = [c.upper() for c in getattr(self.imap, "capabilities", ())]
        if "MOVE" in capacites:
            typ, _ = self.imap.uid("MOVE", str(uid), quoter(cible))
            if typ == "OK":
                return
        typ, _ = self.imap.uid("COPY", str(uid), quoter(cible))
        if typ != "OK":
            raise Erreur(502, f"Le serveur refuse de ranger ce mail dans « {cible} ».")
        self.marquer(uid, "\\Deleted")
        if "UIDPLUS" in capacites:
            self.imap.uid("EXPUNGE", str(uid))
        else:
            self.imap.expunge()


# --- le Mail ------------------------------------------------------------------------------------------
class Courrier:
    def __init__(self, base, prevenir=None):
        self.base = base
        self.prevenir = prevenir or (lambda quoi: None)
        self.lectures = {}                      # clé → mail ouvert (corps sûr, pièces jointes, expiration)
        self.verrou = threading.Lock()
        self.releve_en_cours = False
        self.jetons_ms = {}                     # compte → (jeton d'accès, expiration), en mémoire seulement
        self.flux_ms = {"etat": "repos"}        # connexion Microsoft en cours (une à la fois)
        self.dossier_pieces = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "smoky" / "pieces"

    # --- réglages, comptes ---
    def reglages(self):
        r = self.base.reglage("mail.reglages", {}) or {}
        return {"notifier": r.get("notifier", True) is not False, "microsoft": str(r.get("microsoft", ""))}

    def comptes(self):
        sortie = []
        for c in self.base.lire("SELECT * FROM mail_comptes ORDER BY cree"):
            try:
                c["serveurs"] = json.loads(c["serveurs"])
            except ValueError:
                c["serveurs"] = {}
            sortie.append(c)
        return sortie

    def compte(self, compte_id):
        compte = next((c for c in self.comptes() if c["id"] == compte_id), None) if isinstance(compte_id, str) else None
        if compte is None:
            raise Erreur(404, "Cette boîte n'existe plus.")
        return compte

    def regles(self):
        return {r["expediteur"].lower(): r["categorie"] for r in self.base.lire("SELECT expediteur, categorie FROM mail_regles")}

    def _marque_active(self):
        """~/.local/share/smoky/mail-actif : la relève de fond tourne (et celle de l'ancien Smoky Mail se tait)."""
        marque = Path(self.base.chemin).parent / "mail-actif"
        if self.base.un("SELECT 1 AS x FROM mail_comptes LIMIT 1"):
            marque.touch()
        else:
            marque.unlink(missing_ok=True)

    # --- l'état pour la page ---
    def etat(self, categorie="", recherche="", compte="", avant=None):
        comptes = self.comptes()
        conditions, valeurs = [], []
        if categorie == "non-lus":
            conditions.append("lu = 0")
        elif categorie in CATEGORIES:
            conditions.append("categorie = ?")
            valeurs.append(categorie)
        elif categorie:
            raise Erreur(400, "Catégorie inconnue.")
        if compte:
            if not ID_COMPTE.fullmatch(compte):
                raise Erreur(400, "Boîte inconnue.")
            conditions.append("compte = ?")
            valeurs.append(compte)
        recherche = str(recherche or "").strip()[:100]
        for mot in recherche.split()[:6]:
            motif = "%" + mot.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conditions.append("(objet LIKE ? ESCAPE '\\' OR de_nom LIKE ? ESCAPE '\\' OR de_adresse LIKE ? ESCAPE '\\' "
                              "OR extrait LIKE ? ESCAPE '\\')")
            valeurs += [motif] * 4
        if avant is not None:
            conditions.append("date < ?")
            valeurs.append(float(avant))
        if categorie in ("", "non-lus") and not recherche:        # l'indésirable reste à part
            conditions.append("categorie != 'indesirable'")
        ou = " WHERE " + " AND ".join(conditions) if conditions else ""
        lignes = self.base.lire(f"SELECT * FROM mail_messages{ou} ORDER BY date DESC LIMIT ?", (*valeurs, PAR_PAGE + 1))
        comptes_lus = {c["categorie"]: (c["n"], c["non_lus"]) for c in self.base.lire(
            "SELECT categorie, COUNT(*) AS n, SUM(lu = 0) AS non_lus FROM mail_messages GROUP BY categorie")}
        ms = self.flux_ms
        return {
            "comptes": [{"id": c["id"], "adresse": c["adresse"], "nom": c["nom"], "genre": c["genre"], "auth": c["auth"],
                         "releve": c["releve"], "probleme": c["probleme"], "envoi": c["serveurs"].get("identifiant_envoi", "")}
                        for c in comptes],
            "categories": [{"id": k, "nom": v, "total": comptes_lus.get(k, (0, 0))[0], "non_lus": comptes_lus.get(k, (0, 0))[1] or 0}
                           for k, v in CATEGORIES.items()],
            "messages": [self._ligne(m) for m in lignes[:PAR_PAGE]],
            "suite": len(lignes) > PAR_PAGE,
            "releve": {"en_cours": self.releve_en_cours,
                       "derniere": max([c["releve"] for c in comptes] or [0])},
            "reglages": self.reglages(),
            "regles": [{"expediteur": r["expediteur"], "categorie": r["categorie"]}
                       for r in self.base.lire("SELECT expediteur, categorie FROM mail_regles ORDER BY expediteur")],
            "microsoft": {k: ms.get(k) for k in ("etat", "code", "adresse_page", "erreur", "adresse")},
            "genres": {k: {"nom": v["nom"], "auth": v["auth"]} for k, v in GENRES.items()},
            "brouillon": self.base.reglage("mail.brouillon", None),
        }

    def _ligne(self, m):
        try:
            pieces = json.loads(m["pieces"])
        except ValueError:
            pieces = []
        return {"id": f"{m['compte']}:{m['uid']}", "compte": m["compte"], "date": m["date"], "de": m["de_nom"],
                "de_adresse": m["de_adresse"], "objet": m["objet"], "apercu": m["extrait"][:180], "lu": bool(m["lu"]),
                "pieces": len(pieces), "categorie": m["categorie"], "classe_par": m["classe_par"]}

    # --- relève ---
    def relever(self, attendre=False, notifier=False):
        """Relève toutes les boîtes (dans un fil, sauf attendre=True). Une seule relève à la fois,
        même entre l'appli et la relève de fond (verrou dans $XDG_RUNTIME_DIR). Seule la relève de
        fond prévient (notifier=True) : la page ne relève que quand elle est à l'écran, la liste est
        alors sous tes yeux."""
        if not attendre:
            if self.releve_en_cours:
                return {"message": "Relève déjà en cours."}
            self.releve_en_cours = True
            threading.Thread(target=self._relever_fil, args=(notifier,), daemon=True).start()
            self.prevenir("mail")
            return {"message": "Relève lancée."}
        return self._relever(notifier)

    def _relever_fil(self, notifier):
        try:
            self._relever(notifier)
        finally:
            self.releve_en_cours = False
            self.prevenir("mail")

    def _relever(self, notifier):
        verrou = self.dossier_pieces.parent / "mail.verrou"
        verrou.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(verrou, "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return {"message": "Relève déjà en cours."}
            problemes, nouveaux = [], []
            regles = self.regles()
            for c in self.comptes():
                try:
                    nouveaux += self._relever_compte(c, regles)
                    self.base.ecrire("UPDATE mail_comptes SET releve = ?, probleme = '' WHERE id = ?", (time.time(), c["id"]))
                except Erreur as e:
                    problemes.append(f"{c['adresse']} : {e.message}")
                    self.base.ecrire("UPDATE mail_comptes SET probleme = ? WHERE id = ?", (e.message[:300], c["id"]))
                except (imaplib.IMAP4.error, OSError, ssl.SSLError, ValueError, EOFError) as e:
                    message = f"relève impossible ({type(e).__name__})"
                    problemes.append(f"{c['adresse']} : {message}")
                    self.base.ecrire("UPDATE mail_comptes SET probleme = ? WHERE id = ?", (message, c["id"]))
            if notifier and self.reglages()["notifier"]:
                self._notifier(nouveaux)
        return {"message": " ; ".join(problemes) if problemes else "Relève faite.", "nouveaux": len(nouveaux)}

    def _relever_compte(self, c, regles):
        """→ les nouveaux mails non lus à signaler."""
        with Boite(c, self) as b:
            validite = b.choisir("INBOX")
            if validite != c["validite"]:            # boîte renumérotée par le serveur : on repart de zéro
                with self.base.transaction():
                    self.base.ecrire("DELETE FROM mail_messages WHERE compte = ?", (c["id"],))
                    self.base.ecrire("UPDATE mail_comptes SET validite = ? WHERE id = ?", (validite, c["id"]))
            uids = b.uids_depuis(JOURS)
            presents = set(uids)
            connus = {r["uid"]: r["lu"] for r in self.base.lire("SELECT uid, lu FROM mail_messages WHERE compte = ?", (c["id"],))}
            etats = b.drapeaux([u for u in uids if u in connus] + [u for u in uids if u not in connus][-NOUVEAUX:])
            a_lire = [u for u in uids if u not in connus][-NOUVEAUX:]
            complets = b.bruts([u for u in a_lire if etats.get(u, (0, 0))[1] <= LECTURE_COMPLETE])
            entetes = b.bruts([u for u in a_lire if u not in complets], "BODY.PEEK[HEADER]")
        signaler = []
        premiere = not connus and not c["releve"]
        with self.base.transaction():
            for uid, (lu, _taille) in etats.items():
                if uid in connus and bool(connus[uid]) != lu:
                    self.base.ecrire("UPDATE mail_messages SET lu = ? WHERE compte = ? AND uid = ?", (int(lu), c["id"], uid))
            disparus = [u for u in connus if u not in presents]       # archivés ou supprimés ailleurs
            for i in range(0, len(disparus), 400):
                lot = disparus[i:i + 400]
                self.base.ecrire(f"DELETE FROM mail_messages WHERE compte = ? AND uid IN ({','.join('?' * len(lot))})", (c["id"], *lot))
            for uid in a_lire:
                brut = complets.get(uid) or entetes.get(uid)
                if brut is None:
                    continue
                lu, taille = etats.get(uid, (False, 0))
                r = resume(uid, analyser(brut), lu, taille)
                categorie, par = trier(r, regles)
                self.base.ecrire(
                    "INSERT OR REPLACE INTO mail_messages (compte, uid, date, de_nom, de_adresse, a, cc, objet, extrait, lu, pieces, "
                    "liste, auto, message_id, categorie, classe_par, notifie) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (c["id"], uid, r["date"], r["de_nom"], r["de_adresse"], r["a"], r["cc"], r["objet"], r["extrait"], r["lu"],
                     r["pieces"], r["liste"], r["auto"], r["message_id"], categorie, par, int(premiere or lu)))
                if not premiere and not lu and categorie in A_SIGNALER and not r["liste"] and not r["auto"]:
                    signaler.append({"id": f"{c['id']}:{uid}", "de": r["de_nom"], "objet": r["objet"]})
            # on ne garde que les GARDES plus récents de la boîte
            self.base.ecrire("DELETE FROM mail_messages WHERE compte = ? AND uid NOT IN "
                             "(SELECT uid FROM mail_messages WHERE compte = ? ORDER BY date DESC LIMIT ?)", (c["id"], c["id"], GARDES))
        return signaler

    def _notifier(self, nouveaux):
        """Trois notifications au plus par relève ; un mail n'est signalé qu'une fois."""
        for n in nouveaux[:3]:
            compte, uid = ID_MESSAGE.fullmatch(n["id"]).groups()
            _id, touches = self.base.ecrire("UPDATE mail_messages SET notifie = 1 WHERE compte = ? AND uid = ? AND notifie = 0",
                                            (compte, int(uid)))
            if touches:
                detacher("notify-send", "-a", "Smoky", "-i", "smoky-appli", "-h", "string:desktop-entry:smoky",
                         f"Mail de {n['de']}"[:100], n["objet"][:200])
        if len(nouveaux) > 3:
            detacher("notify-send", "-a", "Smoky", "-i", "smoky-appli", "-h", "string:desktop-entry:smoky",
                     f"{len(nouveaux) - 3} autres nouveaux mails", "À lire dans Smoky → Mail.")

    # --- un mail ---
    def _message(self, mid):
        m = ID_MESSAGE.fullmatch(str(mid or ""))
        if not m:
            raise Erreur(404, "Ce mail n'existe plus.")
        ligne = self.base.un("SELECT * FROM mail_messages WHERE compte = ? AND uid = ?", (m.group(1), int(m.group(2))))
        if ligne is None:
            raise Erreur(404, "Ce mail n'existe plus (rangé ailleurs ou supprimé).")
        return ligne

    def _brut(self, ligne, marquer_lu=False):
        compte = self.compte(ligne["compte"])
        with Boite(compte, self) as b:
            b.choisir("INBOX", lecture_seule=not marquer_lu)
            brut = b.bruts([ligne["uid"]]).get(ligne["uid"])
            if brut is None:
                raise Erreur(404, "Ce mail n'est plus dans la boîte de réception.")
            if marquer_lu and not ligne["lu"]:
                b.marquer(ligne["uid"], "\\Seen")
        return compte, brut

    def ouvrir(self, mid):
        ligne = self._message(mid)
        compte, brut = self._brut(ligne, marquer_lu=True)
        message = analyser(brut)
        texte, page = corps(message)
        pieces = pieces_jointes(message)
        cle = secrets.token_urlsafe(24)
        with self.verrou:
            maintenant = time.monotonic()
            for k in [k for k, v in self.lectures.items() if v["expire"] < maintenant]:
                del self.lectures[k]
            while len(self.lectures) >= LECTURES:
                del self.lectures[min(self.lectures, key=lambda k: self.lectures[k]["expire"])]
            self.lectures[cle] = {"html": html_sur(page, message) if page else None, "pieces": pieces,
                                  "expire": maintenant + DUREE_LECTURE}
        r = resume(ligne["uid"], message, True)
        self.base.ecrire("UPDATE mail_messages SET lu = 1, extrait = ?, pieces = ? WHERE compte = ? AND uid = ?",
                         (r["extrait"], r["pieces"], ligne["compte"], ligne["uid"]))
        self.prevenir("mail")
        repondre = en_tete(message, "Reply-To")
        return {
            "id": mid, "compte": compte["id"], "de": ligne["de_nom"], "de_adresse": ligne["de_adresse"],
            "a": en_tete(message, "To"), "cc": en_tete(message, "Cc"), "repondre_a": repondre,
            "objet": ligne["objet"], "date": ligne["date"], "categorie": ligne["categorie"], "classe_par": ligne["classe_par"],
            "texte": texte[:500_000],
            "corps": f"/courrier/{cle}" if page else None,
            "images_distantes": bool(page and re.search(r"(?is)<img\b[^>]*\bsrc\s*=\s*[\"']?\s*(https?:)?//", page)),
            "pieces": [{"nom": nom, "type": t, "taille": len(contenu), "adresse": f"/courrier/{cle}/{i}"}
                       for i, (nom, t, contenu) in enumerate(pieces)],
            "message_id": (message.get("Message-ID") or "").strip()[:300],
            "references": " ".join((message.get("References") or "").split())[-2000:],
        }

    def lecture(self, cle, piece=None):
        """/courrier/<clé>[/<n>] : (contenu, type, en-têtes) ou None (clé inconnue ou expirée)."""
        with self.verrou:
            lu = self.lectures.get(cle)
            if lu is None or lu["expire"] < time.monotonic():
                return None
        if piece is None:
            if lu["html"] is None:
                return None
            return lu["html"], "text/html; charset=utf-8", [("Content-Security-Policy", CSP_COURRIER), ("X-Frame-Options", "SAMEORIGIN"),
                                                            ("X-DNS-Prefetch-Control", "off")]
        if not 0 <= piece < len(lu["pieces"]):
            return None
        nom, _type, contenu = lu["pieces"][piece]
        ascii_ = re.sub(r"[^A-Za-z0-9._ -]", "_", nom)[:150] or "piece-jointe"
        return contenu, "application/octet-stream", [
            ("Content-Disposition", f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{urllib.parse.quote(nom, safe='')}"),
            ("Content-Security-Policy", "default-src 'none'; sandbox")]

    # --- actions ---
    def agir(self, a):
        action = a.get("action")
        fonction = getattr(self, f"_a_{action}", None) if isinstance(action, str) and action.isidentifier() else None
        if fonction is None:
            raise Erreur(400, "Action inconnue.")
        r = fonction(a)
        if action not in ("brouillon", "relever"):
            self.prevenir("mail")
        return r if r is not None else {}

    def _a_relever(self, a):
        return self.relever()

    def _a_lu(self, a):
        return self._drapeau(a, "\\Seen", True)

    def _a_non_lu(self, a):
        return self._drapeau(a, "\\Seen", False)

    def _drapeau(self, a, drapeau, mettre):
        ligne = self._message(a.get("id"))
        with Boite(self.compte(ligne["compte"]), self) as b:
            b.choisir("INBOX", lecture_seule=False)
            b.marquer(ligne["uid"], drapeau, mettre)
        self.base.ecrire("UPDATE mail_messages SET lu = ? WHERE compte = ? AND uid = ?", (int(mettre), ligne["compte"], ligne["uid"]))
        return {}

    def _a_archiver(self, a):
        return self._ranger(a, ("\\archive", "\\all"), ("archive", "archives", "all mail", "tous les messages"), "Archives",
                            "Mail archivé.")

    def _a_corbeille(self, a):
        return self._ranger(a, ("\\trash",), ("trash", "corbeille", "deleted items", "deleted", "éléments supprimés", "bin"), "Trash",
                            "Mail mis à la corbeille.")

    def _ranger(self, a, drapeaux, noms, creer, message):
        ligne = self._message(a.get("id"))
        with Boite(self.compte(ligne["compte"]), self) as b:
            cible = b.dossier_special(drapeaux, noms, creer=creer)
            b.choisir("INBOX", lecture_seule=False)
            b.deplacer(ligne["uid"], cible)
        self.base.ecrire("DELETE FROM mail_messages WHERE compte = ? AND uid = ?", (ligne["compte"], ligne["uid"]))
        return {"message": message}

    def _a_classer(self, a):
        """Changer la catégorie d'un mail ; « toujours » : aussi les prochains de cet expéditeur."""
        ligne = self._message(a.get("id"))
        categorie = a.get("categorie")
        if categorie not in CATEGORIES:
            raise Erreur(400, "Catégorie inconnue.")
        if a.get("toujours") is True:
            self.base.ecrire("INSERT INTO mail_regles (expediteur, categorie, cree) VALUES (?, ?, ?) ON CONFLICT(expediteur) "
                             "DO UPDATE SET categorie = excluded.categorie", (ligne["de_adresse"], categorie, time.time()))
            self.base.ecrire("UPDATE mail_messages SET categorie = ?, classe_par = 'regle' WHERE de_adresse = ? COLLATE NOCASE "
                             "AND classe_par != 'toi'", (categorie, ligne["de_adresse"]))
        self.base.ecrire("UPDATE mail_messages SET categorie = ?, classe_par = 'toi' WHERE compte = ? AND uid = ?",
                         (categorie, ligne["compte"], ligne["uid"]))
        return {"message": f"Rangé dans {CATEGORIES[categorie]}" + (", et les prochains de cet expéditeur aussi." if a.get("toujours") is True else ".")}

    def _a_oublier_regle(self, a):
        _id, n = self.base.ecrire("DELETE FROM mail_regles WHERE expediteur = ? COLLATE NOCASE", (str(a.get("expediteur", "")),))
        if not n:
            raise Erreur(404, "Cette règle n'existe plus.")
        return {"message": "Règle oubliée : les prochains mails de cet expéditeur seront triés par le PC."}

    def _a_reglages(self, a):
        r = self.reglages()
        if isinstance(a.get("notifier"), bool):
            r["notifier"] = a["notifier"]
        self.base.regler("mail.reglages", r)
        return {}

    def _a_brouillon(self, a):
        """Le brouillon en cours (un seul), gardé pour qu'une fenêtre fermée ne le perde pas ; null : effacé."""
        b = a.get("brouillon")
        if b is None:
            self.base.regler("mail.brouillon", None)
            return {}
        if not isinstance(b, dict):
            raise Erreur(400, "Brouillon illisible.")
        propre = {k: str(b.get(k, ""))[:200_000 if k == "texte" else 2000] for k in ("compte", "a", "cc", "objet", "texte", "en_reponse_a",
                                                                                         "references", "transfert", "genre")}
        propre["pieces"] = [p for p in b.get("pieces", []) if isinstance(p, dict) and JETON_PIECE.fullmatch(str(p.get("jeton", "")))][:20]
        propre["pieces"] = [{"jeton": p["jeton"], "nom": str(p.get("nom", ""))[:200], "taille": int(p.get("taille", 0) or 0)} for p in propre["pieces"]]
        self.base.regler("mail.brouillon", propre)
        return {}

    # --- ajouter, retirer une boîte ---
    def _a_ajouter(self, a):
        genre = a.get("genre")
        if genre not in GENRES or GENRES[genre]["auth"] != "motdepasse":
            raise Erreur(400, "Genre de boîte inconnu.")
        adresse = str(a.get("adresse", "")).strip()
        if not ADRESSE.fullmatch(adresse):
            raise Erreur(400, "Adresse mail invalide.")
        motdepasse = str(a.get("motdepasse", ""))
        if genre == "gmail":
            motdepasse = re.sub(r"\s+", "", motdepasse)        # Google affiche « abcd efgh ijkl mnop »
        if not motdepasse:
            raise Erreur(400, "Mot de passe manquant.")
        serveurs = self._serveurs(genre, adresse, a)
        ancien = self.base.un("SELECT id, serveurs FROM mail_comptes WHERE adresse = ? COLLATE NOCASE", (adresse,))
        if ancien and "identifiant_envoi" not in serveurs:          # mot de passe remis : l'identifiant d'envoi reste
            try:
                vieux = json.loads(ancien["serveurs"]).get("identifiant_envoi")
            except (ValueError, AttributeError):
                vieux = None
            if vieux:
                serveurs["identifiant_envoi"] = vieux
        compte = {"id": ancien["id"] if ancien else "m" + secrets.token_hex(4), "adresse": adresse, "genre": genre,
                  "nom": re.sub(r"[\x00-\x1f\x7f<>\"]+", " ", str(a.get("nom", ""))).strip()[:100], "auth": "motdepasse",
                  "serveurs": serveurs, "validite": "", "releve": 0}
        secret_garder(compte["id"], "motdepasse", motdepasse, f"Smoky — mail {adresse}")
        try:
            with Boite(compte, self) as b:                         # essai avant d'enregistrer
                b.choisir("INBOX")
        except Erreur:
            if not ancien:
                secret_oublier(compte["id"], "motdepasse")
            raise
        self._enregistrer_compte(compte, bool(ancien))
        return {"message": f"{adresse} ajoutée : la relève commence.", "id": compte["id"]}

    def _serveurs(self, genre, adresse, a):
        modele = surcharges().get(genre) or GENRES[genre]
        if genre == "autre" and not surcharges().get(genre):
            imap, smtp = str(a.get("imap", "")).strip().lower(), str(a.get("smtp", "")).strip().lower()
            if not (HOTE.fullmatch(imap) and HOTE.fullmatch(smtp)):
                raise Erreur(400, "Serveurs IMAP / SMTP invalides.")
            port = int(a.get("port_smtp") or 465) if str(a.get("port_smtp", "465")).isdigit() else 0
            if port not in (465, 587):
                raise Erreur(400, "Port d'envoi accepté : 465 ou 587 (connexion chiffrée).")
            modele = {"imap": {"hote": imap, "port": 993, "tls": "ssl"},
                      "smtp": {"hote": smtp, "port": port, "tls": "ssl" if port == 465 else "starttls"}}
        serveurs = {"imap": dict(modele["imap"]), "smtp": dict(modele["smtp"])}
        if genre == "outlook" and not CONSOMMATEUR_MS.search(adresse) and not surcharges().get(genre):
            serveurs["smtp"]["hote"] = "smtp.office365.com"         # Microsoft 365 (école, entreprise)
        envoi = str(a.get("identifiant_envoi", "")).strip()
        if envoi:
            if genre == "uphf" and re.fullmatch(r"[0-9A-Za-z._-]{2,40}", envoi):
                envoi = f"{envoi}@uphf.fr"                          # numéro ENT → identifiant d'envoi de l'UPHF
            if not (ADRESSE.fullmatch(envoi) or re.fullmatch(r"[0-9A-Za-z._-]{2,80}", envoi)):
                raise Erreur(400, "Identifiant d'envoi invalide.")
            serveurs["identifiant_envoi"] = envoi
        return serveurs

    def _enregistrer_compte(self, compte, existe):
        if existe:
            self.base.ecrire("UPDATE mail_comptes SET nom = ?, serveurs = ?, probleme = '' WHERE id = ?",
                             (compte["nom"], json.dumps(compte["serveurs"]), compte["id"]))
        else:
            self.base.ecrire("INSERT INTO mail_comptes (id, adresse, nom, genre, serveurs, auth, cree) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (compte["id"], compte["adresse"], compte["nom"], compte["genre"], json.dumps(compte["serveurs"]),
                              compte["auth"], time.time()))
        self._marque_active()
        self.relever()

    def _a_retirer(self, a):
        compte = self.compte(a.get("id"))
        secret_oublier(compte["id"], "motdepasse")
        secret_oublier(compte["id"], "jeton-microsoft")
        self.jetons_ms.pop(compte["id"], None)
        with self.base.transaction():
            self.base.ecrire("DELETE FROM mail_messages WHERE compte = ?", (compte["id"],))
            self.base.ecrire("DELETE FROM mail_comptes WHERE id = ?", (compte["id"],))
        self._marque_active()
        return {"message": f"{compte['adresse']} retirée de Smoky (les mails restent sur le serveur)."}

    # --- Outlook : connexion Microsoft (code à saisir sur la page officielle) ---
    def _a_microsoft_id(self, a):
        cid = str(a.get("id_appli", "")).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", cid):
            raise Erreur(400, "Identifiant invalide : c'est l'« ID d'application (client) », de la forme 1234abcd-12ab-34cd-56ef-1234567890ab.")
        r = self.reglages()
        r["microsoft"] = cid
        self.base.regler("mail.reglages", r)
        return {}

    def _poster(self, adresse, champs):
        requete = urllib.request.Request(adresse, data=urllib.parse.urlencode(champs).encode(), method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(requete, timeout=30, context=contexte_tls()) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:                     # les refus OAuth arrivent en JSON (code 400)
            try:
                return json.loads(e.read())
            except ValueError:
                return {"error": f"http_{e.code}"}
        except (urllib.error.URLError, OSError, ValueError):
            return {"error": "injoignable"}

    def _a_microsoft_debut(self, a):
        cid = self.reglages()["microsoft"]
        if not cid:
            raise Erreur(400, "Renseigne d'abord l'identifiant d'application Microsoft.")
        r = self._poster(adresse_microsoft() + "/devicecode", {"client_id": cid, "scope": MS_SCOPES})
        if "device_code" not in r:
            raise Erreur(502, f"Microsoft a refusé la demande ({r.get('error_description') or r.get('error', '?')})"[:240])
        self.flux_ms = {"etat": "attente", "code": r["user_code"], "adresse_page": r.get("verification_uri", "https://microsoft.com/devicelogin"),
                        "expire": time.time() + int(r.get("expires_in", 900)), "erreur": "", "adresse": ""}
        threading.Thread(target=self._attendre_microsoft, args=(cid, r["device_code"], int(r.get("interval", 5)), self.flux_ms),
                         daemon=True).start()
        return {}

    def _a_microsoft_annuler(self, a):
        self.flux_ms = {"etat": "repos"}
        return {}

    def _attendre_microsoft(self, cid, code_appareil, intervalle, flux):
        while time.time() < flux.get("expire", 0) and self.flux_ms is flux:
            time.sleep(intervalle)
            r = self._poster(adresse_microsoft() + "/token", {"client_id": cid, "device_code": code_appareil,
                                                              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            erreur = r.get("error")
            if erreur == "authorization_pending":
                continue
            if erreur == "slow_down":
                intervalle += 5
                continue
            if self.flux_ms is not flux:
                return
            if erreur or "refresh_token" not in r:
                flux.update(etat="erreur", erreur={"expired_token": "Code expiré : recommence.",
                                                    "authorization_declined": "Connexion refusée sur la page Microsoft."}.get(
                                                        erreur, f"Réponse de Microsoft incomplète ({erreur or '?'})."))
                self.prevenir("mail")
                return
            try:
                partie = r.get("id_token", "").split(".")[1]
                revendications = json.loads(base64.urlsafe_b64decode(partie + "=" * (-len(partie) % 4)))
            except (IndexError, ValueError):
                revendications = {}
            adresse = str(revendications.get("email") or revendications.get("preferred_username") or "").strip().lower()
            if not ADRESSE.fullmatch(adresse):
                flux.update(etat="erreur", erreur="Adresse du compte Microsoft introuvable.")
                self.prevenir("mail")
                return
            ancien = self.base.un("SELECT id FROM mail_comptes WHERE adresse = ? COLLATE NOCASE", (adresse,))
            compte = {"id": ancien["id"] if ancien else "m" + secrets.token_hex(4), "adresse": adresse, "genre": "outlook",
                      "nom": re.sub(r"[\x00-\x1f\x7f<>\"]+", " ", str(revendications.get("name", ""))).strip()[:100],
                      "auth": "microsoft", "serveurs": self._serveurs("outlook", adresse, {}), "validite": "", "releve": 0}
            try:
                secret_garder(compte["id"], "jeton-microsoft", r["refresh_token"], f"Smoky — mail {adresse} (jeton Microsoft)")
                self.jetons_ms[compte["id"]] = (r["access_token"], time.time() + int(r.get("expires_in", 3600)))
                with Boite(compte, self) as b:
                    b.choisir("INBOX")
            except Erreur as e:
                if not ancien:
                    secret_oublier(compte["id"], "jeton-microsoft")
                flux.update(etat="erreur", erreur=e.message)
                self.prevenir("mail")
                return
            self._enregistrer_compte(compte, bool(ancien))
            flux.update(etat="fini", adresse=adresse)
            self.prevenir("mail")
            return
        if self.flux_ms is flux and flux.get("etat") == "attente":
            flux.update(etat="erreur", erreur="Code expiré : recommence.")
            self.prevenir("mail")

    def jeton_microsoft(self, compte):
        jeton, expire = self.jetons_ms.get(compte["id"], ("", 0))
        if jeton and expire - 120 > time.time():
            return jeton
        renouveau = secret_lire(compte["id"], "jeton-microsoft").strip()
        if not renouveau:
            raise Erreur(401, f"{compte['adresse']} : reconnecte la boîte Outlook (Réglages du Mail).")
        r = self._poster(adresse_microsoft() + "/token", {"client_id": self.reglages()["microsoft"], "grant_type": "refresh_token",
                                                          "refresh_token": renouveau, "scope": MS_SCOPES})
        if "access_token" not in r:
            raise Erreur(401, f"{compte['adresse']} : connexion Microsoft expirée, reconnecte la boîte ({r.get('error', '?')}).")
        if r.get("refresh_token") and r["refresh_token"] != renouveau:
            secret_garder(compte["id"], "jeton-microsoft", r["refresh_token"], f"Smoky — mail {compte['adresse']} (jeton Microsoft)")
        self.jetons_ms[compte["id"]] = (r["access_token"], time.time() + int(r.get("expires_in", 3600)))
        return r["access_token"]

    # --- écrire ---
    def piece(self, nom, contenu):
        """Pièce jointe d'un mail en préparation, gardée en mémoire vive ($XDG_RUNTIME_DIR) jusqu'à l'envoi."""
        nom = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", str(nom or "")).strip()[:200] or "piece-jointe"
        if not contenu:
            raise Erreur(400, "Fichier vide.")
        self.dossier_pieces.mkdir(parents=True, exist_ok=True, mode=0o700)
        maintenant = time.time()
        for vieux in self.dossier_pieces.iterdir():                 # oubliées depuis un jour
            try:
                if maintenant - vieux.stat().st_mtime > 86400:
                    vieux.unlink()
            except OSError:
                pass
        jeton = secrets.token_hex(12)
        (self.dossier_pieces / f"{jeton}.json").write_text(json.dumps({"nom": nom}))
        (self.dossier_pieces / jeton).write_bytes(contenu)
        return {"jeton": jeton, "nom": nom, "taille": len(contenu)}

    def _a_envoyer(self, a):
        compte = self.compte(a.get("compte"))
        a_qui, copie = adresses(a.get("a")), adresses(a.get("cc"))
        if not a_qui:
            raise Erreur(400, "Indique au moins un destinataire.")
        m = EmailMessage()
        m["From"] = email.utils.formataddr((compte["nom"], compte["adresse"]))
        m["To"] = ", ".join(email.utils.formataddr(x) for x in a_qui)
        if copie:
            m["Cc"] = ", ".join(email.utils.formataddr(x) for x in copie)
        m["Subject"] = re.sub(r"[\r\n]+", " ", str(a.get("objet", "")))[:300]
        m["Date"] = email.utils.formatdate(localtime=True)
        m["Message-ID"] = email.utils.make_msgid(domain=compte["adresse"].rsplit("@", 1)[-1])
        en_reponse = re.sub(r"[\r\n]+", " ", str(a.get("en_reponse_a", "")))[:300]
        if en_reponse:
            m["In-Reply-To"] = en_reponse
            m["References"] = (re.sub(r"[\r\n]+", " ", str(a.get("references", "")))[-1500:] + " " + en_reponse).strip()
        m.set_content(str(a.get("texte", ""))[:500_000])
        total = 0
        jetons = [str(j) for j in a.get("pieces", []) if JETON_PIECE.fullmatch(str(j))][:20] if isinstance(a.get("pieces"), list) else []
        for jeton in jetons:
            try:
                nom = json.loads((self.dossier_pieces / f"{jeton}.json").read_text())["nom"]
                contenu = (self.dossier_pieces / jeton).read_bytes()
            except (OSError, ValueError, KeyError):
                raise Erreur(410, "Une pièce jointe n'est plus là : rajoute-la.") from None
            total += len(contenu)
            principal, _, secondaire = (mimetypes.guess_type(nom)[0] or "application/octet-stream").partition("/")
            m.add_attachment(contenu, maintype=principal, subtype=secondaire, filename=nom)
        if a.get("transfert"):                                       # transfert : les pièces jointes du mail d'origine
            _compte, brut = self._brut(self._message(a["transfert"]))
            for nom, type_mime, contenu in pieces_jointes(analyser(brut)):
                total += len(contenu)
                principal, _, secondaire = type_mime.partition("/")
                m.add_attachment(contenu, maintype=principal or "application", subtype=secondaire or "octet-stream", filename=nom)
        if total > PIECES_MAXI:
            raise Erreur(413, "Pièces jointes trop lourdes : 25 Mo en tout au plus.")
        self._smtp(compte, m, [x[1] for x in a_qui + copie])
        if compte["genre"] in ("uphf", "autre"):                    # Gmail et Outlook rangent eux-mêmes l'envoyé
            try:
                with Boite(compte, self) as b:
                    envoyes = b.dossier_special(("\\sent",), ("sent", "envoyés", "sent items", "sent messages", "éléments envoyés"))
                    if envoyes:
                        b.imap.append(quoter(envoyes), "(\\Seen)", imaplib.Time2Internaldate(time.time()), m.as_bytes())
            except (Erreur, imaplib.IMAP4.error, OSError):
                pass                                                # envoyé quand même : seule la copie manque
        for jeton in jetons:
            for f in (jeton, f"{jeton}.json"):
                (self.dossier_pieces / f).unlink(missing_ok=True)
        if a.get("brouillon_fini") is not False:
            self.base.regler("mail.brouillon", None)
        return {"message": "Mail envoyé."}

    def _smtp(self, compte, message, destinataires):
        s = compte["serveurs"]["smtp"]
        try:
            if s["tls"] == "ssl":
                serveur = smtplib.SMTP_SSL(s["hote"], int(s["port"]), context=contexte_tls(), timeout=40)
            else:
                serveur = smtplib.SMTP(s["hote"], int(s["port"]), timeout=40)
                serveur.ehlo()
                if not serveur.has_extn("starttls"):
                    serveur.close()
                    raise Erreur(502, f"{s['hote']} ne propose pas de connexion chiffrée : rien n'a été envoyé.")
                serveur.starttls(context=contexte_tls())
                serveur.ehlo()
        except ssl.SSLCertVerificationError:
            raise Erreur(502, f"{s['hote']} présente un certificat non valable : rien n'a été envoyé.") from None
        except (OSError, smtplib.SMTPException) as e:
            raise Erreur(502, f"Serveur d'envoi {s['hote']} injoignable ({type(e).__name__}) : rien n'a été envoyé.") from None
        try:
            with serveur:
                if compte["auth"] == "microsoft":
                    chaine = f"user={compte['adresse']}\x01auth=Bearer {self.jeton_microsoft(compte)}\x01\x01"
                    serveur.auth("XOAUTH2", lambda defi=None: chaine)
                else:
                    identifiant = compte["serveurs"].get("identifiant_envoi") or compte["adresse"]
                    motdepasse = secret_lire(compte["id"], "motdepasse")
                    if motdepasse.isascii() and identifiant.isascii():
                        serveur.login(identifiant, motdepasse)
                    else:                       # smtplib n'écrit qu'en ASCII : AUTH PLAIN en UTF-8, comme les applis de mail
                        serveur.ehlo_or_helo_if_needed()
                        if "PLAIN" not in serveur.esmtp_features.get("auth", "").upper().split():
                            raise Erreur(400, "Ce serveur n'accepte pas les mots de passe accentués à l'envoi : rien n'a été envoyé.")
                        code, reponse = serveur.docmd("AUTH", "PLAIN " + base64.b64encode(f"\0{identifiant}\0{motdepasse}".encode()).decode())
                        if code != 235:
                            raise smtplib.SMTPAuthenticationError(code, reponse)
                refuses = serveur.send_message(message, to_addrs=destinataires)
                if refuses:
                    raise Erreur(502, "Envoyé, sauf à : " + ", ".join(refuses)[:200])
        except smtplib.SMTPAuthenticationError as e:
            texte = (e.smtp_error or b"").decode(errors="replace")
            if "5.7.139" in texte or "SmtpClientAuthentication" in texte:
                raise Erreur(502, "Outlook a coupé l'envoi depuis les applis de messagerie pour cette boîte : rien n'a été envoyé. "
                                  "Envoie ce mail depuis outlook.com.") from None
            if compte["genre"] == "uphf":
                raise Erreur(401, "L'UPHF refuse l'envoi : l'identifiant d'envoi est ton numéro ENT (Réglages → la boîte UPHF).") from None
            raise Erreur(401, "Le serveur d'envoi refuse la connexion : vérifie le mot de passe. Rien n'a été envoyé.") from None
        except smtplib.SMTPRecipientsRefused:
            raise Erreur(400, "Le serveur refuse ces destinataires : vérifie les adresses. Rien n'a été envoyé.") from None
        except (smtplib.SMTPException, OSError) as e:
            raise Erreur(502, f"Envoi interrompu ({type(e).__name__}) : vérifie dans les envoyés avant de recommencer.") from None


def releve_de_fond(base):
    """lancer.py --courrier (smoky-courrier.timer, toutes les 15 min) : relève et notifications ;
    sur batterie, une fois toutes les 30 min suffit."""
    courrier = Courrier(base)
    comptes = courrier.comptes()
    if not comptes:
        return 0
    if sur_batterie() and time.time() - max(c["releve"] for c in comptes) < 1800:
        return 0
    r = courrier.relever(attendre=True, notifier=True)
    print(f"smoky : {r['message']}")
    return 0
