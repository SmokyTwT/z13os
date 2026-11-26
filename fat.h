/* Smoky OS 100 % maison — fichiers FAT32 d'une clé USB : lecture et écriture.
 *
 * Trouve le volume (table de partitions GPT, table MBR, ou clé formatée sans table), lit les dossiers
 * (noms longs compris), lit un fichier, crée un dossier et écrit un fichier (noms courts « 8.3 »).
 * D'après la spécification de Microsoft « FAT32 File System Specification » (version 1.03).
 * Prudence : un fichier réécrit reçoit d'abord ses nouveaux clusters, puis son entrée de dossier,
 * et seulement ensuite ses anciens clusters sont rendus. Une coupure au mauvais moment laisse au pire
 * des clusters perdus (vus par une vérification du disque), jamais un fichier mélangé.
 * Aucune dépendance au matériel : essayé seul sur une image de clé (essais/fat.c). */
#pragma once
typedef unsigned char u8;                    /* mêmes types qu'uefi.h (C11 permet de les répéter) */
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;

struct disque_fat {                          /* secteurs de 512 octets ; chaque fonction rend 1 si réussi */
  int (*lire)(void *ctx, u64 lba, void *secteur);
  int (*ecrire)(void *ctx, u64 lba, const void *secteur);
  void *ctx;
  u64 secteurs;                              /* taille du disque (0 : inconnue) */
};

struct volume_fat {
  struct disque_fat *d;
  u64 debut, lba_fat, lba_donnees;           /* en secteurs depuis le début du disque */
  u32 sec_cluster, nb_fat, sec_fat, racine, clusters, fsinfo, fat_active;
  int miroir;                                /* 1 : toutes les copies de la FAT sont tenues à jour */
  char etiquette[12];
  u32 prochain_libre;                        /* où chercher le prochain cluster libre */
  u32 libres;                                /* clusters libres (FSInfo) ; 0xFFFFFFFF : inconnu */
  u64 cache_lba; int cache_sale; u8 cache[512];   /* un secteur de FAT */
};

struct entree_fat {
  char nom[96];                              /* nom long (UTF-8) s'il existe, sinon le nom court */
  char court[13];                            /* « NOTES.TXT » */
  u8 attributs;                              /* 0x10 : dossier, 0x02 : caché, 0x04 : système */
  u32 cluster, taille;
  u16 date, heure;                           /* dernière écriture, format FAT */
  u64 lba; u32 pos;                          /* où est l'entrée courte (secteur, octet) */
};

struct date_fat { u16 date, heure; };        /* date : (année − 1980) << 9 | mois << 5 | jour ;
                                                heure : h << 11 | min << 5 | s / 2 */

int fat_monter(struct disque_fat *d, struct volume_fat *v);           /* 1 : volume FAT32 trouvé */
u32 fat_racine(const struct volume_fat *v);
/* « SMOKY/NOTES.TXT » depuis la racine (majuscules et minuscules confondues) ; 1 si trouvé */
int fat_chemin(struct volume_fat *v, const char *chemin, struct entree_fat *e);
/* chaque entrée du dossier (sans « . », « .. » ni l'étiquette) ; s'arrête si rappel rend 1.
 * Rend 1 si arrêté, 0 à la fin du dossier, −1 si le disque ou le volume est illisible */
int fat_lister(struct volume_fat *v, u32 dossier, int (*rappel)(void *ctx, const struct entree_fat *e), void *ctx);
/* contenu du fichier (max octets au plus) ; nombre d'octets lus, −1 si erreur */
long fat_lire(struct volume_fat *v, const struct entree_fat *e, u8 *dest, u32 max);
/* dossier « nom » (8.3) dans parent, créé s'il n'existe pas ; 1 si réussi, son cluster dans *cluster */
int fat_dossier(struct volume_fat *v, u32 parent, const char *nom, struct date_fat quand, u32 *cluster);
/* fichier « nom » (8.3) du dossier, créé ou remplacé par n octets ; 1 si réussi */
int fat_ecrire(struct volume_fat *v, u32 dossier, const char *nom, const u8 *src, u32 n, struct date_fat quand);
