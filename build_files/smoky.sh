#!/usr/bin/env bash
# Image finale — réglages de Smoky OS, appliqués par-dessus le socle une fois les fichiers
# de system_files/ copiés (exécuté par le Containerfile).
# Ici : aucun paquet installé, aucun téléchargement. Tout ce qui est lourd ou vient d'Internet
# est dans le socle (build_files/socle/), pour que cette couche reste petite : c'est elle que
# le PC télécharge à chaque mise à jour.
set -euxo pipefail

FEDORA_VER="$(rpm -E %fedora)"
DISTRO_NAME="${DISTRO_NAME:-Smoky OS}"
MOODLE_URL="${MOODLE_URL:-}"
CHROME_FLAGS="--ozone-platform-hint=auto --force-dark-mode --start-maximized --enable-features=TouchpadOverscrollHistoryNavigation,AcceleratedVideoDecodeLinuxGL --enable-wayland-ime"

# --- Droits ------------------------------------------------------------------
# Droits d'exécution : remis ici au cas où ils se perdraient en route (envoi par le site GitHub…)
chmod 755 /usr/bin/smoky-* /usr/bin/z13-notes-setup \
  /usr/libexec/z13os/*.sh /usr/libexec/smokyos/*.sh /usr/libexec/smokyos/*.py /usr/libexec/smokyos/smoky-app \
  /usr/libexec/smokymail/*.py /usr/libexec/smokymail/*.sh \
  /usr/libexec/smokyagenda/server.py /usr/libexec/smokynotes/server.py

# --- Adresse Moodle (variable de dépôt GitHub MOODLE_URL) --------------------------
mkdir -p /etc/smokyos
echo "${MOODLE_URL:-https://moodle.uphf.fr/}" > /etc/smokyos/moodle-url

# --- Google Chrome : réglé pour Wayland et le décodage vidéo par la puce Intel ------
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

# Index des applis par type de lien ou de fichier. Les paquets le recalculent à leur
# installation, mais ils sont installés dans le socle, avant que les raccourcis Smoky
# n'existent : sans cette ligne, le lien « moodlemobile:// » (retour de la connexion Moodle
# de l'université) ne retrouverait plus Smoky Moodle.
update-desktop-database /usr/share/applications
grep -q '^x-scheme-handler/moodlemobile=.*smoky-moodle-auth.desktop' /usr/share/applications/mimeinfo.cache

# Thème d'icônes « Smoky-icons » : chaque appli livrée avec le système reçoit la
# version Smoky de son vrai logo (argent, carré noir, trait néon à sa couleur),
# générée par smoky-autoicons. Les applis installées plus tard (Flatpak : mpv,
# Proton VPN…) sont traitées sur la machine, à la connexion et à chaque installation.
# Dessinés à la main : TF1+, M6+, Moodle, WhatsApp et les applis Smoky (pas de logo d'origine installé).
rm -f /usr/share/icons/Smoky-icons/apps/256/.keep
python3 /usr/libexec/smokyos/smoky-autoicons.py --system /usr/share/icons/Smoky-icons/apps/256
gtk-update-icon-cache -f /usr/share/icons/Smoky-icons || true
gtk-update-icon-cache -f /usr/share/icons/hicolor || true

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
# gresource et glib-compile-resources viennent du socle (10-paquets.sh) : rien à installer ici.
OUTILS=/usr/libexec/smokyos/outils
GR=/usr/share/gnome-shell/gnome-shell-theme.gresource
if [[ -f "$GR" ]]; then
  GW=$(mktemp -d)
  PREFIX=/org/gnome/shell/theme
  for r in $("$OUTILS/gresource" list "$GR"); do
    [[ "$r" == "$PREFIX"/* ]] || { echo "ressource inattendue : $r"; exit 1; }
    mkdir -p "$GW$(dirname "$r")"
    "$OUTILS/gresource" extract "$GR" "$r" > "$GW$r"
  done
  cp /usr/share/backgrounds/z13os/smokyos.jpg "$GW$PREFIX/smoky-login.jpg"
  for css in "$GW$PREFIX"/*.css; do cat /usr/share/smokyos/login-smoky.css >> "$css"; done
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo "<gresources><gresource prefix=\"$PREFIX\">"
    (cd "$GW$PREFIX" && find . -type f | sed 's|^\./||' | sort | sed 's|.*|<file>&</file>|')
    echo '</gresource></gresources>'
  } > "$GW/theme.xml"
  "$OUTILS/glib-compile-resources" --sourcedir="$GW$PREFIX" --target="$GR" "$GW/theme.xml"
  "$OUTILS/gresource" list "$GR" | grep -q smoky-login.jpg
  rm -rf "$GW"
else
  echo "AVERTISSEMENT : thème GNOME Shell introuvable, écran de connexion non personnalisé"
fi

# --- Services ----------------------------------------------------------------
systemctl --global enable smoky-autoicons.path smoky-autoicons.service smoky-moodle.timer smoky-adaptive.service smoky-mail.timer smoky-agenda-reminders.timer smoky-backup-check.timer
systemctl enable supergfxd.service thermald.service fstrim.timer \
  z13-firstboot.service smoky-focus-cleanup.service \
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
# Nom de machine : non réglé par l'image. (L'ancien « echo smokyos > /etc/hostname » n'a jamais
# eu d'effet : pendant la construction, /etc/hostname est prêté par l'outil de construction et
# ce qu'on y écrit ne reste pas dans l'image. Le régler vraiment changerait le nom du PC à la
# mise à jour : à décider à part.)

# --- Ménage ------------------------------------------------------------------
rm -rf /var/cache/* /var/log/* /tmp/*
