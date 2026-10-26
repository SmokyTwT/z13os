#!/usr/bin/env bash
# Première connexion de chaque utilisateur : installe Claude Code dans ~/.local/bin
set -uo pipefail
done_flag="$HOME/.config/z13os/user-setup.done"
mkdir -p "$HOME/Notes"
bm="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$bm")"
grep -q "file://$HOME/Notes" "$bm" 2>/dev/null || echo "file://$HOME/Notes Notes" >> "$bm"
[[ -f "$done_flag" ]] && exit 0
if curl -fsSL --max-time 300 https://claude.ai/install.sh | bash; then
  mkdir -p "$(dirname "$done_flag")" && touch "$done_flag"
  notify-send -i claude "Smoky OS" "Claude est prêt : Super + C, ou « claude » dans un terminal." || true
fi
