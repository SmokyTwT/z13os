#!/usr/bin/env bash
# Smoky OS — mode concentration : bloque les sites qui distraient pendant N minutes.
#   smoky-focus.sh start MINUTES   (lancé par smoky-focus@MINUTES.service)
#   smoky-focus.sh stop            (retire le blocage ; aussi au démarrage du PC)
set -u
HOSTS=/etc/hosts
LIST=/etc/smokyos/focus-sites.conf
BEGIN="# >>> smoky-focus"
END="# <<< smoky-focus"

stop() {
  sed -i "/^$BEGIN\$/,/^$END\$/d" "$HOSTS"
}

start() {
  local min="$1"
  [[ $min =~ ^[0-9]{1,3}$ ]] && (( min >= 1 && min <= 240 )) || { echo "durée invalide"; exit 2; }
  stop
  {
    echo "$BEGIN"
    grep -v '^\s*#' "$LIST" | tr -d ' \t\r' | grep -E '^[a-z0-9.-]+\.[a-z]{2,}$' | while read -r d; do
      for h in "$d" "www.$d" "m.$d"; do echo "0.0.0.0 $h"; echo ":: $h"; done
    done
    echo "$END"
  } >> "$HOSTS"
  sleep "$(( min * 60 ))"
}

case "${1:-}" in
  start) start "${2:-25}" ;;
  stop) stop ;;
  *) echo "usage : $0 start MINUTES | stop"; exit 2 ;;
esac
