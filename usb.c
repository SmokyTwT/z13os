/* Smoky OS 100 % maison — pilote xHCI et claviers USB (voir usb.h).
 *
 * Chemin d'une touche : le clavier envoie un rapport de 8 octets (modificateurs + 6 touches,
 * protocole de démarrage) sur son point de sortie « interruption » ; le contrôleur le dépose dans
 * notre tampon et écrit un événement ; usb_sonder() le lit, compare au rapport précédent et pousse
 * dans la file du clavier les mêmes codes qu'un clavier PS/2 (jeu 1) : la disposition AZERTY, les
 * accents et Alt Gr du noyau servent donc aussi au clavier USB.
 *
 * Écrit d'après la spécification xHCI 1.2 (Intel) et USB HID 1.11. Mémoire : pages du noyau,
 * adresses physiques = adresses virtuelles (le firmware a laissé une correspondance 1 pour 1). */
#include "usb.h"
#include "noyau.h"

/* --- Petits outils ------------------------------------------------------------------------------- */
static void sortie32(u16 port, u32 v) { __asm__ volatile("outl %0, %1" : : "a"(v), "Nd"(port)); }
static u32 entree32(u16 port) { u32 v; __asm__ volatile("inl %1, %0" : "=a"(v) : "Nd"(port)); return v; }
static void sortie8(u16 port, u8 v) { __asm__ volatile("outb %0, %1" : : "a"(v), "Nd"(port)); }
static u8 entree8(u16 port) { u8 v; __asm__ volatile("inb %1, %0" : "=a"(v) : "Nd"(port)); return v; }
static void barriere(void) { __asm__ volatile("mfence" : : : "memory"); }
static void pause(void) { __asm__ volatile("pause"); }

static u32 lire32(volatile u8 *b, u32 o) { return *(volatile u32 *)(b + o); }
static void ecrire32(volatile u8 *b, u32 o, u32 v) { *(volatile u32 *)(b + o) = v; }
static void ecrire64(volatile u8 *b, u32 o, u64 v) { ecrire32(b, o, (u32)v); ecrire32(b, o + 4, (u32)(v >> 32)); }

static void zero(volatile void *p, u64 n) { volatile u8 *q = p; while (n--) *q++ = 0; }

/* PORTSC : valeur à réécrire sans rien déclencher (bits « 1 efface », activation, remises à zéro) */
static u32 port_neutre(u32 ps) { return ps & ~((0x7Fu << 17) | (1u << 1) | (1u << 4) | (1u << 16) | (1u << 31)); }

/* journal sur le port série COM1 (lu dans les essais QEMU ; sans effet sur un PC qui n'en a pas) */
static void journal(const char *t) {
  for (; *t; t++) {
    for (int i = 0; i < 10000 && !(entree8(0x3FD) & 0x20); i++) pause();
    sortie8(0x3F8, (u8)*t);
  }
}
static void journal_hex(const char *t, u64 v) {
  char d[20]; int n = 0;
  journal(t);
  do { d[n++] = "0123456789abcdef"[v & 15]; v >>= 4; } while (v && n < 16);
  char r[20]; for (int i = 0; i < n; i++) r[i] = d[n - 1 - i]; r[n] = 0;
  journal(r); journal("\n");
}

/* attend que cond() soit vraie, au plus `tics` réveils de la minuterie (50 par seconde) */
#define ATTENDRE(cond, tics_max) ({ u64 _fin = noyau_tics() + (tics_max); int _ok; \
  while (!(_ok = (cond)) && noyau_tics() < _fin) pause(); _ok; })
static void dormir(u64 tics_) { u64 f = noyau_tics() + tics_; while (noyau_tics() < f) pause(); }

static void *page(void) {
  void *p = noyau_allouer_pages(1);
  if (p) zero(p, 4096);
  return p;
}

