#!/usr/bin/env bash
# Connexion de chaque utilisateur : dossier Notes (synchronisé avec Google Drive)
# et raccourci « Notes » dans le gestionnaire de fichiers.
set -uo pipefail
mkdir -p "$HOME/Notes"
bm="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$bm")"
grep -q "file://$HOME/Notes" "$bm" 2>/dev/null || echo "file://$HOME/Notes Notes" >> "$bm"
