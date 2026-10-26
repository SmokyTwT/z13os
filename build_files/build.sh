#!/usr/bin/env bash
# Construit Z13 OS à l'intérieur de l'image Fedora Silverblue (exécuté par le Containerfile)
set -euxo pipefail

FEDORA_VER="$(rpm -E %fedora)"
DISTRO_NAME="${DISTRO_NAME:-Z13 OS}"
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

# --- Outils de cours ---------------------------------------------------------
dnf -y install xournalpp

# --- Google Chrome (s'installe dans /opt : on le déplace dans /usr pour l'image atomique)
mkdir -p /var/opt
dnf -y install google-chrome-stable
mv /var/opt/google /usr/lib/google
printf 'd /var/opt 0755 root root -\nL /var/opt/google - - - - /usr/lib/google\n' > /usr/lib/tmpfiles.d/z13os-chrome.conf
sed -i "s|^Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome-stable ${CHROME_FLAGS}|" \
  /usr/share/applications/google-chrome.desktop

# --- Applis web (streaming, cours, Claude) ------------------------------------
ICONS=/usr/share/icons/hicolor/256x256/apps
mkdir -p "$ICONS"
make_webapp() { # id  nom  url  domaine-icône  catégories
  local id="$1" name="$2" url="$3" domain="$4" cats="$5" icon="web-browser"
  if curl -fsSL --max-time 20 -o "$ICONS/z13-$id.png" \
       "https://www.google.com/s2/favicons?domain=${domain}&sz=256"; then
    icon="z13-$id"
  fi
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
make_webapp netflix "Netflix"      "https://www.netflix.com/browse"   netflix.com      "AudioVideo;Video;"
make_webapp disney  "Disney+"      "https://www.disneyplus.com/fr-fr" disneyplus.com   "AudioVideo;Video;"
make_webapp prime   "Prime Video"  "https://www.primevideo.com"       primevideo.com   "AudioVideo;Video;"
make_webapp tf1     "TF1+"         "https://www.tf1.fr"               tf1.fr           "AudioVideo;Video;"
make_webapp m6      "M6+"          "https://www.m6.fr"                m6.fr            "AudioVideo;Video;"
make_webapp drive   "Google Drive" "https://drive.google.com"         drive.google.com "Office;Education;"
make_webapp claude  "Claude"       "https://claude.ai"                claude.ai        "Office;Education;"
FAVS="'com.github.flxzt.rnote.desktop', 'google-chrome.desktop', 'z13-netflix.desktop', 'z13-disney.desktop', 'z13-prime.desktop', 'z13-tf1.desktop', 'z13-m6.desktop', 'com.spotify.Client.desktop'"
if [[ -n "$MOODLE_URL" ]]; then
  make_webapp moodle "Moodle" "$MOODLE_URL" "$(echo "$MOODLE_URL" | sed -E 's#^https?://([^/]+).*#\1#')" "Education;"
  FAVS+=", 'z13-moodle.desktop'"
fi
FAVS+=", 'z13-drive.desktop', 'z13-claude.desktop', 'org.gnome.Nautilus.desktop', 'org.gnome.Ptyxis.desktop'"

# --- Réglages GNOME par défaut (tactile / tablette) ----------------------------
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

[org.gnome.desktop.wm.preferences]
button-layout='appmenu:minimize,maximize,close'

[org.gnome.settings-daemon.plugins.power]
ambient-enabled=true

[org.gnome.desktop.session]
idle-delay=uint32 300

[org.gnome.shell]
favorite-apps=[${FAVS}]
EOF
glib-compile-schemas /usr/share/glib-2.0/schemas

# --- Services ----------------------------------------------------------------
chmod +x /usr/libexec/z13os/*.sh /usr/bin/z13-status
systemctl enable supergfxd.service thermald.service fstrim.timer \
  z13-powertune.service z13-battery-limit.service z13-firstboot.service \
  rpm-ostreed-automatic.timer

# Mises à jour système téléchargées en arrière-plan, appliquées au prochain redémarrage
sed -i 's/^#\?AutomaticUpdatePolicy=.*/AutomaticUpdatePolicy=stage/' /etc/rpm-ostreed.conf
grep -q '^AutomaticUpdatePolicy=' /etc/rpm-ostreed.conf || echo 'AutomaticUpdatePolicy=stage' >> /etc/rpm-ostreed.conf

# --- Identité ----------------------------------------------------------------
sed -i "s|^PRETTY_NAME=.*|PRETTY_NAME=\"${DISTRO_NAME} (Fedora ${FEDORA_VER})\"|" /usr/lib/os-release
echo "z13os" > /etc/hostname

# --- Ménage ------------------------------------------------------------------
dnf clean all
rm -rf /var/cache/* /var/log/* /tmp/* /var/opt
