#!/usr/bin/env bash
# Essai de démarrage : installe l'image sur un disque virtuel, puis la démarre DEUX fois dans
# une machine virtuelle (QEMU/KVM, UEFI), comme sur un vrai PC :
#   1er démarrage : celui qui suit une installation ou une mise à jour (travaux uniques) ;
#   2e démarrage  : celui de tous les jours. C'est lui qu'on mesure.
# Réussi si le système arrive les deux fois jusqu'à l'écran de connexion. Lancé par le build
# GitHub avant chaque publication :
#   sudo bash tests/image/demarrer.sh localhost/smokyos:build [dossier de travail]
# Ce que l'essai ne voit pas : le matériel du Z13 (écran tactile, carte ASUS, Wi-Fi) et
# l'apparence. Il répond à une question : « est-ce que cette image démarre, et en combien de
# temps ? ». Les durées sont celles d'une petite machine virtuelle : elles servent à comparer
# deux images entre elles, pas à prédire celles du Z13.
#
#   SMOKY_RELIRE=journal     rejoue seulement l'analyse sur un journal série enregistré
#   SMOKY_REFERENCE=1        image de comparaison (déjà publiée) : pas de vérification propre
#                            à la version en cours de construction
set -uo pipefail

IMAGE="${1:?usage : demarrer.sh IMAGE [dossier]}"
T="${2:-/tmp/smoky-vm}"
ATTENTE="${SMOKY_ATTENTE_DEMARRAGE:-600}"        # secondes au plus pour atteindre l'écran de connexion
ECHEC='Kernel panic|emergency mode|Reached target emergency|dracut-emergency|Failed to mount /sysroot|ostree-prepare-root.*(failed|error)'
# écran de connexion : GDM (images d'avant la refonte) ou greetd + écran de connexion Smoky
GDM_KO='(gdm|greetd)\.service: (Failed|Main process exited)|Failed to start (gdm|greetd)\.service'
AFFICHE='Started gdm\.service|écran de connexion Smoky affiché|smoky-mesure\[[0-9]+\]: +[0-9]+ /usr/bin/python3 -I /usr/libexec/smokyos/smoky-connexion\.py'
QEMU=""

mkdir -p "$T"

# Journal nettoyé (retours chariot, couleurs) écrit dans un fichier : toutes les recherches se
# font ensuite sur ce fichier. Surtout pas « commande | grep -q » ici : grep s'arrête à la
# première ligne trouvée, la commande d'avant reçoit « tuyau fermé », et avec pipefail une
# recherche RÉUSSIE est alors comptée comme un échec (vécu : une image saine refusée).
nettoyer() { tr -d '\r' < "$1" | sed -E 's/\x1b\[[0-9;:?]*[A-Za-z]//g' > "$2"; }

# etat_du_journal JOURNAL → echec | gdm | graphique | attente
etat_du_journal() {
  if grep -qaE "$ECHEC" "$1"; then echo echec
  elif grep -qaE "$GDM_KO" "$1"; then echo gdm
  elif grep -qaE 'Reached target graphical\.target' "$1"; then echo graphique
  else echo attente; fi
}

