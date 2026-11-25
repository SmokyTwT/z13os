#!/usr/bin/bash
# Smoky OS — verrouillage (service smoky-verrou) : l'écran de verrouillage Smoky. S'il tombe alors
# que l'écran est verrouillé, il est relancé, puis remplacé par son écran de secours (champ et
# clavier tactile : on déverrouille au doigt) ; swaylock seulement en dernier recours, car il
# demande un vrai clavier. labwc garde l'écran caché entre deux : rien n'est montré sans mot de passe.
/usr/bin/python3 -I /usr/libexec/smokyos/smoky-verrou.py
code=$?
case "$code" in
  0|2|143) exit 0 ;;      # déverrouillé, verrouillage refusé (déjà verrouillé), ou arrêté
esac
systemd-notify --ready 2>/dev/null || true
for mode in normal --secours; do
  echo "écran de verrouillage Smoky tombé (code $code) : relance ($mode)"
  if [[ $mode == normal ]]; then
    /usr/bin/python3 -I /usr/libexec/smokyos/smoky-verrou.py
  else
    /usr/bin/python3 -I /usr/libexec/smokyos/smoky-verrou.py --secours
  fi
  code=$?
  case "$code" in 0|143) exit 0 ;; esac
done
echo "écran de verrouillage Smoky tombé (code $code) : relais par swaylock"
exec swaylock -s fill -i /usr/share/backgrounds/z13os/smokyos.jpg -c 09090a \
  --indicator-radius 90 --inside-color 131315cc --ring-color b6b7c2 --key-hl-color f3f3f6 \
  --text-color f3f3f6 --line-color 00000000 --separator-color 00000000
