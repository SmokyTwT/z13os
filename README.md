# Smoky OS — ta distrib Linux perso pour ROG Flow Z13 (GZ301ZE)

Une image **Fedora Silverblue** (GNOME / Wayland) préparée pour ton Z13. Le système est
« atomique » : chaque mise à jour remplace l'image complète. En cas de souci, tu peux
revenir à la version précédente depuis le menu de démarrage.

## Ce qu'il y a dedans
| Besoin | Solution |
|---|---|
| Tactile, stylet, mode tablette | GNOME Wayland : gestes, clavier virtuel, rotation auto |
| Chrome | Google Chrome, réglé pour Wayland et le décodage vidéo par la puce Intel |
| Netflix, Disney+, Prime Video, TF1+, M6+ | Applis dans le dock |
| Maison | **Smoky Home** : robot Xiaomi X20 Max avec la carte, lumières Tapo, Google Home Mini et Nest Hub (Home Assistant + dreame-vacuum, versions figées) |
| Spotify, Proton VPN | Applis officielles (Flatpak), installées au 1er démarrage |
| WhatsApp | WhatsApp Web en appli dans le dock (il n'existe pas d'appli WhatsApp officielle pour Linux) |
| Moodle, Google Drive | Applis dans le dock + Drive dans Fichiers (Paramètres > Comptes en ligne) |
| Claude | Appli Claude dans le dock |
| Optimisation Z13 | asusctl / supergfxctl, RTX coupée (autonomie), charge limitée à 80 %, thermald, codecs, mises à jour auto |
| Prise de notes façon GoodNotes | **Smoky Notes**, appli maison : bibliothèque de carnets avec couvertures, classeurs et favoris ; papiers ligné, quadrillé, pointillé, Cornell, Seyès, portées (blanc, ivoire, cendre, fumée) ; stylo sensible à la pression, surligneur, gomme (trait entier ou précise), bout gomme du stylet ; lasso (déplacer, agrandir, recolorer, copier, dupliquer) ; formes parfaites en maintenant le stylet ; texte, images, pointeur laser ; import de PDF à annoter ; export PDF vectoriel dans Notes/PDF ; signets et miniatures des pages ; zoom à deux doigts, toucher à 2 doigts = annuler, 3 doigts = rétablir ; gribouiller sur un mot avec le stylo l'efface (le mot passe en rouge pendant le gribouillis : on voit ce qui va partir) ; rejet de la paume ; tout est enregistré dans Notes/Smoky Notes (synchronisé avec Google Drive) |
| Interface Smoky | Applis ouvertes en grand automatiquement (extension maison « smoky-maximize », les boîtes de dialogue gardent leur taille) ; dock flottant en verre fumé (liseré argenté, ombre, survol lumineux, bulles assorties), flou *statique* sur la barre et le dock (calculé une fois, ~0 % de batterie), icônes et curseurs WhiteSur (versions figées) pour toutes les applis, y compris le streaming, grands boutons tactiles dans le centre de contrôle, GSConnect (téléphone), Caffeine (anti-veille), boutons de fenêtre à gauche, thème « fumée » noir/gris/blanc : fond d'écran « smoky » en volutes argentées ; tout le système suit ce style : applis GNOME en noir et argent, dock en verre fumé à liseré argenté, logos Smoky (thème d'icônes « Smoky-icons ») : chaque appli reçoit la version Smoky de son vrai logo (argent, carré noir, trait néon à sa couleur), y compris les applis installées plus tard (smoky-autoicons) ; TF1+, M6+, Moodle et Smoky Notes sont dessinés à la main (tools/make-icons.py), curseur « Smoky » : point blanc néon, anneau sur les liens, volute animée pendant le chargement (tools/make-cursors.py), fenêtres à contour argenté et boutons fermer/réduire/agrandir en blanc néon, Chrome et applis web en sombre, applis Flatpak au thème (version claire et sombre, mode sombre par défaut), centre de contrôle où les boutons actifs s'allument en blanc |
| Smoky Center | Une seule appli de réglages : batterie (limite de charge), profil d'énergie, carte graphique, mode tablette, Moodle, concentration, maison, VPN, sauvegardes, logos, mises à jour ; écran (veilleuse, luminosité auto, rotation, taille du texte), veille et verrouillage, ne pas déranger, son au-delà de 100 %, confidentialité (caméra, localisation, fichiers récents, corbeille auto), dock et pavé tactile, stockage avec nettoyage en un clic, mise à jour des applis, infos système et « Redémarrer sur Windows » (une seule fois) |
| Cours Moodle → Smoky Notes | Connexion une fois avec ton identifiant et ton mot de passe UPHF (Smoky Center > Cours). Le mot de passe n'est **jamais** enregistré : seul le jeton Moodle est rangé dans le trousseau GNOME. Toutes les 2 h, les nouveaux PDF de tes cours arrivent en carnets annotables, rangés par cours. Un carnet déjà annoté n'est jamais écrasé : la nouvelle version arrive à côté |
| Échéances | Devoirs et tests Moodle en pastilles « À rendre » dans Smoky Notes, notification 36 h avant, et fichier Notes/« Moodle - échéances.ics » importable dans Google Agenda |
| Enregistrement audio | Bouton micro dans Smoky Notes : l'audio est lié à l'écriture ; outil « écouter » : touche un mot, la lecture repart au moment où tu l'as écrit |
| Concentration | Pomodoro (25 min par défaut) qui bloque YouTube, TikTok, Instagram, réseaux et streaming le temps de la session (liste : /etc/smokyos/focus-sites.conf) |
| Adaptation automatique | 120 Hz sur secteur, 60 Hz sur batterie ; bouton « Tablette » dans le menu en haut à droite (et dans Smoky Center) : grandes icônes, clavier à l'écran, proposition d'ouvrir Smoky Notes |
| Maison dans les réglages rapides | Bouton « Maison » dans le menu en haut à droite : lumières et robot (démarrer, pause, base) |
| VPN Wi-Fi public | Appli Proton VPN (gratuite) ; pour l'activation automatique, importe aussi ton fichier WireGuard Proton dans Smoky Center ; option pour l'activer tout seul sur les Wi-Fi sans mot de passe |
| Sauvegardes | Déjà Dup (sauvegardes automatiques chiffrées de ton dossier personnel, vers Google Drive ou un disque) |
| Démarrage et connexion | Écran de démarrage Smoky (Plymouth) : fond « smoky » et volute argentée ; écran de connexion au même fond, champs et boutons à liseré néon blanc |
| Thème Smoky partout | Paramètres, Fichiers, Logiciels et toutes les applis GNOME : fond aux volutes « smoky » floutées, barre latérale et listes en verre fumé, interrupteurs, champs et sélection en néon blanc ; Terminal en palette « Smoky » ; mis à jour avec le système à chaque connexion (un thème personnel dans ~/.config/gtk-4.0/gtk.css sans la ligne « Smoky OS » est respecté) |
| Animations légères | Transitions courtes au survol et au clic (bureau, dock, centre de contrôle, connexion, applis GNOME), apparition en fondu des menus et notifications, cartes de Smoky Center en cascade à l'ouverture, ouvertures douces dans Smoky Notes ; uniquement opacité, couleurs et halos (calculés par la puce graphique), jamais en boucle ; tout se coupe avec « Animations » dans Smoky Center |
| Smoky Mail | Toutes tes boîtes (Gmail, Outlook/Hotmail, Orange, Free, UPHF ou tout serveur IMAP) dans une seule liste, au thème Smoky ; Outlook se connecte par la page officielle de Microsoft (code à saisir, une fois l'identifiant d'application créé sur portal.azure.com) ; réponse depuis la bonne boîte : lecture, réponse, archivage, corbeille, recherche. **Claude trie automatiquement** chaque nouveau mail (Important, Cours et université, Personnel, Achats, Newsletters, Notifications, Indésirable) avec un résumé d'une ligne et un repère « à faire » ; notification pour les mails importants, relève toutes les 15 min. Tri par Claude avec ton compte Claude (le même que l'appli, forfait Pro ou Max) via Claude Code, l'outil officiel d'Anthropic, installé en un clic depuis les réglages : pas de clé d'API, rien à payer en plus ; Claude n'y a aucun outil (ni fichiers, ni Internet) ; sans Claude, tri simple sur le PC. Mot de passe dans le trousseau, images distantes (pisteurs) bloquées, scripts des mails jamais exécutés |
| Smoky Agenda | Planifie tes journées : ton emploi du temps (lien iCal de l'ENT / ADE) et tes échéances Moodle s'affichent tout seuls ; « Planifier ma semaine » place autour les révisions (matières dont une échéance approche d'abord, blocs de 50 min + pauses), la salle (pas deux jours de suite), les courses, les repas et tes tâches avant leur date limite ; « ✨ Avec Claude » fait organiser la semaine par Claude avec ton compte (blocs vérifiés : jamais par-dessus un cours) ; rappel avant chaque bloc (préparé à l'avance, aucun programme ne tourne en attendant) ; bouton « Concentration » sur les révisions ; planning copié dans Notes/Planning Smoky.ics |
| Notes sauvegardées | Dossier **Notes** synchronisé toutes les 5 min avec Google Drive > « Notes Z13 » |

## Obtenir l'ISO (GitHub la construit pour toi, gratuitement)
1. Crée un compte sur https://github.com, puis un dépôt **public** nommé `z13os`.
2. Envoie tout le contenu de ce dossier dans le dépôt, y compris le dossier caché `.github`.
   Le plus simple : *Add file → Upload files*, puis glisser-déposer.
3. Moodle : l'UPHF (`https://moodle.uphf.fr/`) est réglé par défaut. Pour en changer, ajoute
   une variable `MOODLE_URL` dans *Settings → Secrets and variables → Actions → Variables*.
4. Onglet **Actions** : lance `build-image` (environ 20 min). `build-iso` démarre ensuite
   tout seul (environ 30 min).
5. *Your profile → Packages → z13os → Package settings* : mets la visibilité sur
   **Public**. C'est nécessaire pour que ton PC reçoive les mises à jour.
6. Dans Actions → `build-iso` → la dernière exécution, télécharge **smokyos-iso**
   (environ 4 Go, contient `smokyos.iso`).

Chaque lundi, GitHub reconstruit l'image avec les derniers correctifs. Ton Z13 les
télécharge seul et les applique au redémarrage suivant.

## Smoky Home : robot, lumières, Google Home
Appli **Smoky Home** (dans le dock). Elle repose sur Home Assistant, qui tourne en conteneur seulement quand l'appli est ouverte, et n'est joignable que depuis ce PC.
1. **Premier lancement** : environ 1,5 Go à télécharger, quelques minutes. Crée ensuite ton compte Smoky Home (local, pas en ligne).
2. **Paramètres → Appareils et services → Ajouter une intégration** :
   - **TP-Link Smart Home** : identifiants de l'appli Tapo, puis les ampoules apparaissent.
   - **Dreame Vacuum** : choisis « Xiaomi Home », connecte ton compte Xiaomi et sélectionne le **X20 Max**. La carte en direct, les pièces et les zones apparaissent.
   - **Google Cast** : le Google Home Mini et le Nest Hub sont détectés tout seuls (volume, musique, annonces, affichage sur le Hub).
3. Le tableau de bord montre tout automatiquement, dans le thème Smoky.

### Robot sur un Wi-Fi public (page « accepter »)
Le robot n'a pas de navigateur pour accepter la page du Wi-Fi public. Ouvre l'appli **Portail Wi-Fi pour un appareil** :
1. Donne l'adresse MAC du robot (Xiaomi Home → robot → Paramètres → Infos réseau). Éteins le robot s'il était déjà sur ce Wi-Fi.
2. Choisis le Wi-Fi public : le PC s'y connecte avec l'adresse du robot, et tu acceptes la page.
3. Le PC reprend sa propre adresse. Tu connectes le robot à ce Wi-Fi depuis Xiaomi Home : il a Internet.

Ensuite, le robot (avec la carte) se pilote de n'importe où : appli Xiaomi Home ou Smoky Home. Si le portail expire, relance l'outil.

## Installer sur le Z13
1. **Sous Windows d'abord** : mets à jour le BIOS avec MyASUS et **sauvegarde tes fichiers**.
2. Copie `smokyos.iso` sur une clé USB (8 Go ou plus) avec **Fedora Media Writer** ou
   **balenaEtcher** (option « image personnalisée »).
3. Allume le Z13 en maintenant **Échap** (ou **F2** → Boot), puis choisis la clé.
4. L'installateur demande seulement le disque. Choisis « récupérer tout l'espace » pour
   remplacer Windows.
5. Au redémarrage, l'assistant GNOME crée ton compte. Branche le Wi-Fi : Spotify, Proton VPN, Déjà Dup et mpv
   s'installent tout seuls dans les minutes qui suivent.
6. Ouvre l'appli **Synchroniser mes notes avec Google Drive** et autorise l'accès (une seule fois).
   Les carnets Smoky Notes et leurs exports PDF sont dans le dossier **Notes**, donc synchronisés.
7. `z13-status` dans un terminal affiche l'état de la machine.

## À savoir (honnêtement)
- **Streaming** : Netflix, Disney+ et Prime Video limitent Chrome sous Linux à environ **720p**.
  C'est une limite côté plateformes, on ne peut pas la contourner. TF1+ et M6+ ne sont pas
  concernés.
- **Claude Desktop** n'existe pas sous Linux : tu as l'appli Claude (web) dans le dock.
- **RTX 3050 Ti** : coupée par défaut (Smoky Center > Carte graphique pour la rallumer, avec le
  pilote libre). Pas de pilote NVIDIA propriétaire : inutile pour les cours et le streaming.
- **Moodle** : si la connexion par identifiant est refusée (connexion UPHF via CAS), Smoky Center
  ouvre automatiquement la page de connexion de l'université, et le jeton revient tout seul.
- **Ajouter un logiciel** : passe par l'app *Logiciels* (Flatpak) ou ajoute un paquet dans
  `build_files/build.sh`, et GitHub reconstruit l'image.

## Autonomie et durée de vie de la batterie
- **Limite de charge à 80 %** (plus de cycles avant usure) ; bouton « Charger à 100 % pour cette
  fois » dans Smoky Center : la limite revient toute seule au débranchement.
- **Débranché** : écran à 60 Hz, « Performance » repasse en « Équilibré » (et revient au rebranchement),
  RTX coupée par défaut, Wi-Fi en économie d'énergie, Chrome en économiseur de batterie sous 20 %.
- **Rien ne tourne pour rien** : les serveurs de Smoky Notes / Center / Mail s'arrêtent avec leur
  fenêtre ; Chrome ne reste pas en arrière-plan ; synchro des notes toutes les 10 min (30 sur
  batterie), relève des mails 15 min (30 sur batterie) ; mises à jour des applis une fois par jour
  et seulement sur secteur ; GNOME Logiciels, ROG Control Center et ModemManager ne tournent plus
  en permanence.

## Sécurité, stabilité, légèreté
- **Secure Boot compatible** : Smoky OS garde le noyau et le chargeur de démarrage signés de
  Fedora, et n'ajoute aucun pilote non signé (pas de pilote NVIDIA propriétaire). Tu peux activer
  le Secure Boot dans le BIOS (F2) ; Windows continue de démarrer normalement à côté.
- **Noyau durci** : un programme ne peut plus lire la mémoire d'un autre, pas de remplacement du
  noyau à chaud, redirections réseau ignorées (Wi-Fi publics).
- **Pare-feu en zone « public »** : rien n'est joignable depuis le réseau (Wi-Fi publics compris),
  sauf la découverte des Google Home/Chromecast et GSConnect. Smoky Notes et Smoky Home ne
  répondent qu'au PC lui-même.
- **Versions figées** : thèmes WhiteSur, intégration du robot et moteur de Smoky Home
  (empreinte sha256) ; bibliothèques PDF de Smoky Notes copiées dans le dépôt.
- **Mises à jour** : image reconstruite chaque lundi, téléchargée en arrière-plan, appliquée au
  redémarrage ; bouton « Rechercher une mise à jour » dans Smoky Center pour le faire tout de suite ; en cas de souci, revenir à la version précédente depuis le menu de démarrage.
- **Moodle** : connexion en HTTPS uniquement, le jeton n'est jamais envoyé à un autre site que
  Moodle (liens externes dans les cours ignorés), téléchargements limités à 200 Mo.
- **Mode concentration** : le service qui modifie /etc/hosts tourne dans un bac à sable (pas de
  réseau, pas d'accès au dossier personnel, seul /etc est modifiable).
- **Allégé** : pas de Firefox (Chrome suffit), pas de visite guidée, pas de variantes d'icônes
  inutiles ; Smoky Home ne tourne que quand l'appli est ouverte.

