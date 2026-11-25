#!/usr/bin/bash
# Smoky OS 100 % maison — construit BOOTX64.EFI (programme UEFI) avec clang et lld, sans aucune bibliothèque.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p construit/esp/EFI/BOOT
# essai du lecteur de descripteurs HID, sur cette machine, avant de construire l'OS
cc -std=c11 -O1 -Wall -Wextra -Werror -I. essais/hid.c hid.c -o construit/essai-hid
construit/essai-hid
clang -target x86_64-unknown-windows -std=c11 -O2 -ffreestanding -fno-builtin -fshort-wchar -mno-red-zone \
  -fno-stack-protector -mno-stack-arg-probe -fno-math-errno -Wall -Wextra -Werror \
  -c smokyos.c -o construit/smokyos.o
clang -target x86_64-unknown-windows -std=c11 -O2 -ffreestanding -fno-builtin -fshort-wchar -mno-red-zone \
  -fno-stack-protector -mno-stack-arg-probe -fno-math-errno -Wall -Wextra -Werror \
  -c noyau.c -o construit/noyau.o
clang -target x86_64-unknown-windows -std=c11 -O2 -ffreestanding -fno-builtin -fshort-wchar -mno-red-zone \
  -fno-stack-protector -mno-stack-arg-probe -fno-math-errno -Wall -Wextra -Werror \
  -c usb.c -o construit/usb.o
clang -target x86_64-unknown-windows -std=c11 -O2 -ffreestanding -fno-builtin -fshort-wchar -mno-red-zone \
  -fno-stack-protector -mno-stack-arg-probe -fno-math-errno -Wall -Wextra -Werror \
  -c hid.c -o construit/hid.o
lld-link -subsystem:efi_application -entry:efi_main -nodefaultlib -out:construit/esp/EFI/BOOT/BOOTX64.EFI construit/smokyos.o construit/noyau.o construit/usb.o construit/hid.o
ls -l construit/esp/EFI/BOOT/BOOTX64.EFI
# Image de clé USB : table de partitions GPT avec une seule partition EFI (FAT32) qui contient
# EFI/BOOT/BOOTX64.EFI. C'est ce que le firmware du Z13 sait démarrer depuis une clé.
rm -f construit/smokyos.img
dd if=/dev/zero of=construit/smokyos.img bs=1M count=64 status=none
printf 'label: gpt\nstart=2048, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="SMOKYOS"\n' \
  | sfdisk --quiet construit/smokyos.img
mformat -i construit/smokyos.img@@1M -F -v SMOKYOS ::
mmd -i construit/smokyos.img@@1M ::/EFI ::/EFI/BOOT
mcopy -i construit/smokyos.img@@1M construit/esp/EFI/BOOT/BOOTX64.EFI ::/EFI/BOOT/BOOTX64.EFI
echo "image de clé USB : construit/smokyos.img"
