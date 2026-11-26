/* Smoky OS 100 % maison — USB : contrôleurs xHCI (USB 3, qui servent aussi l'USB 2 et 1.1) et
 * claviers USB en « protocole de démarrage » (boot protocol). Sur le ROG Flow Z13, le clavier
 * détachable est un clavier USB : sans ce pilote, l'OS ne recevrait aucune touche sur le vrai PC.
 * Les hubs USB 2 sont gérés (un clavier peut être branché derrière), ainsi que les pointeurs : souris,
 * pavés tactiles en mode souris, tablettes (format lu dans leur descripteur de rapport, hid.c), et le
 * pointeur d'un clavier qui en a un (pavé du clavier détachable, récepteur sans fil).
 * Les clés USB (stockage « bulk-only », commandes SCSI) se lisent et s'écrivent par secteurs de 512 octets.
 * Sans interruptions : l'anneau d'événements est relevé à chaque réveil (50 fois par seconde). */
#pragma once
#include "uefi.h"

int usb_demarrer(void);                  /* trouve et prépare les contrôleurs ; renvoie leur nombre */
void usb_sonder(void);                   /* relève les événements : touches, branchements */
void usb_etat(char *d, int max);         /* une ligne pour « systeme » / « usb » */
int usb_claviers(void);                  /* claviers USB prêts */
int usb_decrire(int n, char *d, int max); /* n-ième appareil en une ligne (port, genre, vitesse) ; 0 : fin */
struct souris_evt { int dx, dy, boutons, absolu, x, y; };   /* x, y : de 0 à 65535 si absolu */
int usb_souris(struct souris_evt *e);     /* prochain rapport d'un pointeur USB ; 0 : rien */
int usb_interfaces(int n, char *d, int max);   /* interfaces du n-ième appareil s'il en a plusieurs ; 0 : non */
int usb_nb_souris(void);
int usb_cles(void);                      /* clés USB prêtes */
u32 usb_cle_generation(void);            /* change à chaque clé prête ou retirée */
u64 usb_cle_secteurs(int n);             /* taille de la n-ième clé, en secteurs de 512 octets */
const char *usb_cle_nom(int n);          /* fabricant et modèle */
int usb_cle_lire(int n, u64 lba, u32 nb, void *dest);          /* nb ≤ 8 secteurs ; 1 si réussi */
int usb_cle_ecrire(int n, u64 lba, u32 nb, const void *src);
