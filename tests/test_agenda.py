#!/usr/bin/env python3
"""L'agenda de l'appli Smoky : lecture des emplois du temps (.ics), planification de la semaine,
adresses /api/agenda, rappels (minuteurs systemd) et relais avec l'ancien Smoky Agenda.

Le serveur tourne dans un dossier personnel jetable, à une heure figée (SMOKY_MAINTENANT : mardi
17 novembre 2026, 9 h), avec les fausses commandes de test_smoky.py : aucun minuteur, aucune
notification et aucun appel à Claude n'atteint la vraie machine.

  python3 tests/test_agenda.py
  SMOKY_RACINE=/ python3 tests/test_agenda.py      image construite
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["TZ"] = "Europe/Paris"
time.tzset()
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_smoky import LANCER, PAQUET, RACINE, Dossier, Ecoute, Serveur, attendre  # noqa: E402

os.environ.setdefault("SMOKY_MATIERES", str(RACINE / "usr/share/smokyos/matieres.json"))
sys.path.insert(0, str(PAQUET.parent))
from smoky import agenda as A  # noqa: E402
from smoky import planning as P  # noqa: E402
sys.path.pop(0)

LUNDI = date(2026, 11, 16)
MAINTENANT = "2026-11-17T09:00"            # mardi, 9 h


# --- Emplois du temps d'essai -------------------------------------------------------------------
def ics(*evenements, nom="INSA 2A", prodid="-//ADE//FR", fin_de_ligne="\r\n"):
    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{prodid}", f"X-WR-CALNAME:{nom}"]
    for e in evenements:
        lignes += ["BEGIN:VEVENT", *e, "END:VEVENT"]
    lignes.append("END:VCALENDAR")
    return fin_de_ligne.join(lignes) + fin_de_ligne


def ev(jour, debut, fin, titre, lieu=""):
    """Un événement à l'heure de Paris, comme les exporte ADE."""
    return [f"DTSTART;TZID=Europe/Paris:{jour:%Y%m%d}T{debut.replace(':', '')}00",
            f"DTEND;TZID=Europe/Paris:{jour:%Y%m%d}T{fin.replace(':', '')}00", f"SUMMARY:{titre}", f"LOCATION:{lieu}"]


def semaine_type(debut=LUNDI):
    """Analyse de 8 h à 10 h et BDR de 14 h à 16 h, du lundi au vendredi : 10 cours."""
    evs = []
    for i in range(5):
        j = debut + timedelta(days=i)
        evs += [ev(j, "08:00", "10:00", "Analyse CM", f"Amphi {i}"), ev(j, "14:00", "16:00", "BDR TD", f"B20{i}")]
    return ics(*evs)


def examens_ics():
    return ics(ev(date(2026, 11, 19), "09:00", "11:00", "Examen BDR", "Amphi A"),
               ev(date(2026, 11, 25), "13:30", "15:30", "Partiel d'optique ondulatoire", "Amphi B"), nom="Examens S3")


class SiteEdt:
    """Petit site local qui sert l'emploi du temps (comme le lien iCal de l'ENT)."""

    def __init__(self):
        self.reponse = (200, "text/calendar", semaine_type())
        self.demandes = 0
        site = self

        class Gestion(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                site.demandes += 1
                code, genre, corps = site.reponse
                corps = corps.encode()
                self.send_response(code)
                self.send_header("Content-Type", genre)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *a):
                pass

        self.serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.lien = f"http://127.0.0.1:{self.serveur.server_address[1]}/edt.ics"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()


# --- Lecture des fichiers .ics --------------------------------------------------------------------
class TestLectureIcs(unittest.TestCase):
    def test_lignes_repliees_et_texte_echappe(self):
        texte = ics(["DTSTART;TZID=Europe/Paris:20261116T080000", "DTEND;TZID=Europe/Paris:20261116T100000",
                     "SUMMARY:Analyse num", " érique\\, CM", "LOCATION:Amphi\\; Bâtiment A",
                     "DESCRIPTION:Groupe 2\\nSalle changée"])
        [e] = A.lire_ics(texte)
        self.assertEqual((e["titre"], e["lieu"], e["notes"]), ("Analyse numérique, CM", "Amphi; Bâtiment A", "Groupe 2\nSalle changée"))
        self.assertEqual((e["debut"], e["fin"], e["journee"]), (datetime(2026, 11, 16, 8), datetime(2026, 11, 16, 10), False))

    def test_fuseaux_et_journees(self):
        evs = A.lire_ics(ics(
            ["DTSTART:20261116T130000Z", "DTEND:20261116T150000Z", "SUMMARY:en UTC"],
            ["DTSTART;VALUE=DATE:20261118", "SUMMARY:journée entière sans fin"],
            ["DTSTART;TZID=Europe/Paris:20261119T100000", "SUMMARY:sans fin"],
            ["DTSTART;TZID=America/New_York:20261120T080000", "DTEND;TZID=America/New_York:20261120T090000", "SUMMARY:ailleurs"],
            ["DTSTART:20261121T100000", "DTEND:20261121T090000", "SUMMARY:fin avant le début"],
            fin_de_ligne="\n"))
        par_titre = {e["titre"]: e for e in evs}
        self.assertEqual(par_titre["en UTC"]["debut"], datetime(2026, 11, 16, 14), "13 h UTC = 14 h à Paris en novembre")
        j = par_titre["journée entière sans fin"]
        self.assertEqual((j["journee"], j["debut"], j["fin"]), (True, datetime(2026, 11, 18), datetime(2026, 11, 19)))
        self.assertEqual(par_titre["sans fin"]["fin"], datetime(2026, 11, 19, 11), "sans fin : une heure")
        self.assertEqual(par_titre["ailleurs"]["debut"], datetime(2026, 11, 20, 14), "8 h à New York = 14 h à Paris")
        self.assertEqual(par_titre["fin avant le début"]["fin"], datetime(2026, 11, 21, 11))

    def test_date_illisible_ignoree(self):
        evs = A.lire_ics(ics(["DTSTART:2026-11-16 08:00", "SUMMARY:cassé"], ev(LUNDI, "10:00", "12:00", "bon"),
                             ["SUMMARY:sans début"]))
        self.assertEqual([e["titre"] for e in evs], ["bon"])

    def test_calendrier_d_examens(self):
        self.assertTrue(A.calendrier_d_examens(examens_ics()))
        self.assertTrue(A.calendrier_d_examens(ics(["CATEGORIES:EXAMEN", *ev(LUNDI, "08:00", "10:00", "x")])))
        self.assertFalse(A.calendrier_d_examens(semaine_type()))

    def test_matiere_d_un_titre(self):
        for titre, matiere in (("Examen BDR", "BDR"), ("Partiel d'optique ondulatoire", "Optique"),
                               ("DS Électromagnétisme", "Magnéto"), ("TP Méthodes numériques", "MNA"),
                               ("Réunion de projet", None), ("Rangement", None)):
            with self.subTest(titre=titre):
                self.assertEqual(A.matiere_de(titre), matiere)


# --- Planification sur le PC ------------------------------------------------------------------------
def fixes_type():
    sortie = []
    for e in A.lire_ics(semaine_type()):
        sortie.append({"genre": "cours", "titre": e["titre"], "debut": P.iso(e["debut"]), "fin": P.iso(e["fin"]), "journee": False})
    return sortie


EXAMEN_BDR = {"titre": "Examen BDR", "debut": "2026-11-19T09:00", "fin": "2026-11-19T11:00", "journee": False, "matiere": "BDR"}


