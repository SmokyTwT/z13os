/* Smoky OS 100 % maison, version 0.2 — un système d'exploitation écrit de zéro, pour toi.
 *
 * Aucun Linux, aucune bibliothèque : ce fichier, uefi.h (écrit d'après la spécification) et le
 * compilateur. Il démarre directement par le firmware UEFI du PC, dessine lui-même tout ce
 * que tu vois (y compris sa police, faite de traits sur une grille), lit le clavier et tient un
 * petit carnet de commandes. Le firmware ne sert qu'à démarrer : ensuite Smoky OS le congédie et gère
 * seul les interruptions, la minuterie, le clavier et l'horloge (noyau.c).
 *
 * Sécurité de ton PC : il n'a AUCUN pilote de disque et n'appelle jamais les fonctions
 * d'écriture du firmware (variables EFI). Il ne peut ni lire ni modifier Windows ou Smoky OS.
 */
#include "uefi.h"
#include "noyau.h"

static int noyau_actif;                 /* 1 dès que le firmware est congédié */

int _fltused = 0;              /* exigé par la cible Windows dès qu'on calcule en virgule flottante */

static EFI_SYSTEM_TABLE *ST;
static EFI_BOOT_SERVICES *BS;
static EFI_RUNTIME_SERVICES *RT;

/* --- Mémoire (le compilateur en a besoin) -------------------------------------------------- */
void *memset(void *d, int c, UINTN n) {
  void *r = d;
  __asm__ volatile("rep stosb" : "+D"(d), "+c"(n) : "a"(c) : "memory");
  return r;
}
void *memcpy(void *d, const void *s, UINTN n) {
  void *r = d;
  __asm__ volatile("rep movsb" : "+D"(d), "+S"(s), "+c"(n) : : "memory");
  return r;
}

static int entier(float f) { return (int)f - ((float)(int)f > f); }      /* partie entière (vers le bas) */
static float bornes(float v, float a, float b) { return v < a ? a : v > b ? b : v; }

static float sinus(float x) {                                /* assez précis pour placer des braises */
  while (x > 3.14159265f) x -= 6.2831853f;
  while (x < -3.14159265f) x += 6.2831853f;
  float x2 = x * x;
  return x * (1 - x2 / 6 * (1 - x2 / 20 * (1 - x2 / 42 * (1 - x2 / 72))));
}
static float cosinus(float x) { return sinus(x + 1.5707963f); }

/* --- Écran ---------------------------------------------------------------------------------- */
static u32 *ecran, *fond, *image;     /* mémoire vidéo ; fond calculé une fois ; image en cours */
static int L, H, PAS, BVR;
static float U;                       /* unité : 1 px pour un écran de 1200 px de haut */

static u32 melange(u32 a, u32 b, float t) {
  int r = ((a >> 16) & 255) + (int)((((int)(b >> 16) & 255) - ((int)(a >> 16) & 255)) * t);
  int g = ((a >> 8) & 255) + (int)((((int)(b >> 8) & 255) - ((int)(a >> 8) & 255)) * t);
  int v = (a & 255) + (int)((((int)b & 255) - ((int)a & 255)) * t);
  return (u32)(r << 16 | g << 8 | v);
}

static void point(int x, int y, u32 c, float a) {
  if (x < 0 || y < 0 || x >= L || y >= H || a <= 0) return;
  u32 *p = &image[y * L + x];
  *p = a >= 1 ? c : melange(*p, c, a);
}

static void montrer(int x, int y, int w, int h) {            /* image → écran */
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > L) w = L - x;
  if (y + h > H) h = H - y;
  for (int j = y; j < y + h; j++)
    for (int i = x; i < x + w; i++) {
      u32 c = image[j * L + i];
      ecran[j * PAS + i] = BVR ? c : ((c & 0xff) << 16 | (c & 0xff00) | (c >> 16 & 0xff));
    }
}

static void restaurer(int x, int y, int w, int h) {          /* fond → image */
  for (int j = y < 0 ? 0 : y; j < y + h && j < H; j++)
    memcpy(&image[j * L + (x < 0 ? 0 : x)], &fond[j * L + (x < 0 ? 0 : x)], (UINTN)((w < L - x ? w : L - x) * 4));
}

