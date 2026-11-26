#!/usr/bin/env bash
# Essai d'une installation complète depuis l'ISO, dans une machine virtuelle UEFI (OVMF) :
#  1. l'installateur tourne tout seul avec un kickstart d'essai : celui de l'ISO (langue, clavier,
#     fuseau, image), plus ce qui se choisit d'habitude à l'écran (disque virtuel vide pris en
#     entier, compte « essai » administrateur), puis extinction ;
#  2. le système installé démarre ; un petit service injecté (identifiants SMBIOS, comme dans
#     tests/image/demarrer.sh) attend l'écran de connexion et écrit sur le port série la langue,
#     la disposition du clavier (système et écran de connexion), l'horloge et le compte.
# Rien ne touche au vrai PC : tout se passe dans des fichiers temporaires.
#   sudo bash tests/iso/essai-installation.sh smokyos.iso
# Paquets : qemu-system-x86, xorriso, ovmf. Sans KVM, l'essai est sauté (il durerait des heures).
set -uo pipefail
ISO=${1:?usage : essai-installation.sh smokyos.iso}
T=$(mktemp -d); QEMU=""
trap '[ -n "$QEMU" ] && kill "$QEMU" 2>/dev/null; rm -rf "$T"' EXIT
ATTENTE_INSTALLATION=${SMOKY_ATTENTE_INSTALLATION:-2400}
ATTENTE_DEMARRAGE=${SMOKY_ATTENTE_DEMARRAGE:-600}

if [ ! -w /dev/kvm ]; then echo "RÉSULTAT : essai d'installation sauté (pas de KVM ici)."; exit 0; fi
CODE=/usr/share/OVMF/OVMF_CODE_4M.fd VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
[ -f "$CODE" ] && [ -f "$VARS" ] || { echo "RÉSULTAT : firmware UEFI (paquet ovmf) introuvable."; exit 1; }

if ! xorriso -osirrox on -indev "$ISO" -extract /images/pxeboot/vmlinuz "$T/vmlinuz" \
     -extract /images/pxeboot/initrd.img "$T/initrd.img" -extract /EFI/BOOT/grub.cfg "$T/grub.cfg" \
     -extract /osbuild.ks "$T/osbuild.ks" >/dev/null 2>&1; then
  echo "RÉSULTAT : impossible de lire l'ISO (xorriso)."; exit 1
fi
opts=$(sed -n 's|^[[:space:]]*linux\(efi\)\{0,1\}[[:space:]]\{1,\}/images/pxeboot/vmlinuz[[:space:]]*||p' "$T/grub.cfg" | head -n 1)
opts=$(printf '%s' "$opts" | sed 's/\<rd\.live\.check\>//g; s/\<quiet\>//g; s/inst\.ks=[^ ]*//g')
case $opts in *inst.stage2=*) ;; *) echo "RÉSULTAT : options de démarrage introuvables dans le menu de l'ISO."; exit 1 ;; esac

# kickstart d'essai, sur un second CD (étiquette ESSAIKS)
mkdir -p "$T/ks"
{ cat "$T/osbuild.ks"; printf '\n'; cat <<'EOF'
text
zerombr
clearpart --all --initlabel --disklabel=gpt
autopart --noswap
rootpw --lock
user --name=essai --password=essai-smoky --plaintext --groups=wheel
poweroff
EOF
} > "$T/ks/ks.cfg"
if ! xorriso -as mkisofs -R -J -V ESSAIKS -o "$T/ks.iso" "$T/ks" >/dev/null 2>&1; then
  echo "RÉSULTAT : impossible de préparer le kickstart d'essai."; exit 1
fi
echo "-- kickstart d'essai"; sed 's/--password=[^ ]*/--password=…/' "$T/ks/ks.cfg"

attendre_fin() {   # attendre_fin SECONDES JOURNAL MOTIF → 0 si le motif apparaît ou si la machine s'éteint
  local debut=$SECONDS
  while (( SECONDS - debut < $1 )); do
    if [ -n "$3" ] && grep -aqE "$3" "$2"; then return 0; fi
    kill -0 "$QEMU" 2>/dev/null || { wait "$QEMU" 2>/dev/null; QEMU=""; return 0; }
    sleep 5
  done
  return 1
}

echo "== 1/2 Installation"
cp "$VARS" "$T/vars.fd"
truncate -s 40G "$T/disque.raw"
: > "$T/installation.log"
debut=$SECONDS
qemu-system-x86_64 -machine q35,accel=kvm -cpu host -smp 2 -m 4096 \
  -drive "if=pflash,format=raw,readonly=on,file=$CODE" -drive "if=pflash,format=raw,file=$T/vars.fd" \
  -kernel "$T/vmlinuz" -initrd "$T/initrd.img" \
  -append "$opts inst.ks=hd:LABEL=ESSAIKS:/ks.cfg inst.text console=ttyS0,115200" \
  -drive "file=$ISO,media=cdrom,if=none,id=iso,readonly=on" -device ide-cd,drive=iso,bus=ide.0 \
  -drive "file=$T/ks.iso,media=cdrom,if=none,id=ks,readonly=on" -device ide-cd,drive=ks,bus=ide.1 \
  -drive "file=$T/disque.raw,format=raw,if=virtio,cache=unsafe" \
  -display none -nic none -monitor none -no-reboot -serial "file:$T/installation.log" &
QEMU=$!
if ! attendre_fin "$ATTENTE_INSTALLATION" "$T/installation.log" ""; then
  echo "-- fin du journal de l'installation"; tail -n 60 "$T/installation.log" | tr -d '\r' | cut -c1-200
  echo "RÉSULTAT : l'installation ne s'est pas terminée en $ATTENTE_INSTALLATION s."; exit 1