def reglages(**plus):
    return {**A.REGLAGES, "matieres": ["Analyse", "BDR", "Anglais"], **plus}


def chevauche(a, b, marge=0):
    return P.lire_iso(a["debut"]) < P.lire_iso(b["fin"]) + timedelta(minutes=marge) and \
        P.lire_iso(b["debut"]) - timedelta(minutes=marge) < P.lire_iso(a["fin"])


class TestPlanification(unittest.TestCase):
    def planifier(self, maintenant=datetime(2026, 11, 16, 7), fixes=None, examens=(EXAMEN_BDR,), salle_avant=(), taches=(), **r):
        fixes = fixes_type() + [{**e, "genre": "examen"} for e in examens] if fixes is None else fixes
        return P.planifier(LUNDI, reglages(**r), fixes, list(examens), list(salle_avant), list(taches), A.matiere_de, maintenant), fixes

    def test_une_semaine_bien_rangee(self):
        tache = {"id": 7, "titre": "Rendre le TP", "minutes": 60, "echeance": "2026-11-18"}
        blocs, fixes = self.planifier(taches=[tache])
        r = reglages()
        for b in blocs:
            with self.subTest(bloc=b["titre"], debut=b["debut"]):
                s, f = P.lire_iso(b["debut"]), P.lire_iso(b["fin"])
                self.assertTrue(LUNDI <= s.date() < LUNDI + timedelta(days=7) and s < f and s.date() == f.date())
                self.assertTrue(P.hm(r["reveil"]) <= s.hour * 60 + s.minute and f.hour * 60 + f.minute <= P.hm(r["coucher"]))
                for x in fixes:   # jamais sur un cours ni un examen, ni pendant le trajet
                    self.assertFalse(chevauche(b, x, r["trajet_min"]), f"sur {x['titre']} {x['debut']}")
                for autre in blocs:
                    if autre is not b:
                        self.assertFalse(chevauche(b, autre), f"sur {autre['titre']} {autre['debut']}")
        genres = [b["genre"] for b in blocs]
        self.assertEqual(genres.count("repas"), 14, "déjeuner et dîner chaque jour")
        [courses] = [b for b in blocs if b["genre"] == "courses"]
        self.assertEqual(courses["debut"], "2026-11-21T10:00", "le samedi, à l'heure choisie")
        # salle : 3 séances, jamais deux jours de suite ni le jour de l'examen, dans la plage choisie, programme suivi
        salle = sorted((b for b in blocs if b["genre"] == "salle"), key=lambda b: b["debut"])
        jours = [P.lire_iso(b["debut"]).date() for b in salle]
        self.assertEqual(len(salle), 3)
        self.assertTrue(all((b - a).days > 1 for a, b in zip(jours, jours[1:])), jours)
        self.assertNotIn(date(2026, 11, 19), jours)
        self.assertTrue(all("17:00" <= b["debut"][11:] and b["fin"][11:] <= "21:30" for b in salle))
        self.assertEqual([b["titre"] for b in salle], ["Salle : Pecs et bras", "Salle : Dos, épaules et abdos", "Salle : Pecs et bras"])
        self.assertIn("Développé décliné", salle[0]["notes"])
        # la tâche, avant sa date limite
        [t] = [b for b in blocs if b["genre"] == "tache"]
        self.assertEqual((t["tache"], t["titre"]), (7, "Rendre le TP"))
        self.assertLessEqual(t["debut"][:10], "2026-11-18")
        self.assertEqual(P.lire_iso(t["fin"]) - P.lire_iso(t["debut"]), timedelta(minutes=60))
        # révisions : avant l'examen, tout pour BDR ; après, les matières tour à tour
        revisions = [b for b in blocs if b["genre"] == "revision"]
        avant = {b["matiere"] for b in revisions if b["debut"] < "2026-11-19"}
        apres = {b["matiere"] for b in revisions if b["debut"] >= "2026-11-20"}
        self.assertEqual(avant, {"BDR"})
        self.assertEqual(apres, {"Analyse", "BDR", "Anglais"})
        self.assertFalse([b for b in revisions if b["debut"][:10] == "2026-11-19" and b["matiere"] == "BDR" and b["fin"][11:] > "08:30"],
                         "le jour de l'examen, sa matière seulement avant (et 30 min avant au plus tard)")
        for jour in range(7):
            j = (LUNDI + timedelta(days=jour)).isoformat()
            minutes = sum(50 for b in revisions if b["debut"][:10] == j)
            plafond = (180 if jour >= 5 else 120) * (1.5 if jour <= 3 else 1)    # semaine d'examen : moitié plus
            self.assertLessEqual(minutes, plafond, j)
        for b in revisions:               # 10 minutes de pause après chaque bloc
            fin = P.lire_iso(b["fin"])
            self.assertFalse([x for x in revisions if fin <= P.lire_iso(x["debut"]) < fin + timedelta(minutes=10)], b)

    def test_rien_dans_le_passe(self):
        blocs, _ = self.planifier(maintenant=datetime(2026, 11, 18, 15, 0))
        self.assertTrue(blocs)
        self.assertTrue(all(b["debut"] >= "2026-11-18T15:05" for b in blocs), [b["debut"] for b in blocs if b["debut"] < "2026-11-18T15:05"])

    def test_soiree_qui_finit_apres_minuit(self):
        nuit = {"genre": "perso", "titre": "Nuit chez Paul", "debut": "2026-11-20T20:00", "fin": "2026-11-21T08:30", "journee": False}
        blocs, _ = self.planifier(fixes=fixes_type() + [nuit], examens=())
        self.assertFalse([b for b in blocs if "2026-11-20T20:00" < b["fin"] and b["debut"] < "2026-11-21T08:30"],
                         "rien pendant la soirée, ni le lendemain matin avant son retour")
        self.assertTrue([b for b in blocs if b["debut"][:10] == "2026-11-21"], "le samedi reste planifié après")

    def test_programme_a_la_suite_de_la_semaine_d_avant(self):
        blocs, _ = self.planifier(salle_avant=[{"titre": "Salle : Pecs et bras", "debut": "2026-11-15T18:00"}])
        salle = sorted((b for b in blocs if b["genre"] == "salle"), key=lambda b: b["debut"])
        self.assertEqual(salle[0]["titre"], "Salle : Dos, épaules et abdos")
        self.assertNotEqual(salle[0]["debut"][:10], "2026-11-16", "pas le lendemain de la dernière séance")

    def test_programme_personnel(self):
        blocs, _ = self.planifier(programme="Jambes\nSquat\nPresse\n\nHaut du corps\nTractions", salle_par_semaine=2)
        self.assertEqual([b["titre"] for b in sorted((b for b in blocs if b["genre"] == "salle"), key=lambda b: b["debut"])],
                         ["Salle : Jambes", "Salle : Haut du corps"])

    def test_semaine_pleine(self):
        plein = [{"genre": "perso", "titre": "Stage", "debut": f"{LUNDI + timedelta(days=i)}T00:00",
                  "fin": f"{LUNDI + timedelta(days=i)}T23:59", "journee": False} for i in range(7)]
        blocs, _ = self.planifier(fixes=plein, examens=(), taches=[{"id": 1, "titre": "x", "minutes": 30}])
        self.assertEqual(blocs, [])

    def test_tache_dont_la_date_est_passee(self):
        blocs, _ = self.planifier(maintenant=datetime(2026, 11, 18, 9), taches=[{"id": 3, "titre": "trop tard", "minutes": 30, "echeance": "2026-11-17"}])
        self.assertFalse([b for b in blocs if b["genre"] == "tache"])