/* rectangle aux coins arrondis, bord adouci */
static void bloc(float x, float y, float w, float h, float r, u32 c, float a) {
  for (int j = entier(y); j <= entier(y + h); j++)
    for (int i = entier(x); i <= entier(x + w); i++) {
      float dx = (i + .5f < x + r) ? x + r - (i + .5f) : (i + .5f > x + w - r) ? (i + .5f) - (x + w - r) : 0;
      float dy = (j + .5f < y + r) ? y + r - (j + .5f) : (j + .5f > y + h - r) ? (j + .5f) - (y + h - r) : 0;
      float d = __builtin_sqrtf(dx * dx + dy * dy) - r;
      point(i, j, c, a * bornes(.5f - d, 0, 1));
    }
}

/* --- Police Smoky : chaque signe est fait de traits sur une grille 4 × 8 -------------------------
 * Un trait = suite de points « xy » (chiffres) ; traits séparés par une espace. Ligne de base à 6,
 * hauteur des minuscules à 2, jambages jusqu'à 8. Dessinée pour cet OS, elle s'agrandit sans perte. */
static const char *GLYPHES[128] = {
  [' '] = "", ['.'] = "2626", [','] = "2617", [':'] = "2222 2626", [';'] = "2222 2617", ['!'] = "2024 2626",
  ['?'] = "011030414224 2626", ['-'] = "1333", ['+'] = "1333 2224", ['='] = "1232 1434", ['/'] = "4006",
  ['('] = "30212536", [')'] = "10212516", ['\''] = "2022", ['"'] = "1012 3032", ['<'] = "311335",
  ['>'] = "113315", ['_'] = "0747", ['%'] = "4006 0010110100 3545463635", ['*'] = "2125 1234 1432", ['#'] = "1115 3135 0232 0434",
  ['0'] = "103041453616050110 1531", ['1'] = "112026 1636", ['2'] = "01103041420646",
  ['3'] = "01103041423313 334445361605", ['4'] = "36300444", ['5'] = "400003334445361605",
  ['6'] = "4130100105163645443303", ['7'] = "004016", ['8'] = "13020110304142331304051636454433",
  ['9'] = "4313020110304145361605",
  ['A'] = "062046 1434", ['B'] = "06003041423303 3344453606", ['C'] = "4130100105163645",
  ['D'] = "00304145360600", ['E'] = "40000646 0333", ['F'] = "400006 0333", ['G'] = "41301001051636454323",
  ['H'] = "0006 4046 0343", ['I'] = "1030 2026 1636", ['J'] = "4045361605", ['K'] = "0006 4004 1346",
  ['L'] = "000646", ['M'] = "0600234046", ['N'] = "06004640", ['O'] = "103041453616050110",
  ['P'] = "06003041423303", ['Q'] = "103041453616050110 2446", ['R'] = "06003041423303 2346",
  ['S'] = "413010010213334445361605", ['T'] = "0040 2026", ['U'] = "000516364540", ['V'] = "002640",
  ['W'] = "0016233640", ['X'] = "0046 4006", ['Y'] = "002340 2326", ['Z'] = "00400646",
  ['a'] = "12324346 441405163645", ['b'] = "0006 0312324345361605", ['c'] = "4332120305163645",
  ['d'] = "4046 4332120305163645", ['e'] = "04444332120305163645", ['f'] = "30201116 0232",
  ['g'] = "4247381807 4332120304153544", ['h'] = "0006 0312324346", ['i'] = "2226 2020",
  ['j'] = "22271808 2020", ['k'] = "0006 3205 1446", ['l'] = "10202536", ['m'] = "0602 03122326 23324346",
  ['n'] = "0602 0312324346", ['o'] = "123243453616050312", ['p'] = "0208 0312324345361605",
  ['q'] = "4248 4332120305163645", ['r'] = "0206 031232", ['s'] = "43321203143445361605",
  ['t'] = "10152636 0232", ['u'] = "0205163645 4246", ['v'] = "022642", ['w'] = "0216243642",
  ['x'] = "0246 4206", ['y'] = "0226 4218", ['z'] = "02420646",
};
/* lettres accentuées du français : lettre de base + accent posé dessus (ou cédille dessous) */
static const struct { u32 code; char base; const char *accent; } ACCENTS[] = {
  {0xe9, 'e', "2130"}, {0xe8, 'e', "1021"}, {0xea, 'e', "112031"}, {0xeb, 'e', "1010 3030"},
  {0xe0, 'a', "1021"}, {0xe2, 'a', "112031"}, {0xe7, 'c', "262718"}, {0xf9, 'u', "1021"},
  {0xfb, 'u', "112031"}, {0xfc, 'u', "1010 3030"}, {0xf4, 'o', "112031"}, {0xee, '|', "112031"},
  {0xef, '|', "1010 3030"}, {0xc9, 'E', "2130"}, {0xab, '<', ""}, {0xbb, '>', ""}, {0xd7, 'x', ""},
};

