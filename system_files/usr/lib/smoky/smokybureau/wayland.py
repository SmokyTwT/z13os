"""Smoky OS — petit client Wayland écrit pour Smoky, en Python pur (aucune bibliothèque).

Il parle directement le protocole Wayland (messages binaires sur la prise du moteur
d'affichage) pour deux choses que GTK ne sait pas faire :
  * la liste des fenêtres ouvertes, pour le dock (protocole wlr-foreign-toplevel) :
    titre, appli, état (active, en grand, réduite), et les actions activer / réduire / fermer ;
  * éteindre et rallumer l'écran (protocole wlr-output-power-management).

Il s'intègre à la boucle GLib : lecture seulement quand le moteur d'affichage écrit.
Format des messages : identifiant d'objet (u32), puis taille<<16 | numéro (u32), puis les
arguments, chacun aligné sur 4 octets (chaînes terminées par 0, tableaux précédés de leur taille).
"""
import os
import socket
import struct

ETATS = {0: "grand", 1: "reduite", 2: "active", 3: "plein_ecran"}


def _chaine(s):
    b = s.encode() + b"\0"
    return struct.pack("=I", len(b)) + b + b"\0" * (-len(b) % 4)


class Fenetre:
    """Une fenêtre ouverte, vue par le dock."""

    def __init__(self, client, oid):
        self.client, self.id = client, oid
        self.titre, self.appli, self.etats, self.parent = "", "", set(), None
        self._nouveau = {}

    def activer(self):
        if self.client.seat:
            self.client._envoyer(self.id, 4, struct.pack("=I", self.client.seat))

    def reduire(self):
        self.client._envoyer(self.id, 2)

    def fermer(self):
        self.client._envoyer(self.id, 5)

    def __repr__(self):
        return f"Fenetre({self.appli!r}, {self.titre!r}, {sorted(self.etats)})"


