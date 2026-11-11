#!/usr/bin/env bash
# Vérifie une image Smoky OS construite, AVANT sa publication.
# Lancé par le build GitHub à l'intérieur de l'image (le dossier tests/ du dépôt monté sur /tests) :
#   podman run --rm --network=none -v ./tests:/tests:ro \
#     --mount type=image,source=IMAGE,destination=/image IMAGE bash /tests/image/verifier.sh
# Si une vérification échoue, l'image n'est pas publiée : le PC garde la version qu'il a.
#
# On vérifie ce qui rendrait le PC inutilisable ou une appli cassée si c'était faux :
# démarrage (noyau, image de démarrage), écran de connexion, services, applis, extensions.
set -uo pipefail

echecs=0
ok()        { printf '  ok      %s\n' "$1"; }
echec()     { printf '  ÉCHEC   %s\n' "$1"; echecs=$((echecs + 1)); }
attention() { printf '  note    %s\n' "$1"; }
titre()     { printf '\n== %s\n' "$1"; }
# verifie "description" commande… → ÉCHEC si la commande échoue
verifie() { local quoi="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$quoi"; else echec "$quoi"; fi; }

titre "Identité"
verifie "os-release porte le nom Smoky OS" grep -q '^PRETTY_NAME="Smoky OS (Fedora [0-9]*)"' /usr/lib/os-release
# /etc/hosts d'un conteneur qui tourne est celui du conteneur : on lit celui de l'image dans
# /image (l'image montée à part par le build)
ETC=/etc; [ -d /image/etc ] && ETC=/image/etc
verifie "homeassistant.local pointe vers ce PC (connexion Xiaomi de Smoky Home)" grep -qE '^127\.0\.0\.1[[:space:]]+homeassistant\.local' "$ETC/hosts"
verifie "adresse Moodle enregistrée" grep -q '^https://' /etc/smokyos/moodle-url

titre "Paquets"
for p in ffmpeg intel-media-driver asusctl supergfxctl thermald rclone zenity poppler-utils libsecret efibootmgr \
         google-chrome-stable gtk-update-icon-cache python3-pillow librsvg2-tools gnome-shell-extension-user-theme \
         plymouth-plugin-script; do
  verifie "paquet $p installé" rpm -q "$p"
done
for p in firefox gnome-tour glib2-devel; do
  if rpm -q "$p" >/dev/null 2>&1; then echec "paquet $p encore présent"; else ok "paquet $p absent"; fi
done
for p in dash-to-dock blur-my-shell appindicator caffeine; do
  rpm -q "gnome-shell-extension-$p" >/dev/null 2>&1 && ok "extension $p installée" || attention "extension $p absente des dépôts Fedora"
done

