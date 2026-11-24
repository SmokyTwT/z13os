#!/usr/bin/bash
# Smoky OS 100 % maison — construit BOOTX64.EFI (programme UEFI) avec clang et lld, sans aucune bibliothèque.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p construit/esp/EFI/BOOT
clang -target x86_64-unknown-windows -std=c11 -O2 -ffreestanding -fno-builtin -fshort-wchar -mno-red-zone \
  -fno-stack-protector -mno-stack-arg-probe -fno-math-errno -Wall -Wextra -Werror \
  -c smokyos.c -o construit/smokyos.o
clang -target x86_64-unknown-windows -std=c11 -O2 -ffreestanding -fno-builtin -fshort-wchar -mno-red-zone \
  -fno-stack-protector -mno-stack-arg-probe -fno-math-errno -Wall -Wextra -Werror \
  -c noyau.c -o construit/noyau.o
lld-link -subsystem:efi_application -entry:efi_main -nodefaultlib -out:construit/esp/EFI/BOOT/BOOTX64.EFI construit/smokyos.o construit/noyau.o
ls -l construit/esp/EFI/BOOT/BOOTX64.EFI
# Image de clé USB / de machine virtuelle : une partition FAT (EFI) qui contient EFI/BOOT/BOOTX64.EFI
rm -f construit/smokyos.img
dd if=/dev/zero of=construit/smokyos.img bs=1M count=34 status=none
mkfs.fat -F 32 -n SMOKYOS construit/smokyos.img >/dev/null
mmd -i construit/smokyos.img ::/EFI ::/EFI/BOOT
mcopy -i construit/smokyos.img construit/esp/EFI/BOOT/BOOTX64.EFI ::/EFI/BOOT/BOOTX64.EFI
echo "image : construit/smokyos.img"
