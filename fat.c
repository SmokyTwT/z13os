/* Smoky OS 100 % maison — fichiers FAT32 d'une clé USB (voir fat.h). */
#include "fat.h"

#define FIN_CHAINE 0x0FFFFFF8u                 /* à partir d'ici : dernier cluster d'une chaîne */
#define MAUVAIS 0x0FFFFFF7u                    /* cluster marqué abîmé */

static void copier(void *d, const void *s, u32 n) { u8 *a = d; const u8 *b = s; while (n--) *a++ = *b++; }
static void remplir(void *d, u8 c, u32 n) { u8 *a = d; while (n--) *a++ = c; }
static u16 l16(const u8 *p) { return (u16)(p[0] | p[1] << 8); }
static u32 l32(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static u64 l64(const u8 *p) { return (u64)l32(p) | (u64)l32(p + 4) << 32; }
static void e16(u8 *p, u32 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }
static void e32(u8 *p, u32 v) { e16(p, v); e16(p + 2, v >> 16); }
static char majuscule(char c) { return c >= 'a' && c <= 'z' ? (char)(c - 32) : c; }
static char minuscule(char c) { return c >= 'A' && c <= 'Z' ? (char)(c + 32) : c; }

static u8 S[512];                              /* secteur de travail : démarrage, dossiers, FSInfo */
static u8 D[512];                              /* secteur de travail : données */

static int lire(struct volume_fat *v, u64 lba, void *s) { return v->d->lire(v->d->ctx, lba, s); }
static int ecrire(struct volume_fat *v, u64 lba, const void *s) { return v->d->ecrire(v->d->ctx, lba, s); }
static int valide(const struct volume_fat *v, u32 c) { return c >= 2 && c < v->clusters + 2; }
static u64 lba_cluster(const struct volume_fat *v, u32 c) { return v->lba_donnees + (u64)(c - 2) * v->sec_cluster; }
u32 fat_racine(const struct volume_fat *v) { return v->racine; }

/* --- Le volume ---------------------------------------------------------------------------------- */
/* secteur de démarrage d'un volume FAT32 ? (structure FAT32 : pas de racine de taille fixe, FAT de
 * 32 bits). Le type se lit à la structure, comme le fait Linux ; le nombre de clusters est vérifié. */
static int est_fat32(const u8 *b, u64 debut, u64 limite, struct volume_fat *v) {
  if (b[510] != 0x55 || b[511] != 0xAA || (b[0] != 0xEB && b[0] != 0xE9)) return 0;
  u32 octets = l16(b + 11), spc = b[13], reserves = l16(b + 14), nb_fat = b[16];
  u32 total = l16(b + 19) ? l16(b + 19) : l32(b + 32), sec_fat = l32(b + 36);
  if (octets != 512 || !spc || (spc & (spc - 1)) || !reserves || !nb_fat || nb_fat > 4) return 0;
  if (l16(b + 17) || l16(b + 22) || !sec_fat || !total) return 0;   /* racine fixe ou FAT de 16 bits : pas FAT32 */
  u64 meta = (u64)reserves + (u64)nb_fat * sec_fat;
  if (meta >= total || (limite && debut + total > limite)) return 0;
  u64 clusters = (total - meta) / spc;
  if (!clusters || clusters > 0x0FFFFFF0u - 2 || (clusters + 2) * 4 > (u64)sec_fat * 512) return 0;
  u32 racine = l32(b + 44), ext = l16(b + 40);
  if (racine < 2 || racine >= clusters + 2) return 0;
  v->debut = debut; v->sec_cluster = spc; v->nb_fat = nb_fat; v->sec_fat = sec_fat;
  v->lba_fat = debut + reserves; v->lba_donnees = debut + meta; v->clusters = (u32)clusters; v->racine = racine;
  v->fsinfo = l16(b + 48);
  v->miroir = !(ext & 0x80);                   /* bit 7 : une seule FAT active, les autres ne suivent pas */
  v->fat_active = v->miroir ? 0 : (ext & 15);
  if (v->fat_active >= nb_fat) return 0;
  int n = 0;
  for (int i = 0; i < 11; i++) v->etiquette[i] = (char)(b[71 + i] >= 0x20 && b[71 + i] < 0x7F ? b[71 + i] : '?');
  for (n = 11; n && v->etiquette[n - 1] == ' '; n--) ;
  v->etiquette[n] = 0;
  v->prochain_libre = 2; v->libres = 0xFFFFFFFFu; v->cache_lba = ~0ull; v->cache_sale = 0;
  return 1;
}

int fat_monter(struct disque_fat *d, struct volume_fat *v) {
  v->d = d;
  if (!d->lire(d->ctx, 0, S)) return 0;
  int trouve = est_fat32(S, 0, d->secteurs, v);           /* clé formatée sans table de partitions */
  if (!trouve && S[510] == 0x55 && S[511] == 0xAA) {
    u8 types[4]; u64 debuts[4]; int gpt = 0;
    for (int i = 0; i < 4; i++) {
      const u8 *p = S + 446 + 16 * i;
      types[i] = p[4]; debuts[i] = l32(p + 8);
      if (p[4] == 0xEE) gpt = 1;                          /* table GPT (le MBR la protège) */
    }
    if (gpt) {
      if (!d->lire(d->ctx, 1, S) || l32(S) != 0x20494645 || l32(S + 4) != 0x54524150) return 0;   /* « EFI PART » */
      u64 table = l64(S + 72); u32 nb = l32(S + 80), taille = l32(S + 84);
      if (taille < 128 || taille > 512 || (taille & (taille - 1)) || nb > 1024) return 0;
      u32 par_secteur = 512 / taille;
      for (u32 k = 0; k < nb && !trouve; k++) {
        if (k % par_secteur == 0 && !d->lire(d->ctx, table + k / par_secteur, D)) return 0;
        const u8 *p = D + (k % par_secteur) * taille;
        int vide = 1;
        for (int j = 0; j < 16; j++) if (p[j]) vide = 0;
        u64 premier = l64(p + 32);
        if (!vide && premier && d->lire(d->ctx, premier, S)) trouve = est_fat32(S, premier, d->secteurs, v);
      }
    } else {
      for (int i = 0; i < 4 && !trouve; i++) {
        u8 t = types[i];                                  /* FAT32 (0x0B, 0x0C), FAT16, ou partition EFI */
        if (debuts[i] && (t == 0x0B || t == 0x0C || t == 0x0E || t == 0x06 || t == 0x04 || t == 0x01 || t == 0xEF)
            && d->lire(d->ctx, debuts[i], S))
          trouve = est_fat32(S, debuts[i], d->secteurs, v);
      }
    }
  }
  if (!trouve) return 0;
  if (v->fsinfo && v->fsinfo != 0xFFFF && lire(v, v->debut + v->fsinfo, S) && l32(S) == 0x41615252 &&
      l32(S + 484) == 0x61417272) {                       /* ce qu'a noté le dernier système */
    if (valide(v, l32(S + 492))) v->prochain_libre = l32(S + 492);
    if (l32(S + 488) <= v->clusters) v->libres = l32(S + 488);
  }
  for (u32 s = 0; s < v->sec_cluster && lire(v, lba_cluster(v, v->racine) + s, S); s++) {   /* vraie étiquette */
    for (u32 i = 0; i < 512; i += 32) {
      if (!S[i]) return 1;
      if (S[i] != 0xE5 && (S[i + 11] & 0x3F) == 0x08) {
        int n;
        for (int k = 0; k < 11; k++) v->etiquette[k] = (char)(S[i + k] >= 0x20 && S[i + k] < 0x7F ? S[i + k] : '?');
        for (n = 11; n && v->etiquette[n - 1] == ' '; n--) ;
        v->etiquette[n] = 0;
        return 1;
      }
    }
  }
  return 1;
}

/* --- La FAT, un secteur en mémoire -------------------------------------------------------------- */
static int fat_vider(struct volume_fat *v) {   /* le secteur modifié, écrit dans chaque copie tenue à jour */
  if (!v->cache_sale) return 1;
  u64 rel = v->cache_lba - (v->lba_fat + (u64)v->fat_active * v->sec_fat);
  for (u32 k = 0; k < v->nb_fat; k++)
    if ((v->miroir || k == v->fat_active) && !ecrire(v, v->lba_fat + (u64)k * v->sec_fat + rel, v->cache)) return 0;
  v->cache_sale = 0;
  return 1;
}

static int fat_secteur(struct volume_fat *v, u32 n) {   /* le secteur qui contient l'entrée n */
  u64 lba = v->lba_fat + (u64)v->fat_active * v->sec_fat + n / 128;
  if (lba == v->cache_lba) return 1;
  if (!fat_vider(v)) return 0;
  if (!lire(v, lba, v->cache)) { v->cache_lba = ~0ull; return 0; }
  v->cache_lba = lba;
  return 1;
}

static int fat_valeur(struct volume_fat *v, u32 n, u32 *val) {
  if (n >= v->clusters + 2 || !fat_secteur(v, n)) return 0;
  *val = l32(v->cache + (n % 128) * 4) & 0x0FFFFFFFu;
  return 1;
}

static int fat_poser(struct volume_fat *v, u32 n, u32 val) {  /* les 4 bits du haut sont gardés */
  if (!valide(v, n) || !fat_secteur(v, n)) return 0;
  u8 *p = v->cache + (n % 128) * 4;
  e32(p, (l32(p) & 0xF0000000u) | (val & 0x0FFFFFFFu));
  v->cache_sale = 1;
  return 1;
}

/* cluster qui suit c : 1 (et *s), 0 si c était le dernier, −1 si la chaîne est abîmée */
static int suivant(struct volume_fat *v, u32 c, u32 *s) {
  u32 val;
  if (!fat_valeur(v, c, &val)) return -1;
  if (val >= FIN_CHAINE) return 0;
  if (!valide(v, val) || val == MAUVAIS) return -1;
  *s = val;
  return 1;
}

static u32 allouer(struct volume_fat *v) {     /* un cluster libre, marqué « dernier » ; 0 : plein */
  u32 c = v->prochain_libre;
  for (u32 k = 0; k < v->clusters; k++, c++) {
    if (!valide(v, c)) c = 2;
    u32 val;
    if (!fat_valeur(v, c, &val)) return 0;
    if (!val) {
      if (!fat_poser(v, c, 0x0FFFFFFFu)) return 0;
      v->prochain_libre = c + 1;
      if (v->libres != 0xFFFFFFFFu && v->libres) v->libres--;
      return c;
    }
  }
  return 0;
}

static void liberer(struct volume_fat *v, u32 c) {   /* rend toute la chaîne qui commence en c */
  for (u32 tours = 0; valide(v, c) && tours <= v->clusters; tours++) {
    u32 val;
    if (!fat_valeur(v, c, &val) || !fat_poser(v, c, 0)) return;
    if (c < v->prochain_libre) v->prochain_libre = c;
    if (v->libres != 0xFFFFFFFFu) v->libres++;
    if (val >= FIN_CHAINE) return;
    c = val;
  }
}

/* FSInfo : clusters libres (tenus à jour, ou « inconnu » s'ils l'étaient déjà), et où chercher de la place */
static void noter_fsinfo(struct volume_fat *v) {
  if (!v->fsinfo || v->fsinfo == 0xFFFF) return;
  u64 lba = v->debut + v->fsinfo;
  if (!lire(v, lba, S) || l32(S) != 0x41615252 || l32(S + 484) != 0x61417272 || l32(S + 508) != 0xAA550000u) return;
  e32(S + 488, v->libres <= v->clusters ? v->libres : 0xFFFFFFFFu);
  e32(S + 492, valide(v, v->prochain_libre) ? v->prochain_libre : 0xFFFFFFFFu);
  ecrire(v, lba, S);
}

/* --- Les noms ----------------------------------------------------------------------------------- */
static int permis(char c) {                    /* caractères d'un nom court (sans les codes > 127) */
  if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) return 1;
  for (const char *p = "!#$%&'()-@^_`{}~"; *p; p++) if (c == *p) return 1;
  return 0;
}

