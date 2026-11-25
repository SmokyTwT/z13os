# Smoky OS 100 % maison

C'est un système d'exploitation écrit de zéro : pas de Linux, pas de bibliothèque. Il y a seulement
`smokyos.c` (l'interface), `noyau.c` (le noyau), `usb.c` (le pilote USB), `uefi.h` (les définitions
du firmware, écrites d'après la spécification UEFI) et le compilateur. Son nom de travail était
« Braise ».

Ton Smoky OS de tous les jours (sur Linux) est dans la branche `main`. Celui-ci est dans la branche
`os-maison`.

## Ce qu'il sait faire (version 0.6)

- Il démarre directement par le firmware UEFI du PC, comme un programme `BOOTX64.EFI`, puis il
  **congédie le firmware** (ExitBootServices). À partir de là, il gère seul (`noyau.c`) :
  - les segments et la table des interruptions ;
  - le temps : il le compte avec le compteur du processeur (TSC). Il en connaît la fréquence par le
    processeur lui-même, sinon il la mesure avec le vieux PIT ou, si celui-ci est arrêté (c'est
    possible sur un PC récent comme le Z13), avec l'horloge CMOS ;
  - la minuterie : celle de l'APIC local (la puce d'interruptions des processeurs récents, en mode
    xAPIC ou x2APIC) le réveille 50 fois par seconde. S'il n'y en a pas, il prend le vieux PIT, et
    si aucune ne bat, il reste utilisable : le processeur ne dort plus, c'est tout ;
  - le clavier en AZERTY, avec majuscules, Alt Gr et accents circonflexe et tréma, qu'il soit PS/2
    ou **USB** : il a son propre pilote de contrôleur USB 3 (xHCI, `usb.c`), qui trouve les
    contrôleurs sur le bus PCI, les reprend au BIOS, les remet à zéro, adresse les appareils
    branchés, reconnaît un clavier (protocole de démarrage) et lit ses touches, avec répétition
    quand on maintient une touche. Le clavier peut être branché, débranché et rebranché pendant que
    l'OS tourne, comme le clavier détachable du Z13. Il peut aussi être derrière un ou plusieurs
    **hubs USB 2** (un hub interne du PC, un dock, la partie USB 2 d'un hub USB 3). Un appareil qui
    refuse une requête ne bloque pas les suivantes. Un PC sans contrôleur PS/2 démarre aussi ;
  - les **pointeurs USB** : souris, pavé tactile en mode souris, tablette (pointeur absolu). Il lit
    leur format dans le descripteur de rapport que chaque appareil fournit (`hid.c`, essayé à chaque
    construction contre de vrais descripteurs), avec repli sur le protocole de démarrage. Un clavier
    qui a aussi un pointeur (le pavé du clavier détachable, un récepteur sans fil clavier + souris)
    est géré en entier : ce cas-là n'a pas encore été essayé, faute d'appareil de ce genre dans QEMU ;
  - l'horloge du PC (puce CMOS), lue en temps universel et affichée à l'heure de Paris (heure d'été
    comprise), et la mémoire libre ;
  - un écran d'erreur si le processeur signale une faute.
- Il dessine tout lui-même : le fond aux braises, les fenêtres, la flèche de la souris, et sa
  police, faite de traits sur une grille. Celle-ci s'agrandit sans perte et a les accents français.
  L'écran n'est refait que là où quelque chose a changé.
- Il ouvre des **fenêtres** : on les prend par leur barre de titre pour les déplacer, un clic les
  met devant, le bouton × ou Échap les ferme (sauf le carnet), Alt+Tab passe à la suivante. Celle
  de devant reçoit le clavier.
  - **calculatrice** : au clavier ou à la souris ; priorités (puissance, puis × et ÷, puis + et −),
    parenthèses, virgule ou point, `2(3+4)`, et après « = » on continue avec le résultat ;
  - **notes** : un bloc-notes ; le texte reste tant que le PC est allumé (rien n'est écrit sur le
    disque) ;
  - **horloge** : l'heure en grand, la date, et un chronomètre (Espace pour démarrer ou arrêter).
- Il tient un carnet de commandes : `aide`, `heure`, `memoire`, `ecran`, `systeme`, `usb` (la
  liste des appareils USB, avec leur chemin : `port 6 → 3` veut dire « port 3 du hub branché sur le
  port 6 » ; pour un appareil à plusieurs interfaces, une ligne `interfaces 3/1/1* 3/0/0` donne leur
  classe, sous-classe et protocole, `*` pour celles qu'il utilise), `bilan` (tout ce qu'il voit du PC
  sur un seul écran, à photographier), `calculatrice`,
  `notes`, `horloge`, `effacer`, `apropos`, `redemarrer` (par le contrôleur du clavier, sans le
  firmware) et `eteindre`.
- Si aucun clavier ne répond au démarrage, il affiche tout seul ce qu'a vu le pilote USB (les
  dernières lignes de son journal, gardées en mémoire, et les appareils trouvés) : une photo de
  l'écran suffit pour comprendre, même sur un PC sans port série comme le Z13. Un clavier branché
  ensuite est annoncé.
