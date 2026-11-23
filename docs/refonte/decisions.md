# Smoky OS refait de zéro — fiches de décision

Chaque fiche dit ce qui a été choisi, pourquoi, et ce qu'on a écarté. Décideur : toi.
Elles sont tirées de la recherche du 23/11/2026 et de l'inventaire du dépôt.

---

## Décision 1 — La base : Fedora bootc minimal, sans GNOME

**Statut :** acceptée · **Date :** 23/11/2026

**Contexte.** L'image actuelle part de Fedora Silverblue, qui embarque tout GNOME. On veut
réécrire tout ce qui n'est pas le noyau. Les pilotes du noyau restent : c'est d'eux que vient
l'autonomie.

**Décision.** Partir de `quay.io/fedora/fedora-bootc:44`, l'image minimale officielle. On y
ajoute seulement ce qui sert. Le mécanisme de mise à jour (bootc / rpm-ostree, retour arrière)
et le nom de l'image ne changent pas : ton PC continue de recevoir les mises à jour comme avant.

| Option | Complexité | Autonomie | Risque | « Fait pour toi » |
|---|---|---|---|---|
| **fedora-bootc minimal** | moyenne | meilleure : rien d'inutile en arrière-plan | moyen : la liste des paquets est à faire nous-mêmes | oui |
| Silverblue moins GNOME | forte (on retire morceau par morceau) | moyenne | fort : dépendances cachées | non |
| Fedora Sway Atomic | faible | bonne | faible | non : c'est le bureau de Fedora |

**Ce qu'il faut savoir.**
- La sonde du 23/11 a montré ce qui manque à fedora-bootc : écran de démarrage, Wi-Fi, son,
  Bluetooth, pare-feu et Flatpak. Ces paquets sont ajoutés.
- Elle a aussi montré ce qu'il active et qu'on ne veut pas :
  - `sshd`, qui écouterait sur le réseau : il est coupé.
  - `bootc-fetch-apply-updates.timer`, qui redémarrerait le PC tout seul : il est coupé.
  - `sssd` et `systemd-homed` : coupés.
- Les mises à jour restent « téléchargées en arrière-plan, appliquées au prochain
  redémarrage », comme aujourd'hui.

---

## Décision 2 — Le moteur d'affichage : labwc

**Statut :** acceptée · **Date :** 23/11/2026

**Contexte.** Le moteur d'affichage (« compositeur ») place les fenêtres à l'écran et reçoit le
tactile et le stylet. Il faut qu'il soit économe, stable, et qu'il marche au doigt. Tout ce que
tu vois par-dessus (barre, dock, menus) est écrit pour toi.

**Décision.** labwc 0.9 (paquet Fedora). Les fenêtres sont empilées, comme sous GNOME et Windows,
et s'ouvrent en grand comme aujourd'hui.

| Option | Tactile | Autonomie | Stabilité | Remarque |
|---|---|---|---|---|
| **labwc** | bon : choisi par Raspberry Pi pour ses écrans tactiles, clavier à l'écran automatique | très bonne | très bonne | fenêtres empilées : tes habitudes |
| sway | correct | très bonne | très bonne | fenêtres en mosaïque : autre façon de travailler |
| niri | moyen | bonne | bonne | hors des dépôts Fedora |
| écrit maison | inconnu | inconnue | risquée | des mois, sans pouvoir l'essayer sur ton écran tactile |

**Vérifié dans le code de labwc 0.9.6 :**
- prise en charge des claviers à l'écran (méthodes de saisie) ;
- règles de fenêtres ;
- correspondance du tactile et du stylet avec l'écran ;
- liste des fenêtres pour le dock.

Si l'écran de verrouillage plante, labwc garde l'écran caché et accepte un nouvel écran de
verrouillage (« replacing abandoned lock »).

---

## Décision 3 — Le bureau Smoky : Python, GTK 4 et layer-shell

**Statut :** acceptée · **Date :** 23/11/2026

