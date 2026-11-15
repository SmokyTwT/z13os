"""La mémoire de Smoky : un fichier SQLite dans ~/.local/share/smoky.

Une seule connexion, protégée par un verrou (le serveur traite plusieurs requêtes à la fois).
Le schéma évolue par étapes numérotées (MIGRATIONS) : on n'en modifie jamais une existante, on
en ajoute une à la fin.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path

MIGRATIONS = [
    # 1 — réglages de l'appli et tâches « à faire »
    """
    CREATE TABLE reglages (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
    CREATE TABLE taches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titre TEXT NOT NULL,
        faite INTEGER NOT NULL DEFAULT 0,
        echeance TEXT,                       -- AAAA-MM-JJ, ou NULL
        creee REAL NOT NULL,
        terminee REAL
    );
    CREATE INDEX taches_ouvertes ON taches (faite, echeance);
    """,
]


def dossier_donnees():
    base = os.environ.get("SMOKY_DONNEES") or os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "smoky")
    return Path(base)


class Base:
    def __init__(self, chemin=None):
        self.chemin = Path(chemin) if chemin else dossier_donnees() / "smoky.db"
        self.chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.verrou = threading.RLock()
        # le fichier naît lisible par toi seul (ses fichiers annexes -wal et -shm héritent de ses droits)
        os.close(os.open(self.chemin, os.O_RDWR | os.O_CREAT, 0o600))
        os.chmod(self.chemin, 0o600)
        self.db = sqlite3.connect(self.chemin, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # avant de toucher à quoi que ce soit : une mémoire écrite par une version plus récente reste intacte
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            self.db.close()
            raise RuntimeError("cette mémoire vient d'une version plus récente de Smoky")
        for pragma in ("journal_mode=WAL", "synchronous=NORMAL", "foreign_keys=ON", "busy_timeout=5000"):
            self.db.execute(f"PRAGMA {pragma}")
        self._migrer(version)

    def _migrer(self, version):
        with self.verrou:
            for numero in range(version, len(MIGRATIONS)):
                # chaque étape passe en entier ou pas du tout
                self.db.executescript(f"BEGIN;\n{MIGRATIONS[numero]}\nPRAGMA user_version={numero + 1};\nCOMMIT;")

    def lire(self, sql, params=()):
        with self.verrou:
            return [dict(ligne) for ligne in self.db.execute(sql, params).fetchall()]

    def un(self, sql, params=()):
        lignes = self.lire(sql, params)
        return lignes[0] if lignes else None

    def ecrire(self, sql, params=()):
        """→ (identifiant de la ligne créée, nombre de lignes touchées)."""
        with self.verrou:
            c = self.db.execute(sql, params)
            return c.lastrowid, c.rowcount

    def reglage(self, cle, defaut=None):
        ligne = self.un("SELECT valeur FROM reglages WHERE cle = ?", (cle,))
        if ligne is None:
            return defaut
        try:
            return json.loads(ligne["valeur"])
        except ValueError:
            return defaut

    def regler(self, cle, valeur):
        self.ecrire("INSERT INTO reglages (cle, valeur) VALUES (?, ?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                    (cle, json.dumps(valeur, ensure_ascii=False)))

    def fermer(self):
        with self.verrou:
            self.db.close()
