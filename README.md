# Smoky OS — ta distrib Linux perso pour ROG Flow Z13 (GZ301ZE)

Une image **Fedora bootc** (Wayland) avec le **bureau Smoky**, écrit pour toi, préparée pour ton Z13, à côté de Windows
(double démarrage). Le système est « atomique » : chaque mise à jour remplace l'image
complète, et la version précédente reste dans le menu de démarrage en cas de souci.

## Ce qu'il y a dedans
| Besoin | Solution |
|---|---|
| Tactile, stylet, mode tablette | Bureau Smoky sur labwc : vrai tactile dans les applis (zoom à deux doigts), stylet relié à l'écran, mode tablette (réglages rapides) avec rotation de l'écran ; clavier à l'écran dès que le clavier est détaché, et clavier tactile intégré à l'écran de connexion et au verrouillage |
| Chrome | Google Chrome, réglé pour Wayland et le décodage vidéo par la puce Intel |
| Netflix, Disney+, Prime Video, TF1+, M6+, Spotify, WhatsApp | Applis web dans le dock (il n'existe pas d'appli WhatsApp officielle pour Linux) |
| Maison | **Smoky Home** : robot Xiaomi X20 Max avec la carte, lumières Tapo, Google Home Mini et Nest Hub (Home Assistant + dreame-vacuum + Xiaomi Home, versions figées) |
| Proton VPN, Déjà Dup, mpv | Applis officielles (Flatpak), installées au 1er démarrage |
| Moodle, Google Drive | Applis dans le dock + Drive dans Fichiers (Paramètres > Comptes en ligne) |
| Claude | Appli Claude dans le dock |
| Optimisation Z13 | asusctl / supergfxctl, RTX coupée (autonomie), charge limitée à 80 %, thermald, codecs, mises à jour auto ; moins de réveils du processeur au repos ; consommation et autonomie estimée en direct dans Smoky → Système → Énergie, mesure détaillée par `smoky-diagnostic --energie` |
| Prise de notes façon GoodNotes | **Notes**, dans l'appli Smoky : bibliothèque de carnets avec couvertures, classeurs (une pile par matière), favoris, recherche et corbeille ; papiers vierge, ligné, quadrillé, pointillé, Seyès, Cornell, portées (blanc, ivoire, cendre, fumée ; A4, A4 paysage, écran) ; stylo sensible à la pression, surligneur, gomme (trait entier ou précise), bout gomme du stylet ; lasso (déplacer, agrandir, recolorer, copier, dupliquer) ; formes parfaites en maintenant le stylet ; texte, images, pointeur laser ; un PDF de cours devient un carnet à annoter ; export PDF dans Notes/PDF ; signets et miniatures des pages ; défilement et zoom aux doigts, toucher à 2 doigts = annuler, 3 doigts = rétablir ; gribouiller sur un mot l'efface (il passe en rouge pendant le gribouillis) ; rejet de la paume ; enregistrement automatique dans Notes/Carnets (synchronisé avec Google Drive), une page modifiée ailleurs se met à jour toute seule. Les carnets d'avant restent dans l'ancien Smoky Notes (grille des applis, « ancien »), sans changement |
| Bureau Smoky | Écrit pour Smoky OS (Python + GTK 4, `/usr/lib/smoky/smokybureau`) à la place de GNOME : barre (heure, batterie avec temps restant, réseau, son), dock qui se cache sous les fenêtres (repris de ton dock GNOME à la première connexion), lanceur avec recherche (touche Windows), réglages rapides (profil d'énergie, son, luminosité, réseaux Wi-Fi, Bluetooth, éclairage du soir, charge à 100 % une fois, ne pas mettre en veille, tablette, verrouiller, éteindre, Windows), bulles de son et de luminosité, notifications avec historique et « Ne pas déranger » ; fenêtres ouvertes en grand (règle de labwc, les boîtes de dialogue gardent leur taille) ; écran de connexion et verrouillage Smoky (bouton « Windows », relais swaylock s'il plante) ; aucun flou ni animation en continu (autonomie). Thème « fumée » noir/gris/blanc, logos Smoky-icons et curseur Smoky inchangés. Décisions et conception : `docs/refonte/` |
| Smoky (nouvelle appli unique) | **Smoky**, en tête du dock : une seule fenêtre qui regroupera toutes les applis maison. Déjà là : **Aujourd'hui** (tâches avec date limite, ta journée, état du PC, mise à jour prête), **Notes**, **Agenda** et **Mail** (voir plus bas) et **Système** (tous les réglages de Smoky Center, rangés en dix sections). Maison arrive ensuite ; d'ici là, son bouton ouvre l'ancienne appli. Serveur local sans dépendance (127.0.0.1, code d'accès tiré à chaque lancement), arrêté tout seul quand la fenêtre se ferme |
| Smoky Center (ancien) | Une seule appli de réglages : batterie (limite de charge), profil d'énergie, carte graphique, mode tablette, Moodle, concentration, maison, VPN, sauvegardes, logos, mises à jour ; écran (veilleuse, luminosité auto, rotation, taille du texte), veille et verrouillage, ne pas déranger, son au-delà de 100 %, confidentialité (caméra, localisation, fichiers récents, corbeille auto), dock et pavé tactile, stockage avec nettoyage en un clic, mise à jour des applis, infos système, « Redémarrer sur Windows » et « UEFI » (une seule fois) |
| Cours Moodle (en pause) | **En pause depuis le 22/11/2026** : plus aucun import (ni cours, ni échéances) en attendant que la partie Cours de l'appli Smoky soit refaite ; le fichier `/usr/share/smokyos/moodle-en-pause` le décide, le retirer relance tout. Quand Moodle tourne : connexion une fois avec ton identifiant et ton mot de passe UPHF (Système > Cours), le mot de passe n'est **jamais** enregistré (seul le jeton Moodle est rangé dans le trousseau GNOME) ; toutes les 2 h, les nouveaux PDF de tes cours arrivent en carnets annotables, rangés par matière. Les cours déjà importés restent dans l'ancien Smoky Notes |
| Échéances | Devoirs et tests Moodle « À rendre » dans l'Agenda, notification 36 h avant, et fichier Notes/« Moodle - échéances.ics » importable dans Google Agenda (pas de mise à jour tant que Moodle est en pause) |
| Enregistrement audio | Bouton micro dans les Notes : l'audio est lié à l'écriture ; outil « écouter » : touche un mot, la lecture repart au moment où tu l'as écrit |
| Concentration | Pomodoro (25 min par défaut) qui bloque YouTube, TikTok, Instagram, réseaux et streaming le temps de la session (liste : /etc/smokyos/focus-sites.conf) |
| Adaptation automatique | 120 Hz sur secteur, 60 Hz sur batterie ; bouton « Tablette » dans le menu en haut à droite (et dans Smoky Center) : grandes icônes, clavier à l'écran, proposition d'ouvrir les notes |
| Maison dans les réglages rapides | Bouton « Maison » dans le menu en haut à droite : lumières et robot (démarrer, pause, base) |
| VPN Wi-Fi public | Appli Proton VPN (gratuite) ; pour l'activation automatique, importe aussi ton fichier WireGuard Proton dans Smoky Center ; option pour l'activer tout seul sur les Wi-Fi sans mot de passe |
| Portail Wi-Fi pour un appareil | Valide la page « accepter » d'un Wi-Fi public au nom d'un appareil sans navigateur (robot, Google TV, ampoule) : le PC prend son adresse MAC le temps d'accepter |
| Sauvegardes | Déjà Dup (sauvegardes automatiques chiffrées de ton dossier personnel, vers Google Drive ou un disque) ; rappel si la dernière date de plus de 7 jours |
| Démarrage et connexion | Écran de démarrage Smoky (Plymouth) : fond « smoky » et volute argentée ; écran de connexion au même fond, champs et boutons à liseré néon blanc |
| Thème Smoky partout | Fichiers, Logiciels et les applis GTK : fond aux volutes « smoky » floutées, listes en verre fumé, interrupteurs, champs et sélection en néon blanc ; Terminal en palette « Smoky » ; fenêtres au thème Smoky de labwc ; mis à jour avec le système à chaque connexion (un thème personnel dans ~/.config/gtk-4.0/gtk.css sans la ligne « Smoky OS » est respecté) |
| Sobre pour la batterie | Le bureau ne se redessine que quand quelque chose change : heure à la minute, batterie toutes les 30 s, aucune animation en boucle |
| Mail (dans Smoky) | Toutes tes boîtes dans une seule liste : **Gmail** (mot de passe d'application), **Outlook / Hotmail** (connexion sur la page de Microsoft avec un code, une fois ton identifiant d'application créé dans le portail Microsoft Entra), **UPHF** (mot de passe de l'ENT, numéro ENT pour l'envoi) ou toute boîte IMAP. Tri **sur le PC** (aucun mail ne part vers un service) : Université, Personnes, Achats et factures, Newsletters, Notifications, Indésirable ; « Changer » corrige la catégorie d'un mail, et si tu veux celle des prochains du même expéditeur (règles dans les réglages). Lecture : le HTML s'affiche dans un cadre isolé, sans script ni image venue d'internet (pas de mouchard), avec « texte seul » ; pièces jointes à télécharger. Répondre, répondre à tous, transférer (avec les pièces jointes), écrire avec pièces jointes (25 Mo), depuis la bonne boîte ; un brouillon gardé pendant la frappe. Recherche, archivage, corbeille, non lu. Relève à l'ouverture puis toutes les 3 min ; en arrière-plan toutes les 15 min (30 sur batterie), notification seulement pour un nouveau mail de l'université ou d'une personne. Mots de passe et jetons dans le trousseau GNOME, jamais dans un fichier. Les boîtes de l'ancien Smoky Mail ne sont pas reprises : on les rajoute (il reste dans la grille des applis, « ancien », et se tait dès qu'une boîte est ajoutée ici) |
| Agenda (dans Smoky) | La semaine en grille : ton emploi du temps (lien iCal de l'ENT / ADE relu toutes les 6 h, ou fichier .ics ; un export plus récent dans Téléchargements est repris tout seul), tes examens (calendrier d'examens importé, bilan « révisées sur prévues »), tes rendez-vous et tes échéances Moodle. « Planifier ma semaine » place autour les révisions (examens qui approchent d'abord, blocs de 50 min + pauses), la salle (pas deux jours de suite, programme suivi d'une semaine à l'autre, charges notées depuis la séance), les courses, les repas et tes tâches « à caser » avant leur date limite ; ce que tu as ajouté toi-même et ce qui est fait ne bougent pas. « Avec Claude » fait organiser la semaine par Claude avec ton compte (blocs vérifiés : jamais par-dessus un cours) ; le compte se connecte depuis les réglages de l'agenda. Rappel avant chaque élément et ménage du robot pendant les cours, préparés à l'avance (aucun programme ne tourne en attendant) ; concentration depuis une révision, notes de la matière depuis un cours ou une révision ; « ta journée » dans Aujourd'hui ; planning copié dans Notes/Planning Smoky.ics. Sur petit écran, un jour à la fois. L'ancien Smoky Agenda reste dans la grille des applis (« ancien ») et garde ses rappels tant que le nouvel agenda n'a pas ton emploi du temps ; un bouton reprend son lien et son fichier |
| Notes sauvegardées | Dossier **Notes** synchronisé avec Google Drive > « Notes Z13 » toutes les 10 min (30 min sur batterie) |

## Comment le dépôt est rangé
| Dossier | Rôle |
|---|---|
| `Containerfile.socle`, `build_files/socle/` | **Socle** : Fedora, paquets, thèmes et intégrations de tiers (versions figées), écran de démarrage. La partie lourde, refaite le lundi ou quand un de ces fichiers change |
| `Containerfile`, `build_files/smoky.sh` | **Image finale** : fichiers Smoky et réglages posés sur le socle. Rien n'y est téléchargé |
| `system_files/` | Tout ce qui est copié tel quel dans le système (applis, services, thèmes, bureau Smoky) |
| `tests/` | Vérifications : `verifier.sh` (dépôt), `test_serveurs.py` (applis), `test_smoky.py` et `test_smoky_page.py` (appli Smoky, la seconde dans un vrai Chrome), `test_agenda.py`, `test_notes.py`, `test_mail.py` et `test_mail_page.py` (le Mail, contre de faux serveurs IMAP, SMTP et Microsoft : aucune vraie boîte n'est contactée), `test_gpu.py` (carte graphique), `image/` (image construite) |
| `tools/` | Outils à lancer à la main : logos, curseurs, thème Chrome, `repair-boot.sh` |
| `chrome-theme/` | Thème Chrome, téléchargé par Chrome depuis ce dépôt (ne pas déplacer) |
| `.github/workflows/` | Construction automatique par GitHub |

Les anciennes applis Smoky (Notes, Center, Mail, Agenda) sont de petits serveurs qui n'écoutent que sur
`127.0.0.1`. Leur sécurité (jeton secret, en-tête Host, fichiers servis) est écrite une seule
fois, dans `system_files/usr/libexec/smokyos/smokyapp.py`, et leur lancement dans
`smoky-app`.

La nouvelle appli **Smoky** est rangée à part, pour remplacer les anciennes une à une :
`system_files/usr/lib/smoky/smoky/` (serveur : `serveur.py` pour la sécurité, `systeme.py` pour
les réglages, `taches.py`, `agenda.py` et `planning.py` pour l'agenda, `notes.py` pour les carnets
dans `~/Notes/Carnets`, `courrier.py` pour le mail, `base.py` pour sa mémoire SQLite dans `~/.local/share/smoky/`),
`system_files/usr/share/smoky/` (la page : HTML, CSS, modules JavaScript sans bibliothèque ; seuls
PDF.js et pdf-lib, figés dans `vendor/`, servent aux PDF des Notes) et
`system_files/usr/bin/smoky` (lanceur). Les réglages lisent et écrivent les mêmes fichiers que
Smoky Center (`~/.config/smoky/…`), si bien que l'un remplace l'autre sans rien perdre.

## Mises à jour
- **Automatiques** : chaque lundi, GitHub reconstruit tout avec les derniers correctifs de
  Fedora. Ton Z13 télécharge la nouvelle image en arrière-plan et l'applique au redémarrage
  suivant. Même chose après chaque modification envoyée sur la branche `main`.
- **Tout de suite** : Smoky Center → « Mettre à jour », puis redémarrer.
- **Légères entre deux lundis** : l'image est en deux parties. Tant que le socle ne change
  pas, une mise à jour ne fait retélécharger que les fichiers Smoky (quelques Mo).
- **Jamais sans contrôle** : avant d'être publiée, chaque image est vérifiée (une centaine de
  points : démarrage, écran de connexion, services, applis, bureau Smoky, serveurs lancés pour
  de vrai), puis installée dans une machine virtuelle et démarrée **deux fois de suite**
  jusqu'à l'écran de connexion (le démarrage qui suit une mise à jour, puis celui de tous les
  jours, avec un arrêt propre entre les deux). Si une étape échoue, rien n'est publié et ton
  PC garde sa version. Ce que ces contrôles ne voient pas : le matériel du Z13 (tactile,
  stylet, carte ASUS) et l'apparence.
- **Mesuré à chaque build** : durée du démarrage, services les plus longs, mémoire utilisée
  et services qui tournent sont relevés dans la machine virtuelle. Sur une branche de test,
  le résumé du build les compare à ceux de l'image publiée : une modification qui ralentit le
  démarrage ou ajoute un service se voit avant d'arriver sur le PC.

### Revenir en arrière
- **Pour une fois** : au démarrage, le menu (3 secondes) propose les deux dernières versions ;
  choisis la seconde. Au redémarrage suivant, le PC repart sur la plus récente.
- **Pour rester sur une version** : bascule sur son étiquette, puis redémarre. Tant que tu es
  sur une étiquette fixe, les mises à jour automatiques ne te ramènent pas à la dernière image.
  - celle d'un jour précis (chaque publication garde une étiquette à sa date) :
    `sudo bootc switch ghcr.io/smokytwt/z13os:20261110`
  - celle d'avant la refonte de novembre 2026 : `sudo bootc switch ghcr.io/smokytwt/z13os:v1`
- **Pour reprendre les mises à jour normales** : `sudo bootc switch ghcr.io/smokytwt/z13os:latest`.

Une mise à jour ne touche ni à Windows, ni aux partitions, ni à ton dossier personnel.

### Demander de l'aide : `smoky-diagnostic`
Dans un terminal, `smoky-diagnostic` affiche l'état du PC en une page : version, carte
graphique, durée du démarrage, mémoire, batterie, disque, erreurs récentes. Il ne modifie
rien et ne demande aucun mot de passe. Les chemins de ton dossier personnel, les adresses
(e-mail, IP, MAC) et ce qui ressemble à un code d'accès sont masqués ; relis quand même le
rapport avant de le partager. Pour l'avoir dans un fichier : `smoky-diagnostic > ~/diagnostic.txt`.

Pour l'autonomie : `smoky-diagnostic --energie`, sur batterie, sans toucher au PC pendant une
minute. Il donne la consommation moyenne, l'autonomie qu'elle laisse (batterie pleine et jusqu'à
la limite de charge), les réglages qui comptent (luminosité, fréquence de l'écran, profil
d'énergie, turbo, veille des liaisons PCIe, carte NVIDIA, Wi-Fi) et ce qui a fait travailler le
processeur. `sudo smoky-diagnostic --energie-paquet` ajoute le repos du processeur entier, le
chiffre le plus parlant quand la batterie fond au repos.

## Modifier Smoky OS
1. Modifie les fichiers, puis lance `bash tests/verifier.sh` (moins d'une minute).
2. Envoie sur `main` : GitHub construit, vérifie, démarre l'image dans une machine virtuelle
   puis publie (`build-image`, environ 10 minutes, 15 quand le socle est refait).
   État : `gh run list -R SmokyTwT/z13os`.
3. **Pour essayer sans risque** : envoie sur une autre branche, puis lance `build-image` sur
   cette branche (Actions → build-image → Run workflow). L'image part sur l'étiquette `test`,
   jamais sur `latest`, et le résumé du build liste ce qui diffère de l'image publiée.
- **Ajouter un paquet** : `build_files/socle/10-paquets.sh` (liste `PAQUETS`). Une appli
  graphique s'installe plutôt par l'app *Logiciels* (Flatpak), sans toucher à l'image.
- **Mettre à jour un fichier de tiers** (icônes WhiteSur, intégrations du robot) : remplace sa
  révision dans `build_files/socle/20-tiers.sh` après avoir relu ce qui a changé.
- **Changer d'adresse Moodle** : variable `MOODLE_URL` dans *Settings → Secrets and variables
  → Actions → Variables* (par défaut : `https://moodle.uphf.fr/`).

## Obtenir l'ISO (clé USB d'installation)
L'ISO ne sert qu'à installer ou réinstaller. GitHub la refait après la construction du lundi.
Pour en avoir une tout de suite : onglet **Actions** → `build-iso` → *Run workflow* (environ
15 min), puis télécharge **smokyos-iso** dans l'exécution terminée (environ 4 Go, gardée
14 jours).

Pour partir de zéro sur un autre compte GitHub : crée un dépôt **public** `z13os`, envoie tout
ce dossier (y compris `.github`), lance `build-image`, puis rends le paquet public
(*Your profile → Packages → z13os → Package settings*), sans quoi le PC ne peut pas
télécharger les mises à jour.

## Installer sur le Z13
1. **Sous Windows d'abord** : mets à jour le BIOS avec MyASUS et **sauvegarde tes fichiers**.
2. Copie `smokyos.iso` sur une clé USB (8 Go ou plus) avec **Fedora Media Writer** ou
   **balenaEtcher** (option « image personnalisée »).
3. Allume le Z13 en maintenant **Échap** (ou **F2** → Boot), puis choisis la clé.
4. L'installateur demande seulement le disque.
   **Attention : « récupérer tout l'espace » efface Windows et tout le disque.** Pour garder
   Windows (double démarrage), il faut d'abord libérer de la place depuis Windows (Gestion des
   disques → Réduire le volume) et n'installer Smoky OS que dans cet espace libre.
5. Problème connu, pas encore corrigé : l'installation depuis l'ISO peut s'arrêter à l'étape
   « chargeur de démarrage ». `tools/repair-boot.sh` (à lancer depuis Smoky OS démarré) réécrit
   alors le menu de démarrage Smoky OS / Windows.
6. Au premier démarrage, connecte-toi avec le compte créé à l'installation (l'assistant de GNOME n'existe plus : à revoir pour l'ISO). Branche le Wi-Fi : Proton VPN,
   Déjà Dup et mpv s'installent tout seuls dans les minutes qui suivent.
