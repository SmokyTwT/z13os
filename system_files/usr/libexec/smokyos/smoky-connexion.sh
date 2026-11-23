#!/usr/bin/bash
# Smoky OS — lance l'écran de connexion (compte « greetd », lancé par greetd) : labwc réduit au
# minimum, et l'écran de connexion Smoky. labwc s'arrête quand l'écran de connexion se ferme.
. /usr/libexec/smokyos/smoky-clavier.sh
export XDG_CURRENT_DESKTOP=Smoky XDG_SESSION_TYPE=wayland GSETTINGS_BACKEND=memory
export XCURSOR_THEME=Smoky-cursors XCURSOR_SIZE=32 GTK_THEME=Adwaita:dark
# le compte greetd n'a pas de dossier personnel utilisable : caches en mémoire
export XDG_CACHE_HOME="${XDG_RUNTIME_DIR:-/tmp}/cache" XDG_CONFIG_HOME="${XDG_RUNTIME_DIR:-/tmp}/config"
exec labwc -C /usr/share/smoky-bureau/connexion -S "/usr/bin/python3 -I /usr/libexec/smokyos/smoky-connexion.py"
