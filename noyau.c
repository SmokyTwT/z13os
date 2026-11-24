/* Smoky OS 100 % maison — le noyau (voir noyau.h). Après noyau_demarrer(), plus aucun pilote du
 * firmware ne sert : Smoky OS gère seul les interruptions, la minuterie, le clavier et l'horloge.
 * Toujours aucun pilote de disque. */
#include "noyau.h"

/* --- Ports d'entrée-sortie ----------------------------------------------------------------- */
static void sortie(u16 port, u8 v) { __asm__ volatile("outb %0, %1" : : "a"(v), "Nd"(port)); }
static u8 entree(u16 port) { u8 v; __asm__ volatile("inb %1, %0" : "=a"(v) : "Nd"(port)); return v; }

/* --- Données partagées avec les routines d'interruption (écrites en assembleur plus bas) -------- */
volatile u64 tics;
volatile u64 compte_irq[2];
volatile u8 file_codes[256];
volatile u32 file_tete;
volatile u64 lapic_eoi;                 /* adresse « fin d'interruption » de l'APIC local, ou 0 */
static u32 file_queue;

/* Routines d'interruption : minuterie (IRQ 0), clavier (IRQ 1), défaut (toute autre interruption,
 * acquittée sans rien faire), fautes du processeur (0 à 31 → noyau_panique, sans retour). */
__asm__(
    ".text\n"
    ".globl isr_minuterie\n"
    "isr_minuterie:\n"
    "  pushq %rax\n"
    "  lock incq tics(%rip)\n"
    "  lock incq compte_irq(%rip)\n"
    "  movb $0x20, %al\n"
    "  outb %al, $0x20\n"
    "  popq %rax\n"
    "  iretq\n"
    ".globl isr_clavier\n"
    "isr_clavier:\n"
    "  pushq %rax\n"
    "  pushq %rcx\n"
    "  pushq %rdx\n"
    "  inb $0x60, %al\n"
    "  movl file_tete(%rip), %ecx\n"
    "  leaq file_codes(%rip), %rdx\n"
    "  movb %al, (%rdx,%rcx,1)\n"
    "  incl %ecx\n"
    "  andl $255, %ecx\n"
    "  movl %ecx, file_tete(%rip)\n"
    "  lock incq compte_irq+8(%rip)\n"
    "  movb $0x20, %al\n"
    "  outb %al, $0x20\n"
    "  popq %rdx\n"
    "  popq %rcx\n"
    "  popq %rax\n"
    "  iretq\n"
    ".globl isr_defaut\n"
    "isr_defaut:\n"
    "  pushq %rax\n"
    "  movb $0x20, %al\n"
    "  outb %al, $0xA0\n"
    "  outb %al, $0x20\n"
    "  movq lapic_eoi(%rip), %rax\n"
    "  testq %rax, %rax\n"
    "  jz 1f\n"
    "  movl $0, (%rax)\n"
    "1:\n"
    "  popq %rax\n"
    "  iretq\n"
    ".macro FAUTE n, code\n"
    ".globl faute_\\n\n"
    "faute_\\n:\n"
    "  .if \\code == 0\n"
    "  pushq $0\n"
    "  .endif\n"
    "  pushq $\\n\n"
    "  jmp faute_commune\n"
    ".endm\n"
    "FAUTE 0,0\n FAUTE 1,0\n FAUTE 2,0\n FAUTE 3,0\n FAUTE 4,0\n FAUTE 5,0\n FAUTE 6,0\n FAUTE 7,0\n"
    "FAUTE 8,1\n FAUTE 9,0\n FAUTE 10,1\n FAUTE 11,1\n FAUTE 12,1\n FAUTE 13,1\n FAUTE 14,1\n FAUTE 15,0\n"
    "FAUTE 16,0\n FAUTE 17,1\n FAUTE 18,0\n FAUTE 19,0\n FAUTE 20,0\n FAUTE 21,1\n FAUTE 22,0\n FAUTE 23,0\n"
    "FAUTE 24,0\n FAUTE 25,0\n FAUTE 26,0\n FAUTE 27,0\n FAUTE 28,0\n FAUTE 29,1\n FAUTE 30,1\n FAUTE 31,0\n"
    "faute_commune:\n"
    "  movq (%rsp), %rcx\n"         /* numéro de la faute (1er argument, convention UEFI/Windows) */
    "  movq 8(%rsp), %rdx\n"        /* code d'erreur */
    "  movq 16(%rsp), %r8\n"        /* adresse de l'instruction fautive */
    "  andq $-16, %rsp\n"
    "  subq $32, %rsp\n"
    "  call noyau_panique\n"
    "2:\n"
    "  cli\n"
    "  hlt\n"
    "  jmp 2b\n");