7. Ouvre l'appli **Synchroniser mes notes avec Google Drive** et autorise l'accès (une seule
   fois). Les carnets des Notes (Notes/Carnets) et leurs exports PDF (Notes/PDF) sont dans le dossier **Notes**, donc
   synchronisés.
8. Smoky Center (carte « Système ») affiche l'état de la machine.

## Smoky Home : robot, lumières, Google Home
Appli **Smoky Home** (dans le dock). Elle repose sur Home Assistant, qui tourne en conteneur
seulement quand l'appli est ouverte (ou en arrière-plan si tu l'actives dans Smoky Center).
1. **Premier lancement** : environ 1,5 Go à télécharger, quelques minutes. Crée ensuite ton
   compte Smoky Home (local, pas en ligne).
2. **Paramètres → Appareils et services → Ajouter une intégration** :
   - **TP-Link Smart Home** : identifiants de l'appli Tapo, puis les ampoules apparaissent.
   - **Xiaomi Home** (intégration officielle, celle du **X20 Max**) : connecte ton compte
     Xiaomi et sélectionne le robot. **Dreame Vacuum** est fournie aussi, pour les robots
     qu'elle reconnaît (carte en direct, pièces, zones).
   - **Google Cast** : le Google Home Mini et le Nest Hub sont détectés tout seuls (volume,
     musique, annonces, affichage sur le Hub).
