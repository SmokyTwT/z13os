"""Smoky OS — petit client Wayland écrit pour Smoky, en Python pur (aucune bibliothèque).

Il parle directement le protocole Wayland (messages binaires sur la prise du moteur
d'affichage) pour ce que GTK ne sait pas faire :
  * la liste des fenêtres ouvertes, pour le dock (protocole wlr-foreign-toplevel) :
    titre, appli, état (active, en grand, réduite), et les actions activer / réduire / fermer ;
  * éteindre et rallumer l'écran (protocole wlr-output-power-management) ;
  * pour le clavier à l'écran (ClientClavier) : taper dans l'appli qui a le clavier
    (zwp_virtual_keyboard_v1) et savoir quand un champ de texte est actif (zwp_input_method_v2).

Il s'intègre à la boucle GLib : lecture seulement quand le moteur d'affichage écrit.
Format des messages : identifiant d'objet (u32), puis taille<<16 | numéro (u32), puis les
arguments, chacun aligné sur 4 octets (chaînes terminées par 0, tableaux précédés de leur taille).
"""
import array
import os
import socket
import struct
import time

ETATS = {0: "grand", 1: "reduite", 2: "active", 3: "plein_ecran"}
PROTOCOLES_BUREAU = {"wl_seat", "wl_output", "zwlr_foreign_toplevel_manager_v1", "zwlr_output_power_manager_v1"}


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

    def __init__(self, quand_change=lambda: None, prise=None, protocoles=PROTOCOLES_BUREAU):
        self.protocoles = protocoles          # seuls ces protocoles sont demandés au moteur d'affichage
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

    def _envoyer(self, oid, numero, args=b"", fds=()):
        msg = struct.pack("=II", oid, ((8 + len(args)) << 16) | numero) + args
        if fds:                               # descripteurs de fichier : à côté du message (SCM_RIGHTS)
            self.sock.setblocking(True)
            try:
                envoye = self.sock.sendmsg([msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds).tobytes())])
                if envoye < len(msg):
                    self.sock.sendall(msg[envoye:])
            finally:
                self.sock.setblocking(False)
            return
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
            if interface in self.protocoles:
                self._global(nom, interface, version)
        elif genre == "ecran" and numero == 4:                        # wl_output.name
            self.ecrans[oid] = self._lire_chaine(args, 0)[0]
        elif genre == "gestion_fenetres" and numero == 0:             # toplevel(new_id)
            nid = struct.unpack_from("=I", args)[0]
            f = Fenetre(self, nid)
            self.objets[nid] = ("fenetre", f)
        elif genre == "fenetre":
            self._evenement_fenetre(donnee, numero, args)
        elif genre is not None:
            self._autre(genre, oid, numero, args)

    def _global(self, nom, interface, version):
        if interface == "wl_seat" and self.seat is None:
            self.seat = self._lier(nom, interface, 1, "seat")
        elif interface == "wl_output":
            o = self._lier(nom, interface, min(version, 4), "ecran")
            self.ecrans[o] = ""
        elif interface == "zwlr_foreign_toplevel_manager_v1":
            self._lier(nom, interface, min(version, 3), "gestion_fenetres")
        elif interface == "zwlr_output_power_manager_v1":
            self.gestion_ecran = self._lier(nom, interface, 1, "gestion_ecran")

    def _autre(self, genre, oid, numero, args):
        """Événements des objets propres à une sous-classe."""

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


class ClientClavier(Client):
    """Pour le clavier à l'écran. Il crée un clavier virtuel avec sa propre disposition (keymap :
    voir commun.keymap_clavier) et tape dans l'appli qui a le clavier,
    quelle qu'elle soit (Chrome compris). Il écoute aussi les champs de texte par la méthode de
    saisie : `quand_saisie(True)` quand un champ prend la main, `quand_saisie(False)` quand il la
    rend (seulement pour les applis qui le disent, comme celles en GTK)."""

    def __init__(self, keymap, quand_saisie=lambda actif: None, prise=None):
        self.keymap, self.quand_saisie = keymap, quand_saisie
        self.gestion_clavier = self.gestion_saisie = self.clavier = self.saisie = None
        self.saisie_active = self._saisie_voulue = False
        super().__init__(prise=prise, protocoles={"wl_seat", "zwp_virtual_keyboard_manager_v1",
                                                  "zwp_input_method_manager_v2"})

    def _global(self, nom, interface, version):
        if interface == "zwp_virtual_keyboard_manager_v1":
            self.gestion_clavier = self._lier(nom, interface, 1, "gestion_clavier")
        elif interface == "zwp_input_method_manager_v2":
            self.gestion_saisie = self._lier(nom, interface, 1, "gestion_saisie")
        else:
            super()._global(nom, interface, version)
        self._preparer()

    def _preparer(self):
        if self.seat and self.gestion_clavier and not self.clavier:
            self.clavier = self._nouvel_id("clavier")
            self._envoyer(self.gestion_clavier, 0, struct.pack("=II", self.seat, self.clavier))  # create_virtual_keyboard
            donnees = self.keymap.encode() + b"\0"
            fd = os.memfd_create("smoky-clavier", os.MFD_CLOEXEC)
            try:
                vue = memoryview(donnees)
                while vue:
                    vue = vue[os.write(fd, vue):]
                os.lseek(fd, 0, os.SEEK_SET)          # lu depuis le début, même sans mmap
                self._envoyer(self.clavier, 0, struct.pack("=II", 1, len(donnees)), fds=(fd,))   # keymap(xkb_v1, fd, taille)
            finally:
                os.close(fd)
        if self.seat and self.gestion_saisie and not self.saisie:
            self.saisie = self._nouvel_id("saisie")
            self._envoyer(self.gestion_saisie, 0, struct.pack("=II", self.seat, self.saisie))     # get_input_method

    def taper(self, code, modificateurs=0):
        """Appuie puis relâche la touche `code` (code evdev de la keymap), avec Maj et/ou Alt Gr
        enfoncés si `modificateurs` le dit (masque XKB). False si pas encore prêt."""
        if not self.clavier:
            return False
        t = int(time.monotonic() * 1000) & 0xFFFFFFFF
        if modificateurs:
            self._envoyer(self.clavier, 2, struct.pack("=IIII", modificateurs, 0, 0, 0))      # modifiers
        self._envoyer(self.clavier, 1, struct.pack("=III", t, code, 1))                    # key : appuyée
        self._envoyer(self.clavier, 1, struct.pack("=III", (t + 1) & 0xFFFFFFFF, code, 0))  # relâchée
        if modificateurs:
            self._envoyer(self.clavier, 2, struct.pack("=IIII", 0, 0, 0, 0))
        return True

    def _autre(self, genre, oid, numero, args):
        if genre != "saisie":
            return
        if numero in (0, 1):                  # activate / deactivate : pris en compte au « done »
            self._saisie_voulue = numero == 0
        elif numero == 5 and self._saisie_voulue != self.saisie_active:              # done
            self.saisie_active = self._saisie_voulue
            self.quand_saisie(self.saisie_active)
        elif numero == 6:                     # unavailable : une autre méthode de saisie a la place
            self._envoyer(oid, 6)             # destroy ; on n'insiste pas (le bouton de la barre reste)
            self.saisie, self.gestion_saisie = None, None
            if self.saisie_active:
                self.saisie_active = False
                self.quand_saisie(False)
