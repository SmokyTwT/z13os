"""Smoky OS — socle commun des applis locales (Smoky Notes, Center, Mail, Agenda).

Chaque appli est un petit serveur qui n'écoute que sur 127.0.0.1. Tout ce qui touche à la
sécurité est écrit ici, une seule fois pour les quatre :

* en-tête Host exact (127.0.0.1:PORT ou localhost:PORT) : un site externe qui ferait pointer
  son nom vers 127.0.0.1 (« DNS rebinding ») est refusé ;
* jeton secret tiré au démarrage, écrit dans le dossier privé de la session
  ($XDG_RUNTIME_DIR, lisible par toi seul) et exigé dans l'en-tête X-Smoky-Token de chaque
  appel d'API. Un site externe ne peut pas ajouter cet en-tête sans autorisation CORS, que ce
  serveur ne donne jamais ;
* fichiers de la page servis uniquement depuis le dossier de l'appli, avec une politique de
  contenu (CSP) propre à chaque appli.

Vérifié par tests/test_serveurs.py (dans le dépôt), à chaque construction de l'image.
"""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".pdf": "application/pdf",
    ".json": "application/json", ".woff2": "font/woff2", ".webm": "audio/webm",
}


class Appli:
    """Ce qui distingue une appli : son nom, son port, le dossier de sa page et sa CSP."""

    def __init__(self, nom, port, page, csp, alias=()):
        self.nom = nom
        self.port = int(port)
        self.page = Path(page).resolve()
        self.csp = csp
        self.alias = {"", "/", *alias}                  # chemins qui affichent la page d'accueil
        self.hotes = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.jeton = secrets.token_urlsafe(24)
        # le jeton n'est jamais écrit dans la page : le lanceur le lit ici et le passe dans l'adresse (#k=…)
        self.fichier_jeton = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / f"smoky-{nom}.token"

    def ecrire_jeton(self):
        self.fichier_jeton.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.fichier_jeton, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, self.jeton.encode())
        finally:
            os.close(fd)


class Requete(BaseHTTPRequestHandler):
    """Base des quatre serveurs : réponses, contrôles d'accès, fichiers de la page."""

    appli = None                    # renseigné par servir()
    server_version = "Smoky"
    sys_version = ""

    def log_message(self, *args):   # silencieux (rien d'utile pour le journal)
        pass

    # --- réponses --------------------------------------------------------------------------
    def send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def fail(self, code, message):
        self.send(code, {"error": message})

    # --- contrôles d'accès -----------------------------------------------------------------
    def host_ok(self):
        return self.headers.get("Host", "") in self.appli.hotes

    def api_ok(self):
        return self.host_ok() and secrets.compare_digest(
            self.headers.get("X-Smoky-Token", "").encode(), self.appli.jeton.encode())

    # --- lecture de la requête ---------------------------------------------------------------
    def corps(self, maxi):
        """Corps de la requête ; ValueError s'il dépasse « maxi » octets."""
        n = int(self.headers.get("Content-Length") or 0)
        if n > maxi:
            raise ValueError("trop gros")
        return self.rfile.read(max(n, 0))

    def corps_json(self, maxi):
        """Corps JSON, tronqué à « maxi » octets (un corps tronqué est illisible : ValueError)."""
        return json.loads(self.rfile.read(max(0, min(int(self.headers.get("Content-Length") or 0), maxi))))

    # --- routage commun ----------------------------------------------------------------------
    def do_GET(self):
        if not self.host_ok():
            return self.fail(403, "hôte refusé")
        chemin, _, requete = self.path.partition("?")
        chemin = unquote(chemin)
        if chemin.startswith("/api/"):
            if not self.api_ok():
                return self.fail(403, "jeton manquant")
            return self.api_get(chemin[5:], requete)
        return self.statique(chemin)

    def api_get(self, route, requete):
        self.fail(404, "route inconnue")

    # --- fichiers de la page -----------------------------------------------------------------
    def statique(self, chemin):
        page = self.appli.page
        relatif = "index.html" if chemin in self.appli.alias else chemin.lstrip("/") or "index.html"
        cible = (page / relatif).resolve()
        if page not in cible.parents or not cible.is_file():
            return self.fail(404, "introuvable")
        data = cible.read_bytes()
        if cible.name == "index.html":
            data = data.replace(b"__SMOKY_TOKEN__", b"")
        self.send(200, data, MIME.get(cible.suffix, "application/octet-stream"),
                  {"Content-Security-Policy": self.appli.csp, "X-Frame-Options": "DENY"})


class RequeteActions(Requete):
    """Applis à deux appels (Center, Mail, Agenda) : GET /api/state et POST /api/action."""

    MAXI_ACTION = 100_000           # taille maximale d'une action (octets)

    def etat(self, requete):
        raise NotImplementedError

    def action(self, a):
        raise NotImplementedError

    def api_get(self, route, requete):
        if route == "state":
            return self.send(200, self.etat(requete))
        self.fail(404, "route inconnue")

    def do_POST(self):
        if not self.api_ok() or self.path != "/api/action":
            return self.fail(403, "refusé")
        try:
            a = self.corps_json(self.MAXI_ACTION)
        except ValueError:
            return self.fail(400, "requête illisible")
        try:
            rep = self.action(a) if isinstance(a, dict) else {"ok": False}
        except Exception as e:  # une erreur imprévue s'affiche dans l'appli au lieu de couper la connexion
            rep = {"ok": False, "message": f"erreur : {e}"[:200]}
        self.send(200, rep)


def servir(appli, requete):
    """Écoute sur 127.0.0.1 uniquement, puis écrit le jeton pour le lanceur."""
    requete.appli = appli
    serveur = ThreadingHTTPServer(("127.0.0.1", appli.port), requete)
    # écrit seulement une fois le port obtenu : une deuxième copie de l'appli n'écrase pas le jeton
    appli.ecrire_jeton()
    serveur.serve_forever()
