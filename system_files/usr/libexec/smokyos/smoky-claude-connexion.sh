#!/usr/bin/env bash
# Smoky : connecte ton compte Claude (le même que l'appli Claude) pour « Avec Claude » dans l'agenda.
# Installe Claude Code avec l'installateur officiel d'Anthropic si besoin (dans ~/.local, il se met à
# jour tout seul), puis ouvre la connexion dans le navigateur. Aucune clé d'API.
# (Lancé par Smoky → Agenda → Réglages → « Connecter mon compte Claude ».)
set -u
export PATH="$HOME/.local/bin:$PATH"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
echo "== Smoky : connexion de ton compte Claude =="
echo
if ! command -v claude >/dev/null; then
  echo "Installation de Claude Code (outil officiel d'Anthropic)…"
  if ! curl -fsSL https://claude.ai/install.sh | bash; then
    echo; read -rp "L'installation a échoué (connexion internet ?). Appuie sur Entrée pour fermer."; exit 1
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi
if claude auth status >/dev/null 2>&1; then
  echo "Ton compte Claude est déjà connecté."
else
  echo "Une page de connexion va s'ouvrir : connecte-toi avec ton compte Claude (Pro ou Max)."
  echo
  claude auth login
fi
echo
claude auth status --text
echo
read -rp "Terminé : retourne dans Smoky (Agenda, bouton « Avec Claude »). Entrée pour fermer."
