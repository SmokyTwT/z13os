#!/usr/bin/env bash
# =============================================================================
#  Smoky OS — distrib perso basée sur Fedora Workstation (GNOME / Wayland)
#  Cible : ASUS ROG Flow Z13 2022 (GZ301ZE) — i9-12900H + RTX 3050 Ti, tactile
#
#  À lancer APRÈS une installation fraîche de Fedora Workstation, en tant
#  qu'utilisateur normal (pas root) :   bash install.sh
#
#  Options :
#    --nvidia          installe aussi le pilote NVIDIA propriétaire (jeux/CUDA)
#    --moodle URL      adresse de ton Moodle (ex: https://moodle.univ-xxx.fr)
#    --name NOM        nom de ta distrib (défaut : "Smoky OS")
# =============================================================================
set -euo pipefail

DISTRO_NAME="Smoky OS"
MOODLE_URL=""
WITH_NVIDIA=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --nvidia) WITH_NVIDIA=1; shift ;;
    --moodle) MOODLE_URL="$2"; shift 2 ;;
    --name)   DISTRO_NAME="$2"; shift 2 ;;
    *) echo "Option inconnue : $1"; exit 1 ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
  echo "Lance ce script en utilisateur normal (il utilisera sudo quand il faut)."; exit 1
fi
if ! grep -q '^ID=fedora' /etc/os-release; then
  echo "Ce script est prévu pour Fedora Workstation."; exit 1
fi
if [[ -z "$MOODLE_URL" ]]; then
  read -rp "Adresse de ton Moodle (Entrée pour passer) : " MOODLE_URL || true
fi

FEDORA_VER="$(rpm -E %fedora)"
sudo -v
# garde sudo actif pendant toute l'installation
while true; do sudo -n true; sleep 50; kill -0 "$$" || exit; done 2>/dev/null &

# -----------------------------------------------------------------------------
step "1/10  Accélération de dnf + mise à jour complète"
sudo tee /etc/dnf/libdnf5.conf.d/90-z13.conf >/dev/null <<'EOF'
[main]
max_parallel_downloads=10
fastestmirror=True
EOF
sudo dnf upgrade -y --refresh

# -----------------------------------------------------------------------------
step "2/10  Dépôts RPM Fusion + Flathub"
sudo dnf install -y \
  "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${FEDORA_VER}.noarch.rpm" \
  "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${FEDORA_VER}.noarch.rpm"
sudo dnf config-manager setopt fedora-cisco-openh264.enabled=1 || true
flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo
sudo flatpak remote-modify --enable flathub || true

# -----------------------------------------------------------------------------
step "3/10  Codecs complets + décodage vidéo matériel Intel (streaming fluide, batterie)"
sudo dnf swap -y ffmpeg-free ffmpeg --allowerasing
sudo dnf update -y @multimedia --setopt=install_weak_deps=False --exclude=PackageKit-gstreamer-plugin
sudo dnf install -y intel-media-driver libva-utils intel-gpu-tools

# -----------------------------------------------------------------------------
step "4/10  Support ASUS ROG (asusctl, supergfxctl, ROG Control Center)"
sudo dnf copr enable -y lukenukem/asus-linux
sudo dnf install -y asusctl supergfxctl
sudo dnf install -y asusctl-rog-gui 2>/dev/null || sudo dnf install -y rog-control-center 2>/dev/null \
  || warn "Interface graphique ROG non trouvée, asusctl reste utilisable en ligne de commande"
sudo systemctl enable --now supergfxd.service
sudo systemctl start asusd.service 2>/dev/null || true

# -----------------------------------------------------------------------------
step "5/10  GPU : mode économie (Intel seul) ou NVIDIA"
if [[ $WITH_NVIDIA -eq 1 ]]; then
  sudo dnf install -y akmod-nvidia xorg-x11-drv-nvidia-cuda
  if mokutil --sb-state 2>/dev/null | grep -q enabled; then
    warn "Secure Boot actif : au redémarrage, un écran bleu MOK s'affichera."
    warn "Choisis 'Enroll MOK' et tape le mot de passe demandé ci-dessous."
    sudo kmodgenca -a || true
    sudo mokutil --import /etc/pki/akmods/certs/public_key.der
  fi
  sudo akmods --force || true
  supergfxctl -m Hybrid 2>/dev/null || true
