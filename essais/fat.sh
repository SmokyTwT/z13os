#!/usr/bin/bash
# Smoky OS 100 % maison — essai de fat.c sur de vraies images de clé USB faites par les outils de
# Linux, qui vérifient ensuite le résultat des écritures de Smoky OS : fsck.vfat (aucune erreur)
# et mtype (NOTES.TXT identique). Lancé par construire.sh ; il faut mtools, dosfstools et sfdisk.
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p construit
cc -std=c11 -O1 -Wall -Wextra -Werror -I. essais/fat.c fat.c -o construit/essai-fat
head -c 153600 /dev/urandom > "$T/BOOTX64.EFI"           # un faux programme de démarrage de 150 Kio
export LC_ALL=C.UTF-8                                    # noms longs en UTF-8 pour mtools

essai() {   # essai TITRE IMAGE DÉCALAGE_EN_OCTETS [NOM_LONG]
  local titre=$1 img=$2 dec=$3 long=${4:-}
  mmd -i "$img@@$dec" ::/EFI ::/EFI/BOOT
  mcopy -i "$img@@$dec" "$T/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI
  if [ -n "$long" ]; then printf 'x' > "$T/long"; mcopy -i "$img@@$dec" "$T/long" "::/$long"; fi
  if ! construit/essai-fat "$img" "$T/BOOTX64.EFI" "$long" "$T/attendu"; then echo "ÉCHEC fat : $titre"; return 1; fi
  if ! mtype -i "$img@@$dec" ::/SMOKY/NOTES.TXT | cmp -s - "$T/attendu"; then
    echo "ÉCHEC fat : $titre, NOTES.TXT relu par mtools diffère"; return 1
  fi
  dd if="$img" of="$T/volume" bs=512 skip=$((dec / 512)) status=none
  if ! fsck.vfat -n "$T/volume" > "$T/fsck" 2>&1 || grep -qiE "wrong|uninitiali[sz]ed|corrupt|invalid|bad " "$T/fsck"; then
    echo "ÉCHEC fat : $titre, fsck.vfat :"; cat "$T/fsck"; return 1
  fi
  echo "fat : $titre : relu par mtools, vérifié par fsck.vfat"
}

# clé de Smoky OS : table GPT, une partition EFI en FAT32 (comme construire.sh), clusters de 512 octets
dd if=/dev/zero of="$T/a.img" bs=1M count=64 status=none
printf 'label: gpt\nstart=2048, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B\n' | sfdisk --quiet "$T/a.img"
mformat -i "$T/a.img@@1M" -F -v SMOKYOS ::
essai "GPT, partition EFI" "$T/a.img" 1048576 "Mon fichier très long.txt"
# clé formatée sans table de partitions, clusters de 4 Kio (mkfs.vfat)
dd if=/dev/zero of="$T/b.img" bs=1M count=300 status=none
mkfs.vfat -F 32 -s 8 -n CLE "$T/b.img" > /dev/null
essai "sans table, clusters de 4 Kio" "$T/b.img" 0
# table MBR, partition FAT32 (type 0x0C), comme une clé formatée par Windows ; clusters de 1 Kio
dd if=/dev/zero of="$T/c.img" bs=1M count=80 status=none
printf 'label: dos\nstart=2048, type=c\n' | sfdisk --quiet "$T/c.img"
mformat -i "$T/c.img@@1M" -F -c 2 -v WINDOWS ::
essai "MBR, partition 0x0C" "$T/c.img" 1048576 "Liste de courses.txt"