/* --- PCI (accès par les ports 0xCF8 / 0xCFC) -------------------------------------------------------- */
static u32 pci_lire(u32 bus, u32 dev, u32 fn, u32 off) {
  sortie32(0xCF8, 0x80000000u | bus << 16 | dev << 11 | fn << 8 | (off & 0xFC));
  return entree32(0xCFC);
}
static void pci_ecrire(u32 bus, u32 dev, u32 fn, u32 off, u32 v) {
  sortie32(0xCF8, 0x80000000u | bus << 16 | dev << 11 | fn << 8 | (off & 0xFC));
  sortie32(0xCFC, v);
}

/* --- Correspondance mémoire des registres (MMIO) --------------------------------------------------- */
/* Le firmware fait correspondre adresses virtuelles et physiques ; on vérifie que les registres du
 * contrôleur y sont, sinon on les ajoute en pages de 2 Mio non mises en cache. */
static int mapper(u64 base, u64 taille) {
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
        u64 *t = page();
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

/* --- Structures xHCI --------------------------------------------------------------------------------- */
typedef struct { u64 param; u32 statut; u32 controle; } trb;
#define NB_TRB 256
enum { T_NORMAL = 1, T_SETUP = 2, T_DATA = 3, T_STATUS = 4, T_LINK = 6, T_ENABLE_SLOT = 9,
       T_DISABLE_SLOT = 10, T_ADDRESS = 11, T_CONFIGURE = 12, T_EVALUATE = 13, T_TRANSFERT = 32, T_COMMANDE = 33, T_PORT = 34 };

struct anneau { volatile trb *trbs; u32 index, cycle; };

struct controleur;
struct appareil {
  struct controleur *hc;
  int slot, port, vitesse, dci, interface, clavier;
  struct anneau ep0, ep;
  volatile u8 *entree, *sortie, *tampon, *rapport;
  u8 avant[8];
  u16 repete; u64 repete_a;
};

struct controleur {
  volatile u8 *cap, *op, *rt, *db;
  u32 nb_ports, nb_slots, csz;
  volatile u64 *dcbaa;
  struct anneau commandes;
  volatile trb *ev; u32 ev_index, ev_cycle;
  u8 usb2[256];
  struct appareil app[16]; int nb_app;
  u8 changement[256];
};
static struct controleur HC[4];
static int nb_hc, nb_claviers;

static void poser(struct anneau *a, u64 param, u32 statut, u32 controle) {
  volatile trb *t = &a->trbs[a->index];
  t->param = param;
  t->statut = statut;
  barriere();
  t->controle = controle | a->cycle;
  if (++a->index == NB_TRB - 1) {                       /* dernier : lien vers le début, cycle inversé */
    volatile trb *l = &a->trbs[NB_TRB - 1];
    l->param = (u64)a->trbs;
    l->statut = 0;
    barriere();
    l->controle = (T_LINK << 10) | 2 | a->cycle;
    a->index = 0;
    a->cycle ^= 1;
  }
}

static int nouvel_anneau(struct anneau *a) {
  a->trbs = page();
  a->index = 0;
  a->cycle = 1;
  return a->trbs != 0;
}

static void sonner(struct controleur *hc, int slot, int cible) { barriere(); ecrire32(hc->db, 4 * slot, cible); }

static int evenement(struct controleur *hc, trb *e) {
  volatile trb *t = &hc->ev[hc->ev_index];
  if ((t->controle & 1) != hc->ev_cycle) return 0;
  e->param = t->param; e->statut = t->statut; e->controle = t->controle;
  if (++hc->ev_index == NB_TRB) { hc->ev_index = 0; hc->ev_cycle ^= 1; }
  ecrire64(hc->rt, 0x38, (u64)&hc->ev[hc->ev_index] | 8);   /* ERDP, et « gestionnaire occupé » effacé */
  return 1;
}

static void traiter(struct controleur *hc, const trb *e);

/* attend l'événement de fin de la commande ou du transfert posé en `adresse` */
static int attendre_fin(struct controleur *hc, int type, u64 adresse, int slot, trb *r) {
  u64 fin = noyau_tics() + 100;                         /* 2 s */
  while (noyau_tics() < fin) {
    trb e;
    if (!evenement(hc, &e)) { pause(); continue; }
    int t = (e.controle >> 10) & 63;
    u32 code = e.statut >> 24;
    int echec_ep0 = t == T_TRANSFERT && (int)(e.controle >> 24) == slot && ((e.controle >> 16) & 31) == 1
                    && code != 1 && code != 13;
    if (t == type && (e.param == adresse || echec_ep0)) {
      if (r) *r = e;
      return code == 1 || code == 13;
    }
    traiter(hc, &e);                                    /* touche ou branchement arrivés entre-temps */
  }
  journal_hex("usb : délai dépassé, type ", (u64)type);
  return 0;
}

static int commande(struct controleur *hc, u64 param, u32 controle, trb *r) {
  u64 adresse = (u64)&hc->commandes.trbs[hc->commandes.index];
  poser(&hc->commandes, param, 0, controle);
  sonner(hc, 0, 0);
  return attendre_fin(hc, T_COMMANDE, adresse, 0, r);
}

/* contexte n° i d'un contexte d'entrée (0 = contrôle, 1 = appareil, 2 = EP0…) */
static volatile u32 *ctx(struct appareil *a, int i) { return (volatile u32 *)(a->entree + i * a->hc->csz); }

static int requete(struct appareil *a, u8 type, u8 req, u16 valeur, u16 index, u16 longueur) {
  struct anneau *r = &a->ep0;
  u64 setup = type | (u64)req << 8 | (u64)valeur << 16 | (u64)index << 32 | (u64)longueur << 48;
  u32 trt = longueur ? ((type & 0x80) ? 3 : 2) : 0;
  poser(r, setup, 8, (T_SETUP << 10) | (1 << 6) | (trt << 16));
  if (longueur) poser(r, (u64)a->tampon, longueur, (T_DATA << 10) | ((type & 0x80) ? 1u << 16 : 0));
  u64 adresse = (u64)&r->trbs[r->index];
  poser(r, 0, 0, (T_STATUS << 10) | (1 << 5) | ((longueur && (type & 0x80)) ? 0 : 1u << 16));
  sonner(a->hc, a->slot, 1);
  return attendre_fin(a->hc, T_TRANSFERT, adresse, a->slot, 0);
}

/* --- Clavier : rapport de 8 octets → codes PS/2 du jeu 1 (0x100 : précédé de 0xE0) ------------------ */
static const u16 HID_PS2[0x66] = {
  [0x04] = 0x1E, [0x05] = 0x30, [0x06] = 0x2E, [0x07] = 0x20, [0x08] = 0x12, [0x09] = 0x21, [0x0A] = 0x22,
  [0x0B] = 0x23, [0x0C] = 0x17, [0x0D] = 0x24, [0x0E] = 0x25, [0x0F] = 0x26, [0x10] = 0x32, [0x11] = 0x31,
  [0x12] = 0x18, [0x13] = 0x19, [0x14] = 0x10, [0x15] = 0x13, [0x16] = 0x1F, [0x17] = 0x14, [0x18] = 0x16,
  [0x19] = 0x2F, [0x1A] = 0x11, [0x1B] = 0x2D, [0x1C] = 0x15, [0x1D] = 0x2C,
  [0x1E] = 0x02, [0x1F] = 0x03, [0x20] = 0x04, [0x21] = 0x05, [0x22] = 0x06, [0x23] = 0x07, [0x24] = 0x08,
  [0x25] = 0x09, [0x26] = 0x0A, [0x27] = 0x0B,
  [0x28] = 0x1C, [0x29] = 0x01, [0x2A] = 0x0E, [0x2B] = 0x0F, [0x2C] = 0x39, [0x2D] = 0x0C, [0x2E] = 0x0D,
  [0x2F] = 0x1A, [0x30] = 0x1B, [0x31] = 0x2B, [0x32] = 0x2B, [0x33] = 0x27, [0x34] = 0x28, [0x35] = 0x29,
  [0x36] = 0x33, [0x37] = 0x34, [0x38] = 0x35, [0x39] = 0x3A,
  [0x3A] = 0x3B, [0x3B] = 0x3C, [0x3C] = 0x3D, [0x3D] = 0x3E, [0x3E] = 0x3F, [0x3F] = 0x40, [0x40] = 0x41,
  [0x41] = 0x42, [0x42] = 0x43, [0x43] = 0x44, [0x44] = 0x57, [0x45] = 0x58,
  [0x49] = 0x152, [0x4A] = 0x147, [0x4B] = 0x149, [0x4C] = 0x153, [0x4D] = 0x14F, [0x4E] = 0x151,
  [0x4F] = 0x14D, [0x50] = 0x14B, [0x51] = 0x150, [0x52] = 0x148, [0x64] = 0x56,
};
static const u16 MODIFICATEURS[8] = {0x1D, 0x2A, 0x38, 0x15B, 0x11D, 0x36, 0x138, 0x15C};

static void emettre(u16 code, int relache) {
  if (code & 0x100) noyau_pousser_code(0xE0);
  noyau_pousser_code((u8)((code & 0x7F) | (relache ? 0x80 : 0)));
}

static int contient(const u8 *r, u8 touche) { for (int i = 2; i < 8; i++) if (r[i] == touche) return 1; return 0; }

static void rapport(struct appareil *a, const u8 *r) {
  if (r[2] == 1) return;                                /* trop de touches à la fois : ignoré */
  for (int b = 0; b < 8; b++)
    if (((r[0] ^ a->avant[0]) >> b) & 1) emettre(MODIFICATEURS[b], !((r[0] >> b) & 1));
  for (int i = 2; i < 8; i++)                           /* relâchées */
    if (a->avant[i] && a->avant[i] < 0x66 && HID_PS2[a->avant[i]] && !contient(r, a->avant[i])) {
      emettre(HID_PS2[a->avant[i]], 1);
      if (HID_PS2[a->avant[i]] == a->repete) a->repete = 0;
    }
  for (int i = 2; i < 8; i++)                           /* enfoncées */
    if (r[i] && r[i] < 0x66 && HID_PS2[r[i]] && !contient(a->avant, r[i])) {
      emettre(HID_PS2[r[i]], 0);
      a->repete = HID_PS2[r[i]];
      a->repete_a = noyau_tics() + 25;                  /* répétition après une demi-seconde */
    }
  for (int i = 0; i < 8; i++) a->avant[i] = r[i];
}

static void demander_rapport(struct appareil *a) {
  poser(&a->ep, (u64)a->rapport, 8, (T_NORMAL << 10) | (1 << 5) | (1 << 2));
  sonner(a->hc, a->slot, a->dci);
}

/* --- Un appareil branché sur un port : adresse, descripteurs, clavier ? --------------------------- */
static int intervalle(int vitesse, int b_interval) {
  if (vitesse >= 3) { int v = b_interval - 1; return v < 0 ? 0 : v > 15 ? 15 : v; }   /* haut débit et plus */
  int v = 3; while ((1 << (v + 1)) <= b_interval * 8 && v < 10) v++;                  /* trames de 1 ms */
  return v;
}

static void brancher(struct controleur *hc, int port) {
  int libre = hc->nb_app;                               /* une place laissée par un appareil débranché ? */
  for (int i = 0; i < hc->nb_app; i++) if (!hc->app[i].slot) { libre = i; break; }
  if (libre >= 16) return;
  u32 o = 0x400 + 0x10 * (port - 1);
  u32 ps = lire32(hc->op, o);
  if (!(ps & 1)) return;
  if (hc->usb2[port]) {                                 /* USB 2 : remise à zéro du port */
    ecrire32(hc->op, o, port_neutre(ps) | (1 << 4));
    if (!ATTENDRE(lire32(hc->op, o) & (1 << 21), 25)) { journal_hex("usb : port sans réponse ", port); return; }
    ecrire32(hc->op, o, port_neutre(lire32(hc->op, o)) | (1 << 21) | (1 << 17));
    dormir(3);
  }
  ps = lire32(hc->op, o);
  if (!(ps & 2)) { journal_hex("usb : port pas activé ", port); return; }
  struct appareil *a = &hc->app[libre];
  zero(a, sizeof *a);
  if (libre == hc->nb_app) hc->nb_app++;
  a->hc = hc; a->port = port; a->vitesse = (ps >> 10) & 15;
  trb r;
  if (!commande(hc, 0, T_ENABLE_SLOT << 10, &r)) { journal("usb : pas d'emplacement libre\n"); a->port = 0; return; }
  a->slot = (int)(r.controle >> 24);
  a->entree = page(); a->sortie = page(); a->tampon = page(); a->rapport = page();
  if (!a->entree || !a->sortie || !a->tampon || !a->rapport || !nouvel_anneau(&a->ep0)) return;
  hc->dcbaa[a->slot] = (u64)a->sortie;
  int mps = a->vitesse == 4 ? 512 : a->vitesse == 3 ? 64 : 8;
  ctx(a, 0)[1] = 3;                                     /* ajoute : appareil + EP0 */
  ctx(a, 1)[0] = (u32)a->vitesse << 20 | 1u << 27;
  ctx(a, 1)[1] = (u32)port << 16;
  volatile u32 *ep0 = ctx(a, 2);
  ep0[1] = 3 << 1 | 4 << 3 | (u32)mps << 16;            /* 3 essais, contrôle, taille des paquets */
  ep0[2] = (u32)(u64)a->ep0.trbs | 1;
  ep0[3] = (u32)((u64)a->ep0.trbs >> 32);
  ep0[4] = 8;
  if (!commande(hc, (u64)a->entree, T_ADDRESS << 10 | (u32)a->slot << 24, 0)) {
    journal_hex("usb : adressage refusé, port ", port); return;
  }
  if (!requete(a, 0x80, 6, 0x100, 0, 8)) { journal("usb : descripteur illisible\n"); return; }
  int vrai_mps = a->tampon[7];
  if (a->vitesse < 3 && vrai_mps && vrai_mps != mps) {   /* pleine vitesse : taille réelle d'EP0 */
    zero(a->entree, 4096);
    ctx(a, 0)[1] = 2;
    ctx(a, 2)[1] = 3 << 1 | 4 << 3 | (u32)vrai_mps << 16;
    ctx(a, 2)[2] = (u32)(u64)a->ep0.trbs | 1;
    ctx(a, 2)[3] = (u32)((u64)a->ep0.trbs >> 32);
    ctx(a, 2)[4] = 8;
    commande(hc, (u64)a->entree, T_EVALUATE << 10 | (u32)a->slot << 24, 0);
  }
  if (!requete(a, 0x80, 6, 0x200, 0, 9)) return;        /* configuration : longueur totale */
  int total = a->tampon[2] | a->tampon[3] << 8, valeur = a->tampon[5];
  if (total > 1024) total = 1024;
  if (!requete(a, 0x80, 6, 0x200, 0, (u16)total)) return;
  int clavier = 0, iface = -1, ep_adresse = 0, ep_mps = 8, ep_intervalle = 10;
  for (int i = 0; i + 1 < total && a->tampon[i] >= 2; i += a->tampon[i]) {
    const volatile u8 *d = a->tampon + i;
    if (d[1] == 4) { clavier = d[5] == 3 && d[6] == 1 && d[7] == 1 && !ep_adresse; if (clavier) iface = d[2]; }
    else if (d[1] == 5 && clavier && !ep_adresse && (d[2] & 0x80) && (d[3] & 3) == 3) {
      ep_adresse = d[2]; ep_mps = d[4] | (d[5] & 7) << 8; ep_intervalle = d[6];
    }
  }
  if (!ep_adresse) { journal_hex("usb : appareil (pas un clavier) sur le port ", port); return; }
  requete(a, 0x00, 9, (u16)valeur, 0, 0);               /* SET_CONFIGURATION */
  requete(a, 0x21, 0x0B, 0, (u16)iface, 0);             /* SET_PROTOCOL : protocole de démarrage */
  requete(a, 0x21, 0x0A, 0, (u16)iface, 0);             /* SET_IDLE : rapport seulement au changement */
  a->interface = iface;
  a->dci = (ep_adresse & 15) * 2 + 1;
  if (!nouvel_anneau(&a->ep)) return;
  zero(a->entree, 4096);
  ctx(a, 0)[1] = 1 | 1u << a->dci;
  ctx(a, 1)[0] = (u32)a->vitesse << 20 | (u32)a->dci << 27;
  ctx(a, 1)[1] = (u32)port << 16;
  volatile u32 *ep = ctx(a, a->dci + 1);
  ep[0] = (u32)intervalle(a->vitesse, ep_intervalle) << 16;
  ep[1] = 3 << 1 | 7 << 3 | (u32)ep_mps << 16;          /* interruption entrante */
  ep[2] = (u32)(u64)a->ep.trbs | 1;
  ep[3] = (u32)((u64)a->ep.trbs >> 32);
  ep[4] = 8 | (u32)ep_mps << 16;
  if (!commande(hc, (u64)a->entree, T_CONFIGURE << 10 | (u32)a->slot << 24, 0)) {
    journal("usb : configuration du clavier refusée\n"); return;
  }
  a->clavier = 1;
  nb_claviers++;
  journal_hex("usb : clavier prêt sur le port ", port);
  demander_rapport(a);
}

static void traiter(struct controleur *hc, const trb *e) {
  int t = (e->controle >> 10) & 63;
  if (t == T_PORT) {
    int port = (int)(e->param >> 24);
    if (port > 0 && port <= (int)hc->nb_ports) hc->changement[port] = 1;
  } else if (t == T_TRANSFERT) {
    int slot = (int)(e->controle >> 24), dci = (int)((e->controle >> 16) & 31);
    for (int i = 0; i < hc->nb_app; i++) {
      struct appareil *a = &hc->app[i];
      if (a->clavier && a->slot == slot && a->dci == dci) {
        u32 code = e->statut >> 24;
        if (code == 1 || code == 13) { u8 r[8]; for (int k = 0; k < 8; k++) r[k] = a->rapport[k]; rapport(a, r); }
        if (code == 1 || code == 13) demander_rapport(a);
        else journal_hex("usb : erreur de transfert du clavier ", code);
      }
    }
  }
}

/* --- Démarrage d'un contrôleur ---------------------------------------------------------------------- */
static void reprendre_au_firmware(struct controleur *hc) {
  u32 xecp = (lire32(hc->cap, 0x10) >> 16) * 4;
  for (int n = 0; xecp && n < 64; n++) {
    u32 v = lire32(hc->cap, xecp);
    if ((v & 0xFF) == 1) {                              /* USB Legacy Support : le BIOS rend la main */
      ecrire32(hc->cap, xecp, v | (1u << 24));
      if (!ATTENDRE(!(lire32(hc->cap, xecp) & (1u << 16)), 50)) journal("usb : le BIOS garde le contrôleur\n");
      ecrire32(hc->cap, xecp + 4, (lire32(hc->cap, xecp + 4) & ~0xE011u) | 0xE0000000u);   /* SMI coupées */
    } else if ((v & 0xFF) == 2) {                       /* protocoles des ports : lesquels sont USB 2 */
      u32 p = lire32(hc->cap, xecp + 8);
      int premier = p & 0xFF, nombre = (p >> 8) & 0xFF;
      for (int i = premier; i < premier + nombre && i < 256; i++) hc->usb2[i] = (v >> 24) == 2;
    }
    u32 suivant = (v >> 8) & 0xFF;
    xecp = suivant ? xecp + suivant * 4 : 0;
  }
}

static int preparer(struct controleur *hc, u64 bar) {
  if (!mapper(bar, 0x10000)) return 0;
  hc->cap = (volatile u8 *)bar;
  hc->op = hc->cap + (lire32(hc->cap, 0) & 0xFF);
  hc->rt = hc->cap + (lire32(hc->cap, 0x18) & ~0x1Fu);
  hc->db = hc->cap + (lire32(hc->cap, 0x14) & ~0x3u);
  u32 hcs1 = lire32(hc->cap, 4), hcs2 = lire32(hc->cap, 8), hcc1 = lire32(hc->cap, 0x10);
  hc->nb_slots = hcs1 & 0xFF; if (hc->nb_slots > 16) hc->nb_slots = 16;
  hc->nb_ports = (hcs1 >> 24) & 0xFF;
  hc->csz = (hcc1 & 4) ? 64 : 32;
  reprendre_au_firmware(hc);
  ecrire32(hc->op, 0, lire32(hc->op, 0) & ~1u);         /* arrêt */
  ATTENDRE(lire32(hc->op, 4) & 1, 25);
  ecrire32(hc->op, 0, 2);                               /* remise à zéro */
  if (!ATTENDRE(!(lire32(hc->op, 0) & 2) && !(lire32(hc->op, 4) & (1 << 11)), 50)) {
    journal("usb : le contrôleur ne se remet pas à zéro\n"); return 0;
  }
  ecrire32(hc->op, 0x38, hc->nb_slots);                 /* CONFIG : emplacements utilisés */
  hc->dcbaa = page();
  if (!hc->dcbaa) return 0;
  int brouillon = (int)((hcs2 >> 27) & 0x1F) | (int)(((hcs2 >> 21) & 0x1F) << 5);
  if (brouillon) {                                      /* pages « brouillon » demandées par le matériel */
    u64 *liste = page();
    if (!liste || brouillon > 512) return 0;
    for (int i = 0; i < brouillon; i++) { liste[i] = (u64)page(); if (!liste[i]) return 0; }
    hc->dcbaa[0] = (u64)liste;
  }
  ecrire64(hc->op, 0x30, (u64)hc->dcbaa);
  if (!nouvel_anneau(&hc->commandes)) return 0;
  ecrire64(hc->op, 0x18, (u64)hc->commandes.trbs | 1);
  hc->ev = page();
  volatile u64 *erst = page();
  if (!hc->ev || !erst) return 0;
  erst[0] = (u64)hc->ev; erst[1] = NB_TRB;
  hc->ev_index = 0; hc->ev_cycle = 1;
  ecrire32(hc->rt, 0x28, 1);                            /* une seule portion d'anneau d'événements */
  ecrire64(hc->rt, 0x38, (u64)hc->ev);
  ecrire64(hc->rt, 0x30, (u64)erst);
  ecrire32(hc->op, 0, 1);                               /* en marche (sans interruptions : on relève) */
  if (!ATTENDRE(!(lire32(hc->op, 4) & 1), 25)) { journal("usb : le contrôleur ne démarre pas\n"); return 0; }
  for (u32 p = 1; p <= hc->nb_ports; p++) {             /* alimentation des ports */
    u32 o = 0x400 + 0x10 * (p - 1), ps = lire32(hc->op, o);
    if (!(ps & (1 << 9))) ecrire32(hc->op, o, port_neutre(ps) | (1 << 9));
  }
  dormir(10);                                           /* les appareils se présentent */
  for (u32 p = 1; p <= hc->nb_ports; p++) {
    u32 o = 0x400 + 0x10 * (p - 1);
    u32 ps = lire32(hc->op, o);
    ecrire32(hc->op, o, port_neutre(ps) | (ps & (0x7Fu << 17)));
    hc->changement[p] = 0;
    if (ps & 1) brancher(hc, (int)p);
  }
  return 1;
}

int usb_demarrer(void) {
  for (u32 bus = 0; bus < 256 && nb_hc < 4; bus++)
    for (u32 dev = 0; dev < 32 && nb_hc < 4; dev++) {
      if ((pci_lire(bus, dev, 0, 0) & 0xFFFF) == 0xFFFF) continue;
      int fonctions = (pci_lire(bus, dev, 0, 0x0C) >> 16) & 0x80 ? 8 : 1;
      for (u32 fn = 0; fn < (u32)fonctions && nb_hc < 4; fn++) {
        u32 id = pci_lire(bus, dev, fn, 0);
        if ((id & 0xFFFF) == 0xFFFF) continue;
        if ((pci_lire(bus, dev, fn, 8) >> 8) != 0x0C0330) continue;   /* série USB, xHCI */
        u32 bar0 = pci_lire(bus, dev, fn, 0x10);
        u64 bar = bar0 & ~0xFULL;
        if (((bar0 >> 1) & 3) == 2) bar |= (u64)pci_lire(bus, dev, fn, 0x14) << 32;
        pci_ecrire(bus, dev, fn, 4, pci_lire(bus, dev, fn, 4) | 6);   /* mémoire + maître du bus */
        journal_hex("usb : contrôleur xHCI à ", bar);
        if (preparer(&HC[nb_hc], bar)) nb_hc++;
      }
    }
  return nb_hc;
}

void usb_sonder(void) {
  for (int h = 0; h < nb_hc; h++) {
    struct controleur *hc = &HC[h];
    trb e;
    while (evenement(hc, &e)) traiter(hc, &e);
    for (u32 p = 1; p <= hc->nb_ports; p++) {
      if (!hc->changement[p]) continue;
      hc->changement[p] = 0;
      u32 o = 0x400 + 0x10 * (p - 1), ps = lire32(hc->op, o);
      ecrire32(hc->op, o, port_neutre(ps) | (ps & (0x7Fu << 17)));
      int deja = 0;
      for (int i = 0; i < hc->nb_app; i++)
        if (hc->app[i].port == (int)p && hc->app[i].slot) {
          if (!(ps & 1)) {                               /* débranché : emplacement rendu, place libérée */
            if (hc->app[i].clavier) nb_claviers--;
            commande(hc, 0, T_DISABLE_SLOT << 10 | (u32)hc->app[i].slot << 24, 0);
            hc->dcbaa[hc->app[i].slot] = 0;
            journal_hex("usb : appareil débranché du port ", p);
            hc->app[i].clavier = 0; hc->app[i].port = 0; hc->app[i].slot = 0;
          } else deja = 1;
        }
      if ((ps & 1) && !deja && (ps & (1 << 17))) brancher(hc, (int)p);
    }
    for (int i = 0; i < hc->nb_app; i++) {               /* répétition d'une touche maintenue */
      struct appareil *a = &hc->app[i];
      if (a->clavier && a->repete && noyau_tics() >= a->repete_a) {
        emettre(a->repete, 0);
        a->repete_a = noyau_tics() + 2;
      }
    }
  }
}

int usb_claviers(void) { return nb_claviers; }

void usb_etat(char *d, int max) {
  const char *t = nb_hc == 0 ? "USB : aucun contrôleur xHCI" : nb_claviers ? "USB : clavier USB prêt" :
                  "USB : contrôleur prêt, aucun clavier";
  int i = 0;
  while (t[i] && i < max - 1) { d[i] = t[i]; i++; }
  d[i] = 0;
}
