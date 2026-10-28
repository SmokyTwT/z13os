#!/usr/bin/env bash
# Synchro bidirectionnelle ~/Notes <-> Google Drive (lancée par z13-notes-sync.timer)
set -uo pipefail
rclone listremotes | grep -q '^gdrive:$' || exit 0

# Batterie : sur secteur, une synchro toutes les 10 min ; sur batterie, toutes les 30 min
on_battery() {
  local s bat=0
  for s in /sys/class/power_supply/*; do
    case "$(cat "$s/type" 2>/dev/null)" in
      Mains) [ "$(cat "$s/online" 2>/dev/null)" = 1 ] && return 1 ;;
      Battery) bat=1 ;;
    esac
  done
  [ "$bat" = 1 ]
}
stamp="${XDG_STATE_HOME:-$HOME/.local/state}/smoky-notes-sync"
if on_battery && [ -f "$stamp" ] && [ $(( $(date +%s) - $(stat -c %Y "$stamp") )) -lt 1800 ]; then
  exit 0
fi
mkdir -p "$(dirname "$stamp")"
rclone bisync "$HOME/Notes" "gdrive:Notes Z13" \
  --create-empty-src-dirs --resilient --recover --max-lock 2m \
  --conflict-resolve newer --exclude '*.tmp' --exclude '.~lock*' \
  || { notify-send -i dialog-warning "Notes" "La synchro Google Drive a échoué, nouvel essai plus tard." || true; exit 1; }
touch "$stamp"
