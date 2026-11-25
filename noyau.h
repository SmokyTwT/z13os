/* Smoky OS 100 % maison — le noyau : ce qui fait tourner le PC une fois le firmware congédié.
 * Table des segments (GDT), table des interruptions (IDT), contrôleur d'interruptions (PIC 8259),
 * minuterie (PIT 8254), clavier PS/2 et USB (AZERTY, voir usb.c), horloge temps réel (CMOS), mémoire libre.
 * Tout est écrit ici : aucun pilote du firmware n'est plus utilisé après noyau_demarrer(). */
#pragma once
#include "uefi.h"

enum { TOUCHE_TEXTE = 0, TOUCHE_ENTREE, TOUCHE_EFFACER, TOUCHE_ECHAP, TOUCHE_TAB, TOUCHE_HAUT, TOUCHE_BAS,
       TOUCHE_GAUCHE, TOUCHE_DROITE, TOUCHE_SUPPR, TOUCHE_DEBUT, TOUCHE_FIN };
enum { MOD_CTRL = 1, MOD_ALT = 2, MOD_MAJ = 4 };   /* touches tenues, voir noyau_modificateurs() */

#define TICS_PAR_SECONDE 50

void noyau_demarrer(const EFI_MEMORY_DESCRIPTOR *carte, UINTN taille, UINTN taille_desc);
int noyau_touche(u32 *caractere, int *genre);     /* 1 si une touche attendait */
int noyau_modificateurs(void);                    /* Ctrl, Alt, Maj tenues au moment de la touche */
void noyau_pousser_code(u8 code);                 /* code de touche PS/2 (jeu 1) venu d'ailleurs (USB) */
u64 noyau_tics(void);                             /* 50 par seconde, comptés par le TSC */
u64 noyau_microsecondes(void);                    /* depuis le démarrage du noyau */
void noyau_journal(const char *texte);            /* port série COM1 (essais) */
void noyau_journal_nombre(const char *texte, u64 valeur, int base);
int noyau_mapper(u64 base, u64 taille);           /* registres d'un appareil rendus accessibles */
const char *noyau_minuterie(void);                /* quelle minuterie réveille le processeur */
const char *noyau_calibrage(void);                /* comment la fréquence du TSC a été trouvée */
u64 noyau_frequence_tsc(void);
void noyau_processeur(char *d, int max);          /* nom du processeur */
int noyau_clavier_ps2(void);                      /* 1 : un contrôleur de clavier PS/2 a répondu */
void noyau_attendre(void);                        /* dort jusqu'à la prochaine interruption */
int noyau_heure(EFI_TIME *t);                     /* horloge CMOS du PC (lue par Smoky OS) */
u64 noyau_memoire_totale(void);                   /* en octets */
u64 noyau_memoire_libre(void);
void *noyau_allouer_pages(u64 nombre);            /* pages de 4 Kio, jamais rendues (pour l'instant) */
u64 noyau_interruptions(int irq);
void noyau_redemarrer(void);                      /* par le contrôleur du clavier, sans le firmware */

/* fourni par l'interface : dessine l'écran d'erreur si le processeur signale une faute */
void noyau_panique(int vecteur, u64 code_erreur, u64 adresse);
