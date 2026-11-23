"""Smoky OS — dialogue avec greetd (connexion) : messages JSON précédés de leur longueur
(entier 32 bits, ordre de la machine). Sans GTK : testable partout (tests/test_bureau.py)."""
import json
import os
import socket
import struct

SESSION = ["/usr/bin/smoky-session"]


class Greetd:
    def __init__(self, chemin=None):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
        self.sock.connect(chemin or os.environ["GREETD_SOCK"])

    def _recevoir(self, n):
        donnees = b""
        while len(donnees) < n:
            bloc = self.sock.recv(n - len(donnees))
            if not bloc:
                raise ConnectionError("greetd a fermé la connexion")
            donnees += bloc
        return donnees

    def envoyer(self, message):
        corps = json.dumps(message).encode()
        self.sock.sendall(struct.pack("=I", len(corps)) + corps)
        n = struct.unpack("=I", self._recevoir(4))[0]
        return json.loads(self._recevoir(n))

    def connecter(self, utilisateur, mot_de_passe):
        """Renvoie None si la session démarre, sinon un message d'erreur à afficher."""
        r = self.envoyer({"type": "create_session", "username": utilisateur})
        while r.get("type") == "auth_message":
            secret = r.get("auth_message_type") in ("secret", "visible")
            r = self.envoyer({"type": "post_auth_message_response", "response": mot_de_passe if secret else None})
        if r.get("type") == "success":
            r = self.envoyer({"type": "start_session", "cmd": SESSION, "env": []})
            if r.get("type") == "success":
                return None
        self.envoyer({"type": "cancel_session"})
        if r.get("error_type") == "auth_error":
            return "Mot de passe incorrect"
        return r.get("description") or "Connexion impossible"