3. Le tableau de bord montre tout automatiquement, dans le thème Smoky.

**Accès depuis le réseau** : le pare-feu de Smoky OS bloque le port de Smoky Home (8123) sur
tous les réseaux, donc seul ce PC peut l'ouvrir. Home Assistant, lui, écoute par défaut sur
toutes les adresses. Pour qu'il n'écoute vraiment que ce PC : Smoky Home → Paramètres →
Système → Réseau → serveur HTTP → adresses d'écoute (*Settings → System → Network → Listen
addresses*) : `127.0.0.1`. Home Assistant te demande de confirmer dans les 5 minutes, sinon il
revient au réglage d'avant.

### Robot sur un Wi-Fi public (page « accepter »)
Le robot n'a pas de navigateur pour accepter la page du Wi-Fi public. Ouvre l'appli
**Portail Wi-Fi pour un appareil** :
1. Donne l'adresse MAC du robot (Xiaomi Home → robot → Paramètres → Infos réseau). Elle est
   retenue pour la prochaine fois. Éteins le robot s'il était déjà sur ce Wi-Fi.
2. Choisis le Wi-Fi public : le PC s'y connecte avec l'adresse du robot, et tu acceptes la page.
3. Le PC reprend sa propre adresse. Tu connectes le robot à ce Wi-Fi depuis Xiaomi Home : il a
   Internet.

