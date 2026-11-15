"""Smoky — l'appli unique de Smoky OS : aujourd'hui, notes, agenda, mail, cours, maison, système.

Un petit serveur local (127.0.0.1 uniquement) et une page affichée dans une fenêtre. Rien n'est
accessible depuis le réseau ; chaque requête doit porter le code d'accès tiré au lancement.

  serveur.py     le serveur : sécurité, routes, fichiers de la page, événements vers la page
  base.py        la mémoire de l'appli (SQLite, dans ~/.local/share/smoky)
  commandes.py   lancer une commande système proprement (liste fermée, délais)
  taches.py      « à faire » (page Aujourd'hui)
  systeme.py     réglages de la machine (batterie, écran, carte graphique, mises à jour…)
"""
VERSION = "1"
PORT = 47820