static float couverture[340 * 340];

static void traits(float x, float y, float s, float demi, const char *t, float *c, int x0, int y0, int w, int h) {
  while (*t) {
    float px = -1, py = 0;
    while (*t && *t != ' ') {
      float qx = x + (t[0] - '0') * s, qy = y + (t[1] - '0') * s;
      if (px < 0) { px = qx; py = qy; }                  /* premier point : un trait de longueur nulle = un point */
      float vx = qx - px, vy = qy - py, l2 = vx * vx + vy * vy;
      int a = entier((px < qx ? px : qx) - demi - 1), b = entier((px > qx ? px : qx) + demi + 1);
      int e = entier((py < qy ? py : qy) - demi - 1), f = entier((py > qy ? py : qy) + demi + 1);
      for (int j = e; j <= f; j++)
        for (int i = a; i <= b; i++) {
          if (i < x0 || j < y0 || i >= x0 + w || j >= y0 + h) continue;
          float cx = i + .5f - px, cy = j + .5f - py;
          float k = l2 > 0 ? bornes((cx * vx + cy * vy) / l2, 0, 1) : 0;
          float dx = cx - k * vx, dy = cy - k * vy;
          float v = bornes(demi + .5f - __builtin_sqrtf(dx * dx + dy * dy), 0, 1);
          float *p = &c[(j - y0) * w + (i - x0)];
          if (v > *p) *p = v;
        }
      px = qx; py = qy;
      t += 2;
    }
    while (*t == ' ') t++;
  }
}

/* dessine un caractère posé sur la ligne de base y ; renvoie son avance en pixels */
static float signe(float x, float y, float taille, float graisse, u32 coul, u32 code) {
  const char *base = 0, *accent = "";
  if (code == '|') base = "2226";
  else if (code < 128) base = GLYPHES[code];
  for (unsigned i = 0; !base && i < sizeof ACCENTS / sizeof *ACCENTS; i++)
    if (ACCENTS[i].code == code) {
      base = ACCENTS[i].base == '|' ? "2226" : GLYPHES[(int)ACCENTS[i].base];
      accent = ACCENTS[i].accent;
    }
  if (!base) base = "0006 0646 4640 4000";                  /* signe inconnu : une boîte */
  float s = taille / 8, demi = s * graisse;
  if (code == ' ') return s * 3.4f;
  y -= 6 * s;                                                /* on reçoit la ligne de base */
  int x0 = entier(x - demi - 2), y0 = entier(y - s - demi - 2);
  int w = (int)(4 * s + 2 * demi + 5), h = (int)(9 * s + 2 * demi + 5);
  if (w * h > 340 * 340) return s * 5.6f;
  memset(couverture, 0, (UINTN)(w * h) * sizeof(float));
  traits(x, y, s, demi, base, couverture, x0, y0, w, h);
  traits(x, y, s, demi * .85f, accent, couverture, x0, y0, w, h);
  for (int j = 0; j < h; j++)
    for (int i = 0; i < w; i++)
      if (couverture[j * w + i] > 0) point(x0 + i, y0 + j, coul, couverture[j * w + i]);
  return s * 5.6f;
}

/* UTF-8 → points de code */
static int decoder(const char *t, u32 *sortie, int max) {
  int n = 0;
  const u8 *p = (const u8 *)t;
  while (*p && n < max) {
    u32 c = *p++;
    if (c >= 0xe0) { c = (c & 15) << 12 | (p[0] & 63) << 6 | (p[1] & 63); p += 2; }
    else if (c >= 0xc0) { c = (c & 31) << 6 | (p[0] & 63); p++; }
    sortie[n++] = c;
  }
  return n;
}

