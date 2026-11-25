# Smoky OS refait de zéro — conception

Les choix et leurs raisons sont dans [decisions.md](decisions.md). Ici, ce que fait le système
et comment les morceaux se parlent.

## Ce que le bureau doit faire

**Pour toi :**
- Se connecter au doigt ou au clavier, avec un bouton « Démarrer Windows ».
- Retrouver ton dock (mêmes applis, même ordre) et ton fond d'écran.
- Avoir les fenêtres en grand, et deux fenêtres côte à côte d'un geste ou d'un raccourci.
- En haut : l'heure, la batterie avec le temps restant, le réseau et le son.
- Dans les réglages rapides :
  - Wi-Fi, Bluetooth, son, luminosité ;
  - économie d'énergie, 60/120 Hz, « charger à 100 % une fois » ;
  - tablette, rotation, « ne pas mettre en veille » ;
  - éclairage du soir, et Maison (lumières, robot).
- Des notifications discrètes, avec un historique.
- Un lanceur qui cherche les applis.
- Un écran de verrouillage avec la météo et l'état du PC.
- Un clavier à l'écran maison dans la session (`smokybureau/clavier_ecran.py`, service `smoky-clavier-ecran`, Stevia retiré) : une bande layer-shell en bas qui ne prend jamais le clavier ; les touches partent par un clavier virtuel Wayland (`zwp_virtual_keyboard_v1`) avec sa propre disposition (`commun.keymap_clavier`) : lettres et chiffres à leur place, le reste sur les 4 niveaux (rien, Maj, Alt Gr, Maj + Alt Gr) de touches ordinaires seulement, pour que Chrome, qui lit aussi le code de la touche, ne voie jamais un Ctrl ou une touche inconnue ; donc dans toutes les applis, Chrome compris. Il apparaît par le bouton de la barre, ou tout seul quand un champ de texte prend la main (`zwp_input_method_v2` : applis GTK et Chrome, vérifié avec Chrome 153 dans l'atelier, `tests/atelier/`) si le mode tablette est actif ou le clavier détaché (détecté par `/proc/bus/input/devices`), et jamais quand un vrai clavier est branché à cet instant : celui du Z13 ou un autre, même derrière un hub (corrigé le 25/11 : il sortait en mode tablette avec un clavier externe). Sorti tout seul, il se range dès qu'un vrai clavier arrive ; `smoky-adaptive` revoit aussi le clavier toutes les 10 s, au cas où `/dev/input` n'aurait rien signalé.
- Un clavier tactile intégré à l'écran de connexion et au verrouillage (on peut toujours entrer sans clavier), et la rotation automatique en tablette : mode tablette des réglages rapides, ou clavier détaché (comme Windows sur le Z13 ; « verrouiller la rotation » de Système reste respecté).
- Les boutons de l'écran de connexion disent à l'écran pourquoi ils ont échoué. « Windows » passe par une demande déposée dans `/var/lib/greetd` et exécutée par `smoky-windows-connexion.path` : l'écran de connexion tourne dans le domaine SELinux de greetd (`xdm_t`), qui ne peut pas démarrer de service lui-même.

**Contraintes :**
- **Autonomie.** Rien ne se réveille sans raison. Pas de flou en direct, pas d'animation
  continue. L'heure est mise à jour à la minute, la batterie toutes les 30 s.
- **Tactile.** Les cibles font au moins 44 px.
- **Sûreté.**
  - Un élément qui plante redémarre seul.
  - Le verrouillage tient même si son écran plante.
  - Rien n'écoute sur le réseau, aucun mot de passe n'est stocké.
  - Windows et le démarrage ne sont jamais touchés.

## Les morceaux

```
 démarrage ─► greetd (système)
                 │
                 ├─► labwc « connexion » ─► smoky-connexion        (écran de connexion, GTK 4)
                 │        mot de passe ─► PAM ─► trousseau déverrouillé
                 ▼
            smoky-session ─► labwc (ton bureau, config Smoky)
                               │ au lancement : prévient systemd (variables Wayland)
                               ▼
              systemd --user : smoky-bureau-session.target
               ├─ smoky-bureau.service    barre, dock, lanceur, notifications,
               │                          réglages rapides, bulles, verrouillage
               ├─ smoky-adaptive.service  énergie : batterie ⇄ secteur, rotation, tablette
               ├─ smoky-veille.service    inactivité : atténuer, verrouiller, éteindre l'écran, veille
               ├─ smoky-nuit.service      éclairage du soir (si activé)
               ├─ portails xdg (fichiers, partage d'écran en visio), trousseau, autorisations
               └─ tes applis : Chrome, appli Smoky (port 47820), Fichiers…
```

