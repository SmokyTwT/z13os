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

etape "Travaux de démarrage faits une fois par image"
# faux système : ligne de commande du noyau, lien vers le déploiement, mémoire dans /var
u=system_files/usr/libexec/smokyos/une-fois-par-image.sh
r=$(mktemp -d); ko=0
c1=$(printf 'a%.0s' {1..64}); c2=$(printf 'b%.0s' {1..64})
mkdir -p "$r/proc" "$r/sysroot/ostree/boot.1/default/xyz" "$r/sysroot/ostree/deploy/default/deploy"
echo "BOOT_IMAGE=(hd0,gpt2)/vmlinuz root=UUID=1 rw ostree=/ostree/boot.1/default/xyz/0 quiet" > "$r/proc/cmdline"
ln -s "../../../deploy/default/deploy/$c1.0" "$r/sysroot/ostree/boot.1/default/xyz/0"
essai() { local attendu="$1" quoi="$2"; shift 2; SMOKY_UNEFOIS_RACINE="$r" bash "$u" "$@" >/dev/null 2>&1; local code=$?
  [ "$code" = "$attendu" ] || { echec "une-fois-par-image : $quoi (code $code au lieu de $attendu)"; ko=1; }; }
essai 0 "jamais fait : à faire" appstream
essai 0 "note que c'est fait" appstream fait
essai 1 "même image : déjà fait" appstream
essai 0 "autre travail : à faire" mandb
ln -sfn "../../../deploy/default/deploy/$c2.0" "$r/sysroot/ostree/boot.1/default/xyz/0"
essai 0 "nouvelle image : à refaire" appstream
essai 0 "note pour la nouvelle image" appstream fait
essai 1 "nouvelle image : déjà fait" appstream
ln -sfn "../../../deploy/default/deploy/$c2.1" "$r/sysroot/ostree/boot.1/default/xyz/0"
essai 0 "même contenu, autre déploiement : à refaire" appstream
ln -sfn "../ailleurs" "$r/sysroot/ostree/boot.1/default/xyz/0"
essai 0 "lien inattendu : dans le doute, à faire" appstream
essai 0 "…et rien n'est noté" appstream fait
[ "$(cat "$r/var/lib/smokyos/fait-appstream")" = "$c2.0" ] || { echec "une-fois-par-image : la mémoire a été écrasée par une identité douteuse"; ko=1; }
echo "root=UUID=1 rw quiet" > "$r/proc/cmdline"
essai 0 "pas de système atomique : à faire" appstream
essai 0 "nom invalide : à faire, sans rien écrire" "../../etc/passwd" fait
[ "$(find "$r/var" -type f | wc -l)" = 1 ] || { echec "une-fois-par-image : fichier inattendu dans /var"; ko=1; }
rm -rf "$r"
[ "$ko" -eq 0 ] && ok "une-fois-par-image.sh : 13 cas (à faire, déjà fait, nouvelle image, cas douteux)"
for d in system_files/usr/lib/systemd/system/*.service.d/50-smokyos.conf; do
  grep -q '^ExecCondition=/usr/libexec/smokyos/une-fois-par-image.sh [a-z]*$' "$d" && grep -q '^ExecStartPost=/usr/libexec/smokyos/une-fois-par-image.sh [a-z]* fait$' "$d" \
    || echec "complément incomplet : $d"
done

etape "Diagnostic (smoky-diagnostic)"
# de fausses commandes « bavardes » : le rapport ne doit rien laisser passer de personnel
faux=$(mktemp -d)
cat > "$faux/journalctl" <<'EOF'
#!/bin/sh
echo "erreur dans /var/home/camille/Documents/secret.pdf et /home/camille/x"
echo "envoi vers camille.martin@exemple.fr depuis 192.168.1.42 (aa:bb:cc:dd:ee:ff)"
echo "GET https://moodle.exemple.fr/ws?wstoken=abcdef0123456789&x=1 password=hunter2"
EOF
chmod +x "$faux/journalctl"
rapport=$(HOME=/var/home/camille PATH="$faux:$PATH" bash system_files/usr/bin/smoky-diagnostic 2>&1)
rm -rf "$faux"
if printf '%s\n' "$rapport" | grep -qE 'camille|martin@|secret\.pdf|192\.168|aa:bb:cc|abcdef0123456789|hunter2'; then
  echec "smoky-diagnostic laisse passer une information personnelle"
  printf '%s\n' "$rapport" | grep -nE 'camille|martin@|secret\.pdf|192\.168|aa:bb:cc|abcdef0123456789|hunter2' | head -5
elif printf '%s\n' "$rapport" | grep -q 'wstoken=masqué' && printf '%s\n' "$rapport" | grep -q '^== Carte graphique'; then
  ok "rapport produit, informations personnelles masquées"
else
  echec "smoky-diagnostic : rapport incomplet"; printf '%s\n' "$rapport" | tail -15
fi

etape "Outils de mesure du démarrage"
if python3 tests/image/mesures.py --verifier >/dev/null 2>&1; then ok "lecture des mesures"; else echec "tests/image/mesures.py --verifier"; fi

etape "Carte graphique (Intel sur Smoky OS, Ultimate sur Windows)"
if sortie=$(python3 tests/test_gpu.py 2>&1); then
  ok "$(printf '%s\n' "$sortie" | grep -oE 'Ran [0-9]+ tests' | sed 's/Ran /tests réussis : /; s/ tests//')"
else
  echec "tests de la carte graphique"; printf '%s\n' "$sortie" | tail -40
fi

printf '\n'
if [ "$echecs" -eq 0 ]; then echo "RÉSULTAT : tout est bon."; else echo "RÉSULTAT : $echecs problème(s)."; exit 1; fi
