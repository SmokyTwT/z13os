#!/usr/bin/env bash
# Synchro bidirectionnelle ~/Notes <-> Google Drive (lancée par z13-notes-sync.timer)
set -uo pipefail
rclone listremotes | grep -q '^gdrive:$' || exit 0
rclone bisync "$HOME/Notes" "gdrive:Notes Z13" \
  --create-empty-src-dirs --resilient --recover --max-lock 2m \
  --conflict-resolve newer --exclude '*.tmp' --exclude '.~lock*' \
  || { notify-send -i dialog-warning "Notes" "La synchro Google Drive a échoué, nouvel essai dans 5 min." || true; exit 1; }
