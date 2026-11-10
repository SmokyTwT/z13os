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
    if efibootmgr --bootnext "$id" >/dev/null 2>&1; then systemctl reboot; fi
    # Repli par le menu GRUB, seulement si le lanceur de Windows est le vrai : un autre Linux
    # (CachyOS ici) avait mis son GRUB à la place de bootmgfw.efi, d'où un « grub rescue »
    esp=$(lsblk -nrpo NAME,PARTTYPE | awk 'tolower($2)=="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"{print $1; exit}')
    # partition EFI déjà montée ailleurs (/boot/efi…) : on lit là ; sinon montage en lecture seule
    mnt=$(findmnt -nro TARGET --source "$esp" 2>/dev/null | head -1)
    own=
    if [[ -z "$mnt" && -n "$esp" ]]; then
      mnt=$(mktemp -d)
      mount -o ro "$esp" "$mnt" 2>/dev/null && own=1 || mnt=
    fi
    if [[ -n "$mnt" ]]; then
      real=1
      grep -qai grub "$mnt/EFI/Microsoft/Boot/bootmgfw.efi" 2>/dev/null && real=0
      [[ -n "$own" ]] && umount "$mnt"
      [[ "$real" = 1 ]] && grub_once "Windows"
    fi
    echo "Le firmware refuse : redémarre, appuie sur Échap au logo ROG et choisis Windows Boot Manager"; exit 1 ;;
  uefi)
    systemctl reboot --firmware-setup 2>/dev/null || grub_once "Réglages du firmware (UEFI)" ;;
  *) echo "usage : $0 windows|uefi"; exit 2 ;;
esac
