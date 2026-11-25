#!/usr/bin/bash
# Smoky OS — lance l'écran de connexion (compte « greetd », lancé par greetd) : labwc réduit au
# minimum, et l'écran de connexion Smoky. labwc s'arrête quand l'écran de connexion se ferme.
if [[ "${1:-}" == --dans-labwc ]]; then
  # Dans la session labwc de l'écran de connexion. S'il tombe, il est relancé, puis remplacé par
  # l'écran de secours (mot de passe, clavier tactile, boutons) : on peut toujours entrer au doigt.
  for essai in 1 2; do
    /usr/bin/python3 -I /usr/libexec/smokyos/smoky-connexion.py
    code=$?
    # 0 : ta session est lancée ; 143 : arrêté (SIGTERM) ; autre chose : il est tombé
    if [[ $code -eq 0 || $code -eq 143 ]]; then exit 0; fi
    echo "écran de connexion tombé (code $code, essai $essai)"
    sleep 1
  done
  exec /usr/bin/python3 -I /usr/libexec/smokyos/smoky-connexion.py --secours
fi
. /usr/libexec/smokyos/smoky-clavier.sh
export XDG_CURRENT_DESKTOP=Smoky XDG_SESSION_TYPE=wayland GSETTINGS_BACKEND=memory
export XCURSOR_THEME=Smoky-cursors XCURSOR_SIZE=32 GTK_THEME=Adwaita:dark
# le compte greetd n'a pas de dossier personnel utilisable : caches en mémoire
export XDG_CACHE_HOME="${XDG_RUNTIME_DIR:-/tmp}/cache" XDG_CONFIG_HOME="${XDG_RUNTIME_DIR:-/tmp}/config"
exec labwc -C /usr/share/smoky-bureau/connexion -S "/usr/libexec/smokyos/smoky-connexion.sh --dans-labwc"
