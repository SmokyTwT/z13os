#!/usr/bin/env python3
"""Tests de smokygpu.py (puce Intel sur Smoky OS, mode Ultimate sur Windows).

Aucun vrai firmware n'est touché : un faux « firmware » reproduit les règles du noyau
(asus-armoury), et le redémarrage est simulé. On rejoue des suites de démarrages complètes
pour vérifier en particulier qu'il ne peut jamais y avoir de boucle de redémarrages.

  python3 tests/test_gpu.py                    arbre du dépôt (system_files/)
  SMOKY_RACINE=/ python3 tests/test_gpu.py     système installé ou image construite
"""
import errno
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True      # pas de __pycache__ laissé dans system_files/

RACINE = Path(os.environ.get("SMOKY_RACINE") or Path(__file__).resolve().parent.parent / "system_files").resolve()
SCRIPT = RACINE / "usr/libexec/smokyos/smokygpu.py"
ARMOURY = "class/firmware-attributes/asus-armoury/attributes"


class Firmware:
    """Faux firmware ASUS, avec les règles du noyau : le MUX ne change qu'au redémarrage, et
    certaines écritures sont refusées selon l'état de l'autre réglage."""

    def __init__(self, mux=1, nvidia_coupee=0, present=True):
        self.present = present
        self.mux = mux                    # ce que le matériel fait en ce moment
        self.mux_demande = mux            # ce qui sera appliqué au prochain redémarrage
        self.nvidia_coupee = nvidia_coupee
        self.ecritures = []               # journal : (réglage, valeur, accepté)
        self.sourd = False                # True : accepte les écritures du MUX mais ne les applique jamais
        self.refus = None                 # errno à renvoyer pour toute écriture du MUX

    def lire(self, nom):
        if not self.present:
            return None
        return {"gpu_mux_mode": self.mux, "dgpu_disable": self.nvidia_coupee}.get(nom)

    def ecrire(self, nom, valeur):
        if not self.present:
            return False, "réglage absent"
        ok, message = True, ""
        if nom == "gpu_mux_mode":
            if self.refus:
                ok, message = False, f"{os.strerror(self.refus)} (erreur {self.refus})"
            elif valeur == 0 and self.nvidia_coupee == 1:      # « Cannot switch MUX to dGPU mode when dGPU is disabled »
                ok, message = False, f"{os.strerror(errno.ENODEV)} (erreur {errno.ENODEV})"
            else:
                self.mux_demande = valeur
        elif nom == "dgpu_disable":
            if valeur == 1 and self.mux == 0:                  # « Cannot disable dGPU when the MUX is in dGPU mode »
                ok, message = False, f"{os.strerror(errno.EBUSY)} (erreur {errno.EBUSY})"
            else:
                self.nvidia_coupee = valeur
        self.ecritures.append((nom, valeur, ok))
        return ok, message

    def redemarrer(self):
        if not self.sourd:
            self.mux = self.mux_demande
        self.mux_demande = self.mux


