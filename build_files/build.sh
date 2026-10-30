#!/usr/bin/env bash
# Construit Smoky OS à l'intérieur de l'image Fedora Silverblue (exécuté par le Containerfile)
set -euxo pipefail

FEDORA_VER="$(rpm -E %fedora)"
DISTRO_NAME="${DISTRO_NAME:-Smoky OS}"
MOODLE_URL="${MOODLE_URL:-}"
CHROME_FLAGS="--ozone-platform-hint=auto --force-dark-mode --start-maximized --enable-features=TouchpadOverscrollHistoryNavigation,AcceleratedVideoDecodeLinuxGL --enable-wayland-ime"

# --- Dépôts ------------------------------------------------------------------
dnf -y install \
  "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${FEDORA_VER}.noarch.rpm" \
  "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${FEDORA_VER}.noarch.rpm"

curl -fsSL -o /etc/yum.repos.d/asus-linux.repo \
  "https://copr.fedorainfracloud.org/coprs/lukenukem/asus-linux/repo/fedora-${FEDORA_VER}/lukenukem-asus-linux-fedora-${FEDORA_VER}.repo"

cat > /etc/yum.repos.d/google-chrome.repo <<'EOF'
[google-chrome]
name=google-chrome
baseurl=https://dl.google.com/linux/chrome/rpm/stable/x86_64
enabled=1
gpgcheck=1
gpgkey=https://dl.google.com/linux/linux_signing_key.pub
EOF

# --- Codecs complets + décodage vidéo matériel Intel ---------------------------
dnf -y install --allowerasing ffmpeg
dnf -y install intel-media-driver libva-utils

# --- Support ASUS ROG + énergie ----------------------------------------------
dnf -y install asusctl supergfxctl thermald
# (pas d'interface ROG Control Center : Smoky Center fait la même chose sans tourner en arrière-plan)

# --- Allègement : Firefox fait doublon avec Chrome, la visite guidée ne sert qu'une fois
dnf -y remove firefox firefox-langpacks gnome-tour || true

# --- Synchro des notes avec Google Drive -------------------------------------
dnf -y install rclone zenity

# --- Smoky Moodle (import des PDF de cours, échéances) : pdfinfo + trousseau GNOME
dnf -y install poppler-utils libsecret
# redémarrer sur Windows depuis Smoky Center (double démarrage)
dnf -y install efibootmgr
mkdir -p /etc/smokyos
echo "${MOODLE_URL:-https://moodle.uphf.fr/}" > /etc/smokyos/moodle-url

# --- Google Chrome (s'installe dans /opt : on le déplace dans /usr pour l'image atomique)
mkdir -p /var/opt
dnf -y install google-chrome-stable
mv /var/opt/google /usr/lib/google
printf 'd /var/opt 0755 root root -\nL /var/opt/google - - - - /usr/lib/google\n' > /usr/lib/tmpfiles.d/z13os-chrome.conf
sed -i "s|^Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome-stable ${CHROME_FLAGS}|" \
  /usr/share/applications/google-chrome.desktop

