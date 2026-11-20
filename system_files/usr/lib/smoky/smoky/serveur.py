"""Le serveur de Smoky : n'écoute que sur 127.0.0.1 et ne répond qu'à sa propre page.

Sécurité, appliquée à CHAQUE requête avant tout le reste :
  - en-tête Host : seulement « localhost:PORT » ou « 127.0.0.1:PORT » (une page web d'ailleurs
    ne peut pas se faire passer pour l'appli en jouant sur les noms de domaine) ;
  - /api/… : code d'accès tiré au lancement, connu de la seule fenêtre de l'appli ; une requête
    envoyée par une autre page (en-têtes Origin, Sec-Fetch-Site) est refusée ;
  - fichiers de la page : uniquement ceux du dossier de l'appli, sans en sortir ;
  - la page elle-même ne peut charger ni script, ni style, ni image venus d'ailleurs (CSP).

Événements vers la page : /api/flux (Server-Sent Events).

Arrêt tout seul (arret_auto) : quand il n'y a plus ni fenêtre reliée à /api/flux, ni navigateur
de l'appli en marche (« present »), depuis un moment. Les deux signes comptent : Chrome peut
endormir une page en arrière-plan et couper sa connexion alors que la fenêtre existe toujours.
"""
import collections
import hashlib
import hmac
import json
import os
import re
import secrets
import select
import signal
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon", ".woff2": "font/woff2",
    ".ttf": "font/ttf", ".txt": "text/plain; charset=utf-8",
    # ressources de pdf.js (affichage des PDF dans Notes)
    ".wasm": "application/wasm", ".bcmap": "application/octet-stream", ".pfb": "application/octet-stream",
    ".icc": "application/octet-stream",
}
# 'wasm-unsafe-eval' : pdf.js décode certaines images des PDF en WebAssembly (jamais de eval() pour autant)
CSP = ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; "
       "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
CORPS_MAXI = 6_000_000      # un emploi du temps .ics importé fait 5 Mo au plus


class Brut:
    """Réponse qui n'est pas du JSON : un fichier (PDF, image, son) envoyé tel quel."""

    def __init__(self, contenu, type_mime):
        self.contenu, self.type_mime = contenu, type_mime


class Erreur(Exception):
    """Erreur à dire telle quelle à la page (message en français, pour l'utilisateur)."""

    def __init__(self, statut, message):
        super().__init__(message)
        self.statut, self.message = statut, message