class Client:
    """Connexion au moteur d'affichage. `quand_change()` est appelé après chaque mise à jour
    complète de la liste des fenêtres."""

    def __init__(self, quand_change=lambda: None, prise=None):
        if prise is None:
            nom = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
            prise = nom if nom.startswith("/") else os.path.join(os.environ["XDG_RUNTIME_DIR"], nom)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
        self.sock.connect(prise)
        self.sock.setblocking(False)
        self.quand_change = quand_change
        self.tampon = b""
        self.prochain = 2                     # 1 = wl_display
        self.objets = {1: ("display", None)}  # id -> (genre, donnée)
        self.fenetres = {}                    # id -> Fenetre
        self.ecrans = {}                      # id wl_output -> nom
        self.seat = None
        self.gestion_ecran = None
        self.registre = self._nouvel_id("registre")
        self._envoyer(1, 1, struct.pack("=I", self.registre))   # wl_display.get_registry

    # --- bas niveau ------------------------------------------------------------------
    def _nouvel_id(self, genre, donnee=None):
        oid, self.prochain = self.prochain, self.prochain + 1
        self.objets[oid] = (genre, donnee)
        return oid

    def _envoyer(self, oid, numero, args=b""):
        msg = struct.pack("=II", oid, ((8 + len(args)) << 16) | numero) + args
        try:
            self.sock.sendall(msg)
        except BlockingIOError:
            self.sock.setblocking(True)
            self.sock.sendall(msg)
            self.sock.setblocking(False)

    def _lier(self, nom, interface, version, genre):
        oid = self._nouvel_id(genre)
        self._envoyer(self.registre, 0, struct.pack("=I", nom) + _chaine(interface) + struct.pack("=II", version, oid))
        return oid

    def fileno(self):
        return self.sock.fileno()

    def lire(self, *_):
        """À appeler quand la prise est lisible. Renvoie False si la connexion est perdue."""
        try:
            donnees = self.sock.recv(65536)
        except BlockingIOError:
            return True
        except OSError:
            return False
        if not donnees:
            return False
        self.tampon += donnees
        while len(self.tampon) >= 8:
            oid, mot = struct.unpack_from("=II", self.tampon)
            taille = mot >> 16
            if taille < 8 or len(self.tampon) < taille:
                break
            args, self.tampon = self.tampon[8:taille], self.tampon[taille:]
            self._evenement(oid, mot & 0xFFFF, args)
        return True

    # --- événements ------------------------------------------------------------------
    @staticmethod
    def _lire_chaine(args, pos):
        n = struct.unpack_from("=I", args, pos)[0]
        s = args[pos + 4:pos + 4 + n].rstrip(b"\0").decode(errors="replace")
        return s, pos + 4 + n + (-n % 4)

    def _evenement(self, oid, numero, args):
        genre, donnee = self.objets.get(oid, (None, None))
        if genre == "display" and numero == 0:                        # error
            obj, code = struct.unpack_from("=II", args)
            message, _ = self._lire_chaine(args, 8)
            raise ConnectionError(f"Wayland : erreur {code} sur l'objet {obj} : {message}")
        if genre == "display" and numero == 1:                        # delete_id
            self.objets.pop(struct.unpack_from("=I", args)[0], None)
        elif genre == "registre" and numero == 0:                     # global
            nom = struct.unpack_from("=I", args)[0]
            interface, pos = self._lire_chaine(args, 4)
            version = struct.unpack_from("=I", args, pos)[0]
            if interface == "wl_seat" and self.seat is None:
                self.seat = self._lier(nom, interface, 1, "seat")
            elif interface == "wl_output":
                o = self._lier(nom, interface, min(version, 4), "ecran")
                self.ecrans[o] = ""
            elif interface == "zwlr_foreign_toplevel_manager_v1":
                self._lier(nom, interface, min(version, 3), "gestion_fenetres")
            elif interface == "zwlr_output_power_manager_v1":
                self.gestion_ecran = self._lier(nom, interface, 1, "gestion_ecran")
        elif genre == "ecran" and numero == 4:                        # wl_output.name
            self.ecrans[oid] = self._lire_chaine(args, 0)[0]
        elif genre == "gestion_fenetres" and numero == 0:             # toplevel(new_id)
            nid = struct.unpack_from("=I", args)[0]
            f = Fenetre(self, nid)
            self.objets[nid] = ("fenetre", f)
        elif genre == "fenetre":
            self._evenement_fenetre(donnee, numero, args)

    def _evenement_fenetre(self, f, numero, args):
        if numero == 0:
            f._nouveau["titre"] = self._lire_chaine(args, 0)[0]
        elif numero == 1:
            f._nouveau["appli"] = self._lire_chaine(args, 0)[0]
        elif numero == 4:                                             # state(array)
            n = struct.unpack_from("=I", args)[0]
            valeurs = struct.unpack_from(f"={n // 4}I", args, 4)
            f._nouveau["etats"] = {ETATS[v] for v in valeurs if v in ETATS}
        elif numero == 7:                                             # parent
            f._nouveau["parent"] = struct.unpack_from("=I", args)[0] or None
        elif numero == 5:                                             # done
            for cle, val in f._nouveau.items():
                setattr(f, cle, val)
            f._nouveau = {}
            self.fenetres[f.id] = f
            self.quand_change()
        elif numero == 6:                                             # closed
            self.fenetres.pop(f.id, None)
            self._envoyer(f.id, 7)                                    # destroy
            self.quand_change()

    # --- écran -------------------------------------------------------------------------
    def ecran_allume(self, allume):
        """Éteint (False) ou rallume (True) tous les écrans. Renvoie False si impossible."""
        if not self.gestion_ecran:
            return False
        for sortie in self.ecrans:
            p = self._nouvel_id("puissance")
            self._envoyer(self.gestion_ecran, 0, struct.pack("=II", p, sortie))   # get_output_power
            self._envoyer(p, 0, struct.pack("=I", 1 if allume else 0))            # set_mode
            self._envoyer(p, 1)                                                   # destroy
        return True