Ensuite, le robot (avec la carte) se pilote de n'importe où : appli Xiaomi Home ou Smoky Home.
Si le portail expire, relance l'outil.

## À savoir (honnêtement)
- **Streaming** : Netflix, Disney+ et Prime Video limitent Chrome sous Linux à environ **720p**.
  C'est une limite côté plateformes, on ne peut pas la contourner. TF1+ et M6+ ne sont pas
  concernés.
- **Claude Desktop** n'existe pas sous Linux : tu as l'appli Claude (web) dans le dock.
- **RTX 3050 Ti** : coupée par défaut (Smoky Center > Carte graphique pour la rallumer, avec le
  pilote libre). Pas de pilote NVIDIA propriétaire : inutile pour les cours et le streaming.
- **Moodle** : si la connexion par identifiant est refusée (connexion UPHF via CAS), Smoky Center
  ouvre automatiquement la page de connexion de l'université, et le jeton revient tout seul.
- **Nom du PC** : l'image ne le règle pas. Le PC garde le nom choisi à l'installation ou dans
  Paramètres → Système → À propos → Nom de l'appareil.
- **Redémarrer sur Windows** : le firmware ASUS refuse parfois qu'on lui indique le prochain
  système à démarrer. Smoky Center passe alors par le menu de démarrage (GRUB), une seule fois.
