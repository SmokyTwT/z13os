#!/usr/bin/env bash
# Smoky OS — prépare l'atelier sans écran (Ubuntu 24.04, comme la session de travail de Claude).
# Installe labwc 0.7.1 (paquet), grim et le reste ; construit gtk4-layer-shell 1.3.0 (avec
# gtk4-session-lock) dans /usr/local, et labwc 0.7.4 (méthode de saisie : text-input-v3 et
# input-method-v2, absents de la 0.7.1). Versions épinglées par leur étiquette. Rien n'est lancé.
set -euo pipefail
SOURCES=${ATELIER_SOURCES:-/var/tmp/atelier}
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q --no-install-recommends labwc grim wlr-randr dbus dbus-x11 imagemagick curl git \
  python3-gi gir1.2-gtk-4.0 libgtk-4-dev gobject-introspection libgirepository1.0-dev libxkbcommon0 \
  meson ninja-build pkg-config libwlroots-dev wayland-protocols libwayland-dev libxkbcommon-dev libxml2-dev \
  libcairo2-dev libpango1.0-dev libglib2.0-dev libinput-dev libpixman-1-dev libpng-dev libdrm-dev
mkdir -p "$SOURCES"

if [[ ! -e /usr/local/lib/x86_64-linux-gnu/libgtk4-layer-shell.so.1.3.0 ]]; then
  rm -rf "$SOURCES/gtk4-layer-shell"
  git clone -q --depth 1 --branch v1.3.0 https://github.com/wmww/gtk4-layer-shell.git "$SOURCES/gtk4-layer-shell"
  meson setup "$SOURCES/gtk4-layer-shell/build" "$SOURCES/gtk4-layer-shell" --prefix=/usr/local \
    -Dvapi=false -Dsmoke-tests=false
  ninja -C "$SOURCES/gtk4-layer-shell/build" install
fi

if [[ ! -x "$SOURCES/labwc-0.7.4/build/labwc" ]]; then
  rm -rf "$SOURCES/labwc-0.7.4"
  git clone -q --depth 1 --branch 0.7.4 https://github.com/labwc/labwc.git "$SOURCES/labwc-0.7.4"
  meson setup "$SOURCES/labwc-0.7.4/build" "$SOURCES/labwc-0.7.4" \
    -Dxwayland=disabled -Dman-pages=disabled -Dsvg=disabled -Dnls=disabled
  ninja -C "$SOURCES/labwc-0.7.4/build"
fi
echo "atelier prêt. labwc avec méthode de saisie : $SOURCES/labwc-0.7.4/build/labwc"