class Machine:
    """Un PC simulé : faux firmware + smokygpu.py chargé avec des dossiers jetables."""

    def __init__(self, **firmware):
        self.dossier = Path(tempfile.mkdtemp(prefix="smoky-test-gpu-"))
        self.fw = Firmware(**firmware)
        self.horloge = 1_800_000_000
        self.boot = 0
        self.redemarrages = 0             # redémarrages demandés par smokygpu
        self.redemarrage_possible = True
        self.a_redemarrer = False
        env = {"SMOKY_GPU_SYS": self.dossier / "sys", "SMOKY_GPU_ETAT": self.dossier / "var/gpu.json",
               "SMOKY_GPU_CONF": self.dossier / "etc/gpu.conf", "SMOKY_GPU_SUPERGFX": self.dossier / "etc/supergfxd.conf",
               "SMOKY_GPU_BOOT_ID": self.dossier / "boot_id", "SMOKY_GPU_PAUSE": "0", "SMOKY_GPU_ATTENTE": "0"}
        (self.dossier / "etc").mkdir()
        ancien = {k: os.environ.get(k) for k in env}
        os.environ.update({k: str(v) for k, v in env.items()})
        try:
            spec = importlib.util.spec_from_file_location(f"smokygpu_{id(self)}", SCRIPT)
            self.m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.m)
        finally:
            for k, v in ancien.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.m.lire, self.m.ecrire = self.fw.lire, self.fw.ecrire
        self.m.redemarrer = self._redemarrer
        self.m.time.time = lambda: self.horloge
        self.m.print = lambda *a, **k: None
        self._nouveau_boot()

    def _nouveau_boot(self):
        self.boot += 1
        (self.dossier / "boot_id").write_text(f"boot-{self.boot}\n")

    def _redemarrer(self):
        if not self.redemarrage_possible:
            return False
        self.redemarrages += 1
        self.a_redemarrer = True
        return True

    def un_demarrage(self, apres=30):
        """Un seul démarrage de Smoky OS ; → True si smokygpu a demandé un redémarrage."""
        self.horloge += apres
        self._nouveau_boot()
        self.a_redemarrer = False
        assert self.m.demarrage() == 0
        return self.a_redemarrer

    def demarrer(self, apres=30, duree_redemarrage=30):
        """Smoky OS démarre (« apres » secondes après le démarrage précédent). Tant que
        smokygpu demande un redémarrage, on le fait, comme le ferait le vrai PC ; → nombre
        de redémarrages automatiques provoqués par ce démarrage."""
        total = 0
        while self.un_demarrage(apres):
            total += 1
            assert total < 10, "boucle de redémarrages !"
            self.fw.redemarrer()
            apres = duree_redemarrage        # un redémarrage prend une trentaine de secondes
        return total

    def vers_windows(self, ultimate_dans_windows=None, apres=3600):
        """Bouton « Redémarrer sur Windows » ; dans Windows, il peut changer le mode à la main."""
        assert self.m.windows() == 0
        self.fw.redemarrer()
        self.horloge += apres
        if ultimate_dans_windows is not None:        # Armoury Crate : réglage + redémarrage de Windows
            self.fw.nvidia_coupee = 0
            self.fw.mux = self.fw.mux_demande = 0 if ultimate_dans_windows else 1

    def windows_par_le_menu(self, ultimate, apres=3600):
        """Windows choisi dans le menu de démarrage (Smoky OS ne peut rien préparer)."""
        self.fw.redemarrer()
        self.horloge += apres
        self.fw.nvidia_coupee = 0
        self.fw.mux = self.fw.mux_demande = 0 if ultimate else 1

    @property
    def etat(self):
        f = self.dossier / "var/gpu.json"
        return json.loads(f.read_text()) if f.exists() else None

    def memoire(self, **valeurs):
        (self.dossier / "var").mkdir(exist_ok=True)
        (self.dossier / "var/gpu.json").write_text(json.dumps(valeurs))

    def conf(self, texte):
        (self.dossier / "etc/gpu.conf").write_text(texte)

    def ecritures(self, nom="gpu_mux_mode"):
        return [(v, ok) for n, v, ok in self.fw.ecritures if n == nom]

    def fermer(self):
        shutil.rmtree(self.dossier, ignore_errors=True)


class Base(unittest.TestCase):
    def machine(self, **kw):
        m = Machine(**kw)
        self.addCleanup(m.fermer)
        return m