# --- Mesures prises dans la machine virtuelle -------------------------------------------------
# Un petit service est ajouté à la machine virtuelle SANS toucher à l'image : il lui est passé
# par le firmware virtuel (« credentials » de systemd). Il attend la fin du démarrage, relève
# les durées, la mémoire et ce qui tourne, puis éteint proprement la machine.
read -r -d '' MESURE_SCRIPT <<'EOS' || true
for _ in $(seq 90); do systemd-analyze time >/dev/null 2>&1 && break; sleep 2; done
sleep 20
n=1; [ -e /var/lib/smoky-mesure ] && n=2
echo "SMOKY-MESURE-DEBUT $n"
echo "== durée"; systemd-analyze time 2>&1
echo "== services les plus longs à démarrer"; systemd-analyze blame 2>&1 | grep -v '\.device$' | sed -n '1,25p'
echo "== chaîne critique (ce qui retarde la fin du démarrage)"; systemd-analyze critical-chain graphical.target 2>&1 | sed -n '4,22p'
echo "== chaîne critique de l'écran de connexion"; systemd-analyze critical-chain display-manager.service 2>&1 | sed -n '4,16p'
echo "== écran de connexion Smoky"; pgrep -a -u greetd 2>&1 | cut -c1-150 | head -5
echo "== services qui tournent"; systemctl list-units --type=service --state=running --no-legend --plain 2>&1 | awk '{print $1}' | sort | tr '\n' ' '; echo
echo "== services en échec"; systemctl list-units --failed --no-legend --plain 2>&1 | awk '{print $1}' | tr '\n' ' '; echo
echo "== mémoire (Mo)"; free -m 2>&1
echo "== processus les plus gros (Mo)"; ps -eo rss,comm --sort=-rss | awk 'NR>1 && NR<=26 {printf "%7.1f %s\n", $1/1024, $2}'
echo "== nombre de processus"; ps -e --no-headers | wc -l
echo "== mémoire compressée"; sysctl vm.swappiness vm.page-cluster 2>&1 | tr '\n' ' '; echo; swapon --show=NAME,SIZE --noheadings 2>&1 | tr '\n' ' '; echo
if [ "$n" = 2 ] && [ -e /etc/smokyos/essai-connexion ]; then
  # Bouton « Windows » de l'écran de connexion : il l'actionne tout seul en machine virtuelle de test
  # (fichier déposé au 1er démarrage). Pas de Windows ici : la réponse attendue est « Windows
  # introuvable », qui prouve que la demande est bien arrivée jusqu'au service système.
  echo "== bouton Windows de l'écran de connexion"
  for _ in $(seq 45); do journalctl -b -t smoky-connexion -o cat 2>/dev/null | grep -q '^bouton Windows : ' && break; sleep 2; done
  ligne=$(journalctl -b -t smoky-connexion -o cat 2>/dev/null | grep '^bouton Windows : ' | tail -1)
  [ -n "$ligne" ] || ligne="aucune réponse de l'écran de connexion"   # (apostrophe hors de ${…:-…} : bash l'y prend pour un guillemet)
  echo "$ligne"
  journalctl -b -u smoky-windows-connexion.service -o cat --no-pager 2>&1 | tail -4
  ls -laZ /var/lib/greetd 2>&1 | head -5
  journalctl -b -o cat --no-pager 2>/dev/null | grep -E 'avc: +denied' | grep -E 'xdm_t|greet' | tail -5
  case "$ligne" in
    *"Windows introuvable"*|*"firmware refuse"*|*"redémarrage"*) echo "SMOKY-WINDOWS ok" ;;
    *) echo "SMOKY-WINDOWS ko" ;;
  esac
fi
if [ "$n" = 2 ] && systemctl is-active -q greetd.service && [ -s /var/lib/smoky-mesure-mdp ]; then
  # Bureau Smoky : on se connecte vraiment, comme l'écran de connexion (protocole de greetd),
  # puis on regarde si labwc et le bureau Smoky tournent dans la session du compte d'essai
  echo "== connexion au bureau Smoky (compte essai)"
  python3 - <<'PY' 2>&1
import json, socket, struct, subprocess
mdp = open("/var/lib/smoky-mesure-mdp").read().strip()
pid = subprocess.run(["pgrep", "-u", "greetd", "-f", "smoky-connexion.py"], capture_output=True, text=True).stdout.split()
env = open(f"/proc/{pid[0]}/environ", "rb").read().split(b"\0")
chemin = [e.split(b"=", 1)[1].decode() for e in env if e.startswith(b"GREETD_SOCK=")][0]
s = socket.socket(socket.AF_UNIX)
s.connect(chemin)
def lire(n):
    d = b""
    while len(d) < n:
        d += s.recv(n - len(d))
    return d
def envoyer(m):
    c = json.dumps(m).encode()
    s.sendall(struct.pack("=I", len(c)) + c)
    return json.loads(lire(struct.unpack("=I", lire(4))[0]))
r = envoyer({"type": "create_session", "username": "essai"})
while r.get("type") == "auth_message":
    r = envoyer({"type": "post_auth_message_response",
                 "response": mdp if r.get("auth_message_type") in ("secret", "visible") else None})
print("mot de passe :", r.get("type"), r.get("description", ""))
if r.get("type") == "success":
    print("ouverture :", envoyer({"type": "start_session", "cmd": ["/usr/bin/smoky-session"], "env": []}).get("type"))
