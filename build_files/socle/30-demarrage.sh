#!/usr/bin/env bash
# Socle 3/3 — écran de démarrage Smoky (Plymouth), intégré à l'image de démarrage (initramfs).
# Le thème (system_files/usr/share/plymouth/themes/smoky) est copié par Containerfile.socle
# juste avant ce script.
set -euxo pipefail

plymouth-set-default-theme smoky

# Une image de démarrage par noyau présent (il n'y en a qu'un en temps normal)
noyaux=0
for vmlinuz in /usr/lib/modules/*/vmlinuz; do
  [[ -f "$vmlinuz" ]] || continue
  kver=$(basename "$(dirname "$vmlinuz")")
  dracut --no-hostonly --kver "$kver" --reproducible --zstd --add ostree -f "/usr/lib/modules/$kver/initramfs.img"
  noyaux=$((noyaux + 1))
done
[[ "$noyaux" -ge 1 ]] || { echo "ERREUR : aucun noyau trouvé dans /usr/lib/modules"; exit 1; }

rm -rf /var/cache/* /var/log/* /var/tmp/*
