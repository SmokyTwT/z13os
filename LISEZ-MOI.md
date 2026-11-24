# Smoky OS 100 % maison

C'est un système d'exploitation écrit de zéro : pas de Linux, pas de bibliothèque. Il y a seulement
`smokyos.c`, `uefi.h` (les définitions du firmware, écrites d'après la spécification UEFI) et le
compilateur. Son nom de travail était « Braise ».

Ton Smoky OS de tous les jours (sur Linux) est dans la branche `main`. Celui-ci est dans la branche
`os-maison`.

## Ce qu'il sait faire (version 0.2)

- Il démarre directement par le firmware UEFI du PC, comme un programme `BOOTX64.EFI`, puis il
  **congédie le firmware** (ExitBootServices). À partir de là, il gère seul (`noyau.c`) :
  - les segments et la table des interruptions ;
  - le contrôleur d'interruptions et la minuterie, à 50 réveils par seconde ;
  - le clavier PS/2 en AZERTY, avec majuscules, Alt Gr et accents circonflexe et tréma ;
  - l'horloge du PC (puce CMOS) et la mémoire libre ;
  - un écran d'erreur si le processeur signale une faute.
- Il dessine tout lui-même : le fond aux braises, les cadres, et sa police, faite de traits sur une
  grille. Celle-ci s'agrandit sans perte et a les accents français.
- Il tient un carnet de commandes : `aide`, `heure`, `memoire`, `ecran`, `systeme`, `effacer`,
  `apropos`, `redemarrer` (par le contrôleur du clavier, sans le firmware) et `eteindre`.
- Entre deux interruptions, le processeur dort (`hlt`).

## Sécurité de ton PC

Il n'a **aucun pilote de disque**. Il n'appelle jamais les fonctions d'écriture du firmware. Il ne
peut donc ni lire ni modifier ton Windows, ton Smoky OS de tous les jours, ou un réglage du PC. Le
firmware lui sert uniquement à démarrer et, pour `eteindre`, à couper le courant.

## Construire et essayer

```bash
./construire.sh      # → construit/esp/EFI/BOOT/BOOTX64.EFI et construit/smokyos.img (clé USB : GPT + partition EFI)
./essayer.py         # machine virtuelle QEMU + firmware OVMF, démarrage depuis une clé USB virtuelle
```

Pour l'essayer sur le Z13, il faudra une clé USB et couper Secure Boot le temps de l'essai, parce
qu'il n'est pas signé. On le fera ensemble, plus tard, avec ton accord.

## La suite

| Version | Contenu |
|---|---|
| 0.2 | Fait : il prend la main (sa mémoire, ses interruptions, sa minuterie, son clavier, son horloge). |
| 0.3 | Clavier USB (contrôleur xHCI) et APIC du Z13 : indispensables pour le vrai PC, qui n'a pas de PS/2. |
| 0.4 | Fenêtres et petites applis : notes, calculatrice, horloge. |
