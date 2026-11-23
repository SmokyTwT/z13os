# shellcheck shell=bash
# Smoky OS — disposition du clavier du système (celle choisie à l'installation), pour labwc.
# À sourcer : définit XKB_DEFAULT_LAYOUT (et XKB_DEFAULT_VARIANT s'il y en a une). Français par défaut.
smoky_clavier() {
  local layout="" variant="" f=/etc/X11/xorg.conf.d/00-keyboard.conf
  if command -v localectl >/dev/null; then
    layout=$(localectl status 2>/dev/null | sed -n 's/^ *X11 Layout: *//p')
    variant=$(localectl status 2>/dev/null | sed -n 's/^ *X11 Variant: *//p')
  fi
  if [[ -z "$layout" && -r "$f" ]]; then
    layout=$(sed -n 's/.*"XkbLayout" *"\([^"]*\)".*/\1/p' "$f")
    variant=$(sed -n 's/.*"XkbVariant" *"\([^"]*\)".*/\1/p' "$f")
  fi
  export XKB_DEFAULT_LAYOUT="${layout:-fr}"
  if [[ -n "$variant" ]]; then export XKB_DEFAULT_VARIANT="$variant"; fi
}
smoky_clavier