class Requete:
    def __init__(self, methode, chemin, params, entetes, corps, morceaux):
        self.methode, self.chemin, self.params, self.entetes, self.corps = methode, chemin, params, entetes, corps
        self.morceaux = morceaux                      # parties nommées du chemin : /api/taches/<id>

    def json(self):
        """Corps JSON, qui doit être un objet."""
        try:
            donnees = json.loads(self.corps.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise Erreur(400, "Requête illisible.") from None
        if not isinstance(donnees, dict):
            raise Erreur(400, "Requête illisible.")
        return donnees


class Fenetre:
    """Une fenêtre reliée à /api/flux : ses événements en attente, et un tube pour réveiller le
    fil qui lui parle (il attend à la fois ce tube et la connexion, sans jamais tourner à vide)."""

    def __init__(self):
        self.attente = collections.deque()
        self.lecture, self.ecriture = os.pipe()
        os.set_blocking(self.ecriture, False)

    def pousser(self, evenement):
        if len(self.attente) >= 200:                  # fenêtre qui ne lit plus
            return False
        self.attente.append(evenement)
        try:
            os.write(self.ecriture, b"!")
        except BlockingIOError:                       # tube plein : elle est déjà prévenue
            pass
        except OSError:
            return False
        return True

    def fermer(self):
        for tube in (self.lecture, self.ecriture):
            try:
                os.close(tube)
            except OSError:
                pass


class Flux:
    """Événements poussés vers les fenêtres ouvertes, et compte de ces fenêtres."""

    def __init__(self):
        self.verrou = threading.Lock()
        self.clients = set()
        self.dernier_depart = time.monotonic()        # dernier instant où une fenêtre était encore là

    def entrer(self):
        fenetre = Fenetre()
        with self.verrou:
            self.clients.add(fenetre)
        return fenetre

    def sortir(self, fenetre):
        with self.verrou:                             # sous verrou : personne n'écrit dans un tube fermé
            self.clients.discard(fenetre)
            self.dernier_depart = time.monotonic()
            fenetre.fermer()

    def presents(self):
        with self.verrou:
            return len(self.clients)

    def publier(self, nom, donnees=None):
        with self.verrou:
            for fenetre in self.clients:
                fenetre.pousser((nom, donnees))


class Appli:
    def __init__(self, dossier_page, port, jeton=None, arret_auto=None, present=None):
        self.dossier = Path(dossier_page).resolve()
        self.port = int(port)
        self.jeton = jeton or secrets.token_urlsafe(32)
        self.arret_auto = arret_auto                  # secondes sans fenêtre avant de s'arrêter (None : jamais)
        self.present = present                        # fonction → True tant que le navigateur de l'appli tourne
        # Adresse de la page. Chrome nomme la fenêtre d'après l'hôte et ce chemin
        # (« chrome-localhost__smoky-Default ») : c'est le StartupWMClass de smoky.desktop.
        self.entree = "/smoky"
        self.flux = Flux()
        self.routes = []
        self.serveur = None
        self._statiques = {}                          # chemin → (signature du fichier, empreinte, contenu)

    # --- Routes --------------------------------------------------------------------------------
    def route(self, methode, motif, corps_maxi=None):
        """@appli.route("POST", "/api/taches/<id>") ; la fonction reçoit une Requete et renvoie
        un objet (envoyé en JSON), (statut, objet) ou un Brut (fichier). corps_maxi : taille
        permise pour l'envoi (CORPS_MAXI par défaut ; plus pour un PDF ou un enregistrement)."""
        regex = re.compile("^" + re.sub(r"<([a-z_]+)>", r"(?P<\1>[^/]+)", motif) + "$")

        def poser(fonction):
            self.routes.append((methode, regex, fonction, corps_maxi or CORPS_MAXI))
            return fonction
        return poser

    def _trouver(self, methode, chemin):
        """→ (fonction, parties nommées du chemin, taille d'envoi permise)."""
        autres = False
        for m, regex, fonction, maxi in self.routes:
            trouve = regex.match(chemin)
            if trouve:
                if m == methode:
                    return fonction, trouve.groupdict(), maxi
                autres = True
        raise Erreur(405 if autres else 404, "Cette action n'existe pas.")

    # --- Fichiers de la page ---------------------------------------------------------------------
    def fichier(self, chemin):
        """→ (contenu, type, empreinte) ou None. Jamais hors du dossier de la page."""
        relatif = "index.html" if chemin in ("", "/", self.entree) else chemin.lstrip("/")
        if "\x00" in relatif or any(p in ("..", "") or p.startswith(".") for p in relatif.split("/")):
            return None
        cible = self.dossier / relatif
        try:
            reel = cible.resolve(strict=True)
            if not reel.is_relative_to(self.dossier) or not reel.is_file():
                return None
            st = reel.stat()
        except OSError:
            return None
        type_mime = TYPES.get(reel.suffix.lower())
        if type_mime is None:
            return None
        signature = (st.st_ino, st.st_size, st.st_mtime_ns)
        connu = self._statiques.get(relatif)
        if connu and connu[0] == signature:
            return connu[2], type_mime, connu[1]
        try:
            contenu = reel.read_bytes()
        except OSError:
            return None
        empreinte = '"' + hashlib.sha256(contenu).hexdigest()[:20] + '"'
        self._statiques[relatif] = (signature, empreinte, contenu)
        return contenu, type_mime, empreinte

    # --- Marche ----------------------------------------------------------------------------------
    def hotes(self):
        return {f"localhost:{self.port}", f"127.0.0.1:{self.port}"}

    def ecrire_acces(self):
        """Le lanceur lit ici le port et le code d'accès (fichier lisible par toi seul)."""
        dossier = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "smoky"
        try:
            dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
            cible = dossier / "serveur.json"
            tmp = dossier / "serveur.json.tmp"
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                json.dump({"port": self.port, "jeton": self.jeton, "pid": os.getpid()}, f)
            os.replace(tmp, cible)
            return cible
        except OSError as e:
            print(f"smoky : code d'accès non écrit ({e})", file=sys.stderr)
            return None

    def servir(self, pret=None):
        self.serveur = _Serveur(("127.0.0.1", self.port), _gestionnaire(self))
        acces = self.ecrire_acces()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=self.arreter, daemon=True).start())
        if self.arret_auto:
            threading.Thread(target=self._veiller, daemon=True).start()
        if pret:
            pret()
        try:
            self.serveur.serve_forever(poll_interval=1.0)
        finally:
            self.serveur.server_close()
            if acces:
                try:
                    if json.loads(acces.read_text()).get("pid") == os.getpid():
                        acces.unlink()
                except (OSError, ValueError):
                    pass

    def arreter(self):
        if self.serveur:
            self.flux.publier("arret")
            self.serveur.shutdown()

    def _veiller(self):
        """Plus aucune fenêtre depuis « arret_auto » secondes : le serveur s'arrête (batterie)."""
        vu = time.monotonic()                         # dernier instant où quelque chose prouvait une fenêtre
        while True:
            time.sleep(min(5.0, self.arret_auto / 4))
            if self.flux.presents():
                vu = time.monotonic()
                continue
            if time.monotonic() - max(vu, self.flux.dernier_depart) <= self.arret_auto:
                continue
            try:                                      # le délai est passé : dernier contrôle, plus coûteux
                la = bool(self.present and self.present())
            except Exception:                         # dans le doute, on reste
                la = True
            if la:
                vu = time.monotonic()
                continue
            self.arreter()
            return


