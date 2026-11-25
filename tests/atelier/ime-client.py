"""Sans GTK : un client méthode de saisie + clavier virtuel (wayland.ClientClavier) qui note quand un
champ prend la main, puis tape tous les caractères du clavier de session, ⏎, x, ⌫, ⌫."""
import os
import select
import sys
import time

sys.path.insert(0, os.environ["SMOKY_LIB"])
from smokybureau import commun, wayland  # noqa: E402

texte, codes = commun.keymap_clavier(commun.caracteres_session())
attendu = "".join(c for c in commun.caracteres_session() if c not in commun.TOUCHES_ENVOYEES or c == " ")
debut = time.time()
champs = []
client = wayland.ClientClavier(texte, quand_saisie=lambda actif: champs.append(actif))


def pomper(duree):
    fin = time.time() + duree
    while time.time() < fin:
        prets, _, _ = select.select([client.fileno()], [], [], 0.05)
        if prets and not client.lire():
            return


pomper(float(sys.argv[1]) if len(sys.argv) > 1 else 2)
for c in attendu:
    client.taper(*codes[c])
    pomper(0.015)
for c in ("⏎", "x", "⌫", "⌫"):                  # retour à la ligne puis effacé : texte inchangé
    client.taper(*codes[c])
    pomper(0.05)
pomper(1.5)
with open(os.path.join(os.environ["ATELIER"], "attendu.txt"), "w", encoding="utf-8") as f:
    f.write(attendu)
print("champ actif (méthode de saisie) :", champs, flush=True)