static int nom_court(const char *nom, u8 n83[11]) {   /* « notes.txt » → « NOTES   TXT » ; 0 : pas un nom 8.3 */
  int i = 0, j = 0, k = 0;
  remplir(n83, ' ', 11);
  for (; nom[i] && nom[i] != '.'; i++) { if (j >= 8 || !permis(nom[i])) return 0; n83[j++] = (u8)majuscule(nom[i]); }
  if (!j) return 0;
  if (nom[i] == '.') {
    for (i++; nom[i]; i++) { if (k >= 3 || !permis(nom[i])) return 0; n83[8 + k++] = (u8)majuscule(nom[i]); }
    if (!k) return 0;
  }
  return 1;
}

static char lettre_courte(const u8 *e, int i, int bas) {   /* octets > 127 : page de codes inconnue → « ? » */
  char c = e[i] >= 0x20 && e[i] < 0x7F ? (char)e[i] : '?';
  return bas ? minuscule(c) : c;
}

static void texte_court(const u8 *e, char *d) {   /* entrée → « NOTES.TXT » (minuscules si demandé, comme Windows) */
  int n = 0;
  for (int i = 0; i < 8 && e[i] != ' '; i++) d[n++] = lettre_courte(e, i, e[12] & 0x08);
  if (e[8] != ' ') {
    d[n++] = '.';
    for (int i = 8; i < 11 && e[i] != ' '; i++) d[n++] = lettre_courte(e, i, e[12] & 0x10);
  }
  d[n] = 0;
}

