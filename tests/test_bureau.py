"""Tests du bureau Smoky, sans écran ni GTK : ce qui peut casser sans se voir.

  * le client Wayland maison face à un faux moteur d'affichage (liste des fenêtres du dock) ;
  * le dialogue avec greetd face à un faux greetd (connexion, mauvais mot de passe) ;
  * la reprise unique du dock GNOME ;
  * le choix de la fréquence de l'écran (60 Hz sur batterie, la plus haute sur secteur).
L'apparence se vérifie à part (essai visuel sans écran) et le démarrage en machine virtuelle.
"""
import json
import os
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
