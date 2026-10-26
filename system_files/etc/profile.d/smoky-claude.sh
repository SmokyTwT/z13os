# Smoky OS — le terminal, c'est Claude.
# Ouvrir un terminal lance directement Claude Code. Quand tu le quittes
# (/exit ou Ctrl+D), tu retrouves un terminal classique dans la même fenêtre.
#   claude              : revenir à Claude
#   ia QUESTION         : réponse rapide, sans quitter le terminal classique
#   commande | ia "..." : envoyer la sortie d'une commande à Claude
#   terminal-classique  : ne plus lancer Claude à l'ouverture du terminal
#   terminal-claude     : relancer Claude à chaque ouverture (par défaut)
case $- in *i*) ;; *) return 0 2>/dev/null ;; esac
[ -n "${BASH_VERSION:-}${ZSH_VERSION:-}" ] || return 0 2>/dev/null

case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac

SMOKY_CLASSIC_FLAG="$HOME/.config/smoky/terminal-classique"

ia() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "Claude Code n'est pas encore installé (il s'installe tout seul à la connexion, avec Internet)."
    echo "Pour l'installer maintenant : curl -fsSL https://claude.ai/install.sh | bash"
    return 1
  fi
  if [ ! -t 0 ]; then
    claude -p "${*:-Explique ceci.}"
  elif [ $# -eq 0 ]; then
    claude
  else
    claude -p "$*"
  fi
}

terminal-classique() {
  mkdir -p "${SMOKY_CLASSIC_FLAG%/*}" && touch "$SMOKY_CLASSIC_FLAG"
  echo "C'est noté : le terminal s'ouvrira en mode classique. « terminal-claude » pour revenir à Claude."
}

terminal-claude() {
  rm -f "$SMOKY_CLASSIC_FLAG"
  echo "C'est noté : Claude s'ouvrira à chaque nouveau terminal."
}

command_not_found_handle() {
  printf 'Commande introuvable : %s\n' "$1" >&2
  printf '\033[2mAstuce : tape « claude » et demande-lui, ou : ia "comment faire %s ?"\033[0m\n' "$*" >&2
  return 127
}

# Démarrage automatique de Claude : une seule fois par fenêtre ou onglet de
# terminal graphique, jamais dans Claude lui-même, en SSH ou dans un sous-shell.
if [ -z "${SMOKY_CLAUDE_AUTO:-}" ] && [ -z "${CLAUDECODE:-}" ] && [ -z "${SSH_CONNECTION:-}" ] \
   && [ -n "${VTE_VERSION:-}" ] && [ -t 0 ] && [ -t 1 ]; then
  export SMOKY_CLAUDE_AUTO=1
  if [ ! -e "$SMOKY_CLASSIC_FLAG" ] && command -v claude >/dev/null 2>&1; then
    claude
    printf '\n\033[1;97m  smoky\033[0m \033[2m· terminal classique — tape \033[0;97mclaude\033[0;2m pour revenir à Claude\033[0m\n'
  elif [ ! -e "$SMOKY_CLASSIC_FLAG" ]; then
    printf '\033[1;97m  smoky\033[0m \033[2m· Claude s’installe en arrière-plan (connexion Internet nécessaire), il s’ouvrira ici au prochain terminal\033[0m\n'
  else
    printf '\033[1;97m  smoky\033[0m \033[2m· tape \033[0;97mclaude\033[0;2m pour me parler, ou \033[0;97mia ta question\033[0m\n'
  fi
fi
