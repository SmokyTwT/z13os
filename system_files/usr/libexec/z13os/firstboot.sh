#!/usr/bin/env bash
# Applis Flatpak de Smoky OS (Spotify, mpv, Déjà Dup, Proton VPN) + réglages du premier démarrage.
# Relancé quand la liste change (numéro de version dans /var/lib/z13os/apps.version) :
# les applis ajoutées sont installées, celles retirées de Smoky OS sont désinstallées.
# Chaque appli est installée séparément : un échec n'empêche pas les autres, et le service
# réessaie plus tard (sans tourner en boucle : voir StartLimit dans le service).
set -uo pipefail
APPS_VERSION=2
APPS=(com.spotify.Client io.mpv.Mpv org.gnome.DejaDup com.protonvpn.www)
RETIREES=(com.valvesoftware.Steam)
STATE=/var/lib/z13os
mkdir -p "$STATE"

# Spotify en Wayland dessine lui-même sa barre de titre (boutons bleus de Chromium, hors thème) :
# en XWayland, c'est GNOME qui la dessine, au thème Smoky (net grâce à xwayland-native-scaling).
# Appliqué à chaque démarrage (réglage léger), même quand la liste des applis n'a pas changé.
# (--socket=x11 indispensable : sans Wayland, « fallback-x11 » ne donne pas X11 et Spotify ne s'ouvre plus)
flatpak override --system --nosocket=wayland --socket=x11 com.spotify.Client 2>/dev/null || true

[[ "$(cat "$STATE/apps.version" 2>/dev/null)" == "$APPS_VERSION" ]] && exit 0

flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo || exit 1
flatpak remote-modify --system --enable flathub
failed=0
for app in "${APPS[@]}"; do
  flatpak install --system -y --noninteractive flathub "$app" || { echo "échec : $app"; failed=1; }
done
for app in "${RETIREES[@]}"; do
  if flatpak info --system "$app" >/dev/null 2>&1; then
    flatpak uninstall --system -y --noninteractive "$app" || true
  fi
done
flatpak uninstall --system -y --noninteractive --unused || true
# Les applis Flatpak lisent aussi le thème Smoky (fenêtres noir/argent)
flatpak override --system --filesystem=xdg-config/gtk-4.0:ro --filesystem=xdg-config/gtk-3.0:ro

# Réglages matériels : une seule fois (ensuite, c'est Smoky Center qui décide)
if [[ ! -f "$STATE/firstboot.done" ]]; then
  # La RTX 3050 Ti ne sert pas aux cours ni au streaming : coupée (+ autonomie, - chaleur)
  supergfxctl -m Integrated || true
  # Batterie chargée à 80 % max (durée de vie) ; asusd mémorise le réglage
  asusctl -c 80 || asusctl battery limit 80 || true
fi
[ "$failed" -eq 0 ] || exit 1
touch "$STATE/firstboot.done"
echo "$APPS_VERSION" > "$STATE/apps.version"