# --- L'agenda par ses adresses -------------------------------------------------------------------
class AvecServeur(unittest.TestCase):
    """Un serveur neuf par test, à l'heure figée."""
    env = {"SMOKY_MAINTENANT": MAINTENANT}

    def setUp(self):
        self.srv = Serveur(env=self.env)
        self.addCleanup(self.srv.stop)

    def etat(self, semaine=0):
        code, e = self.srv.json("GET", f"/api/agenda?semaine={semaine}")
        self.assertEqual(code, 200, e)
        return e

    def agir(self, action, **valeurs):
        return self.srv.json("POST", "/api/agenda", {"action": action, **valeurs})

    def reussir(self, action, **valeurs):
        code, r = self.agir(action, **valeurs)
        self.assertEqual(code, 200, r)
        return r

    def importer(self, texte=None):
        return self.reussir("importer", contenu=texte or semaine_type())

    def elements(self, genre=None, **kw):
        return [e for e in self.etat(**kw)["elements"] if genre is None or e["genre"] == genre]


class TestAgenda(AvecServeur):
    def test_semaine_vide(self):
        e = self.etat()
        self.assertEqual((e["debut"], e["maintenant"], e["decalage"]), ("2026-11-16", MAINTENANT, 0))
        self.assertEqual(e["jours"], [(LUNDI + timedelta(days=i)).isoformat() for i in range(7)])
        self.assertEqual(e["elements"], [])
        self.assertEqual(e["edt"], {"lien": False, "lien_lu": False, "fichier": False, "cours": 0, "erreur": "", "ancien": False})
        self.assertEqual(e["reglages"]["matieres"][:3], ["Magnéto", "MNA", "Algèbre"], "matières communes de Smoky OS")
        self.assertEqual(e["seances"][0]["nom"], "Pecs et bras")
        self.assertEqual(self.etat(1)["debut"], "2026-11-23")
        self.assertEqual(self.etat(-1)["debut"], "2026-11-09")
        for mauvais in ("abc", "100", "1.5", "%2B1", "%D9%A3", "-"):
            with self.subTest(semaine=mauvais):
                self.assertEqual(self.srv.req("GET", f"/api/agenda?semaine={mauvais}")[0], 400)

    def test_importer_un_emploi_du_temps(self):
        self.assertEqual(self.importer()["message"], "Emploi du temps importé : 10 cours.")
        cours = self.elements("cours")
        self.assertEqual(len(cours), 10)
        mardi = [c for c in cours if c["debut"][:10] == "2026-11-17"]
        self.assertEqual([(c["titre"], c["debut"][11:], c["fin"][11:], c["lieu"], c["source"]) for c in mardi],
                         [("Analyse CM", "08:00", "10:00", "Amphi 1", "edt"), ("BDR TD", "14:00", "16:00", "B201", "edt")])
        fichier = Path(self.srv.environnement["SMOKY_DONNEES"]) / "emploi-du-temps.ics"
        self.assertEqual(oct(fichier.stat().st_mode & 0o777), "0o600", "lisible par toi seul")
        self.assertEqual(self.elements("cours", semaine=1), [], "rien la semaine suivante")
        self.assertEqual(self.etat()["edt"]["cours"], 10)
        # même emploi du temps importé de nouveau : pas de doublon
        self.importer()
        self.assertEqual(len(self.elements("cours")), 10)

    def test_fichiers_refuses(self):
        for contenu, message in (("bonjour", "Ce fichier n'est pas un calendrier .ics."), (ics(), "Aucun cours trouvé dans ce fichier."),
                                 (None, "Ce fichier n'est pas un calendrier .ics."), (["BEGIN:VCALENDAR"], "Ce fichier n'est pas un calendrier .ics."),
                                 ("BEGIN:VCALENDAR\n" + "x" * (5 * 1024 * 1024), "Ce fichier n'est pas un calendrier .ics.")):
            with self.subTest(contenu=str(contenu)[:30]):
                self.assertEqual(self.agir("importer", contenu=contenu), (400, {"erreur": message}))
        self.assertEqual(self.etat()["edt"]["fichier"], False)

    def test_calendrier_d_examens(self):
        self.assertEqual(self.importer(examens_ics())["message"], "2 examens ajoutés à ton agenda.")
        self.importer(examens_ics())                     # importé deux fois : toujours 2 examens
        e = self.etat()
        self.assertEqual([(x["titre"], x["matiere"]) for x in e["examens"]], [("Examen BDR", "BDR"), ("Partiel d'optique ondulatoire", "Optique")])
        [jeudi] = self.elements("examen")
        self.assertEqual((jeudi["debut"], jeudi["lieu"], jeudi["source"]), ("2026-11-19T09:00", "Amphi A", "toi"))
        self.assertFalse(e["edt"]["fichier"], "un calendrier d'examens ne remplace pas l'emploi du temps")

    def test_ajouter(self):
        r = self.reussir("ajouter", genre="perso", titre="  Dentiste\x1b[0m\n", lieu="Rue Haute", jour="2026-11-18", debut="17:00", fin="18:00")
        self.assertRegex(r["id"], r"^toi-[0-9a-f]{10}$")
        self.reussir("ajouter", genre="examen", titre="DS Électromagnétisme", jour="2026-11-20", debut="10:00", fin="12:00")
        self.reussir("ajouter", genre="revision", matiere="BDR", jour="2026-11-18", debut="20:00", fin="21:00")
        r = self.reussir("ajouter", genre="tache", titre="Préparer l'exposé", minutes=90, echeance="2026-11-20")
        self.assertIn("Planifier", r["message"])
        e = self.etat()
        [rdv] = [x for x in e["elements"] if x["genre"] == "perso"]
        self.assertEqual((rdv["titre"], rdv["lieu"], rdv["debut"], rdv["fin"]), ("Dentiste [0m", "Rue Haute", "2026-11-18T17:00", "2026-11-18T18:00"))
        self.assertEqual([x["matiere"] for x in e["examens"]], ["Magnéto"])
        [rev] = [x for x in e["elements"] if x["genre"] == "revision"]
        self.assertEqual((rev["titre"], rev["origine"], rev["matiere"], rev["source"]), ("Révision : BDR", "toi", "BDR", "plan"))
        self.assertEqual([(t["titre"], t["minutes"], t["echeance"], t["creneau"]) for t in e["a_caser"]],
                         [("Préparer l'exposé", 90, "2026-11-20", None)])
        self.assertEqual([t["minutes"] for t in self.srv.json("GET", "/api/aujourdhui")[1]["taches"]], [90], "aussi dans « à faire »")

    def test_taches_avec_duree(self):
        for minutes in ("30", 5, 481, True, 2.5):
            with self.subTest(minutes=minutes):
                self.assertEqual(self.srv.json("POST", "/api/taches", {"titre": "x", "minutes": minutes}),
                                 (400, {"erreur": "Durée entre 10 et 480 minutes."}))
        code, t = self.srv.json("POST", "/api/taches", {"titre": "Ranger le bureau", "minutes": 30})
        self.assertEqual((code, t["minutes"]), (201, 30))
        self.assertEqual([x["titre"] for x in self.etat()["a_caser"]], ["Ranger le bureau"])
        code, t = self.srv.json("POST", f"/api/taches/{t['id']}", {"minutes": None})
        self.assertEqual((code, t["minutes"]), (200, None))
        self.assertEqual(self.etat()["a_caser"], [], "sans durée : une simple tâche, plus à caser")

    def test_ajouter_refuse(self):
        bon = {"genre": "perso", "titre": "x", "jour": "2026-11-18", "debut": "17:00", "fin": "18:00"}
        for changement, message in (({"titre": " "}, "Donne un nom."), ({"titre": None}, "Donne un nom."),
                                    ({"debut": "25:00"}, "Date ou heure invalide."), ({"jour": "2026-02-30"}, "Date ou heure invalide."),
                                    ({"jour": "18/11/2026"}, "Date ou heure invalide."), ({"fin": "16:00"}, "La fin doit être après le début."),
                                    ({"fin": "17:00"}, "La fin doit être après le début."), ({"genre": "cours"}, "Genre inconnu."),
                                    ({"genre": "revision", "matiere": "Cuisine"}, "Matière inconnue."),
                                    ({"genre": "tache", "minutes": 5}, "Durée entre 10 et 480 minutes."),
                                    ({"genre": "tache", "minutes": True}, "Durée entre 10 et 480 minutes."),
                                    ({"genre": "tache", "minutes": "60"}, "Durée entre 10 et 480 minutes."),
                                    ({"genre": "tache", "minutes": 60, "echeance": "demain"}, "Date limite invalide.")):
            with self.subTest(**{k: str(v) for k, v in changement.items()}):
                self.assertEqual(self.agir("ajouter", **{**bon, **changement}), (400, {"erreur": message}))
        self.assertEqual(self.etat()["elements"], [])
        for corps in ({"action": "inconnue"}, {"action": "_a_ajouter"}, {"action": "__init__"}, {"action": 3}, {}, []):
            with self.subTest(corps=corps):
                self.assertEqual(self.srv.json("POST", "/api/agenda", corps)[0], 400)

    def test_planifier_garde_ce_qui_doit_rester(self):
        self.importer()
        self.reussir("ajouter", genre="revision", matiere="Anglais", jour="2026-11-18", debut="18:00", fin="19:00")
        r = self.reussir("planifier", semaine=0)
        self.assertRegex(r["message"], r"^Semaine planifiée : \d+ blocs\.$")
        blocs = [x for x in self.etat()["elements"] if x["source"] == "plan"]
        self.assertTrue(all(x["debut"] >= "2026-11-17T09:05" for x in blocs if x["origine"] == "pc"), "rien dans le passé")
        a_moi = [x for x in blocs if x["origine"] == "toi"]
        self.assertEqual(len(a_moi), 1)
        jeudi = next(x for x in blocs if x["origine"] == "pc" and x["debut"][:10] == "2026-11-19")
        self.reussir("basculer", id=jeudi["id"])
        # le lendemain à midi : on replanifie ; restent le passé, ce qui est fait, ce que tu as ajouté
        self.srv.arreter()
        self.srv.environnement["SMOKY_MAINTENANT"] = "2026-11-18T12:00"
        self.srv.demarrer()
        self.reussir("planifier", semaine=0)
        apres = {x["id"]: x for x in self.etat()["elements"] if x["source"] == "plan"}
        for x in blocs:
            garde = x["debut"] <= "2026-11-18T12:00" or x["origine"] == "toi" or x["id"] == jeudi["id"]   # commencé : gardé
            self.assertEqual(x["id"] in apres, garde, x)
        self.assertTrue(apres[jeudi["id"]]["fait"])
        self.assertEqual(self.etat()["planifie_par"], "pc")
        self.assertEqual(self.agir("planifier", semaine=-1), (400, {"erreur": "Cette semaine est déjà passée."}))
        self.assertEqual(self.agir("planifier", semaine="1")[0], 400)

    def test_une_tache_casee_suit_son_etat(self):
        self.importer()
        tid = self.reussir("ajouter", genre="tache", titre="Rendre le TP", minutes=60, echeance="2026-11-18")["id"]
        self.reussir("planifier")
        [bloc] = [x for x in self.elements("tache")]
        self.assertEqual((bloc["tache"], bloc["titre"]), (tid, "Rendre le TP"))
        [t] = self.etat()["a_caser"]
        self.assertEqual(t["creneau"], bloc["debut"])
        # cochée dans l'agenda → faite dans « à faire »
        self.assertEqual(self.reussir("basculer", id=bloc["id"])["fait"], True)
        tache = lambda: next(x for x in self.srv.json("GET", "/api/aujourdhui")[1]["taches"] if x["id"] == tid)  # noqa: E731
        self.assertTrue(tache()["faite"])
        self.assertEqual(self.etat()["a_caser"], [])
        self.reussir("basculer", id=bloc["id"])
        self.assertFalse(tache()["faite"])
        # cochée dans « à faire » → son créneau est fait aussi
        self.assertEqual(self.srv.json("POST", f"/api/taches/{tid}", {"faite": True})[0], 200)
        self.assertTrue(self.elements("tache")[0]["fait"])
        # replanifier ne la recase pas ; supprimée, son créneau disparaît
        self.reussir("planifier")
        self.assertEqual(len(self.elements("tache")), 1)
        self.assertEqual(self.srv.req("DELETE", f"/api/taches/{tid}")[0], 200)
        self.assertEqual(self.elements("tache"), [])

    def test_retirer_et_cocher(self):
        self.importer()
        eid = self.reussir("ajouter", genre="perso", titre="Dentiste", jour="2026-11-18", debut="17:00", fin="18:00")["id"]
        self.assertEqual(self.agir("basculer", id=eid), (400, {"erreur": "Seuls les blocs du planning se cochent."}))
        cours = self.elements("cours")[0]["id"]
        for mauvais in (cours, "due-12", "bloc-zzzzzzzzzz", "bloc-0000000000", "toi-'; DROP TABLE x", None, 3):
            with self.subTest(id=mauvais):
                self.assertEqual(self.agir("supprimer", id=mauvais), (404, {"erreur": "Élément introuvable."}))
        self.assertEqual(self.reussir("supprimer", id=eid)["message"], "Retiré de ton agenda.")
        self.assertEqual(self.elements("perso"), [])
        self.assertEqual(len(self.elements("cours")), 10, "les cours de l'emploi du temps ne se retirent pas")

    def test_reglages(self):
        r = self.reussir("regler", valeurs={"reveil": "06:45", "repas_min": 30, "rappels": False, "matieres": [" BDR ", "Anglais", "BDR", ""],
                                            "modele": "haiku", "courses_jour": 6})
        self.assertEqual({k: r["reglages"][k] for k in ("reveil", "repas_min", "rappels", "matieres", "modele", "courses_jour")},
                         {"reveil": "06:45", "repas_min": 30, "rappels": False, "matieres": ["BDR", "Anglais"], "modele": "haiku", "courses_jour": 6})
        self.assertEqual(self.etat()["reglages"]["reveil"], "06:45", "gardé")
        for valeurs, message in (({"inconnu": 1}, "Réglage inconnu."), ({}, "Réglage inconnu."), ({"reveil": "7h"}, "Heure invalide (HH:MM)."),
                                 ({"reveil": "24:00"}, "Heure invalide (HH:MM)."), ({"repas_min": 5}, "Choisis un nombre entre 15 et 120."),
                                 ({"repas_min": "30"}, "Choisis un nombre entre 15 et 120."), ({"salle_par_semaine": True}, "Choisis un nombre entre 0 et 7."),
                                 ({"rappels": 1}, "Valeur refusée."), ({"coucher": "06:00"}, "L'heure de coucher doit être après celle du réveil."),
                                 ({"salle_des": "21:00"}, "La plage de la salle est plus courte qu'une séance."), ({"modele": "gpt"}, "Modèle inconnu."),
                                 ({"lien": "ftp://ent.exemple/edt.ics"}, "Le lien de l'emploi du temps doit commencer par https://"),
                                 ({"lien": "https://"}, "Le lien de l'emploi du temps doit commencer par https://"),
                                 ({"lien": "https://ent.exemple/a b.ics"}, "Le lien de l'emploi du temps doit commencer par https://")):
            with self.subTest(valeurs=valeurs):
                self.assertEqual(self.agir("regler", valeurs=valeurs), (400, {"erreur": message}))
        self.assertEqual(self.etat()["reglages"]["repas_min"], 30, "un réglage refusé ne change rien")
        # liste des matières de Smoky OS remise : elle suit de nouveau les matières communes
        commun = self.etat()["matieres_os"]
        self.reussir("regler", valeurs={"matieres": commun})
        self.assertEqual(self.srv.json("GET", "/api/agenda")[1]["reglages"]["matieres"], commun)

    def test_moodle_et_journee(self):
        dossier = self.srv.home / ".local/share/smoky-moodle"
        dossier.mkdir(parents=True)
        due = int(datetime(2026, 11, 17, 23, 59).timestamp())
        (dossier / "echeances.json").write_text(json.dumps([
            {"id": 41, "name": "Compte rendu TP3", "course": "Bases de données", "time": due, "subject": "BDR", "url": "https://moodle.exemple/x"},
            {"id": 42, "name": "Hors semaine", "time": due + 30 * 86400}, {"id": "x", "time": "jamais"}, "n'importe quoi"]))
        self.importer()
        [d] = self.elements("devoir")
        self.assertEqual((d["titre"], d["debut"], d["fin"], d["matiere"], d["source"], d["id"]),
                         ("Compte rendu TP3", "2026-11-17T23:29", "2026-11-17T23:59", "BDR", "moodle", "due-41"))
        code, auj = self.srv.json("GET", "/api/aujourdhui")
        self.assertEqual(auj["maintenant"], MAINTENANT)
        self.assertEqual([(x["genre"], x["titre"]) for x in auj["journee"]],
                         [("cours", "Analyse CM"), ("cours", "BDR TD"), ("devoir", "Compte rendu TP3")])
        self.reussir("planifier")
        self.assertNotIn("repas", [x["genre"] for x in self.srv.json("GET", "/api/aujourdhui")[1]["journee"]], "les repas n'encombrent pas « ta journée »")

    def test_seance_de_salle(self):
        self.importer()
        self.reussir("planifier")
        salle = self.elements("salle")[0]
        exercice = salle["notes"].splitlines()[0]
        self.assertEqual(self.reussir("seance", id=salle["id"], entrees=[{"exercice": exercice, "kg": 42.5, "reps": 10}])["message"], "Séance notée.")
        self.reussir("seance", id=salle["id"], entrees=[{"exercice": exercice, "kg": 45, "reps": 8}])     # corrigée : remplace
        self.assertEqual(self.etat()["charges"], {exercice: {"kg": 45.0, "reps": 8, "jour": salle["debut"][:10]}})
        autre = self.elements("repas")[0]["id"]
        for entrees, ident, message in (([{"exercice": exercice, "kg": 600, "reps": 8}], salle["id"], "Charge ou répétitions invalides."),
                                        ([{"exercice": exercice, "kg": 40, "reps": 0}], salle["id"], "Charge ou répétitions invalides."),
                                        ([{"exercice": "", "kg": 40, "reps": 5}], salle["id"], "Charge ou répétitions invalides."),
                                        ([{"exercice": exercice, "kg": True, "reps": 5}], salle["id"], "Charge ou répétitions invalides."),
                                        ([], salle["id"], "Rien à noter."), ("x", salle["id"], "Rien à noter."),
                                        ([{"exercice": exercice, "kg": 40, "reps": 5}], autre, "Ce n'est pas une séance de salle.")):
            with self.subTest(entrees=str(entrees)[:40]):
                self.assertEqual(self.agir("seance", id=ident, entrees=entrees), (400, {"erreur": message}))

    def test_ouvrir_un_carnet(self):
        self.srv.vider()
        self.assertEqual(self.reussir("ouvrir_carnet", matiere="BDR")["message"], "Carnet BDR ouvert dans Smoky Notes.")
        self.assertEqual(self.srv.attendre_commandes(1), [["smoky-notes", "--classeur", "BDR"]])
        self.assertEqual(self.agir("ouvrir_carnet", matiere="../../x"), (400, {"erreur": "Matière inconnue."}))

    def test_les_fenetres_sont_prevenues(self):
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        self.assertEqual(fenetre.attendre("bonjour"), {})
        self.importer()
        self.assertEqual(fenetre.attendre("change"), {"quoi": "agenda"})
        self.agir("ajouter", genre="perso", titre="", jour="2026-11-18", debut="17:00", fin="18:00")
        self.assertIsNone(fenetre.attendre("change", delai=0.5), "une demande refusée n'annonce rien")


