/* Smoky OS 100 % maison — descripteurs de rapport HID (voir hid.h).
 *
 * Un descripteur est une suite d'éléments courts : un octet (taille, type, étiquette) puis 0, 1, 2 ou
 * 4 octets de valeur. Les éléments « globaux » (page d'usage, bornes, taille et nombre des champs,
 * numéro de rapport) restent valables jusqu'à nouvel ordre ; les « locaux » (usages) ne valent que pour
 * l'élément « principal » suivant (collection, entrée…). Chaque entrée ajoute nombre × taille bits au
 * rapport de son numéro. On garde les boutons 1 à 3, X, Y et la molette d'une collection d'application
 * « souris » ou « pointeur ». Un pavé tactile qui démarre en mode souris (c'est la règle) en a une. */
#include "hid.h"

#define U_SOURIS     0x00010002u
#define U_POINTEUR   0x00010001u
#define U_PAVE       0x000D0005u
#define U_X          0x00010030u
#define U_Y          0x00010031u
#define U_MOLETTE    0x00010038u
#define PAGE_BOUTONS 0x0009u

struct globaux { u32 page, taille, compte, lmax_brut; i32 lmin, lmax_signe; u8 id; };

int hid_pointeur(const volatile u8 *d, int n, struct pointeur_hid *p) {
  static u16 decalage[256];                  /* position suivante, en bits, dans chaque rapport */
  struct globaux g = {0, 0, 0, 0, 0, 0, 0}, pile[4];
  u32 usages[16], umin = 0, umax = 0;
  int nu = 0, plage = 0, profondeur = 0, appli = 0, nb_pile = 0;
  int id_xy = -1, id_boutons = -1, id_molette = -1;
  u8 *z = (u8 *)p;
  for (unsigned k = 0; k < sizeof *p; k++) z[k] = 0;
  for (int k = 0; k < 256; k++) decalage[k] = 0;
  for (int i = 0; i < n;) {
    u8 prefixe = d[i];
    if (prefixe == 0xFE) {                   /* élément long (réservé) : sauté */
      if (i + 1 >= n) break;
      i += 3 + d[i + 1];
      continue;
    }
    int t = prefixe & 3, sz = t == 3 ? 4 : t, type = (prefixe >> 2) & 3, tag = prefixe >> 4;
    if (i + 1 + sz > n) break;
    u32 v = 0;
    for (int k = 0; k < sz; k++) v |= (u32)d[i + 1 + k] << (8 * k);
    i32 sv = sz == 1 ? (i32)(signed char)v : sz == 2 ? (i32)(short)v : (i32)v;
    i += 1 + sz;
    if (type == 1) {                         /* globaux */
      if (tag == 0) g.page = v;
      else if (tag == 1) g.lmin = sv;
      else if (tag == 2) { g.lmax_signe = sv; g.lmax_brut = v; }
      else if (tag == 7) g.taille = v;
      else if (tag == 8) g.id = (u8)v;
      else if (tag == 9) g.compte = v;
      else if (tag == 10 && nb_pile < 4) pile[nb_pile++] = g;      /* PUSH */
      else if (tag == 11 && nb_pile > 0) g = pile[--nb_pile];      /* POP */
    } else if (type == 2) {                  /* locaux : usages (page incluse sur 4 octets) */
      u32 u = sz == 4 ? v : (g.page << 16 | v);
      if (tag == 0) { if (nu < 16) usages[nu++] = u; }
      else if (tag == 1) { umin = u; plage = 1; }
      else if (tag == 2) { umax = u; plage = 1; }
    } else if (type == 0) {                  /* principaux */
      if (tag == 10) {                       /* collection */
        if (profondeur == 0 && v == 1) {     /* d'application : laquelle ? */
          u32 u = nu ? usages[0] : 0;
          appli = u == U_SOURIS || u == U_POINTEUR ? 1 : u == U_PAVE ? 2 : 0;
          if (appli == 2) p->pave = 1;
        }
        profondeur++;
      } else if (tag == 12) {                /* fin de collection */
        if (profondeur > 0 && --profondeur == 0) appli = 0;
      } else if (tag == 8) {                 /* entrée */
        u32 debut = decalage[g.id];
        i32 lmax = g.lmin < 0 ? g.lmax_signe : (i32)g.lmax_brut;
        if (appli == 1 && !(v & 1) && (v & 2) && g.taille > 0 && g.taille <= 32) {   /* données variables */
          for (u32 k = 0; k < g.compte && k < 64; k++) {
            u32 u = plage ? (umin + k <= umax ? umin + k : umax) : nu ? usages[k < (u32)nu ? k : (u32)nu - 1] : 0;
            u32 bit = debut + k * g.taille;
            if ((u >> 16) == PAGE_BOUTONS && (u & 0xFFFF) >= 1 && (u & 0xFFFF) <= 3) {
              int b = (int)(u & 0xFFFF) - 1;
              if (id_boutons < 0 || id_boutons == g.id) {
                id_boutons = g.id;
                p->bit_bouton[b] = (u16)bit;
                if (b + 1 > p->nb_boutons) p->nb_boutons = (u8)(b + 1);
              }
              continue;
            }
            struct champ_hid *c = u == U_X ? &p->x : u == U_Y ? &p->y : u == U_MOLETTE ? &p->molette : 0;
            if (!c || c->present) continue;
            if (c == &p->molette) id_molette = g.id;
            else if (id_xy >= 0 && id_xy != g.id) continue;     /* X et Y dans le même rapport */
            else id_xy = g.id;
            c->present = 1; c->bit = (u16)bit; c->taille = (u16)g.taille;
            c->min = g.lmin; c->max = lmax; c->relatif = (v & 4) != 0;
          }
        }
        decalage[g.id] = (u16)(debut + g.compte * g.taille);
      }
      nu = 0;
      plage = 0;                             /* les locaux ne valent que pour cet élément */
    }
  }
  if (!p->x.present || !p->y.present || p->x.relatif != p->y.relatif) return 0;
  if (!p->x.relatif && (p->x.max <= p->x.min || p->y.max <= p->y.min)) return 0;
  if (id_boutons >= 0 && id_boutons != id_xy) p->nb_boutons = 0;       /* dans un autre rapport : ignorés */
  if (id_molette >= 0 && id_molette != id_xy) p->molette.present = 0;
  p->id = (u8)(id_xy > 0 ? id_xy : 0);
  p->absolu = !p->x.relatif;
  return 1;
}