PY
  pkill -u greetd -f smoky-connexion.py     # greetd ouvre la session quand l'écran de connexion se ferme
  sleep 25
  echo "== processus de la session"; pgrep -a -u essai 2>&1 | cut -c1-120 | head -25
  if pgrep -u essai -x labwc >/dev/null && pgrep -u essai -f smoky-bureau.py >/dev/null; then
    echo "SMOKY-SESSION ok"
  else
    echo "SMOKY-SESSION absente"
  fi
  echo "== erreurs de la session"; journalctl -b _UID=1000 -p warning --no-pager -o cat 2>&1 | grep -v -i 'egl\|mesa' | tail -20
fi
echo "SMOKY-MESURE-FIN $n"
if [ "$n" = 1 ]; then
  # un compte ordinaire, comme sur un vrai PC : au second démarrage, l'écran de connexion
  # affiche la liste des comptes (et le bureau Smoky est essayé avec ce compte)
  mdp=$(head -c 18 /dev/urandom | base64)
  useradd -m -u 1000 -c "Essai" essai 2>&1 && echo "essai:$mdp" | chpasswd 2>&1
  (umask 077; printf '%s\n' "$mdp" > /var/lib/smoky-mesure-mdp)
  # au second démarrage, l'écran de connexion essaiera son bouton « Windows » (voir connexion.py)
  mkdir -p /etc/smokyos && echo windows > /etc/smokyos/essai-connexion
fi
touch /var/lib/smoky-mesure
sleep 2
systemctl poweroff
EOS
MESURE_UNITE='[Unit]
Description=Smoky OS : mesures de l essai de démarrage (machine virtuelle de test)
After=graphical.target
ConditionPathExists=!/etc/initrd-release
[Service]
Type=exec
SyslogIdentifier=smoky-mesure
ExecStart=/usr/bin/bash /run/credentials/@system/smoky.mesure
'
MESURE_LIEN='[Unit]
Wants=smoky-mesure.service
'
b64() { printf '%s' "$1" | base64 -w0; }

lancer_vm() {   # journal série
  : > "$1"
  qemu-system-x86_64 -machine "q35,accel=$ACCEL" -cpu "$CPU" -smp 2 -m 4096 \
    -drive "if=pflash,format=raw,readonly=on,file=$CODE" \
    -drive "if=pflash,format=raw,file=$T/vars.fd" \
    -drive "file=$T/disque.raw,format=raw,if=virtio,cache=unsafe" \
    -device virtio-vga -display none -nic none -monitor none -no-reboot \
    -smbios "type=11,value=io.systemd.credential.binary:systemd.extra-unit.smoky-mesure.service=$(b64 "$MESURE_UNITE")" \
    -smbios "type=11,value=io.systemd.credential.binary:systemd.unit-dropin.graphical.target=$(b64 "$MESURE_LIEN")" \
    -smbios "type=11,value=io.systemd.credential.binary:smoky.mesure=$(b64 "$MESURE_SCRIPT")" \
    -serial "file:$1" &
  QEMU=$!
}

# un_demarrage N JOURNAL → remplit ETAT[N], DUREE[N] (jusqu'à l'écran de connexion), ARRET[N]
un_demarrage() {
  local n="$1" serie="$2" etat=attente debut duree arret="?" t0
  lancer_vm "$serie"
  debut=$(date +%s)
  while [ $(( $(date +%s) - debut )) -lt "$ATTENTE" ]; do
    if grep -qaE "$ECHEC" "$serie"; then etat=echec; break; fi
    if grep -qaE 'Reached target graphical\.target' "$serie"; then etat=graphique; break; fi
    kill -0 "$QEMU" 2>/dev/null || { etat=arret; break; }
    sleep 3
  done
  duree=$(( $(date +%s) - debut ))
  if [ "$etat" = graphique ]; then
    # l'écran de connexion (GDM) démarre juste après. On attend la fin des mesures (qui
    # éteignent la machine) : au moins 40 s pendant lesquelles GDM peut s'installer… ou tomber.
    for _ in $(seq 75); do
      grep -qaE "$GDM_KO" "$serie" && { etat=gdm; break; }
      grep -qaF "SMOKY-MESURE-FIN" "$serie" && break
      kill -0 "$QEMU" 2>/dev/null || break
      sleep 2
    done
    # arrêt propre demandé par le service de mesure : combien de temps met la machine à s'éteindre ?
    if grep -qaF "SMOKY-MESURE-FIN" "$serie"; then
      t0=$(date +%s)
      for _ in $(seq 60); do kill -0 "$QEMU" 2>/dev/null || break; sleep 2; done
      if kill -0 "$QEMU" 2>/dev/null; then arret="plus de 120"; else arret=$(( $(date +%s) - t0 )); fi
    fi
  fi
  kill "$QEMU" 2>/dev/null; wait "$QEMU" 2>/dev/null
  ETAT[n]=$etat; DUREE[n]=$duree; ARRET[n]=$arret
}

