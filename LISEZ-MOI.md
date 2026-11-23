# Smoky OS 100 % maison

C'est un système d'exploitation écrit de zéro : pas de Linux, pas de bibliothèque. Il y a seulement
`smokyos.c`, `uefi.h` (les définitions du firmware, écrites d'après la spécification UEFI) et le
compilateur. Son nom de travail était « Braise ».

Ton Smoky OS de tous les jours (sur Linux) est dans la branche `main`. Celui-ci est dans la branche
`os-maison`.

## Ce qu'il sait faire (version 0.1)

- Il démarre directement par le firmware UEFI du PC, comme un programme `BOOTX64.EFI`.
- Il dessine tout lui-même : le fond aux braises, les cadres, et sa police, faite de traits sur une
  grille. Celle-ci s'agrandit sans perte et a les accents français.
- Il lit le clavier, en AZERTY par défaut, avec la commande `clavier` pour passer en QWERTY.
- Il tient un carnet de commandes : `aide`, `heure`, `memoire`, `ecran`, `effacer`, `apropos`,
  `redemarrer`, `eteindre` et `quitter`.
- Entre deux touches, le processeur dort : un seul réveil par seconde, pour l'heure.

## Sécurité de ton PC

Il n'a **aucun pilote de disque**. Il n'appelle jamais les fonctions d'écriture du firmware. Il ne
peut donc ni lire ni modifier ton Windows, ton Smoky OS de tous les jours, ou un réglage du PC. Le
firmware lui sert uniquement à démarrer, à lire le clavier et à donner l'heure.

## Construire et essayer

```bash
./construire.sh      # → construit/esp/EFI/BOOT/BOOTX64.EFI et construit/smokyos.img
./essayer.py         # machine virtuelle QEMU + firmware OVMF, captures dans /tmp/smokyos-essai
```

Pour l'essayer sur le Z13, il faudra une clé USB et couper Secure Boot le temps de l'essai, parce
qu'il n'est pas signé. On le fera ensemble, plus tard, avec ton accord.

## La suite

| Version | Contenu |
|---|---|
| 0.2 | Il prend la main : sa propre mémoire, ses interruptions et son horloge, sans le firmware. |
| 0.3 | Clavier USB et écran tactile du Z13, avec ses propres pilotes. |
| 0.4 | Fenêtres et petites applis : notes, calculatrice, horloge. |
