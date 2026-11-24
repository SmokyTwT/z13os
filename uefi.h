/* Smoky OS 100 % maison — définitions UEFI écrites à la main d'après la spécification UEFI 2.10.
 * Seulement ce dont l'OS se sert. Volontairement ABSENTS : tout ce qui touche aux disques
 * (Block I/O, systèmes de fichiers) et l'écriture des variables du firmware : l'OS ne peut
 * donc ni lire ni écrire un disque, ni changer un réglage du PC.
 * Compilé pour la cible x86_64-unknown-windows : la convention d'appel est déjà celle d'UEFI. */
#pragma once

typedef unsigned long long u64;
typedef long long i64;
typedef unsigned int u32;
typedef int i32;
typedef unsigned short u16;
typedef short i16;
typedef unsigned char u8;
typedef u64 UINTN;
typedef u64 EFI_STATUS;
typedef void *EFI_HANDLE;
typedef void *EFI_EVENT;
typedef u16 CHAR16;

#define EFI_SUCCESS 0
#define EFI_ERREUR(s) ((s) & 0x8000000000000000ULL)

typedef struct { u32 d1; u16 d2, d3; u8 d4[8]; } EFI_GUID;
typedef struct { u64 signature; u32 revision, taille_entete, crc32, reserve; } EFI_TABLE_HEADER;

/* --- Clavier (entrée texte simple) --------------------------------------------------- */
typedef struct { u16 code_touche; CHAR16 caractere; } EFI_INPUT_KEY;
typedef struct EFI_SIMPLE_TEXT_INPUT {
  EFI_STATUS (*reset)(struct EFI_SIMPLE_TEXT_INPUT *, u8);
  EFI_STATUS (*lire_touche)(struct EFI_SIMPLE_TEXT_INPUT *, EFI_INPUT_KEY *);
  EFI_EVENT attente_touche;
} EFI_SIMPLE_TEXT_INPUT;

typedef struct EFI_SIMPLE_TEXT_OUTPUT {
  void *reset;
  EFI_STATUS (*ecrire)(struct EFI_SIMPLE_TEXT_OUTPUT *, CHAR16 *);
  void *tester, *mode_query, *mode_set, *attribut;
  EFI_STATUS (*effacer)(struct EFI_SIMPLE_TEXT_OUTPUT *);
  void *curseur_pos;
  EFI_STATUS (*curseur_visible)(struct EFI_SIMPLE_TEXT_OUTPUT *, u8);
  void *mode;
} EFI_SIMPLE_TEXT_OUTPUT;

/* --- Heure et redémarrage (services d'exécution) ------------------------------------------ */
typedef struct {
  u16 annee; u8 mois, jour, heure, minute, seconde, pad1;
  u32 nanoseconde; i16 fuseau; u8 heure_ete, pad2;
} EFI_TIME;

enum { EFI_RESET_FROID = 0, EFI_RESET_CHAUD = 1, EFI_RESET_ARRET = 2 };

typedef struct {
  EFI_TABLE_HEADER entete;
  EFI_STATUS (*lire_heure)(EFI_TIME *, void *);
  void *ecrire_heure, *lire_reveil, *ecrire_reveil, *carte_virtuelle, *convertir_pointeur;
  void *lire_variable, *variable_suivante;
  void *ecrire_variable;              /* jamais appelée */
  void *compteur_haut;
  void (*redemarrer)(u32 type, EFI_STATUS statut, UINTN taille, void *donnees);
} EFI_RUNTIME_SERVICES;

/* --- Mémoire --------------------------------------------------------------------------- */
typedef struct {
  u32 type; u32 pad; u64 debut_physique, debut_virtuel, nb_pages, attributs;
} EFI_MEMORY_DESCRIPTOR;
enum { EFI_MEMOIRE_CODE_CHARGEUR = 1, EFI_MEMOIRE_DONNEES_CHARGEUR = 2, EFI_MEMOIRE_CODE_DEMARRAGE = 3,
       EFI_MEMOIRE_DONNEES_DEMARRAGE = 4, EFI_MEMOIRE_LIBRE = 7 };

