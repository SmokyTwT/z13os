/* Smoky OS 100 % maison — le noyau (voir noyau.h). Après noyau_demarrer(), plus aucun pilote du
 * firmware ne sert : Smoky OS gère seul les interruptions, la minuterie, le clavier et l'horloge.
 * Toujours aucun pilote de disque. */
#include "noyau.h"
#include "usb.h"

/* --- Ports d'entrée-sortie ----------------------------------------------------------------- */
static void sortie(u16 port, u8 v) { __asm__ volatile("outb %0, %1" : : "a"(v), "Nd"(port)); }
static u8 entree(u16 port) { u8 v; __asm__ volatile("inb %1, %0" : "=a"(v) : "Nd"(port)); return v; }

/* --- Données partagées avec les routines d'interruption (écrites en assembleur plus bas) -------- */
volatile u64 tics;
volatile u64 compte_irq[2];
volatile u8 file_codes[256];
volatile u32 file_tete;
volatile u64 lapic_eoi;                 /* adresse « fin d'interruption » de l'APIC local, ou 0 */
volatile u32 apic_x2;                   /* APIC local en mode x2APIC : on lui parle par MSR */
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
    ".globl isr_minuterie_apic\n"            /* minuterie de l'APIC local (PC récents) */
    "isr_minuterie_apic:\n"
    "  pushq %rax\n"
    "  pushq %rcx\n"
    "  pushq %rdx\n"
    "  lock incq tics(%rip)\n"
    "  lock incq compte_irq(%rip)\n"
    "  call fin_apic\n"
    "  popq %rdx\n"
    "  popq %rcx\n"
    "  popq %rax\n"
    "  iretq\n"
    ".globl isr_parasite\n"                  /* interruption parasite de l'APIC : jamais acquittée */
    "isr_parasite:\n"
    "  iretq\n"
    ".globl isr_defaut\n"
    "isr_defaut:\n"
    "  pushq %rax\n"
    "  pushq %rcx\n"
    "  pushq %rdx\n"
    "  movb $0x20, %al\n"
    "  outb %al, $0xA0\n"
    "  outb %al, $0x20\n"
    "  call fin_apic\n"
    "  popq %rdx\n"
    "  popq %rcx\n"
    "  popq %rax\n"
    "  iretq\n"
    "fin_apic:\n"                            /* « fin d'interruption » à l'APIC local, s'il est actif */
    "  cmpl $0, apic_x2(%rip)\n"
    "  je 1f\n"
    "  movl $0x80B, %ecx\n"
    "  xorl %eax, %eax\n"
    "  xorl %edx, %edx\n"
    "  wrmsr\n"
    "  ret\n"
    "1:\n"
    "  movq lapic_eoi(%rip), %rax\n"
    "  testq %rax, %rax\n"
    "  jz 2f\n"
    "  movl $0, (%rax)\n"
    "2:\n"
    "  ret\n"
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
    "3:\n"
    "  cli\n"
    "  hlt\n"
    "  jmp 3b\n");

extern void isr_minuterie(void), isr_minuterie_apic(void), isr_clavier(void), isr_defaut(void), isr_parasite(void);
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
  poser(0xFF, isr_parasite);
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

static void cpuid(u32 f, u32 *a, u32 *b, u32 *c, u32 *d) {
  __asm__ volatile("cpuid" : "=a"(*a), "=b"(*b), "=c"(*c), "=d"(*d) : "a"(f), "c"(0));
}
static u64 lire_msr(u32 n) { u32 b, h; __asm__ volatile("rdmsr" : "=a"(b), "=d"(h) : "c"(n)); return (u64)h << 32 | b; }
static void ecrire_msr(u32 n, u64 v) { __asm__ volatile("wrmsr" : : "c"(n), "a"((u32)v), "d"((u32)(v >> 32))); }
static u64 apic_base;

static void reperer_apic(void) {
  u32 a, b, c, d;
  cpuid(1, &a, &b, &c, &d);
  if (!(d & (1 << 9))) return;                          /* processeur sans APIC local */
  u64 msr = lire_msr(0x1B);
  if (!(msr & (1 << 11))) return;                       /* APIC local coupé */
  apic_x2 = (msr >> 10) & 1;
  apic_base = msr & 0x000FFFFFFFFFF000ULL;
  if (!apic_x2 && !noyau_mapper(apic_base, 0x1000)) { apic_base = 0; return; }
  lapic_eoi = apic_x2 ? 0 : apic_base + 0xB0;          /* on saura l'acquitter */
}

