#!/usr/bin/bash
# Répare le démarrage de Smoky OS après une installation interrompue à l'étape
# « configuration du chargeur de démarrage » (menu GRUB absent, root= absent).
# À lancer depuis Smoky OS démarré : sudo bash repair-boot.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Lance-moi avec sudo."; exit 1; }

ask() { local r; read -r -p "$1 [o/N] " r </dev/tty; [[ "$r" =~ ^[oOyY] ]]; }

BOOT_UUID=$(findmnt -no UUID /boot)
ROOT_UUID=$(findmnt -no UUID /sysroot)
[ -n "$BOOT_UUID" ] && [ -n "$ROOT_UUID" ] || { echo "Impossible de trouver /boot ou /sysroot."; exit 1; }
SUBVOL=$(findmnt -no OPTIONS /sysroot | tr ',' '\n' | sed -n 's/^subvol=\/*//p')
echo "/boot : $BOOT_UUID   système : $ROOT_UUID (sous-volume « ${SUBVOL:-aucun} »)"

# 0. Mises à jour depuis le dépôt de Smoky OS (avant les kargs : une bascule repart du système démarré)
if ! rpm-ostree status --booted | grep -q 'ghcr.io/smokytwt/z13os'; then
  echo "L'image suivie n'est pas ghcr.io/smokytwt/z13os:latest (les mises à jour ne marcheraient pas)."
  ask "Basculer dessus maintenant (téléchargement) ?" && bootc switch ghcr.io/smokytwt/z13os:latest
fi

# 1. Paramètres du noyau manquants dans l'entrée de démarrage
echo "== Paramètres du noyau"
ARGS=(--append-if-missing="root=UUID=$ROOT_UUID" --append-if-missing=rw)
[ -n "$SUBVOL" ] && ARGS+=(--append-if-missing="rootflags=subvol=$SUBVOL")
if rpm-ostree kargs | grep -q "root=UUID=$ROOT_UUID"; then
  echo "Déjà en place."
else
  rpm-ostree kargs "${ARGS[@]}"
fi

# 2. Partition EFI
ESP=$(lsblk -nrpo NAME,PARTTYPE | awk 'tolower($2)=="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"{print $1; exit}')
[ -n "$ESP" ] || { echo "Partition EFI introuvable."; exit 1; }
ESP_UUID=$(blkid -s UUID -o value "$ESP")
ESPDIR=$(findmnt -no TARGET "$ESP" | head -1 || true)
if [ -z "$ESPDIR" ]; then
  ESPDIR=/run/smoky-esp; mkdir -p "$ESPDIR"; mount "$ESP" "$ESPDIR"
  trap 'umount "$ESPDIR"' EXIT
fi
[ -f "$ESPDIR/EFI/fedora/grubx64.efi" ] || { echo "GRUB absent de $ESPDIR/EFI/fedora."; exit 1; }

# 3. Configuration GRUB : menu lu depuis les entrées de Smoky OS (+ Windows)
echo "== Menu de démarrage"
mkdir -p /boot/grub2
[ -f /boot/grub2/grub.cfg ] && cp /boot/grub2/grub.cfg /boot/grub2/grub.cfg.avant-reparation
cat > /boot/grub2/grub.cfg <<EOF
set timeout=3
set timeout_style=menu
insmod part_gpt
insmod ext2
insmod fat
search --no-floppy --fs-uuid --set=root $BOOT_UUID
set boot=\$root
blscfg
menuentry "Windows" {
  insmod chain
  search --no-floppy --fs-uuid --set=root $ESP_UUID
  chainloader /EFI/Microsoft/Boot/bootmgfw.efi
}
menuentry "Réglages du firmware (UEFI)" {
  fwsetup
}
EOF

[ -f "$ESPDIR/EFI/fedora/grub.cfg" ] && cp "$ESPDIR/EFI/fedora/grub.cfg" "$ESPDIR/EFI/fedora/grub.cfg.avant-reparation"
cat > "$ESPDIR/EFI/fedora/grub.cfg" <<EOF
search --no-floppy --fs-uuid --set=dev $BOOT_UUID
set prefix=(\$dev)/grub2
export prefix
configfile \$prefix/grub.cfg
EOF
sync
echo "Menu écrit."

# 4. Entrée de démarrage CachyOS périmée
echo "== Entrées du firmware"
efibootmgr
CACHY=$(efibootmgr | sed -n 's/^Boot\([0-9A-Fa-f]\{4\}\)\*\? \+[Cc]achy[Oo][Ss].*/\1/p')
for n in $CACHY; do
  if ask "Supprimer l'entrée de démarrage CachyOS (Boot$n) ?"; then
    efibootmgr -q -b "$n" -B || echo "Le firmware refuse la suppression : elle se fera depuis le BIOS (sans gravité)."
  fi
done
if [ -d "$ESPDIR/EFI/cachyos" ] && ask "Supprimer le dossier EFI/cachyos (restes de CachyOS) ?"; then
  rm -rf "$ESPDIR/EFI/cachyos"
fi

# 5. Smoky OS en premier dans l'ordre de démarrage
FED=$(efibootmgr | sed -n 's/^Boot\([0-9A-Fa-f]\{4\}\)\*\? \+Fedora.*/\1/p' | head -1)
if [ -n "$FED" ]; then
  ORDER=$(efibootmgr | sed -n 's/^BootOrder: //p')
  EXIST=$(efibootmgr | sed -n 's/^Boot\([0-9A-Fa-f]\{4\}\)\*\? .*/\1/p' | paste -sd' ')
  NEW=$(echo "$FED,$ORDER" | tr ',' '\n' | awk -v ok=" $EXIST " 'NF && index(ok," "$0" ") && !seen[$0]++' | paste -sd,)
  if [ "$NEW" != "$ORDER" ]; then
    efibootmgr -q -o "$NEW" && echo "Smoky OS passe en premier." \
      || echo "Le firmware refuse de changer l'ordre : mets « Fedora » en premier dans le BIOS (F2)."
  fi
fi


echo
echo "Terminé. Redémarre : le menu Smoky OS / Windows doit apparaître tout seul."
