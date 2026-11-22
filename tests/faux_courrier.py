"""Faux serveurs de mail pour les tests de Smoky : IMAP, SMTP et connexion Microsoft, de vrais petits
serveurs locaux en TLS (certificats d'essai faits par openssl), qui parlent juste assez leur protocole
pour l'appli. Rien ne sort de la machine.
"""
import base64
import email.utils
import json
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
import urllib.parse
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def certificats(dossier):
    """Autorité d'essai + certificat « localhost » signé par elle. → (autorité, certificat, clé)."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    ca, cle_ca = dossier / "ca.pem", dossier / "ca.key"
    cert, cle, demande, ext = dossier / "serveur.pem", dossier / "serveur.key", dossier / "serveur.csr", dossier / "ext.cnf"
    if cert.exists():
        return str(ca), str(cert), str(cle)
    openssl = shutil.which("openssl") or "/usr/bin/openssl"
    courbe = ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes"]
    subprocess.run([openssl, "req", "-x509", *courbe, "-keyout", str(cle_ca), "-out", str(ca), "-days", "3",
                    "-subj", "/CN=Autorite d'essai Smoky", "-addext", "basicConstraints=critical,CA:TRUE",
                    "-addext", "keyUsage=critical,keyCertSign,cRLSign"], check=True, capture_output=True)
    subprocess.run([openssl, "req", *courbe, "-keyout", str(cle), "-out", str(demande), "-subj", "/CN=localhost"],
                   check=True, capture_output=True)
    ext.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:FALSE\n"
                   "keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n"
                   "authorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n")
    subprocess.run([openssl, "x509", "-req", "-in", str(demande), "-CA", str(ca), "-CAkey", str(cle_ca), "-CAcreateserial",
                    "-out", str(cert), "-days", "3", "-extfile", str(ext)], check=True, capture_output=True)
    return str(ca), str(cert), str(cle)


def mail(de="Lina Martin <lina.martin@gmail.com>", a="moi@gmail.com", objet="Bonjour", texte="Salut !", html=None, date=None,
         entetes=None, pieces=(), images=()):
    """Un vrai message (octets RFC 5322)."""
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = de, a, objet
    m["Date"] = email.utils.formatdate(date if date is not None else time.time(), localtime=True)
    m["Message-ID"] = email.utils.make_msgid(domain="essai.local")
    for k, v in (entetes or {}).items():
        m[k] = v
    m.set_content(texte)
    if html is not None:
        m.add_alternative(html, subtype="html")
        for cid, contenu in images:                      # images jointes au HTML (cid:)
            m.get_payload()[1].add_related(contenu, maintype="image", subtype="png", cid=f"<{cid}>")
    for nom, contenu, genre in pieces:
        principal, _, secondaire = genre.partition("/")
        m.add_attachment(contenu, maintype=principal, subtype=secondaire, filename=nom)
    return m.as_bytes()


# --- IMAP ----------------------------------------------------------------------------------------------
def jetons_imap(texte):
    """Découpe une ligne de commande IMAP : atomes, "chaînes", (listes)."""
    sortie, pile, i = [], [], 0
    courant = sortie
    while i < len(texte):
        c = texte[i]
        if c == " ":
            i += 1
        elif c == "(":
            nouvelle = []
            courant.append(nouvelle)
            pile.append(courant)
            courant = nouvelle
            i += 1
        elif c == ")":
            courant = pile.pop()
            i += 1
        elif c == '"':
            j, morceau = i + 1, ""
            while texte[j] != '"':
                if texte[j] == "\\":
                    j += 1
                morceau += texte[j]
                j += 1
            courant.append(morceau)
            i = j + 1
        else:
            m = re.match(r"[^ ()\"]+(\[[^\]]*\])?(<[0-9.]+>)?", texte[i:])
            courant.append(m.group(0))
            i += len(m.group(0))
    return sortie


class Lettre:
    def __init__(self, uid, brut, drapeaux=(), date=None):
        self.uid, self.brut, self.drapeaux = uid, brut, set(drapeaux)
        self.date = date if date is not None else time.time()


class FauxIMAP:
    """Un petit serveur IMAP4rev1 chiffré, avec ses dossiers (INBOX, Archive, Trash, Sent par défaut)."""

    def __init__(self, cert, cle, comptes, dossiers=None, capacites=("MOVE", "UIDPLUS"), validite=1000):
        self.comptes = dict(comptes)              # identifiant → mot de passe
        self.jetons = {}                          # adresse → jeton d'accès Microsoft (XOAUTH2)
        speciaux = dossiers if dossiers is not None else {"Archive": "\\Archive", "Trash": "\\Trash", "Sent": "\\Sent"}
        self.dossiers = {"INBOX": []}
        self.speciaux = {}
        for nom, drapeau in speciaux.items():
            self.dossiers[nom] = []
            self.speciaux[nom] = drapeau
        self.capacites = list(capacites)
        self.validite = validite
        self.suivant = 1
        self.journal = []                          # (identifiant, commande, arguments)
        self.verrou = threading.Lock()
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, cle)
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.fini = False
        threading.Thread(target=self._accepter, daemon=True).start()

    def deposer(self, brut, dossier="INBOX", drapeaux=(), date=None):
        with self.verrou:
            lettre = Lettre(self.suivant, brut, drapeaux, date)
            self.suivant += 1
            self.dossiers[dossier].append(lettre)
            return lettre.uid

    def lettre(self, uid, dossier="INBOX"):
        return next((x for x in self.dossiers[dossier] if x.uid == uid), None)

    def arreter(self):
        self.fini = True
        try:
            self.sock.close()
        except OSError:
            pass

    def _accepter(self):
        while not self.fini:
            try:
                brut, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(brut,), daemon=True).start()

    def _session(self, brut):
        try:
            conn = self.ctx.wrap_socket(brut, server_side=True)
        except (ssl.SSLError, OSError):
            brut.close()
            return
        f = conn.makefile("rwb", buffering=0)
        etat = {"qui": None, "dossier": None, "lecture_seule": True}

        def dire(texte):
            f.write(texte.encode() + b"\r\n") if isinstance(texte, str) else f.write(texte)

        try:
            dire("* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN AUTH=XOAUTH2] Faux IMAP pret")
            while True:
                ligne = f.readline()
                if not ligne:
                    return
                ligne = ligne.rstrip(b"\r\n").decode("utf-8", "replace")
                litteral = None
                m = re.search(r"\{(\d+)\}$", ligne)
                if m:                                  # APPEND : le message suit la ligne
                    dire("+ prêt")
                    litteral = self._lire(f, int(m.group(1)))
                    f.readline()
                    ligne = ligne[:m.start()].rstrip()
                tag, _, reste = ligne.partition(" ")
                commande, _, args = reste.partition(" ")
                commande = commande.upper()
                if commande == "UID":
                    sous, _, args = args.partition(" ")
                    commande = "UID " + sous.upper()
                self.journal.append((etat["qui"], commande, args))
                try:
                    if not self._traiter(f, dire, etat, tag, commande, args, litteral):
                        return
                except Exception as e:                # commande mal comprise : réponse BAD, comme un vrai serveur
                    dire(f"{tag} BAD {type(e).__name__}")
        except (OSError, ssl.SSLError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _lire(f, n):
        donnees = b""
        while len(donnees) < n:
            morceau = f.read(n - len(donnees))
            if not morceau:
                break
            donnees += morceau
        return donnees

    def _drapeaux(self, lettre):
        return " ".join(sorted(lettre.drapeaux))

    def _choisies(self, etat, ensemble):
        lettres = self.dossiers[etat["dossier"]]
        uids = set()
        for morceau in ensemble.split(","):
            if ":" in morceau:
                a, b = morceau.split(":")
                hi = max(x.uid for x in lettres) if lettres else 0
                a, b = int(a), (hi if b == "*" else int(b))
                uids.update(range(min(a, b), max(a, b) + 1))
            else:
                uids.add(int(morceau))
        return [(i + 1, x) for i, x in enumerate(lettres) if x.uid in uids]

    def _traiter(self, f, dire, etat, tag, commande, args, litteral):
        j = jetons_imap(args)
        if commande == "CAPABILITY":
            extra = (" " + " ".join(self.capacites)) if etat["qui"] else ""
            dire(f"* CAPABILITY IMAP4rev1 AUTH=PLAIN AUTH=XOAUTH2{extra}")
            dire(f"{tag} OK CAPABILITY fait")
        elif commande == "NOOP":
            dire(f"{tag} OK NOOP")
        elif commande == "LOGOUT":
            dire("* BYE au revoir")
            dire(f"{tag} OK LOGOUT")
            return False
        elif commande == "LOGIN":
            if self.comptes.get(j[0]) == j[1]:
                etat["qui"] = j[0]
                dire(f"{tag} OK LOGIN fait")
            else:
                dire(f"{tag} NO [AUTHENTICATIONFAILED] Identifiants refuses")
        elif commande == "AUTHENTICATE":
            dire("+ ")
            reponse = base64.b64decode(f.readline().strip()).decode("utf-8", "replace")
            if j[0].upper() == "PLAIN":
                _, qui, mdp = reponse.split("\0")
                ok = self.comptes.get(qui) == mdp
            else:
                m = re.fullmatch(r"user=([^\x01]+)\x01auth=Bearer ([^\x01]+)\x01\x01", reponse)
                qui = m.group(1) if m else ""
                ok = bool(m) and self.jetons.get(qui) == m.group(2)
            if ok:
                etat["qui"] = qui
                dire(f"{tag} OK AUTHENTICATE fait")
            else:
                dire(f"{tag} NO [AUTHENTICATIONFAILED] Refuse")
        elif not etat["qui"]:
            dire(f"{tag} NO connecte-toi d'abord")
        elif commande in ("SELECT", "EXAMINE"):
            nom = j[0]
            if nom.upper() == "INBOX":
                nom = "INBOX"
            if nom not in self.dossiers:
                dire(f"{tag} NO dossier inconnu")
                return True
            etat.update(dossier=nom, lecture_seule=commande == "EXAMINE")
            dire(f"* {len(self.dossiers[nom])} EXISTS")
            dire(f"* OK [UIDVALIDITY {self.validite}] valide")
            dire(f"* OK [UIDNEXT {self.suivant}] suivant")
            dire(f"{tag} OK [{'READ-ONLY' if etat['lecture_seule'] else 'READ-WRITE'}] {commande} fait")
        elif commande == "LIST":
            for nom in self.dossiers:
                drapeau = self.speciaux.get(nom, "")
                dire(f'* LIST (\\HasNoChildren{" " + drapeau if drapeau else ""}) "/" "{nom}"')
            dire(f"{tag} OK LIST fait")
        elif commande in ("CREATE", "SUBSCRIBE"):
            if commande == "CREATE":
                self.dossiers.setdefault(j[0], [])
            dire(f"{tag} OK {commande} fait")
        elif commande == "APPEND":
            nom = j[0]
            drapeaux = j[1] if len(j) > 1 and isinstance(j[1], list) else []
            self.deposer(litteral or b"", nom, drapeaux)
            dire(f"{tag} OK APPEND fait")
        elif commande == "UID SEARCH":
            lettres = self.dossiers[etat["dossier"]]
            if j and j[0].upper() == "SINCE":
                depuis = time.mktime(time.strptime(j[1], "%d-%b-%Y"))
                lettres = [x for x in lettres if x.date >= depuis - 86400]
            dire("* SEARCH" + "".join(f" {x.uid}" for x in lettres))
            dire(f"{tag} OK SEARCH fait")
        elif commande == "UID FETCH":
            elements = [e.upper() for e in (j[1] if isinstance(j[1], list) else [j[1]])]
            for seq, x in self._choisies(etat, j[0]):
                morceaux = [f"UID {x.uid}"]
                if "FLAGS" in elements:
                    morceaux.append(f"FLAGS ({self._drapeaux(x)})")
                if "RFC822.SIZE" in elements:
                    morceaux.append(f"RFC822.SIZE {len(x.brut)}")
                corps = None
                if "BODY.PEEK[]" in elements or "BODY[]" in elements:
                    corps = ("BODY[]", x.brut)
                    if "BODY[]" in elements and not etat["lecture_seule"]:
                        x.drapeaux.add("\\Seen")
                elif "BODY.PEEK[HEADER]" in elements:
                    tete = x.brut.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n" if b"\r\n\r\n" in x.brut else x.brut.split(b"\n\n", 1)[0] + b"\n\n"
                    corps = ("BODY[HEADER]", tete)
                if corps:
                    f.write(f"* {seq} FETCH ({' '.join(morceaux)} {corps[0]} {{{len(corps[1])}}}\r\n".encode() + corps[1] + b")\r\n")
                else:
                    dire(f"* {seq} FETCH ({' '.join(morceaux)})")
            dire(f"{tag} OK FETCH fait")
        elif commande == "UID STORE":
            if etat["lecture_seule"]:
                dire(f"{tag} NO dossier en lecture seule")
                return True
            mode, drapeaux = j[1].upper(), set(j[2] if isinstance(j[2], list) else [j[2]])
            for seq, x in self._choisies(etat, j[0]):
                if mode.startswith("+"):
                    x.drapeaux |= drapeaux
                elif mode.startswith("-"):
                    x.drapeaux -= drapeaux
                else:
                    x.drapeaux = set(drapeaux)
                dire(f"* {seq} FETCH (UID {x.uid} FLAGS ({self._drapeaux(x)}))")
            dire(f"{tag} OK STORE fait")
        elif commande in ("UID MOVE", "UID COPY"):
            if commande == "UID MOVE" and "MOVE" not in self.capacites:
                dire(f"{tag} BAD MOVE inconnu")
                return True
            cible = j[1]
            if cible not in self.dossiers:
                dire(f"{tag} NO [TRYCREATE] dossier inconnu")
                return True
            choisies = self._choisies(etat, j[0])
            for _seq, x in choisies:
                self.deposer(x.brut, cible, x.drapeaux - {"\\Deleted"}, x.date)
            if commande == "UID MOVE":
                for seq, x in sorted(choisies, reverse=True, key=lambda c: c[0]):
                    self.dossiers[etat["dossier"]].remove(x)
                    dire(f"* {seq} EXPUNGE")
            dire(f"{tag} OK {commande} fait")
        elif commande in ("EXPUNGE", "UID EXPUNGE"):
            lettres = self.dossiers[etat["dossier"]]
            visees = {x.uid for _s, x in self._choisies(etat, j[0])} if commande == "UID EXPUNGE" else None
            for i in range(len(lettres) - 1, -1, -1):
                if "\\Deleted" in lettres[i].drapeaux and (visees is None or lettres[i].uid in visees):
                    del lettres[i]
                    dire(f"* {i + 1} EXPUNGE")
            dire(f"{tag} OK EXPUNGE fait")
        elif commande == "CLOSE":
            dire(f"{tag} OK CLOSE fait")
        else:
            dire(f"{tag} BAD commande inconnue")
        return True


# --- SMTP ----------------------------------------------------------------------------------------------
class FauxSMTP:
    """Un petit serveur SMTP : TLS d'emblée (« ssl », port 465) ou STARTTLS (« starttls », port 587)."""

    def __init__(self, cert, cle, comptes, tls="ssl", refus_auth=None, refus_destinataires=()):
        self.comptes = dict(comptes)              # identifiant → mot de passe
        self.jetons = {}                          # adresse → jeton d'accès (XOAUTH2)
        self.tls, self.refus_auth, self.refus_destinataires = tls, refus_auth, set(refus_destinataires)
        self.recus = []                           # {"de", "a", "donnees", "qui"}
        self.journal = []
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, cle)
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.fini = False
        threading.Thread(target=self._accepter, daemon=True).start()

    def arreter(self):
        self.fini = True
        try:
            self.sock.close()
        except OSError:
            pass

    def _accepter(self):
        while not self.fini:
            try:
                brut, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(brut,), daemon=True).start()

    def _session(self, conn):
        try:
            if self.tls == "ssl":
                conn = self.ctx.wrap_socket(conn, server_side=True)
            f = conn.makefile("rwb", buffering=0)
            chiffre = self.tls == "ssl"
            qui, de, a = None, None, []

            def dire(texte):
                f.write(texte.encode() + b"\r\n")
            dire("220 faux ESMTP")
            while True:
                ligne = f.readline()
                if not ligne:
                    return
                ligne = ligne.rstrip(b"\r\n").decode("utf-8", "replace")
                verbe, _, reste = ligne.partition(" ")
                verbe = verbe.upper()
                self.journal.append((verbe, reste if verbe != "AUTH" else reste.split(" ")[0]))
                if verbe in ("EHLO", "HELO"):
                    lignes = ["250-faux", "250-SIZE 52428800"]
                    if chiffre:
                        lignes.append("250-AUTH PLAIN LOGIN XOAUTH2")
                    elif self.tls == "starttls":
                        lignes.append("250-STARTTLS")
                    lignes.append("250 8BITMIME")
                    for x in lignes:
                        dire(x)
                elif verbe == "STARTTLS" and not chiffre:
                    dire("220 vas-y")
                    conn = self.ctx.wrap_socket(conn, server_side=True)
                    f = conn.makefile("rwb", buffering=0)
                    chiffre = True
                elif verbe == "AUTH":
                    if not chiffre:
                        dire("530 chiffre d'abord")
                        continue
                    meca, _, initial = reste.partition(" ")
                    meca = meca.upper()
                    if meca == "LOGIN":
                        dire("334 VXNlcm5hbWU6")
                        u = base64.b64decode(f.readline().strip()).decode()
                        dire("334 UGFzc3dvcmQ6")
                        p = base64.b64decode(f.readline().strip()).decode()
                        ok = self.comptes.get(u) == p
                    else:
                        if not initial:
                            dire("334 ")
                            initial = f.readline().strip().decode()
                        texte = base64.b64decode(initial).decode("utf-8", "replace")
                        if meca == "PLAIN":
                            _, u, p = texte.split("\0")
                            ok = self.comptes.get(u) == p
                        else:
                            m = re.fullmatch(r"user=([^\x01]+)\x01auth=Bearer ([^\x01]+)\x01\x01", texte)
                            u = m.group(1) if m else ""
                            ok = bool(m) and self.jetons.get(u) == m.group(2)
                    if self.refus_auth:
                        dire(self.refus_auth)
                    elif ok:
                        qui = u
                        dire("235 2.7.0 accepte")
                    else:
                        dire("535 5.7.8 identifiants refuses")
                elif verbe == "MAIL":
                    if not qui:
                        dire("530 5.7.0 connecte-toi")
                        continue
                    de, a = re.search(r"<([^>]*)>", reste).group(1), []
                    dire("250 ok")
                elif verbe == "RCPT":
                    adresse = re.search(r"<([^>]*)>", reste).group(1)
                    if adresse in self.refus_destinataires:
                        dire("550 5.1.1 destinataire inconnu")
                    else:
                        a.append(adresse)
                        dire("250 ok")
                elif verbe == "DATA":
                    if not a:
                        dire("554 personne")
                        continue
                    dire("354 vas-y")
                    donnees = b""
                    while True:
                        x = f.readline()
                        if x in (b".\r\n", b".\n", b""):
                            break
                        donnees += x[1:] if x.startswith(b"..") else x
                    self.recus.append({"de": de, "a": a, "donnees": donnees, "qui": qui})
                    dire("250 2.0.0 recu")
                elif verbe == "RSET":
                    de, a = None, []
                    dire("250 ok")
                elif verbe == "NOOP":
                    dire("250 ok")
                elif verbe == "QUIT":
                    dire("221 au revoir")
                    return
                else:
                    dire("502 inconnu")
        except (OSError, ssl.SSLError, ValueError, AttributeError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


# --- connexion Microsoft (code d'appareil) -----------------------------------------------------------------
class FauxMicrosoft:
    """/devicecode puis /token : le premier relevé dit « en attente », le suivant donne les jetons."""

    def __init__(self, cert, cle, adresse="moi@outlook.fr", nom="Moi Essai", attente=1):
        self.adresse, self.nom, self.attente = adresse, nom, attente
        self.demandes = []
        self.jeton_acces, self.jeton_renouveau = "acces-" + str(time.time()), "renouveau-1"
        faux = self

        class Gestion(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                champs = dict(x.split("=", 1) for x in self.rfile.read(int(self.headers["Content-Length"])).decode().split("&"))
                champs = {k: urllib.parse.unquote_plus(v) for k, v in champs.items()}
                faux.demandes.append((self.path, champs))
                if self.path.endswith("/devicecode"):
                    r = {"device_code": "appareil-123", "user_code": "ABCD-EFGH", "verification_uri": "https://microsoft.com/devicelogin",
                         "expires_in": 120, "interval": 1}
                    code = 200
                elif champs.get("grant_type", "").endswith("device_code"):
                    if faux.attente > 0:
                        faux.attente -= 1
                        r, code = {"error": "authorization_pending"}, 400
                    else:
                        r, code = faux.jetons(), 200
                elif champs.get("grant_type") == "refresh_token":
                    if champs.get("refresh_token") == faux.jeton_renouveau:
                        faux.jeton_acces = "acces-" + str(time.time())
                        r, code = {"access_token": faux.jeton_acces, "expires_in": 3600}, 200
                    else:
                        r, code = {"error": "invalid_grant"}, 400
                else:
                    r, code = {"error": "unsupported_grant_type"}, 400
                corps = json.dumps(r).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, cle)
        self.serveur.socket = ctx.wrap_socket(self.serveur.socket, server_side=True)
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def jetons(self):
        charge = base64.urlsafe_b64encode(json.dumps({"email": self.adresse, "name": self.nom}).encode()).decode().rstrip("=")
        return {"access_token": self.jeton_acces, "refresh_token": self.jeton_renouveau, "expires_in": 3600,
                "id_token": f"e30.{charge}.signature"}

    def arreter(self):
        self.serveur.shutdown()


FAUX_TROUSSEAU = '''#!{python}
"""Faux secret-tool des tests : garde les secrets dans un fichier JSON (jamais le vrai trousseau)."""
import json, os, sys
from pathlib import Path
f = Path(os.environ["SMOKY_TEST_FAUX"]) / "trousseau.json"
if (Path(os.environ["SMOKY_TEST_FAUX"]) / "trousseau-ferme").exists():
    sys.exit(1)
tout = json.loads(f.read_text()) if f.exists() else {{}}
action, args = sys.argv[1], sys.argv[2:]
if action == "store":
    etiquette = args.pop(0).split("=", 1)[1]
cle = " ".join(args)
if action == "store":
    tout[cle] = {{"secret": sys.stdin.read(), "etiquette": etiquette}}
elif action == "lookup":
    if cle not in tout:
        sys.exit(1)
    sys.stdout.write(tout[cle]["secret"])
elif action == "clear":
    tout.pop(cle, None)
f.write_text(json.dumps(tout))
'''