class _Serveur(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        # une fenêtre qui se ferme en pleine réponse n'est pas une erreur à noter
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, TimeoutError)):
            super().handle_error(request, client_address)


def _gestionnaire(appli):
    class Gestionnaire(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Smoky"
        sys_version = ""
        timeout = 120                                 # une connexion muette ne reste pas ouverte indéfiniment

        def log_message(self, *args):                 # pas de journal des requêtes
            pass

        # --- réponses ---
        def _envoyer(self, statut, corps=b"", type_mime="text/plain; charset=utf-8", entetes=()):
            self.send_response(statut)
            self.send_header("Content-Type", type_mime)
            self.send_header("Content-Length", str(len(corps)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            for nom, valeur in entetes:
                self.send_header(nom, valeur)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corps)

        def _json(self, statut, objet):
            self._envoyer(statut, json.dumps(objet, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8", [("Cache-Control", "no-store")])

        def _refuser(self, statut, message):
            self.close_connection = True
            if self.path.startswith("/api/"):
                self._json(statut, {"erreur": message})
            else:
                self._envoyer(statut, message.encode("utf-8"))

        # --- contrôles ---
        def _autorisee(self):
            """Code d'accès + requête venue de la page de l'appli elle-même."""
            origine = self.headers.get("Origin")
            if origine is not None and origine not in {f"http://{h}" for h in appli.hotes()}:
                return False
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                return False
            recu = self.headers.get("X-Smoky-Jeton", "")
            if not recu and self.command == "GET" and self._chemin == "/api/flux":
                recu = (self._params.get("k") or [""])[0]      # EventSource ne sait pas envoyer d'en-tête
            return hmac.compare_digest(recu.encode("utf-8", "replace"), appli.jeton.encode())

        def _traiter(self):
            if self.headers.get("Host", "") not in appli.hotes():
                return self._refuser(403, "Accès refusé.")
            url = urlsplit(self.path)
            try:
                self._chemin = unquote(url.path, errors="strict")
            except UnicodeDecodeError:
                return self._refuser(400, "Adresse illisible.")
            self._params = parse_qs(url.query)
            if not self._chemin.startswith("/api/"):
                return self._statique()
            if not self._autorisee():
                return self._refuser(403, "Accès refusé : rouvre Smoky depuis son icône.")
            if self._chemin == "/api/flux" and self.command == "GET":
                return self._flux()
            try:
                fonction, morceaux, maxi = appli._trouver("GET" if self.command == "HEAD" else self.command, self._chemin)
            except Erreur as e:
                return self._refuser(e.statut, e.message)
            corps = b""
            if self.command in ("POST", "PUT", "DELETE"):
                try:
                    taille = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._refuser(400, "Requête illisible.")
                if taille < 0 or taille > maxi:
                    return self._refuser(413, "Envoi trop volumineux.")
                corps = self.rfile.read(taille)
                if len(corps) != taille:                  # connexion coupée en plein envoi
                    return self._refuser(400, "Envoi incomplet.")
            try:
                resultat = fonction(Requete(self.command, self._chemin, self._params, self.headers, corps, morceaux))
                if isinstance(resultat, Brut):
                    return self._envoyer(200, resultat.contenu, resultat.type_mime, [("Cache-Control", "no-store")])
                statut = 200
                if isinstance(resultat, tuple):
                    statut, resultat = resultat
                self._json(statut, resultat if resultat is not None else {})
            except Erreur as e:
                self._json(e.statut, {"erreur": e.message})
            except (BrokenPipeError, ConnectionResetError):
                raise
            except Exception:                         # une erreur de programmation ne doit pas tuer le serveur
                traceback.print_exc()
                self._json(500, {"erreur": "Erreur interne de Smoky."})

        def _statique(self):
            if self.command not in ("GET", "HEAD"):
                return self._refuser(405, "Méthode refusée.")
            trouve = appli.fichier(self._chemin)
            if trouve is None:
                return self._refuser(404, "Introuvable.")
            contenu, type_mime, empreinte = trouve
            entetes = [("ETag", empreinte), ("Cache-Control", "no-cache")]
            if type_mime.startswith("text/html"):
                entetes += [("Content-Security-Policy", CSP), ("Cross-Origin-Opener-Policy", "same-origin"),
                            ("X-Frame-Options", "DENY")]
            if self.headers.get("If-None-Match") == empreinte:
                return self._envoyer(304, b"", type_mime, entetes)
            self._envoyer(200, contenu, type_mime, entetes)

        def _flux(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            fenetre = appli.flux.entrer()
            try:
                self.wfile.write(b"event: bonjour\ndata: {}\n\n")
                self.wfile.flush()
                while True:
                    # On attend, sans rien consommer : un événement à envoyer (le tube), ou la
                    # connexion qui bouge. La page n'envoie jamais rien sur ce canal : si la
                    # connexion devient « lisible », c'est que la fenêtre est partie.
                    prets, _, _ = select.select([self.connection, fenetre.lecture], [], [], 30)
                    if self.connection in prets:
                        return
                    if not prets:                     # rien depuis 30 s : un signe de vie
                        self.wfile.write(b": toujours la\n\n")
                        self.wfile.flush()
                        continue
                    os.read(fenetre.lecture, 4096)
                    while fenetre.attente:
                        nom, donnees = fenetre.attente.popleft()
                        texte = json.dumps(donnees if donnees is not None else {}, ensure_ascii=False)
                        self.wfile.write(f"event: {nom}\ndata: {texte}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        if nom == "arret":
                            return
            except (OSError, ValueError):             # connexion coupée pendant l'envoi
                pass
            finally:
                appli.flux.sortir(fenetre)

        def do_GET(self):
            self._traiter()

        do_HEAD = do_POST = do_PUT = do_DELETE = do_GET

        def do_OPTIONS(self):                         # aucune autre page n'a le droit d'appeler l'appli
            self._refuser(403, "Accès refusé.")

    return Gestionnaire
