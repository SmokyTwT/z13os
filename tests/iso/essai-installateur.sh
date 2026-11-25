#!/usr/bin/env bash
# Essai de l'installateur de l'ISO dans une machine virtuelle, sans rien installer : l'ISO
# démarre en mode texte (sur le port série) et on attend le résumé de l'installation.
# Il doit être en français, avec les étapes « Configurations de la langue » et « Création de
# l'utilisateur » (sinon : pas de compte, ou un mot de passe tapé en QWERTY).
#   sudo bash tests/iso/essai-installateur.sh smokyos.iso
# Lancé par build-iso.yml après la construction de l'ISO. Paquets : qemu-system-x86, xorriso.
set -uo pipefail
ISO=${1:?usage : essai-installateur.sh smokyos.iso}
T=$(mktemp -d); QEMU=""
trap '[ -n "$QEMU" ] && kill "$QEMU" 2>/dev/null; rm -rf "$T"' EXIT

# noyau, image de démarrage et options de la première entrée du menu de l'ISO
if ! xorriso -osirrox on -indev "$ISO" -extract /images/pxeboot/vmlinuz "$T/vmlinuz" \
     -extract /images/pxeboot/initrd.img "$T/initrd.img" -extract /EFI/BOOT/grub.cfg "$T/grub.cfg" >/dev/null 2>&1; then
  echo "RÉSULTAT : impossible de lire l'ISO (xorriso)."; exit 1
fi
opts=$(sed -n 's|^[[:space:]]*linux\(efi\)\{0,1\}[[:space:]]\{1,\}/images/pxeboot/vmlinuz[[:space:]]*||p' "$T/grub.cfg" | head -n 1)
opts=$(printf '%s' "$opts" | sed 's/\<rd\.live\.check\>//g; s/\<quiet\>//g')
case $opts in *inst.ks=*) ;; *) echo "RÉSULTAT : options de démarrage introuvables dans le menu de l'ISO."; exit 1 ;; esac
echo "options du menu de l'ISO : $opts"

ACCEL=kvm; CPU=host; ATTENTE=600
[ -w /dev/kvm ] || { ACCEL=tcg; CPU=max; ATTENTE=2400; echo "note : pas de KVM ici, émulation lente"; }
truncate -s 20G "$T/disque.raw"   # un disque vide, pour que l'installateur en trouve un
: > "$T/serie.log"
qemu-system-x86_64 -machine "q35,accel=$ACCEL" -cpu "$CPU" -smp 2 -m 4096 \
  -kernel "$T/vmlinuz" -initrd "$T/initrd.img" -append "$opts inst.text console=ttyS0,115200" \
  -cdrom "$ISO" -drive "file=$T/disque.raw,format=raw,if=virtio,cache=unsafe" \
  -display none -nic none -monitor none -no-reboot -serial "file:$T/serie.log" &
QEMU=$!

# le résumé se termine par une invite : « ['b' pour démarrer l'installation, 'q' pour quitter… »
# (« 'b' to begin installation » si l'installateur est resté en anglais)
debut=$SECONDS; fin=""
while (( SECONDS - debut < ATTENTE )); do
  if grep -aqF "['b' " "$T/serie.log"; then fin=invite; break; fi
  if ! kill -0 "$QEMU" 2>/dev/null; then fin=arret; break; fi
  sleep 5
done
duree=$((SECONDS - debut))
resume=$(grep -a -B40 -F "['b' " "$T/serie.log" | tail -n 41)

if [ "$fin" != invite ]; then
  echo "-- fin du journal série"; tail -n 40 "$T/serie.log" | tr -d '\r'
  case $fin in
    arret) echo "RÉSULTAT : la machine virtuelle s'est arrêtée avant le résumé de l'installation ($duree s)." ;;
    *)     echo "RÉSULTAT : pas de résumé de l'installation après $duree s." ;;
  esac
  exit 1
fi
echo "-- résumé de l'installation ($duree s après le démarrage)"; printf '%s\n' "$resume" | tr -d '\r'
manque=""
# des morceaux courts, qu'un retour à la ligne du résumé (deux colonnes) ne coupe pas
grep -aqF "to begin installation" <<<"$resume" && manque+=" le français (l'installateur est resté en anglais) ;"
grep -aqF "de la langue" <<<"$resume" || manque+=" l'étape de la langue et du clavier ;"
grep -aqF "Français" <<<"$resume" || manque+=" la langue réglée sur le français ;"
grep -aqF "utilisateur" <<<"$resume" || manque+=" l'étape « Création de l'utilisateur » ;"
grep -aqF "Destination" <<<"$resume" || manque+=" le choix du disque ;"
if [ -n "$manque" ]; then
  echo "RÉSULTAT : résumé de l'installation incomplet, il manque :${manque% ;}."
  exit 1
fi
grep -aqE "Configuration de réseau|Network configuration" <<<"$resume" && echo "note : l'étape du réseau est présente (elle devait être retirée)"
echo "RÉSULTAT : l'installateur démarre en français ; langue, disque et création du compte sont proposés."
