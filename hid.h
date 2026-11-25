/* Smoky OS 100 % maison — descripteurs de rapport HID : souris, pavés tactiles, tablettes.
 *
 * Un appareil HID décrit lui-même le format de ses rapports (spécification « Device Class Definition
 * for HID 1.11 », chapitre 6.2.2). On y cherche un pointeur : une collection « souris » ou « pointeur »
 * (ou un pavé tactile) avec des boutons et des coordonnées X et Y, relatives (souris, pavé en mode
 * souris) ou absolues (tablette, écran tactile USB). Aucune dépendance au matériel : essayé seul. */
#pragma once
typedef unsigned char u8;                    /* mêmes types qu'uefi.h (C11 permet de les répéter) */
typedef unsigned short u16;
typedef unsigned int u32;
typedef int i32;
typedef long long i64;

struct champ_hid { u16 bit, taille; i32 min, max; u8 present, relatif; };

struct pointeur_hid {
  u8 id;                     /* numéro de rapport (0 : l'appareil n'en met pas) */
  u8 absolu;                 /* coordonnées absolues : tablette, écran tactile */
  u8 pave;                   /* le descripteur décrit aussi un pavé tactile */
  u8 nb_boutons;             /* 0 à 3 : gauche, droit, milieu */
  u16 bit_bouton[3];
  struct champ_hid x, y, molette;
};

/* 1 si le descripteur (n octets) décrit un pointeur utilisable */
int hid_pointeur(const volatile u8 *desc, int n, struct pointeur_hid *p);

/* lit un rapport de n octets : 1 s'il concerne ce pointeur. boutons : bit 0 gauche, 1 droit, 2 milieu ;
 * dx, dy : déplacement (relatif) ; x, y : position de 0 à 65535 (absolu) */
int hid_lire(const struct pointeur_hid *p, const volatile u8 *r, int n, int *boutons, int *dx, int *dy, int *x, int *y);
