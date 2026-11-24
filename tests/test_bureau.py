"""Tests du bureau Smoky, sans écran ni GTK : ce qui peut casser sans se voir.

  * le client Wayland maison face à un faux moteur d'affichage (liste des fenêtres du dock) ;
  * le dialogue avec greetd face à un faux greetd (connexion, mauvais mot de passe) ;
  * la reprise unique du dock GNOME ;
  * le choix de la fréquence de l'écran (60 Hz sur batterie, la plus haute sur secteur).
L'apparence se vérifie à part (essai visuel sans écran) et le démarrage en machine virtuelle.
"""
import json
import os
import ctypes
import ctypes.util
import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent / "system_files"
sys.path.insert(0, str(RACINE / "usr/lib/smoky"))

from smokybureau import commun, ecran, greetd, reseau, wayland  # noqa: E402


def chaine(s):
    b = s.encode() + b"\0"
    return struct.pack("=I", len(b)) + b + b"\0" * (-len(b) % 4)


def message(oid, numero, args=b""):
    return struct.pack("=II", oid, ((8 + len(args)) << 16) | numero) + args


def lire_messages_de(donnees):
    sortie = []
    while len(donnees) >= 8:
        oid, mot = struct.unpack_from("=II", donnees)
        taille = mot >> 16
        sortie.append((oid, mot & 0xFFFF, donnees[8:taille]))
        donnees = donnees[taille:]
    return sortie


def lire_messages(sock):
    """Tous les messages reçus du client : [(objet, numéro, arguments)]."""
    sock.settimeout(0.5)
    donnees = b""
    try:
        while True:
            bloc = sock.recv(65536)
            if not bloc:
                break
            donnees += bloc
    except (socket.timeout, BlockingIOError):
        pass
    sortie = []
    while len(donnees) >= 8:
        oid, mot = struct.unpack_from("=II", donnees)
        taille = mot >> 16
        sortie.append((oid, mot & 0xFFFF, donnees[8:taille]))
        donnees = donnees[taille:]
    return sortie