# mesures N JOURNAL_PROPRE → écrit $T/mesures-N.txt (bloc relevé dans la machine virtuelle)
# À ce bloc s'ajoutent des relevés tirés du journal série : quand l'écran de connexion est lancé
# puis affiché (secondes depuis le lancement du noyau), durée de l'arrêt, et ce qui l'a retardé.
instant() { grep -aE "$1" "$2" | sed -n '1p' | sed -E 's/^\[ *([0-9]+\.[0-9])[0-9]*\].*/\1/'; }
mesures() {
  local sortie="$T/mesures-$1.txt"
  grep -aE '^\[[ 0-9.]+\] smoky-mesure\[[0-9]+\]: ' "$2" | sed -E 's/^\[[ 0-9.]+\] smoky-mesure\[[0-9]+\]: ?//' \
    | sed -n "/^SMOKY-MESURE-DEBUT $1/,/^SMOKY-MESURE-FIN $1/p" | grep -avE '^SMOKY-MESURE-' > "$sortie" || true
  [ -s "$sortie" ] || return 0
  {
    echo "== écran de connexion (secondes depuis le lancement du noyau)"
    echo "lancé $(instant 'systemd\[1\]: Started (gdm|greetd)\.service' "$2")"
    echo "affiché $(instant 'systemd\[[0-9]+\]: Started org\.gnome\.Shell@[a-z0-9]+\.service|écran de connexion Smoky affiché' "$2")"
    echo "== arrêt"
    echo "durée ${ARRET[$1]}"
    # ce qui a refusé de s'arrêter à temps (attendu jusqu'au délai, puis tué)
    sed -n '/SMOKY-MESURE-FIN/,$p' "$2" | grep -aE "State 'stop-[a-z]+' timed out|Failed with result 'timeout'|stop job is running" \
      | sed -E 's/^\[[ 0-9.]+\] //; s/\x1b\[[0-9;:]*m//g' | sort -u | sed -n '1,8p' | sed 's/^/retard : /'
  } >> "$sortie"
}

ETAT=([1]=attente [2]=absent); DUREE=([1]="?" [2]="?"); ARRET=([1]="?" [2]="?")
if [ -n "${SMOKY_RELIRE:-}" ]; then
  # rejoue l'analyse sur un journal enregistré (un seul démarrage)
  rm -f "$T"/serie-*.log "$T"/serie-*.txt "$T"/mesures-*.txt
  cp "$SMOKY_RELIRE" "$T/serie-1.log"
  ETAT[1]=$(etat_du_journal "$T/serie-1.log")