class TestDemarrage(Base):
    def test_pc_sans_aiguillage(self):
        m = self.machine(present=False)
        self.assertEqual(m.demarrer(), 0)
        self.assertEqual(m.fw.ecritures, [])
        self.assertIsNone(m.etat, "rien n'est écrit sur un PC sans MUX")
        self.assertEqual(m.m.windows(), 0)
        self.assertEqual(m.fw.ecritures, [])

    def test_ecran_deja_sur_intel(self):
        m = self.machine(mux=1)
        for _ in range(3):
            self.assertEqual(m.demarrer(), 0)
        self.assertEqual(m.fw.ecritures, [], "aucune écriture dans le firmware en temps normal")
        self.assertEqual(m.etat["mux"], 1)
        self.assertNotIn("windows_ultimate", m.etat)

    def test_demarrage_normal_sans_ecriture_sur_le_disque(self):
        m = self.machine(mux=1)
        m.demarrer()
        fichier = m.dossier / "var/gpu.json"
        avant = (fichier.stat().st_ino, fichier.stat().st_mtime_ns)
        for _ in range(3):
            m.demarrer()
        self.assertEqual((fichier.stat().st_ino, fichier.stat().st_mtime_ns), avant,
                         "rien n'a changé : le fichier n'est pas réécrit à chaque démarrage")

    def test_ultimate_un_seul_redemarrage(self):
        m = self.machine(mux=0)
        self.assertEqual(m.demarrer(), 1, "un redémarrage automatique, pas plus")
        self.assertEqual(m.fw.mux, 1, "l'écran est rendu à la puce Intel")
        self.assertEqual(m.ecritures(), [(1, True)])
        e = m.etat
        self.assertEqual((e["mux"], e["essais"]), (1, 0))
        self.assertIs(e["windows_ultimate"], True, "Smoky OS retient que Windows était en Ultimate")
        for cle in ("essai", "essai_boot", "probleme"):
            self.assertNotIn(cle, e)
        self.assertIsInstance(e["dernier_basculement"], int)
        self.assertEqual(m.demarrer(apres=86400), 0, "les démarrages suivants sont directs")
        self.assertEqual(m.redemarrages, 1)

    def test_l_essai_est_note_avant_de_toucher_au_firmware(self):
        m = self.machine(mux=0)
        vu = {}
        vraie = m.fw.ecrire

        def ecrire(nom, valeur):
            vu["etat"] = m.etat                               # ce qui est sur le disque à cet instant
            return vraie(nom, valeur)
        m.m.ecrire = ecrire
        self.assertTrue(m.un_demarrage())
        self.assertEqual(vu["etat"]["essai"], m.horloge)
        self.assertEqual(vu["etat"]["essai_boot"], f"boot-{m.boot}")
        self.assertEqual(vu["etat"]["essais"], 1)

    def test_sans_trace_sur_le_disque_on_ne_touche_a_rien(self):
        # la mémoire ne peut pas être enregistrée (ici : son dossier est un fichier)
        m = self.machine(mux=0)
        (m.dossier / "var").write_text("pas un dossier")
        for _ in range(5):
            self.assertEqual(m.demarrer(), 0, "pas de trace possible = pas d'essai, donc pas de boucle")
        self.assertEqual(m.fw.ecritures, [])
        self.assertEqual(m.redemarrages, 0)
        # la mémoire semble écrite mais ne l'est pas vraiment (relecture différente)
        m2 = self.machine(mux=0)
        with mock.patch.object(os, "replace", lambda *a, **k: None):
            for _ in range(5):
                self.assertEqual(m2.demarrer(), 0)
        self.assertEqual(m2.fw.ecritures, [])
        self.assertEqual(m2.redemarrages, 0)

    def test_jamais_de_boucle_si_le_firmware_n_applique_pas(self):
        m = self.machine(mux=0)
        m.fw.sourd = True                                   # écritures acceptées, jamais appliquées
        self.assertEqual(m.demarrer(), 1, "1er essai : un redémarrage, puis on s'arrête")
        self.assertEqual(m.etat["essais"], 1)
        self.assertIn("resté relié à la carte NVIDIA", m.etat["probleme"])
        self.assertEqual(m.demarrer(apres=7200), 1, "2e et dernier essai, plus tard")
        self.assertEqual(m.etat["essais"], 2)
        for _ in range(5):
            self.assertEqual(m.demarrer(apres=7200), 0, "ensuite, plus aucun redémarrage automatique")
        self.assertEqual(m.redemarrages, 2)
        self.assertEqual(len(m.ecritures()), 2)
        self.assertIn("Deux essais ratés", m.etat["probleme"])
        # le jour où l'écran revient sur Intel (réglé depuis Windows), tout repart de zéro
        m.fw.sourd = False
        m.fw.mux = m.fw.mux_demande = 1
        self.assertEqual(m.demarrer(apres=7200), 0)
        self.assertEqual(m.etat["essais"], 0)
        self.assertNotIn("probleme", m.etat)
        m.fw.mux = m.fw.mux_demande = 0
        self.assertEqual(m.demarrer(apres=7200), 1)
        self.assertEqual(m.fw.mux, 1)

    def test_demarrages_rapproches_sans_boucle(self):
        m = self.machine(mux=0)
        m.fw.sourd = True
        total = sum(m.demarrer(apres=5) for _ in range(20))   # 20 démarrages à 5 s d'intervalle
        self.assertEqual(total, 2)
        self.assertEqual(m.redemarrages, 2)

    def test_redemarrages_lents_sans_boucle(self):
        # firmware qui n'applique rien ET redémarrage très lent (mot de passe du disque, menu
        # de démarrage laissé ouvert…) : la limite ne dépend pas du temps écoulé
        for duree in (179, 181, 600, 86400 * 3):
            with self.subTest(duree=duree):
                m = self.machine(mux=0)
                m.fw.sourd = True
                total = sum(m.demarrer(apres=duree, duree_redemarrage=duree) for _ in range(12))
                self.assertEqual(total, 2, "deux redémarrages automatiques au plus, quel que soit le rythme")
                self.assertEqual(len(m.ecritures()), 2)

    def test_un_seul_redemarrage_par_demarrage(self):
        m = self.machine(mux=0)
        m.fw.sourd = True
        for _ in range(6):
            self.assertLessEqual(m.demarrer(apres=7200), 1)

    def test_relance_pendant_le_meme_demarrage(self):
        m = self.machine(mux=0)
        m.redemarrage_possible = False
        self.assertFalse(m.un_demarrage())
        avant = m.etat
        for _ in range(3):                                   # « systemctl restart smoky-gpu » à la main
            self.assertEqual(m.m.demarrage(), 0)
        self.assertEqual(m.ecritures(), [(1, True)], "une seule écriture dans le firmware")
        self.assertEqual(m.etat, avant)
        self.assertEqual(m.etat["essais"], 1)

    def test_ecriture_refusee(self):
        m = self.machine(mux=0)
        m.fw.refus = errno.EIO
        for _ in range(4):
            self.assertEqual(m.demarrer(apres=3600), 0, "pas de redémarrage si le firmware refuse")
        self.assertEqual(m.fw.mux, 0)
        self.assertIn("refusé", m.etat["probleme"])
        self.assertNotIn("essai", m.etat)
        self.assertEqual(m.etat["essais"], 0, "un refus n'est pas un essai : rien n'a changé")
        m.fw.refus = None
        self.assertEqual(m.demarrer(apres=3600), 1, "nouvel essai dès que le firmware accepte")
        self.assertEqual(m.fw.mux, 1)

    def test_redemarrage_impossible(self):
        m = self.machine(mux=0)
        m.redemarrage_possible = False
        self.assertEqual(m.demarrer(), 0)
        self.assertIn("redémarre Smoky OS", m.etat["probleme"])
        m.fw.redemarrer()                                   # il redémarre lui-même
        self.assertEqual(m.demarrer(), 0)
        self.assertEqual(m.fw.mux, 1)
        self.assertNotIn("probleme", m.etat)
        self.assertEqual(m.etat["essais"], 0)

    def test_desactive_par_le_reglage(self):
        m = self.machine(mux=0)
        m.conf("intel_auto = non   # je garde la NVIDIA\n")
        for _ in range(3):
            self.assertEqual(m.demarrer(), 0)
        self.assertEqual(m.fw.ecritures, [])
        self.assertIn("désactivé", m.etat["probleme"])
        self.assertIs(m.etat["windows_ultimate"], True)

    def test_reessayer(self):
        m = self.machine(mux=0)
        m.fw.sourd = True
        for _ in range(4):
            m.demarrer(apres=7200)
        self.assertEqual(m.redemarrages, 2)
        self.assertIn("reessayer", m.etat["probleme"], "le message dit comment relancer")
        self.assertEqual(m.m.reessayer(), 0)
        self.assertEqual(m.etat["essais"], 0)
        self.assertNotIn("probleme", m.etat)
        m.fw.sourd = False
        self.assertEqual(m.demarrer(apres=7200), 1)
        self.assertEqual(m.fw.mux, 1)

    def test_valeurs_inattendues(self):
        for contenu in ("2", "", "abc", "-1", "01", "1 0", "\xff\xfe"):
            with self.subTest(contenu=contenu):
                d = Path(tempfile.mkdtemp(prefix="smoky-test-gpu-"))
                self.addCleanup(shutil.rmtree, d, True)
                f = d / "sys" / ARMOURY / "gpu_mux_mode/current_value"
                f.parent.mkdir(parents=True)
                f.write_bytes(contenu.encode("latin-1"))
                r = lancer(d, "demarrage")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(f.read_bytes(), contenu.encode("latin-1"), "valeur inattendue : on ne touche à rien")
                self.assertFalse((d / "journal").exists(), "aucune commande lancée")
                self.assertFalse((d / "var").exists())

    def test_memoire_abimee(self):
        for contenu in ("", "{", "[1, 2]", '"texte"', '{"essai": "hier", "essais": "beaucoup"}',
                        '{"essai": true, "essais": null}', '{"essais": -40}', '{"essai": -5, "essais": 1.5}'):
            with self.subTest(contenu=contenu):
                m = self.machine(mux=0)
                (m.dossier / "var").mkdir()
                (m.dossier / "var/gpu.json").write_text(contenu)
                self.assertEqual(m.demarrer(), 1)
                self.assertEqual(m.fw.mux, 1)
        # même avec une mémoire abîmée, la limite tient
        m = self.machine(mux=0)
        m.fw.sourd = True
        m.memoire(essais=-40)
        self.assertEqual(sum(m.demarrer(apres=7200) for _ in range(8)), 2)
        m = self.machine(mux=0)
        m.memoire(essais=10 ** 9)
        self.assertEqual(m.demarrer(), 0, "compteur démesuré : on reste du côté prudent")

    def test_horloge_qui_recule(self):
        # Windows règle l'horloge du PC autrement : l'heure peut reculer entre deux démarrages
        m = self.machine(mux=0)
        m.fw.sourd = True
        self.assertTrue(m.un_demarrage())
        m.fw.redemarrer()
        self.assertFalse(m.un_demarrage(apres=-50), "essai « dans le futur » de 50 s : essai raté, pas de 2e redémarrage")
        self.assertIn("resté relié", m.etat["probleme"])
        self.assertEqual(m.demarrer(apres=-3600), 1)
        self.assertEqual(sum(m.demarrer(apres=-3600) for _ in range(5)), 0)
        self.assertEqual(m.redemarrages, 2)

    def test_supergfxd(self):
        m = self.machine(mux=1)
        f = m.dossier / "etc/supergfxd.conf"
        conf = {"mode": "AsusMuxDgpu", "vfio_enable": False, "always_reboot": False, "hotplug_type": "None"}
        f.write_text(json.dumps(conf))
        m.demarrer()
        self.assertEqual(json.loads(f.read_text()), {**conf, "mode": "Integrated"})
        for mode in ("Integrated", "Hybrid", "Vfio"):
            f.write_text(json.dumps({**conf, "mode": mode}))
            m.demarrer()
            self.assertEqual(json.loads(f.read_text())["mode"], mode, "un mode choisi dans Smoky OS n'est pas modifié")
        f.write_text("pas du json")
        m.demarrer()
        self.assertEqual(f.read_text(), "pas du json")
        # tant que l'écran est sur la NVIDIA, on ne touche pas aux réglages de supergfxd
        m2 = self.machine(mux=0)
        m2.conf("intel_auto=non\n")
        f2 = m2.dossier / "etc/supergfxd.conf"
        f2.write_text(json.dumps(conf))
        m2.demarrer()
        self.assertEqual(json.loads(f2.read_text())["mode"], "AsusMuxDgpu")