else
  # La RTX ne sert à rien pour le streaming : on la coupe → +2 à 3 h d'autonomie
  supergfxctl -m Integrated 2>/dev/null || warn "Mode Integrated appliqué au prochain redémarrage"
fi

# -----------------------------------------------------------------------------
step "6/10  Énergie, thermique, SSD, firmware"
sudo dnf install -y thermald powertop fwupd iio-sensor-proxy
sudo systemctl enable --now thermald.service fstrim.timer
# Limite de charge à 80 % : préserve la batterie (le Z13 reste souvent branché)
asusctl -c 80 2>/dev/null || asusctl battery limit 80 2>/dev/null || true
# Firmware (SSD, Thunderbolt, etc.)
sudo fwupdmgr refresh --force -y >/dev/null 2>&1 || true
sudo fwupdmgr update -y --no-reboot-check 2>/dev/null || true
# Réglages d'économie supplémentaires (audio, PCIe, USB autosuspend) au démarrage
sudo tee /etc/systemd/system/z13-powertune.service >/dev/null <<'EOF'
[Unit]
Description=Smoky OS - réglages d'économie d'énergie
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/bin/sh -c 'echo 1 > /sys/module/snd_hda_intel/parameters/power_save 2>/dev/null; for f in /sys/bus/pci/devices/*/power/control; do echo auto > "$f"; done; true'

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable z13-powertune.service

# -----------------------------------------------------------------------------
step "7/10  Google Chrome (DRM Widevine pour Netflix, Disney+, Prime, TF1+, M6+)"
sudo dnf install -y fedora-workstation-repositories
sudo dnf config-manager setopt google-chrome.enabled=1
sudo dnf install -y google-chrome-stable

# Flags Chrome : Wayland natif (tactile parfait, pinch-zoom, gestes), décodage
# vidéo matériel, retour arrière par glissement
CHROME_FLAGS="--ozone-platform-hint=auto --enable-features=TouchpadOverscrollHistoryNavigation,AcceleratedVideoDecodeLinuxGL,AcceleratedVideoDecodeLinuxZeroCopyGL,VaapiVideoDecoder --enable-wayland-ime"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/z13os"
mkdir -p "$APPS_DIR" "$ICON_DIR"

sed -e "s|^Exec=/usr/bin/google-chrome-stable|Exec=/usr/bin/google-chrome-stable ${CHROME_FLAGS}|" \
  /usr/share/applications/google-chrome.desktop > "$APPS_DIR/google-chrome.desktop"

# -----------------------------------------------------------------------------
step "8/10  Applis : Netflix, Disney+, Prime Video, TF1+, M6+, Moodle, Drive, Claude, Spotify"
make_webapp() { # id  nom  url  domaine-pour-icone
  local id="$1" name="$2" url="$3" domain="$4" icon="web-browser"
  if curl -fsSL --max-time 15 -o "$ICON_DIR/$id.png" \
       "https://www.google.com/s2/favicons?domain=${domain}&sz=256"; then
    icon="$ICON_DIR/$id.png"
  fi
  cat > "$APPS_DIR/z13-$id.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Exec=/usr/bin/google-chrome-stable ${CHROME_FLAGS} --app=$url --class=z13-$id
Icon=$icon
StartupWMClass=z13-$id
Categories=AudioVideo;Video;Network;
Terminal=false
EOF
}
make_webapp netflix  "Netflix"     "https://www.netflix.com/browse"       netflix.com
make_webapp disney   "Disney+"     "https://www.disneyplus.com/fr-fr"     disneyplus.com
make_webapp prime    "Prime Video" "https://www.primevideo.com"           primevideo.com
make_webapp tf1      "TF1+"        "https://www.tf1.fr"                   tf1.fr
make_webapp m6       "M6+"         "https://www.m6.fr"                    m6.fr
make_webapp drive    "Google Drive" "https://drive.google.com"            drive.google.com
make_webapp claude   "Claude"      "https://claude.ai"                    claude.ai
if [[ -n "$MOODLE_URL" ]]; then
  make_webapp moodle "Moodle"      "$MOODLE_URL"                          moodle.org
fi
sed -i 's/^Categories=.*/Categories=Education;Office;/' "$APPS_DIR"/z13-{drive,claude}.desktop
[[ -f "$APPS_DIR/z13-moodle.desktop" ]] && sed -i 's/^Categories=.*/Categories=Education;/' "$APPS_DIR/z13-moodle.desktop"