class TestMiseANiveau(unittest.TestCase):
    def test_memoire_de_l_etape_1(self):
        """La mémoire laissée par la version d'avant (étape 1 : réglages et tâches) passe à l'agenda sans rien perdre."""
        import sqlite3
        from smoky.base import MIGRATIONS

        def preparer(srv):
            (srv.base / "donnees").mkdir()
            db = sqlite3.connect(srv.base / "donnees/smoky.db")
            db.executescript(f"BEGIN;\n{MIGRATIONS[0]}\nPRAGMA user_version=1;\nCOMMIT;")
            db.execute("INSERT INTO taches (titre, faite, echeance, creee) VALUES ('Réviser MNA', 0, '2026-11-20', 1)")
            db.execute("INSERT INTO reglages (cle, valeur) VALUES ('autre', '{\"garde\": true}')")
            db.commit()
            db.close()
        srv = Serveur(env={"SMOKY_MAINTENANT": MAINTENANT}, preparer=preparer)
        self.addCleanup(srv.stop)
        self.assertEqual([(t["titre"], t["echeance"], t["minutes"]) for t in srv.json("GET", "/api/aujourdhui")[1]["taches"]],
                         [("Réviser MNA", "2026-11-20", None)])
        self.assertEqual(srv.json("POST", "/api/agenda", {"action": "importer", "contenu": semaine_type()})[0], 200)
        self.assertEqual(len([e for e in srv.json("GET", "/api/agenda")[1]["elements"] if e["genre"] == "cours"]), 10)
        lecture = sqlite3.connect(srv.base / "donnees/smoky.db")
        self.addCleanup(lecture.close)
        self.assertEqual(lecture.execute("PRAGMA user_version").fetchone()[0], len(MIGRATIONS))
        self.assertEqual(lecture.execute("SELECT valeur FROM reglages WHERE cle = 'autre'").fetchone()[0], '{"garde": true}')