titre "Démarrage"
noyaux=0
for vmlinuz in /usr/lib/modules/*/vmlinuz; do
  [ -f "$vmlinuz" ] || continue
  noyaux=$((noyaux + 1))
  d=$(dirname "$vmlinuz"); k=$(basename "$d")
  taille=$(stat -c %s "$d/initramfs.img" 2>/dev/null || echo 0)
  if [ "$taille" -gt 20000000 ]; then ok "image de démarrage du noyau $k ($((taille / 1000000)) Mo)"; else echec "image de démarrage du noyau $k absente ou trop petite ($taille octets)"; fi
  [ "$taille" -lt 160000000 ] || attention "image de démarrage du noyau $k : $((taille / 1000000)) Mo, plus que prévu (regarde l'inventaire : qu'est-ce qui a grossi ?)"
  contenu=$(lsinitrd "$d/initramfs.img" 2>/dev/null)
  # l'écran Intel et le disque du Z13 (les autres pilotes utiles font partie du noyau lui-même
  # ou sont comparés à l'image publiée dans le résumé du build)
  manque=""
  for pilote in i915 xe nvme; do
    grep -qE "/$pilote\.ko" <<<"$contenu" || manque+="$pilote "
  done
  [ -z "$manque" ] && ok "noyau $k : écran Intel et disque NVMe dans l'image de démarrage" || echec "noyau $k : pilotes absents de l'image de démarrage : $manque"
  # pilotes graphiques NVIDIA/AMD : volontairement hors de l'image de démarrage (30-demarrage.sh)
  if grep -qE '/(nouveau|amdgpu|radeon)\.ko' <<<"$contenu"; then attention "noyau $k : pilotes NVIDIA/AMD revenus dans l'image de démarrage (elle grossit de 136 Mo)"; else ok "noyau $k : pas de pilote NVIDIA/AMD dans l'image de démarrage"; fi
  grep -q 'ostree-prepare-root' <<<"$contenu" && ok "noyau $k : le système atomique (ostree) est dans l'image de démarrage" || echec "noyau $k : ostree absent de l'image de démarrage"
  grep -q 'plymouth/themes/smoky/' <<<"$contenu" && ok "noyau $k : écran de démarrage Smoky présent" || echec "noyau $k : écran de démarrage Smoky absent"
done
[ "$noyaux" -eq 1 ] && ok "un seul noyau" || echec "$noyaux noyau(x) dans /usr/lib/modules (1 attendu)"
verifie "thème Plymouth par défaut : smoky" bash -c '[ "$(plymouth-set-default-theme)" = smoky ]'

titre "Écran de connexion"
GR=/usr/share/gnome-shell/gnome-shell-theme.gresource
gresource() { /usr/libexec/smokyos/outils/gresource "$@"; }      # outil gardé dans le socle
export -f gresource
verifie "fond Smoky dans le thème de connexion" bash -c "gresource list $GR | grep -q smoky-login.jpg"
sans_style=0
for css in $(gresource list "$GR" 2>/dev/null | grep '\.css$'); do
  # grep -c lit tout (pas de « tuyau fermé » compté comme un échec, contrairement à grep -q)
  [ "$(gresource extract "$GR" "$css" 2>/dev/null | grep -c 'smoky-login.jpg')" -ge 1 ] || sans_style=$((sans_style + 1))
done
[ "$sans_style" -eq 0 ] && ok "style Smoky ajouté à chaque feuille du thème de connexion" || echec "style Smoky absent de $sans_style feuille(s) du thème de connexion"
nb=$(gresource list "$GR" 2>/dev/null | wc -l)
nb_css=$(gresource list "$GR" 2>/dev/null | grep -c '\.css$')
[ "$nb" -ge 5 ] && [ "$nb_css" -ge 1 ] && ok "thème de connexion lisible ($nb fichiers dont $nb_css feuilles de style)" || echec "thème de connexion incomplet ($nb fichiers, $nb_css feuilles de style)"

titre "Services"
for u in supergfxd.service thermald.service fstrim.timer z13-firstboot.service smoky-focus-cleanup.service \
         smoky-gpu.service rpm-ostreed-automatic.timer smoky-flatpak-update.timer; do
  verifie "$u activé" systemctl is-enabled "$u"
done
for u in smoky-autoicons.path smoky-autoicons.service smoky-moodle.timer smoky-adaptive.service smoky-mail.timer \
         smoky-agenda-reminders.timer smoky-backup-check.timer; do
  verifie "$u activé (session)" systemctl --global is-enabled "$u"
done
verifie "ModemManager désactivé" bash -c '[ "$(systemctl is-enabled ModemManager.service 2>/dev/null)" = masked ]'
verifie "mises à jour automatiques préparées (stage)" grep -q '^AutomaticUpdatePolicy=stage' /etc/rpm-ostreed.conf
verifie "pare-feu en zone public" bash -c '[ "$(firewall-offline-cmd --get-default-zone)" = public ]'
if firewall-offline-cmd --zone=public --query-service=ssh >/dev/null 2>&1; then echec "ssh ouvert dans le pare-feu"; else ok "ssh fermé dans le pare-feu"; fi
# nos unités : pas d'erreur de syntaxe
unites=()
for u in /usr/lib/systemd/system/smoky-*.service /usr/lib/systemd/system/smoky-*.timer /usr/lib/systemd/system/z13-*.service; do
  [[ -f "$u" && "$u" != *@* ]] && unites+=("$u")      # les modèles (smoky-focus@) ne se vérifient pas seuls
done
erreurs=$(systemd-analyze verify --recursive-errors=no "${unites[@]}" 2>&1 | grep -E 'smoky-|z13-' | grep -viE 'is not executable|not found in path' || true)
[ -z "$erreurs" ] && ok "unités systemd Smoky sans erreur" || { echec "unités systemd Smoky"; printf '%s\n' "$erreurs" | sed 's/^/          /'; }

titre "Applis"
for f in /usr/bin/smoky-notes /usr/bin/smoky-center /usr/bin/smoky-mail /usr/bin/smoky-agenda /usr/bin/smoky-home \
         /usr/bin/smoky-portail /usr/bin/z13-notes-setup /usr/libexec/smokyos/smoky-app /usr/libexec/smokyos/smoky-webapp \
         /usr/libexec/smokyos/smoky-bootonce.sh /usr/libexec/smokyos/smoky-focus.sh /usr/libexec/z13os/firstboot.sh \
         /usr/libexec/z13os/user-setup.sh /usr/libexec/z13os/notes-sync.sh; do
  verifie "$f exécutable" test -x "$f"
done
# /opt (= /var/opt) n'existe qu'une fois le système démarré : ici on passe par le dossier réel
verifie "Google Chrome se lance (version)" /usr/lib/google/chrome/google-chrome --version
verifie "Chrome déplacé dans /usr/lib/google" test -x /usr/lib/google/chrome/chrome
verifie "lien /opt/google recréé au démarrage" grep -q '^L /var/opt/google - - - - /usr/lib/google$' /usr/lib/tmpfiles.d/z13os-chrome.conf
verifie "règles Chrome lisibles" python3 -c 'import json; json.load(open("/etc/opt/chrome/policies/managed/smokyos.json"))'
verifie "Chrome réglé pour Wayland" grep -q '^Exec=/usr/bin/google-chrome-stable --ozone-platform-hint=auto' /usr/share/applications/google-chrome.desktop
for a in netflix disney prime tf1 m6 drive spotify whatsapp claude moodle; do
  verifie "appli web $a" grep -q '^StartupWMClass=chrome-' "/usr/share/applications/z13-$a.desktop"
done
verifie "Python : tous les scripts Smoky se compilent" python3 - <<'PY'
import ast, pathlib, sys
ko = 0
for f in [*pathlib.Path("/usr/libexec").glob("smoky*/*.py")]:
    try:
        ast.parse(f.read_text(), str(f))
    except SyntaxError as e:
        print(e); ko = 1