class TestWayland(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        chemin = os.path.join(self.dossier.name, "wayland-test")
        self.serveur = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.serveur.bind(chemin)
        self.serveur.listen(1)
        self.changements = 0
        self.client = wayland.Client(quand_change=self.compter, prise=chemin)
        self.cote_serveur, _ = self.serveur.accept()

    def tearDown(self):
        self.cote_serveur.close()
        self.client.sock.close()
        self.serveur.close()
        self.dossier.cleanup()

    def compter(self):
        self.changements += 1

    def envoyer(self, *messages):
        self.cote_serveur.sendall(b"".join(messages))
        for _ in range(20):
            if not self.client.lire():
                break
            try:
                if not self.client.sock.recv(1, socket.MSG_PEEK):
                    break
            except BlockingIOError:
                break

    def test_liste_des_fenetres_et_actions(self):
        reçus = lire_messages(self.cote_serveur)
        self.assertEqual(reçus[0][:2], (1, 1), "premier message : wl_display.get_registry")
        registre = struct.unpack("=I", reçus[0][2])[0]
        self.envoyer(message(registre, 0, struct.pack("=I", 1) + chaine("wl_seat") + struct.pack("=I", 8)),
                     message(registre, 0, struct.pack("=I", 2) + chaine("zwlr_foreign_toplevel_manager_v1") + struct.pack("=I", 3)),
                     message(registre, 0, struct.pack("=I", 3) + chaine("wl_compositor") + struct.pack("=I", 6)))
        liens = [m for m in lire_messages(self.cote_serveur) if m[0] == registre and m[1] == 0]
        interfaces = [m[2][8:8 + struct.unpack_from("=I", m[2], 4)[0] - 1].decode() for m in liens]
        self.assertEqual(interfaces, ["wl_seat", "zwlr_foreign_toplevel_manager_v1"], "seuls les protocoles utiles sont demandés")
        gestion = struct.unpack_from("=I", liens[1][2], len(liens[1][2]) - 4)[0]
        siege = struct.unpack_from("=I", liens[0][2], len(liens[0][2]) - 4)[0]
        f = 0xFF000001                                      # objet créé par le serveur
        self.envoyer(message(gestion, 0, struct.pack("=I", f)), message(f, 0, chaine("Moodle — Chrome")),
                     message(f, 1, chaine("google-chrome")), message(f, 4, struct.pack("=III", 8, 0, 2)),
                     message(f, 5))
        fen = self.client.fenetres[f]
        self.assertEqual((fen.titre, fen.appli, fen.etats), ("Moodle — Chrome", "google-chrome", {"grand", "active"}))
        self.assertEqual(self.changements, 1, "une mise à jour par « done », pas par événement")
        fen.activer()
        fen.fermer()
        actions = [m for m in lire_messages(self.cote_serveur) if m[0] == f]
        self.assertEqual(actions[0][1:], (4, struct.pack("=I", siege)), "activer passe le siège")
        self.assertEqual(actions[1][1], 5, "fermer")
        self.envoyer(message(f, 6))
        self.assertNotIn(f, self.client.fenetres, "fenêtre fermée retirée du dock")
        self.assertIn((f, 7, b""), lire_messages(self.cote_serveur), "objet détruit côté client")

    def test_erreur_du_moteur_d_affichage(self):
        with self.assertRaises(ConnectionError):
            self.envoyer(message(1, 0, struct.pack("=II", 3, 1) + chaine("mauvais message")))

    def test_connexion_perdue(self):
        self.cote_serveur.close()
        self.assertFalse(self.client.lire(), "la boucle GLib arrête de surveiller une prise fermée")


class FauxGreetd(threading.Thread):
    def __init__(self, sock, mot_de_passe):
        super().__init__(daemon=True)
        self.sock, self.bon, self.recus = sock, mot_de_passe, []

    def lire(self):
        n = struct.unpack("=I", self.sock.recv(4))[0]
        m = json.loads(self.sock.recv(n))
        self.recus.append(m)
        return m

    def repondre(self, m):
        corps = json.dumps(m).encode()
        self.sock.sendall(struct.pack("=I", len(corps)) + corps)

    def run(self):
        self.lire()                                                     # create_session
        self.repondre({"type": "auth_message", "auth_message_type": "secret", "auth_message": "Password:"})
        reponse = self.lire()["response"]
        if reponse == self.bon:
            self.repondre({"type": "success"})
            self.lire()                                                 # start_session
            self.repondre({"type": "success"})
        else:
            self.repondre({"type": "error", "error_type": "auth_error", "description": "pam"})
            self.lire()                                                 # cancel_session
            self.repondre({"type": "success"})


class TestGreetd(unittest.TestCase):
    def essai(self, mot_de_passe):
        a, b = socket.socketpair()
        faux = FauxGreetd(b, "bon-mot-de-passe")
        faux.start()
        g = greetd.Greetd.__new__(greetd.Greetd)
        g.sock = a
        resultat = g.connecter("smoky", mot_de_passe)
        faux.join(2)
        a.close()
        b.close()
        return resultat, faux.recus

    def test_connexion_ouvre_la_session_smoky(self):
        resultat, recus = self.essai("bon-mot-de-passe")
        self.assertIsNone(resultat)
        self.assertEqual(recus[0], {"type": "create_session", "username": "smoky"})
        self.assertEqual(recus[-1], {"type": "start_session", "cmd": ["/usr/bin/smoky-session"], "env": []})

    def test_mauvais_mot_de_passe(self):
        resultat, recus = self.essai("faux")
        self.assertEqual(resultat, "Mot de passe incorrect")
        self.assertEqual(recus[-1], {"type": "cancel_session"}, "la tentative est annulée proprement")
        self.assertNotIn("start_session", [m["type"] for m in recus])


class TestDock(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.bureau = Path(self.dossier.name) / "bureau.json"
        self.defaut = Path(self.dossier.name) / "dock.json"
        self.defaut.write_text(json.dumps({"dock": ["smoky.desktop", "google-chrome.desktop"]}))
        self.patchs = [mock.patch.object(commun, "BUREAU", self.bureau), mock.patch.object(commun, "DOCK_DEFAUT", self.defaut)]
        for p in self.patchs:
            p.start()

    def tearDown(self):
        for p in self.patchs:
            p.stop()
        self.dossier.cleanup()

    def test_reprend_le_dock_gnome_une_seule_fois(self):
        gnome = "['smoky.desktop', 'org.gnome.Nautilus.desktop', 'z13-moodle.desktop']"
        with mock.patch.object(commun, "commande", return_value=gnome + "\n"):
            self.assertEqual(commun.dock(), ["smoky.desktop", "org.gnome.Nautilus.desktop", "z13-moodle.desktop"])
        with mock.patch.object(commun, "commande", return_value="['autre.desktop']"):
            self.assertEqual(commun.dock()[1], "org.gnome.Nautilus.desktop", "ensuite, c'est le dock Smoky qui compte")
        self.assertTrue(json.loads(self.bureau.read_text())["dock_repris_de_gnome"])

    def test_sans_reglage_gnome_dock_smoky(self):
        with mock.patch.object(commun, "commande", return_value=""):
            self.assertEqual(commun.dock(), ["smoky.desktop", "google-chrome.desktop"])

    def test_reglage_gnome_illisible(self):
        with mock.patch.object(commun, "commande", return_value="@as ['oups"):
            self.assertEqual(commun.dock(), ["smoky.desktop", "google-chrome.desktop"])


class TestFrequence(unittest.TestCase):
    SORTIES = [{"name": "eDP-1", "enabled": True, "modes": [
        {"width": 1920, "height": 1200, "refresh": 120.0, "current": True},
        {"width": 1920, "height": 1200, "refresh": 60.002, "current": False},
        {"width": 1280, "height": 800, "refresh": 60.0, "current": False}]}]

    def appels(self, batterie, sorties=None):
        vus = []

        def faux(*args, **_):
            vus.append(args)
            return json.dumps(sorties or self.SORTIES) if args[:2] == ("wlr-randr", "--json") else ""
        with mock.patch.object(commun, "commande", side_effect=faux):
            ecran.choisir_frequence(batterie)
        return [a for a in vus if "--mode" in a]

    def test_batterie_60_hz_meme_definition(self):
        self.assertEqual(self.appels(True), [("wlr-randr", "--output", "eDP-1", "--mode", "1920x1200@60.002Hz")])

    def test_secteur_deja_au_maximum(self):
        self.assertEqual(self.appels(False), [], "rien à changer : aucun appel inutile")

    def test_ecran_introuvable(self):
        self.assertEqual(self.appels(True, sorties=[{"name": "HDMI-A-1", "enabled": False, "modes": []},
                                                    {"name": "DP-1", "enabled": False, "modes": []}]), [])


class TestWifi(unittest.TestCase):
    LISTE = ("*:Bbox-03D5DF02:82:WPA2\n:Study Aulnoy\\: invités:64:\n:eduroam:71:WPA2 802.1X\n"
             ":Bbox-03D5DF02:40:WPA2\n::30:WPA2\n:All Suites:55:--\n")

    def faux(self, *args, **_):
        if "list" in args:
            return self.LISTE
        return "Bbox-03D5DF02:802-11-wireless\neduroam:802-11-wireless\nSmoky VPN:vpn\n"

    def test_liste_triee_et_dedoublonnee(self):
        with mock.patch.object(commun, "commande", side_effect=self.faux):
            liste = reseau.reseaux()
        self.assertEqual([r["nom"] for r in liste], ["Bbox-03D5DF02", "eduroam", "Study Aulnoy: invités", "All Suites"],
                         "réseau actif d'abord, puis le plus fort ; un seul par nom ; réseaux sans nom ignorés")
        self.assertTrue(liste[0]["actif"] and liste[0]["connu"])
        self.assertTrue(liste[1]["entreprise"] and liste[1]["connu"])
        self.assertFalse(liste[2]["connu"])

    def test_mot_de_passe_jamais_sur_la_ligne_de_commande(self):
        appels = []

        def faux_run(args, **kw):
            appels.append((args, kw.get("input")))
            return mock.Mock(returncode=0, stderr="")
        with mock.patch.object(reseau.subprocess, "run", side_effect=faux_run):
            self.assertIsNone(reseau.connecter({"nom": "Maison", "connu": False}, "secret-123"))
        args, entree = appels[0]
        self.assertNotIn("secret-123", " ".join(args))
        self.assertEqual(entree, "secret-123\n")
        self.assertIn("--ask", args)


class TestAlertesBatterie(unittest.TestCase):
    def test_une_alerte_par_seuil_et_par_decharge(self):
        deja = set()
        vues = []
        for niveau in (40, 16, 15, 14, 12, 7, 6, 5):
            alerte, deja = commun.alerte_batterie(niveau, False, deja)
            vues.append(alerte)
        self.assertEqual(vues, [None, None, "faible", None, None, "critique", None, None])
        self.assertEqual(commun.alerte_batterie(5, True, deja), (None, set()), "en charge : on repart de zéro")
        self.assertEqual(commun.alerte_batterie(6, False, set())[0], "critique", "débranché à 6 % : alerte critique directe")


class TestClavierTactile(unittest.TestCase):
    """Clavier tactile de l'écran de connexion et du verrouillage (clavier détaché)."""

    @staticmethod
    def taper(touches):
        texte, etat, valide = "", ("abc", False), False
        for t in touches:
            texte, etat, valide = commun.touche_clavier(texte, etat, t)
        return texte, etat, valide

    def test_mot_de_passe(self):
        texte, _etat, valide = self.taper(["m", "⇧", "O", "t", "123", "4", "2", "#+=", "$", "abc", "espace",
                                            "àé", "é", "x", "⌫", "⏎"])
        self.assertEqual(texte, "mOt42$ é")
        self.assertTrue(valide)

    def test_majuscules(self):
        # les touches portent leur caractère : après ⇧, l'écran montre A, Z, E…
        self.assertEqual(self.taper(["⇧", "A", "b"])[0], "Ab", "⇧ une fois : une seule majuscule")
        texte, etat, _ = self.taper(["⇧", "⇧", "A", "B", "⇧", "c"])
        self.assertEqual(texte, "ABc", "⇧ deux fois : majuscules verrouillées, ⇧ encore : fini")
        self.assertEqual(etat, ("abc", False))

    def test_tout_se_tape(self):
        touches = set()
        for nom, rangees in commun.COUCHES_CLAVIER.items():
            toutes = " ".join(rangees).split(" ")
            for t in toutes:
                if t not in commun.TOUCHES_SPECIALES:
                    self.assertEqual(len(t), 1, f"{nom} : touche « {t} »")
                    touches.add(t)
            for indispensable in ("⌫", "⏎", "espace"):
                self.assertIn(indispensable, toutes, nom)
            self.assertTrue({"abc", "⇧"} & set(toutes), f"{nom} : pas de retour aux lettres")
        manque = [chr(c) for c in range(33, 127) if chr(c) not in touches]
        self.assertEqual(manque, [], "caractères d'un mot de passe impossibles à taper au doigt")

    def test_clavier_detache(self):
        branche = """I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
P: Phys=LNXPWRBN/button/input0
H: Handlers=kbd event0
B: PROP=0
B: EV=3
B: KEY=10000000000000 0

I: Bus=0003 Vendor=0b05 Product=1a30 Version=0110
N: Name="ASUSTeK Computer Inc. N-KEY Device Keyboard"
H: Handlers=sysrq kbd leds event5
B: PROP=0
B: EV=120013
B: KEY=1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe
B: MSC=10
B: LED=1f

I: Bus=0019 Vendor=0000 Product=0000 Version=0000
N: Name="Asus WMI hotkeys"
H: Handlers=kbd event8
B: PROP=0
B: EV=100013
B: KEY=80000000000000 0 0 0 1500b00000c00 4000000000300000 0
"""
        self.assertEqual(commun.claviers_physiques(branche), ["ASUSTeK Computer Inc. N-KEY Device Keyboard"])
        blocs = branche.split("\n\n")
        self.assertEqual(commun.claviers_physiques(blocs[0] + "\n\n" + blocs[2]), [], "boutons seuls : pas un clavier")


class TestClavierSession(unittest.TestCase):
    """Clavier à l'écran de la session : couches, disposition (keymap), protocole Wayland."""

    def test_couches(self):
        envoyables = set(commun.caracteres_session())
        manque = [chr(c) for c in range(32, 127) if chr(c) not in envoyables]
        self.assertEqual(manque, [], "tout l'ASCII s'envoie depuis le clavier de la session")
        for nom, rangees in commun.COUCHES_SESSION.items():
            toutes = " ".join(rangees).split(" ")
            for indispensable in ("⌫", "⏎", "espace", "⌄"):
                self.assertIn(indispensable, toutes, nom)
        etat, envoi = commun.touche_session(("abc", False), "⇧")
        self.assertEqual((etat, envoi), (("ABC", False), None))
        self.assertEqual(commun.touche_session(etat, "A"), (("abc", False), "A"))
        self.assertEqual(commun.touche_session(etat, "espace")[1], " ")
        self.assertEqual(commun.touche_session(etat, "⌫")[1], "⌫")
        self.assertEqual(commun.touche_session(etat, "⌄")[1], "cacher")

    @unittest.skipUnless(ctypes.util.find_library("xkbcommon"), "libxkbcommon absent")
    def test_keymap_chaque_caractere_revient(self):
        texte, codes = commun.keymap_clavier(commun.caracteres_session())
        xkb = ctypes.CDLL(ctypes.util.find_library("xkbcommon"))
        xkb.xkb_context_new.restype = ctypes.c_void_p
        xkb.xkb_keymap_new_from_string.restype = ctypes.c_void_p
        xkb.xkb_keymap_new_from_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        xkb.xkb_state_new.restype = ctypes.c_void_p
        xkb.xkb_state_new.argtypes = [ctypes.c_void_p]
        xkb.xkb_state_key_get_one_sym.restype = ctypes.c_uint32
        xkb.xkb_state_key_get_one_sym.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        xkb.xkb_state_key_get_utf8.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t]
        contexte = xkb.xkb_context_new(0)
        keymap = xkb.xkb_keymap_new_from_string(contexte, texte.encode(), 1, 0)
        self.assertTrue(keymap, "la disposition se compile (libxkbcommon)")
        etat = xkb.xkb_state_new(keymap)
        xkb.xkb_state_update_mask.argtypes = [ctypes.c_void_p] + [ctypes.c_uint32] * 6
        speciaux = {"⌫": (0xFF08, 14), "⏎": (0xFF0D, 28), "⇥": (0xFF09, 15), "←": (0xFF51, 105),
                    "→": (0xFF53, 106), " ": (0x20, 57)}
        ordinaires = set(range(2, 14)) | set(range(16, 28)) | set(range(30, 42)) | {43} | set(range(44, 54)) | {86}
        for c, (code, mods) in codes.items():
            xkb.xkb_state_update_mask(etat, mods, 0, 0, 0, 0, 0)
            if c in speciaux:
                self.assertEqual((xkb.xkb_state_key_get_one_sym(etat, code + 8), code), speciaux[c], c)
                continue
            self.assertIn(code, ordinaires, f"{c} : seulement des touches ordinaires (Chrome lit aussi le code)")
            tampon = ctypes.create_string_buffer(16)
            xkb.xkb_state_key_get_utf8(etat, code + 8, tampon, 16)
            self.assertEqual(tampon.value.decode(), c, f"code {code}, modificateurs {mods:#x}")
        self.assertEqual(codes["a"], (30, 0), "les lettres gardent leur place")
        self.assertEqual(codes["A"], (30, commun.MAJ))
        self.assertEqual(codes["1"], (2, 0))

    def test_protocole(self):
        texte, codes = commun.keymap_clavier(commun.caracteres_session())
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "wayland-test")
            serveur = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            serveur.bind(chemin)
            serveur.listen(1)
            champs = []
            client = wayland.ClientClavier(texte, quand_saisie=champs.append, prise=chemin)
            cote, _ = serveur.accept()
            cote.settimeout(1)
            try:
                registre = struct.unpack("=I", lire_messages(cote)[0][2])[0]
                annonces = [("wl_seat", 8), ("wl_output", 4), ("zwp_input_method_manager_v2", 1),
                            ("zwp_virtual_keyboard_manager_v1", 1)]
                cote.sendall(b"".join(message(registre, 0, struct.pack("=I", i) + chaine(nom) + struct.pack("=I", v))
                                      for i, (nom, v) in enumerate(annonces, 1)))
                for _ in range(5):
                    client.lire()
                donnees, fds, _, _ = socket.recv_fds(cote, 65536, 4)
                recus = lire_messages_de(donnees)
                liens = [m for m in recus if m[0] == registre]
                noms = [m[2][8:8 + struct.unpack_from("=I", m[2], 4)[0] - 1].decode() for m in liens]
                self.assertEqual(noms, ["wl_seat", "zwp_input_method_manager_v2", "zwp_virtual_keyboard_manager_v1"],
                                 "pas d'écran ni de liste des fenêtres pour le clavier")
                ident = {nom: struct.unpack_from("=I", m[2], len(m[2]) - 4)[0] for nom, m in zip(noms, liens)}
                siege, gestion_saisie, gestion_clavier = (ident["wl_seat"], ident["zwp_input_method_manager_v2"],
                                                          ident["zwp_virtual_keyboard_manager_v1"])
                cree = [m for m in recus if m[0] == gestion_clavier][0]
                clavier = struct.unpack("=II", cree[2])[1]
                self.assertEqual(struct.unpack("=I", cree[2][:4])[0], siege)
                keymap = [m for m in recus if m[0] == clavier and m[1] == 0][0]
                format_, taille = struct.unpack("=II", keymap[2])
                self.assertEqual(len(fds), 1, "la disposition part avec son descripteur de fichier")
                self.assertEqual((format_, taille), (1, len(texte.encode()) + 1))
                with os.fdopen(fds[0], "rb") as f:
                    self.assertEqual(f.read(), texte.encode() + b"\0")
                saisie = struct.unpack("=II", [m for m in recus if m[0] == gestion_saisie][0][2])[1]
                code, mods = codes["€"]
                self.assertTrue(mods, "€ demande Alt Gr")
                self.assertTrue(client.taper(code, mods))
                envoyes = [(m[1], m[2]) for m in lire_messages(cote) if m[0] == clavier]
                self.assertEqual(envoyes[0], (2, struct.pack("=IIII", mods, 0, 0, 0)), "modificateurs d'abord")
                self.assertEqual([struct.unpack("=III", a)[1:] for n, a in envoyes[1:3]], [(code, 1), (code, 0)])
                self.assertEqual(envoyes[3], (2, struct.pack("=IIII", 0, 0, 0, 0)), "puis relâchés")
                for evenements, attendu in (([0, 5], [True]), ([1, 5], [True, False]), ([0, 1, 5], [True, False])):
                    cote.sendall(b"".join(message(saisie, n) for n in evenements))
                    client.lire()
                    self.assertEqual(champs, attendu, f"événements {evenements}")
                cote.sendall(message(saisie, 6))
                client.lire()
                self.assertIn((saisie, 6, b""), lire_messages(cote), "méthode de saisie prise ailleurs : objet rendu")
            finally:
                cote.close()
                client.sock.close()
                serveur.close()