fi
duree_installation=$((SECONDS - debut))
if ! grep -aq "Install finished" "$T/installation.log"; then
  echo "-- fin du journal de l'installation"; tail -n 60 "$T/installation.log" | tr -d '\r' | cut -c1-200
  echo "RÉSULTAT : la machine s'est éteinte sans finir l'installation ($duree_installation s)."; exit 1
fi
echo "installation terminée en $duree_installation s"

echo "== 2/2 Premier démarrage du système installé"
ESSAI_UNITE='[Unit]
Description=Smoky OS : essai de l ISO (machine virtuelle de test)
After=graphical.target
ConditionPathExists=!/etc/initrd-release
[Service]
Type=exec
ExecStart=/usr/bin/bash /run/credentials/@system/smoky.essai
'
ESSAI_LIEN='[Unit]
Wants=smoky-essai.service
'
# écrit sur le port série, en une fois à la fin : le noyau du système installé y écrit aussi (l'installateur
# lui a transmis console=ttyS0), et ses messages se mêleraient aux nôtres
ESSAI_SCRIPT='r=/run/smoky-essai.txt
{
echo "ESSAI début"
for i in $(seq 1 90); do pgrep -u greetd -x labwc >/dev/null && break; sleep 2; done
p=$(pgrep -u greetd -x labwc | head -n 1)
echo "ESSAI greetd $(systemctl is-active greetd)"
echo "ESSAI écran de connexion ${p:+lancé}"
if [ -n "$p" ]; then tr "\0" "\n" < "/proc/$p/environ" | grep "^XKB_" | sed "s/^/ESSAI connexion /"; fi
LC_ALL=C localectl status | sed "s/^ */ESSAI localectl /"
echo "ESSAI horloge $(tail -n 1 /etc/adjtime 2>/dev/null || echo absente)"
echo "ESSAI fuseau $(timedatectl show -p Timezone --value)"
echo "ESSAI compte $(id -nG essai 2>&1)"
echo "ESSAI en échec : $(systemctl --failed --no-legend --plain | awk "{print \$1}" | tr "\n" " ")"
echo "ESSAI fin"
} > "$r" 2>&1
{ printf "\n\n"; cat "$r"; printf "\n"; } > /dev/ttyS0
sleep 2
systemctl poweroff
'
b64() { printf '%s' "$1" | base64 -w0; }
: > "$T/demarrage.log"
debut=$SECONDS
qemu-system-x86_64 -machine q35,accel=kvm -cpu host -smp 2 -m 4096 \
  -drive "if=pflash,format=raw,readonly=on,file=$CODE" -drive "if=pflash,format=raw,file=$T/vars.fd" \
  -drive "file=$T/disque.raw,format=raw,if=virtio,cache=unsafe" \
  -device virtio-vga -display none -nic none -monitor none -no-reboot \
  -smbios "type=11,value=io.systemd.credential.binary:systemd.extra-unit.smoky-essai.service=$(b64 "$ESSAI_UNITE")" \
  -smbios "type=11,value=io.systemd.credential.binary:systemd.unit-dropin.graphical.target=$(b64 "$ESSAI_LIEN")" \
  -smbios "type=11,value=io.systemd.credential.binary:smoky.essai=$(b64 "$ESSAI_SCRIPT")" \
  -serial "file:$T/demarrage.log" &
QEMU=$!
attendre_fin "$ATTENTE_DEMARRAGE" "$T/demarrage.log" "ESSAI fin"
duree_demarrage=$((SECONDS - debut))
echo "-- ce que dit le système installé ($duree_demarrage s)"
essai_lignes() { grep -ao 'ESSAI [^[:cntrl:]]*' "$T/demarrage.log"; }
essai_lignes | sed 's/^ESSAI //'
if ! essai_lignes | grep -qx "ESSAI fin"; then
  echo "-- fin du journal série"; tail -n 30 "$T/demarrage.log" | tr -d '\r' | cut -c1-200
  echo "RÉSULTAT : installation faite ($duree_installation s), mais le système installé n'a pas répondu en $ATTENTE_DEMARRAGE s."
  exit 1
fi

e=$(essai_lignes)
manque=""
grep -qx "ESSAI greetd active" <<<"$e" || manque+=" greetd actif ;"
grep -qx "ESSAI écran de connexion lancé" <<<"$e" || manque+=" écran de connexion lancé ;"
grep -qx "ESSAI connexion XKB_DEFAULT_LAYOUT=fr" <<<"$e" || manque+=" écran de connexion en AZERTY (fr) ;"
grep -qE "^ESSAI localectl System Locale: LANG=fr_FR\.UTF-8" <<<"$e" || manque+=" langue du système en français ;"
grep -qE "^ESSAI localectl X11 Layout: fr$" <<<"$e" || manque+=" disposition du clavier du système fr ;"
grep -qx "ESSAI horloge LOCAL" <<<"$e" || manque+=" horloge du PC à l'heure locale (comme Windows) ;"
grep -qx "ESSAI fuseau Europe/Paris" <<<"$e" || manque+=" fuseau Europe/Paris ;"
grep -qE "^ESSAI compte .*\<wheel\>" <<<"$e" || manque+=" compte « essai » administrateur ;"
if [ -n "$manque" ]; then
  echo "RÉSULTAT : installation faite ($duree_installation s) et système démarré, mais il manque :${manque% ;}."
  exit 1
fi
echo "RÉSULTAT : installation complète en $duree_installation s ; le système installé démarre jusqu'à l'écran de connexion, en français et en AZERTY, fuseau Europe/Paris, horloge à l'heure locale, compte administrateur créé."
