#!/usr/bin/env bash
# Premier démarrage : applis Flatpak (Spotify, mpv, Steam, Déjà Dup) et carte graphique en mode économie.
# Chaque appli est installée séparément : un échec n'empêche pas les autres, et le service
# réessaie plus tard (sans tourner en boucle : voir StartLimit dans le service).
set -uo pipefail
flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo || exit 1
flatpak remote-modify --system --enable flathub
failed=0
for app in com.spotify.Client io.mpv.Mpv com.valvesoftware.Steam org.gnome.DejaDup; do
  flatpak install --system -y --noninteractive flathub "$app" || { echo "échec : $app"; failed=1; }
done
# Les applis Flatpak lisent aussi le thème Smoky (fenêtres noir/argent)
flatpak override --system --filesystem=xdg-config/gtk-4.0:ro --filesystem=xdg-config/gtk-3.0:ro
# La RTX 3050 Ti ne sert pas au streaming : on la coupe (+ autonomie, - chaleur)
supergfxctl -m Integrated || true
# Batterie chargée à 80 % max (durée de vie) ; asusd mémorise le réglage, modifiable dans Smoky Center
asusctl -c 80 || asusctl battery limit 80 || true
[ "$failed" -eq 0 ] || exit 1
mkdir -p /var/lib/z13os
touch /var/lib/z13os/firstboot.done
