/* Smoky OS 100 % maison — USB : contrôleurs xHCI (USB 3, qui servent aussi l'USB 2 et 1.1) et
 * claviers USB en « protocole de démarrage » (boot protocol). Sur le ROG Flow Z13, le clavier
 * détachable est un clavier USB : sans ce pilote, l'OS ne recevrait aucune touche sur le vrai PC.
 * Sans interruptions : l'anneau d'événements est relevé à chaque réveil (50 fois par seconde). */
#pragma once
#include "uefi.h"

int usb_demarrer(void);                  /* trouve et prépare les contrôleurs ; renvoie leur nombre */
void usb_sonder(void);                   /* relève les événements : touches, branchements */
void usb_etat(char *d, int max);         /* une ligne pour « systeme » / « usb » */
int usb_claviers(void);                  /* claviers USB prêts */
