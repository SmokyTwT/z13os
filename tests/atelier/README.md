# Atelier sans écran

Essais du bureau Smoky qui demandent un vrai moteur d'affichage, sans écran ni machine virtuelle :
labwc tourne en « headless » (sortie virtuelle de 1920×1200), les applis GTK et Chrome s'y affichent,
`grim` fait les captures. Fait pour la session de travail de Claude (Ubuntu 24.04), pas pour l'image.

```bash
bash tests/atelier/preparer.sh   # une fois : paquets, gtk4-layer-shell 1.3.0, labwc 0.7.4
bash tests/atelier/lancer.sh     # tous les essais, avec un résumé
```

| Essai | Ce qu'il vérifie |
|---|---|
| `clavier-session.py` | clavier à l'écran de la session : ses vrais boutons tapent dans un champ GTK (majuscule, chiffre, €, espace, accent, ⌫, ⏎) et ⌄ le range |
| `clavier-tout.py` | les 131 caractères du clavier de session arrivent tels quels (disposition maison, Maj et Alt Gr) |
| `clavier-auto.py` | il sort seul quand un champ GTK prend la main et rentre quand un bouton la reprend (méthode de saisie : labwc 0.7.4) |
| `clavier-externe.py` | avec un vrai clavier branché (faux `/proc/bus/input/devices` : clavier USB derrière un hub), il ne sort pas seul, même en mode tablette ; sorti seul, il se range quand on branche un clavier ; ouvert par le bouton, il reste, sauf si le bouton disparaît (méthode de saisie : labwc 0.7.4) |
| `connexion-clavier.py` | clavier tactile de l'écran de connexion et du verrouillage : mot de passe, ⏎, champ bloqué pendant la vérification |
| `connexion-secours.py`, `verrou-secours.py` | panne simulée de l'affichage complet : l'écran de secours apparaît (champ, clavier tactile qui tape, boutons), l'écran reste verrouillé |
| `connexion-windows.py` | bouton « Windows » de l'écran de connexion : confirmation, demande déposée, réponse affichée, repli |
| `chrome.sh` | Chrome sous Wayland : les 131 caractères et ⏎/⌫ (bons codes de touche), et Chrome signale son champ ; `CAPTURES=1` ajoute des captures du vrai clavier par-dessus Chrome |

`bureau.sh commande…` lance l'atelier (avec le bureau, ou `SANS_BUREAU=1`) puis la commande, et
laisse tout dans `/tmp/atelier` (journaux, `captures/`). `LABWC=…` choisit le labwc : celui du paquet
(0.7.1) n'a pas la méthode de saisie Wayland, celui que construit `preparer.sh` (0.7.4) l'a, comme le
labwc 0.9 de l'image. Vérifié le 25/11/2026 avec Chrome for Testing 153 : Chrome signale ses champs
(text-input-v3) sans aucune option, donc le clavier à l'écran y apparaît seul.