- **Mode Ultimate de Windows** (Armoury Crate) : c'est un réglage du firmware, il reste donc en
  place quand on revient sur Smoky OS, et l'écran serait relié à la carte NVIDIA. Smoky OS le
  voit au démarrage, rend l'écran à la puce Intel et **redémarre une fois tout seul** (une
  trentaine de secondes) ; ensuite tout démarre directement. En repartant par « Redémarrer sur
  Windows » (Smoky Center), le mode Ultimate est remis : Windows le retrouve sans rien faire.
  Si tu choisis Windows dans le menu de démarrage, Smoky OS n'a rien pu préparer : Windows
  démarre en mode Standard. Réglages : `/etc/smokyos/gpu.conf` ; état :
  `python3 /usr/libexec/smokyos/smokygpu.py etat`. Garde-fous : un seul redémarrage automatique
  par démarrage, deux essais au plus, et rien du tout si le firmware répond de travers.

## Autonomie et durée de vie de la batterie
- **Limite de charge à 80 %** (plus de cycles avant usure) ; bouton « Charger à 100 % pour cette
  fois » dans Smoky Center : la limite revient toute seule au débranchement.
- **Débranché** : écran à 60 Hz, « Performance » repasse en « Équilibré » (et revient au
  rebranchement), RTX coupée par défaut, Wi-Fi en économie d'énergie, Chrome en économiseur de
  batterie sous 20 %.
