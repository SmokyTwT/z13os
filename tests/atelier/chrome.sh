#!/usr/bin/env bash
# Chrome sous Wayland dans l'atelier : 1) les 131 caractères du clavier de session tapés par le vrai
# clavier virtuel arrivent tels quels, ⏎/⌫ ont les bons codes ; 2) Chrome signale son champ (méthode
# de saisie : il faut le labwc 0.7.4 de preparer.sh). CAPTURES=1 : en plus, le vrai clavier à l'écran
# par-dessus Chrome quand le champ, puis un bouton, puis le champ ont la main (captures/chrome-*.png).
# À lancer par bureau.sh. DRAPEAUX : options de Chrome en plus (ex. --enable-wayland-ime).
set -u
ICI=$(cd "$(dirname "$0")" && pwd)
command -v google-chrome > /dev/null || { echo "SAUTÉ Chrome : google-chrome absent"; exit 0; }
chrome() {  # $1 = profil, $2 = adresse
  # shellcheck disable=SC2086
  google-chrome --ozone-platform=wayland --no-sandbox --no-first-run --no-default-browser-check \
    --user-data-dir="$ATELIER/$1" --remote-debugging-port=9333 ${DRAPEAUX:-} "$2" > "$ATELIER/$1.log" 2>&1 &
}
chrome chrome-frappe "file://$ICI/chrome-page.html"
sleep 5
python3 -I "$ICI/ime-client.py" 2 | tee "$ATELIER/saisie.txt"
sleep 1
curl -s http://127.0.0.1:9333/json > "$ATELIER/pages.json"
pkill -f "$ATELIER/chrome-frappe"; sleep 1
python3 - "$ATELIER" <<'PY'
import html, json, os, sys
dossier = sys.argv[1]
pages = [p for p in json.load(open(os.path.join(dossier, "pages.json"))) if p.get("type") == "page"]
titre = html.unescape(pages[0]["title"]) if pages else ""
attendu = open(os.path.join(dossier, "attendu.txt"), encoding="utf-8").read()
recu, _, touches = (titre[2:] if titre.startswith("V:") else "").partition("|CODES|")
ecarts = [(i, a, b) for i, (a, b) in enumerate(zip(attendu, recu)) if a != b][:6]
ok = recu == attendu and touches == "Enter,KeyX,Backspace,Backspace"
print(f"{'OK ' if ok else 'KO '} Chrome : frappe par le clavier virtuel {len(recu)}/{len(attendu)}, écarts {ecarts}, "
      f"dernières touches {touches or '?'}")
saisie = open(os.path.join(dossier, "saisie.txt"), encoding="utf-8").read()
print(("OK " if "True" in saisie else "INFO") + " Chrome : champ signalé par la méthode de saisie : " + saisie.strip())
sys.exit(0 if ok else 1)
PY
resultat=$?
if [[ -n "${CAPTURES:-}" ]]; then
  python3 -I "$SMOKY_DEPOT/system_files/usr/libexec/smokyos/smoky-clavier-ecran.py" > "$ATELIER/clavier.log" 2>&1 &
  sleep 2
  gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled true
  chrome chrome-captures "file://$ICI/chrome-page.html#aller-retour"
  sleep 4.5; grim "$ATELIER/captures/chrome-1-champ.png"
  sleep 3.5; grim "$ATELIER/captures/chrome-2-bouton.png"
  sleep 4;   grim "$ATELIER/captures/chrome-3-champ.png"
  pkill -f "$ATELIER/chrome-captures"
  echo "captures : $ATELIER/captures/chrome-*.png"
fi
exit $resultat