class TestWindows(Base):
    def test_ultimate_remis_si_windows_l_avait(self):
        m = self.machine(mux=0)
        m.demarrer()                                        # Smoky OS constate Ultimate et revient à Intel
        m.fw.ecritures.clear()
        m.vers_windows()
        self.assertEqual(m.ecritures(), [(0, True)])
        self.assertEqual(m.fw.mux, 0, "Windows démarre en mode Ultimate")
        self.assertNotIn("probleme_windows", m.etat)

    def test_une_seule_ecriture_par_demarrage(self):
        m = self.machine(mux=0)
        m.demarrer()
        m.fw.ecritures.clear()
        for _ in range(3):                                  # smoky-bootonce.sh peut appeler deux fois
            self.assertEqual(m.m.windows(), 0)
        self.assertEqual(m.ecritures(), [(0, True)])

    def test_pas_touche_si_windows_n_a_jamais_eu_ultimate(self):
        m = self.machine(mux=1)
        m.demarrer()
        m.vers_windows()
        self.assertEqual(m.fw.ecritures, [])
        self.assertEqual(m.fw.mux, 1)

    def test_reglage_oui_et_non(self):
        m = self.machine(mux=1)
        m.conf("windows_ultimate=oui\n")
        m.demarrer()
        m.vers_windows()
        self.assertEqual(m.fw.mux, 0, "« oui » : Ultimate remis même sans l'avoir constaté")
        m2 = self.machine(mux=0)
        m2.conf("windows_ultimate=non\n")
        m2.demarrer()
        m2.fw.ecritures.clear()
        m2.vers_windows()
        self.assertEqual(m2.fw.ecritures, [], "« non » : jamais")
        self.assertEqual(m2.fw.mux, 1)

    def test_nvidia_coupee_par_le_firmware(self):
        m = self.machine(mux=0)
        m.demarrer()
        m.fw.nvidia_coupee = 1                              # mode « Eco » : le firmware refuserait Ultimate
        m.fw.ecritures.clear()
        m.vers_windows()
        self.assertEqual(m.fw.ecritures, [("dgpu_disable", 0, True), ("gpu_mux_mode", 0, True)],
                         "la NVIDIA est rallumée AVANT de demander Ultimate")
        self.assertEqual(m.fw.mux, 0)

    def test_refus_du_firmware(self):
        m = self.machine(mux=0)
        m.demarrer()
        m.fw.refus = errno.EIO
        m.fw.ecritures.clear()
        m.vers_windows()
        self.assertEqual(m.fw.mux, 1, "Windows démarre en mode Standard, rien de cassé")
        self.assertIn("non remis", m.etat["probleme_windows"])
        self.assertEqual(m.ecritures(), [(0, False)] * 6, "quelques essais, pas plus")
        self.assertEqual(m.m.resume()["probleme"], m.etat["probleme_windows"], "Smoky Center le dit")
        m.fw.refus = None
        m.demarrer()
        m.vers_windows()
        self.assertEqual(m.fw.mux, 0)
        self.assertNotIn("probleme_windows", m.etat)

    def test_ecran_reste_sur_la_nvidia(self):
        m = self.machine(mux=0)
        m.conf("intel_auto=non\n")
        m.demarrer()
        m.vers_windows()
        self.assertEqual(m.fw.ecritures, [], "déjà en Ultimate : rien à écrire")
        self.assertEqual(m.fw.mux, 0)

    def test_bouton_windows_alors_que_le_retour_a_intel_attend(self):
        # le retour à Intel est demandé mais le PC n'a pas pu redémarrer ; puis « Redémarrer sur Windows »
        m = self.machine(mux=0)
        m.redemarrage_possible = False
        self.assertFalse(m.un_demarrage())
        self.assertEqual(m.fw.mux_demande, 1)
        m.vers_windows()
        self.assertEqual(m.fw.mux, 0, "Windows retrouve bien Ultimate")
        self.assertEqual(m.ecritures(), [(1, True), (0, True)])
        self.assertNotIn("essai", m.etat)
        self.assertEqual(m.etat["essais"], 0, "l'essai annulé ne compte pas")
        m.redemarrage_possible = True
        self.assertEqual(m.demarrer(), 1)
        self.assertEqual(m.fw.mux, 1)