else
  rm -f "$T/disque.raw" "$T"/serie-*.log "$T"/serie-*.txt "$T"/mesures-*.txt "$T/vars.fd"

  echo "== 1/4 Installation de l'image sur un disque virtuel"
  truncate -s 24G "$T/disque.raw"
  # bootc install : l'installateur fourni par l'image elle-même. Options :
  #  --generic-image     disque démarrable partout (BIOS et UEFI), sans rien écrire dans un firmware
  #  --via-loopback      la cible est un fichier
  #  --skip-fetch-check  l'image vient d'être construite ici, elle n'est pas encore sur un registre
  #  --disable-selinux   la machine de construction (Ubuntu) n'a pas SELinux : on ne peut pas y
  #                      poser fidèlement les étiquettes ; l'essai démarre donc sans SELinux
  #  console série       tout le journal du démarrage sort sur le port série, lu plus bas
  if ! podman run --rm --privileged --pid=host --security-opt label=type:unconfined_t \
        -v /dev:/dev -v /var/lib/containers:/var/lib/containers -v "$T":/output \
        "$IMAGE" bootc install to-disk --generic-image --via-loopback --filesystem btrfs \
          --skip-fetch-check --disable-selinux \
          --karg console=ttyS0,115200n8 --karg systemd.journald.forward_to_console=1 \
          /output/disque.raw; then
    echo "RÉSULTAT : l'installation sur le disque virtuel a échoué."
    exit 1
  fi

  CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
  VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
  [ -f "$CODE" ] && [ -f "$VARS" ] || { echo "RÉSULTAT : firmware UEFI (paquet ovmf) introuvable."; exit 1; }
  cp "$VARS" "$T/vars.fd"
  ACCEL=kvm; CPU=host
  [ -w /dev/kvm ] || { ACCEL=tcg; CPU=max; ATTENTE=$((ATTENTE * 4)); echo "note : pas de KVM ici, émulation lente"; }
  # à la sortie : machine arrêtée, disque virtuel supprimé (une dizaine de Go)
  trap 'kill "$QEMU" 2>/dev/null; wait "$QEMU" 2>/dev/null; rm -f "$T/disque.raw"' EXIT

  echo "== 2/4 Premier démarrage (celui qui suit une installation)"
  un_demarrage 1 "$T/serie-1.log"
  echo "   état : ${ETAT[1]} après ${DUREE[1]} s"
  if [ "${ETAT[1]}" = graphique ]; then
    echo "== 3/4 Second démarrage (celui de tous les jours)"
    un_demarrage 2 "$T/serie-2.log"
    echo "   état : ${ETAT[2]} après ${DUREE[2]} s"
  fi
fi

echo "== 4/4 Résultat"
for n in 1 2; do
  [ -f "$T/serie-$n.log" ] || continue
  nettoyer "$T/serie-$n.log" "$T/serie-$n.txt"
  mesures "$n" "$T/serie-$n.txt"
  duree_systeme=$(grep -aE 'Startup finished in' "$T/serie-$n.txt" | tail -n 1 | sed -E 's/^.*Startup finished in //')
  [ -n "$duree_systeme" ] && echo "  durée du démarrage n°$n (dans la machine virtuelle) : $duree_systeme"
  [ "${ARRET[n]}" != "?" ] && echo "  durée de l'arrêt n°$n : ${ARRET[n]} s"
  if [ -s "$T/mesures-$n.txt" ]; then
    lance=$(sed -n 's/^lancé //p' "$T/mesures-$n.txt"); affiche=$(sed -n 's/^affiché //p' "$T/mesures-$n.txt")
    [ -n "$lance$affiche" ] && echo "  écran de connexion n°$n : lancé à ${lance:-?} s, affiché à ${affiche:-?} s (depuis le lancement du noyau)"
    sed -n "s/^retard : /  arrêt n°$n retardé par : /p" "$T/mesures-$n.txt"
  fi
done
PROPRE="$T/serie-1.txt"
echecs=$(cat "$T"/serie-?.txt | grep -aE 'Failed to start |\.service: Failed with result' | sed -E 's/^\[[ 0-9.]+\] //' | sort -u | sed -n '1,15p')
if [ -n "$echecs" ]; then
  echo "  services en échec dans la machine virtuelle (souvent normal sans le matériel du Z13) :"
  printf '%s\n' "$echecs" | sed -E 's/\x1b\[[0-9;:]*m//g; s/^/    /'
  # pour chacun, ce que le journal disait juste avant l'échec (hors assistant de première installation)
  for unite in $(printf '%s\n' "$echecs" | grep -oE '[A-Za-z0-9@:_.-]+\.service' | grep -v 'gnome-initial-setup' | sort -u); do
    echo "    -- $unite, juste avant l'échec :"
    cat "$T"/serie-?.txt | grep -aF -B6 -e "$unite: Failed" -e "Failed to start $unite" | sed -n '1,9p' | cut -c1-220 | sed 's/^/       /'
  done
fi
if [ -s "$T/mesures-2.txt" ]; then
  echo "--- Mesures du second démarrage (machine virtuelle : 2 cœurs, 4 Go) ---"
  sed 's/^/  /' "$T/mesures-2.txt"
elif [ -z "${SMOKY_RELIRE:-}" ]; then
  echo "  note : mesures du second démarrage indisponibles"
fi