extern void isr_minuterie(void), isr_clavier(void), isr_defaut(void);
#define F(n) extern void faute_##n(void);
F(0) F(1) F(2) F(3) F(4) F(5) F(6) F(7) F(8) F(9) F(10) F(11) F(12) F(13) F(14) F(15)
F(16) F(17) F(18) F(19) F(20) F(21) F(22) F(23) F(24) F(25) F(26) F(27) F(28) F(29) F(30) F(31)
#undef F
static void (*const FAUTES[32])(void) = {
  faute_0, faute_1, faute_2, faute_3, faute_4, faute_5, faute_6, faute_7, faute_8, faute_9, faute_10,
  faute_11, faute_12, faute_13, faute_14, faute_15, faute_16, faute_17, faute_18, faute_19, faute_20,
  faute_21, faute_22, faute_23, faute_24, faute_25, faute_26, faute_27, faute_28, faute_29, faute_30, faute_31};

/* --- Segments et table des interruptions ----------------------------------------------------- */
static u64 GDT[3] = {0, 0x00AF9A000000FFFFULL, 0x00CF92000000FFFFULL};   /* nul, code 64 bits, données */
struct __attribute__((packed)) porte { u16 off0, selecteur; u8 ist, type; u16 off1; u32 off2, zero; };
static struct porte IDT[256];
struct __attribute__((packed)) registre_table { u16 limite; u64 base; };

static void poser(int v, void (*f)(void)) {
  u64 a = (u64)f;
  IDT[v] = (struct porte){(u16)a, 0x08, 0, 0x8E, (u16)(a >> 16), (u32)(a >> 32), 0};
}

static void charger_tables(void) {
  static struct registre_table gdtr, idtr;
  gdtr = (struct registre_table){sizeof GDT - 1, (u64)GDT};
  __asm__ volatile(
      "lgdt %0\n"
      "pushq $0x08\n"
      "leaq 1f(%%rip), %%rax\n"
      "pushq %%rax\n"
      "lretq\n"
      "1:\n"
      "movw $0x10, %%ax\n"
      "movw %%ax, %%ds\n"
      "movw %%ax, %%es\n"
      "movw %%ax, %%ss\n"
      "movw %%ax, %%fs\n"
      "movw %%ax, %%gs\n"
      : : "m"(gdtr) : "rax", "memory");
  for (int v = 0; v < 256; v++) poser(v, v < 32 ? FAUTES[v] : isr_defaut);
  poser(0x20, isr_minuterie);
  poser(0x21, isr_clavier);
  idtr = (struct registre_table){sizeof IDT - 1, (u64)IDT};
  __asm__ volatile("lidt %0" : : "m"(idtr) : "memory");
}

/* --- Contrôleur d'interruptions, minuterie, APIC ---------------------------------------------- */
static void preparer_pic(void) {
  sortie(0x20, 0x11); sortie(0xA0, 0x11);            /* initialisation */
  sortie(0x21, 0x20); sortie(0xA1, 0x28);            /* IRQ 0-7 → 0x20, 8-15 → 0x28 */
  sortie(0x21, 0x04); sortie(0xA1, 0x02);
  sortie(0x21, 0x01); sortie(0xA1, 0x01);
  sortie(0x21, 0xFC); sortie(0xA1, 0xFF);            /* seules la minuterie et le clavier passent */
}

static void preparer_minuterie(void) {
  u16 diviseur = (u16)(1193182 / TICS_PAR_SECONDE);   /* 50 réveils par seconde, pas plus */
  sortie(0x43, 0x36);
  sortie(0x40, (u8)diviseur);
  sortie(0x40, (u8)(diviseur >> 8));
}

static void reperer_apic(void) {
  u32 bas, haut;
  __asm__ volatile("rdmsr" : "=a"(bas), "=d"(haut) : "c"(0x1B));
  u64 msr = (u64)haut << 32 | bas;
  lapic_eoi = (msr & (1 << 11)) ? (msr & ~0xFFFULL) + 0xB0 : 0;  /* APIC actif : on saura l'acquitter */
}

/* --- Clavier PS/2 (contrôleur 8042), disposition AZERTY ------------------------------------------- */
static void attendre_ecriture(void) { for (int i = 0; i < 100000 && (entree(0x64) & 2); i++); }
static void attendre_lecture(void) { for (int i = 0; i < 100000 && !(entree(0x64) & 1); i++); }