class TestAllersRetours(Base):
    def test_cycle_complet(self):
        """Windows en Ultimate ↔ Smoky OS sur Intel, dix allers-retours par le bouton."""
        m = self.machine(mux=0)
        for tour in range(10):
            with self.subTest(tour=tour):
                self.assertEqual(m.demarrer(apres=3600), 1, "arrivée sur Smoky OS : un seul redémarrage")
                self.assertEqual(m.fw.mux, 1)
                self.assertEqual(m.demarrer(apres=3600), 0, "redémarrage de Smoky OS : direct")
                self.assertEqual(m.demarrer(apres=20), 0)
                m.vers_windows()
                self.assertEqual(m.fw.mux, 0, "Windows retrouve Ultimate sans rien faire")
                self.assertEqual(m.etat["essais"], 0)
        self.assertEqual(m.redemarrages, 10)

    def test_aller_retour_tres_rapide(self):
        m = self.machine(mux=0)
        m.demarrer()
        m.vers_windows(apres=60)                            # une minute sous Windows
        self.assertEqual(m.demarrer(apres=20), 1, "le retour à Intel marche même juste après")
        self.assertEqual(m.fw.mux, 1)

    def test_windows_par_le_menu_de_demarrage(self):
        m = self.machine(mux=0)
        m.demarrer()
        m.windows_par_le_menu(ultimate=False)               # Windows démarre en Standard, il n'y touche pas
        self.assertEqual(m.demarrer(), 0)
        m.vers_windows()
        self.assertEqual(m.fw.mux, 0, "la préférence Ultimate est gardée pour le prochain passage par le bouton")

    def test_ultimate_remis_a_la_main_juste_apres_un_basculement(self):
        m = self.machine(mux=0)
        self.assertTrue(m.un_demarrage())                   # Smoky OS bascule et redémarre…
        m.windows_par_le_menu(ultimate=True, apres=600)     # …mais il choisit Windows et remet Ultimate
        self.assertEqual(m.demarrer(), 1, "dix minutes plus tard : ce n'est pas un essai raté")
        self.assertEqual(m.fw.mux, 1)
        self.assertEqual(m.etat["essais"], 0)

    def test_deux_fois_de_suite_puis_reessayer(self):
        # deux fois de suite : bascule, puis Windows choisi au menu et Ultimate remis à la main,
        # sans jamais laisser Smoky OS revoir l'écran sur Intel. On s'arrête (prudence), et la
        # commande « reessayer » relance.
        m = self.machine(mux=0)
        for _ in range(2):
            self.assertTrue(m.un_demarrage())
            m.windows_par_le_menu(ultimate=True, apres=600)
        self.assertEqual(m.demarrer(), 0)
        self.assertIn("Deux essais ratés", m.etat["probleme"])
        self.assertEqual(m.m.reessayer(), 0)
        self.assertEqual(m.demarrer(), 1)
        self.assertEqual(m.fw.mux, 1)