# Spotify (version officielle via Flathub)
flatpak install -y --noninteractive flathub com.spotify.Client
# Lecteur vidéo local + Rnote (prise de notes au stylet)
flatpak install -y --noninteractive flathub io.mpv.Mpv com.github.flxzt.rnote
update-desktop-database "$APPS_DIR" 2>/dev/null || true

# -----------------------------------------------------------------------------
step "9/10  Claude Code (l'assistant IA en terminal) + Claude en appli web"
sudo dnf install -y git curl
curl -fsSL https://claude.ai/install.sh | bash
grep -q '.local/bin' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

# -----------------------------------------------------------------------------
step "10/10  GNOME optimisé tactile / tablette + identité « ${DISTRO_NAME} »"
# Mise à l'échelle fractionnée (125 %/150 % nettes sur l'écran 13,4")
gsettings set org.gnome.mutter experimental-features "['scale-monitor-framebuffer', 'xwayland-native-scaling']"
# Pavé tactile du clavier détachable
gsettings set org.gnome.desktop.peripherals.touchpad tap-to-click true
gsettings set org.gnome.desktop.peripherals.touchpad natural-scroll true
gsettings set org.gnome.desktop.peripherals.touchpad disable-while-typing true
# Rotation automatique (gyroscope) + luminosité auto
gsettings set org.gnome.settings-daemon.plugins.power ambient-enabled true || true
gsettings set org.gnome.settings-daemon.peripherals.touchscreen orientation-lock false 2>/dev/null || true
# Gros boutons de fenêtre plus faciles au doigt, pourcentage batterie
gsettings set org.gnome.desktop.wm.preferences button-layout 'appmenu:minimize,maximize,close'
gsettings set org.gnome.desktop.interface show-battery-percentage true
gsettings set org.gnome.desktop.interface cursor-size 32
# Profil énergie équilibré par défaut, mise en veille écran après 5 min
gsettings set org.gnome.desktop.session idle-delay 300
# Favoris du dock
FAVS="['google-chrome.desktop', 'z13-netflix.desktop', 'z13-disney.desktop', 'z13-prime.desktop', 'z13-tf1.desktop', 'z13-m6.desktop', 'com.spotify.Client.desktop'"
[[ -f "$APPS_DIR/z13-moodle.desktop" ]] && FAVS+=", 'z13-moodle.desktop'"
FAVS+=", 'z13-drive.desktop', 'z13-claude.desktop', 'org.gnome.Nautilus.desktop', 'org.gnome.Ptyxis.desktop']"
gsettings set org.gnome.shell favorite-apps "$FAVS"

# Google Drive aussi dans le gestionnaire de fichiers (Comptes en ligne GNOME)
sudo dnf install -y gvfs-goa gnome-online-accounts

# Identité
sudo hostnamectl set-hostname smokyos
sudo hostnamectl set-hostname --pretty "$DISTRO_NAME"
sudo tee /etc/motd >/dev/null <<EOF
  ${DISTRO_NAME} — ROG Flow Z13 (GZ301ZE)
  'claude' pour lancer Claude Code  ·  'z13-status' pour l'état de la machine
EOF
sudo tee /usr/local/bin/z13-status >/dev/null <<'EOF'
#!/usr/bin/env bash
echo "GPU      : $(supergfxctl -g 2>/dev/null || echo ?)"
echo "Profil   : $(powerprofilesctl get 2>/dev/null || echo ?)"
echo "Batterie : $(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null)% ($(cat /sys/class/power_supply/BAT0/status 2>/dev/null))"
echo "Limite   : $(cat /sys/class/power_supply/BAT0/charge_control_end_threshold 2>/dev/null)%"
echo "VA-API   : $(vainfo 2>/dev/null | grep -m1 'Driver version' | sed 's/.*: //')"
echo "Noyau    : $(uname -r)"
EOF
sudo chmod +x /usr/local/bin/z13-status

step "Terminé ! Redémarre maintenant :  sudo reboot"
cat <<EOF

Après le redémarrage :
  • Paramètres > Comptes en ligne > Google  → Drive dans Fichiers
  • Ouvre chaque appli de streaming une fois pour te connecter
  • Lance « claude » dans un terminal pour connecter Claude Code
  • Paramètres > Écrans : choisis 125 % ou 150 % et 120 Hz
EOF
