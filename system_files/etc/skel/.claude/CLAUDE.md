# Contexte : l'ordinateur de l'utilisateur

- Langue : réponds en français, simplement ; l'utilisateur n'est pas développeur.
- Machine : ASUS ROG Flow Z13 2022 (GZ301ZE, i9-12900H, RTX 3050 Ti, écran tactile + stylet).
- Système : **Smoky OS**, une image personnelle basée sur **Fedora Silverblue** (système atomique).
  - Le système de base est en lecture seule : **ne pas utiliser `dnf install`**.
  - Applis : `flatpak install flathub <id>` (préféré). Paquet système en dernier recours :
    `rpm-ostree install <paquet>` puis redémarrage.
  - Mises à jour : automatiques chaque semaine (image reconstruite sur GitHub, appliquée au redémarrage).
    Revenir à la version précédente : `rpm-ostree rollback` puis redémarrer.
  - L'image se construit depuis le dépôt GitHub `SmokyTwT/z13os` (build_files/build.sh) :
    un changement durable du système se fait là, pas sur la machine.
- Matériel ASUS : `asusctl` (charge limitée à 80 %, profils), `supergfxctl -m Integrated|Hybrid` (carte graphique).
  `z13-status` résume l'état de la machine.
- Notes : appli **Smoky Notes** ; carnets dans `~/Notes/Smoky Notes`, exports PDF dans `~/Notes/PDF`,
  `~/Notes` est synchronisé avec Google Drive (rclone, minuteur `z13-notes-sync.timer`).
- Cours : Moodle de l'UPHF (https://moodle.uphf.fr/).
- Demande confirmation avant toute action qui supprime des fichiers ou modifie le système.
