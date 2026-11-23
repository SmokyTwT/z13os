#!/usr/bin/env bash
# Socle 1/3 — dépôts et paquets.
# Tout ce qui passe par dnf est ici, et seulement ici : la base des paquets (RPM) ne change
# donc qu'avec le socle, jamais avec une simple mise à jour des fichiers Smoky.
#
# Smoky OS refait de zéro : on part de fedora-bootc, l'image minimale de Fedora (sans bureau),
# et on n'ajoute que ce qui sert. Le bureau est celui de Smoky (labwc + smoky-bureau), pas GNOME.
# Les choix sont expliqués dans docs/refonte/decisions.md.
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
  # --- Matériel du Z13 --------------------------------------------------------
  # microprogrammes absents de fedora-bootc : Wi-Fi AX210, son Intel (SOF) ; pilotes rares
  iwlwifi-mvm-firmware alsa-sof-firmware alsa-ucm kernel-modules-extra
  # microprogramme de la carte NVIDIA : sans lui, le pilote nouveau ne la prend pas en charge et elle
  # resterait allumée (vérifié le 15/11 sur le PC : avec lui, elle dort en D3cold au repos)
  nvidia-gpu-firmware
  # décodage vidéo matériel Intel
  intel-media-driver libva-utils
  # ASUS ROG (limite de charge, carte graphique), température, capteurs (rotation, lumière)
  asusctl supergfxctl thermald iio-sensor-proxy
  # un seul gestionnaire de profils d'énergie (décision 4) + état de la batterie
  power-profiles-daemon upower
  # mises à jour de firmware, mesures d'énergie (powertop sans --auto-tune), diagnostic
  fwupd powertop iw pciutils usbutils
  # mémoire compressée (comme avant)
  zram-generator-defaults
  # écran de démarrage Smoky (Plymouth)
  plymouth plymouth-plugin-script

  # --- Réseau, son, Bluetooth, impression -------------------------------------------
  NetworkManager-wifi NetworkManager-bluetooth NetworkManager-openvpn NetworkManager-openconnect
  firewalld nss-mdns
  pipewire pipewire-pulseaudio pipewire-alsa wireplumber
  bluez cups system-config-printer

  # --- Bureau Smoky -----------------------------------------------------------
  # moteur d'affichage, connexion (avec sa règle SELinux), applis X11 anciennes
  labwc greetd greetd-selinux xorg-x11-server-Xwayland
  # le bureau lui-même est écrit en Python + GTK 4 (barre, dock, connexion, verrouillage)
  gtk4 gtk4-layer-shell python3-gobject python3-pam
  # inactivité, verrouillage de secours, éclairage du soir, écran (fréquence, rotation),
  # captures d'écran, presse-papiers, lecteurs multimédia
  swayidle swaylock wlsunset wlr-randr grim slurp wl-clipboard playerctl libnotify
  # partage d'écran en visio et sélecteur de fichiers pour les applis
  xdg-desktop-portal xdg-desktop-portal-wlr xdg-desktop-portal-gtk
  # trousseau (mots de passe de Mail : jamais dans un fichier), réglages GTK
  gnome-keyring gnome-keyring-pam dconf gsettings-desktop-schemas at-spi2-core
  xdg-user-dirs xdg-utils
  # langue française
  glibc-langpack-fr hunspell-fr
  # polices et icônes de base
  adwaita-sans-fonts adwaita-mono-fonts adwaita-icon-theme google-noto-color-emoji-fonts liberation-fonts

  # --- Applis ----------------------------------------------------------------
  # Fichiers, Terminal, texte, images, PDF, calculatrice ; réglages avancés (Wi-Fi
  # d'entreprise comme eduroam, Bluetooth, son) ; logithèque pour les applis Flatpak
  nautilus gvfs gvfs-mtp ptyxis gnome-text-editor loupe papers gnome-calculator
  nm-connection-editor blueman pavucontrol gnome-software flatpak mate-polkit
  # clavier à l'écran (Stevia, celui de Phosh : s'affiche seul dans un champ de texte en mode tablette)
  stevia
  google-chrome-stable

  # --- Outils déjà utilisés par Smoky --------------------------------------------
  # synchro des notes avec Google Drive ; import des PDF ; trousseau ; redémarrer sur Windows
  rclone zenity poppler-utils libsecret efibootmgr
  # icônes Smoky (smoky-autoicons)
  gtk-update-icon-cache python3-pillow librsvg2-tools
)
dnf -y install "${PAQUETS[@]}"

# Police des titres Smoky (Comfortaa) : paquet Fedora s'il existe ; sinon smoky.sh installe celle
# de l'appli Smoky. Ne bloque pas la construction.
dnf -y install --skip-unavailable aajohan-comfortaa-fonts || true
# Rien n'est désinstallé de fedora-bootc : sssd, par exemple, est référencé par la configuration
# PAM de Fedora. Les services inutiles sont seulement coupés (smoky.sh).

# --- Google Chrome ------------------------------------------------------------------
# Silverblue : /opt pointe vers /var/opt (hors de l'image) → on range Chrome dans /usr.
# fedora-bootc : /opt est un vrai dossier de l'image (en lecture seule sur le PC) → rien à faire.
if [[ -d /var/opt/google ]]; then
  mv /var/opt/google /usr/lib/google
  printf 'd /var/opt 0755 root root -\nL /var/opt/google - - - - /usr/lib/google\n' > /usr/lib/tmpfiles.d/z13os-chrome.conf
fi
test -x /usr/bin/google-chrome-stable

# --- Ménage ------------------------------------------------------------------
dnf clean all
rm -rf /var/cache/* /var/log/* /var/opt
