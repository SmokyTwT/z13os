# Smoky OS — ta distrib Linux perso pour ROG Flow Z13 (GZ301ZE)

Une image **Fedora Silverblue** (GNOME / Wayland) préparée pour ton Z13, à côté de Windows
(double démarrage). Le système est « atomique » : chaque mise à jour remplace l'image
complète, et la version précédente reste dans le menu de démarrage en cas de souci.

## Ce qu'il y a dedans
| Besoin | Solution |
|---|---|
| Tactile, stylet, mode tablette | GNOME Wayland : gestes, clavier virtuel, rotation auto |
| Chrome | Google Chrome, réglé pour Wayland et le décodage vidéo par la puce Intel |
| Netflix, Disney+, Prime Video, TF1+, M6+, Spotify, WhatsApp | Applis web dans le dock (il n'existe pas d'appli WhatsApp officielle pour Linux) |
| Maison | **Smoky Home** : robot Xiaomi X20 Max avec la carte, lumières Tapo, Google Home Mini et Nest Hub (Home Assistant + dreame-vacuum + Xiaomi Home, versions figées) |
| Proton VPN, Déjà Dup, mpv | Applis officielles (Flatpak), installées au 1er démarrage |
| Moodle, Google Drive | Applis dans le dock + Drive dans Fichiers (Paramètres > Comptes en ligne) |
| Claude | Appli Claude dans le dock |
| Optimisation Z13 | asusctl / supergfxctl, RTX coupée (autonomie), charge limitée à 80 %, thermald, codecs, mises à jour auto |
| Prise de notes façon GoodNotes | **Smoky Notes**, appli maison : bibliothèque de carnets avec couvertures, classeurs et favoris ; papiers ligné, quadrillé, pointillé, Cornell, Seyès, portées (blanc, ivoire, cendre, fumée) ; stylo sensible à la pression, surligneur, gomme (trait entier ou précise), bout gomme du stylet ; lasso (déplacer, agrandir, recolorer, copier, dupliquer) ; formes parfaites en maintenant le stylet ; texte, images, pointeur laser ; import de PDF à annoter ; export PDF vectoriel dans Notes/PDF ; signets et miniatures des pages ; zoom à deux doigts, toucher à 2 doigts = annuler, 3 doigts = rétablir ; gribouiller sur un mot avec le stylo l'efface (le mot passe en rouge pendant le gribouillis : on voit ce qui va partir) ; rejet de la paume ; tout est enregistré dans Notes/Smoky Notes (synchronisé avec Google Drive) |
| Interface Smoky | Applis ouvertes en grand automatiquement (extension maison « smoky-maximize », les boîtes de dialogue gardent leur taille) ; dock flottant en verre fumé (liseré argenté, ombre, survol lumineux, bulles assorties), flou *statique* sur la barre et le dock (calculé une fois, ~0 % de batterie), icônes et curseurs WhiteSur (versions figées) pour toutes les applis, y compris le streaming, grands boutons tactiles dans le centre de contrôle, Caffeine (anti-veille), boutons de fenêtre à gauche, thème « fumée » noir/gris/blanc : fond d'écran « smoky » en volutes argentées ; tout le système suit ce style : applis GNOME en noir et argent, dock en verre fumé à liseré argenté, logos Smoky (thème d'icônes « Smoky-icons ») : chaque appli reçoit la version Smoky de son vrai logo (argent, carré noir, trait néon à sa couleur), y compris les applis installées plus tard (smoky-autoicons) ; TF1+, M6+, Moodle et Smoky Notes sont dessinés à la main (tools/make-icons.py), curseur « Smoky » : point blanc néon, anneau sur les liens, volute animée pendant le chargement (tools/make-cursors.py), fenêtres à contour argenté et boutons fermer/réduire/agrandir en blanc néon, Chrome et applis web en sombre, applis Flatpak au thème (version claire et sombre, mode sombre par défaut), centre de contrôle où les boutons actifs s'allument en blanc |
| Smoky Center | Une seule appli de réglages : batterie (limite de charge), profil d'énergie, carte graphique, mode tablette, Moodle, concentration, maison, VPN, sauvegardes, logos, mises à jour ; écran (veilleuse, luminosité auto, rotation, taille du texte), veille et verrouillage, ne pas déranger, son au-delà de 100 %, confidentialité (caméra, localisation, fichiers récents, corbeille auto), dock et pavé tactile, stockage avec nettoyage en un clic, mise à jour des applis, infos système, « Redémarrer sur Windows » et « UEFI » (une seule fois) |
| Cours Moodle → Smoky Notes | Connexion une fois avec ton identifiant et ton mot de passe UPHF (Smoky Center > Cours). Le mot de passe n'est **jamais** enregistré : seul le jeton Moodle est rangé dans le trousseau GNOME. Toutes les 2 h, les nouveaux PDF de tes cours arrivent en carnets annotables, rangés par matière. Un carnet déjà annoté n'est jamais écrasé : la nouvelle version arrive à côté |
| Échéances | Devoirs et tests Moodle en pastilles « À rendre » dans Smoky Notes, notification 36 h avant, et fichier Notes/« Moodle - échéances.ics » importable dans Google Agenda |
| Enregistrement audio | Bouton micro dans Smoky Notes : l'audio est lié à l'écriture ; outil « écouter » : touche un mot, la lecture repart au moment où tu l'as écrit |
| Concentration | Pomodoro (25 min par défaut) qui bloque YouTube, TikTok, Instagram, réseaux et streaming le temps de la session (liste : /etc/smokyos/focus-sites.conf) |
| Adaptation automatique | 120 Hz sur secteur, 60 Hz sur batterie ; bouton « Tablette » dans le menu en haut à droite (et dans Smoky Center) : grandes icônes, clavier à l'écran, proposition d'ouvrir Smoky Notes |
| Maison dans les réglages rapides | Bouton « Maison » dans le menu en haut à droite : lumières et robot (démarrer, pause, base) |
| VPN Wi-Fi public | Appli Proton VPN (gratuite) ; pour l'activation automatique, importe aussi ton fichier WireGuard Proton dans Smoky Center ; option pour l'activer tout seul sur les Wi-Fi sans mot de passe |
| Portail Wi-Fi pour un appareil | Valide la page « accepter » d'un Wi-Fi public au nom d'un appareil sans navigateur (robot, Google TV, ampoule) : le PC prend son adresse MAC le temps d'accepter |
| Sauvegardes | Déjà Dup (sauvegardes automatiques chiffrées de ton dossier personnel, vers Google Drive ou un disque) ; rappel si la dernière date de plus de 7 jours |
| Démarrage et connexion | Écran de démarrage Smoky (Plymouth) : fond « smoky » et volute argentée ; écran de connexion au même fond, champs et boutons à liseré néon blanc |
| Thème Smoky partout | Paramètres, Fichiers, Logiciels et toutes les applis GNOME : fond aux volutes « smoky » floutées, barre latérale et listes en verre fumé, interrupteurs, champs et sélection en néon blanc ; Terminal en palette « Smoky » ; mis à jour avec le système à chaque connexion (un thème personnel dans ~/.config/gtk-4.0/gtk.css sans la ligne « Smoky OS » est respecté) |
| Animations légères | Transitions courtes au survol et au clic (bureau, dock, centre de contrôle, connexion, applis GNOME), apparition en fondu des menus et notifications, cartes de Smoky Center en cascade à l'ouverture, ouvertures douces dans Smoky Notes ; uniquement opacité, couleurs et halos (calculés par la puce graphique), jamais en boucle ; tout se coupe avec « Animations » dans Smoky Center |
| Smoky Mail | Toutes tes boîtes (Gmail, Outlook/Hotmail, Orange, Free, UPHF ou tout serveur IMAP) dans une seule liste, au thème Smoky ; Outlook se connecte par la page officielle de Microsoft (code à saisir, une fois l'identifiant d'application créé sur portal.azure.com) ; réponse depuis la bonne boîte : lecture, réponse, archivage, corbeille, recherche. **Claude trie automatiquement** chaque nouveau mail (Important, Cours et université, Personnel, Achats, Newsletters, Notifications, Indésirable) avec un résumé d'une ligne et un repère « à faire » ; notification pour les mails importants, relève toutes les 15 min. Tri par Claude avec ton compte Claude (le même que l'appli, forfait Pro ou Max) via Claude Code, l'outil officiel d'Anthropic, installé en un clic depuis les réglages : pas de clé d'API, rien à payer en plus ; Claude n'y a aucun outil (ni fichiers, ni Internet) ; sans Claude, tri simple sur le PC. Mot de passe dans le trousseau, images distantes (pisteurs) bloquées, scripts des mails jamais exécutés |
| Smoky Agenda | Planifie tes journées : ton emploi du temps (lien iCal de l'ENT / ADE, ou fichier .ics importé) et tes échéances Moodle s'affichent tout seuls ; « Planifier ma semaine » place autour les révisions (matières dont une échéance approche d'abord, blocs de 50 min + pauses), la salle (pas deux jours de suite), les courses, les repas et tes tâches avant leur date limite ; « ✨ Avec Claude » fait organiser la semaine par Claude avec ton compte (blocs vérifiés : jamais par-dessus un cours) ; rappel avant chaque bloc (préparé à l'avance, aucun programme ne tourne en attendant) ; bouton « Concentration » sur les révisions ; planning copié dans Notes/Planning Smoky.ics |
| Notes sauvegardées | Dossier **Notes** synchronisé avec Google Drive > « Notes Z13 » toutes les 10 min (30 min sur batterie) |

## Comment le dépôt est rangé
| Dossier | Rôle |
|---|---|
| `Containerfile.socle`, `build_files/socle/` | **Socle** : Fedora, paquets, thèmes et intégrations de tiers (versions figées), écran de démarrage. La partie lourde, refaite le lundi ou quand un de ces fichiers change |
| `Containerfile`, `build_files/smoky.sh` | **Image finale** : fichiers Smoky et réglages posés sur le socle. Rien n'y est téléchargé |
| `system_files/` | Tout ce qui est copié tel quel dans le système (applis, services, thèmes, extensions) |
| `tests/` | Vérifications : `verifier.sh` (dépôt), `test_serveurs.py` (applis), `image/` (image construite) |
| `tools/` | Outils à lancer à la main : logos, curseurs, thème Chrome, `repair-boot.sh` |
| `chrome-theme/` | Thème Chrome, téléchargé par Chrome depuis ce dépôt (ne pas déplacer) |
| `.github/workflows/` | Construction automatique par GitHub |

Les applis Smoky (Notes, Center, Mail, Agenda) sont de petits serveurs qui n'écoutent que sur
`127.0.0.1`. Leur sécurité (jeton secret, en-tête Host, fichiers servis) est écrite une seule
fois, dans `system_files/usr/libexec/smokyos/smokyapp.py`, et leur lancement dans
`smoky-app`.

## Mises à jour
- **Automatiques** : chaque lundi, GitHub reconstruit tout avec les derniers correctifs de
  Fedora. Ton Z13 télécharge la nouvelle image en arrière-plan et l'applique au redémarrage
  suivant. Même chose après chaque modification envoyée sur la branche `main`.
- **Tout de suite** : Smoky Center → « Mettre à jour », puis redémarrer.
- **Légères entre deux lundis** : l'image est en deux parties. Tant que le socle ne change
  pas, une mise à jour ne fait retélécharger que les fichiers Smoky (quelques Mo).
- **Jamais sans contrôle** : avant d'être publiée, chaque image est vérifiée (une centaine de
  points : démarrage, écran de connexion, services, applis, extensions, serveurs lancés pour
  de vrai), puis installée et démarrée dans une machine virtuelle jusqu'à l'écran de
  connexion. Si une étape échoue, rien n'est publié et ton PC garde sa version. Ce que ces
  contrôles ne voient pas : le matériel du Z13 (tactile, stylet, carte ASUS) et l'apparence.

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
6. Au premier démarrage, l'assistant GNOME crée ton compte. Branche le Wi-Fi : Proton VPN,
   Déjà Dup et mpv s'installent tout seuls dans les minutes qui suivent.
7. Ouvre l'appli **Synchroniser mes notes avec Google Drive** et autorise l'accès (une seule
   fois). Les carnets Smoky Notes et leurs exports PDF sont dans le dossier **Notes**, donc
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
- **Rien ne tourne pour rien** : les serveurs de Smoky Notes / Center / Mail / Agenda
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
  Smoky Home (empreinte sha256) ; bibliothèques PDF de Smoky Notes copiées dans le dépôt.
- **Moodle** : connexion en HTTPS uniquement, le jeton n'est jamais envoyé à un autre site que
  Moodle (liens externes dans les cours ignorés), téléchargements limités à 200 Mo.
- **Mode concentration** : le service qui modifie /etc/hosts tourne dans un bac à sable (pas de
  réseau, pas d'accès au dossier personnel, seul /etc est modifiable).
- **Allégé** : pas de Firefox (Chrome suffit), pas de visite guidée, pas de variantes d'icônes
  inutiles ; Smoky Home ne tourne que quand l'appli est ouverte.