static u8 somme_court(const u8 *e) {           /* somme de contrôle qui relie un nom long à son nom court */
  u8 s = 0;
  for (int i = 0; i < 11; i++) s = (u8)(((s & 1) << 7) + (s >> 1) + e[i]);
  return s;
}

static void utf8(const u16 *t, int n, char *d, int max) {
  int k = 0;
  for (int i = 0; i < n && t[i] && t[i] != 0xFFFF; i++) {
    u32 c = t[i] >= 0xD800 && t[i] < 0xE000 ? '?' : t[i];
    int l = c < 0x80 ? 1 : c < 0x800 ? 2 : 3;
    if (k + l >= max) break;
    if (l == 1) d[k++] = (char)c;
    else if (l == 2) { d[k++] = (char)(0xC0 | c >> 6); d[k++] = (char)(0x80 | (c & 63)); }
    else { d[k++] = (char)(0xE0 | c >> 12); d[k++] = (char)(0x80 | (c >> 6 & 63)); d[k++] = (char)(0x80 | (c & 63)); }
  }
  d[k] = 0;
}

/* --- Les dossiers ------------------------------------------------------------------------------- */
int fat_lister(struct volume_fat *v, u32 dossier, int (*rappel)(void *ctx, const struct entree_fat *e), void *ctx) {
  static const u8 POS[13] = {1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30};   /* lettres d'un morceau de nom long */
  u16 lfn[260];
  int attendu = 0, pret = 0;                   /* morceau de nom long attendu ensuite ; nom long complet */
  u8 somme = 0;
  u32 c = dossier;
  for (u32 tours = 0; tours <= v->clusters; tours++) {
    if (!valide(v, c)) return -1;
    for (u32 s = 0; s < v->sec_cluster; s++) {
      u64 lba = lba_cluster(v, c) + s;
      if (!lire(v, lba, S)) return -1;
      for (u32 i = 0; i < 512; i += 32) {
        const u8 *e = S + i;
        if (!e[0]) return 0;                   /* fin du dossier */
        if (e[0] == 0xE5) { attendu = pret = 0; continue; }
        if ((e[11] & 0x3F) == 0x0F) {          /* morceau de nom long, du dernier au premier */
          int ord = e[0] & 0x3F;
          if (e[0] & 0x40) {
            attendu = ord >= 1 && ord <= 20 ? ord : 0; somme = e[13]; pret = 0;
            for (int k = 0; k < 260; k++) lfn[k] = 0;
          }
          if (!attendu || ord != attendu || e[13] != somme) { attendu = pret = 0; continue; }
          for (int k = 0; k < 13; k++) lfn[(ord - 1) * 13 + k] = l16(e + POS[k]);
          if (--attendu == 0) pret = 1;
          continue;
        }
        int long_ok = pret && somme_court(e) == somme;
        attendu = pret = 0;
        if ((e[11] & 0x08) || e[0] == '.') continue;      /* étiquette du volume, « . » et « .. » */
        struct entree_fat x;
        texte_court(e, x.court);
        if (long_ok) utf8(lfn, 260, x.nom, sizeof x.nom);
        else copier(x.nom, x.court, sizeof x.court);
        x.attributs = e[11];
        x.cluster = (u32)l16(e + 20) << 16 | l16(e + 26);
        x.taille = l32(e + 28);
        x.heure = l16(e + 22); x.date = l16(e + 24);
        x.lba = lba; x.pos = i;
        if (rappel(ctx, &x)) return 1;
      }
    }
    u32 s2;
    int r = suivant(v, c, &s2);
    if (r <= 0) return r;
    c = s2;
  }
  return -1;                                   /* la chaîne tourne en rond */
}

