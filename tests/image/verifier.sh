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
         google-chrome-stable gtk-update-icon-cache python3-pillow librsvg2-tools plymouth plymouth-plugin-script \
         iwlwifi-mvm-firmware nvidia-gpu-firmware alsa-sof-firmware NetworkManager-wifi firewalld pipewire wireplumber bluez flatpak \
         labwc greetd greetd-selinux gtk4-layer-shell python3-gobject python3-pam swayidle swaylock wlr-randr \
         xdg-desktop-portal-wlr gnome-keyring-pam power-profiles-daemon upower iio-sensor-proxy nautilus ptyxis \
         mate-polkit wlsunset blueman nm-connection-editor stevia; do
  verifie "paquet $p installé" rpm -q "$p"
done
# plus de GNOME Shell ni de GDM ; un seul gestionnaire de profils d'énergie (décision 4)
for p in firefox gnome-tour glib2-devel gdm gnome-shell tuned tuned-ppd; do
  if rpm -q "$p" >/dev/null 2>&1; then echec "paquet $p encore présent"; else ok "paquet $p absent"; fi
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
verifie "greetd lance l'écran de connexion Smoky" grep -q '^command = "/usr/libexec/smokyos/smoky-connexion.sh"' /etc/greetd/config.toml
verifie "écran de connexion sous le compte greetd" grep -q '^user = "greetd"' /etc/greetd/config.toml
verifie "compte greetd présent" getent passwd greetd
verifie "dossier de l'écran de connexion créé au démarrage (bouton Windows)" bash -c 'systemd-tmpfiles --cat-config 2>/dev/null | grep -q "^d /var/lib/greetd "'
verifie "bouton Windows : de quoi écrire le choix dans le menu de démarrage" bash -c 'command -v grub2-editenv || test -x /usr/libexec/smokyos/smoky-grubenv.py'
echo "  (grub2-editenv : $(command -v grub2-editenv || echo "absent, repli smoky-grubenv.py"))"
verifie "connexion : le trousseau est déverrouillé par le mot de passe" grep -q 'pam_gnome_keyring.so' /etc/pam.d/greetd
verifie "verrouillage : vérification PAM dédiée" grep -q '^auth .*include .*system-auth' /etc/pam.d/smoky-verrou
for f in /usr/libexec/smokyos/smoky-connexion.sh /usr/bin/smoky-session /usr/bin/smoky-bureau-cmd \
         /usr/libexec/smokyos/smoky-bureau.py /usr/libexec/smokyos/smoky-verrou.py /usr/libexec/smokyos/smoky-verrou.sh \
         /usr/libexec/smokyos/smoky-connexion.py /usr/libexec/smokyos/smoky-adaptive.py; do
  verifie "$(basename "$f") exécutable" test -x "$f"
done
verifie "session Smoky déclarée" grep -q '^Exec=/usr/bin/smoky-session' /usr/share/wayland-sessions/smoky.desktop
verifie "démarrage en mode graphique" bash -c '[ "$(systemctl get-default)" = graphical.target ]'

titre "Services"
for u in supergfxd.service thermald.service fstrim.timer z13-firstboot.service smoky-focus-cleanup.service \
         smoky-gpu.service rpm-ostreed-automatic.timer smoky-flatpak-update.timer greetd.service \
         power-profiles-daemon.service smoky-asusd-profils.service firewalld.service bluetooth.service \
         smoky-windows-connexion.path; do
  verifie "$u activé" systemctl is-enabled "$u"
done
for u in smoky-autoicons.path smoky-autoicons.service smoky-adaptive.service smoky-mail.timer \
         smoky-agenda-reminders.timer smoky-backup-check.timer smoky-courrier.timer; do
  verifie "$u activé (session)" systemctl --global is-enabled "$u"
done
verifie "Moodle en pause : plus de vérification toutes les 2 h" bash -c '[ -f /usr/share/smokyos/moodle-en-pause ] && ! systemctl --global is-enabled smoky-moodle.timer >/dev/null 2>&1'
# fedora-bootc active des services de serveur : rien n'écoute sur le réseau, pas de redémarrage tout seul
for u in sshd.service bootc-fetch-apply-updates.timer; do
  verifie "$u coupé" bash -c "[ \"\$(systemctl is-enabled $u 2>/dev/null)\" = masked ]"
done
for u in sssd.service systemd-homed.service; do
  verifie "$u désactivé" bash -c "! systemctl is-enabled $u >/dev/null 2>&1"
done
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
         /usr/libexec/smokyos/smoky-bootonce.sh /usr/libexec/smokyos/smoky-focus.sh /usr/libexec/smokyos/smoky-claude-connexion.sh \
         /usr/libexec/z13os/firstboot.sh \
         /usr/libexec/z13os/user-setup.sh /usr/libexec/z13os/notes-sync.sh; do
  verifie "$f exécutable" test -x "$f"