sys.exit(ko)
PY
verifie "Python : GLib/Gio et Pillow disponibles" python3 -c 'import gi; gi.require_version("Gio", "2.0"); from gi.repository import Gio, GLib; from PIL import Image'
verifie "lien moodlemobile:// relié à Smoky Moodle (retour de la connexion de l'université)" grep -q '^x-scheme-handler/moodlemobile=.*smoky-moodle-auth.desktop' /usr/share/applications/mimeinfo.cache
verifie "liens http(s) reliés à Chrome" grep -q '^x-scheme-handler/https=.*google-chrome.desktop' /usr/share/applications/mimeinfo.cache
verifie "liste des matières lisible" python3 -c 'import json; assert len(json.load(open("/usr/share/smokyos/matieres.json"))["matieres"]) >= 10'
verifie "Smoky Home : intégration du robot (Dreame)" test -f /usr/share/smoky-home/custom_components/dreame_vacuum/manifest.json
verifie "Smoky Home : intégration Xiaomi Home" test -f /usr/share/smoky-home/custom_components/xiaomi_home/manifest.json
verifie "Smoky Home : configuration de départ" test -f /usr/share/smoky-home/seed/configuration.yaml

titre "Thème"
verifie "icônes WhiteSur" test -f /usr/share/icons/WhiteSur/index.theme
verifie "curseurs WhiteSur" test -d /usr/share/icons/WhiteSur-cursors/cursors
nb=$(ls /usr/share/icons/Smoky-icons/apps/256/*.png 2>/dev/null | wc -l)
[ "$nb" -ge 10 ] && ok "icônes Smoky générées ($nb)" || echec "icônes Smoky générées : $nb (10 attendues au moins)"
verifie "réglages GNOME par défaut de Smoky OS présents" grep -q "^icon-theme='Smoky-icons'" /usr/share/glib-2.0/schemas/zz1-z13os.gschema.override
verifie "réglages GNOME compilés après ceux de Smoky OS" bash -c '[ -s /usr/share/glib-2.0/schemas/gschemas.compiled ] && ! [ /usr/share/glib-2.0/schemas/zz1-z13os.gschema.override -nt /usr/share/glib-2.0/schemas/gschemas.compiled ]'
verifie "dock : applis Smoky dans les favoris par défaut" grep -q "favorite-apps=\['smoky-notes.desktop'" /usr/share/glib-2.0/schemas/zz1-z13os.gschema.override
avert=$(glib-compile-schemas --strict --dry-run /usr/share/glib-2.0/schemas 2>&1 | grep -i 'z13os' || true)
[ -z "$avert" ] && ok "tous les réglages par défaut de Smoky OS existent encore dans GNOME" || { attention "réglages par défaut ignorés par GNOME :"; printf '%s\n' "$avert" | sed 's/^/          /'; }

titre "Extensions GNOME Shell"
version=$(gnome-shell --version 2>/dev/null | grep -oE '[0-9]+' | head -1)
if [ -n "$version" ]; then
  for m in /usr/share/gnome-shell/extensions/smoky-*@smokyos/metadata.json; do
    nom=$(basename "$(dirname "$m")")
    if python3 -c 'import json, sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1]))["shell-version"] else 1)' "$m" "$version"; then
      ok "$nom accepte GNOME $version"
    else
      echec "$nom ne déclare pas GNOME $version (l'extension serait désactivée)"
    fi
  done
else
  echec "version de GNOME Shell introuvable"
fi

titre "Règles des images bootc"
if command -v bootc >/dev/null 2>&1; then
  if sortie=$(bootc container lint --no-truncate 2>&1); then
    ok "bootc container lint ($(printf '%s\n' "$sortie" | grep -ciE '^lint warning') avertissement(s), détail ci-dessous)"
    printf '%s\n' "$sortie" | head -60 | sed 's/^/          /'
  else
    echec "bootc container lint"
    printf '%s\n' "$sortie" | tail -30 | sed 's/^/          /'
  fi
else
  attention "bootc absent de l'image : règles non vérifiées"
fi

titre "Carte graphique (Intel sur Smoky OS, Ultimate sur Windows)"
verifie "réglages présents (/etc/smokyos/gpu.conf)" grep -q '^intel_auto=oui$' /etc/smokyos/gpu.conf
verifie "smokygpu.py répond (lecture seule)" bash -c 'python3 -I /usr/libexec/smokyos/smokygpu.py etat | python3 -c "import json, sys; e = json.load(sys.stdin); assert {\"mux\", \"interface\", \"probleme\"} <= set(e)"'
verifie "le redémarrage sur Windows passe par smokygpu.py" grep -q 'smokygpu.py windows' /usr/libexec/smokyos/smoky-bootonce.sh
# le noyau de l'image sait-il régler l'aiguillage ? (asus-armoury : noyaux récents ; asus-wmi : anciens)
recent=$(find /usr/lib/modules -name 'asus-armoury.ko*' 2>/dev/null | head -1)
ancien=$(find /usr/lib/modules -name 'asus-wmi.ko*' 2>/dev/null | head -1)
lit() { case "$1" in *.zst) zstd -dcq "$1" ;; *.xz) xz -dc "$1" ;; *.gz) gzip -dc "$1" ;; *) cat "$1" ;; esac; }
if [ -n "$recent" ] && [ "$(lit "$recent" 2>/dev/null | grep -ac 'gpu_mux_mode')" -ge 1 ]; then
  ok "noyau : réglage de l'aiguillage graphique présent (asus-armoury)"
elif [ -n "$ancien" ] && [ "$(lit "$ancien" 2>/dev/null | grep -ac 'gpu_mux_mode')" -ge 1 ]; then
  ok "noyau : réglage de l'aiguillage graphique présent (asus-wmi, ancienne forme)"
else
  attention "noyau : réglage de l'aiguillage graphique introuvable (asus-armoury : ${recent:-absent}) — le retour à Intel ne pourra rien faire"
fi
if SMOKY_RACINE=/ HOME=/tmp/verif-home python3 /tests/test_gpu.py >/tmp/verif-gpu.log 2>&1; then
  ok "tests de la carte graphique : $(tail -3 /tmp/verif-gpu.log | grep -oE 'Ran [0-9]+ tests' || echo réussis)"
else
  echec "tests de la carte graphique"
  tail -40 /tmp/verif-gpu.log | sed 's/^/          /'
fi

titre "Mémoire compressée (zram)"
verifie "réglages zram présents" grep -q 'KERNEL=="zram0".*vm.swappiness' /usr/lib/udev/rules.d/71-smokyos-zram.rules
verifie "zram activé par Fedora (sinon ces réglages ne servent à rien)" grep -q '^zram-size' /usr/lib/systemd/zram-generator.conf
if udevadm verify --help >/dev/null 2>&1; then
  verifie "règle udev valide" udevadm verify /usr/lib/udev/rules.d/71-smokyos-zram.rules
fi
verifie "aucun autre réglage ne fixe vm.swappiness" bash -c '! grep -rqsE "^\s*vm\.(swappiness|page-cluster)" /usr/lib/sysctl.d /etc/sysctl.d /etc/sysctl.conf'

titre "Travaux de démarrage faits une fois par image"
for u in fedora-atomic-desktop-appstream-cache-refresh fedora-atomic-desktop-mandb-update; do
  if [ -f "/usr/lib/systemd/system/$u.service" ]; then
    verifie "$u : lancé une fois par image, plus à chaque démarrage" bash -c "systemctl cat $u.service 2>/dev/null | grep -q '^ExecCondition=/usr/libexec/smokyos/une-fois-par-image.sh'"
  else
    attention "$u.service n'existe plus dans Fedora : le complément Smoky ne sert plus (à retirer)"
  fi
done
verifie "une-fois-par-image.sh : dans le doute, « à faire »" bash -c '/usr/libexec/smokyos/une-fois-par-image.sh appstream; [ $? -eq 0 ]'

titre "Diagnostic"
verifie "smoky-diagnostic produit son rapport" bash -c 'r=$(/usr/bin/smoky-diagnostic 2>&1); for t in "== Système" "== Carte graphique" "== Démarrage" "== Mémoire" "== Énergie" "== Disque"; do printf "%s\n" "$r" | grep -qF "$t" || exit 1; done'

titre "Serveurs des applis (lancés pour de vrai dans l'image)"
if SMOKY_RACINE=/ HOME=/tmp/verif-home python3 /tests/test_serveurs.py >/tmp/verif-serveurs.log 2>&1; then
  ok "tests des serveurs : $(tail -3 /tmp/verif-serveurs.log | grep -oE 'Ran [0-9]+ tests' || echo réussis)"
else
  echec "tests des serveurs"
  tail -40 /tmp/verif-serveurs.log | sed 's/^/          /'
fi

printf '\n'
if [ "$echecs" -eq 0 ]; then
  echo "RÉSULTAT : image valide, elle peut être publiée."
else
  echo "RÉSULTAT : $echecs vérification(s) en échec — image NON publiée."
  exit 1
fi
