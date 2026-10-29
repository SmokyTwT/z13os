#!/usr/bin/env bash
# Connexion de chaque utilisateur : dossier Notes (synchronisé avec Google Drive),
# raccourci « Notes » dans Fichiers, et thème Smoky des applis (GTK 3/4, Terminal).
set -uo pipefail
mkdir -p "$HOME/Notes"
bm="$HOME/.config/gtk-3.0/bookmarks"
mkdir -p "$(dirname "$bm")"
grep -q "file://$HOME/Notes" "$bm" 2>/dev/null || echo "file://$HOME/Notes Notes" >> "$bm"

# Thème Smoky : copié (pas lié, pour que les applis Flatpak le voient aussi) et mis à jour
# avec le système. Un fichier gtk.css personnel (sans la ligne « Smoky OS ») n'est pas touché.
SRC=/usr/share/smokyos/gtk
install_css() { # source destination
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [[ ! -e "$dst" ]] || head -1 "$dst" | grep -q "Smoky OS"; then
    cmp -s "$src" "$dst" || cp "$src" "$dst"
  fi
}
install_css "$SRC/gtk4.css" "$HOME/.config/gtk-4.0/gtk.css"
install_css "$SRC/gtk3.css" "$HOME/.config/gtk-3.0/gtk.css"
cmp -s "$SRC/smoky-bg.jpg" "$HOME/.config/gtk-4.0/smoky-bg.jpg" || cp "$SRC/smoky-bg.jpg" "$HOME/.config/gtk-4.0/smoky-bg.jpg"

# Terminal : palette « Smoky » (noir fumé, texte argent)
PAL="${XDG_DATA_HOME:-$HOME/.local/share}/org.gnome.Ptyxis/palettes"
mkdir -p "$PAL"
cmp -s /usr/share/smokyos/ptyxis/smoky.palette "$PAL/smoky.palette" || cp /usr/share/smokyos/ptyxis/smoky.palette "$PAL/smoky.palette"

# Nouveautés appliquées une fois aux comptes existants (les nouveaux les ont par défaut) :
# écran de verrouillage sans notifications, avec météo et état du PC (smoky-lockinfo).
MARK="$HOME/.config/smoky/setup-lockinfo"
if [[ ! -e "$MARK" ]] && command -v gsettings >/dev/null; then
  gsettings set org.gnome.desktop.notifications show-in-lock-screen false
  # liste déjà personnalisée (sinon la valeur par défaut de Smoky OS l'inclut déjà)
  cur=$(dconf read /org/gnome/shell/enabled-extensions 2>/dev/null)
  if [[ -n "$cur" && "$cur" != *smoky-lockinfo@smokyos* ]]; then
    if [[ "$cur" == "@as []" || "$cur" == "[]" ]]; then new="['smoky-lockinfo@smokyos']"; else new="${cur%]}, 'smoky-lockinfo@smokyos']"; fi
    gsettings set org.gnome.shell enabled-extensions "$new"
  fi
  mkdir -p "$(dirname "$MARK")" && touch "$MARK"
fi

# Spotify devient une appli web Smoky : son icône remplace l'ancienne dans le dock (liste personnalisée)
favs=$(dconf read /org/gnome/shell/favorite-apps 2>/dev/null)
if [[ "$favs" == *com.spotify.Client.desktop* ]]; then
  gsettings set org.gnome.shell favorite-apps "${favs//com.spotify.Client.desktop/z13-spotify.desktop}"
fi
