#!/usr/bin/env bash
# Essai de démarrage : installe l'image sur un disque virtuel, puis la démarre dans une machine
# virtuelle (QEMU/KVM, UEFI), comme sur un vrai PC. Réussi si le système arrive jusqu'à
# l'écran de connexion. Lancé par le build GitHub avant chaque publication :
#   sudo bash tests/image/demarrer.sh localhost/smokyos:build [dossier de travail]
# Ce que l'essai ne voit pas : le matériel du Z13 (écran tactile, carte ASUS, Wi-Fi) et
# l'apparence. Il répond à une seule question : « est-ce que cette image démarre ? ».
set -uo pipefail

IMAGE="${1:?usage : demarrer.sh IMAGE [dossier]}"
T="${2:-/tmp/smoky-vm}"
ATTENTE="${SMOKY_ATTENTE_DEMARRAGE:-600}"        # secondes au plus pour atteindre l'écran de connexion
SERIE="$T/serie.log"

mkdir -p "$T"
rm -f "$T/disque.raw" "$SERIE" "$T/vars.fd"

echo "== 1/3 Installation de l'image sur un disque virtuel"
truncate -s 24G "$T/disque.raw"
# bootc install : l'installateur fourni par l'image elle-même. Options :
#  --generic-image     disque démarrable partout (BIOS et UEFI), sans rien écrire dans un firmware
#  --via-loopback      la cible est un fichier
#  --skip-fetch-check  l'image vient d'être construite ici, elle n'est pas encore sur un registre
#  --disable-selinux   la machine de construction (Ubuntu) n'a pas SELinux : on ne peut pas y
#                      poser fidèlement les étiquettes ; l'essai démarre donc sans SELinux
#  console série       tout le journal du démarrage sort sur le port série, lu plus bas
if ! podman run --rm --privileged --pid=host --security-opt label=type:unconfined_t \
      -v /dev:/dev -v /var/lib/containers:/var/lib/containers -v "$T":/output \
      "$IMAGE" bootc install to-disk --generic-image --via-loopback --filesystem btrfs \
        --skip-fetch-check --disable-selinux \
        --karg console=ttyS0,115200n8 --karg systemd.journald.forward_to_console=1 \
        /output/disque.raw; then
  echo "RÉSULTAT : l'installation sur le disque virtuel a échoué."
  exit 1
fi

echo "== 2/3 Démarrage dans la machine virtuelle"
CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
[ -f "$CODE" ] && [ -f "$VARS" ] || { echo "RÉSULTAT : firmware UEFI (paquet ovmf) introuvable."; exit 1; }
cp "$VARS" "$T/vars.fd"
ACCEL=kvm; CPU=host
[ -w /dev/kvm ] || { ACCEL=tcg; CPU=max; ATTENTE=$((ATTENTE * 4)); echo "note : pas de KVM ici, émulation lente"; }
: > "$SERIE"
qemu-system-x86_64 -machine "q35,accel=$ACCEL" -cpu "$CPU" -smp 2 -m 4096 \
  -drive "if=pflash,format=raw,readonly=on,file=$CODE" \
  -drive "if=pflash,format=raw,file=$T/vars.fd" \
  -drive "file=$T/disque.raw,format=raw,if=virtio,cache=unsafe" \
  -device virtio-vga -display none -nic none -monitor none -no-reboot \
  -serial "file:$SERIE" &
QEMU=$!
# à la sortie : machine arrêtée, disque virtuel supprimé (une dizaine de Go)
trap 'kill "$QEMU" 2>/dev/null; wait "$QEMU" 2>/dev/null; rm -f "$T/disque.raw"' EXIT

ECHEC='Kernel panic|emergency mode|Reached target emergency|dracut-emergency|Failed to mount /sysroot|ostree-prepare-root.*(failed|error)'
etat=attente
debut=$(date +%s)
while [ $(( $(date +%s) - debut )) -lt "$ATTENTE" ]; do
  if grep -qaE "$ECHEC" "$SERIE"; then etat=echec; break; fi
  if grep -qaE 'Reached target graphical\.target' "$SERIE"; then etat=graphique; break; fi
  kill -0 "$QEMU" 2>/dev/null || { etat=arret; break; }
  sleep 3
done
duree=$(( $(date +%s) - debut ))

# l'écran de connexion (GDM) démarre juste après : on lui laisse 40 s pour s'installer… ou tomber
if [ "$etat" = graphique ]; then
  for _ in $(seq 20); do
    grep -qaE 'gdm\.service: (Failed|Main process exited)|Failed to start gdm\.service' "$SERIE" && { etat=gdm; break; }
    sleep 2
  done
fi

echo "== 3/3 Résultat"
propre() { tr -d '\r' < "$SERIE" | sed -E 's/\x1b\[[0-9;?]*[A-Za-z]//g'; }
propre | grep -aE 'Startup finished in' | tail -1 | sed -E 's/^.*Startup finished in/  durée du démarrage (dans la machine virtuelle) :/'
echecs=$(propre | grep -aE 'Failed to start |\.service: Failed with result' | sed -E 's/^\[[ 0-9.]+\] //' | sort -u | head -15)
[ -n "$echecs" ] && { echo "  services en échec dans la machine virtuelle (souvent normal sans le matériel du Z13) :"; printf '%s\n' "$echecs" | sed 's/^/    /'; }

case "$etat" in
  graphique)
    if propre | grep -qaE 'Started gdm\.service'; then
      echo "RÉSULTAT : l'image démarre jusqu'à l'écran de connexion (${duree} s)."
      exit 0
    fi
    echo "RÉSULTAT : le système démarre (${duree} s) mais l'écran de connexion (GDM) n'apparaît pas dans le journal."
    ;;
  gdm)    echo "RÉSULTAT : le système démarre mais l'écran de connexion (GDM) plante." ;;
  echec)  echo "RÉSULTAT : le démarrage a échoué (mode de secours ou erreur du noyau)." ;;
  arret)  echo "RÉSULTAT : la machine virtuelle s'est arrêtée avant la fin du démarrage." ;;
  *)      echo "RÉSULTAT : toujours pas d'écran de connexion après ${ATTENTE} s." ;;
esac
echo "--- 60 dernières lignes du démarrage ---"
propre | tail -60
exit 1