class TestEmploiDuTempsSources(AvecServeur):
    def test_lien_ical(self):
        site = SiteEdt()
        self.addCleanup(site.fermer)
        r = self.reussir("regler", valeurs={"lien": site.lien})
        self.assertEqual(r["message"], "Lien enregistré : 10 cours trouvés.")
        e = self.etat()
        self.assertEqual((e["edt"]["lien"], e["edt"]["lien_lu"], e["edt"]["cours"]), (True, True, 10))
        self.assertEqual(len(self.elements("cours")), 10)
        self.etat()
        time.sleep(0.5)
        self.assertEqual(site.demandes, 1, "relu au plus toutes les 6 heures : pas à chaque affichage")
        # la même semaine importée aussi en fichier : pas de doublon
        self.importer()
        self.assertEqual(len(self.elements("cours")), 10)
        # le site se met à répondre autre chose : la dernière copie reste affichée, l'erreur est dite clairement
        for reponse, morceau in (((200, "text/html", "<html><body>Connexion CAS</body></html>"), "page web"),
                                 ((403, "text/plain", "non"), "erreur 403"), ((200, "text/plain", "rien"), "pas un calendrier")):
            site.reponse = reponse
            with self.subTest(morceau=morceau):
                code, r = self.agir("actualiser")
                self.assertEqual(code, 502)
                self.assertIn(morceau, r["erreur"])
                e = self.etat()
                self.assertIn(morceau, e["edt"]["erreur"])
                self.assertEqual(len([x for x in e["elements"] if x["genre"] == "cours"]), 10)
        site.reponse = (200, "text/calendar", semaine_type(LUNDI + timedelta(days=7)))
        self.assertEqual(self.reussir("actualiser")["message"], "Emploi du temps relu : 10 cours.")
        self.assertEqual(self.etat()["edt"]["erreur"], "")
        self.assertEqual(len(self.elements("cours", semaine=1)), 10)

    def test_lien_relu_toutes_les_6_heures(self):
        site = SiteEdt()
        self.addCleanup(site.fermer)
        self.reussir("regler", valeurs={"lien": site.lien})
        self.assertEqual(site.demandes, 1)
        copie = Path(self.srv.environnement["SMOKY_DONNEES"]) / "emploi-du-temps-lien.ics"
        # serveur relancé (plus aucun souvenir du dernier essai) : copie fraîche, pas relue
        self.srv.arreter()
        self.srv.demarrer()
        self.etat()
        time.sleep(0.5)
        self.assertEqual(site.demandes, 1, "copie de moins de 6 heures : le site n'est pas sollicité")
        # copie de 7 heures : relue en arrière-plan, et la page est prévenue
        os.utime(copie, (time.time() - 7 * 3600, time.time() - 7 * 3600))
        self.srv.arreter()
        self.srv.demarrer()
        fenetre = Ecoute(self.srv)
        self.addCleanup(fenetre.fermer)
        fenetre.attendre("bonjour")
        self.assertEqual(len(self.elements("cours")), 10, "la vieille copie s'affiche en attendant")
        self.assertEqual(fenetre.attendre("change"), {"quoi": "agenda"})
        self.assertEqual(site.demandes, 2)
        self.assertGreater(copie.stat().st_mtime, time.time() - 60)

    def test_site_en_panne_pas_sollicite_a_chaque_affichage(self):
        site = SiteEdt()
        self.addCleanup(site.fermer)
        site.reponse = (500, "text/plain", "panne")
        self.reussir("regler", valeurs={"lien": site.lien})
        for _ in range(3):
            self.etat()
        time.sleep(0.5)
        self.assertEqual(site.demandes, 1, "après un échec : un nouvel essai toutes les 10 minutes au plus")

    def test_lien_injoignable_et_webcal(self):
        site = SiteEdt()
        lien = site.lien
        site.fermer()
        r = self.reussir("regler", valeurs={"lien": lien})
        self.assertIn("injoignable", r["message"])
        self.assertIn("injoignable", self.etat()["edt"]["erreur"])
        r = self.reussir("regler", valeurs={"lien": "webcal://127.0.0.1:9/edt.ics"})
        self.assertEqual(r["reglages"]["lien"], "https://127.0.0.1:9/edt.ics", "webcal:// devient https://")
        self.reussir("regler", valeurs={"lien": ""})
        self.assertEqual(self.etat()["edt"], {"lien": False, "lien_lu": False, "fichier": False, "cours": 0, "erreur": "", "ancien": False})

    def test_telechargements(self):
        dl = self.srv.home / "Téléchargements"
        dl.mkdir()
        (dl / "invitation.ics").write_text(ics(ev(LUNDI, "18:00", "19:00", "Apéro")))               # une simple invitation
        (dl / "export-smoky.ics").write_text(semaine_type().replace("PRODID:-//ADE//FR", "PRODID:-//Smoky OS//Agenda//FR"))
        self.assertEqual(self.elements("cours"), [], "ni une invitation, ni un fichier écrit par Smoky")
        (dl / "ADECal.ics").write_text(semaine_type())
        self.assertEqual(len(self.elements("cours")), 10, "repris tout seul")
        (dl / "Examens S3.ics").write_text(examens_ics())
        os.utime(dl / "Examens S3.ics", (time.time() + 5, time.time() + 5))
        self.assertEqual(len(self.etat()["examens"]), 2)
        # un fichier plus ancien que l'emploi du temps actuel n'est pas repris
        (dl / "vieux.ics").write_text(semaine_type(LUNDI + timedelta(days=7)))
        os.utime(dl / "vieux.ics", (time.time() - 86400, time.time() - 86400))
        self.assertEqual(self.elements("cours", semaine=1), [])

    def test_reprendre_l_ancien_agenda(self):
        site = SiteEdt()
        self.addCleanup(site.fermer)
        ancien = self.srv.home / ".local/share/smoky-agenda"
        ancien.mkdir(parents=True)
        (ancien / "settings.json").write_text(json.dumps({"ics_url": site.lien, "wake": "07:00"}))
        (ancien / "edt-cache.ics").write_text(semaine_type())
        (ancien / "edt-import.ics").write_text(ics(ev(date(2026, 11, 21), "09:00", "12:00", "Rattrapage Méca")))
        avant = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in ancien.iterdir()}
        self.assertTrue(self.etat()["edt"]["ancien"])
        site.reponse = (500, "text/plain", "panne")       # le site ne répond pas : sa dernière copie sert
        r = self.reussir("reprendre_ancien")
        self.assertEqual(r["message"], "Repris de l'ancien Agenda : le lien et le fichier importé.")
        e = self.etat()
        self.assertEqual(e["reglages"]["lien"], site.lien)
        self.assertEqual(sorted({x["titre"] for x in e["elements"] if x["genre"] == "cours"}), ["Analyse CM", "BDR TD", "Rattrapage Méca"])
        self.assertFalse(e["edt"]["ancien"], "proposé seulement tant que l'agenda est vide")
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in ancien.iterdir()}, avant, "l'ancien agenda n'est pas modifié")

    def test_rien_a_reprendre(self):
        self.assertEqual(self.agir("reprendre_ancien"), (404, {"erreur": "L'ancien Agenda n'a pas d'emploi du temps à reprendre."}))


