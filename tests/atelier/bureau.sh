#!/usr/bin/env bash
# Smoky OS — atelier sans écran : labwc headless (1920×1200), bus de session, bureau Smoky, puis la
# commande donnée en arguments, avec WAYLAND_DISPLAY, SMOKY_LIB… déjà prêts. Captures avec grim.
#   SANS_BUREAU=1 : sans le bureau (fond, barre, dock)
#   LABWC=…       : autre labwc (celui de preparer.sh pour la méthode de saisie)
# Les fichiers de l'essai vont dans /tmp/atelier (effacé au début).
set -u
DEPOT=$(cd "$(dirname "$0")/../.." && pwd)
R=$DEPOT/system_files
T=/tmp/atelier; rm -rf "$T"
mkdir -p "$T/xdg" "$T/home/.config/smoky" "$T/home/.local/share/applications" "$T/home/.local/share/themes" "$T/labwc" "$T/captures"
chmod 700 "$T/xdg"
export XDG_RUNTIME_DIR=$T/xdg HOME=$T/home XDG_CONFIG_HOME=$T/home/.config XDG_DATA_HOME=$T/home/.local/share
export LD_LIBRARY_PATH=/usr/local/lib/x86_64-linux-gnu GI_TYPELIB_PATH=/usr/local/lib/x86_64-linux-gnu/girepository-1.0
export SMOKY_LIB=$R/usr/lib/smoky SMOKY_BUREAU_CSS=$R/usr/share/smoky-bureau/bureau.css SMOKY_DEPOT=$DEPOT ATELIER=$T
export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=1 GDK_BACKEND=wayland
export PATH=/usr/bin:$PATH
for a in "Smoky:smoky-appli:applications-office" "Google Chrome:google-chrome:web-browser" \
         "Fichiers:org.gnome.Nautilus:system-file-manager" "Terminal:org.gnome.Ptyxis:utilities-terminal"; do
  IFS=: read -r nom id icone <<<"$a"
  printf '[Desktop Entry]\nType=Application\nName=%s\nExec=true\nIcon=%s\n' "$nom" "$icone" \
    > "$T/home/.local/share/applications/$id.desktop"
done
echo '{"dock": ["smoky-appli.desktop", "google-chrome.desktop", "org.gnome.Nautilus.desktop", "org.gnome.Ptyxis.desktop"]}' \
  > "$T/home/.config/smoky/bureau.json"
cp "$R/usr/share/smoky-bureau/labwc/rc.xml" "$R/usr/share/smoky-bureau/labwc/menu.xml" "$T/labwc/"
: > "$T/labwc/autostart"
cp -r "$R/usr/share/themes/Smoky" "$T/home/.local/share/themes/"
DBUS_SESSION_BUS_ADDRESS=$(dbus-daemon --session --fork --print-address=1 | head -1)
export DBUS_SESSION_BUS_ADDRESS
"${LABWC:-labwc}" -C "$T/labwc" > "$T/labwc.log" 2>&1 &
for _ in $(seq 50); do compgen -G "$XDG_RUNTIME_DIR/wayland-*" > /dev/null && break; sleep 0.1; done
WAYLAND_DISPLAY=$(basename "$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -name 'wayland-*' ! -name '*.lock' | head -1)")
export WAYLAND_DISPLAY
wlr-randr --output HEADLESS-1 --custom-mode 1920x1200 2>> "$T/labwc.log"
if [[ -z "${SANS_BUREAU:-}" ]]; then
  /usr/bin/python3 -I "$R/usr/libexec/smokyos/smoky-bureau.py" > "$T/bureau.log" 2>&1 &
  sleep 4
  grim "$T/captures/bureau.png"
fi
"$@"