- Entre deux interruptions, le processeur dort (`hlt`).

## Sécurité de ton PC

Il n'a **aucun pilote de disque**. Il n'appelle jamais les fonctions d'écriture du firmware. Il ne
peut donc ni lire ni modifier ton Windows, ton Smoky OS de tous les jours, ou un réglage du PC. Le
firmware lui sert uniquement à démarrer et, pour `eteindre`, à couper le courant. Le pilote USB ne
parle qu'aux claviers, aux pointeurs et aux hubs : une clé USB branchée est seulement reconnue (elle
apparaît dans `usb`), jamais lue.

## Construire et essayer

```bash
./construire.sh      # → construit/esp/EFI/BOOT/BOOTX64.EFI et construit/smokyos.img (clé USB : GPT + partition EFI)
./essayer.py         # machine virtuelle QEMU + firmware OVMF, démarrage depuis une clé USB virtuelle
./essayer.py 25 --branchement   # le clavier USB n'est branché qu'après le démarrage, puis débranché et rebranché
./essayer.py 25 --sans-pit      # sans PIT ni HPET, comme un PC récent dont le firmware les arrête
./essayer.py 25 --hub           # le clavier derrière un hub ; --hubs : derrière deux hubs à la suite
./essayer.py 25 --tablette      # une tablette (pointeur absolu) à la place de la souris
```

`construire.sh` commence par l'essai du lecteur de descripteurs HID (`essais/hid.c`, compilé et lancé
sur la machine de construction) : souris et tablette de QEMU, souris de récepteur sans fil, pavé
tactile de précision, clavier, PUSH/POP, descripteur coupé.

Les options se combinent (`--hubs --branchement`). Chaque essai tape `aide`, `memoire`, `systeme`,
`heure`, une ligne avec Maj, Alt Gr et un accent, puis `usb` et `bilan`. Ensuite il ouvre la
calculatrice (un calcul tapé, puis 7 + 1 = 8 à la souris), la déplace par sa barre de titre, passe au
carnet par Alt+Tab, écrit dans les notes, les ferme et les rouvre (le texte est toujours là), et
lance le chronomètre. Il prend une capture après chaque étape dans `/tmp/smokyos-essai/`.

La machine virtuelle n'a pas de contrôleur PS/2 (`i8042=off`) : tout ce qui est tapé passe par le
clavier USB et le pilote maison (`systeme` affiche 0 interruption du clavier PS/2). Le journal du
pilote sort sur le port série (`/tmp/smokyos-essai/serie.txt`).

Pour l'essayer sur le Z13, il faudra une clé USB et couper Secure Boot le temps de l'essai, parce
qu'il n'est pas signé. On le fera ensemble, plus tard, avec ton accord. Ce jour-là, la commande
`bilan` dira en une photo ce qu'il a trouvé : processeur, minuterie, écran, clavier, appareils USB.

## La suite

| Version | Contenu |
|---|---|
| 0.2 | Fait : il prend la main (sa mémoire, ses interruptions, sa minuterie, son clavier, son horloge). |
| 0.3 | Fait : clavier USB (pilote xHCI maison), branchement à chaud, PC sans PS/2. |
| 0.4 | Fait : le temps par le compteur du processeur, la minuterie de l'APIC local (un PC dont le vieux PIT est arrêté fonctionne), les hubs USB 2, la reprise après une requête refusée, un contrôleur USB endormi réveillé, la commande `bilan`. Vérifié dans QEMU (avec et sans PIT, derrière un et deux hubs, branchement à chaud), pas encore sur le vrai Z13. Le mode x2APIC n'a pas pu être essayé (ce QEMU ne l'émule pas) : s'il ne répondait pas, l'OS prendrait le PIT, ou se passerait de minuterie. |
| 0.5 | Fait : souris USB, fenêtres (déplacer, mettre devant, fermer, Alt+Tab), calculatrice, notes, horloge avec chronomètre, heure de Paris. Vérifié dans QEMU. |
| 0.6 | Fait : pointeurs décrits par leur descripteur de rapport (souris, pavé tactile en mode souris, tablette), clavier + pointeur sur un même appareil (pour le pavé du clavier du Z13), interfaces affichées par `usb` et `bilan`. Vérifié dans QEMU avec une souris et une tablette ; le clavier + pointeur attend un vrai appareil. |
| 0.7 | L'essai sur le vrai Z13 (photo de `bilan`), puis ce qu'il montrera : le pavé en mode précision s'il le faut, l'écran tactile (I2C, plus gros morceau). |
