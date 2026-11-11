#!/usr/bin/env bash
# Certains travaux de Fedora tournent à CHAQUE démarrage alors qu'ils ne servent qu'après un
# changement d'image (une mise à jour) : catalogue des logiciels (appstream), index des pages
# de manuel (mandb). Ce script permet de ne les lancer qu'une fois par image :
#   une-fois-par-image.sh NOM         code 0 : à faire (image nouvelle, ou jamais fait) ; code 1 : déjà fait
#   une-fois-par-image.sh NOM fait    note que c'est fait pour l'image en service
# Il est branché sur les services concernés par un complément systemd (ExecCondition= et
# ExecStartPost=, dossiers fedora-atomic-desktop-*.service.d).
# Dans le doute (image impossible à identifier, mémoire illisible), la réponse est « à faire » :
# au pire, le service tourne à chaque démarrage, comme avant.
set -u
nom="${1:-}"
[[ "$nom" =~ ^[a-z0-9-]+$ ]] || { echo "usage : $0 NOM [fait]" >&2; exit 0; }
RACINE="${SMOKY_UNEFOIS_RACINE:-}"          # pour les tests : faux /proc, /sysroot et /var
MEMOIRE="$RACINE/var/lib/smokyos/fait-$nom"

# Identité de l'image en service : le nom du dossier de son déploiement, « <empreinte>.<numéro> ».
# Le noyau reçoit « ostree=/ostree/boot.N/default/<…>/0 », un lien qui mène à ce dossier.
identite() {
  local lien cible
  lien=$(tr ' ' '\n' < "$RACINE/proc/cmdline" 2>/dev/null | sed -n 's/^ostree=//p' | head -n 1)
  [ -n "$lien" ] || return 1
  cible=$(readlink "$RACINE/sysroot$lien" 2>/dev/null) || return 1
  cible=${cible##*/}
  [[ "$cible" =~ ^[0-9a-f]{64}\.[0-9]+$ ]] || return 1
  printf '%s\n' "$cible"
}

id=$(identite) || exit 0                                   # image non identifiable : à faire
if [ "${2:-}" = fait ]; then
  mkdir -p "${MEMOIRE%/*}" && printf '%s\n' "$id" > "$MEMOIRE.tmp" && mv -f "$MEMOIRE.tmp" "$MEMOIRE"
  exit 0
fi
[ "$(cat "$MEMOIRE" 2>/dev/null)" = "$id" ] && exit 1      # déjà fait pour cette image
exit 0
