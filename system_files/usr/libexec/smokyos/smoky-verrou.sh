#!/usr/bin/bash
# Smoky OS — verrouillage (service smoky-verrou) : l'écran de verrouillage Smoky ; s'il plante alors
# que l'écran est verrouillé, swaylock prend le relais pour que tu puisses déverrouiller (labwc garde
# l'écran caché entre les deux : rien n'est jamais montré sans mot de passe).
/usr/bin/python3 -I /usr/libexec/smokyos/smoky-verrou.py
code=$?
case "$code" in
  0|2) exit 0 ;;          # déverrouillé, ou verrouillage refusé (déjà verrouillé)
esac
echo "écran de verrouillage Smoky tombé (code $code) : relais par swaylock"
systemd-notify --ready 2>/dev/null || true
exec swaylock -s fill -i /usr/share/backgrounds/z13os/smokyos.jpg -c 09090a \
  --indicator-radius 90 --inside-color 131315cc --ring-color b6b7c2 --key-hl-color f3f3f6 \
  --text-color f3f3f6 --line-color 00000000 --separator-color 00000000
