/* Smoky OS 100 % maison — le noyau : ce qui fait tourner le PC une fois le firmware congédié.
 * Table des segments (GDT), table des interruptions (IDT), contrôleur d'interruptions (PIC 8259),
 * minuterie (PIT 8254), clavier PS/2 (AZERTY), horloge temps réel (CMOS), mémoire libre.
 * Tout est écrit ici : aucun pilote du firmware n'est plus utilisé après noyau_demarrer(). */
#pragma once
#include "uefi.h"

enum { TOUCHE_TEXTE = 0, TOUCHE_ENTREE, TOUCHE_EFFACER, TOUCHE_ECHAP };

#define TICS_PAR_SECONDE 50

void noyau_demarrer(const EFI_MEMORY_DESCRIPTOR *carte, UINTN taille, UINTN taille_desc);
int noyau_touche(u32 *caractere, int *genre);     /* 1 si une touche attendait */
u64 noyau_tics(void);
void noyau_attendre(void);                        /* dort jusqu'à la prochaine interruption */
int noyau_heure(EFI_TIME *t);                     /* horloge CMOS du PC (lue par Smoky OS) */
u64 noyau_memoire_totale(void);                   /* en octets */
u64 noyau_memoire_libre(void);
void *noyau_allouer_pages(u64 nombre);            /* pages de 4 Kio, jamais rendues (pour l'instant) */
u64 noyau_interruptions(int irq);
void noyau_redemarrer(void);                      /* par le contrôleur du clavier, sans le firmware */

/* fourni par l'interface : dessine l'écran d'erreur si le processeur signale une faute */
void noyau_panique(int vecteur, u64 code_erreur, u64 adresse);