static float largeur(const u32 *t, int n, float taille) {
  float s = taille / 8, l = 0;
  for (int i = 0; i < n; i++) l += t[i] == ' ' ? s * 3.4f : s * 5.6f;
  return l;
}

static float ecrire(float x, float y, float taille, float graisse, u32 coul, const char *texte) {
  u32 t[200];
  int n = decoder(texte, t, 200);
  for (int i = 0; i < n; i++) x += signe(x, y, taille, graisse, coul, t[i]);
  return x;
}

/* --- Le fond : fumée froide en haut, braises en bas à droite --------------------------------- */
static u32 graine = 0x2026bead;
static float hasard(void) { graine = graine * 1664525u + 1013904223u; return (graine >> 8) / 16777216.0f; }

static void dessiner_fond(void) {
  for (int y = 0; y < H; y++)
    for (int x = 0; x < L; x++) {
      float fy = (float)y / H;
      u32 c = melange(0x0a0a0c, 0x140d0b, fy * fy);
      float dx = (x - L * .82f) / (H * .95f), dy = (y - H * 1.08f) / (H * .95f);
      float d = __builtin_sqrtf(dx * dx + dy * dy);
      float lueur = bornes(1 - d, 0, 1);
      c = melange(c, 0xff6a3d, lueur * lueur * lueur * .38f);
      float ex = (x - L * .12f) / (H * .8f), ey = (y + H * .15f) / (H * .8f);
      float f = bornes(1 - __builtin_sqrtf(ex * ex + ey * ey), 0, 1);
      c = melange(c, 0xb6b7c2, f * f * .07f);
      fond[y * L + x] = c;
    }
  u32 *garde = image;                                     /* les braises : petits points chauds */
  image = fond;
  for (int k = 0; k < 420; k++) {
    float r = hasard(), a = hasard() * 6.2832f;
    float px = L * .82f + cosinus(a) * r * H * .9f, py = H * 1.05f + sinus(a) * r * H * .75f;
    float t = bornes(1.1f - r, 0, 1), rayon = (.6f + hasard() * 1.8f) * U;
    bloc(px - rayon, py - rayon, 2 * rayon, 2 * rayon, rayon, hasard() < .3f ? 0xffd2a1 : 0xff8f5a, t * (.25f + hasard() * .6f));
  }
  image = garde;
  memcpy(image, fond, (UINTN)L * H * 4);
}

/* --- Le carnet : commandes et réponses -------------------------------------------------------- */
#define LIGNES 64
#define LARGE 110
static u32 journal[LIGNES][LARGE];
static int longueurs[LIGNES], couleurs[LIGNES], nb_lignes;
static u32 saisie[LARGE];
static int nb_saisie;
static float CX, CY, CW, CH;

static void noter(const char *texte, u32 couleur) {
  if (nb_lignes == LIGNES) {
    for (int i = 1; i < LIGNES; i++) {
      memcpy(journal[i - 1], journal[i], sizeof journal[0]);
      longueurs[i - 1] = longueurs[i]; couleurs[i - 1] = couleurs[i];
    }
    nb_lignes--;
  }
  longueurs[nb_lignes] = decoder(texte, journal[nb_lignes], LARGE);
  couleurs[nb_lignes++] = (int)couleur;
}