class TestGrubenv(unittest.TestCase):
    """Bouton Windows : choix écrit dans le menu de démarrage sans grub2-editenv."""
    SCRIPT = RACINE / "usr/libexec/smokyos/smoky-grubenv.py"

    def ecrire(self, chemin, ligne):
        import subprocess
        subprocess.run([sys.executable, "-I", str(self.SCRIPT), str(chemin), ligne], check=True)

    def test_format(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / "grubenv"
            self.ecrire(env, "saved_entry=ostree-1")
            self.ecrire(env, "next_entry=Windows")
            self.ecrire(env, "next_entry=Windows")
            donnees = env.read_bytes()
            self.assertEqual(len(donnees), 1024)
            self.assertTrue(donnees.startswith(b"# GRUB Environment Block\nsaved_entry=ostree-1\nnext_entry=Windows\n#"))
            self.assertFalse((Path(d) / "grubenv.new").exists())

    @unittest.skipUnless(__import__("shutil").which("grub-editenv"), "grub-editenv absent")
    def test_comme_grub(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            subprocess.run(["grub-editenv", str(a), "create"], check=True)
            subprocess.run(["grub-editenv", str(a), "set", "saved_entry=x", "next_entry=Windows"], check=True)
            subprocess.run(["grub-editenv", str(b), "create"], check=True)
            subprocess.run(["grub-editenv", str(b), "set", "saved_entry=x"], check=True)
            self.ecrire(b, "next_entry=Windows")
            self.assertEqual(a.read_bytes(), b.read_bytes(), "même fichier que grub-editenv")
            liste = subprocess.run(["grub-editenv", str(b), "list"], capture_output=True, text=True, check=True).stdout
            self.assertEqual(liste.split(), ["saved_entry=x", "next_entry=Windows"])


class TestReglagesRepris(unittest.TestCase):
    def test_veille_par_defaut(self):
        self.assertEqual(commun.arguments_veille({}), [
            "swayidle", "-w", "timeout", "300", "smoky-bureau-cmd ecran eteindre", "resume", "smoky-bureau-cmd ecran allumer",
            "timeout", "300", "smoky-bureau-cmd verrouiller", "timeout", "900", "smoky-bureau-cmd veille-si-batterie",
            "before-sleep", "smoky-bureau-cmd verrouiller"])

    def test_veille_jamais_et_secteur(self):
        args = commun.arguments_veille({"idle_delay": 0, "sleep_battery_type": "nothing",
                                        "sleep_ac_type": "suspend", "sleep_ac": 3600})
        self.assertNotIn("smoky-bureau-cmd verrouiller", args[:-1], "inactivité « jamais » : pas de verrouillage")
        self.assertIn("smoky-bureau-cmd veille-si-secteur", args)
        self.assertNotIn("smoky-bureau-cmd veille-si-batterie", args)
        self.assertEqual(args[-2:], ["before-sleep", "smoky-bureau-cmd verrouiller"], "toujours verrouillé avant la veille")

    def test_verrouillage_apres_ecran_eteint(self):
        args = commun.arguments_veille({"idle_delay": 600, "lock_delay": 60})
        self.assertEqual(args[args.index("smoky-bureau-cmd verrouiller") - 1], "660")

    def test_eclairage_du_soir(self):
        self.assertEqual(commun.arguments_nuit({"temperature": 2700, "automatique": True}, {"lat": 50.36, "lon": 3.52}),
                         ["wlsunset", "-T", "6500", "-t", "2700", "-l", "50.36", "-L", "3.52"])
        self.assertEqual(commun.arguments_nuit({"automatique": False, "debut": 21.5, "fin": 6.25})[-4:],
                         ["-s", "21:30", "-S", "06:15"])
        self.assertEqual(commun.arguments_nuit({"temperature": 99999})[4], "6400", "température bornée")


class TestBatterie(unittest.TestCase):
    def test_temps_restant_lisse(self):
        with tempfile.TemporaryDirectory() as d:
            bat = Path(d) / "class/power_supply/BAT0"
            bat.mkdir(parents=True)
            for nom, val in {"type": "Battery", "capacity": "76", "status": "Discharging", "energy_now": "30000000",
                             "power_now": "9000000", "charge_control_end_threshold": "80"}.items():
                (bat / nom).write_text(val)
            with mock.patch.object(commun, "SYS", Path(d)):
                b = commun.Batterie()
                e = b.etat()
                self.assertEqual((e["niveau"], e["minutes"], e["watts"], e["limite"]), (76, 200, 9.0, 80))
                (bat / "power_now").write_text("19000000")
                self.assertEqual(b.etat()["watts"], 11.0, "un pic de consommation ne fait pas tout sauter")
                (bat / "status").write_text("Charging")
                self.assertIsNone(b.etat()["minutes"])
                self.assertEqual(commun.duree(200), "3 h 20")


if __name__ == "__main__":
    unittest.main()
