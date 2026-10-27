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
| Spotify, Steam | Applis officielles (Flatpak), installées au 1er démarrage |
| Moodle, Google Drive | Applis dans le dock + Drive dans Fichiers (Paramètres > Comptes en ligne) |
| Claude | Appli Claude dans le dock ; Claude Code reste disponible en tapant `claude` dans un terminal (il connaît Smoky OS via ~/.claude/CLAUDE.md) |
| Optimisation Z13 | asusctl / supergfxctl, RTX coupée (autonomie), charge limitée à 80 %, thermald, codecs, mises à jour auto |
| Prise de notes façon GoodNotes | **Smoky Notes**, appli maison : bibliothèque de carnets avec couvertures, classeurs et favoris ; papiers ligné, quadrillé, pointillé, Cornell, Seyès, portées (blanc, ivoire, cendre, fumée) ; stylo sensible à la pression, surligneur, gomme (trait entier ou précise), bout gomme du stylet ; lasso (déplacer, agrandir, recolorer, copier, dupliquer) ; formes parfaites en maintenant le stylet ; texte, images, pointeur laser ; import de PDF à annoter ; export PDF vectoriel dans Notes/PDF ; signets et miniatures des pages ; zoom à deux doigts, toucher à 2 doigts = annuler, 3 doigts = rétablir ; gribouiller sur un mot avec le stylo l'efface ; rejet de la paume ; tout est enregistré dans Notes/Smoky Notes (synchronisé avec Google Drive) |
| Interface Smoky | Applis ouvertes en grand automatiquement (extension maison « smoky-maximize », les boîtes de dialogue gardent leur taille) ; dock flottant en verre fumé (liseré argenté, ombre, survol lumineux, bulles assorties), flou *statique* sur la barre et le dock (calculé une fois, ~0 % de batterie), icônes et curseurs WhiteSur (versions figées) pour toutes les applis, y compris le streaming, grands boutons tactiles dans le centre de contrôle, GSConnect (téléphone), Caffeine (anti-veille), boutons de fenêtre à gauche, thème « fumée » noir/gris/blanc : fond d'écran « smoky » en volutes argentées ; tout le système suit ce style : applis GNOME en noir et argent, dock en verre fumé à liseré argenté, logos Smoky (thème d'icônes « Smoky-icons ») : chaque appli reçoit la version Smoky de son vrai logo (argent, carré noir, trait néon à sa couleur), y compris les applis installées plus tard (smoky-autoicons) ; TF1+, M6+, Moodle et Smoky Notes sont dessinés à la main (tools/make-icons.py), curseur « Smoky » : point blanc néon, anneau sur les liens, volute animée pendant le chargement (tools/make-cursors.py), fenêtres à contour argenté et boutons fermer/réduire/agrandir en blanc néon, Chrome et applis web en sombre, applis Flatpak au thème (version claire et sombre, mode sombre par défaut), centre de contrôle où les boutons actifs s'allument en blanc |
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
5. Au redémarrage, l'assistant GNOME crée ton compte. Branche le Wi-Fi : Spotify et
   Claude Code s'installent tout seuls dans les minutes qui suivent.
6. Ouvre l'appli **Synchroniser mes notes avec Google Drive** et autorise l'accès (une seule fois).
   Les carnets Smoky Notes et leurs exports PDF sont dans le dossier **Notes**, donc synchronisés.
7. `z13-status` dans un terminal affiche l'état de la machine.

## À savoir (honnêtement)
- **Streaming** : Netflix, Disney+ et Prime Video limitent Chrome sous Linux à environ **720p**.
  C'est une limite côté plateformes, on ne peut pas la contourner. TF1+ et M6+ ne sont pas
  concernés.
- **Claude Desktop** n'existe pas sous Linux : tu as l'appli web Claude et Claude Code.
- **RTX 3050 Ti** : coupée par défaut. Pour la rallumer : `supergfxctl -m Hybrid`, puis
  déconnexion et reconnexion. Le pilote NVIDIA n'est pas inclus.
- **Ajouter un logiciel** : passe par l'app *Logiciels* (Flatpak) ou ajoute un paquet dans
  `build_files/build.sh`, et GitHub reconstruit l'image.

`alternative/install-sur-fedora.sh` : l'ancienne méthode, à lancer sur un Fedora
Workstation classique déjà installé.
