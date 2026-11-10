#!/usr/bin/env bash
# Socle 2/3 — fichiers de tiers, versions figées : rien n'est pris « à la dernière version ».
# Pour mettre à jour l'un d'eux : relire ce qui a changé, puis remplacer sa révision ici.
set -euxo pipefail
shopt -s inherit_errexit

WHITESUR_ICONS_REV=73d8040da51a9ed74e47c7366e7e9ff437601a5c    # tag 2026-09-10
WHITESUR_CURSORS_REV=e190baf618ed95ee217d2fd45589bd309b37672b  # 2025-04-05
DREAME_REV=f5b8472b8e2e4bb3dff7bc2a81a5fd594eca9585            # v2.0.2
XIAOMI_HOME_REV=75b3acb6325a3a8d295688b13904737d6738a6a5       # v0.5.0

# archive DÉPÔT RÉVISION → télécharge l'archive GitHub de cette révision exacte et affiche le
# dossier où elle est extraite
archive() {
  local depot="$1" rev="$2" dir
  dir=$(mktemp -d)
  curl -fsSL --retry 3 --retry-delay 5 -o "$dir/archive.tar.gz" "https://github.com/$depot/archive/$rev.tar.gz"
  tar -xzf "$dir/archive.tar.gz" -C "$dir"
  rm "$dir/archive.tar.gz"
  echo "$dir/${depot##*/}-$rev"
}

# --- Icônes et curseurs WhiteSur (relus avant intégration) ------------------------
src=$(archive vinceliuice/WhiteSur-icon-theme "$WHITESUR_ICONS_REV")
bash "$src/install.sh" -d /usr/share/icons
rm -rf "$(dirname "$src")"
src=$(archive vinceliuice/WhiteSur-cursors "$WHITESUR_CURSORS_REV")
cp -r "$src/dist" /usr/share/icons/WhiteSur-cursors
rm -rf "$(dirname "$src")"
# Seule la variante principale sert (Smoky-icons en hérite) ; les autres ne sont que des liens
rm -rf /usr/share/icons/WhiteSur-dark /usr/share/icons/WhiteSur-light
gtk-update-icon-cache -f /usr/share/icons/WhiteSur || true

# --- Smoky Home : robot Xiaomi/Dreame (avec carte), lumières Tapo, Google Home ---------
# Moteur : Home Assistant en conteneur (etc/containers/systemd/users/smoky-home.container).
mkdir -p /usr/share/smoky-home/custom_components
# Intégration du robot : dreame-vacuum (licence MIT)
src=$(archive Tasshack/dreame-vacuum "$DREAME_REV")
cp -r "$src/custom_components/dreame_vacuum" /usr/share/smoky-home/custom_components/
cp "$src/LICENSE" /usr/share/smoky-home/custom_components/dreame_vacuum/LICENSE
rm -rf "$(dirname "$src")"
# Intégration officielle Xiaomi Home (licence Xiaomi : usage non commercial avec Home Assistant) :
# robots Xiaomi que Dreame Vacuum ne connaît pas (X20 Max = xiaomi.vacuum.d109gl).
# Sa connexion au compte Xiaomi revient sur http://homeassistant.local:8123 (adresse imposée) :
# system_files/etc/hosts fait pointer ce nom vers Smoky Home sur ce PC (jamais un autre appareil
# du réseau). Fichier livré tel quel : pendant la construction, /etc/hosts n'est pas modifiable.
src=$(archive XiaoMi/ha_xiaomi_home "$XIAOMI_HOME_REV")
cp -r "$src/custom_components/xiaomi_home" /usr/share/smoky-home/custom_components/
cp "$src/LICENSE.md" /usr/share/smoky-home/custom_components/xiaomi_home/LICENSE.md
rm -rf "$(dirname "$src")"

rm -rf /var/cache/* /var/log/*