# --- Planification par Claude (fausse commande claude) -------------------------------------------
FAUX_CLAUDE = r'''#!/bin/sh
# Faux Claude Code : « auth status » répond selon le fichier claude-connecte ; sinon il note la
# consigne reçue et renvoie la réponse préparée dans claude-reponse (après 1 s si claude-lent existe).
F=$SMOKY_TEST_FAUX
if [ "$1" = "auth" ]; then [ -e "$F/claude-connecte" ]; exit $?; fi
[ -e "$F/claude-lent" ] && /bin/sleep 1
US=$(printf '\037')
ligne=claude
for a in "$@"; do ligne="$ligne$US$a"; done
printf '%s\n' "$ligne" >> "$SMOKY_TEST_JOURNAL"
printf '%s|%s\n' "${ANTHROPIC_API_KEY:-sans-cle}" "${ANTHROPIC_BASE_URL:-sans-adresse}" > "$F/claude-env"
while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$l"; done > "$F/claude-consigne"
while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$l"; done < "$F/claude-reponse"
[ -e "$F/claude-echec" ] && exit 1
exit 0
'''


class TestPlanifierAvecClaude(AvecServeur):
    env = {"SMOKY_MAINTENANT": MAINTENANT, "ANTHROPIC_API_KEY": "cle-d-essai", "ANTHROPIC_BASE_URL": "http://192.0.2.1"}

    def setUp(self):
        super().setUp()
        (self.srv.faux / "claude").write_text(FAUX_CLAUDE)
        (self.srv.faux / "claude").chmod(0o755)
        (self.srv.faux / "claude-connecte").touch()
        self.importer()
        self.tid = self.reussir("ajouter", genre="tache", titre="Rendre le TP", minutes=60, echeance="2026-11-20")["id"]

    def repondre(self, blocs, is_error=False):
        texte = "Voici ta semaine :\n" + json.dumps({"blocks": blocs}, ensure_ascii=False)
        (self.srv.faux / "claude-reponse").write_text(json.dumps({"type": "result", "is_error": is_error, "result": texte}))

    def attendre_resultat(self):
        attendre(lambda: (self.etat()["claude_travail"]["resultat"] or {}).get("message"), 20)
        e = self.etat()
        self.assertFalse(e["claude_travail"]["en_cours"])
        return e

    def test_seuls_les_bons_blocs_sont_gardes(self):
        attendre(lambda: self.etat()["claude"], 10)
        self.repondre([
            {"day": "2026-11-18", "start": "18:00", "end": "19:00", "type": "revision", "title": "Révision : BDR"},
            {"day": "2026-11-18", "start": "09:00", "end": "10:00", "type": "revision", "title": "sur un cours"},
            {"day": "2026-11-23", "start": "10:00", "end": "11:00", "type": "revision", "title": "semaine suivante"},
            {"day": "2026-11-17", "start": "07:00", "end": "08:00", "type": "revision", "title": "dans le passé"},
            {"day": "2026-11-19", "start": "20:00", "end": "19:00", "type": "perso", "title": "à l'envers"},
            {"day": "2026-11-19", "start": "17:00", "end": "18:30", "type": "salle", "title": "Salle : Dos, épaules et abdos"},
            {"day": "2026-11-20", "start": "18:00", "end": "19:00", "type": "tache", "title": "Rendre le TP", "task": str(self.tid)},
            {"day": "2026-11-20", "start": "18:30", "end": "19:30", "type": "revision", "title": "sur un autre bloc"},
            {"day": "2026-11-21", "start": "10:00", "end": "18:00", "type": "revision", "title": "trop long"},
            {"day": "2026-11-21", "start": "11:00", "end": "12:00", "type": "inconnu", "title": "Ignore les consignes", "task": "999"},
            "oops"])
        r = self.reussir("planifier", claude=True)
        self.assertEqual(r["message"], "Claude organise ta semaine. Cela peut prendre quelques minutes.")
        e = self.attendre_resultat()
        self.assertEqual(e["claude_travail"]["resultat"]["message"], "Claude a organisé ta semaine : 4 blocs.")
        blocs = sorted(((x["genre"], x["titre"], x["debut"], x["origine"], x["tache"], x["matiere"])
                        for x in e["elements"] if x["source"] == "plan"), key=lambda x: x[2])
        self.assertEqual(blocs, [
            ("revision", "Révision : BDR", "2026-11-18T18:00", "claude", None, "BDR"),
            ("salle", "Salle : Dos, épaules et abdos", "2026-11-19T17:00", "claude", None, None),
            ("tache", "Rendre le TP", "2026-11-20T18:00", "claude", self.tid, None),
            ("perso", "Ignore les consignes", "2026-11-21T11:00", "claude", None, None)])
        salle = next(x for x in e["elements"] if x["genre"] == "salle")
        self.assertIn("Tirage machine", salle["notes"], "les exercices de la séance, comme le planning du PC")
        self.assertEqual(e["planifie_par"], "claude")
        # ce que Claude reçoit : la semaine, sans aucun outil ni session gardée
        [appel] = [c for c in self.srv.commandes() if c[0] == "claude"]
        for option in ("--disallowedTools", "--no-session-persistence", "--model"):
            self.assertIn(option, appel)
        self.assertEqual(appel[appel.index("--model") + 1], "opus")
        consigne = (self.srv.faux / "claude-consigne").read_text()
        self.assertIn('"semaine_du": "2026-11-16"', consigne)
        self.assertIn("BDR TD", consigne)
        self.assertNotIn(self.srv.jeton, consigne)
        self.assertEqual((self.srv.faux / "claude-env").read_text(), "sans-cle|sans-adresse\n", "ton abonnement Claude, jamais une clé d'API")

    def test_echec_de_claude(self):
        attendre(lambda: self.etat()["claude"], 10)
        self.reussir("planifier")                                 # un planning du PC existe déjà
        avant = sorted(x["id"] for x in self.etat()["elements"] if x["source"] == "plan")
        for preparer, morceau in ((lambda: self.repondre([], is_error=True), "impossible"),
                                  (lambda: self.repondre([{"day": "2026-11-17", "start": "08:00", "end": "09:00"}]), "inutilisable"),
                                  (lambda: (self.srv.faux / "claude-reponse").write_text("pas du JSON"), "impossible")):
            preparer()
            with self.subTest(morceau=morceau):
                self.reussir("planifier", claude=True)
                e = self.attendre_resultat()
                self.assertFalse(e["claude_travail"]["resultat"]["ok"])
                self.assertIn(morceau, e["claude_travail"]["resultat"]["message"])
                self.assertEqual(sorted(x["id"] for x in e["elements"] if x["source"] == "plan"), avant, "planning inchangé")
                self.srv.json("GET", "/api/agenda")

    def test_claude_pas_connecte(self):
        (self.srv.faux / "claude-connecte").unlink()
        self.assertEqual(self.agir("planifier", claude=True),
                         (400, {"erreur": "Claude n'est pas connecté (Smoky Mail, Réglages, Connecter mon compte Claude)."}))
        self.assertFalse(self.etat()["claude"])