struct recherche { const char *nom; int n; struct entree_fat *e; };

static int meme_nom(const char *a, int n, const char *b) {   /* a sur n octets, b terminé par 0 */
  for (int i = 0; i < n; i++) if (!b[i] || majuscule(a[i]) != majuscule(b[i])) return 0;
  return !b[n];
}

static int rappel_recherche(void *ctx, const struct entree_fat *x) {
  struct recherche *r = ctx;
  if (!meme_nom(r->nom, r->n, x->nom) && !meme_nom(r->nom, r->n, x->court)) return 0;
  *r->e = *x;
  return 1;
}

static int chercher(struct volume_fat *v, u32 dossier, const char *nom, int n, struct entree_fat *e) {
  struct recherche r = {nom, n, e};
  return fat_lister(v, dossier, rappel_recherche, &r) == 1;
}

int fat_chemin(struct volume_fat *v, const char *chemin, struct entree_fat *e) {
  remplir(e, 0, sizeof *e);
  e->attributs = 0x10; e->cluster = v->racine;          /* la racine */
  const char *p = chemin;
  while (*p == '/') p++;
  while (*p) {
    int n = 0;
    while (p[n] && p[n] != '/') n++;
    if (!(e->attributs & 0x10)) return 0;               /* un fichier ne contient rien */
    if (!chercher(v, e->cluster ? e->cluster : v->racine, p, n, e)) return 0;
    p += n;
    while (*p == '/') p++;
  }
  return 1;
}

