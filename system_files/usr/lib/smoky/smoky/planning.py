"""Planifier une semaine sur le PC, sans réseau : repas, courses, salle, tâches, révisions.

C'est l'algorithme de l'ancien Smoky Agenda, qui avait fait ses preuves ; seuls les noms ont
changé. Tout est en heure locale, à la minute près, au format « AAAA-MM-JJTHH:MM ».

Entrées de planifier() :
  debut        le lundi de la semaine (date)
  reglages     les réglages de l'agenda (agenda.REGLAGES)
  fixes        ce qui est déjà pris : cours, examens, rendez-vous, échéances, blocs gardés
               ({genre, debut, fin, journee, matiere?})
  examens      les examens à venir ({titre, debut, journee, matiere?})
  salle_avant  les séances de salle déjà passées ou gardées, avant cette semaine
  taches       les tâches à caser ({id, titre, minutes, echeance?})
  matiere_de   fonction : titre → matière (ou None)
  maintenant   l'heure actuelle (rien n'est placé dans le passé)
Sortie : des blocs {genre, titre, debut, fin, matiere?, tache?, notes?}.
"""
import re
from datetime import datetime, timedelta

# programme proposé tant que tu n'as pas écrit le tien (Réglages de l'agenda → Salle de sport)
PROGRAMME = """Pecs et bras
Développé décliné
Chest press (mouvement avant bras, ou normal)
Chest press sur le côté
Biceps poulie marteau + triceps (superset)
Spider curl
Poulie droite
Poulie basse bras en arrière (biceps)
Avant-bras

Dos, épaules et abdos
Tirage machine
Tirage horizontal machine
Poulie verticale prise serrée
Épaules machine
Élévations latérales + superset allongé
Poulie : élévation bras droit + élévations latérales
Abdos : poulie, pendu + élévations de genoux au sol"""


def hm(texte):
    h, m = map(int, texte.split(":"))
    return h * 60 + m


def a_minute(jour, minutes):
    return datetime.combine(jour, datetime.min.time()) + timedelta(minutes=minutes)


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M")


def lire_iso(texte):
    return datetime.strptime(texte[:16], "%Y-%m-%dT%H:%M")


def seances(programme):
    """Séances d'un programme : un paragraphe par séance, la 1re ligne est son nom."""
    out = []
    for paragraphe in re.split(r"\n\s*\n", (programme or PROGRAMME).strip()):
        lignes = [ligne.strip() for ligne in paragraphe.splitlines() if ligne.strip()]
        if lignes:
            out.append({"nom": lignes[0][:60], "exercices": lignes[1:30]})
    return out


class Journee:
    """Créneaux libres d'une journée, en minutes depuis minuit."""

    def __init__(self, jour, reglages, pris):
        self.jour = jour
        self.libre = [(hm(reglages["reveil"]), hm(reglages["coucher"]))]
        for debut, fin in pris:
            self.prendre(debut, fin)

    def prendre(self, debut, fin):
        reste = []
        for a, b in self.libre:
            if fin <= a or debut >= b:
                reste.append((a, b))
            else:
                if debut > a:
                    reste.append((a, debut))
                if fin < b:
                    reste.append((fin, b))
        self.libre = reste

    def trouver(self, duree, des=0, avant=24 * 60, pres_de=None):
        """Premier créneau libre de « duree » minutes entre des et avant (le plus proche de « pres_de »)."""
        possibles = []
        for a, b in self.libre:
            s, e = max(a, des), min(b, avant)
            if e - s >= duree:
                if pres_de is not None and s <= pres_de <= e - duree:
                    return pres_de
                possibles.append(s if pres_de is None or pres_de < s else e - duree)
        if not possibles:
            return None
        return min(possibles, key=lambda s: abs(s - pres_de)) if pres_de is not None else possibles[0]

    def minutes_libres(self):
        return sum(b - a for a, b in self.libre)


