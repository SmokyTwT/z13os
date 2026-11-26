#!/usr/bin/env bash
# Smoky OS — tous les essais de l'atelier sans écran, avec un résumé (code 1 si l'un échoue).
#   bash tests/atelier/preparer.sh   (une fois)
#   bash tests/atelier/lancer.sh
set -u
ICI=$(cd "$(dirname "$0")" && pwd)
LABWC_SAISIE=${ATELIER_SOURCES:-/var/tmp/atelier}/labwc-0.7.4/build/labwc
lignes=()
essai() {  # $1 = labwc à utiliser ; ensuite la commande, lancée par bureau.sh sans le bureau (AVEC_BUREAU=1 : avec)
  local labwc=$1 sortie sans=1
  shift
  [[ -n "${AVEC_BUREAU:-}" ]] && sans=
  sortie=$(LABWC=$labwc SANS_BUREAU=$sans timeout 150 "$ICI/bureau.sh" "$@" 2>&1 | grep -E '^(OK|KO|SAUTÉ|INFO) ')
  [[ -n "$sortie" ]] || sortie="KO  $* : pas de résultat (voir /tmp/atelier)"
  printf '%s\n' "$sortie"
  lignes+=("$sortie")
}
for e in clavier-session.py clavier-tout.py connexion-clavier.py connexion-windows.py connexion-secours.py \
         verrou-secours.py; do
  essai labwc env GSETTINGS_BACKEND=memory python3 "$ICI/$e"
done
AVEC_BUREAU=1 essai labwc /usr/bin/python3 "$ICI/plateau.py"     # zone de notification de la vraie barre
if [[ -x "$LABWC_SAISIE" ]]; then
  essai "$LABWC_SAISIE" env GSETTINGS_BACKEND=memory python3 "$ICI/clavier-auto.py"
  essai "$LABWC_SAISIE" env GSETTINGS_BACKEND=memory python3 "$ICI/clavier-externe.py"
  essai "$LABWC_SAISIE" "$ICI/chrome.sh"
else
  echo "SAUTÉ apparition seule du clavier et Chrome : lance d'abord tests/atelier/preparer.sh"
fi
echo
if printf '%s\n' "${lignes[@]}" | grep -q '^KO'; then
  echo "RÉSULTAT : au moins un essai de l'atelier a échoué."
  exit 1
fi
echo "RÉSULTAT : atelier, tout est bon."
