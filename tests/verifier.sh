#!/usr/bin/env bash
# Vérifications rapides du dépôt, sans construire l'image (moins d'une minute).
#   bash tests/verifier.sh
# Lancé par GitHub avant chaque construction ; à lancer aussi avant d'envoyer une modification.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

echecs=0
etape() { printf '\n== %s\n' "$1"; }
ok()    { printf '  ok      %s\n' "$1"; }
echec() { printf '  ÉCHEC   %s\n' "$1"; echecs=$((echecs + 1)); }
note()  { printf '  note    %s\n' "$1"; }

# Scripts shell du dépôt : *.sh et fichiers sans extension qui commencent par #!…sh
mapfile -t SHELLS < <({ git ls-files '*.sh'; git ls-files system_files/usr/bin system_files/usr/libexec | while read -r f; do
  [ -f "$f" ] && head -c 64 "$f" | head -1 | grep -qE '^#!.*(bash|/sh)' && echo "$f"; done; } | sort -u)
mapfile -t PYTHONS < <(git ls-files '*.py' | grep -v '/vendor/')
mapfile -t JS < <(git ls-files '*.js' '*.mjs' | grep -v '/vendor/')

etape "Scripts shell (${#SHELLS[@]})"
for f in "${SHELLS[@]}"; do bash -n "$f" 2>/dev/null || echec "syntaxe : $f"; done
if command -v shellcheck >/dev/null; then
  if sortie=$(shellcheck -S warning "${SHELLS[@]}" 2>&1); then ok "shellcheck"; else echec "shellcheck"; printf '%s\n' "$sortie" | head -40; fi
else
  note "shellcheck absent : contrôle de syntaxe seulement"
fi

etape "Python (${#PYTHONS[@]})"
if python3 - "${PYTHONS[@]}" <<'PY'
import ast, sys
ko = 0
for f in sys.argv[1:]:
    try:
        ast.parse(open(f, encoding="utf-8").read(), f)
    except SyntaxError as e:
        print(f"   {e}"); ko = 1
sys.exit(ko)
PY
then ok "syntaxe"; else echec "syntaxe Python"; fi
if python3 -m pyflakes --version >/dev/null 2>&1; then
  if sortie=$(python3 -m pyflakes "${PYTHONS[@]}" 2>&1); then ok "pyflakes"; else echec "pyflakes"; printf '%s\n' "$sortie" | head -40; fi
else
  note "pyflakes absent (pip install pyflakes) : noms inutilisés non vérifiés"
fi

etape "JavaScript (${#JS[@]})"
if command -v node >/dev/null; then
  ko=0
  for f in "${JS[@]}"; do
    # modules ES : extensions GNOME Shell et Smoky Notes ; scripts classiques ailleurs
    if grep -qE '^(import|export) ' "$f"; then node --check --input-type=module < "$f" 2>/dev/null || { echec "syntaxe : $f"; ko=1; }
    else node --check "$f" 2>/dev/null || { echec "syntaxe : $f"; ko=1; }; fi
  done
  [ "$ko" -eq 0 ] && ok "syntaxe"
else
  note "node absent : JavaScript non vérifié"
fi

etape "Fichiers de données"
ko=0
while read -r f; do
  python3 -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$f" 2>/dev/null || { echec "JSON illisible : $f"; ko=1; }
done < <(git ls-files '*.json' | grep -v '/vendor/')
[ "$ko" -eq 0 ] && ok "JSON"
ko=0
while read -r f; do
  grep -q '^\[Desktop Entry\]' "$f" && grep -q '^Exec=' "$f" || { echec "raccourci incomplet : $f"; ko=1; }
  exe=$(sed -n 's/^Exec=\([^ ]*\).*/\1/p' "$f" | head -1)
  case "$exe" in /usr/bin/smoky-*|/usr/bin/z13-*|/usr/libexec/*) [ -f "system_files$exe" ] || { echec "$f lance $exe, absent du dépôt"; ko=1; } ;; esac
done < <(git ls-files 'system_files/usr/share/applications/*.desktop' 'system_files/etc/xdg/autostart/*.desktop')
[ "$ko" -eq 0 ] && ok "raccourcis (.desktop)"

etape "Services"
ko=0
while read -r f; do
  while read -r exe; do
    case "$exe" in /usr/libexec/*|/usr/bin/smoky-*|/usr/bin/z13-*) [ -f "system_files$exe" ] || { echec "$f lance $exe, absent du dépôt"; ko=1; } ;; esac
  done < <(sed -n 's/^Exec[A-Za-z]*=[-+!@:]*\([^ ]*\).*/\1/p' "$f"; sed -n 's/^Exec[A-Za-z]*=.*python3 \([^ ]*\).*/\1/p' "$f")
done < <(git ls-files 'system_files/usr/lib/systemd/*' 'system_files/etc/containers/systemd/*')
# chaque service activé à la construction existe (dans le dépôt, ou fourni par un paquet connu)
for u in $(grep -E '^(systemctl| )' build_files/smoky.sh | grep -oE '[A-Za-z0-9@_-]+\.(service|timer|path)' | sort -u); do
  case "$u" in supergfxd.service|thermald.service|fstrim.timer|rpm-ostreed-automatic.timer|ModemManager.service) continue ;; esac
  [ -f "system_files/usr/lib/systemd/system/$u" ] || [ -f "system_files/usr/lib/systemd/user/$u" ] || { echec "smoky.sh active $u, absent du dépôt"; ko=1; }
done
[ "$ko" -eq 0 ] && ok "fichiers lancés par les services"

etape "Droits d'exécution"
ko=0
for f in "${SHELLS[@]}"; do
  case "$f" in system_files/usr/bin/*|system_files/usr/libexec/*|build_files/*|tests/*|tools/*)
    [ "$(git ls-files -s "$f" | cut -c1-6)" = 100755 ] || { echec "pas exécutable dans git : $f (git update-index --chmod=+x)"; ko=1; } ;;
  esac
done
[ "$ko" -eq 0 ] && ok "scripts exécutables"

etape "Versions figées"
if grep -nE 'archive/(main|master|HEAD)|/releases/latest|@latest' build_files/socle/*.sh build_files/smoky.sh; then
  echec "un téléchargement n'est pas figé sur une révision"
else
  ok "téléchargements figés sur une révision"
fi
grep -q '@sha256:[0-9a-f]\{64\}' system_files/etc/containers/systemd/users/smoky-home.container && ok "moteur de Smoky Home figé par son empreinte" || echec "moteur de Smoky Home non figé"

etape "Serveurs des applis"
if sortie=$(python3 tests/test_serveurs.py 2>&1); then
  ok "$(printf '%s\n' "$sortie" | grep -oE 'Ran [0-9]+ tests' | sed 's/Ran /tests réussis : /; s/ tests//')"
else
  echec "tests des serveurs"; printf '%s\n' "$sortie" | tail -40
fi

printf '\n'
if [ "$echecs" -eq 0 ]; then echo "RÉSULTAT : tout est bon."; else echo "RÉSULTAT : $echecs problème(s)."; exit 1; fi