static i32 champ(const volatile u8 *d, int n, const struct champ_hid *c) {
  u32 v = 0;
  for (u32 b = 0; b < c->taille; b++) {
    u32 bit = c->bit + b;
    if ((int)(bit >> 3) >= n) break;         /* rapport plus court que prévu */
    if ((d[bit >> 3] >> (bit & 7)) & 1) v |= 1u << b;
  }
  if (c->min < 0 && c->taille < 32 && ((v >> (c->taille - 1)) & 1)) v |= ~0u << c->taille;   /* signé */
  return (i32)v;
}

int hid_lire(const struct pointeur_hid *p, const volatile u8 *r, int n, int *boutons, int *dx, int *dy, int *x, int *y) {
  if (p->id) {
    if (n < 1 || r[0] != p->id) return 0;    /* un autre rapport du même appareil */
    r++;
    n--;
  }
  *boutons = 0;
  for (int b = 0; b < p->nb_boutons; b++) {
    u32 bit = p->bit_bouton[b];
    if ((int)(bit >> 3) < n && ((r[bit >> 3] >> (bit & 7)) & 1)) *boutons |= 1 << b;
  }
  i32 vx = champ(r, n, &p->x), vy = champ(r, n, &p->y);
  *dx = *dy = *x = *y = 0;
  if (p->absolu) {
    i64 ax = (i64)(vx - p->x.min) * 65535 / (p->x.max - p->x.min);
    i64 ay = (i64)(vy - p->y.min) * 65535 / (p->y.max - p->y.min);
    *x = (int)(ax < 0 ? 0 : ax > 65535 ? 65535 : ax);
    *y = (int)(ay < 0 ? 0 : ay > 65535 ? 65535 : ay);
  } else {
    *dx = vx;
    *dy = vy;
  }
  return 1;
}
