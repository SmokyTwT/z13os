# Smoky OS 100 % maison

C'est un système d'exploitation écrit de zéro : pas de Linux, pas de bibliothèque. Il y a seulement
`smokyos.c` (l'interface), `noyau.c` (le noyau), `usb.c` (le pilote USB), `uefi.h` (les définitions
du firmware, écrites d'après la spécification UEFI) et le compilateur. Son nom de travail était
« Braise ».

Ton Smoky OS de tous les jours (sur Linux) est dans la branche `main`. Celui-ci est dans la branche
`os-maison`.

## Ce qu'il sait faire (version 0.3)

- Il démarre directement par le firmware UEFI du PC, comme un programme `BOOTX64.EFI`, puis il
  **congédie le firmware** (ExitBootServices). À partir de là, il gère seul (`noyau.c`) :
  - les segments et la table des interruptions ;
  - le contrôleur d'interruptions et la minuterie, à 50 réveils par seconde ;
  - le clavier en AZERTY, avec majuscules, Alt Gr et accents circonflexe et tréma, qu'il soit PS/2
    ou **USB** : il a son propre pilote de contrôleur USB 3 (xHCI, `usb.c`), qui trouve les
    contrôleurs sur le bus PCI, les reprend au BIOS, les remet à zéro, adresse les appareils
    branchés, reconnaît un clavier (protocole de démarrage) et lit ses touches, avec répétition
    quand on maintient une touche. Le clavier peut être branché, débranché et rebranché pendant que
    l'OS tourne, comme le clavier détachable du Z13. Un PC sans contrôleur PS/2 démarre aussi ;
  - l'horloge du PC (puce CMOS) et la mémoire libre ;
  - un écran d'erreur si le processeur signale une faute.
- Il dessine tout lui-même : le fond aux braises, les cadres, et sa police, faite de traits sur une
  grille. Celle-ci s'agrandit sans perte et a les accents français.
- Il tient un carnet de commandes : `aide`, `heure`, `memoire`, `ecran`, `systeme`, `usb`,
  `effacer`, `apropos`, `redemarrer` (par le contrôleur du clavier, sans le firmware) et `eteindre`.
- Entre deux interruptions, le processeur dort (`hlt`).

## Sécurité de ton PC

Il n'a **aucun pilote de disque**. Il n'appelle jamais les fonctions d'écriture du firmware. Il ne
peut donc ni lire ni modifier ton Windows, ton Smoky OS de tous les jours, ou un réglage du PC. Le
firmware lui sert uniquement à démarrer et, pour `eteindre`, à couper le courant. Le pilote USB ne
sait parler qu'aux claviers : une clé USB branchée est seulement reconnue, jamais lue.

## Construire et essayer

```bash
./construire.sh      # → construit/esp/EFI/BOOT/BOOTX64.EFI et construit/smokyos.img (clé USB : GPT + partition EFI)
./essayer.py         # machine virtuelle QEMU + firmware OVMF, démarrage depuis une clé USB virtuelle
./essayer.py 25 --branchement   # le clavier USB n'est branché qu'après le démarrage, puis débranché et rebranché
```

La machine virtuelle n'a pas de contrôleur PS/2 (`i8042=off`) : tout ce qui est tapé passe par le
clavier USB et le pilote maison (`systeme` affiche 0 interruption du clavier PS/2). Le journal du
pilote sort sur le port série (`/tmp/smokyos-essai/serie.txt`).

Pour l'essayer sur le Z13, il faudra une clé USB et couper Secure Boot le temps de l'essai, parce
qu'il n'est pas signé. On le fera ensemble, plus tard, avec ton accord.

## La suite

| Version | Contenu |
|---|---|
| 0.2 | Fait : il prend la main (sa mémoire, ses interruptions, sa minuterie, son clavier, son horloge). |
| 0.3 | Fait : clavier USB (pilote xHCI maison), branchement à chaud, PC sans PS/2. Pas encore : les concentrateurs USB (si le clavier du Z13 passe par un concentrateur interne, il faudra les gérer) et l'APIC (la minuterie passe encore par le vieux contrôleur PIC). |
| 0.4 | Fenêtres et petites applis : notes, calculatrice, horloge. |
