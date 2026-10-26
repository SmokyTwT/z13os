# Smoky OS — Claude intégré au terminal.
#   claude          : ouvre Claude Code (assistant qui agit dans le terminal)
#   ia QUESTION     : réponse rapide de Claude, sans quitter le terminal
#   ia              : sans question, ouvre Claude Code
#   commande | ia "explique"  : envoie la sortie d'une commande à Claude
case $- in *i*) ;; *) return 0 2>/dev/null ;; esac
[ -n "${BASH_VERSION:-}${ZSH_VERSION:-}" ] || return 0 2>/dev/null

case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac

ia() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "Claude Code n'est pas encore installé (il s'installe tout seul à la connexion, avec Internet)."
    echo "Pour l'installer maintenant : curl -fsSL https://claude.ai/install.sh | bash"
    return 1
  fi
  if [ ! -t 0 ]; then
    # données envoyées par un tube : « journalctl -b | ia "pourquoi ça plante ?" »
    claude -p "${*:-Explique ceci.}"
  elif [ $# -eq 0 ]; then
    claude
  else
    claude -p "$*"
  fi
}

# Commande inconnue : proposer de demander à Claude
command_not_found_handle() {
  printf 'Commande introuvable : %s\n' "$1" >&2
  printf '\033[2mAstuce : ia "comment faire %s sur Smoky OS ?"\033[0m\n' "$*" >&2
  return 127
}

# Accueil discret, une fois par fenêtre de terminal (pas dans Claude Code lui-même)
if [ -z "${SMOKY_GREETED:-}" ] && [ -z "${CLAUDECODE:-}" ]; then
  export SMOKY_GREETED=1
  printf '\033[1;97m  smoky\033[0m \033[2m· tape \033[0;97mclaude\033[0;2m pour me parler, ou \033[0;97mia ta question\033[0;2m pour une réponse rapide\033[0m\n'
fi