- **Rien ne tourne pour rien** : le serveur de l'appli Smoky (et ceux des anciennes applis)
  s'arrêtent avec leur fenêtre ; Chrome ne reste pas en arrière-plan ; synchro des notes
  toutes les 10 min (30 sur batterie), relève des mails 15 min (30 sur batterie) ; mises à jour
  des applis une fois par jour et seulement sur secteur ; GNOME Logiciels, ROG Control Center
  et ModemManager ne tournent plus en permanence ; le service de premier démarrage ne
  demande plus le réseau à chaque allumage (seulement quand il a des applis à installer).

## Sécurité, stabilité, légèreté
- **Secure Boot compatible** : Smoky OS garde le noyau et le chargeur de démarrage signés de
  Fedora, et n'ajoute aucun pilote non signé (pas de pilote NVIDIA propriétaire). Windows
  continue de démarrer normalement à côté.
- **Noyau durci** : un programme ne peut plus lire la mémoire d'un autre, pas de remplacement du
  noyau à chaud, redirections réseau ignorées (Wi-Fi publics).
- **Pare-feu en zone « public »** : rien n'est joignable depuis le réseau (Wi-Fi publics
  compris, ssh fermé), sauf la découverte des Google Home/Chromecast. Les applis Smoky
  n'écoutent que sur `127.0.0.1`.
