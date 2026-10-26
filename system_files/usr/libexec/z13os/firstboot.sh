#!/usr/bin/env bash
# Premier démarrage : applis Flatpak et carte graphique en mode économie
set -euo pipefail
flatpak remote-add --if-not-exists --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-modify --system --enable flathub
flatpak install --system -y --noninteractive flathub com.spotify.Client io.mpv.Mpv com.github.flxzt.rnote
# La RTX 3050 Ti ne sert pas au streaming : on la coupe (+ autonomie, - chaleur)
supergfxctl -m Integrated || true
mkdir -p /var/lib/z13os
touch /var/lib/z13os/firstboot.done