# réglages de la mémoire compressée : simple constat (non bloquant)
if [ -s "$T/mesures-2.txt" ] && [ -z "${SMOKY_REFERENCE:-}" ] && ! grep -qa 'vm.swappiness = 180' "$T/mesures-2.txt"; then
  echo "  attention : réglages de la mémoire compressée (zram) non appliqués dans la machine virtuelle"
fi

# smoky-gpu.service passe avant l'écran de connexion : ici (pas de carte ASUS), il doit avoir
# tourné sans rien trouver à faire, et sans erreur
gpu_ok() {
  [ -n "${SMOKY_REFERENCE:-}" ] && return 0
  grep -qaF "smokygpu : pas d'aiguillage" "$1" && ! grep -qaE 'smoky-gpu\.service: (Failed|Main process exited)' "$1"
}

case "${ETAT[1]}" in
  graphique)
    if grep -qa 'SMOKY-SESSION absente' "$T/serie-2.txt"; then
      echo "RÉSULTAT : l'écran de connexion s'affiche, mais le bureau Smoky ne démarre pas après la connexion."
      sed -n '/connexion au bureau Smoky/,/SMOKY-MESURE-FIN/p' "$T/serie-2.txt" | sed -E 's/^\[[ 0-9.]+\] smoky-mesure\[[0-9]+\]: ?//' | tail -n 50
      exit 1
    fi
    if ! grep -qaE "$AFFICHE" "$PROPRE"; then
      echo "RÉSULTAT : le système démarre (${DUREE[1]} s) mais l'écran de connexion n'apparaît pas dans le journal."
      grep -aE 'greetd|labwc|smoky-connexion|smokybureau' "$PROPRE" | tail -n 25
    elif ! gpu_ok "$PROPRE"; then
      echo "RÉSULTAT : le système démarre (${DUREE[1]} s), mais le service de la carte graphique (smoky-gpu) n'a pas tourné comme prévu."
      grep -aE 'smoky-gpu|smokygpu' "$PROPRE" | tail -n 20
    elif [ -n "${SMOKY_RELIRE:-}" ]; then
      echo "RÉSULTAT : l'image démarre jusqu'à l'écran de connexion (journal rejoué)."
      exit 0
    elif [ "${ETAT[2]}" = graphique ] && grep -qaE "$AFFICHE" "$T/serie-2.txt" && gpu_ok "$T/serie-2.txt"; then
      session=""
      grep -qa 'SMOKY-SESSION ok' "$T/serie-2.txt" && session=", et le bureau Smoky s'ouvre après la connexion"
      # bouton Windows de l'écran de connexion : signalé (sans bloquer la publication) s'il ne passe pas
      if grep -qa 'SMOKY-WINDOWS ok' "$T/serie-2.txt"; then
        session="$session ; le bouton Windows de l'écran de connexion répond"
      elif grep -qa 'SMOKY-WINDOWS ko' "$T/serie-2.txt"; then
        echo "::warning::le bouton Windows de l'écran de connexion ne passe pas (détail ci-dessous)"
        sed -n '/bouton Windows de l.écran de connexion/,/SMOKY-WINDOWS/p' "$T/serie-2.txt" | sed -E 's/^\[[ 0-9.]+\] smoky-mesure\[[0-9]+\]: ?//'
      fi
      echo "RÉSULTAT : l'image démarre deux fois de suite jusqu'à l'écran de connexion (${DUREE[1]} s, puis ${DUREE[2]} s)$session."
      exit 0
    else
      echo "RÉSULTAT : le premier démarrage réussit (${DUREE[1]} s), mais pas le second (état : ${ETAT[2]})."
      PROPRE="$T/serie-2.txt"
    fi
    ;;
  gdm)    echo "RÉSULTAT : le système démarre mais l'écran de connexion plante." ;;
  echec)  echo "RÉSULTAT : le démarrage a échoué (mode de secours ou erreur du noyau)." ;;
  arret)  echo "RÉSULTAT : la machine virtuelle s'est arrêtée avant la fin du démarrage." ;;
  *)      echo "RÉSULTAT : toujours pas d'écran de connexion après ${ATTENTE} s." ;;
esac
echo "--- 60 dernières lignes du démarrage ---"
[ -f "$PROPRE" ] && tail -n 60 "$PROPRE"
exit 1