/* --- Services de démarrage (dans l'ordre exact de la spécification) ----------------------------- */
#define EVT_TIMER 0x80000000u
enum { MINUTERIE_ANNULER = 0, MINUTERIE_PERIODIQUE = 1, MINUTERIE_RELATIVE = 2 };

typedef struct {
  EFI_TABLE_HEADER entete;
  void *elever_tpl, *restaurer_tpl;
  void *allouer_pages, *liberer_pages;
  EFI_STATUS (*carte_memoire)(UINTN *taille, EFI_MEMORY_DESCRIPTOR *carte, UINTN *cle, UINTN *taille_desc, u32 *version);
  EFI_STATUS (*allouer)(u32 type, UINTN taille, void **tampon);
  EFI_STATUS (*liberer)(void *tampon);
  EFI_STATUS (*creer_evenement)(u32 type, UINTN tpl, void *fonction, void *contexte, EFI_EVENT *evenement);
  EFI_STATUS (*minuterie)(EFI_EVENT evenement, u32 type, u64 delai_100ns);
  EFI_STATUS (*attendre)(UINTN nombre, EFI_EVENT *evenements, UINTN *indice);
  void *signaler, *fermer_evenement, *verifier_evenement;
  void *installer_protocole, *reinstaller_protocole, *desinstaller_protocole, *gerer_protocole, *reserve;
  void *notification_protocole, *trouver_poignee, *trouver_chemin, *installer_table;
  void *charger_image, *lancer_image, *sortir, *decharger_image;
  EFI_STATUS (*sortir_services)(EFI_HANDLE image, UINTN cle_carte);
  void *compteur_suivant;
  EFI_STATUS (*attendre_us)(UINTN microsecondes);
  EFI_STATUS (*chien_de_garde)(UINTN delai, u64 code, UINTN taille, CHAR16 *donnees);
  void *connecter, *deconnecter, *ouvrir_protocole, *fermer_protocole, *info_protocole;
  void *protocoles_par_poignee, *tampon_poignees;
  EFI_STATUS (*trouver_protocole)(EFI_GUID *guid, void *enregistrement, void **interface);
} EFI_BOOT_SERVICES;

typedef struct {
  EFI_TABLE_HEADER entete;
  CHAR16 *fabricant; u32 revision_firmware;
  EFI_HANDLE poignee_entree; EFI_SIMPLE_TEXT_INPUT *entree;
  EFI_HANDLE poignee_sortie; EFI_SIMPLE_TEXT_OUTPUT *sortie;
  EFI_HANDLE poignee_erreur; EFI_SIMPLE_TEXT_OUTPUT *erreur;
  EFI_RUNTIME_SERVICES *execution;
  EFI_BOOT_SERVICES *demarrage;
  UINTN nb_tables; void *tables;
} EFI_SYSTEM_TABLE;

/* --- Affichage (Graphics Output Protocol) --------------------------------------------------- */
enum { PIXEL_RVB = 0, PIXEL_BVR = 1, PIXEL_MASQUE = 2, PIXEL_BLT_SEUL = 3 };
typedef struct {
  u32 version, largeur, hauteur, format;
  u32 masques[4];
  u32 pixels_par_ligne;
} EFI_GOP_MODE_INFO;
typedef struct {
  u32 nb_modes, mode;
  EFI_GOP_MODE_INFO *info;
  UINTN taille_info;
  u64 tampon_ecran;
  UINTN taille_tampon;
} EFI_GOP_MODE;
typedef struct EFI_GOP {
  EFI_STATUS (*lire_mode)(struct EFI_GOP *, u32 mode, UINTN *taille, EFI_GOP_MODE_INFO **info);
  EFI_STATUS (*choisir_mode)(struct EFI_GOP *, u32 mode);
  void *blt;
  EFI_GOP_MODE *mode;
} EFI_GOP;

static EFI_GUID GUID_GOP = {0x9042a9de, 0x23dc, 0x4a38, {0x96, 0xfb, 0x7a, 0xde, 0xd0, 0x80, 0x51, 0x6a}};