def planifier(debut, reglages, fixes, examens, salle_avant, taches, matiere_de, maintenant):
    r = reglages
    jours = []
    for i in range(7):
        jour = debut + timedelta(days=i)
        minuit = datetime.combine(jour, datetime.min.time())
        pris = []
        for ev in fixes:
            if ev.get("journee"):
                continue
            s, e = lire_iso(ev["debut"]), lire_iso(ev["fin"])
            if e <= minuit or s >= minuit + timedelta(days=1):
                continue
            # en minutes depuis minuit ce jour-là : une soirée qui finit après minuit prend aussi le début du lendemain
            marge = r["trajet_min"] if ev["genre"] in ("cours", "examen") else 0
            pris.append((int((s - minuit).total_seconds() // 60) - marge, int((e - minuit).total_seconds() // 60) + marge))
        if jour == maintenant.date():                    # pas de planning dans le passé
            pris.append((0, maintenant.hour * 60 + maintenant.minute + 5))
        elif jour < maintenant.date():
            pris.append((0, 24 * 60))
        jours.append(Journee(jour, r, pris))
    blocs = []

    def poser(journee, s, duree, genre, titre, plus=None):
        journee.prendre(s, s + duree)
        blocs.append({"genre": genre, "titre": titre, "debut": iso(a_minute(journee.jour, s)),
                      "fin": iso(a_minute(journee.jour, s + duree)), **(plus or {})})

    # 1. repas
    for journee in jours:
        for nom, heure in (("Déjeuner", r["dejeuner"]), ("Dîner", r["diner"])):
            s = journee.trouver(r["repas_min"], hm(heure) - 45, hm(heure) + 75, pres_de=hm(heure))
            if s is not None:
                poser(journee, s, r["repas_min"], "repas", nom)

    # 2. courses
    jour_courses = jours[int(r["courses_jour"]) % 7]
    s = jour_courses.trouver(r["courses_min"], hm(r["reveil"]), hm(r["coucher"]), pres_de=hm(r["courses_heure"]))
    if s is not None:
        poser(jour_courses, s, r["courses_min"], "courses", "Courses")

    # examens à venir (pour la salle et les révisions)
    examens = sorted(examens, key=lambda e: e["debut"])
    jours_examen = {lire_iso(e["debut"]).date() for e in examens}

    # 3. salle : les jours les plus légers, jamais deux jours de suite, pas un jour d'examen si
    # possible ; les séances suivent le programme d'une semaine à l'autre
    voulu = int(r["salle_par_semaine"])
    programme = seances(r["programme"])
    sans_examen = sorted((j for j in jours if j.jour not in jours_examen), key=lambda j: -j.minutes_libres())
    avant = sorted((b for b in salle_avant if lire_iso(b["debut"]).date() < debut), key=lambda b: b["debut"])
    derniere = lire_iso(avant[-1]["debut"]).date() if avant else None
    choisis = []
    # jours sans examen d'abord, puis (s'il le faut) le soir d'un jour d'examen ; jamais deux jours
    # de suite : mieux vaut une séance de moins que des muscles qui ne récupèrent pas
    for groupe in (sans_examen, [j for j in jours if j.jour in jours_examen]):
        for journee in groupe:
            if len(choisis) >= voulu:
                break
            if (journee in choisis or any(abs((journee.jour - c.jour).days) == 1 for c in choisis)
                    or (derniere and (journee.jour - derniere).days == 1)):
                continue
            s = journee.trouver(r["salle_min"], hm(r["salle_des"]), hm(r["salle_avant"]))
            if s is not None:
                choisis.append(journee)
                poser(journee, s, r["salle_min"], "salle", "Salle de sport")
    if programme:                                        # dans l'ordre des jours, à la suite de la semaine d'avant
        noms = [x["nom"] for x in programme]
        precedente = avant[-1]["titre"].split(":", 1)[-1].strip() if avant else None
        premiere = noms.index(precedente) + 1 if precedente in noms else 0
        for i, b in enumerate(sorted((b for b in blocs if b["genre"] == "salle"), key=lambda b: b["debut"])):
            seance = programme[(premiere + i) % len(programme)]
            b["titre"] = f"Salle : {seance['nom']}"
            b["notes"] = "\n".join(seance["exercices"])

    # 4. tâches à caser avant leur date limite (la plus urgente d'abord)
    for t in sorted(taches, key=lambda t: t.get("echeance") or "9999"):
        duree = int(t["minutes"])
        limite = datetime.strptime(t["echeance"], "%Y-%m-%d").date() if t.get("echeance") else debut + timedelta(days=6)
        for journee in jours:
            if journee.jour > limite:
                break
            s = journee.trouver(duree, hm(r["reveil"]), hm(r["coucher"]))
            if s is not None:
                poser(journee, s, duree, "tache", t["titre"], {"tache": t["id"]})
                break

    # 5. révisions : d'abord les examens qui approchent (toutes leurs matières, et d'autant plus
    # souvent que l'examen est proche ; le matin d'un examen, sa matière en premier), puis les
    # matières des échéances Moodle, puis les matières tour à tour
    matieres = [x for x in r["matieres"] if x] or ["Cours de la semaine"]
    urgentes = [ev["matiere"] for ev in fixes if ev["genre"] == "devoir" and ev.get("matiere")]
    tour = urgentes + matieres
    n = 0
    donnes = {}                                          # blocs déjà donnés à chaque matière
    for journee in jours:
        proches = []                                     # (jours restants, matière) des 14 prochains jours
        for e in examens:
            reste = (lire_iso(e["debut"]).date() - journee.jour).days
            matiere = e.get("matiere") or matiere_de(e["titre"])
            if 0 <= reste <= 14 and matiere and matiere not in [p[1] for p in proches]:
                proches.append((reste, matiere))
        cible = r["revision_weekend_min"] if journee.jour.weekday() >= 5 else r["revision_semaine_min"]
        if proches and proches[0][0] <= 7:               # semaine d'examens : moitié plus de révisions
            cible = int(cible * 1.5)
        # poids : examen du jour 6, veille 4, puis de moins en moins ; le bloc va à la matière la plus
        # « en retard » par rapport à son poids, pour que toutes soient révisées
        poids = {m: 6 if reste == 0 else 4 if reste == 1 else max(1.0, 8 / reste) for reste, m in proches}
        # heure de l'examen du jour : sa matière n'est révisée qu'avant
        examen_a = {(e.get("matiere") or matiere_de(e["titre"])): hm(e["debut"][11:16]) for e in examens
                    if not e.get("journee") and lire_iso(e["debut"]).date() == journee.jour}
        fait, bloc = 0, int(r["bloc_min"])
        deja = set()
        while fait + bloc <= cible:
            s = journee.trouver(bloc, hm(r["reveil"]) + 30, hm(r["coucher"]) - 60)
            if s is None:
                break
            if poids:
                # le matin d'un examen : un dernier bloc sur sa matière avant tout le reste
                avant_examen = [x for x in examen_a if x in poids and x not in deja]
                matiere = avant_examen[0] if avant_examen else max(poids, key=lambda x: poids[x] / (donnes.get(x, 0) + 1))
                if matiere in examen_a and s + bloc > examen_a[matiere] - 30:   # examen passé ou trop proche
                    del poids[matiere]
                    continue
                donnes[matiere] = donnes.get(matiere, 0) + 1
                deja.add(matiere)
            else:                                        # pas la matière d'un examen passé le jour même
                choix = [x for x in tour if x not in examen_a] or tour
                matiere = choix[n % len(choix)]
                n += 1
            poser(journee, s, bloc, "revision", f"Révision : {matiere}", {"matiere": matiere})
            journee.prendre(s + bloc, s + bloc + 10)     # pause de 10 min
            fait += bloc
    return blocs
