/* Essai sur la machine de construction (pas dans l'OS) : fat.c face à de vraies images de clé,
 * préparées par essais/fat.sh avec les outils de Linux (mformat, mkfs.vfat), qui les vérifient
 * ensuite (fsck.vfat, mtype).
 *   essai-fat IMAGE FICHIER_EFI NOM_LONG ATTENDU
 * IMAGE contient EFI/BOOT/BOOTX64.EFI (copie de FICHIER_EFI) et, si NOM_LONG n'est pas vide, un
 * fichier à nom long à la racine. ATTENDU reçoit le contenu final de SMOKY/NOTES.TXT. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <string.h>
#include "../fat.h"

static FILE *img;
static int echecs;
#define VERIFIE(c) do { if (!(c)) { printf("ÉCHEC %s:%d : %s\n", __FILE__, __LINE__, #c); echecs++; } } while (0)

static int lire_img(void *ctx, u64 lba, void *s) {
  (void)ctx;
  return fseeko(img, (off_t)(lba * 512), SEEK_SET) == 0 && fread(s, 512, 1, img) == 1;
}
static int ecrire_img(void *ctx, u64 lba, const void *s) {
  (void)ctx;
  return fseeko(img, (off_t)(lba * 512), SEEK_SET) == 0 && fwrite(s, 512, 1, img) == 1;
}

static u8 contenu[300000], relu[300000];

static void texte(u8 *t, u32 n, int graine) {           /* contenu reconnaissable, différent à chaque graine */
  static const char LETTRES[] = "abcdefghijklmnopqrstuvwxyz ,.;\n";
  for (u32 i = 0; i < n; i++) t[i] = (u8)LETTRES[(i * 7 + (u32)graine * 13) % (sizeof LETTRES - 1)];
}

/* écrit puis relit (par le chemin) un fichier du dossier SMOKY */
static void ecrire_relire(struct volume_fat *v, u32 dossier, const char *nom, u32 n, int graine, struct date_fat q) {
  char chemin[64];
  struct entree_fat e;
  texte(contenu, n, graine);
  VERIFIE(fat_ecrire(v, dossier, nom, contenu, n, q));
  snprintf(chemin, sizeof chemin, "SMOKY/%s", nom);
  VERIFIE(fat_chemin(v, chemin, &e));
  VERIFIE(e.taille == n);
  memset(relu, 0xAA, n + 16);
  VERIFIE(fat_lire(v, &e, relu, sizeof relu) == (long)n);
  VERIFIE(memcmp(contenu, relu, n) == 0);
}

struct liste { int n; char noms[80][96]; };
static int retenir(void *ctx, const struct entree_fat *e) {
  struct liste *l = ctx;
  if (l->n < 80) snprintf(l->noms[l->n++], 96, "%s", e->nom);
  return 0;
}
static int contient(const struct liste *l, const char *nom) {
  for (int i = 0; i < l->n; i++) if (!strcmp(l->noms[i], nom)) return 1;
  return 0;
}