- **Mots de passe** : ceux des boîtes mail et le jeton Moodle sont rangés dans le trousseau
  GNOME (à défaut de trousseau, dans un fichier lisible par toi seul) ; le mot de passe Moodle
  n'est jamais enregistré.
- **Versions figées** : thèmes WhiteSur, intégrations du robot (révision git) et moteur de
  Smoky Home (empreinte sha256) ; bibliothèques PDF des Notes (PDF.js 6.3.289, pdf-lib 1.17.1) copiées dans le dépôt.
- **Moodle** : connexion en HTTPS uniquement, le jeton n'est jamais envoyé à un autre site que
  Moodle (liens externes dans les cours ignorés), téléchargements limités à 200 Mo.
- **Mode concentration** : le service qui modifie /etc/hosts tourne dans un bac à sable (pas de
  réseau, pas d'accès au dossier personnel, seul /etc est modifiable).
- **Allégé** : pas de Firefox (Chrome suffit), pas de visite guidée, pas de variantes d'icônes
  inutiles ; Smoky Home ne tourne que quand l'appli est ouverte.
- **Rien d'inutile au démarrage** : Fedora refait le catalogue des logiciels et l'index des
  pages de manuel à chaque allumage ; Smoky OS ne les refait qu'une fois par image (après une
  mise à jour). Pour voir ce qui prend du temps sur ton PC : `smoky-diagnostic`.
- **Mémoire pleine** : Fedora compresse en mémoire ce qui sert le moins (zram) au lieu de
  l'écrire sur le disque. Smoky OS règle le noyau en conséquence (`vm.swappiness=180`,
  `vm.page-cluster=0`, fichier `/usr/lib/udev/rules.d/71-smokyos-zram.rules`) : sans effet
  tant qu'il reste de la mémoire, moins d'à-coups quand elle est pleine.