long fat_lire(struct volume_fat *v, const struct entree_fat *e, u8 *dest, u32 max) {
  if (e->attributs & 0x18) return -1;                   /* dossier ou étiquette */
  u32 reste = e->taille < max ? e->taille : max, lus = 0, c = e->cluster;
  while (reste) {
    if (!valide(v, c)) return -1;
    for (u32 s = 0; s < v->sec_cluster && reste; s++) {
      if (!lire(v, lba_cluster(v, c) + s, D)) return -1;
      u32 k = reste < 512 ? reste : 512;
      copier(dest + lus, D, k);
      lus += k; reste -= k;
    }
    if (reste && suivant(v, c, &c) != 1) return -1;     /* fichier plus court que sa taille annoncée */
  }
  return (long)lus;
}

/* une place dans le dossier (entrée effacée, ou la fin) ; un cluster vidé de plus s'il est plein */
static int place_libre(struct volume_fat *v, u32 dossier, u64 *lba, u32 *pos) {
  u32 c = dossier;
  for (u32 tours = 0; tours <= v->clusters; tours++) {
    if (!valide(v, c)) return 0;
    for (u32 s = 0; s < v->sec_cluster; s++) {
      u64 l = lba_cluster(v, c) + s;
      if (!lire(v, l, S)) return 0;
      for (u32 i = 0; i < 512; i += 32)
        if (!S[i] || S[i] == 0xE5) { *lba = l; *pos = i; return 1; }
    }
    u32 s2;
    int r = suivant(v, c, &s2);
    if (r < 0) return 0;
    if (!r) {
      u32 n = allouer(v);
      if (!n) return 0;
      remplir(S, 0, 512);
      for (u32 s = 0; s < v->sec_cluster; s++)
        if (!ecrire(v, lba_cluster(v, n) + s, S)) { liberer(v, n); return 0; }
      if (!fat_poser(v, c, n) || !fat_vider(v)) { liberer(v, n); return 0; }
      *lba = lba_cluster(v, n); *pos = 0;
      return 1;
    }
    c = s2;
  }
  return 0;
}

static void preparer_entree(u8 *e, const u8 *n83, u8 attributs, u32 cluster, u32 taille, struct date_fat q) {
  remplir(e, 0, 32);
  copier(e, n83, 11);
  e[11] = attributs;
  e16(e + 14, q.heure); e16(e + 16, q.date);          /* création */
  e16(e + 18, q.date);                                 /* dernier accès */
  e16(e + 20, cluster >> 16);
  e16(e + 22, q.heure); e16(e + 24, q.date);          /* dernière écriture */
  e16(e + 26, cluster);
  e32(e + 28, taille);
}

