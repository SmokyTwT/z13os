#!/usr/bin/env bash
# Smoky OS — redémarrer une seule fois ailleurs : « windows » ou « uefi » (réglages du BIOS).
# 1er essai : par le firmware (efibootmgr --bootnext, systemctl --firmware-setup).
# Le firmware ASUS refuse parfois qu'on écrive ses variables (« Cannot allocate memory ») :
# on passe alors par le menu de démarrage Smoky OS (GRUB), qui choisit l'entrée une seule fois.
set -uo pipefail
target="${1:-}"
CFG=/boot/grub2/grub.cfg
ENV=/boot/grub2/grubenv

grub_once() {   # titre de l'entrée du menu GRUB
  [[ -f "$CFG" ]] || { echo "menu de démarrage introuvable"; exit 1; }
  if ! grep -q next_entry "$CFG"; then
    # le menu lit « next_entry » (une seule fois) dans grubenv
    sed -i '/^set timeout_style=menu$/a\
if [ -s $prefix/grubenv ]; then\
  load_env\
fi\
if [ "${next_entry}" ]; then\
  set default="${next_entry}"\
  set next_entry=\
  save_env next_entry\
  set timeout=0\
fi' "$CFG"
  fi
  [[ -f "$ENV" ]] || grub2-editenv "$ENV" create
  grub2-editenv "$ENV" set "next_entry=$1"
  sync
  systemctl reboot
}

case "$target" in
  windows)
    id=$(efibootmgr | sed -nE 's/^Boot([0-9A-Fa-f]{4})\*?[[:space:]]+Windows Boot Manager.*/\1/p' | head -1)
    [[ -n "$id" ]] || { echo "Windows introuvable"; exit 1; }
    if efibootmgr --bootnext "$id" >/dev/null 2>&1; then systemctl reboot; else grub_once "Windows"; fi ;;
  uefi)
    systemctl reboot --firmware-setup 2>/dev/null || grub_once "Réglages du firmware (UEFI)" ;;
  *) echo "usage : $0 windows|uefi"; exit 2 ;;
esac
