#!/usr/bin/env bash
# Socle 3/3 — écran de démarrage Smoky (Plymouth), intégré à l'image de démarrage (initramfs).
# Le thème (system_files/usr/share/plymouth/themes/smoky) est copié par Containerfile.socle
# juste avant ce script.
set -euxo pipefail

plymouth-set-default-theme smoky

# Pilotes graphiques laissés HORS de l'image de démarrage : NVIDIA (pilote libre « nouveau »)
# et AMD. Sur le Z13, l'écran est tenu par la puce Intel ; ces trois pilotes embarquaient à eux
# seuls 136 Mo de microprogrammes sur 284 (mesuré : tests/image/inventaire.sh), à charger et à
# décompresser à chaque démarrage. Ils restent installés dans le système et se chargent comme
# avant une fois celui-ci lancé (carte NVIDIA rallumée depuis Smoky Center, boîtier externe) :
# seule leur copie « démarrage » disparaît. Si l'écran est relié à la NVIDIA (mode Ultimate de
# Windows), le tout début du démarrage s'affiche par l'écran du firmware, sans pilote.
# Tout le reste de l'image de démarrage est celui de Fedora, inchangé.
PILOTES_OMIS="nouveau amdgpu radeon"

# Une image de démarrage par noyau présent (il n'y en a qu'un en temps normal)
noyaux=0
for vmlinuz in /usr/lib/modules/*/vmlinuz; do
  [[ -f "$vmlinuz" ]] || continue
  kver=$(basename "$(dirname "$vmlinuz")")
  dracut --no-hostonly --kver "$kver" --reproducible --zstd --add ostree \
    --omit-drivers "$PILOTES_OMIS" -f "/usr/lib/modules/$kver/initramfs.img"
  # garde-fou : l'écran Intel et le disque du Z13 doivent toujours y être (le reste est comparé
  # pilote par pilote à l'image publiée, dans le résumé du build d'une branche de test)
  contenu=$(lsinitrd "/usr/lib/modules/$kver/initramfs.img")
  for pilote in i915 xe nvme; do
    grep -qE "/$pilote\.ko" <<<"$contenu" || { echo "ERREUR : pilote $pilote absent de l'image de démarrage"; exit 1; }
  done
  ls -l "/usr/lib/modules/$kver/initramfs.img"
  noyaux=$((noyaux + 1))
done
[[ "$noyaux" -ge 1 ]] || { echo "ERREUR : aucun noyau trouvé dans /usr/lib/modules"; exit 1; }

rm -rf /var/cache/* /var/log/* /var/tmp/*
