#!/usr/bin/env bash
# Construit Smoky OS à l'intérieur de l'image Fedora Silverblue (exécuté par le Containerfile)
set -euxo pipefail

FEDORA_VER="$(rpm -E %fedora)"
DISTRO_NAME="${DISTRO_NAME:-Smoky OS}"
MOODLE_URL="${MOODLE_URL:-}"
CHROME_FLAGS="--ozone-platform-hint=auto --enable-features=TouchpadOverscrollHistoryNavigation,AcceleratedVideoDecodeLinuxGL,AcceleratedVideoDecodeLinuxZeroCopyGL,VaapiVideoDecoder --enable-wayland-ime"

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
dnf -y install asusctl supergfxctl thermald powertop
dnf -y install asusctl-rog-gui || dnf -y install rog-control-center || echo "AVERTISSEMENT : pas d'interface ROG"

# --- Synchro des notes avec Google Drive -------------------------------------
dnf -y install rclone

# --- Google Chrome (s'installe dans /opt : on le déplace dans /usr pour l'image atomique)
mkdir -p /var/opt
dnf -y install google-chrome-stable
mv /var/opt/google /usr/lib/google
printf 'd /var/opt 0755 root root -\nL /var/opt/google - - - - /usr/lib/google\n' > /usr/lib/tmpfiles.d/z13os-chrome.conf
sed -i "s|^Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome-stable ${CHROME_FLAGS}|" \
  /usr/share/applications/google-chrome.desktop

# --- Applis web (streaming, cours, Claude) ------------------------------------
# Icônes : celles du thème WhiteSur quand il en a une, sinon les nôtres (hicolor)
make_webapp() { # id  nom  url  icône  catégories
  local id="$1" name="$2" url="$3" icon="$4" cats="$5"
  cat > "/usr/share/applications/z13-$id.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Exec=/usr/bin/google-chrome-stable ${CHROME_FLAGS} --app=$url --class=z13-$id
Icon=$icon
StartupWMClass=z13-$id
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
make_webapp claude  "Claude"       "https://claude.ai"                claude         "Office;Education;"
FAVS="'smoky-notes.desktop', 'google-chrome.desktop', 'z13-netflix.desktop', 'z13-disney.desktop', 'z13-prime.desktop', 'z13-tf1.desktop', 'z13-m6.desktop', 'com.spotify.Client.desktop'"
if [[ -n "$MOODLE_URL" ]]; then
  make_webapp moodle "Moodle" "$MOODLE_URL" smokyos-moodle "Education;"
  FAVS+=", 'z13-moodle.desktop'"
fi
FAVS+=", 'z13-drive.desktop', 'z13-claude.desktop', 'org.gnome.Nautilus.desktop', 'org.gnome.Ptyxis.desktop'"

# --- Look Smoky : dock + flou statique (calculé une fois, quasi gratuit)
# gsconnect : relie ton téléphone (notifications, fichiers, presse-papiers)
# caffeine : empêche la veille d'un clic (cours en visio, lecture)
for ext in dash-to-dock blur-my-shell appindicator gsconnect caffeine; do
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
# Icône WhiteSur pour Spotify (Flatpak) + caches d'icônes à jour
for t in WhiteSur WhiteSur-dark WhiteSur-light; do
  [[ -f /usr/share/icons/$t/apps/scalable/spotify-client.svg ]] &&
    ln -sf spotify-client.svg /usr/share/icons/$t/apps/scalable/com.spotify.Client.svg
  gtk-update-icon-cache -f /usr/share/icons/$t || true
done
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
icon-theme='WhiteSur'
cursor-theme='WhiteSur-cursors'
accent-color='slate'
color-scheme='prefer-dark'
clock-show-weekday=true

[org.gnome.desktop.wm.preferences]
button-layout='close,minimize,maximize:appmenu'

[org.gnome.desktop.background]
picture-uri='file:///usr/share/backgrounds/z13os/smokyos-light.png'
picture-uri-dark='file:///usr/share/backgrounds/z13os/smokyos-dark.png'
picture-options='zoom'

[org.gnome.desktop.screensaver]
picture-uri='file:///usr/share/backgrounds/z13os/smokyos-dark.png'

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
transparency-mode='FIXED'
background-opacity=0.35
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

[org.gnome.shell]
favorite-apps=[${FAVS}]
enabled-extensions=['dash-to-dock@micxgx.gmail.com', 'blur-my-shell@aunetx', 'appindicatorsupport@rgcjonas.gmail.com', 'user-theme@gnome-shell-extensions.gcampax.github.com', 'gsconnect@andyholmes.github.io', 'caffeine@patapon.info']

[org.gnome.shell.extensions.user-theme]
name='Smoky'
EOF
glib-compile-schemas /usr/share/glib-2.0/schemas

# --- Services ----------------------------------------------------------------
chmod +x /usr/libexec/z13os/*.sh /usr/bin/z13-status /usr/bin/z13-notes-setup /usr/bin/smoky-notes /usr/libexec/smokynotes/server.py
systemctl enable supergfxd.service thermald.service fstrim.timer \
  z13-powertune.service z13-battery-limit.service z13-firstboot.service \
  rpm-ostreed-automatic.timer

# Mises à jour système téléchargées en arrière-plan, appliquées au prochain redémarrage
sed -i 's/^#\?AutomaticUpdatePolicy=.*/AutomaticUpdatePolicy=stage/' /etc/rpm-ostreed.conf
grep -q '^AutomaticUpdatePolicy=' /etc/rpm-ostreed.conf || echo 'AutomaticUpdatePolicy=stage' >> /etc/rpm-ostreed.conf

# --- Identité ----------------------------------------------------------------
sed -i "s|^PRETTY_NAME=.*|PRETTY_NAME=\"${DISTRO_NAME} (Fedora ${FEDORA_VER})\"|" /usr/lib/os-release
echo "smokyos" > /etc/hostname

# --- Ménage ------------------------------------------------------------------
dnf clean all
rm -rf /var/cache/* /var/log/* /tmp/* /var/opt