**Comment ils se parlent :**
- `smoky-bureau` publie un service D-Bus de session, `fr.smoky.Bureau` (lanceur, bulle,
  verrouiller, état). La commande `smoky-bureau-cmd` l'appelle ; les raccourcis de labwc
  passent par elle.
- La liste des fenêtres (pour le dock) et l'extinction de l'écran passent par le client Wayland
  maison `smoky/bureau/wayland.py`, avec les protocoles wlr foreign-toplevel et output-power.
- Pour l'énergie :
  - power-profiles-daemon et UPower par D-Bus ;
  - `wlr-randr` pour la fréquence et la rotation ;
  - logind pour la luminosité, sans droits administrateur ;
  - asusd pour la limite de charge.
- Pour le réseau, le Bluetooth et le son : NetworkManager (`nmcli`), BlueZ (D-Bus) et PipeWire
  (`wpctl`), seulement quand on ouvre les réglages rapides ou qu'on appuie sur une touche.

**Réglages et données :**
- `~/.config/smoky/bureau.json` : dock, options du bureau.
- `~/.config/smoky/adaptive.json` : énergie et tablette (fichier existant, mêmes clés).
- `~/.config/smoky/meteo.json` : lieu de la météo (fichier existant).
- **Migration une seule fois**, à la première connexion au nouveau bureau : les favoris du dock
  GNOME (`/org/gnome/shell/favorite-apps`) deviennent ceux du dock Smoky. Ton fond d'écran
  personnel est repris s'il en avait un.

## Quand quelque chose plante

| Ce qui tombe | Ce qui se passe |
|---|---|
| `smoky-bureau` | systemd le relance (3 fois en 30 s au plus). Les fenêtres restent ouvertes. |
| L'écran de verrouillage | labwc garde l'écran caché. Smoky relance l'écran de verrouillage, puis `swaylock` en secours. |
| labwc lui-même | retour à l'écran de connexion. Les fichiers enregistrés sont intacts. |
| L'écran de connexion | greetd le relance. |
| Toute l'image | au démarrage, le menu GRUB propose la version précédente (retour arrière). |

## Comment on l'essaie sans risque

1. Tout est construit sur la branche `zero`. GitHub vérifie l'image et la démarre deux fois en
   machine virtuelle.
2. L'image d'essai est publiée sous l'étiquette `test`, jamais `latest`. Ton PC ne la reçoit
   pas tout seul.
3. Pour l'essayer, une commande fait passer ton PC sur `test`, et une autre le ramène sur
   `latest`. Avant ça, on épingle ta version actuelle pour qu'elle reste dans le menu de
   démarrage.
4. Quand tu es satisfait, et seulement avec ton accord, ça part sur `main`.

## Les lots

| Lot | Contenu |
|---|---|
| 1 | Nouvelle base (fedora-bootc), énergie à un seul chef, greetd et connexion, session labwc, barre et dock, verrouillage. Démarre en VM. |
| 2 | Lanceur, notifications, réglages rapides complets, bulles, veille et extinction de l'écran. |
| 3 | Clavier à l'écran, rotation, mode tablette automatique. |
| 4 | Migration du dock et des réglages, essai sur ton PC. |
| 5 | Réécriture de l'appli Smoky, intégrée au bureau (recherche unifiée, notifications natives). |

## Ce qu'on revisitera

- **Carte NVIDIA :** passer à la coupure complète (`dgpu_disable`) si tu l'acceptes. C'est le
  plus gros gain restant.
- **Mesures sur ton PC :** `powertop` et `smoky-diagnostic --energie` sur batterie, pour régler
  la suite sur des chiffres.
- **Zone de notification** (icônes de Proton VPN, Discord…) : à ajouter si tu en utilises.