static int poser_entree(struct volume_fat *v, u64 lba, u32 pos, const u8 *e) {
  if (!lire(v, lba, S)) return 0;
  copier(S + pos, e, 32);
  return ecrire(v, lba, S);
}

static int longueur(const char *t) { int n = 0; while (t[n]) n++; return n; }

int fat_dossier(struct volume_fat *v, u32 parent, const char *nom, struct date_fat q, u32 *cluster) {
  u8 n83[11], e[32], point[11];
  struct entree_fat x;
  if (!nom_court(nom, n83)) return 0;
  if (chercher(v, parent, nom, longueur(nom), &x)) {
    if (!(x.attributs & 0x10) || !valide(v, x.cluster)) return 0;   /* un fichier porte ce nom */
    *cluster = x.cluster;
    return 1;
  }
  u32 c = allouer(v);
  if (!c) return 0;
  remplir(D, 0, 512);
  for (u32 s = 1; s < v->sec_cluster; s++) if (!ecrire(v, lba_cluster(v, c) + s, D)) goto rate;
  remplir(point, ' ', 11); point[0] = '.';
  preparer_entree(D, point, 0x10, c, 0, q);
  point[1] = '.';
  preparer_entree(D + 32, point, 0x10, parent == v->racine ? 0 : parent, 0, q);
  if (!ecrire(v, lba_cluster(v, c), D) || !fat_vider(v)) goto rate;   /* à lui avant d'être nommé */
  u64 lba; u32 pos;
  if (!place_libre(v, parent, &lba, &pos)) goto rate;
  preparer_entree(e, n83, 0x10, c, 0, q);
  if (!poser_entree(v, lba, pos, e)) goto rate;
  noter_fsinfo(v);
  *cluster = c;
  return 1;
rate:
  liberer(v, c);
  fat_vider(v);
  return 0;
}

int fat_ecrire(struct volume_fat *v, u32 dossier, const char *nom, const u8 *src, u32 n, struct date_fat q) {
  u8 n83[11], e[32];
  struct entree_fat ancien;
  if (!nom_court(nom, n83)) return 0;
  int existe = chercher(v, dossier, nom, longueur(nom), &ancien);
  if (existe && (ancien.attributs & 0x18)) return 0;     /* un dossier porte ce nom */
  /* 1. les nouveaux clusters, remplis (la FAT les marque à lui avant que l'entrée les désigne) */
  u32 premier = 0, dernier = 0, ecrit = 0;
  while (ecrit < n) {
    u32 c = allouer(v);
    if (!c) goto rate;
    if (dernier && !fat_poser(v, dernier, c)) { liberer(v, c); goto rate; }
    if (!premier) premier = c;
    dernier = c;
    for (u32 s = 0; s < v->sec_cluster; s++) {
      u32 k = n - ecrit < 512 ? n - ecrit : 512;
      if (k) copier(D, src + ecrit, k);
      if (k < 512) remplir(D + k, 0, 512 - k);
      if (!ecrire(v, lba_cluster(v, c) + s, D)) goto rate;
      ecrit += k;
    }
  }
  if (!fat_vider(v)) goto rate;
  /* 2. l'entrée du dossier : mise à jour sur place (le nom long éventuel reste valable), ou nouvelle */
  if (existe) {
    if (!lire(v, ancien.lba, S)) goto rate;
    u8 *p = S + ancien.pos;
    e16(p + 20, premier >> 16); e16(p + 26, premier); e32(p + 28, n);
    e16(p + 18, q.date); e16(p + 22, q.heure); e16(p + 24, q.date);
    p[11] |= 0x20;                                       /* à sauvegarder */
    if (!ecrire(v, ancien.lba, S)) goto rate;
  } else {
    u64 lba; u32 pos;
    if (!place_libre(v, dossier, &lba, &pos)) goto rate;
    preparer_entree(e, n83, 0x20, premier, n, q);
    if (!poser_entree(v, lba, pos, e)) goto rate;
  }
  /* 3. seulement maintenant, les anciens clusters sont rendus */
  if (existe && valide(v, ancien.cluster)) liberer(v, ancien.cluster);
  fat_vider(v);
  noter_fsinfo(v);
  return 1;
rate:
  if (premier) liberer(v, premier);
  fat_vider(v);
  return 0;
}