def lancer(dossier, action, env=None):
    """Lance le vrai script, avec de faux fichiers et de fausses commandes (journal dans « journal »)."""
    faux = dossier / "bin"
    faux.mkdir(exist_ok=True)
    for nom in ("systemctl", "plymouth"):
        f = faux / nom
        f.write_text(f'#!/bin/sh\necho "{nom} $*" >> "{dossier}/journal"\nexit ${{FAUX_CODE:-0}}\n')
        f.chmod(0o755)
    e = {"PATH": f"{faux}:/usr/bin:/bin", "HOME": str(dossier / "home"), "XDG_CACHE_HOME": str(dossier / "cache"),
         "SMOKY_GPU_SYS": str(dossier / "sys"), "SMOKY_GPU_ETAT": str(dossier / "var/gpu.json"),
         "SMOKY_GPU_CONF": str(dossier / "gpu.conf"), "SMOKY_GPU_SUPERGFX": str(dossier / "supergfxd.conf"),
         "SMOKY_GPU_BOOT_ID": str(dossier / "boot_id"), "SMOKY_GPU_ATTENTE": "0", "SMOKY_GPU_PAUSE": "0",
         **(env or {})}
    # -I : comme dans smoky-gpu.service (Python isolé, rien n'est lu dans le dossier de l'utilisateur)
    return subprocess.run([sys.executable, "-I", str(SCRIPT), action], env=e, capture_output=True, text=True, timeout=60)


