#!/usr/bin/env bash
# Smoky OS — redémarrer une seule fois sur Windows (double démarrage), puis revenir à Smoky OS.
# Indique au firmware l'entrée « Windows Boot Manager » pour le prochain démarrage uniquement.
set -euo pipefail
id=$(efibootmgr | sed -nE 's/^Boot([0-9A-Fa-f]{4})\*?[[:space:]]+Windows Boot Manager.*/\1/p' | head -1)
[[ -n "$id" ]] || { echo "Windows introuvable"; exit 1; }
efibootmgr --bootnext "$id" >/dev/null
systemctl reboot