int main(int argc, char **argv) {
  if (argc < 5) { printf("usage : essai-fat IMAGE FICHIER_EFI NOM_LONG ATTENDU\n"); return 2; }
  img = fopen(argv[1], "r+b");
  if (!img) { printf("image introuvable : %s\n", argv[1]); return 2; }
  fseeko(img, 0, SEEK_END);
  struct disque_fat d = {lire_img, ecrire_img, 0, (u64)ftello(img) / 512};
  struct volume_fat v;
  struct entree_fat e;
  VERIFIE(fat_monter(&d, &v));
  if (echecs) return 1;

  /* le programme de démarrage, lu en entier (minuscules dans le chemin : noms confondus) */
  FILE *f = fopen(argv[2], "rb");
  size_t n_efi = f ? fread(contenu, 1, sizeof contenu, f) : 0;
  if (f) fclose(f);
  VERIFIE(n_efi > 0);
  VERIFIE(fat_chemin(&v, "efi/boot/bootx64.efi", &e));
  VERIFIE(e.taille == n_efi && !(e.attributs & 0x10));
  VERIFIE(fat_lire(&v, &e, relu, sizeof relu) == (long)n_efi && memcmp(contenu, relu, n_efi) == 0);
  VERIFIE(!fat_chemin(&v, "EFI/BOOT/ABSENT.EFI", &e));
  VERIFIE(!fat_chemin(&v, "EFI/BOOT/BOOTX64.EFI/X", &e));      /* un fichier ne contient rien */

  /* SMOKY/NOTES.TXT : créé, puis remplacé par plus long (plusieurs clusters), vide, puis moyen */
  struct date_fat q = {(u16)((2026 - 1980) << 9 | 11 << 5 | 26), (u16)(1 << 11 | 10 << 5 | 30 / 2)};
  u32 dossier = 0, encore = 0;
  VERIFIE(fat_dossier(&v, fat_racine(&v), "SMOKY", q, &dossier));
  VERIFIE(fat_dossier(&v, fat_racine(&v), "smoky", q, &encore) && encore == dossier);   /* déjà là */
  ecrire_relire(&v, dossier, "NOTES.TXT", 100, 1, q);
  ecrire_relire(&v, dossier, "NOTES.TXT", 20000, 2, q);
  ecrire_relire(&v, dossier, "notes.txt", 0, 3, q);              /* même fichier, autre casse */
  ecrire_relire(&v, dossier, "NOTES.TXT", 3000, 4, q);
  /* 40 fichiers de plus : le dossier grandit (16 entrées par secteur) */
  char nom[16];
  for (int i = 1; i <= 40; i++) { snprintf(nom, sizeof nom, "TEST%02d.TXT", i); ecrire_relire(&v, dossier, nom, (u32)(10 + i * 37), 10 + i, q); }
  /* refusés : nom qui n'est pas « 8.3 », fichier qui porterait le nom d'un dossier */
  VERIFIE(!fat_ecrire(&v, dossier, "nom trop long.txt", contenu, 10, q));
  VERIFIE(!fat_ecrire(&v, dossier, "A.B.C", contenu, 10, q));
  VERIFIE(!fat_ecrire(&v, fat_racine(&v), "SMOKY", contenu, 10, q));
  VERIFIE(!fat_dossier(&v, dossier, "NOTES.TXT", q, &encore));   /* un fichier porte ce nom */

  /* tout relu après un nouveau montage, comme au démarrage suivant */
  struct volume_fat v2;
  VERIFIE(fat_monter(&d, &v2));
  VERIFIE(fat_chemin(&v2, "SMOKY/NOTES.TXT", &e) && e.taille == 3000);
  texte(contenu, 3000, 4);
  VERIFIE(fat_lire(&v2, &e, relu, sizeof relu) == 3000 && memcmp(contenu, relu, 3000) == 0);
  VERIFIE(e.date == q.date && e.heure == q.heure);
  VERIFIE(fat_chemin(&v2, "smoky/test40.txt", &e) && e.taille == 10 + 40 * 37);
  struct liste l = {0};
  VERIFIE(fat_lister(&v2, dossier, retenir, &l) == 0);
  VERIFIE(l.n == 41 && contient(&l, "NOTES.TXT") && contient(&l, "TEST01.TXT") && contient(&l, "TEST40.TXT"));
  struct liste racine = {0};
  VERIFIE(fat_lister(&v2, fat_racine(&v2), retenir, &racine) == 0);
  VERIFIE(contient(&racine, "EFI") && contient(&racine, "SMOKY"));
  if (argv[3][0]) VERIFIE(contient(&racine, argv[3]));          /* nom long relu tel quel (UTF-8) */

  f = fopen(argv[4], "wb");
  texte(contenu, 3000, 4);
  if (f) { fwrite(contenu, 1, 3000, f); fclose(f); }
  fclose(img);
  printf("fat : %s, étiquette « %s », %u secteur(s) par cluster, %u clusters : %s\n", argv[1], v.etiquette,
         v.sec_cluster, v.clusters, echecs ? "ÉCHEC" : "tout est bon");
  return echecs != 0;
}