**Décision.** Un programme `smoky-bureau` en Python (comme l'appli Smoky) dessine :
- la barre ;
- le dock ;
- le lanceur ;
- les notifications ;
- les réglages rapides ;
- les bulles de volume et de luminosité.

GTK 4 avec gtk4-layer-shell 1.3 sert à poser ces éléments au bord de l'écran. La liste des
fenêtres passe par un petit client Wayland écrit pour Smoky, en Python pur.

**Pourquoi.**
- GTK gère nativement le tactile, la mise à l'échelle et l'accessibilité.
- Python est déjà la langue de l'appli Smoky.
- Rien ne tourne quand rien ne change.

**Écarté :**
- Une barre en page web : un moteur web ouvert en permanence consomme plus.
- Rust ou C : plus lent à faire évoluer, pour un gain négligeable sur une barre.

**Règles d'autonomie dans le code :**
- aucune minuterie de moins d'une seconde ;
- l'heure est mise à jour une fois par minute, la batterie toutes les 30 s ;
- aucune animation qui tourne en continu ;
- pas de flou calculé en direct.

---

## Décision 4 — L'énergie : un seul chef

**Statut :** acceptée · **Date :** 23/11/2026

**Contexte.** asusd et tuned-ppd se disputaient le profil d'énergie. C'est très probablement ce
qui t'a laissé en « Performance » sur batterie (asusctl le dit dans son manuel, issue #724).

**Décision.**
- `power-profiles-daemon` est le seul à changer de profil, comme le recommande asus-linux.org.
- asusd garde la limite de charge et la carte graphique. Sa gestion des profils est coupée une
  fois pour toutes, avant son démarrage (`change_platform_profile_on_ac/battery: false`,
  `platform_profile_linked_epp: false`).
- Le service `smoky-adaptive` (même nom qu'aujourd'hui) applique la règle :
  - débranché : profil économie, écran à 60 Hz, luminosité plafonnée, Smoky Home en pause ;
  - rebranché : tout revient comme avant.
  Chaque point est réglable.
- La carte NVIDIA : sa coupure complète par le firmware (`dgpu_disable`) s'appliquerait aussi
  à Windows. Elle ne sera activée que si tu le décides.

**Ce qu'on ne fait pas** (recherche du 23/11) : forcer l'ASPM, `powertop --auto-tune` en bloc à
cause du clavier détachable, ou faire tourner deux gestionnaires d'énergie.

---

## Décision 5 — Connexion et verrouillage écrits pour Smoky

**Statut :** acceptée · **Date :** 23/11/2026

**Décision.**
- **Connexion :** greetd (paquet Fedora, avec sa règle SELinux) lance l'écran de connexion
  Smoky, écrit en Python et GTK 4.
  - Il propose ton compte, le mot de passe, l'éteindre et le redémarrer, et « Démarrer
    Windows ».
  - Le mot de passe déverrouille le trousseau comme avant : Mail continue de marcher sans rien
    redemander.
- **Verrouillage :** l'écran de verrouillage Smoky affiche l'heure, la météo et l'état du PC.
  - Il utilise le protocole de verrouillage sûr (ext-session-lock) et vérifie le mot de passe
    par PAM, le même chemin que la connexion.
  - S'il plante, l'écran reste caché et `swaylock` prend le relais : le PC ne reste jamais
    déverrouillé par accident.

---

## Décision 6 — Ce qui est gardé tel quel (et pourquoi)

**Statut :** acceptée · **Date :** 23/11/2026

**Les noms que ton PC utilise.**
- Services, applis (`smoky-*`, `z13-*`), ports (47820 pour l'appli Smoky, 8123 pour Smoky Home)
  et dossiers de données (`~/.config/smoky`, `~/.local/share/smoky`, `~/.config/smoky-home`…).
- Tes données ne bougent pas.

**Le démarrage et Windows.**
- GRUB et « Démarrer Windows » par `next_entry`. Le firmware ASUS refuse les écritures EFI.
- Le service `smoky-gpu`, qui rend l'écran à la puce Intel si Windows a laissé le mode
  Ultimate, et le lui remet en repartant sur Windows. Il est éprouvé et testé (tests/test_gpu.py).
  Il touche au démarrage : on ne le réécrit pas pour le plaisir.

**L'écran de démarrage et la sécurité.**
- L'écran de démarrage Smoky (Plymouth).
- Le pare-feu en zone « public ».
- Les règles polkit limitées.

**Les applis.**
- L'appli Smoky (tâches, notes, mail, agenda, système, maison) reste en place pendant que le
  bureau est refait. Sa réécriture vient après, pour l'intégrer au nouveau bureau.

---

## Décision 7 — Braise, l'OS 100 % maison

**Statut :** acceptée · **Date :** 23/11/2026

**Décision.**
- **Langage et démarrage.** Braise est écrit en C autonome, sans aucune bibliothèque. Il
  démarre directement par le firmware UEFI, comme un programme `BOOTX64.EFI`.
- **Contenu.** Il a sa propre mémoire, ses interruptions, son affichage et sa police dessinée à
  la main, son clavier, ses fenêtres et ses petites applis.
- **Sécurité de ton disque.** Il n'a **aucun pilote de disque**, et n'appelle jamais les
  fonctions d'écriture du firmware : il ne peut physiquement pas toucher à Windows ni à
  Smoky OS.
- **Tests.** Il est d'abord essayé dans une machine virtuelle (QEMU), puis sur clé USB.

**Pourquoi C plutôt que Rust :** l'outil Rust pour UEFI n'est pas téléchargeable depuis l'atelier
de travail. C se compile ici, tout de suite, avec clang.
