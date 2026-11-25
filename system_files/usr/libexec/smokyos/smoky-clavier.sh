# shellcheck shell=bash
# Smoky OS — disposition du clavier du système (celle choisie à l'installation), pour labwc.
# À sourcer : définit XKB_DEFAULT_LAYOUT (et XKB_DEFAULT_VARIANT s'il y en a une). Français par défaut.
# Rien de réglé : localectl écrit « (unset) » (« n/a » avant systemd 254). Passé tel quel, labwc
# refuserait la disposition et se mettrait en QWERTY, et le mot de passe ne passerait plus.
smoky_clavier() {
  local layout="" variant="" f="${SMOKY_CLAVIER_XORG:-/etc/X11/xorg.conf.d/00-keyboard.conf}"
  if command -v localectl >/dev/null; then
    layout=$(LC_ALL=C localectl status 2>/dev/null | sed -n 's/^ *X11 Layout: *//p')
    variant=$(LC_ALL=C localectl status 2>/dev/null | sed -n 's/^ *X11 Variant: *//p')
  fi
  case $layout in "(unset)"|n/a|-) layout="" variant="" ;; esac
  case $variant in "(unset)"|n/a|-) variant="" ;; esac
  if [[ -z "$layout" && -r "$f" ]]; then
    layout=$(sed -n 's/.*"XkbLayout" *"\([^"]*\)".*/\1/p' "$f")
    variant=$(sed -n 's/.*"XkbVariant" *"\([^"]*\)".*/\1/p' "$f")
  fi
  export XKB_DEFAULT_LAYOUT="${layout:-fr}"
  if [[ -n "$variant" ]]; then export XKB_DEFAULT_VARIANT="$variant"; fi
}
smoky_clavier