# --- Rappels -----------------------------------------------------------------------------------------
class TestRappels(AvecServeur):
    def rappels(self, attendus=1):
        """Commandes systemd-run passées une fois le changement digéré (les rappels sont repréparés 1,5 s après)."""
        attendre(lambda: len([c for c in self.srv.commandes() if c[0] == "systemd-run"]) >= attendus, 10)
        time.sleep(2)
        return [c for c in self.srv.commandes() if c[0] == "systemd-run"]

    def test_une_notification_avant_chaque_element(self):
        self.srv.vider()
        self.importer()
        poses = self.rappels()
        par_heure = {next(a for a in c if a.startswith("--on-calendar="))[14:]: c for c in poses}
        # mardi 9 h : le cours de 8 h est commencé ; BDR à 14 h (rappel 13 h 50), puis mercredi jusqu'à 21 h (36 h)
        self.assertEqual(sorted(par_heure), ["2026-11-17 13:50:00", "2026-11-18 07:50:00", "2026-11-18 13:50:00"])
        c = par_heure["2026-11-17 13:50:00"]
        self.assertRegex(next(a for a in c if a.startswith("--unit=")), r"^--unit=smoky-rappel-[0-9a-f]{12}$")
        self.assertEqual(c[c.index("notify-send"):], ["notify-send", "-a", "Smoky", "-i", "smoky-appli", "Cours : BDR TD", "14:00 – 16:00, B201"])
        # les minuteurs posés avant sont d'abord retirés ; ceux de l'ancien Agenda aussi (relais pris)
        [liste] = [c for c in self.srv.commandes() if c[:3] == ["systemctl", "--user", "list-units"]][:1]
        self.assertIn("smoky-rappel-*.timer", liste)
        self.assertIn("smoky-agenda-r-*.timer", liste)

    def test_reglages_des_rappels(self):
        self.importer()
        self.reussir("planifier")
        self.rappels()
        self.srv.vider()
        self.reussir("regler", valeurs={"rappel_avant": 30, "menage_pendant_cours": True})
        poses = self.rappels()
        heures = [next(a for a in c if a.startswith("--on-calendar="))[14:] for c in poses]
        self.assertIn("2026-11-17 13:30:00", heures, "30 minutes avant")
        self.assertFalse([c for c in poses if "Repas" in " ".join(c) or "Déjeuner" in c or "Dîner" in c], "pas de rappel pour les repas")
        [menage] = [c for c in poses if any(a.startswith("--unit=smoky-menage-") for a in c)]
        self.assertIn("--unit=smoky-menage-20261118", menage)
        self.assertIn("--on-calendar=2026-11-18 08:10:00", menage, "10 min après le début du premier cours d'une heure")
        self.assertEqual(menage[-2:], ["/usr/bin/python3", str(RACINE / "usr/libexec/smokyos/smoky-home-clean.py")])
        self.srv.vider()
        self.reussir("regler", valeurs={"rappels": False, "menage_pendant_cours": False})
        attendre(lambda: [c for c in self.srv.commandes() if c[:3] == ["systemctl", "--user", "list-units"]], 10)
        time.sleep(2)
        self.assertEqual([c for c in self.srv.commandes() if c[0] == "systemd-run"], [], "rappels coupés : aucun minuteur")

    def test_planning_copie_dans_notes(self):
        export = self.srv.home / "Notes/Planning Smoky.ics"
        self.reussir("ajouter", genre="perso", titre="Dentiste", jour="2026-11-18", debut="17:00", fin="18:00")
        self.reussir("ajouter", genre="revision", matiere="BDR", jour="2026-11-18", debut="20:00", fin="21:00")
        self.rappels()
        self.assertFalse(export.exists(), "tant que l'ancien Agenda est en service, son fichier n'est pas touché")
        self.importer()
        self.reussir("planifier")
        self.assertTrue(attendre(export.exists, 10))
        time.sleep(2)
        texte = export.read_bytes().decode()
        blocs = [x for x in self.etat()["elements"] if x["source"] == "plan"]
        self.assertEqual(texte.count("BEGIN:VEVENT"), len(blocs))
        self.assertIn("PRODID:-//Smoky OS//Agenda//FR", texte)
        self.assertIn("SUMMARY:Révision : BDR\r\n", texte)
        self.assertIn("DTSTART:20261118T190000Z\r\n", texte, "20 h à Paris = 19 h UTC en novembre")
        avant = export.stat().st_mtime_ns
        self.reussir("regler", valeurs={"rappel_avant": 15})        # le planning ne change pas : fichier pas réécrit
        time.sleep(2.5)
        self.assertEqual(export.stat().st_mtime_ns, avant)
        # un export repris dans Téléchargements n'est jamais pris pour un emploi du temps
        (self.srv.home / "Téléchargements").mkdir()
        (self.srv.home / "Téléchargements/Planning Smoky.ics").write_text(texte)
        self.assertEqual(len(self.elements("cours")), 10)

    def test_ancien_agenda_garde_ses_rappels_tant_qu_il_n_est_pas_remplace(self):
        self.srv.vider()
        self.reussir("ajouter", genre="perso", titre="Dentiste", jour="2026-11-17", debut="17:00", fin="18:00")
        self.rappels()
        [liste] = [c for c in self.srv.commandes() if c[:3] == ["systemctl", "--user", "list-units"]][:1]
        self.assertNotIn("smoky-agenda-r-*.timer", liste, "sans emploi du temps, l'ancien Agenda garde ses rappels")


