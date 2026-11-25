/* Smoky OS 100 % maison, version 0.6 — un système d'exploitation écrit de zéro, pour toi.
 *
 * Aucun Linux, aucune bibliothèque : ce fichier, uefi.h (écrit d'après la spécification) et le
 * compilateur. Il démarre directement par le firmware UEFI du PC, dessine lui-même tout ce
 * que tu vois (y compris sa police, faite de traits sur une grille), lit le clavier et la souris,
 * et ouvre des fenêtres : le carnet de commandes, une calculatrice, des notes, une horloge. Le firmware ne sert qu'à démarrer : ensuite Smoky OS le congédie et gère
 * seul les interruptions, la minuterie, le clavier et l'horloge (noyau.c).
 *
 * Sécurité de ton PC : il n'a AUCUN pilote de disque et n'appelle jamais les fonctions
 * d'écriture du firmware (variables EFI). Il ne peut ni lire ni modifier Windows ou Smoky OS.
 */
#include "uefi.h"
#include "noyau.h"
#include "usb.h"

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

/* zone en cours de dessin : rien n'est dessiné hors d'elle (voir rafraichir) */
static int ZX0, ZY0, ZX1 = 1 << 30, ZY1 = 1 << 30;

static void point(int x, int y, u32 c, float a) {
  if (x < ZX0 || y < ZY0 || x >= ZX1 || y >= ZY1 || x < 0 || y < 0 || x >= L || y >= H || a <= 0) return;
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
  int j0 = entier(y), j1 = entier(y + h), i0 = entier(x), i1 = entier(x + w);
  if (j0 < ZY0) j0 = ZY0;
  if (j1 >= ZY1) j1 = ZY1 - 1;
  if (i0 < ZX0) i0 = ZX0;
  if (i1 >= ZX1) i1 = ZX1 - 1;
  for (int j = j0; j <= j1; j++) {
    float dy = (j + .5f < y + r) ? y + r - (j + .5f) : (j + .5f > y + h - r) ? (j + .5f) - (y + h - r) : 0;
    for (int i = i0; i <= i1; i++) {
      float dx = (i + .5f < x + r) ? x + r - (i + .5f) : (i + .5f > x + w - r) ? (i + .5f) - (x + w - r) : 0;
      float cov = dx == 0 && dy == 0 ? 1 : bornes(.5f - (__builtin_sqrtf(dx * dx + dy * dy) - r), 0, 1);
      point(i, j, c, a * cov);                                /* l'intérieur : sans racine carrée */
    }
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

/* signes hors ASCII que le clavier AZERTY tape directement (Alt Gr, Maj), et la flèche */
static const struct { u32 code; const char *traits; } AUTRES[] = {
  {0x20ac, "4130100105163645 0232 0434"},                  /* € */
  {0xa3, "4130201116 0646 0333"},                         /* £ */
  {0xb0, "102022121210"},                                 /* ° */
  {0xb5, "0208 0205163645 4246"},                         /* µ */
  {0x2192, "0444 224426"},                                /* → (chemin d'un appareil derrière un hub) */
  {0x2190, "0444 220426"},                                /* ← (effacer, dans la calculatrice) */
  {0xd7, "1234 1432"},                                    /* × */
  {0xf7, "1333 2121 2525"},                               /* ÷ */
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
  for (unsigned i = 0; !base && i < sizeof AUTRES / sizeof *AUTRES; i++)
    if (AUTRES[i].code == code) base = AUTRES[i].traits;
  if (!base) base = "0006 0646 4640 4000";                  /* signe inconnu : une boîte */
  float s = taille / 8, demi = s * graisse;
  if (code == ' ') return s * 3.4f;
  y -= 6 * s;                                                /* on reçoit la ligne de base */
  int x0 = entier(x - demi - 2), y0 = entier(y - s - demi - 2);
  int w = (int)(4 * s + 2 * demi + 5), h = (int)(9 * s + 2 * demi + 5);
  if (w * h > 340 * 340) return s * 5.6f;
  if (x0 >= ZX1 || y0 >= ZY1 || x0 + w <= ZX0 || y0 + h <= ZY0) return s * 5.6f;   /* hors de la zone */
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

/* --- Fenêtres ---------------------------------------------------------------------------------
 * Chacune a sa place et son rang ; celle de devant reçoit le clavier. On la déplace par sa barre de
 * titre, on la ferme par son bouton ou Échap (sauf le carnet), Alt+Tab passe à la suivante. L'écran
 * n'est refait que là où quelque chose a changé (abimer, puis rafraichir). */
enum { F_CARNET, F_CALC, F_NOTES, F_HORLOGE, NB_FEN };
static const char *TITRES[NB_FEN] = {"carnet", "calculatrice", "notes", "horloge"};
static struct { float x, y, w, h; int ouverte; } FEN[NB_FEN];
static int pile[NB_FEN], nb_pile;                           /* pile[nb_pile - 1] : devant */
static int AX0, AY0, AX1, AY1, rien_a_refaire = 1;          /* zone abîmée, à refaire */

static void abimer(float x, float y, float w, float h) {
  int x0 = entier(x) - 3, y0 = entier(y) - 3, x1 = entier(x + w) + 4, y1 = entier(y + h) + 4;
  if (x0 < 0) x0 = 0;
  if (y0 < 0) y0 = 0;
  if (x1 > L) x1 = L;
  if (y1 > H) y1 = H;
  if (x0 >= x1 || y0 >= y1) return;
  if (rien_a_refaire) { AX0 = x0; AY0 = y0; AX1 = x1; AY1 = y1; rien_a_refaire = 0; return; }
  if (x0 < AX0) AX0 = x0;
  if (y0 < AY0) AY0 = y0;
  if (x1 > AX1) AX1 = x1;
  if (y1 > AY1) AY1 = y1;
}
static void abimer_fenetre(int f) { abimer(FEN[f].x, FEN[f].y, FEN[f].w, FEN[f].h); }
static int devant(void) { return nb_pile ? pile[nb_pile - 1] : -1; }

static void retirer(int f) {
  int k = 0;
  for (int i = 0; i < nb_pile; i++) if (pile[i] != f) pile[k++] = pile[i];
  nb_pile = k;
}
static void mettre_devant(int f) {
  int avant = devant();
  retirer(f);
  pile[nb_pile++] = f;
  abimer_fenetre(f);
  if (avant >= 0 && avant != f) abimer_fenetre(avant);      /* son titre s'éteint */
}
static void ouvrir(int f) { FEN[f].ouverte = 1; mettre_devant(f); }
static void fermer(int f) {
  if (f <= F_CARNET || !FEN[f].ouverte) return;            /* le carnet reste toujours */
  FEN[f].ouverte = 0;
  retirer(f);
  abimer_fenetre(f);
  if (devant() >= 0) abimer_fenetre(devant());
}
static void suivante(void) {                                /* Alt+Tab : celle de devant passe derrière */
  if (nb_pile < 2) return;
  int f = pile[nb_pile - 1];
  for (int i = nb_pile - 1; i > 0; i--) pile[i] = pile[i - 1];
  pile[0] = f;
  abimer_fenetre(f);
  abimer_fenetre(devant());
}

static int dedans(float px, float py, float x, float y, float w, float h) {
  return px >= x && py >= y && px < x + w && py < y + h;
}
static float bouton_fermer_x(int f) { return FEN[f].x + FEN[f].w - 52 * U; }
static float bouton_fermer_y(int f) { return FEN[f].y + 14 * U; }

static void cadre(int f) {
  int actif = devant() == f;
  float x = FEN[f].x, y = FEN[f].y, w = FEN[f].w, h = FEN[f].h;
  bloc(x, y, w, h, 20 * U, actif ? 0x4a4a54 : 0x2b2b31, .96f);
  bloc(x + 1, y + 1, w - 2, h - 2, 19 * U, 0x111113, .95f);
  ecrire(x + 30 * U, y + 36 * U, 19 * U, .42f, actif ? 0xf3f3f6 : 0x8a8a94, TITRES[f]);
  if (f != F_CARNET) {
    float bx = bouton_fermer_x(f), by = bouton_fermer_y(f);
    bloc(bx, by, 30 * U, 30 * U, 15 * U, actif ? 0x2c2c33 : 0x1f1f24, 1);
    signe(bx + 9 * U, by + 26 * U, 18 * U, .5f, actif ? 0xff8f85 : 0x7c7c86, 0xd7);
  }
}

/* --- Le carnet ------------------------------------------------------------------------------------ */
static void abimer_saisie_carnet(void) {                    /* seule la ligne de saisie change quand on tape */
  abimer(FEN[F_CARNET].x + 20 * U, FEN[F_CARNET].y + FEN[F_CARNET].h - 66 * U, FEN[F_CARNET].w - 40 * U, 52 * U);
}
static void dessiner_carnet(void) {
  float X = FEN[F_CARNET].x, Y = FEN[F_CARNET].y, W = FEN[F_CARNET].w, Hc = FEN[F_CARNET].h;
  ecrire(X + W - 300 * U, Y + 36 * U, 15 * U, .38f, 0x7c7c86, "tape « aide » puis Entrée");
  float taille = 21 * U, pas = 33 * U, bas = Y + Hc - 34 * U;
  int visibles = (int)((Hc - 130 * U) / pas);
  int premier = nb_lignes > visibles ? nb_lignes - visibles : 0;
  for (int i = premier; i < nb_lignes; i++) {
    float lx = X + 34 * U, ly = Y + 90 * U + (i - premier) * pas;
    for (int k = 0; k < longueurs[i]; k++) lx += signe(lx, ly, taille, .38f, (u32)couleurs[i], journal[i][k]);
  }
  bloc(X + 22 * U, bas - 30 * U, W - 44 * U, 46 * U, 14 * U, 0x1d1d21, .95f);
  float lx = X + 38 * U;
  lx += signe(lx, bas, taille, .45f, 0xff8f85, '>');
  lx += 10 * U;
  for (int k = 0; k < nb_saisie; k++) lx += signe(lx, bas, taille, .38f, 0xf3f3f6, saisie[k]);
  if (devant() == F_CARNET) bloc(lx + 2 * U, bas - 22 * U, 3 * U, 26 * U, 1.5f * U, 0xff8f85, 1);   /* curseur */
}

/* --- L'heure, en haut à droite ------------------------------------------------------------------ */
static const char *JOURS[] = {"dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"};
static const char *MOIS[] = {"janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                             "septembre", "octobre", "novembre", "décembre"};
static int derniere_minute = -1;

static int jour_semaine(int a, int m, int j) {             /* Zeller simplifié (0 = dimanche) */
  static const int t[] = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
  if (m < 3) a--;
  return (a + a / 4 - a / 100 + a / 400 + t[m - 1] + j) % 7;
}

static int jours_du_mois(int a, int m) {
  static const int j[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  return m == 2 && a % 4 == 0 && (a % 100 || a % 400 == 0) ? 29 : j[m - 1];
}

/* heure d'été en Europe : du dernier dimanche de mars au dernier dimanche d'octobre, à 1 h UTC */
static int heure_ete(const EFI_TIME *t) {
  if (t->mois < 3 || t->mois > 10) return 0;
  if (t->mois > 3 && t->mois < 10) return 1;
  int dimanche = jours_du_mois(t->annee, t->mois) - jour_semaine(t->annee, t->mois, jours_du_mois(t->annee, t->mois));
  int passe = t->jour > dimanche || (t->jour == dimanche && t->heure >= 1);
  return t->mois == 3 ? passe : !passe;
}

/* l'horloge du PC est en temps universel (Smoky OS la laisse ainsi) : on affiche l'heure de Paris */
static int lire_heure(EFI_TIME *t) {
  if (!(noyau_actif ? noyau_heure(t) : !EFI_ERREUR(RT->lire_heure(t, 0)))) return 0;
  t->heure += heure_ete(t) ? 2 : 1;
  if (t->heure >= 24) {
    t->heure -= 24;
    if (++t->jour > jours_du_mois(t->annee, t->mois)) { t->jour = 1; if (++t->mois > 12) { t->mois = 1; t->annee++; } }
  }
  return 1;
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

static void abimer_heure(void) { abimer(L - 420 * U, 18 * U, 400 * U, 110 * U); }

static void dessiner_heure(void) {
  EFI_TIME t;
  if (!lire_heure(&t)) return;
  derniere_minute = t.minute;
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
}

/* --- La calculatrice -----------------------------------------------------------------------------
 * Priorités usuelles (puissance, puis × et ÷, puis + et −), parenthèses, virgule ou point, moins
 * devant un nombre, multiplication sous-entendue « 2(3+4) ». Calculs en double précision. */
static u32 calc_saisie[48];
static int calc_n, calc_fini;
static double calc_valeur;
static char calc_resultat[64];
static u32 calc_couleur = 0xf3f3f6;

static const u32 *ex;
static int ex_n, ex_i;
static const char *ex_erreur;

static int ex_voir(void) {
  while (ex_i < ex_n && ex[ex_i] == ' ') ex_i++;
  return ex_i < ex_n ? (int)ex[ex_i] : 0;
}
static double ex_somme(void);
static double ex_signe(void);

static double ex_nombre(void) {
  double v = 0, echelle = 0;
  int chiffres = 0;
  for (; ex_i < ex_n; ex_i++) {
    u32 c = ex[ex_i];
    if (c >= '0' && c <= '9') {
      if (echelle > 0) { v += (c - '0') * echelle; echelle /= 10; }
      else v = v * 10 + (c - '0');
      chiffres++;
    } else if ((c == ',' || c == '.') && echelle == 0) echelle = .1;
    else break;
  }
  if (!chiffres && !ex_erreur) ex_erreur = "nombre attendu";
  return v;
}

static double ex_facteur(void) {
  int c = ex_voir();
  if (c == '(') {
    ex_i++;
    double v = ex_somme();
    if (ex_voir() != ')') { if (!ex_erreur) ex_erreur = "parenthèse non fermée"; return 0; }
    ex_i++;
    return v;
  }
  if ((c >= '0' && c <= '9') || c == ',' || c == '.') return ex_nombre();
  if (!ex_erreur) ex_erreur = c ? "signe inattendu" : "calcul incomplet";
  return 0;
}

static double ex_puissance(void) {
  double b = ex_facteur();
  if (ex_voir() != '^') return b;
  ex_i++;
  double e = ex_signe();                                    /* 2^3^2 = 2^9, et 2^-1 = 0,5 */
  if (ex_erreur) return 0;
  long long n = (long long)e;
  if ((double)n != e || n > 1000 || n < -1000) { ex_erreur = "puissance entière (jusqu'à 1000) seulement"; return 0; }
  double r = 1;
  for (long long k = 0; k < (n < 0 ? -n : n); k++) r *= b;
  if (n < 0) {
    if (r == 0) { ex_erreur = "division par zéro"; return 0; }
    r = 1 / r;
  }
  return r;
}

static double ex_signe(void) {                              /* -2^2 = -4 */
  int c = ex_voir();
  if (c == '-') { ex_i++; return -ex_signe(); }
  if (c == '+') { ex_i++; return ex_signe(); }
  return ex_puissance();
}

static double ex_produit(void) {
  double v = ex_signe();
  while (!ex_erreur) {
    int c = ex_voir();
    if (c == 0xd7) { ex_i++; v *= ex_signe(); }
    else if (c == 0xf7) {
      ex_i++;
      double d = ex_signe();
      if (d == 0 && !ex_erreur) { ex_erreur = "division par zéro"; return 0; }
      v /= d;
    } else if (c == '(') v *= ex_signe();                   /* 2(3+4) */
    else break;
  }
  return v;
}

static double ex_somme(void) {
  double v = ex_produit();
  while (!ex_erreur) {
    int c = ex_voir();
    if (c == '+') { ex_i++; v += ex_produit(); }
    else if (c == '-') { ex_i++; v -= ex_produit(); }
    else break;
  }
  return v;
}

static int evaluer(const u32 *t, int n, double *v) {
  ex = t; ex_n = n; ex_i = 0; ex_erreur = 0;
  *v = ex_somme();
  if (!ex_erreur && ex_voir()) ex_erreur = ex[ex_i] == ')' ? "parenthèse en trop" : "signe inattendu";
  if (!ex_erreur && (*v != *v || *v > 1e300 || *v < -1e300)) ex_erreur = "résultat trop grand";
  return !ex_erreur;
}

/* nombre écrit à la française : 81,5 ; 0,3 (et pas 0,30000000000000004) ; 1,1529215046e18 */
static void formater(double v, char *d) {
  if (v < 0) { *d++ = '-'; v = -v; }
  if (v >= 1e15 || (v > 0 && v < 1e-9)) {
    int e = 0;
    while (v >= 10) { v /= 10; e++; }
    while (v < 1) { v *= 10; e--; }
    formater(v, d);
    copier(fin(d), e < 0 ? "e-" : "e");
    nombre_libre(fin(d), (u64)(e < 0 ? -e : e));
    return;
  }
  u64 entiere = (u64)v, decimales = (u64)((v - (double)entiere) * 1e10 + .5);
  if (decimales >= 10000000000ULL) { entiere++; decimales -= 10000000000ULL; }
  nombre_libre(d, entiere);
  if (decimales) {
    char f[12];
    for (int i = 9; i >= 0; i--) { f[i] = (char)('0' + decimales % 10); decimales /= 10; }
    f[10] = 0;
    for (int k = 9; k >= 0 && f[k] == '0'; k--) f[k] = 0;
    copier(fin(d), ",");
    copier(fin(d), f);
  }
}

static void calc_calculer(void) {
  double v;
  if (!calc_n) return;
  if (evaluer(calc_saisie, calc_n, &v)) {
    copier(calc_resultat, "= ");
    formater(v, fin(calc_resultat));
    calc_couleur = 0xf3f3f6;
    calc_valeur = v;
    calc_fini = 1;
  } else {
    copier(calc_resultat, ex_erreur);
    calc_couleur = 0xff8f85;
  }
}

static void calc_ajouter(u32 c) {
  if (c == '*' || c == 'x' || c == 'X') c = 0xd7;
  if (c == '/' || c == ':') c = 0xf7;
  if (c == '.') c = ',';
  if (calc_fini) {                                          /* après « = » : on continue avec le résultat, */
    calc_n = 0;                                             /* ou on repart de zéro avec un nombre */
    if (c == '+' || c == '-' || c == 0xd7 || c == 0xf7 || c == '^') {
      char r[48]; u32 t[48];
      formater(calc_valeur, r);
      int n = decoder(r, t, 40);
      for (int i = 0; i < n; i++) calc_saisie[calc_n++] = t[i];
    }
    calc_fini = 0;
  }
  if (calc_n < 46) calc_saisie[calc_n++] = c;
  calc_resultat[0] = 0;
}

static void abimer_affichage_calc(void) {
  abimer(FEN[F_CALC].x + 20 * U, FEN[F_CALC].y + 62 * U, FEN[F_CALC].w - 40 * U, 136 * U);
}

static void calc_touche(u32 c, int genre) {
  abimer_affichage_calc();
  if (genre == TOUCHE_ENTREE) calc_calculer();
  else if (genre == TOUCHE_EFFACER) { calc_fini = 0; if (calc_n) calc_n--; calc_resultat[0] = 0; }
  else if (genre == TOUCHE_SUPPR) { calc_n = 0; calc_fini = 0; calc_resultat[0] = 0; }
  else if (genre == TOUCHE_TEXTE) {
    if (c == '=') calc_calculer();
    else if ((c >= '0' && c <= '9') || c == '+' || c == '-' || c == '*' || c == '/' || c == ':' || c == 'x' ||
             c == 'X' || c == 0xd7 || c == 0xf7 || c == '(' || c == ')' || c == ',' || c == '.' || c == '^' || c == ' ')
      calc_ajouter(c);
  }
}

static const char *CALC_TOUCHES[20] = {"C", "(", ")", "÷", "7", "8", "9", "×", "4", "5", "6", "-",
                                       "1", "2", "3", "+", "0", ",", "←", "="};
static float calc_bw(void) { return (FEN[F_CALC].w - 78 * U) / 4; }
static float calc_bx(int k) { return FEN[F_CALC].x + 24 * U + (k % 4) * (calc_bw() + 10 * U); }
static float calc_by(int k) { return FEN[F_CALC].y + 214 * U + (k / 4) * 80 * U; }
#define CALC_BH (70 * U)

static void dessiner_calc(void) {
  float X = FEN[F_CALC].x, Y = FEN[F_CALC].y, W = FEN[F_CALC].w;
  bloc(X + 22 * U, Y + 64 * U, W - 44 * U, 132 * U, 16 * U, 0x1d1d21, .95f);
  float taille = 24 * U, avance = taille / 8 * 5.6f, lx = X + 40 * U;
  int place = (int)((W - 84 * U) / avance), debut = calc_n > place ? calc_n - place : 0;
  for (int k = debut; k < calc_n; k++)
    lx += signe(lx, Y + 112 * U, taille, .4f, calc_fini ? 0x8a8a94 : 0xf3f3f6, calc_saisie[k]);
  if (devant() == F_CALC && !calc_fini) bloc(lx + 2 * U, Y + 88 * U, 3 * U, 28 * U, 1.5f * U, 0xff8f85, 1);
  u32 t[64];
  int n = decoder(calc_resultat, t, 64);
  float tr = calc_couleur == 0xf3f3f6 ? 32 * U : 18 * U, lr = largeur(t, n, tr);
  ecrire(X + W - 42 * U - lr, Y + 172 * U, tr, .45f, calc_couleur, calc_resultat);
  for (int k = 0; k < 20; k++) {
    float bx = calc_bx(k), by = calc_by(k), bw = calc_bw(), tl = 26 * U;
    int egal = k == 19, operation = k % 4 == 3, rouge = k == 0 || k == 18;
    bloc(bx, by, bw, CALC_BH, 14 * U, egal ? 0xff8f85 : operation ? 0x2a2a31 : 0x1d1d21, 1);
    u32 l[4];
    int m = decoder(CALC_TOUCHES[k], l, 4);
    ecrire(bx + (bw - largeur(l, m, tl)) / 2, by + CALC_BH / 2 + .37f * tl, tl, .45f,
           egal ? 0x111113 : rouge ? 0xff8f85 : 0xf3f3f6, CALC_TOUCHES[k]);
  }
}

static void calc_clic(float px, float py) {
  for (int k = 0; k < 20; k++)
    if (dedans(px, py, calc_bx(k), calc_by(k), calc_bw(), CALC_BH)) {
      u32 l[4];
      decoder(CALC_TOUCHES[k], l, 4);
      if (k == 0) calc_touche(0, TOUCHE_SUPPR);
      else if (k == 18) calc_touche(0, TOUCHE_EFFACER);
      else if (k == 19) calc_touche(0, TOUCHE_ENTREE);
      else calc_touche(l[0], TOUCHE_TEXTE);
      return;
    }
}

/* --- Les notes : texte gardé tant que le PC est allumé (aucun pilote de disque) ---------------------- */
#define NOTES_MAX 6000
static u32 notes_texte[NOTES_MAX];
static int notes_n;

static int notes_debuts[NOTES_MAX + 1];
#define NOTES_TAILLE (21 * U)
#define NOTES_PAS (32 * U)

/* découpe en lignes (saut de ligne, ou bord droit) ; renvoie le nombre de lignes */
static int notes_lignes(void) {
  float avance = NOTES_TAILLE / 8 * 5.6f, espace = NOTES_TAILLE / 8 * 3.4f;
  float gauche = FEN[F_NOTES].x + 34 * U, droite = FEN[F_NOTES].x + FEN[F_NOTES].w - 34 * U, lx = gauche;
  int nb = 0;
  notes_debuts[nb++] = 0;
  for (int k = 0; k < notes_n; k++) {
    u32 c = notes_texte[k];
    if (c == '\n') { notes_debuts[nb++] = k + 1; lx = gauche; continue; }
    float a = c == ' ' ? espace : avance;
    if (lx + a > droite) { notes_debuts[nb++] = k; lx = gauche; }
    lx += a;
  }
  return nb;
}
static int notes_visibles(void) { return (int)((FEN[F_NOTES].h - 170 * U) / NOTES_PAS) + 1; }

static void notes_touche(u32 c, int genre) {
  int avant = notes_lignes();
  if (genre == TOUCHE_EFFACER) { if (notes_n) notes_n--; }
  else {
    if (genre == TOUCHE_TAB) { if (notes_n < NOTES_MAX) notes_texte[notes_n++] = ' '; c = ' '; }
    else if (genre == TOUCHE_ENTREE) c = '\n';
    else if (genre != TOUCHE_TEXTE) return;
    if (notes_n < NOTES_MAX) notes_texte[notes_n++] = c;
  }
  int apres = notes_lignes(), vis = notes_visibles();
  float X = FEN[F_NOTES].x, Y = FEN[F_NOTES].y;
  if (apres != avant || notes_n <= 1)                       /* les lignes bougent : tout le texte */
    abimer(X + 20 * U, Y + 60 * U, FEN[F_NOTES].w - 40 * U, FEN[F_NOTES].h - 100 * U);
  else {                                                     /* sinon la dernière ligne seulement */
    int ligne = apres - 1 - (apres > vis ? apres - vis : 0);
    abimer(X + 20 * U, Y + 94 * U + ligne * NOTES_PAS - 30 * U, FEN[F_NOTES].w - 40 * U, 42 * U);
  }
}

static void dessiner_notes(void) {
  float X = FEN[F_NOTES].x, Y = FEN[F_NOTES].y, Hn = FEN[F_NOTES].h;
  float taille = NOTES_TAILLE, pas = NOTES_PAS, gauche = X + 34 * U, haut = Y + 94 * U;
  int nb = notes_lignes(), visibles = notes_visibles();
  int *debuts = notes_debuts;
  int premiere = nb > visibles ? nb - visibles : 0;
  float cx = gauche, cy = haut;
  for (int l = premiere; l < nb; l++) {
    int fin_ligne = l + 1 < nb ? debuts[l + 1] : notes_n;
    float x = gauche, y = haut + (l - premiere) * pas;
    for (int k = debuts[l]; k < fin_ligne && notes_texte[k] != '\n'; k++)
      x += signe(x, y, taille, .38f, 0xf3f3f6, notes_texte[k]);
    cx = x; cy = y;
  }
  if (!notes_n) ecrire(gauche + 12 * U, haut, taille, .38f, 0x55555e, "Écris ici.");
  if (devant() == F_NOTES) bloc(cx + 2 * U, cy - 22 * U, 3 * U, 26 * U, 1.5f * U, 0xff8f85, 1);
  ecrire(gauche, Y + Hn - 30 * U, 15 * U, .36f, 0x7c7c86,
         "Gardées tant que le PC est allumé : rien n'est écrit sur le disque.");
}

/* --- L'horloge : heure de Paris en grand, et un chronomètre -------------------------------------- */
static int chrono_marche;
static u64 chrono_depart, chrono_cumul;                     /* microsecondes */
static u64 chrono_us(void) { return chrono_cumul + (chrono_marche ? noyau_microsecondes() - chrono_depart : 0); }
static void chrono_basculer(void) {
  if (chrono_marche) chrono_cumul += noyau_microsecondes() - chrono_depart;
  else chrono_depart = noyau_microsecondes();
  chrono_marche = !chrono_marche;
}
static void chrono_zero(void) { chrono_cumul = 0; chrono_depart = noyau_microsecondes(); }

#define HB_W (170 * U)
#define HB_H (58 * U)
static float horloge_bx(int k) { return FEN[F_HORLOGE].x + (FEN[F_HORLOGE].w - 360 * U) / 2 + k * 190 * U; }
static float horloge_by(void) { return FEN[F_HORLOGE].y + FEN[F_HORLOGE].h - 92 * U; }
static void abimer_chrono(void) { abimer(FEN[F_HORLOGE].x + 20 * U, FEN[F_HORLOGE].y + 236 * U, FEN[F_HORLOGE].w - 40 * U, 76 * U); }

static void centrer(float y, float taille, float graisse, u32 coul, const char *t) {
  u32 tmp[80];
  float l = largeur(tmp, decoder(t, tmp, 80), taille);
  ecrire(FEN[F_HORLOGE].x + (FEN[F_HORLOGE].w - l) / 2, y, taille, graisse, coul, t);
}

static void dessiner_horloge(void) {
  float Y = FEN[F_HORLOGE].y;
  EFI_TIME t;
  char d[80], x[24];
  if (lire_heure(&t)) {
    nombre(d, t.heure, 2); d[2] = ':'; nombre(d + 3, t.minute, 2); d[5] = ':'; nombre(d + 6, t.seconde, 2);
    centrer(Y + 168 * U, 72 * U, .5f, 0xf3f3f6, d);
    copier(d, JOURS[jour_semaine(t.annee, t.mois, t.jour)]); copier(fin(d), " ");
    nombre_libre(x, t.jour); copier(fin(d), x); copier(fin(d), " "); copier(fin(d), MOIS[(t.mois + 11) % 12]);
    copier(fin(d), " "); nombre_libre(x, t.annee); copier(fin(d), x); copier(fin(d), ", heure de Paris");
    centrer(Y + 212 * U, 17 * U, .4f, 0xb6b7c2, d);
  }
  u64 ds = chrono_us() / 100000;                            /* dixièmes de seconde */
  copier(d, "chrono  ");
  nombre(fin(d), (int)(ds / 600 % 100), 2); copier(fin(d), ":");
  nombre(fin(d), (int)(ds / 10 % 60), 2); copier(fin(d), ",");
  nombre(fin(d), (int)(ds % 10), 1);
  centrer(Y + 290 * U, 34 * U, .45f, chrono_marche ? 0xff8f85 : 0xb6b7c2, d);
  const char *etiquettes[2] = {chrono_marche ? "Arrêter" : "Démarrer", "Zéro"};
  for (int k = 0; k < 2; k++) {
    u32 tmp[16];
    float bx = horloge_bx(k), by = horloge_by(), tl = 20 * U;
    bloc(bx, by, HB_W, HB_H, 14 * U, k == 0 ? 0x2a2a31 : 0x1d1d21, 1);
    ecrire(bx + (HB_W - largeur(tmp, decoder(etiquettes[k], tmp, 16), tl)) / 2, by + HB_H / 2 + .37f * tl, tl, .42f,
           0xf3f3f6, etiquettes[k]);
  }
}

static void horloge_touche(u32 c, int genre) {
  if (genre == TOUCHE_TEXTE && c == ' ') chrono_basculer();
  else if (genre == TOUCHE_EFFACER || genre == TOUCHE_SUPPR) chrono_zero();
}
static void horloge_clic(float px, float py) {
  if (dedans(px, py, horloge_bx(0), horloge_by(), HB_W, HB_H)) chrono_basculer();
  else if (dedans(px, py, horloge_bx(1), horloge_by(), HB_W, HB_H)) chrono_zero();
}

/* --- Composition : fond, heure, puis fenêtres de la plus lointaine à celle de devant ----------------- */
static int curseur_abime;
static void rafraichir(void) {
  if (rien_a_refaire) return;
  ZX0 = AX0; ZY0 = AY0; ZX1 = AX1; ZY1 = AY1;
  restaurer(ZX0, ZY0, ZX1 - ZX0, ZY1 - ZY0);
  dessiner_heure();
  for (int i = 0; i < nb_pile; i++) {
    int f = pile[i];
    if (FEN[f].x > AX1 || FEN[f].y > AY1 || FEN[f].x + FEN[f].w < AX0 || FEN[f].y + FEN[f].h < AY0) continue;
    /* rien ne déborde de la fenêtre : zone ∩ fenêtre */
    ZX0 = AX0 > entier(FEN[f].x) ? AX0 : entier(FEN[f].x);
    ZY0 = AY0 > entier(FEN[f].y) ? AY0 : entier(FEN[f].y);
    ZX1 = AX1 < entier(FEN[f].x + FEN[f].w) + 2 ? AX1 : entier(FEN[f].x + FEN[f].w) + 2;
    ZY1 = AY1 < entier(FEN[f].y + FEN[f].h) + 2 ? AY1 : entier(FEN[f].y + FEN[f].h) + 2;
    cadre(f);
    if (f == F_CARNET) dessiner_carnet();
    else if (f == F_CALC) dessiner_calc();
    else if (f == F_NOTES) dessiner_notes();
    else dessiner_horloge();
  }
  montrer(AX0, AY0, AX1 - AX0, AY1 - AY0);
  ZX0 = ZY0 = 0; ZX1 = ZY1 = 1 << 30;
  rien_a_refaire = 1;
  curseur_abime = 1;
}

/* --- La souris : flèche dessinée par-dessus l'écran (l'image en dessous reste intacte) ---------------- */
static const char *FLECHE[17] = {
  "X          ", "XX         ", "X.X        ", "X..X       ", "X...X      ", "X....X     ", "X.....X    ",
  "X......X   ", "X.......X  ", "X........X ", "X.....XXXXX", "X..X..X    ", "X.X X..X   ", "XX  X..X   ",
  "X    X..X  ", "     X..X  ", "      XX   "};
static float souris_x, souris_y, prise_x, prise_y;
static int souris_vue, curseur_x = -1000, curseur_y, boutons_avant, deplace = -1, ECH = 1;

static void effacer_curseur(void) {
  if (curseur_x > -1000) montrer(curseur_x, curseur_y, 12 * ECH, 18 * ECH);   /* l'image est à jour */
  curseur_x = -1000;
}

static void dessiner_curseur(void) {
  effacer_curseur();
  curseur_x = (int)souris_x; curseur_y = (int)souris_y;
  for (int j = 0; j < 17; j++)
    for (int i = 0; FLECHE[j][i]; i++) {
      if (FLECHE[j][i] == ' ') continue;
      u32 c = FLECHE[j][i] == 'X' ? 0x0a0a0c : 0xf3f3f6;
      u32 e = BVR ? c : ((c & 0xff) << 16 | (c & 0xff00) | (c >> 16 & 0xff));
      for (int b = 0; b < ECH; b++)
        for (int a = 0; a < ECH; a++) {
          int px = curseur_x + i * ECH + a, py = curseur_y + j * ECH + b;
          if (px >= 0 && py >= 0 && px < L && py < H) ecran[py * PAS + px] = e;
        }
    }
  curseur_abime = 0;
}

static void souris_bouger(int dx, int dy) {
  souris_x = bornes(souris_x + dx, 0, L - 1);
  souris_y = bornes(souris_y + dy, 0, H - 1);
  if (deplace < 0) return;
  abimer_fenetre(deplace);                                  /* fenêtre tenue par sa barre de titre */
  FEN[deplace].x = bornes(souris_x - prise_x, 80 * U - FEN[deplace].w, L - 80 * U);
  FEN[deplace].y = bornes(souris_y - prise_y, 0, H - 60 * U);
  abimer_fenetre(deplace);
}

static void souris_appui(void) {
  for (int i = nb_pile - 1; i >= 0; i--) {
    int f = pile[i];
    if (!dedans(souris_x, souris_y, FEN[f].x, FEN[f].y, FEN[f].w, FEN[f].h)) continue;
    if (devant() != f) mettre_devant(f);
    if (f != F_CARNET && dedans(souris_x, souris_y, bouton_fermer_x(f), bouton_fermer_y(f), 30 * U, 30 * U)) fermer(f);
    else if (souris_y < FEN[f].y + 60 * U) { deplace = f; prise_x = souris_x - FEN[f].x; prise_y = souris_y - FEN[f].y; }
    else if (f == F_CALC) calc_clic(souris_x, souris_y);
    else if (f == F_HORLOGE) { horloge_clic(souris_x, souris_y); abimer_fenetre(f); }
    return;
  }
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
    noter("usb         les appareils USB branchés", 0xb6b7c2);
    noter("bilan       tout ce que Smoky OS voit du PC, pour une photo", 0xb6b7c2);
    noter("calculatrice, notes, horloge   ouvrent leur fenêtre", 0xb6b7c2);
    noter("effacer     vide le carnet", 0xb6b7c2);
    noter("apropos     ce qu'est cet OS", 0xb6b7c2);
    noter("redemarrer, eteindre", 0xb6b7c2);
    noter("Échap ferme une fenêtre, Alt+Tab passe à la suivante.", 0x7c7c86);
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
    noter("interruptions, minuterie, claviers (AZERTY), souris, horloge et mémoire.", 0xb6b7c2);
    u64 secondes = noyau_tics() / TICS_PAR_SECONDE;
    copier(d, "Allumé depuis "); nombre_libre(x, secondes / 60); copier(fin(d), x); copier(fin(d), " min ");
    nombre_libre(x, secondes % 60); copier(fin(d), x); copier(fin(d), " s");
    noter(d, 0xb6b7c2);
    copier(d, "Interruptions : minuterie "); nombre_libre(x, noyau_interruptions(0)); copier(fin(d), x);
    copier(fin(d), ", clavier "); nombre_libre(x, noyau_interruptions(1)); copier(fin(d), x);
    noter(d, 0xb6b7c2);
    copier(d, "Minuterie : "); copier(fin(d), noyau_minuterie()); noter(d, 0xb6b7c2);
    u64 mhz = noyau_frequence_tsc() / 1000000;
    copier(d, "Compteur du processeur : "); nombre_libre(x, mhz); copier(fin(d), x);
    copier(fin(d), " MHz (mesuré par : "); copier(fin(d), noyau_calibrage()); copier(fin(d), ")");
    noter(d, 0xb6b7c2);
  } else if (egal(s, n, "usb")) {
    char d[96]; usb_etat(d, sizeof d); noter(d, 0xf3f3f6);
    int n = 0;
    for (; n < 10 && usb_decrire(n, d, sizeof d); n++) {
      noter(d, 0xb6b7c2);
      if (usb_interfaces(n, d, sizeof d)) noter(d, 0x7c7c86);
    }
    if (!n) noter("Aucun appareil USB branché.", 0xb6b7c2);
    noter("Pilote maison : xHCI, hubs USB 2, claviers, souris, pavés et tablettes.", 0x7c7c86);
  } else if (egal(s, n, "bilan")) {
    char d[120], x[24];
    nb_lignes = 0;                                        /* le carnet entier, pour une seule photo */
    noter("Bilan de ce PC par Smoky OS 100 % maison 0.6", 0xf3f3f6);
    copier(d, "Processeur : "); noyau_processeur(fin(d), 64); noter(d, 0xb6b7c2);
    copier(d, "Compteur du processeur : "); nombre_libre(x, noyau_frequence_tsc() / 1000000); copier(fin(d), x);
    copier(fin(d), " MHz (mesuré par : "); copier(fin(d), noyau_calibrage()); copier(fin(d), ")");
    noter(d, 0xb6b7c2);
    copier(d, "Minuterie : "); copier(fin(d), noyau_minuterie()); noter(d, 0xb6b7c2);
    memoire(d); noter(d, 0xb6b7c2);
    copier(d, "Écran : "); nombre(x, L, L >= 1000 ? 4 : 3); copier(fin(d), x); copier(fin(d), " × ");
    nombre(x, H, H >= 1000 ? 4 : 3); copier(fin(d), x); copier(fin(d), BVR ? " (BVR)" : " (RVB)");
    noter(d, 0xb6b7c2);
    noter(noyau_clavier_ps2() ? "Clavier PS/2 : contrôleur présent" : "Clavier PS/2 : absent (normal sur un PC récent)", 0xb6b7c2);
    usb_etat(d, sizeof d); noter(d, 0xf3f3f6);
    for (int k = 0; k < 10 && usb_decrire(k, d, sizeof d); k++) {
      noter(d, 0xb6b7c2);
      if (usb_interfaces(k, d, sizeof d)) noter(d, 0x7c7c86);
    }
  } else if (egal(s, n, "calculatrice") || egal(s, n, "calc")) {
    ouvrir(F_CALC);
  } else if (egal(s, n, "notes")) {
    ouvrir(F_NOTES);
  } else if (egal(s, n, "horloge") || egal(s, n, "chrono")) {
    ouvrir(F_HORLOGE);
  } else if (egal(s, n, "effacer")) {
    nb_lignes = 0;
  } else if (egal(s, n, "apropos") || egal(s, n, "à-propos")) {
    noter("Smoky OS 100 % maison 0.6 : écrit de zéro, sans Linux ni bibliothèque.", 0xf3f3f6);
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
  ecrire(x + 12 * U, 74 * U, 17 * U, .4f, 0x7c7c86, "0.6");
  ecrire(44 * U, 108 * U, 17 * U, .4f, 0xb6b7c2, "100 % maison, écrit de zéro");
  ecrire(44 * U, H - 40 * U, 15 * U, .38f, 0x7c7c86,
         "Aucun pilote de disque : ton Windows et ton Smoky OS de tous les jours ne peuvent pas être touchés.");
  memcpy(fond, image, (UINTN)L * H * 4);
  montrer(0, 0, L, H);
  FEN[F_CARNET].w = 1080 * U; FEN[F_CARNET].h = 760 * U;
  FEN[F_CARNET].x = (L - FEN[F_CARNET].w) / 2; FEN[F_CARNET].y = 170 * U;
  if (FEN[F_CARNET].w > L - 40) { FEN[F_CARNET].w = L - 40; FEN[F_CARNET].x = 20; }
  FEN[F_CALC].w = 440 * U; FEN[F_CALC].h = 650 * U;
  FEN[F_CALC].x = bornes(FEN[F_CARNET].x + FEN[F_CARNET].w - 300 * U, 20, L - FEN[F_CALC].w - 20); FEN[F_CALC].y = 220 * U;
  FEN[F_NOTES].w = 720 * U; FEN[F_NOTES].h = 560 * U;
  FEN[F_NOTES].x = bornes(FEN[F_CARNET].x - 60 * U, 20, L - FEN[F_NOTES].w - 20); FEN[F_NOTES].y = 250 * U;
  FEN[F_HORLOGE].w = 520 * U; FEN[F_HORLOGE].h = 420 * U;
  FEN[F_HORLOGE].x = (L - FEN[F_HORLOGE].w) / 2; FEN[F_HORLOGE].y = 300 * U;
  souris_x = L / 2.0f; souris_y = H / 2.0f;
  ECH = (int)(U * 1.6f + .5f) < 1 ? 1 : (int)(U * 1.6f + .5f);
  noter("Bonjour ! Smoky OS a démarré tout seul, sans Linux.", 0xf3f3f6);
  noter("Tape « aide » pour voir ce qu'il sait faire.", 0xb6b7c2);
  ouvrir(F_CARNET);
  abimer_heure();
  rafraichir();

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
    abimer_fenetre(F_CARNET);
    rafraichir();
    for (;;) __asm__ volatile("hlt");
  }
  noyau_demarrer(carte, taille, taille_desc);
  noter("Firmware congédié : Smoky OS tourne seul. Tape « systeme ».", 0xb6b7c2);
  abimer_fenetre(F_CARNET);
  rafraichir();
  usb_demarrer();                                         /* clavier USB (celui du Z13 en est un) */
  { char d[96]; usb_etat(d, sizeof d); noter(d, usb_claviers() ? 0xb6b7c2 : 0x7c7c86); }
  abimer_fenetre(F_CARNET);
  rafraichir();
  u64 derniere_seconde = 0, prochain_chrono = 0;
  for (;;) {
    noyau_attendre();                                       /* le processeur dort entre deux interruptions */
    u64 seconde = noyau_tics() / TICS_PAR_SECONDE;
    if (seconde != derniere_seconde) {
      derniere_seconde = seconde;
      EFI_TIME t;
      if (lire_heure(&t) && t.minute != derniere_minute) abimer_heure();
      if (FEN[F_HORLOGE].ouverte) abimer(FEN[F_HORLOGE].x + 20 * U, FEN[F_HORLOGE].y + 80 * U, FEN[F_HORLOGE].w - 40 * U, 150 * U);
    }
    if (FEN[F_HORLOGE].ouverte && chrono_marche && noyau_tics() >= prochain_chrono) {
      prochain_chrono = noyau_tics() + 5;                     /* le chrono : 10 fois par seconde */
      abimer_chrono();
    }
    u32 c; int genre;
    while (noyau_touche(&c, &genre)) {
      int f = devant();
      if (genre == TOUCHE_TAB && (noyau_modificateurs() & MOD_ALT)) { suivante(); continue; }
      if (genre == TOUCHE_ECHAP && f != F_CARNET) { fermer(f); continue; }
      if (f == F_CARNET) {
        if (genre == TOUCHE_ENTREE) { executer(); abimer_fenetre(F_CARNET); }
        else if (genre == TOUCHE_EFFACER) { if (nb_saisie) nb_saisie--; abimer_saisie_carnet(); }
        else if (genre == TOUCHE_ECHAP) { nb_saisie = 0; abimer_saisie_carnet(); }
        else if (genre == TOUCHE_TEXTE && nb_saisie < 90) { saisie[nb_saisie++] = c; abimer_saisie_carnet(); }
      } else if (f == F_CALC) calc_touche(c, genre);
      else if (f == F_NOTES) notes_touche(c, genre);
      else if (f == F_HORLOGE) { horloge_touche(c, genre); abimer_fenetre(F_HORLOGE); }
    }
    struct souris_evt ev;
    while (usb_souris(&ev)) {
      souris_vue = 1;
      if (ev.absolu) souris_bouger((int)(ev.x * (L - 1) / 65535.0f - souris_x), (int)(ev.y * (H - 1) / 65535.0f - souris_y));
      else souris_bouger(ev.dx, ev.dy);
      if ((ev.boutons & 1) && !(boutons_avant & 1)) souris_appui();
      if (!(ev.boutons & 1)) deplace = -1;
      boutons_avant = ev.boutons;
      curseur_abime = 1;
    }
    if (souris_vue && !usb_nb_souris()) { souris_vue = 0; deplace = -1; effacer_curseur(); }
    rafraichir();
    if (souris_vue && curseur_abime) dessiner_curseur();
  }
}

/* --- Écran d'erreur : le processeur a signalé une faute (appelé par le noyau, sans retour) --------- */
void noyau_panique(int vecteur, u64 code_erreur, u64 adresse) {
  static const char *NOMS[32] = {"division par zéro", "pas à pas", "NMI", "point d'arrêt", "dépassement",
    "hors limites", "instruction inconnue", "coprocesseur absent", "double faute", "", "segment d'état",
    "segment absent", "pile", "protection générale", "défaut de page", "", "calcul flottant",
    "alignement", "vérification machine", "calcul SIMD", "virtualisation", "contrôle de flux"};
  char d[160], x[24];
  ZX0 = ZY0 = 0; ZX1 = ZY1 = 1 << 30;                        /* tout l'écran, quelle que soit la zone en cours */
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