static void dessiner_carnet(void) {
  int x = entier(CX), y = entier(CY), w = (int)CW + 2, h = (int)CH + 2;
  restaurer(x - 2, y - 2, w + 4, h + 4);
  bloc(CX, CY, CW, CH, 20 * U, 0x2b2b31, .95f);
  bloc(CX + 1, CY + 1, CW - 2, CH - 2, 19 * U, 0x111113, .94f);
  ecrire(CX + 30 * U, CY + 34 * U, 19 * U, .42f, 0xf3f3f6, "carnet");
  ecrire(CX + CW - 300 * U, CY + 34 * U, 15 * U, .38f, 0x7c7c86, "tape « aide » puis Entrée");
  float taille = 21 * U, pas = 33 * U, bas = CY + CH - 34 * U;
  int visibles = (int)((CH - 130 * U) / pas);
  int premier = nb_lignes > visibles ? nb_lignes - visibles : 0;
  for (int i = premier; i < nb_lignes; i++) {
    float lx = CX + 34 * U, ly = CY + 90 * U + (i - premier) * pas;
    for (int k = 0; k < longueurs[i]; k++) lx += signe(lx, ly, taille, .38f, (u32)couleurs[i], journal[i][k]);
  }
  bloc(CX + 22 * U, bas - 30 * U, CW - 44 * U, 46 * U, 14 * U, 0x1d1d21, .95f);
  float lx = CX + 38 * U;
  lx += signe(lx, bas, taille, .45f, 0xff8f85, '>');
  lx += 10 * U;
  for (int k = 0; k < nb_saisie; k++) lx += signe(lx, bas, taille, .38f, 0xf3f3f6, saisie[k]);
  bloc(lx + 2 * U, bas - 22 * U, 3 * U, 26 * U, 1.5f * U, 0xff8f85, 1);   /* curseur (fixe : pas de clignotement) */
  montrer(x - 2, y - 2, w + 4, h + 4);
}