done
# /opt (= /var/opt) n'existe qu'une fois le système démarré : ici on passe par le dossier réel
verifie "Google Chrome se lance (version)" google-chrome-stable --version
# fedora-bootc : /opt est un vrai dossier de l'image (Silverblue le renvoyait vers /var/opt)
verifie "Chrome dans l'image (/opt/google)" bash -c 'test -x /opt/google/chrome/chrome && [ ! -L /opt ]'
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
verifie "réglages lisibles (thème)" gsettings get org.gnome.desktop.interface color-scheme
verifie "réglages de la page Système lisibles par le bureau (éclairage du soir, veille)" bash -c 'gsettings get org.gnome.settings-daemon.plugins.color night-light-enabled && gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout'
verifie "dock Smoky par défaut : Smoky puis Chrome en tête" python3 -c 'import json, sys; d = json.load(open("/usr/share/smoky-bureau/dock.json"))["dock"]; sys.exit(0 if d[:2] == ["smoky.desktop", "google-chrome.desktop"] and "smoky-notes.desktop" not in d else 1)'
avert=$(glib-compile-schemas --strict --dry-run /usr/share/glib-2.0/schemas 2>&1 | grep -i 'z13os' || true)
[ -z "$avert" ] && ok "tous les réglages par défaut de Smoky OS existent encore dans GNOME" || { attention "réglages par défaut ignorés par GNOME :"; printf '%s\n' "$avert" | sed 's/^/          /'; }

titre "Bureau Smoky"
verifie "le bureau Smoky se charge (GTK 4, layer-shell, verrouillage, PAM)" python3 -I -c '
import sys; sys.path.insert(0, "/usr/lib/smoky")
import smokybureau.bureau, smokybureau.verrou, smokybureau.connexion, smokybureau.clavier, smokybureau.energie, smokybureau.cmd, pam'
verifie "modules du bureau précompilés" bash -c 'ls /usr/lib/smoky/smokybureau/__pycache__/bureau.*.pyc >/dev/null'
for f in /usr/share/smoky-bureau/labwc/rc.xml /usr/share/smoky-bureau/labwc/menu.xml /usr/share/smoky-bureau/connexion/rc.xml; do
  verifie "$(basename "$(dirname "$f")")/$(basename "$f") lisible" python3 -c 'import sys, xml.etree.ElementTree as E; E.parse(sys.argv[1])' "$f"
done
verifie "thème des fenêtres Smoky" test -f /usr/share/themes/Smoky/labwc/themerc
verifie "agent polkit présent" test -x /usr/libexec/polkit-mate-authentication-agent-1
for f in blueman.desktop geoclue-demo-agent.desktop; do
  [ -f "/etc/xdg/autostart/$f" ] && verifie "$f ne se lance pas à la connexion" grep -q '^Hidden=true' "/etc/xdg/autostart/$f"
done
verifie "clavier à l'écran présent" bash -c 'command -v stevia || command -v phosh-osk-stevia'
verifie "style du bureau" test -s /usr/share/smoky-bureau/bureau.css
verifie "police des titres (Comfortaa)" bash -c 'fc-list | grep -qi comfortaa'
verifie "asusd ne change plus le profil d'énergie (réglage forcé à chaque démarrage)" grep -q 'change_platform_profile_on_battery' /usr/libexec/smokyos/smoky-asusd-profils.sh
unites_session=(/usr/lib/systemd/user/smoky-bureau*.service /usr/lib/systemd/user/smoky-bureau-session.target \
                /usr/lib/systemd/user/smoky-veille.service /usr/lib/systemd/user/smoky-verrou.service \
                /usr/lib/systemd/user/smoky-nuit.service /usr/lib/systemd/user/smoky-autorisation.service \
                /usr/lib/systemd/user/smoky-clavier-ecran.service)
erreurs=$(systemd-analyze --user verify --recursive-errors=no "${unites_session[@]}" 2>&1 | grep -E 'smoky-' | grep -viE 'is not executable|not found in path' || true)
[ -z "$erreurs" ] && ok "unités de session du bureau sans erreur" || { echec "unités de session du bureau :"; printf '%s\n' "$erreurs" | sed 's/^/          /'; }

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