class TestModeRappels(unittest.TestCase):
    """lancer.py --rappels : le minuteur du matin et de la connexion (smoky-agenda-reminders)."""

    def setUp(self):
        self.d = Dossier()
        self.addCleanup(self.d.effacer)
        self.ancien = self.d.base / "ancien-agenda.py"
        self.ancien.write_text("import os, sys\nopen(os.environ['SMOKY_TEST_JOURNAL'], 'a').write('ancien-agenda\\x1f' + '\\x1f'.join(sys.argv[1:]) + '\\n')\n")
        self.env = self.d.env(SMOKY_DONNEES=self.d.base / "donnees", SMOKY_MAINTENANT=MAINTENANT, SMOKY_ANCIEN_AGENDA=self.ancien)

    def lancer(self):
        r = subprocess.run([sys.executable, "-I", "-B", str(LANCER), "--rappels"], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_avec_un_emploi_du_temps(self):
        (self.d.base / "donnees").mkdir()
        (self.d.base / "donnees/emploi-du-temps.ics").write_text(semaine_type())
        (self.d.home / ".local/share/smoky-agenda").mkdir(parents=True)
        (self.d.home / ".local/share/smoky-agenda/agenda.json").write_text("{}")
        self.assertEqual(self.lancer(), "smoky : 3 rappel(s) préparé(s)\n")
        noms = [c[0] for c in self.d.commandes()]
        self.assertEqual(noms.count("systemd-run"), 3)
        self.assertNotIn("ancien-agenda", noms, "le nouvel agenda a pris le relais")

    def test_ancien_agenda_pas_encore_remplace(self):
        (self.d.home / ".local/share/smoky-agenda").mkdir(parents=True)
        (self.d.home / ".local/share/smoky-agenda/agenda.json").write_text("{}")
        self.assertEqual(self.lancer(), "smoky : 0 rappel(s) préparé(s)\n")
        self.assertIn(["ancien-agenda", "--reminders"], self.d.commandes())

    def test_sans_ancien_agenda(self):
        self.lancer()
        self.assertNotIn("ancien-agenda", [c[0] for c in self.d.commandes()])


# --- Installation -------------------------------------------------------------------------------------
class TestInstallation(unittest.TestCase):
    def test_service_des_rappels(self):
        unite = (RACINE / "usr/lib/systemd/user/smoky-agenda-reminders.service").read_text()
        self.assertIn("ExecStart=/usr/bin/python3 -I /usr/lib/smoky/lancer.py --rappels\n", unite)
        self.assertIn("ConditionPathExists=|%h/.local/share/smoky/smoky.db\n", unite)
        self.assertIn("ConditionPathExists=|%h/.local/share/smoky-agenda/agenda.json\n", unite)
        self.assertTrue((RACINE / "usr/lib/systemd/user/smoky-agenda-reminders.timer").is_file(), "même nom qu'avant")

    def test_raccourcis(self):
        smoky = (RACINE / "usr/share/applications/smoky.desktop").read_text()
        self.assertIn("[Desktop Action agenda]\nName=Agenda\nExec=/usr/bin/smoky --aller /agenda\n", smoky)
        self.assertIn("Actions=agenda;systeme;", smoky)
        ancien = (RACINE / "usr/share/applications/smoky-agenda.desktop").read_text()
        self.assertIn("Name=Smoky Agenda (ancien)\n", ancien)
        self.assertIn("Exec=/usr/bin/smoky-agenda\n", ancien, "l'ancien reste lançable, sous le même nom de fichier")


if __name__ == "__main__":
    unittest.main(verbosity=1)