/* --- L'heure, en haut à droite ------------------------------------------------------------------ */
static const char *JOURS[] = {"dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"};
static const char *MOIS[] = {"janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                             "septembre", "octobre", "novembre", "décembre"};
static int derniere_minute = -1;

static int lire_heure(EFI_TIME *t) {
  return noyau_actif ? noyau_heure(t) : !EFI_ERREUR(RT->lire_heure(t, 0));
}

static int jour_semaine(int a, int m, int j) {             /* Zeller simplifié (0 = dimanche) */
  static const int t[] = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
  if (m < 3) a--;
  return (a + a / 4 - a / 100 + a / 400 + t[m - 1] + j) % 7;
}

static void nombre(char *d, int n, int chiffres) {
  for (int i = chiffres - 1; i >= 0; i--) { d[i] = (char)('0' + n % 10); n /= 10; }
  d[chiffres] = 0;
}

static void copier(char *d, const char *s) { while ((*d++ = *s++)); }

static void nombre_libre(char *d, u64 n) {                 /* nombre sans zéros devant */
  char t[24]; int i = 0;
  do { t[i++] = (char)('0' + n % 10); n /= 10; } while (n);
  while (i) *d++ = t[--i];
  *d = 0;
}
static char *fin(char *d) { while (*d) d++; return d; }

static void dessiner_heure(int force) {
  EFI_TIME t;
  if (!lire_heure(&t)) return;
  if (!force && t.minute == derniere_minute) return;
  derniere_minute = t.minute;
  int x = L - entier(420 * U), y = entier(18 * U), w = entier(400 * U), h = entier(110 * U);
  restaurer(x, y, w, h);
  char hm[8], date[64];
  nombre(hm, t.heure, 2); hm[2] = ':'; nombre(hm + 3, t.minute, 2);
  copier(date, JOURS[jour_semaine(t.annee, t.mois, t.jour)]);
  copier(fin(date), " ");
  nombre(fin(date), t.jour, t.jour >= 10 ? 2 : 1);
  copier(fin(date), " ");
  copier(fin(date), MOIS[(t.mois + 11) % 12]);
  u32 tmp[64];
  float lh = largeur(tmp, decoder(hm, tmp, 64), 44 * U), ld = largeur(tmp, decoder(date, tmp, 64), 17 * U);
  ecrire(L - 44 * U - lh, 74 * U, 44 * U, .5f, 0xf3f3f6, hm);
  ecrire(L - 44 * U - ld, 108 * U, 17 * U, .4f, 0xb6b7c2, date);
  montrer(x, y, w, h);
}

/* --- Commandes du carnet ------------------------------------------------------------------------ */
static int egal(const u32 *a, int n, const char *b) {
  int i = 0;
  for (; i < n && b[i]; i++) if (a[i] != (u8)b[i]) return 0;
  return i == n && !b[i];
}

static void taille_texte(char *d, u64 octets) {
  u64 mo = octets / (1024 * 1024);
  char n[24];
  if (mo >= 1024) {
    nombre_libre(n, mo / 1024); copier(fin(d), n); copier(fin(d), ",");
    nombre_libre(n, mo % 1024 * 10 / 1024); copier(fin(d), n); copier(fin(d), " Go");
  } else {
    nombre_libre(n, mo); copier(fin(d), n); copier(fin(d), " Mo");
  }
}

static void memoire(char *d) {
  copier(d, "Mémoire vive : ");
  taille_texte(d, noyau_memoire_totale());
  copier(fin(d), ", dont ");
  taille_texte(d, noyau_memoire_libre());
  copier(fin(d), " libres");
}

static int executer(void) {                                 /* renvoie 1 pour quitter */
  char ligne[160] = "> ";
  char *p = fin(ligne);
  for (int i = 0; i < nb_saisie && p < ligne + 150; i++) {
    u32 c = saisie[i];
    if (c < 0x80) *p++ = (char)c;
    else if (c < 0x800) { *p++ = (char)(0xc0 | c >> 6); *p++ = (char)(0x80 | (c & 63)); }
    else { *p++ = (char)(0xe0 | c >> 12); *p++ = (char)(0x80 | (c >> 6 & 63)); *p++ = (char)(0x80 | (c & 63)); }
  }
  *p = 0;
  noter(ligne, 0x7c7c86);
  u32 *s = saisie; int n = nb_saisie;
  while (n && *s == ' ') { s++; n--; }
  while (n && s[n - 1] == ' ') n--;
  int quitter = 0;
  if (!n) ;
  else if (egal(s, n, "aide")) {
    noter("heure       l'heure et la date", 0xb6b7c2);
    noter("memoire     la mémoire vive du PC", 0xb6b7c2);
    noter("ecran       la définition de l'écran", 0xb6b7c2);
    noter("systeme     ce que Smoky OS gère lui-même", 0xb6b7c2);
    noter("effacer     vide le carnet", 0xb6b7c2);
    noter("apropos     ce qu'est cet OS", 0xb6b7c2);
    noter("redemarrer, eteindre", 0xb6b7c2);
  } else if (egal(s, n, "heure")) {
    EFI_TIME t; char d[96], x[8];
    if (lire_heure(&t)) {
      copier(d, "Il est "); nombre(x, t.heure, 2); copier(fin(d), x); copier(fin(d), " h ");
      nombre(x, t.minute, 2); copier(fin(d), x); copier(fin(d), ", ");
      copier(fin(d), JOURS[jour_semaine(t.annee, t.mois, t.jour)]); copier(fin(d), " ");
      nombre(x, t.jour, t.jour >= 10 ? 2 : 1); copier(fin(d), x); copier(fin(d), " ");
      copier(fin(d), MOIS[(t.mois + 11) % 12]); copier(fin(d), " "); nombre(x, t.annee, 4); copier(fin(d), x);
      noter(d, 0xf3f3f6);
    }
  } else if (egal(s, n, "memoire") || egal(s, n, "mémoire")) {
    char d[96]; memoire(d); noter(d, 0xf3f3f6);
  } else if (egal(s, n, "ecran") || egal(s, n, "écran")) {
    char d[96], x[8];
    copier(d, "Écran : "); nombre(x, L, L >= 1000 ? 4 : 3); copier(fin(d), x); copier(fin(d), " × ");
    nombre(x, H, H >= 1000 ? 4 : 3); copier(fin(d), x); copier(fin(d), BVR ? " (BVR)" : " (RVB)");
    noter(d, 0xf3f3f6);
  } else if (egal(s, n, "systeme") || egal(s, n, "système")) {
    char d[120], x[24];
    noter("Le firmware est congédié : Smoky OS gère seul", 0xf3f3f6);
    noter("interruptions, minuterie, clavier AZERTY, horloge et mémoire.", 0xb6b7c2);
    u64 secondes = noyau_tics() / TICS_PAR_SECONDE;
    copier(d, "Allumé depuis "); nombre_libre(x, secondes / 60); copier(fin(d), x); copier(fin(d), " min ");
    nombre_libre(x, secondes % 60); copier(fin(d), x); copier(fin(d), " s");
    noter(d, 0xb6b7c2);
    copier(d, "Interruptions : minuterie "); nombre_libre(x, noyau_interruptions(0)); copier(fin(d), x);
    copier(fin(d), ", clavier "); nombre_libre(x, noyau_interruptions(1)); copier(fin(d), x);
    noter(d, 0xb6b7c2);
  } else if (egal(s, n, "effacer")) {
    nb_lignes = 0;
  } else if (egal(s, n, "apropos") || egal(s, n, "à-propos")) {
    noter("Smoky OS 100 % maison 0.2 : écrit de zéro, sans Linux ni bibliothèque.", 0xf3f3f6);
    noter("Il démarre par le firmware, puis se débrouille seul.", 0xb6b7c2);
    noter("Aucun pilote de disque : il ne peut pas toucher à tes systèmes.", 0xb6b7c2);
  } else if (egal(s, n, "redemarrer") || egal(s, n, "redémarrer")) {
    noyau_redemarrer();
  } else if (egal(s, n, "eteindre") || egal(s, n, "éteindre")) {
    RT->redemarrer(EFI_RESET_ARRET, EFI_SUCCESS, 0, 0);
  } else {
    noter("Commande inconnue. Tape « aide ».", 0xff8f85);
  }
  nb_saisie = 0;
  return quitter;
}

/* --- Démarrage ---------------------------------------------------------------------------------- */
static int choisir_ecran(void) {
  EFI_GOP *gop = 0;
  if (EFI_ERREUR(BS->trouver_protocole(&GUID_GOP, 0, (void **)&gop)) || !gop) return 0;
  u32 meilleur = gop->mode->mode; u64 score = 0;
  for (u32 m = 0; m < gop->mode->nb_modes; m++) {
    UINTN t; EFI_GOP_MODE_INFO *info;
    if (EFI_ERREUR(gop->lire_mode(gop, m, &t, &info)) || info->format > PIXEL_BVR) continue;
    if (info->largeur > 1920 || info->hauteur > 1200) continue;
    u64 s = (u64)info->largeur * info->hauteur;
    if (s > score) { score = s; meilleur = m; }
  }
  if (meilleur != gop->mode->mode) gop->choisir_mode(gop, meilleur);
  EFI_GOP_MODE_INFO *i = gop->mode->info;
  if (i->format > PIXEL_BVR) return 0;
  L = (int)i->largeur; H = (int)i->hauteur; PAS = (int)i->pixels_par_ligne; BVR = i->format == PIXEL_BVR;
  ecran = (u32 *)gop->mode->tampon_ecran;
  U = H / 1200.0f;
  return 1;
}

EFI_STATUS efi_main(EFI_HANDLE image_os, EFI_SYSTEM_TABLE *st) {
  (void)image_os;
  ST = st; BS = st->demarrage; RT = st->execution;
  BS->chien_de_garde(0, 0, 0, 0);                    /* sinon le firmware redémarre le PC après 5 min */
  if (!choisir_ecran()) {
    st->sortie->ecrire(st->sortie, (CHAR16 *)u"Smoky OS : pas d'ecran graphique utilisable.\r\n");
    return 1;
  }
  st->sortie->curseur_visible(st->sortie, 0);
  if (EFI_ERREUR(BS->allouer(EFI_MEMOIRE_DONNEES_CHARGEUR, (UINTN)L * H * 4, (void **)&fond)) ||
      EFI_ERREUR(BS->allouer(EFI_MEMOIRE_DONNEES_CHARGEUR, (UINTN)L * H * 4, (void **)&image)))
    return 1;
  dessiner_fond();
  float x = ecrire(44 * U, 74 * U, 44 * U, .55f, 0xff8f85, "smoky os");
  ecrire(x + 12 * U, 74 * U, 17 * U, .4f, 0x7c7c86, "0.2");
  ecrire(44 * U, 108 * U, 17 * U, .4f, 0xb6b7c2, "100 % maison, écrit de zéro");
  ecrire(44 * U, H - 40 * U, 15 * U, .38f, 0x7c7c86,
         "Aucun pilote de disque : ton Windows et ton Smoky OS de tous les jours ne peuvent pas être touchés.");
  memcpy(fond, image, (UINTN)L * H * 4);
  montrer(0, 0, L, H);
  CW = 1080 * U; CH = 760 * U; CX = (L - CW) / 2; CY = 170 * U;
  if (CW > L - 40) { CW = L - 40; CX = 20; }
  noter("Bonjour ! Smoky OS a démarré tout seul, sans Linux.", 0xf3f3f6);
  noter("Tape « aide » pour voir ce qu'il sait faire.", 0xb6b7c2);
  dessiner_carnet();
  dessiner_heure(1);

  /* congé au firmware : dernière carte de la mémoire, puis ExitBootServices (sans rien afficher
   * ni allouer entre les deux, sinon la carte change et il faut recommencer) */
  static EFI_MEMORY_DESCRIPTOR carte[768];
  UINTN taille = 0, cle = 0, taille_desc = 0; u32 version;
  for (int essai = 0; essai < 8 && !noyau_actif; essai++) {
    taille = sizeof carte;
    if (EFI_ERREUR(BS->carte_memoire(&taille, carte, &cle, &taille_desc, &version))) break;
    if (!EFI_ERREUR(BS->sortir_services(image_os, cle))) noyau_actif = 1;
  }
  if (!noyau_actif) {
    noter("Le firmware n'a pas voulu laisser la main.", 0xff8f85);
    dessiner_carnet();
    for (;;) __asm__ volatile("hlt");
  }
  noyau_demarrer(carte, taille, taille_desc);
  noter("Firmware congédié : Smoky OS tourne seul. Tape « systeme ».", 0xb6b7c2);
  dessiner_carnet();
  u64 derniere_seconde = 0;
  for (;;) {
    noyau_attendre();                                       /* le processeur dort entre deux interruptions */
    u64 seconde = noyau_tics() / TICS_PAR_SECONDE;
    if (seconde != derniere_seconde) { derniere_seconde = seconde; dessiner_heure(0); }
    u32 c; int genre, change = 0;
    while (noyau_touche(&c, &genre)) {
      if (genre == TOUCHE_ENTREE) executer();
      else if (genre == TOUCHE_EFFACER) { if (nb_saisie) nb_saisie--; }
      else if (genre == TOUCHE_ECHAP) nb_saisie = 0;
      else if (nb_saisie < 90) saisie[nb_saisie++] = c;
      change = 1;
    }
    if (change) dessiner_carnet();
  }
}

/* --- Écran d'erreur : le processeur a signalé une faute (appelé par le noyau, sans retour) --------- */
void noyau_panique(int vecteur, u64 code_erreur, u64 adresse) {
  static const char *NOMS[32] = {"division par zéro", "pas à pas", "NMI", "point d'arrêt", "dépassement",
    "hors limites", "instruction inconnue", "coprocesseur absent", "double faute", "", "segment d'état",
    "segment absent", "pile", "protection générale", "défaut de page", "", "calcul flottant",
    "alignement", "vérification machine", "calcul SIMD", "virtualisation", "contrôle de flux"};
  char d[160], x[24];
  float w = 900 * U, h = 260 * U, bx = (L - w) / 2, by = (H - h) / 2;
  bloc(bx, by, w, h, 20 * U, 0xff8f85, 1);
  bloc(bx + 2, by + 2, w - 4, h - 4, 19 * U, 0x1a0f0e, 1);
  ecrire(bx + 40 * U, by + 64 * U, 26 * U, .5f, 0xff8f85, "Le processeur a signalé une erreur");
  copier(d, "Faute n° "); nombre_libre(x, (u64)vecteur); copier(fin(d), x);
  if (vecteur >= 0 && vecteur < 32 && NOMS[vecteur] && NOMS[vecteur][0]) { copier(fin(d), " : "); copier(fin(d), NOMS[vecteur]); }
  copier(fin(d), " (code "); nombre_libre(x, code_erreur); copier(fin(d), x); copier(fin(d), ")");
  ecrire(bx + 40 * U, by + 120 * U, 19 * U, .4f, 0xf3f3f6, d);
  copier(d, "Instruction à l'adresse "); nombre_libre(x, adresse); copier(fin(d), x);
  ecrire(bx + 40 * U, by + 160 * U, 17 * U, .38f, 0xb6b7c2, d);
  ecrire(bx + 40 * U, by + 210 * U, 17 * U, .38f, 0xb6b7c2, "Smoky OS s'est arrêté. Rien n'a été écrit sur ton disque.");
  montrer((int)bx - 2, (int)by - 2, (int)w + 4, (int)h + 4);
  for (;;) __asm__ volatile("cli\n hlt");
}