static u32 apic_lire(u32 r) { return apic_x2 ? (u32)lire_msr(0x800 + r / 16) : *(volatile u32 *)(apic_base + r); }
static void apic_ecrire(u32 r, u32 v) {
  if (apic_x2) ecrire_msr(0x800 + r / 16, v); else *(volatile u32 *)(apic_base + r) = v;
}

/* --- Clavier PS/2 (contrôleur 8042), disposition AZERTY ------------------------------------------- */
static void attendre_ecriture(void) { for (int i = 0; i < 100000 && (entree(0x64) & 2); i++); }
static void attendre_lecture(void) { for (int i = 0; i < 100000 && !(entree(0x64) & 1); i++); }

static int ps2_present;
int noyau_clavier_ps2(void) { return ps2_present; }

static void preparer_clavier(void) {
  file_queue = file_tete;
  if (entree(0x64) == 0xFF) return;                    /* pas de contrôleur 8042 : PC récent, clavier USB */
  ps2_present = 1;
  for (int i = 0; i < 256 && (entree(0x64) & 1); i++) entree(0x60);   /* vide ce qui traîne */
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

void noyau_pousser_code(u8 code) {
  u64 drapeaux;
  __asm__ volatile("pushfq\n popq %0\n cli" : "=r"(drapeaux) : : "memory");   /* la routine du clavier PS/2 écrit aussi */
  file_codes[file_tete] = code;
  file_tete = (file_tete + 1) & 255;
  if (drapeaux & 0x200) __asm__ volatile("sti" : : : "memory");
}

int noyau_touche(u32 *caractere, int *genre) {
  usb_sonder();                                         /* touches des claviers USB */
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

/* --- Journal série (COM1) : lu dans les essais QEMU, sans effet sur un PC qui n'en a pas ---------- */
void noyau_journal(const char *t) {
  for (; *t; t++) {
    for (int i = 0; i < 10000 && !(entree(0x3FD) & 0x20); i++) __asm__ volatile("pause");
    sortie(0x3F8, (u8)*t);
  }
}
void noyau_journal_nombre(const char *t, u64 v, int base) {
  char d[24]; int n = 0;
  noyau_journal(t);
  do { d[n++] = "0123456789abcdef"[v % base]; v /= base; } while (v && n < 22);
  char r[24]; for (int i = 0; i < n; i++) r[i] = d[n - 1 - i]; r[n] = 0;
  noyau_journal(r);
}

/* --- Correspondance mémoire des registres (MMIO) ---------------------------------------------------
 * Le firmware fait correspondre adresses virtuelles et physiques ; on vérifie que des registres y
 * sont, sinon on les ajoute en pages de 2 Mio non mises en cache. */
static u64 *page_vide(void) {
  u64 *p = noyau_allouer_pages(1);
  if (p) for (int i = 0; i < 512; i++) p[i] = 0;
  return p;
}
int noyau_mapper(u64 base, u64 taille) {
  u64 cr3, cr0;
  __asm__ volatile("mov %%cr3, %0" : "=r"(cr3));
  for (u64 a = base & ~0x1FFFFFULL; a < base + taille; a += 0x200000) {
    u64 *pml4 = (u64 *)(cr3 & 0x000FFFFFFFFFF000ULL);
    u64 *e = &pml4[(a >> 39) & 511];
    __asm__ volatile("mov %%cr0, %0" : "=r"(cr0));
    __asm__ volatile("mov %0, %%cr0" : : "r"(cr0 & ~(1ULL << 16)));   /* tables peut-être en lecture seule */
    int ok = 1;
    for (int niveau = 0; niveau < 2 && ok; niveau++) {                 /* PML4 → PDPT → PD */
      if (!(*e & 1)) {
        u64 *t = page_vide();
        if (!t) { ok = 0; break; }
        *e = (u64)t | 3;
      }
      if (niveau == 1 && (*e & 0x80)) break;                           /* page de 1 Gio : déjà là */
      u64 *table = (u64 *)(*e & 0x000FFFFFFFFFF000ULL);
      e = &table[(a >> (niveau == 0 ? 30 : 21)) & 511];
      if (niveau == 1 && !(*e & 1)) *e = a | 0x80 | 0x10 | 0x8 | 3;      /* 2 Mio, PCD|PWT, écriture */
    }
    __asm__ volatile("mov %0, %%cr0" : : "r"(cr0));
    if (!ok) return 0;
  }
  __asm__ volatile("mov %%cr3, %%rax\n mov %%rax, %%cr3" : : : "rax", "memory");
  return 1;
}

/* --- Le temps : compteur du processeur (TSC) et minuterie ----------------------------------------
 * Le temps vient du TSC, une fois sa fréquence connue : il ne dépend d'aucune interruption. Les
 * interruptions de la minuterie servent seulement à réveiller le processeur. Sur les PC récents,
 * l'ancienne minuterie (PIT 8254) peut être arrêtée par le firmware : on prend alors celle de
 * l'APIC local, et si aucune ne bat, le processeur ne dort plus (il relève tout en boucle). */
static u64 tsc_hz, tsc_depart;
static int minuterie;                                   /* 0 : aucune, 1 : PIT, 2 : APIC local */
static const char *calibrage = "?";

static u64 tsc(void) { u32 b, h; __asm__ volatile("rdtsc" : "=a"(b), "=d"(h)); return (u64)h << 32 | b; }
static u64 plausible(u64 hz) { return hz >= 200000000ULL && hz <= 10000000000ULL ? hz : 0; }  /* 0,2 à 10 GHz */
static u32 cpuid_max(void) { u32 max, b, c, d; cpuid(0, &max, &b, &c, &d); return max; }

static u64 calibrer_par_cpuid15(void) {                 /* Intel récents : fréquence exacte du quartz */
  u32 a, b, c, d;
  if (cpuid_max() < 0x15) return 0;
  cpuid(0x15, &a, &b, &c, &d);
  return a && b && c ? plausible((u64)c * b / a) : 0;
}

static u64 calibrer_par_cpuid16(void) {                 /* fréquence de base annoncée (à 0,5 % près) */
  u32 a, b, c, d;
  if (cpuid_max() < 0x16) return 0;
  cpuid(0x16, &a, &b, &c, &d);
  return plausible((u64)(a & 0xFFFF) * 1000000ULL);
}

static u64 calibrer_par_pit(void) {                     /* voie 2 du PIT : 10 ms comptées par le TSC */
  u8 v = entree(0x61);
  if (v == 0xFF) return 0;                              /* rien ne répond au port 0x61 */
  sortie(0x61, (u8)((v & ~0x02) | 0x01));               /* porte ouverte, haut-parleur coupé */
  sortie(0x43, 0xB0);                                   /* voie 2, mode 0 : sortie basse, haute à la fin */
  sortie(0x42, 11932 & 0xFF);
  sortie(0x42, 11932 >> 8);
  if (entree(0x61) & 0x20) return 0;                    /* déjà haute : le PIT ne compte pas */
  u64 t0 = tsc();
  while (!(entree(0x61) & 0x20))
    if (tsc() - t0 > 400000000ULL) return 0;            /* toujours rien : PIT arrêté */
  return plausible((tsc() - t0) * 100);
}

static u64 calibrer_par_rtc(void) {                     /* une seconde de l'horloge CMOS */
  u64 n = 0, t0 = 0;
  for (int tour = 0; tour < 2; tour++) {
    while (!(cmos(0x0A) & 0x80)) if (++n > 30000000) return 0;   /* mise à jour qui commence… */
    while (cmos(0x0A) & 0x80) if (++n > 30000000) return 0;      /* …et finit : nouvelle seconde */
    if (!tour) t0 = tsc();
  }
  return plausible(tsc() - t0);
}

static void calibrer_tsc(void) {
  tsc_depart = tsc();
  if ((tsc_hz = calibrer_par_cpuid15())) calibrage = "processeur";
  else if ((tsc_hz = calibrer_par_pit())) calibrage = "PIT";
  else if ((tsc_hz = calibrer_par_cpuid16())) calibrage = "fréquence de base du processeur";
  else if ((tsc_hz = calibrer_par_rtc())) calibrage = "horloge CMOS";
  else { tsc_hz = 2000000000ULL; calibrage = "rien : 2 GHz supposés"; }
}

u64 noyau_microsecondes(void) {
  if (!tsc_hz) return 0;
  u64 t = tsc() - tsc_depart;
  return t / tsc_hz * 1000000ULL + t % tsc_hz * 1000000ULL / tsc_hz;
}

static void attendre_us(u64 us) { u64 f = noyau_microsecondes() + us; while (noyau_microsecondes() < f) __asm__ volatile("pause"); }

static int preparer_minuterie_apic(void) {
  if (!apic_base && !apic_x2) return 0;
  apic_ecrire(0xF0, apic_lire(0xF0) | 0x100 | 0xFF);  /* APIC en marche, interruptions parasites → 0xFF */
  apic_ecrire(0x80, 0);                                 /* priorité 0 : toutes les interruptions passent */
  apic_ecrire(0x3E0, 3);                                /* diviseur 16 */
  apic_ecrire(0x320, 0x20 | (1 << 16));                 /* minuterie masquée le temps de la mesurer */
  apic_ecrire(0x380, 0xFFFFFFFF);
  attendre_us(10000);
  u32 ecoule = 0xFFFFFFFF - apic_lire(0x390);
  apic_ecrire(0x380, 0);
  if (ecoule < 100) return 0;
  apic_ecrire(0x320, 0x20 | (1 << 17));                 /* périodique, vecteur 0x20 */
  apic_ecrire(0x380, ecoule * 2);                       /* 20 ms : 50 réveils par seconde */
  return 1;
}

static int minuterie_bat(void) {
  u64 avant = compte_irq[0];
  attendre_us(100000);
  return compte_irq[0] >= avant + 2;
}

static void journaliser_temps(void) {
  noyau_journal_nombre("noyau : compteur du processeur ", tsc_hz / 1000000, 10);
  noyau_journal(" MHz (mesuré par : "); noyau_journal(calibrage); noyau_journal(")\n");
  noyau_journal("noyau : minuterie "); noyau_journal(minuterie == 2 ? "APIC locale" : minuterie == 1 ? "PIT" : "aucune");
  noyau_journal(apic_x2 ? " (x2APIC)\n" : "\n");
}

const char *noyau_minuterie(void) {
  return minuterie == 2 ? (apic_x2 ? "APIC locale (x2APIC)" : "APIC locale") :
         minuterie == 1 ? "PIT 8254" : "aucune : le processeur ne dort pas";
}
const char *noyau_calibrage(void) { return calibrage; }

/* nom du processeur tel qu'il le donne lui-même (sinon son fabricant) */
void noyau_processeur(char *d, int max) {
  u32 r[13] = {0}, a, b, c, e;
  cpuid(0x80000000, &a, &b, &c, &e);
  if (a >= 0x80000004)
    for (u32 i = 0; i < 3; i++) cpuid(0x80000002 + i, &r[4 * i], &r[4 * i + 1], &r[4 * i + 2], &r[4 * i + 3]);
  else cpuid(0, &a, &r[0], &r[2], &r[1]);              /* « GenuineIntel », « AuthenticAMD »… */
  const char *t = (const char *)r;
  int i = 0, espace = 1;
  for (int k = 0; k < 48 && t[k] && i < max - 1; k++) {
    if (t[k] == ' ') { if (!espace) d[i++] = ' '; espace = 1; }
    else { d[i++] = t[k]; espace = 0; }
  }
  while (i && d[i - 1] == ' ') i--;
  d[i] = 0;
}
u64 noyau_frequence_tsc(void) { return tsc_hz; }

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
u64 noyau_tics(void) { return noyau_microsecondes() / (1000000 / TICS_PAR_SECONDE); }
u64 noyau_interruptions(int irq) { return irq >= 0 && irq < 2 ? compte_irq[irq] : 0; }
void noyau_attendre(void) {
  if (minuterie) __asm__ volatile("sti\n hlt" : : : "memory");   /* réveillé par la minuterie */
  else __asm__ volatile("sti\n pause" : : : "memory");          /* sans minuterie : on relève en boucle */
}

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
  calibrer_tsc();
  preparer_clavier();
  /* minuterie : celle de l'APIC local d'abord (le PIT peut être arrêté sur un PC récent), sinon le PIT */
  if (preparer_minuterie_apic()) {
    sortie(0x21, 0xFD);                                 /* IRQ 0 du PIC masquée : une seule minuterie */
    poser(0x20, isr_minuterie_apic);
    __asm__ volatile("sti");
    if (minuterie_bat()) { minuterie = 2; journaliser_temps(); return; }
    __asm__ volatile("cli");
    apic_ecrire(0x320, 1 << 16);                        /* elle ne bat pas : arrêtée */
  }
  poser(0x20, isr_minuterie);
  preparer_minuterie();
  sortie(0x21, 0xFC);
  __asm__ volatile("sti");
  minuterie = minuterie_bat() ? 1 : 0;
  journaliser_temps();
}