# --- Applis web (streaming, cours, messagerie, Claude) -------------------------
# Icônes : celles du thème WhiteSur quand il en a une, sinon les nôtres (hicolor)
# Sous Wayland, Chrome ignore --class pour une fenêtre --app : il la nomme
# « chrome-<hôte>_<chemin>-Default ». StartupWMClass doit porter ce nom exact, sinon
# GNOME ne relie pas la fenêtre à son icône et en ajoute une seconde dans le dock.
chrome_app_id() { # url → identifiant de fenêtre Wayland de Chrome
  local rest="${1#*://}" host path
  host="${rest%%/*}"; host="${host%%:*}"
  [[ "$rest" == */* ]] && path="/${rest#*/}" || path="/"
  path="${path%%\?*}"; path="${path%%#*}"
  echo "chrome-${host}_${path//\//_}-Default"
}
# Appli web dans son propre profil Chrome (processus à part) : sa fenêtre n'est jamais rattachée
# à Chrome, ni à une version « installée » du site par Chrome (claude.ai propose de s'installer).
cat > /usr/libexec/smokyos/smoky-webapp <<EOF
#!/usr/bin/bash
id="\$1" url="\$2"; shift 2
exec /usr/bin/google-chrome-stable ${CHROME_FLAGS} --no-first-run --no-default-browser-check \\
  --user-data-dir="\${XDG_DATA_HOME:-\$HOME/.local/share}/smoky-webapps/\$id" --app="\$url" "\$@"
EOF
chmod 755 /usr/libexec/smokyos/smoky-webapp
make_webapp() { # id  nom  url  icône  catégories  [solo = profil Chrome à part]
  local id="$1" name="$2" url="$3" icon="$4" cats="$5" exec
  if [[ "${6:-}" == solo ]]; then
    exec="/usr/libexec/smokyos/smoky-webapp $id $url"
  else
    exec="/usr/bin/google-chrome-stable ${CHROME_FLAGS} --app=$url --class=z13-$id"
  fi
  cat > "/usr/share/applications/z13-$id.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Exec=$exec
Icon=$icon
StartupWMClass=$(chrome_app_id "$url")
Categories=$cats
Terminal=false
EOF
}
make_webapp netflix "Netflix"      "https://www.netflix.com/browse"   netflix        "AudioVideo;Video;"
make_webapp disney  "Disney+"      "https://www.disneyplus.com/fr-fr" disney         "AudioVideo;Video;"
make_webapp prime   "Prime Video"  "https://www.primevideo.com"       primevideo     "AudioVideo;Video;"
make_webapp tf1     "TF1+"         "https://www.tf1.fr"               smokyos-tf1    "AudioVideo;Video;"
make_webapp m6      "M6+"          "https://www.m6.fr"                smokyos-m6     "AudioVideo;Video;"
make_webapp drive   "Google Drive" "https://drive.google.com"         google-drive   "Office;Education;"
# Spotify en appli web : l'appli Flatpak dessinait une barre de titre bleue impossible à thémer
make_webapp spotify "Spotify"      "https://open.spotify.com"         smokyos-spotify "AudioVideo;Audio;Music;Player;"
make_webapp whatsapp "WhatsApp"    "https://web.whatsapp.com"         smokyos-whatsapp "Network;InstantMessaging;Chat;"
make_webapp claude  "Claude"       "https://claude.ai"                claude         "Office;Education;" solo
FAVS="'smoky-notes.desktop', 'google-chrome.desktop', 'z13-netflix.desktop', 'z13-disney.desktop', 'z13-prime.desktop', 'z13-tf1.desktop', 'z13-m6.desktop', 'z13-spotify.desktop', 'z13-whatsapp.desktop', 'smoky-mail.desktop', 'smoky-agenda.desktop'"
if [[ -n "$MOODLE_URL" ]]; then
  make_webapp moodle "Moodle" "$MOODLE_URL" smokyos-moodle "Education;"
  FAVS+=", 'z13-moodle.desktop'"
fi
FAVS+=", 'z13-drive.desktop', 'z13-claude.desktop', 'smoky-home.desktop', 'smoky-center.desktop', 'org.gnome.Nautilus.desktop', 'org.gnome.Ptyxis.desktop'"

# --- Look Smoky : dock + flou statique (calculé une fois, quasi gratuit)
# caffeine : empêche la veille d'un clic (cours en visio, lecture)
for ext in dash-to-dock blur-my-shell appindicator caffeine; do
  dnf -y install "gnome-shell-extension-$ext" || echo "AVERTISSEMENT : extension $ext indisponible"
done

# Icônes et curseurs WhiteSur, versions figées (relues avant intégration)
WHITESUR_ICONS_REV=73d8040da51a9ed74e47c7366e7e9ff437601a5c    # tag 2026-09-10
WHITESUR_CURSORS_REV=e190baf618ed95ee217d2fd45589bd309b37672b  # 2025-04-05
dnf -y install gtk-update-icon-cache
WS=$(mktemp -d)
curl -fsSL "https://github.com/vinceliuice/WhiteSur-icon-theme/archive/${WHITESUR_ICONS_REV}.tar.gz" | tar -xz -C "$WS"
bash "$WS/WhiteSur-icon-theme-${WHITESUR_ICONS_REV}/install.sh" -d /usr/share/icons
curl -fsSL "https://github.com/vinceliuice/WhiteSur-cursors/archive/${WHITESUR_CURSORS_REV}.tar.gz" | tar -xz -C "$WS"
cp -r "$WS/WhiteSur-cursors-${WHITESUR_CURSORS_REV}/dist" /usr/share/icons/WhiteSur-cursors
rm -rf "$WS"
# Seule la variante principale sert (Smoky-icons en hérite) ; les autres ne sont que des liens
rm -rf /usr/share/icons/WhiteSur-dark /usr/share/icons/WhiteSur-light
gtk-update-icon-cache -f /usr/share/icons/WhiteSur || true

# Thème d'icônes « Smoky-icons » : chaque appli livrée avec le système reçoit la
# version Smoky de son vrai logo (argent, carré noir, trait néon à sa couleur),
# générée par smoky-autoicons. Les applis installées plus tard (Flatpak : mpv,
# Proton VPN…) sont traitées sur la machine, à la connexion et à chaque installation.
# Dessinés à la main : TF1+, M6+, Moodle, WhatsApp et les applis Smoky (pas de logo d'origine installé).
dnf -y install python3-pillow librsvg2-tools
rm -f /usr/share/icons/Smoky-icons/apps/256/.keep
python3 /usr/libexec/smokyos/smoky-autoicons.py --system /usr/share/icons/Smoky-icons/apps/256
gtk-update-icon-cache -f /usr/share/icons/Smoky-icons || true
gtk-update-icon-cache -f /usr/share/icons/hicolor || true

# Thème « Smoky » du centre de contrôle (fichier CSS dans system_files)
dnf -y install gnome-shell-extension-user-theme

# --- Réglages GNOME par défaut (tactile / tablette + look) --------------------
cat > /usr/share/glib-2.0/schemas/zz1-z13os.gschema.override <<EOF
[org.gnome.mutter]
experimental-features=['scale-monitor-framebuffer', 'xwayland-native-scaling']

[org.gnome.desktop.peripherals.touchpad]
tap-to-click=true
natural-scroll=true
disable-while-typing=true

[org.gnome.desktop.interface]
show-battery-percentage=true
cursor-size=32
icon-theme='Smoky-icons'
cursor-theme='Smoky-cursors'
accent-color='slate'
color-scheme='prefer-dark'
clock-show-weekday=true

[org.gnome.desktop.wm.preferences]
button-layout='close,minimize,maximize:appmenu'

[org.gnome.desktop.background]
picture-uri='file:///usr/share/backgrounds/z13os/smokyos.jpg'
picture-uri-dark='file:///usr/share/backgrounds/z13os/smokyos.jpg'
picture-options='zoom'

[org.gnome.desktop.screensaver]
picture-uri='file:///usr/share/backgrounds/z13os/smokyos.jpg'

[org.gnome.shell.extensions.dash-to-dock]
dock-position='BOTTOM'
dock-fixed=false
intellihide=true
extend-height=false
dash-max-icon-size=52
show-apps-at-top=false
show-trash=false
show-mounts=false
running-indicator-style='DOTS'
custom-theme-customize-running-dots=true
custom-theme-running-dots-color='#ffffff'
transparency-mode='DEFAULT'
apply-custom-theme=false
custom-theme-shrink=true
click-action='minimize-or-previews'

[org.gnome.shell.extensions.blur-my-shell.panel]
blur=true
static-blur=true

[org.gnome.shell.extensions.blur-my-shell.dash-to-dock]
blur=true
static-blur=true

[org.gnome.shell.extensions.blur-my-shell.overview]
blur=true

[org.gnome.shell.extensions.blur-my-shell.appfolder]
blur=true

[org.gnome.shell.extensions.blur-my-shell.applications]
blur=false

[org.gnome.settings-daemon.plugins.power]
ambient-enabled=true

[org.gnome.desktop.session]
idle-delay=uint32 300

[org.gnome.desktop.notifications]
show-in-lock-screen=false

[org.gnome.shell]
favorite-apps=[${FAVS}]
enabled-extensions=['dash-to-dock@micxgx.gmail.com', 'blur-my-shell@aunetx', 'appindicatorsupport@rgcjonas.gmail.com', 'user-theme@gnome-shell-extensions.gcampax.github.com', 'caffeine@patapon.info', 'smoky-maximize@smokyos', 'smoky-home@smokyos', 'smoky-tablet@smokyos', 'smoky-lockinfo@smokyos']

[org.gnome.shell.extensions.user-theme]
name='Smoky'

[org.gnome.Ptyxis.Profile]
palette-id='smoky'
EOF
glib-compile-schemas /usr/share/glib-2.0/schemas

# --- Smoky Home : robot Xiaomi/Dreame (avec carte), lumières Tapo, Google Home ---
# Moteur : Home Assistant en conteneur (etc/containers/systemd/users/smoky-home.container).
# Intégration du robot : dreame-vacuum (licence MIT), version figée.
DREAME_REV=f5b8472b8e2e4bb3dff7bc2a81a5fd594eca9585   # v2.0.2
mkdir -p /usr/share/smoky-home/custom_components
DV=$(mktemp -d)
curl -fsSL "https://github.com/Tasshack/dreame-vacuum/archive/${DREAME_REV}.tar.gz" | tar -xz -C "$DV"
cp -r "$DV/dreame-vacuum-${DREAME_REV}/custom_components/dreame_vacuum" /usr/share/smoky-home/custom_components/
cp "$DV/dreame-vacuum-${DREAME_REV}/LICENSE" /usr/share/smoky-home/custom_components/dreame_vacuum/LICENSE
rm -rf "$DV"
# Intégration officielle Xiaomi Home (licence Xiaomi : usage non commercial avec Home Assistant),
# version figée : robots Xiaomi que Dreame Vacuum ne connaît pas (X20 Max = xiaomi.vacuum.d109gl).
XIAOMI_HOME_REV=75b3acb6325a3a8d295688b13904737d6738a6a5   # v0.5.0
XH=$(mktemp -d)
curl -fsSL "https://github.com/XiaoMi/ha_xiaomi_home/archive/${XIAOMI_HOME_REV}.tar.gz" | tar -xz -C "$XH"
cp -r "$XH/ha_xiaomi_home-${XIAOMI_HOME_REV}/custom_components/xiaomi_home" /usr/share/smoky-home/custom_components/
cp "$XH/ha_xiaomi_home-${XIAOMI_HOME_REV}/LICENSE.md" /usr/share/smoky-home/custom_components/xiaomi_home/LICENSE.md
rm -rf "$XH"
# Sa connexion au compte Xiaomi revient sur http://homeassistant.local:8123 (adresse imposée) :
# system_files/etc/hosts fait pointer ce nom vers Smoky Home sur ce PC (jamais un autre appareil
# du réseau). Fichier livré tel quel : pendant la construction, /etc/hosts n'est pas modifiable.

# --- Pare-feu ------------------------------------------------------------------
# Fedora ouvre par défaut les ports 1025-65535 (zone FedoraWorkstation). Sur des Wi-Fi
# publics, on passe en zone « public » : rien n'est joignable depuis le réseau, sauf la
# découverte locale (mDNS : Google Home, Chromecast).
# Smoky Notes et Smoky Home (port 8123) ne sont donc accessibles que depuis ce PC.
firewall-offline-cmd --set-default-zone=public
firewall-offline-cmd --zone=public --remove-service=ssh || true

# --- Écran de connexion Smoky (GDM) ----------------------------------------------
# L'écran de connexion n'utilise pas les thèmes utilisateur : on ajoute le fond « smoky »
# et le style néon (usr/share/smokyos/login-smoky.css) dans le thème intégré de GNOME Shell.
GR=/usr/share/gnome-shell/gnome-shell-theme.gresource
if [[ -f "$GR" ]]; then
  dnf -y install glib2-devel          # glib-compile-resources, retiré juste après
  GW=$(mktemp -d)
  PREFIX=/org/gnome/shell/theme
  for r in $(gresource list "$GR"); do
    [[ "$r" == "$PREFIX"/* ]] || { echo "ressource inattendue : $r"; exit 1; }
    mkdir -p "$GW$(dirname "$r")"
    gresource extract "$GR" "$r" > "$GW$r"
  done
  cp /usr/share/backgrounds/z13os/smokyos.jpg "$GW$PREFIX/smoky-login.jpg"
  for css in "$GW$PREFIX"/*.css; do cat /usr/share/smokyos/login-smoky.css >> "$css"; done
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo "<gresources><gresource prefix=\"$PREFIX\">"
    (cd "$GW$PREFIX" && find . -type f | sed 's|^\./||' | sort | sed 's|.*|<file>&</file>|')
    echo '</gresource></gresources>'
  } > "$GW/theme.xml"
  glib-compile-resources --sourcedir="$GW$PREFIX" --target="$GR" "$GW/theme.xml"
  gresource list "$GR" | grep -q smoky-login.jpg
  rm -rf "$GW"
  dnf -y remove glib2-devel || true
else
  echo "AVERTISSEMENT : thème GNOME Shell introuvable, écran de connexion non personnalisé"
fi

# --- Écran de démarrage Smoky (Plymouth) ------------------------------------------
dnf -y install plymouth-plugin-script
plymouth-set-default-theme smoky
KVER=$(ls /usr/lib/modules | head -1)
dracut --no-hostonly --kver "$KVER" --reproducible --zstd -v --add ostree -f "/usr/lib/modules/$KVER/initramfs.img"

# --- Services ----------------------------------------------------------------
chmod +x /usr/libexec/z13os/*.sh /usr/bin/z13-notes-setup /usr/bin/smoky-notes /usr/bin/smoky-home /usr/bin/smoky-portail /usr/bin/smoky-center /usr/bin/smoky-mail /usr/libexec/smokymail/*.py /usr/libexec/smokymail/*.sh \
  /usr/bin/smoky-agenda /usr/libexec/smokyagenda/server.py \
  /usr/libexec/smokynotes/server.py /usr/libexec/smokyos/*.py /usr/libexec/smokyos/*.sh
systemctl --global enable smoky-autoicons.path smoky-autoicons.service smoky-moodle.timer smoky-adaptive.service smoky-mail.timer smoky-agenda-reminders.timer smoky-backup-check.timer
systemctl enable supergfxd.service thermald.service fstrim.timer \
  z13-powertune.service z13-firstboot.service smoky-focus-cleanup.service \
  rpm-ostreed-automatic.timer smoky-flatpak-update.timer

# --- Autonomie ----------------------------------------------------------------------------------
# Pas de modem 4G/5G sur le Z13 : ModemManager ne sert à rien
systemctl mask ModemManager.service || true
# GNOME Logiciels ne reste plus ouvert en permanence en arrière-plan (≈ 150 Mo de mémoire, réveils
# réguliers) : les applis se mettent à jour une fois par jour, sur secteur (smoky-flatpak-update),
# et le système via rpm-ostree. L'appli Logiciels reste utilisable normalement.
if [[ -f /etc/xdg/autostart/org.gnome.Software.desktop ]]; then
  grep -q '^Hidden=true' /etc/xdg/autostart/org.gnome.Software.desktop || \
    sed -i '/^\[Desktop Entry\]/a Hidden=true' /etc/xdg/autostart/org.gnome.Software.desktop
fi

# Mises à jour système téléchargées en arrière-plan, appliquées au prochain redémarrage
sed -i 's/^#\?AutomaticUpdatePolicy=.*/AutomaticUpdatePolicy=stage/' /etc/rpm-ostreed.conf
grep -q '^AutomaticUpdatePolicy=' /etc/rpm-ostreed.conf || echo 'AutomaticUpdatePolicy=stage' >> /etc/rpm-ostreed.conf

# --- Identité ----------------------------------------------------------------
sed -i "s|^PRETTY_NAME=.*|PRETTY_NAME=\"${DISTRO_NAME} (Fedora ${FEDORA_VER})\"|" /usr/lib/os-release
echo "smokyos" > /etc/hostname

# --- Ménage ------------------------------------------------------------------
dnf clean all
rm -rf /var/cache/* /var/log/* /tmp/* /var/opt
