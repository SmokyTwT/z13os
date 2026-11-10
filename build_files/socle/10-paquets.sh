#!/usr/bin/env bash
# Socle 1/3 — dépôts et paquets.
# Tout ce qui passe par dnf est ici, et seulement ici : la base des paquets (RPM) ne change
# donc qu'avec le socle, jamais avec une simple mise à jour des fichiers Smoky.
set -euxo pipefail

FEDORA_VER="$(rpm -E %fedora)"

# --- Dépôts ------------------------------------------------------------------
dnf -y install \
  "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${FEDORA_VER}.noarch.rpm" \
  "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${FEDORA_VER}.noarch.rpm"

curl -fsSL --retry 3 --retry-delay 5 -o /etc/yum.repos.d/asus-linux.repo \
  "https://copr.fedorainfracloud.org/coprs/lukenukem/asus-linux/repo/fedora-${FEDORA_VER}/lukenukem-asus-linux-fedora-${FEDORA_VER}.repo"

cat > /etc/yum.repos.d/google-chrome.repo <<'REPO'
[google-chrome]
name=google-chrome
baseurl=https://dl.google.com/linux/chrome/rpm/stable/x86_64
enabled=1
gpgcheck=1
gpgkey=https://dl.google.com/linux/linux_signing_key.pub
REPO

# --- Codecs complets ---------------------------------------------------------
# ffmpeg (RPM Fusion) remplace la version réduite de Fedora : --allowerasing, limité à ce paquet
dnf -y install --allowerasing ffmpeg

# --- Tous les autres paquets, en une seule transaction -------------------------
# Chrome s'installe dans /opt, qui est /var/opt sur une image atomique : le dossier doit exister
mkdir -p /var/opt
PAQUETS=(
  # décodage vidéo matériel Intel
  intel-media-driver libva-utils
  # support ASUS ROG + énergie (pas d'interface ROG Control Center : Smoky Center fait la même
  # chose sans tourner en arrière-plan)
  asusctl supergfxctl thermald
  # synchro des notes avec Google Drive
  rclone zenity
  # Smoky Moodle (import des PDF de cours, échéances) : pdfinfo + trousseau GNOME
  poppler-utils libsecret
  # redémarrer sur Windows depuis Smoky Center (double démarrage)
  efibootmgr
  google-chrome-stable
  # icônes Smoky (smoky-autoicons) et thème du centre de contrôle
  gtk-update-icon-cache python3-pillow librsvg2-tools gnome-shell-extension-user-theme
  # écran de démarrage Smoky (Plymouth)
  plymouth-plugin-script
  # gresource + glib-compile-resources (thème de l'écran de connexion) : gardés à part, puis paquet retiré
  glib2-devel
)
dnf -y install "${PAQUETS[@]}"

# Look Smoky : dock, flou statique (calculé une fois, quasi gratuit), zone de notification,
# caffeine (empêche la veille d'un clic : cours en visio, lecture). Une extension absente des
# dépôts ne bloque pas la construction : elle est signalée.
EXTENSIONS=(dash-to-dock blur-my-shell appindicator caffeine)
dnf -y install --skip-unavailable --skip-broken "${EXTENSIONS[@]/#/gnome-shell-extension-}"
for ext in "${EXTENSIONS[@]}"; do
  rpm -q "gnome-shell-extension-$ext" >/dev/null || echo "AVERTISSEMENT : extension $ext indisponible"
done

# --- Outils de construction gardés pour l'image finale ---------------------------
# Le thème de l'écran de connexion est recompilé à chaque image (smoky.sh). On garde les deux
# seuls programmes nécessaires (lire et écrire un fichier .gresource), pour que l'image finale
# n'ait jamais à installer de paquet.
for outil in gresource glib-compile-resources; do
  install -Dm755 "/usr/bin/$outil" "/usr/libexec/smokyos/outils/$outil"
done
dnf -y remove glib2-devel
/usr/libexec/smokyos/outils/gresource list /usr/share/gnome-shell/gnome-shell-theme.gresource >/dev/null

# --- Allègement : Firefox fait doublon avec Chrome, la visite guidée ne sert qu'une fois
dnf -y remove firefox firefox-langpacks gnome-tour || true

# --- Google Chrome : déplacé de /opt vers /usr (image atomique) -------------------
mv /var/opt/google /usr/lib/google
printf 'd /var/opt 0755 root root -\nL /var/opt/google - - - - /usr/lib/google\n' > /usr/lib/tmpfiles.d/z13os-chrome.conf

# --- Ménage ------------------------------------------------------------------
dnf clean all
rm -rf /var/cache/* /var/log/* /var/opt