static void preparer_clavier(void) {
  while (entree(0x64) & 1) entree(0x60);              /* vide ce qui traîne */
  attendre_ecriture(); sortie(0x64, 0x20);
  attendre_lecture();
  u8 config = entree(0x60);
  config = (u8)((config | 0x41) & ~0x10);             /* interruption du clavier, traduction, horloge active */
  attendre_ecriture(); sortie(0x64, 0x60);
  attendre_ecriture(); sortie(0x60, config);
  file_queue = file_tete;
}

static const u16 NORMAL[128] = {
  [0x02] = '&', [0x03] = 0xe9, [0x04] = '"', [0x05] = '\'', [0x06] = '(', [0x07] = '-', [0x08] = 0xe8,
  [0x09] = '_', [0x0A] = 0xe7, [0x0B] = 0xe0, [0x0C] = ')', [0x0D] = '=',
  [0x10] = 'a', [0x11] = 'z', [0x12] = 'e', [0x13] = 'r', [0x14] = 't', [0x15] = 'y', [0x16] = 'u',
  [0x17] = 'i', [0x18] = 'o', [0x19] = 'p', [0x1B] = '$',
  [0x1E] = 'q', [0x1F] = 's', [0x20] = 'd', [0x21] = 'f', [0x22] = 'g', [0x23] = 'h', [0x24] = 'j',
  [0x25] = 'k', [0x26] = 'l', [0x27] = 'm', [0x28] = 0xf9, [0x29] = 0xb2, [0x2B] = '*',
  [0x2C] = 'w', [0x2D] = 'x', [0x2E] = 'c', [0x2F] = 'v', [0x30] = 'b', [0x31] = 'n', [0x32] = ',',
  [0x33] = ';', [0x34] = ':', [0x35] = '!', [0x39] = ' ', [0x56] = '<',
};
static const u16 MAJUSCULE[128] = {
  [0x02] = '1', [0x03] = '2', [0x04] = '3', [0x05] = '4', [0x06] = '5', [0x07] = '6', [0x08] = '7',
  [0x09] = '8', [0x0A] = '9', [0x0B] = '0', [0x0C] = 0xb0, [0x0D] = '+', [0x1B] = 0xa3, [0x28] = '%',
  [0x29] = 0xb2, [0x2B] = 0xb5, [0x32] = '?', [0x33] = '.', [0x34] = '/', [0x35] = 0xa7, [0x39] = ' ',
  [0x56] = '>',
};
static const u16 ALTGR[128] = {
  [0x03] = '~', [0x04] = '#', [0x05] = '{', [0x06] = '[', [0x07] = '|', [0x08] = '`', [0x09] = '\\',
  [0x0A] = '^', [0x0B] = '@', [0x0C] = ']', [0x0D] = '}', [0x12] = 0x20ac,
};

static int maj, altgr, verrou_maj, etendu;
static u32 morte;                                      /* accent en attente (^ ou ¨) */

static u32 accentuer(u32 morte_, u32 c) {
  static const char voyelles[] = "aeiouAEIOU";
  static const u16 circonflexe[] = {0xe2, 0xea, 0xee, 0xf4, 0xfb, 0xc2, 0xca, 0xce, 0xd4, 0xdb};
  static const u16 trema[] = {0xe4, 0xeb, 0xef, 0xf6, 0xfc, 0xc4, 0xcb, 0xcf, 0xd6, 0xdc};
  for (int i = 0; voyelles[i]; i++)
    if ((u32)voyelles[i] == c) return morte_ == '^' ? circonflexe[i] : trema[i];
  return c == ' ' ? morte_ : c;
}

int noyau_touche(u32 *caractere, int *genre) {
  while (file_queue != file_tete) {
    u8 code = file_codes[file_queue];
    file_queue = (file_queue + 1) & 255;
    if (code == 0xE0) { etendu = 1; continue; }
    int relache = code & 0x80, touche = code & 0x7F, e = etendu;
    etendu = 0;
    if (touche == 0x2A || touche == 0x36) { maj = !relache; continue; }
    if (touche == 0x38) { if (e) altgr = !relache; continue; }
    if (touche == 0x1D) continue;
    if (relache) continue;
    if (touche == 0x3A) { verrou_maj = !verrou_maj; continue; }
    if (touche == 0x1C) { *genre = TOUCHE_ENTREE; *caractere = 0; return 1; }
    if (touche == 0x0E) { *genre = TOUCHE_EFFACER; *caractere = 0; return 1; }
    if (touche == 0x01) { *genre = TOUCHE_ECHAP; *caractere = 0; return 1; }
    if (e) continue;                                    /* flèches et autres : pas encore */
    if (touche == 0x1A && !altgr) { morte = maj ? 0xa8 : '^'; continue; }
    u32 c = altgr ? ALTGR[touche] : (maj && MAJUSCULE[touche]) ? MAJUSCULE[touche] : NORMAL[touche];
    if (!c) continue;
    if (c >= 'a' && c <= 'z' && (maj ^ verrou_maj)) c -= 32;
    if (morte) { c = accentuer(morte, c); morte = 0; }
    *genre = TOUCHE_TEXTE; *caractere = c;
    return 1;
  }
  return 0;
}