titre "Énergie"
verifie "moins de réveils au repos (chien de garde NMI coupé, écritures groupées)" grep -q '^kernel.nmi_watchdog = 0' /usr/lib/sysctl.d/61-smokyos-energie.conf
verifie "aucun autre réglage ne rallume le chien de garde NMI" bash -c '! grep -rqsE "^\s*kernel\.nmi_watchdog\s*=\s*1" /usr/lib/sysctl.d /etc/sysctl.d /etc/sysctl.conf'
verifie "mesure d'énergie utilisable (smoky-diagnostic --energie)" bash -c 'smoky-diagnostic --energie 2 | grep -qE "Pas de batterie trouvée|^moyenne"'
verifie "un seul chef des profils d'énergie (power-profiles-daemon, sans tuned)" bash -c 'rpm -q power-profiles-daemon >/dev/null && ! rpm -q tuned-ppd >/dev/null 2>&1'

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

titre "Appli Smoky (nouvelle appli unique)"
verifie "lanceur exécutable" test -x /usr/bin/smoky
verifie "serveur présent" test -f /usr/lib/smoky/lancer.py
verifie "page présente" test -f /usr/share/smoky/index.html
verifie "raccourci dans la grille des applis" grep -q '^Exec=/usr/bin/smoky$' /usr/share/applications/smoky.desktop
verifie "icône de l'appli" test -f /usr/share/icons/hicolor/scalable/apps/smoky-appli.svg
verifie "Smoky dans le dock par défaut" grep -q '"smoky.desktop"' /usr/share/smoky-bureau/dock.json
verifie "modules Python précompilés (ouverture plus rapide)" bash -c 'n=$(ls /usr/lib/smoky/smoky/*.py | wc -l); p=$(ls /usr/lib/smoky/smoky/__pycache__/*.pyc 2>/dev/null | wc -l); [ "$p" -ge "$n" ]'
verifie "le serveur démarre avec le Python de l'image" python3 -I /usr/lib/smoky/lancer.py --help
if SMOKY_RACINE=/ HOME=/tmp/verif-home python3 /tests/test_smoky.py >/tmp/verif-smoky.log 2>&1; then
  ok "tests de l'appli : $(tail -3 /tmp/verif-smoky.log | grep -oE 'Ran [0-9]+ tests' || echo réussis)"
else
  echec "tests de l'appli Smoky"
  tail -40 /tmp/verif-smoky.log | sed 's/^/          /'
fi
verifie "rappels de l'agenda : service relié à l'appli Smoky" grep -q '^ExecStart=/usr/bin/python3 -I /usr/lib/smoky/lancer.py --rappels$' /usr/lib/systemd/user/smoky-agenda-reminders.service
if SMOKY_RACINE=/ HOME=/tmp/verif-home python3 /tests/test_agenda.py >/tmp/verif-agenda.log 2>&1; then
  ok "tests de l'agenda : $(tail -3 /tmp/verif-agenda.log | grep -oE 'Ran [0-9]+ tests' || echo réussis)"
else
  echec "tests de l'agenda"
  tail -40 /tmp/verif-agenda.log | sed 's/^/          /'
fi
# la page, dans le Chrome de l'image (sans fenêtre)
rm -f /tmp/verif-smoky-page-2.log
page() { SMOKY_RACINE=/ HOME=/tmp/verif-home SMOKY_CHROME=/usr/lib/google/chrome/chrome python3 /tests/test_smoky_page.py "$@"; }
if page >/tmp/verif-smoky-page.log 2>&1; then
  ok "page de l'appli dans le Chrome de l'image : $(tail -3 /tmp/verif-smoky-page.log | grep -oE 'Ran [0-9]+ tests' || echo réussie)"
else
  # second essai pour les seuls tests ratés (navigateur lent au mauvais moment), signalé ;
  # un échec qui se répète reste un échec
  mapfile -t rates < <(sed -nE 's/^(FAIL|ERROR): (setUpClass|tearDownClass) \(__main__\.([A-Za-z_0-9]+)\).*/\3/p
    s/^(FAIL|ERROR): ([A-Za-z_0-9]+) \(__main__\.([A-Za-z_0-9]+).*/\3.\2/p' /tmp/verif-smoky-page.log | sort -u)
  if [ "${#rates[@]}" -gt 0 ] && page "${rates[@]}" >/tmp/verif-smoky-page-2.log 2>&1; then
    attention "page de l'appli dans le Chrome de l'image : réussie au 2e essai pour ${rates[*]} (test instable, à corriger)"
    grep -v '^\[.*:ERROR:' /tmp/verif-smoky-page.log | grep -A12 '^FAIL\|^ERROR' | head -30 | sed 's/^/          /'
  else
    echec "page de l'appli Smoky dans le Chrome de l'image"
    journal=/tmp/verif-smoky-page.log; [ -s /tmp/verif-smoky-page-2.log ] && journal=/tmp/verif-smoky-page-2.log
    grep -v '^\[.*:ERROR:' "$journal" | tail -40 | sed 's/^/          /'
  fi
fi

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
