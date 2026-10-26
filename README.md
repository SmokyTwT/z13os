# Z13 OS — ta distrib Linux perso pour ROG Flow Z13 (GZ301ZE)

Une image **Fedora Silverblue** (GNOME / Wayland) préparée pour ton Z13. Le système est
« atomique » : chaque mise à jour remplace l'image complète. En cas de souci, tu peux
revenir à la version précédente depuis le menu de démarrage.

## Ce qu'il y a dedans
| Besoin | Solution |
|---|---|
| Tactile, stylet, mode tablette | GNOME Wayland : gestes, clavier virtuel, rotation auto |
| Chrome | Google Chrome, réglé pour Wayland et le décodage vidéo par la puce Intel |
| Netflix, Disney+, Prime Video, TF1+, M6+ | Applis dans le dock |
| Spotify | Appli officielle, installée au 1er démarrage |
| Moodle, Google Drive | Applis dans le dock + Drive dans Fichiers (Paramètres > Comptes en ligne) |
| Claude | Claude Code installé à la 1re connexion (`claude` dans un terminal) + appli Claude |
| Optimisation Z13 | asusctl / supergfxctl, RTX coupée (autonomie), charge limitée à 80 %, thermald, codecs, mises à jour auto |
| Notes au stylet | Xournal++ |

## Obtenir l'ISO (GitHub la construit pour toi, gratuitement)
1. Crée un compte sur https://github.com, puis un dépôt **public** nommé `z13os`.
2. Envoie tout le contenu de ce dossier dans le dépôt, y compris le dossier caché `.github`.
   Le plus simple : *Add file → Upload files*, puis glisser-déposer.
3. *Settings → Secrets and variables → Actions → Variables* : ajoute `MOODLE_URL`
   avec l'adresse de ton Moodle.
4. Onglet **Actions** : lance `build-image` (environ 20 min). `build-iso` démarre ensuite
   tout seul (environ 30 min).
5. *Your profile → Packages → z13os → Package settings* : mets la visibilité sur
   **Public**. C'est nécessaire pour que ton PC reçoive les mises à jour.
6. Dans Actions → `build-iso` → la dernière exécution, télécharge **z13os-iso**
   (environ 4 Go, contient `z13os.iso`).

Chaque lundi, GitHub reconstruit l'image avec les derniers correctifs. Ton Z13 les
télécharge seul et les applique au redémarrage suivant.

## Installer sur le Z13
1. **Sous Windows d'abord** : mets à jour le BIOS avec MyASUS et **sauvegarde tes fichiers**.
2. Copie `z13os.iso` sur une clé USB (8 Go ou plus) avec **Fedora Media Writer** ou
   **balenaEtcher** (option « image personnalisée »).
3. Allume le Z13 en maintenant **Échap** (ou **F2** → Boot), puis choisis la clé.
4. L'installateur demande seulement le disque. Choisis « récupérer tout l'espace » pour
   remplacer Windows.
5. Au redémarrage, l'assistant GNOME crée ton compte. Branche le Wi-Fi : Spotify et
   Claude Code s'installent tout seuls dans les minutes qui suivent.
6. `z13-status` dans un terminal affiche l'état de la machine.

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