def charger(dossier):
    """Charge le vrai module (rien de simulé) sur un faux arbre de fichiers."""
    env = {"SMOKY_GPU_SYS": dossier / "sys", "SMOKY_GPU_ETAT": dossier / "var/gpu.json", "SMOKY_GPU_CONF": dossier / "gpu.conf",
           "SMOKY_GPU_SUPERGFX": dossier / "supergfxd.conf", "SMOKY_GPU_BOOT_ID": dossier / "boot_id"}
    with mock.patch.dict(os.environ, {k: str(v) for k, v in env.items()}):
        spec = importlib.util.spec_from_file_location(f"smokygpu_vrai_{id(dossier)}", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class TestVraiScript(Base):
    """Le script lancé pour de vrai : lecture et écriture des fichiers, commandes appelées."""

    def dossier(self, mux="0", nvidia="0", interface=ARMOURY):
        d = Path(tempfile.mkdtemp(prefix="smoky-test-gpu-"))
        self.addCleanup(shutil.rmtree, d, True)
        if interface.startswith("class/"):
            fichiers = {"mux": d / "sys" / interface / "gpu_mux_mode/current_value",
                        "nvidia": d / "sys" / interface / "dgpu_disable/current_value"}
        else:
            fichiers = {"mux": d / "sys" / interface / "gpu_mux_mode", "nvidia": d / "sys" / interface / "dgpu_disable"}
        for f, v in ((fichiers["mux"], mux), (fichiers["nvidia"], nvidia)):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(v + "\n")
        (d / "boot_id").write_text("boot-1\n")
        return d, fichiers

    def test_demarrage_en_ultimate(self):
        d, f = self.dossier(mux="0")
        r = lancer(d, "demarrage")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(f["mux"].read_text(), "1\n", "le script demande la puce Intel au firmware")
        journal = (d / "journal").read_text().splitlines()
        self.assertEqual([l for l in journal if l.startswith("systemctl")], ["systemctl --no-block reboot"])
        self.assertTrue(any(l.startswith("plymouth display-message --text=") for l in journal))
        etat = json.loads((d / "var/gpu.json").read_text())
        self.assertIsInstance(etat["essai"], int)
        self.assertEqual((etat["essai_boot"], etat["essais"]), ("boot-1", 1))
        self.assertEqual(stat.S_IMODE((d / "var/gpu.json").stat().st_mode), 0o644)
        self.assertEqual(sorted(p.name for p in (d / "var").iterdir()), ["gpu.json"], "pas de fichier temporaire oublié")
        self.assertIn("redémarrage", r.stdout)

    def test_demarrage_normal_aucune_commande(self):
        d, f = self.dossier(mux="1")
        r = lancer(d, "demarrage")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(f["mux"].read_text(), "1\n")
        self.assertFalse((d / "journal").exists(), "ni redémarrage ni message en temps normal")

    def test_sans_aiguillage(self):
        d = Path(tempfile.mkdtemp(prefix="smoky-test-gpu-"))
        self.addCleanup(shutil.rmtree, d, True)
        for action in ("demarrage", "windows", "note"):
            r = lancer(d, action)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((d / "journal").exists())
        self.assertFalse((d / "var").exists())
        r = lancer(d, "etat")
        self.assertEqual(json.loads(r.stdout)["mux"], None)

    def test_ancienne_interface(self):
        d, f = self.dossier(mux="0", interface="devices/platform/asus-nb-wmi")
        self.assertEqual(json.loads(lancer(d, "etat").stdout)["interface"], "asus-nb-wmi")
        lancer(d, "demarrage")
        self.assertEqual(f["mux"].read_text(), "1\n")

    def test_les_deux_interfaces_la_recente_gagne(self):
        d, f = self.dossier(mux="0")
        ancien = d / "sys/devices/platform/asus-nb-wmi/gpu_mux_mode"
        ancien.parent.mkdir(parents=True)
        ancien.write_text("0\n")
        self.assertEqual(json.loads(lancer(d, "etat").stdout)["interface"], "asus-armoury")
        lancer(d, "demarrage")
        self.assertEqual((f["mux"].read_text(), ancien.read_text()), ("1\n", "0\n"))

    def test_disposition_reelle_de_sys(self):
        # sur un vrai PC, /sys/class/firmware-attributes/asus-armoury est un lien vers /sys/devices/virtual/…
        d = Path(tempfile.mkdtemp(prefix="smoky-test-gpu-"))
        self.addCleanup(shutil.rmtree, d, True)
        reel = d / "sys/devices/virtual/firmware-attributes/asus-armoury/attributes"
        for nom, v in (("gpu_mux_mode", "0"), ("dgpu_disable", "0")):
            (reel / nom).mkdir(parents=True)
            (reel / nom / "current_value").write_text(v + "\n")
        (d / "sys/class/firmware-attributes").mkdir(parents=True)
        (d / "sys/class/firmware-attributes/asus-armoury").symlink_to("../../devices/virtual/firmware-attributes/asus-armoury")
        (d / "boot_id").write_text("boot-1\n")
        etat = json.loads(lancer(d, "etat").stdout)
        self.assertEqual((etat["mux"], etat["interface"], etat["nvidia_coupee"]), (0, "asus-armoury", 0))
        lancer(d, "demarrage")
        self.assertEqual((reel / "gpu_mux_mode/current_value").read_text(), "1\n")

    def test_refus_du_noyau(self):
        # le vrai ecrire() : le noyau répond par une erreur au moment de l'écriture
        d, f = self.dossier(mux="0")
        m = charger(d)
        vrai = open

        def refuse(fichier, mode="r", *a, **k):
            if "w" in mode and str(fichier) == str(f["mux"]):
                raise OSError(errno.ENODEV, os.strerror(errno.ENODEV))
            return vrai(fichier, mode, *a, **k)
        with mock.patch("builtins.open", refuse):
            self.assertEqual(m.ecrire("gpu_mux_mode", 1), (False, f"{os.strerror(errno.ENODEV)} (erreur {errno.ENODEV})"))
            m.print = lambda *a, **k: None
            self.assertEqual(m.demarrage(), 0)
        etat = json.loads((d / "var/gpu.json").read_text())
        self.assertIn("refusé", etat["probleme"])
        self.assertEqual(etat["essais"], 0)
        self.assertEqual(f["mux"].read_text(), "0\n")
        self.assertEqual(m.ecrire("reglage_qui_n_existe_pas", 1), (False, "réglage absent"))
        self.assertIsNone(m.lire("reglage_qui_n_existe_pas"))

    def test_reglage_d_une_autre_marque_ignore(self):
        d, f = self.dossier(mux="0", interface="class/firmware-attributes/thinklmi/attributes")
        etat = json.loads(lancer(d, "etat").stdout)
        self.assertEqual((etat["mux"], etat["interface"]), (None, None))
        lancer(d, "demarrage")
        self.assertEqual(f["mux"].read_text(), "0\n")
        self.assertFalse((d / "journal").exists())

    def test_redemarrage_refuse_par_systemd(self):
        d, f = self.dossier(mux="0")
        r = lancer(d, "demarrage", {"FAUX_CODE": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("redémarre Smoky OS", json.loads((d / "var/gpu.json").read_text())["probleme"])
        # relancé pendant le même démarrage (le vrai firmware affiche encore « NVIDIA ») : rien de plus
        f["mux"].write_text("0\n")
        avant = (d / "var/gpu.json").read_text()
        r = lancer(d, "demarrage", {"FAUX_CODE": "1"})
        self.assertEqual((d / "var/gpu.json").read_text(), avant)
        self.assertEqual((d / "journal").read_text().count("systemctl"), 1)

    def test_windows_puis_etat(self):
        d, f = self.dossier(mux="1", nvidia="1")
        (d / "gpu.conf").write_text("# essai\nwindows_ultimate = OUI\nreglage_inconnu=1\nintel_auto=peut-être\n")
        etat = json.loads(lancer(d, "etat").stdout)
        self.assertEqual((etat["mux"], etat["interface"], etat["nvidia_coupee"], etat["windows_ultimate"], etat["intel_auto"]),
                         (1, "asus-armoury", 1, True, True))
        r = lancer(d, "windows")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((f["nvidia"].read_text(), f["mux"].read_text()), ("0\n", "0\n"))
        self.assertFalse((d / "journal").exists(), "« windows » ne redémarre pas lui-même")

    def test_fichier_de_reglages_illisible(self):
        d, f = self.dossier(mux="1")
        (d / "gpu.conf").write_bytes(b"\xff\xfe\x00windows_ultimate=oui\n")
        etat = json.loads(lancer(d, "etat").stdout)
        self.assertEqual((etat["intel_auto"], etat["windows_ultimate"]), (True, False), "réglages par défaut")

    def test_note_une_seule_fois(self):
        d, f = self.dossier(mux="0")
        lancer(d, "demarrage")                              # bascule
        f["mux"].write_text("0\n")                          # le vrai firmware affiche encore « NVIDIA » jusqu'au redémarrage
        self.assertEqual(lancer(d, "note").stdout, "", "rien à dire tant que le retour à Intel n'est pas confirmé")
        f["mux"].write_text("1\n")
        (d / "boot_id").write_text("boot-2\n")
        lancer(d, "demarrage")                              # démarrage suivant, sur Intel
        premiere = lancer(d, "note").stdout
        self.assertIn("a redémarré une fois", premiere)
        self.assertIn("Redémarrer sur Windows", premiere)
        self.assertEqual(lancer(d, "note").stdout, "", "le message n'est donné qu'une fois")

    def test_note_en_cas_de_probleme(self):
        d, f = self.dossier(mux="0")
        (d / "gpu.conf").write_text("intel_auto=non\n")
        lancer(d, "demarrage")
        premiere = lancer(d, "note").stdout
        self.assertIn("carte NVIDIA", premiere)
        self.assertIn("désactivé", premiere)
        self.assertEqual(lancer(d, "note").stdout, "", "une fois par démarrage")
        (d / "boot_id").write_text("boot-2\n")
        self.assertIn("carte NVIDIA", lancer(d, "note").stdout)

    def test_reessayer_et_action_inconnue(self):
        d, _f = self.dossier()
        (d / "var").mkdir()
        (d / "var/gpu.json").write_text(json.dumps({"essais": 2, "probleme": "x", "windows_ultimate": True}))
        r = lancer(d, "reessayer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((d / "var/gpu.json").read_text()), {"essais": 0, "windows_ultimate": True})
        self.assertEqual(lancer(d, "autre").returncode, 2)
        self.assertEqual(lancer(d, "").returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