/* --- Horloge temps réel (puce CMOS du PC) -------------------------------------------------------- */
static u8 cmos(u8 r) { sortie(0x70, r); return entree(0x71); }

int noyau_heure(EFI_TIME *t) {
  u8 v[7], w[7];
  do {
    for (int i = 0; i < 100000 && (cmos(0x0A) & 0x80); i++);   /* attend la fin d'une mise à jour */
    u8 r[7] = {0x00, 0x02, 0x04, 0x07, 0x08, 0x09, 0x0B};
    for (int i = 0; i < 7; i++) v[i] = cmos(r[i]);
    for (int i = 0; i < 7; i++) w[i] = cmos(r[i]);
  } while (v[0] != w[0] || v[1] != w[1] || v[2] != w[2]);
  u8 format = v[6];
  int pm = !(format & 2) && (v[2] & 0x80);
  v[2] &= 0x7F;
  if (!(format & 4))                                    /* BCD → nombre */
    for (int i = 0; i < 6; i++) v[i] = (u8)((v[i] & 15) + (v[i] >> 4) * 10);
  if (!(format & 2)) v[2] = (u8)(v[2] % 12 + (pm ? 12 : 0));
  t->seconde = v[0]; t->minute = v[1]; t->heure = v[2]; t->jour = v[3]; t->mois = v[4];
  t->annee = (u16)(2000 + v[5]);
  return t->mois >= 1 && t->mois <= 12;
}

/* --- Mémoire --------------------------------------------------------------------------------- */
struct zone { u64 debut, pages; };
static struct zone LIBRE[128];
static int nb_libre;
static u64 total_pages, pages_prises;

void *noyau_allouer_pages(u64 nombre) {
  for (int i = 0; i < nb_libre; i++)
    if (LIBRE[i].pages >= nombre) {
      u64 a = LIBRE[i].debut;
      LIBRE[i].debut += nombre * 4096;
      LIBRE[i].pages -= nombre;
      pages_prises += nombre;
      return (void *)a;
    }
  return 0;
}

u64 noyau_memoire_totale(void) { return total_pages * 4096; }
u64 noyau_memoire_libre(void) {
  u64 p = 0;
  for (int i = 0; i < nb_libre; i++) p += LIBRE[i].pages;
  return p * 4096;
}
u64 noyau_tics(void) { return tics; }
u64 noyau_interruptions(int irq) { return irq >= 0 && irq < 2 ? compte_irq[irq] : 0; }
void noyau_attendre(void) { __asm__ volatile("sti\n hlt" : : : "memory"); }

void noyau_redemarrer(void) {
  attendre_ecriture();
  sortie(0x64, 0xFE);                                   /* impulsion de réinitialisation du 8042 */
  static struct registre_table vide = {0, 0};
  __asm__ volatile("lidt %0\n int3" : : "m"(vide));    /* sinon : triple faute, le PC redémarre */
}

void noyau_demarrer(const EFI_MEMORY_DESCRIPTOR *carte, UINTN taille, UINTN taille_desc) {
  __asm__ volatile("cli");
  for (UINTN o = 0; o < taille; o += taille_desc) {
    const EFI_MEMORY_DESCRIPTOR *m = (const EFI_MEMORY_DESCRIPTOR *)((const u8 *)carte + o);
    if (m->type >= EFI_MEMOIRE_CODE_CHARGEUR && m->type <= EFI_MEMOIRE_LIBRE) total_pages += m->nb_pages;
    /* seule la mémoire « libre » est reprise : la pile actuelle est dans la mémoire du firmware */
    if (m->type == EFI_MEMOIRE_LIBRE && m->debut_physique >= 0x100000 && nb_libre < 128)
      LIBRE[nb_libre++] = (struct zone){m->debut_physique, m->nb_pages};
  }
  charger_tables();
  reperer_apic();
  preparer_pic();
  preparer_minuterie();
  preparer_clavier();
  __asm__ volatile("sti");
}
