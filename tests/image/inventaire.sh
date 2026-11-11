#!/usr/bin/env bash
# Inventaire d'une image Smoky OS : ce qui est activé, ce qui pèse. Lecture seule.
# Lancé par le build GitHub sur les branches de test (journal du build), à l'intérieur de l'image :
#   podman run --rm --network=none -v ./tests:/tests:ro IMAGE bash /tests/image/inventaire.sh
# Sert à décider en connaissance de cause : avant de couper ou d'alléger quoi que ce soit, on
# regarde ici ce que l'image contient vraiment.
set -uo pipefail

titre() { printf '\n=== %s\n' "$1"; }
en_ligne() { awk '{print $1}' | sort | tr '\n' ' '; echo; }

titre "Services activés au démarrage (système)"
systemctl list-unit-files --state=enabled --no-legend --no-pager 2>/dev/null | en_ligne

titre "Services activés dans chaque session"
systemctl --global list-unit-files --state=enabled --no-legend --no-pager 2>/dev/null | en_ligne

titre "Programmes lancés à l'ouverture de session (autostart)"
for d in /etc/xdg/autostart /usr/share/gdm/greeter/autostart; do
  [ -d "$d" ] || continue
  for f in "$d"/*.desktop; do
    [ -f "$f" ] || continue
    cache=""; grep -q '^Hidden=true' "$f" && cache=" (désactivé)"
    printf '  %s%s\n' "${f#/}" "$cache"
  done
done

titre "Paquets"
echo "  nombre : $(rpm -qa | wc -l)"
echo "  les 40 plus gros :"
rpm -qa --qf '%{SIZE} %{NAME}\n' | sort -rn | sed -n '1,40p' | awk '{printf "  %8.1f Mo  %s\n", $1 / 1048576, $2}'

titre "Microprogrammes (firmware) installés"
rpm -qa --qf '%{SIZE} %{NAME}\n' | grep -E 'firmware|microcode|ucode' | sort -rn | awk '{printf "  %8.1f Mo  %s\n", $1 / 1048576, $2}'

titre "Ce qui pèse dans /usr (Mo)"
du -xsm /usr/lib/modules /usr/lib/firmware /usr/lib64 /usr/libexec /usr/bin /usr/share/* /usr/lib/* 2>/dev/null \
  | sort -rn | sed -n '1,30p' | awk '{printf "  %6d  %s\n", $1, $2}'

titre "Démarrage"
for d in /usr/lib/modules/*/; do
  [ -f "$d/vmlinuz" ] || continue
  printf '  noyau %s : image de démarrage %s Mo\n' "$(basename "$d")" "$(( $(stat -c %s "$d/initramfs.img" 2>/dev/null || echo 0) / 1000000 ))"
done

titre "Mémoire compressée (zram) et réglages du noyau"
for f in /usr/lib/systemd/zram-generator.conf /etc/systemd/zram-generator.conf; do [ -f "$f" ] && { echo "  $f :"; sed 's/^/    /' "$f"; }; done
echo "  fichiers de réglages : $(ls /usr/lib/sysctl.d /etc/sysctl.d 2>/dev/null | tr '\n' ' ')"
grep -rhE '^\s*vm\.' /usr/lib/sysctl.d /etc/sysctl.d 2>/dev/null | sed 's/^/    /' || true

# Unités à relire en entier (dépannage) : SMOKY_INVENTAIRE_UNITES="a.service b.timer"
for u in ${SMOKY_INVENTAIRE_UNITES:-}; do
  titre "Unité $u"
  systemctl cat "$u" --no-pager 2>&1 | sed -n '1,60p' | sed 's/^/  /'
done
exit 0
