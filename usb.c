/* Smoky OS 100 % maison — pilote xHCI et claviers USB (voir usb.h).
 *
 * Chemin d'une touche : le clavier envoie un rapport de 8 octets (modificateurs + 6 touches,
 * protocole de démarrage) sur son point de sortie « interruption » ; le contrôleur le dépose dans
 * notre tampon et écrit un événement ; usb_sonder() le lit, compare au rapport précédent et pousse
 * dans la file du clavier les mêmes codes qu'un clavier PS/2 (jeu 1) : la disposition AZERTY, les
 * accents et Alt Gr du noyau servent donc aussi au clavier USB.
 *
 * Hubs USB 2 (et partie USB 2 des hubs USB 3) : un appareil derrière un hub est désigné au contrôleur
 * par le port où commence la chaîne et par un chemin (4 bits par étage). Un clavier pleine ou basse
 * vitesse derrière un hub haut débit passe par le traducteur (TT) de ce hub, que le contrôleur doit
 * connaître. Le hub signale ses ports qui changent sur son propre point « interruption » ; on les
 * examine ensuite par des requêtes au hub (chapitre 11 de la spécification USB 2.0).
 *
 * Écrit d'après les spécifications xHCI 1.2 (Intel), USB 2.0 et USB HID 1.11. Mémoire : pages du noyau,
 * adresses physiques = adresses virtuelles (le firmware a laissé une correspondance 1 pour 1). */
#include "usb.h"
#include "noyau.h"

/* --- Petits outils ------------------------------------------------------------------------------- */
static void sortie32(u16 port, u32 v) { __asm__ volatile("outl %0, %1" : : "a"(v), "Nd"(port)); }
static u32 entree32(u16 port) { u32 v; __asm__ volatile("inl %1, %0" : "=a"(v) : "Nd"(port)); return v; }
static void barriere(void) { __asm__ volatile("mfence" : : : "memory"); }
static void pause(void) { __asm__ volatile("pause"); }

static u32 lire32(volatile u8 *b, u32 o) { return *(volatile u32 *)(b + o); }
static void ecrire32(volatile u8 *b, u32 o, u32 v) { *(volatile u32 *)(b + o) = v; }
static void ecrire64(volatile u8 *b, u32 o, u64 v) { ecrire32(b, o, (u32)v); ecrire32(b, o + 4, (u32)(v >> 32)); }

static void zero(volatile void *p, u64 n) { volatile u8 *q = p; while (n--) *q++ = 0; }

/* PORTSC : valeur à réécrire sans rien déclencher (bits « 1 efface », activation, remises à zéro) */
static u32 port_neutre(u32 ps) { return ps & ~((0x7Fu << 17) | (1u << 1) | (1u << 4) | (1u << 16) | (1u << 31)); }

static void journal(const char *t) { noyau_journal(t); }
static void journal_hex(const char *t, u64 v) { noyau_journal_nombre(t, v, 16); noyau_journal("\n"); }
static void journal_nb(const char *t, u64 v) { noyau_journal_nombre(t, v, 10); noyau_journal("\n"); }

/* attend que cond() soit vraie, au plus `tics` réveils de la minuterie (50 par seconde) */
#define ATTENDRE(cond, tics_max) ({ u64 _fin = noyau_tics() + (tics_max); int _ok; \
  while (!(_ok = (cond)) && noyau_tics() < _fin) pause(); _ok; })
static void dormir(u64 tics_) { u64 f = noyau_tics() + tics_; while (noyau_tics() < f) pause(); }
static void dormir_ms(u64 ms) { u64 f = noyau_microsecondes() + ms * 1000; while (noyau_microsecondes() < f) pause(); }

static void *page(void) {
  void *p = noyau_allouer_pages(1);
  if (p) zero(p, 4096);
  return p;
}
static volatile u8 *page_propre(volatile u8 *p) { if (p) { zero(p, 4096); return p; } return page(); }

/* --- PCI (accès par les ports 0xCF8 / 0xCFC) -------------------------------------------------------- */
static u32 pci_lire(u32 bus, u32 dev, u32 fn, u32 off) {
  sortie32(0xCF8, 0x80000000u | bus << 16 | dev << 11 | fn << 8 | (off & 0xFC));
  return entree32(0xCFC);
}
static void pci_ecrire(u32 bus, u32 dev, u32 fn, u32 off, u32 v) {
  sortie32(0xCF8, 0x80000000u | bus << 16 | dev << 11 | fn << 8 | (off & 0xFC));
  sortie32(0xCFC, v);
}

/* contrôleur endormi par le firmware (état D3) : remis en marche (D0) avant de lire ses registres */
static void reveiller_pci(u32 bus, u32 dev, u32 fn) {
  if (!((pci_lire(bus, dev, fn, 4) >> 16) & 0x10)) return;          /* pas de liste de capacités */
  u32 ptr = pci_lire(bus, dev, fn, 0x34) & 0xFC;
  for (int n = 0; ptr && n < 48; n++) {
    u32 v = pci_lire(bus, dev, fn, ptr);
    if ((v & 0xFF) == 1) {                                           /* gestion de l'énergie */
      u32 pmcsr = pci_lire(bus, dev, fn, ptr + 4);
      if (pmcsr & 3) {
        pci_ecrire(bus, dev, fn, ptr + 4, pmcsr & ~3u);
        dormir_ms(10);
        journal("usb : contrôleur réveillé\n");
      }
      return;
    }
    ptr = (v >> 8) & 0xFC;
  }
}

/* --- Structures xHCI --------------------------------------------------------------------------------- */
typedef struct { u64 param; u32 statut; u32 controle; } trb;
#define NB_TRB 256
#define NB_APP 16
enum { T_NORMAL = 1, T_SETUP = 2, T_DATA = 3, T_STATUS = 4, T_LINK = 6, T_ENABLE_SLOT = 9,
       T_DISABLE_SLOT = 10, T_ADDRESS = 11, T_CONFIGURE = 12, T_EVALUATE = 13, T_RESET_EP = 14, T_STOP_EP = 15,
       T_DEQUEUE = 16, T_TRANSFERT = 32, T_COMMANDE = 33, T_PORT = 34 };

struct anneau { volatile trb *trbs; u32 index, cycle; };

struct controleur;
struct appareil {
  struct controleur *hc;
  struct appareil *parent;              /* hub où il est branché ; 0 : directement sur le contrôleur */
  int slot, port, vitesse, dci, interface, clavier, hub, souris;
  int port_parent, etage;               /* port du hub parent ; étage 0 = sur le contrôleur */
  u32 route;                            /* chemin depuis le port du contrôleur : 4 bits par étage */
  int tt_slot, tt_port;                 /* traducteur du hub haut débit qu'empruntent les appareils lents */
  int nb_ports_hub, ttt, alim_ms, sonde_lente, panne, pannes;
  u32 a_voir;                           /* ports du hub à examiner (bit n : port n) */
  u64 prochaine_sonde;
  u16 vendeur, produit; u8 classe;
  int longueur;                         /* octets demandés au point « interruption » */
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
  struct appareil app[NB_APP]; int nb_app;
  u8 changement[256];
};
static struct controleur HC[4];
static int nb_hc, nb_claviers, nb_souris;

/* souris : rapports (boutons, déplacement) mis en file pour l'interface */
static struct { int dx, dy, boutons; } FILE_SOURIS[64];
static int souris_tete, souris_queue;

int usb_souris(int *dx, int *dy, int *boutons) {
  if (souris_queue == souris_tete) return 0;
  *dx = FILE_SOURIS[souris_queue].dx; *dy = FILE_SOURIS[souris_queue].dy; *boutons = FILE_SOURIS[souris_queue].boutons;
  souris_queue = (souris_queue + 1) & 63;
  return 1;
}
int usb_nb_souris(void) { return nb_souris; }

static void rapport_souris(const volatile u8 *r) {
  int suivant = (souris_tete + 1) & 63;
  if (suivant == souris_queue) return;                  /* file pleine : l'interface ne suit pas */
  FILE_SOURIS[souris_tete].boutons = r[0] & 7;
  FILE_SOURIS[souris_tete].dx = (signed char)r[1];
  FILE_SOURIS[souris_tete].dy = (signed char)r[2];
  souris_tete = suivant;
}

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

static int nouvel_anneau(struct anneau *a) {              /* page déjà à lui (vidée) ou nouvelle */
  if (a->trbs) zero(a->trbs, 4096); else a->trbs = page();
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

/* point d'accès bloqué (refus « stall », erreur de transmission) ou muet : remis en route */
static void relancer(struct appareil *a, int dci, struct anneau *r) {
  u32 cible = (u32)dci << 16 | (u32)a->slot << 24;
  commande(a->hc, 0, T_RESET_EP << 10 | cible, 0);      /* sort de l'arrêt sur erreur (sinon : refus sans effet) */
  commande(a->hc, 0, T_STOP_EP << 10 | cible, 0);       /* arrête une attente en cours (idem) */
  commande(a->hc, (u64)&r->trbs[r->index] | r->cycle, T_DEQUEUE << 10 | cible, 0);   /* repart après */
}

static int requete(struct appareil *a, u8 type, u8 req, u16 valeur, u16 index, u16 longueur) {
  struct anneau *r = &a->ep0;
  u64 setup = type | (u64)req << 8 | (u64)valeur << 16 | (u64)index << 32 | (u64)longueur << 48;
  u32 trt = longueur ? ((type & 0x80) ? 3 : 2) : 0;
  poser(r, setup, 8, (T_SETUP << 10) | (1 << 6) | (trt << 16));
  if (longueur) poser(r, (u64)a->tampon, longueur, (T_DATA << 10) | ((type & 0x80) ? 1u << 16 : 0));
  u64 adresse = (u64)&r->trbs[r->index];
  poser(r, 0, 0, (T_STATUS << 10) | (1 << 5) | ((longueur && (type & 0x80)) ? 0 : 1u << 16));
  sonner(a->hc, a->slot, 1);
  if (attendre_fin(a->hc, T_TRANSFERT, adresse, a->slot, 0)) return 1;
  relancer(a, 1, r);                                    /* la requête suivante doit pouvoir passer */
  return 0;
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
  poser(&a->ep, (u64)a->rapport, (u32)a->longueur, (T_NORMAL << 10) | (1 << 5) | (1 << 2));
  sonner(a->hc, a->slot, a->dci);
}

/* --- Un appareil : adresse, descripteurs, puis clavier ou hub ------------------------------------- */
static int intervalle(int vitesse, int b_interval) {
  if (vitesse >= 3) { int v = b_interval - 1; return v < 0 ? 0 : v > 15 ? 15 : v; }   /* haut débit et plus */
  int v = 3; while ((1 << (v + 1)) <= b_interval * 8 && v < 10) v++;                  /* trames de 1 ms */
  return v;
}

/* contexte « appareil » : chemin, vitesse, hub (ses ports, son temps de réflexion), traducteur */
static void ecrire_slot(struct appareil *a, int entrees) {
  volatile u32 *s = ctx(a, 1);
  s[0] = a->route | (u32)a->vitesse << 20 | (u32)(a->hub ? 1 : 0) << 26 | (u32)entrees << 27;
  s[1] = (u32)a->port << 16 | (u32)(a->hub ? a->nb_ports_hub : 0) << 24;
  s[2] = (u32)a->tt_slot | (u32)a->tt_port << 8 | (u32)a->ttt << 16;
  s[3] = 0;
}

static void ecrire_ep_interruption(struct appareil *a, int mps, int b_interval) {
  volatile u32 *ep = ctx(a, a->dci + 1);
  ep[0] = (u32)intervalle(a->vitesse, b_interval) << 16;
  ep[1] = 3 << 1 | 7 << 3 | (u32)mps << 16;            /* 3 essais, interruption entrante */
  ep[2] = (u32)(u64)a->ep.trbs | 1;
  ep[3] = (u32)((u64)a->ep.trbs >> 32);
  ep[4] = (u32)a->longueur | (u32)mps << 16;
}

static struct appareil *place_libre(struct controleur *hc) {
  for (int i = 0; i < hc->nb_app; i++) if (!hc->app[i].slot) return &hc->app[i];
  return hc->nb_app < NB_APP ? &hc->app[hc->nb_app++] : 0;
}

static u32 tous_les_ports(struct appareil *h) { return ((1u << h->nb_ports_hub) - 1) << 1; }

/* parti : ce qui est branché derrière lui d'abord, puis son emplacement rendu au contrôleur */
static void debrancher(struct appareil *a) {
  struct controleur *hc = a->hc;
  for (int i = 0; i < hc->nb_app; i++)
    if (hc->app[i].slot && hc->app[i].parent == a) debrancher(&hc->app[i]);
  if (a->clavier) nb_claviers--;
  if (a->souris) nb_souris--;
  commande(hc, 0, T_DISABLE_SLOT << 10 | (u32)a->slot << 24, 0);
  hc->dcbaa[a->slot] = 0;
  if (a->parent) journal_nb("usb : appareil débranché d'un hub, port ", (u64)a->port_parent);
  else journal_nb("usb : appareil débranché du port ", (u64)a->port);
  a->clavier = 0; a->souris = 0; a->hub = 0; a->a_voir = 0; a->port = 0; a->parent = 0; a->slot = 0;
}

static int preparer_hub(struct appareil *a, int ep_mps) {
  if (a->vitesse >= 4) { journal("usb : hub USB 3 : seule sa partie USB 2 est gérée\n"); return 0; }
  if (a->etage >= 5) { journal("usb : trop de hubs à la suite\n"); return 0; }
  if (!requete(a, 0xA0, 6, 0x2900, 0, 9)) { journal("usb : descripteur du hub illisible\n"); return 0; }
  int n = a->tampon[2];
  if (!n) return 0;
  a->nb_ports_hub = n > 15 ? 15 : n;
  a->ttt = a->vitesse == 3 ? (a->tampon[3] >> 5) & 3 : 0;   /* temps de réflexion du traducteur */
  a->alim_ms = a->tampon[5] * 2;
  a->longueur = (n + 8) / 8 > ep_mps ? (n + 8) / 8 : ep_mps;
  if (a->longueur > 64) a->longueur = 64;
  a->hub = 1;
  return 1;
}

static void allumer_hub(struct appareil *a) {
  for (int p = 1; p <= a->nb_ports_hub; p++) requete(a, 0x23, 3, 8, (u16)p, 0);   /* PORT_POWER */
  dormir_ms(a->alim_ms > 100 ? (u64)a->alim_ms : 100);  /* courant établi, appareils présentés */
  a->a_voir = tous_les_ports(a);
}

/* un appareil vient d'être remis à zéro, son port est activé : on l'installe */
static void installer(struct controleur *hc, struct appareil *parent, int port_parent, int racine, int vitesse) {
  struct appareil *a = place_libre(hc);
  if (!a) { journal("usb : trop d'appareils\n"); return; }
  volatile u8 *pages[4] = {a->entree, a->sortie, a->tampon, a->rapport};
  volatile trb *anneaux[2] = {a->ep0.trbs, a->ep.trbs};
  zero(a, sizeof *a);
  a->entree = page_propre(pages[0]); a->sortie = page_propre(pages[1]);
  a->tampon = page_propre(pages[2]); a->rapport = page_propre(pages[3]);
  a->ep0.trbs = anneaux[0]; a->ep.trbs = anneaux[1];
  if (!a->entree || !a->sortie || !a->tampon || !a->rapport || !nouvel_anneau(&a->ep0)) return;
  a->hc = hc; a->parent = parent; a->port_parent = port_parent; a->port = racine; a->vitesse = vitesse;
  if (parent) {
    a->etage = parent->etage + 1;
    a->route = parent->route | (u32)(port_parent < 15 ? port_parent : 15) << (4 * parent->etage);
    if (vitesse == 1 || vitesse == 2) {                 /* lent derrière un hub : quel traducteur ? */
      if (parent->vitesse == 3) { a->tt_slot = parent->slot; a->tt_port = port_parent; }
      else { a->tt_slot = parent->tt_slot; a->tt_port = parent->tt_port; }
    }
  }
  trb r;
  if (!commande(hc, 0, T_ENABLE_SLOT << 10, &r)) { journal("usb : pas d'emplacement libre\n"); return; }
  a->slot = (int)(r.controle >> 24);
  if (a->slot <= 0 || a->slot > (int)hc->nb_slots) { a->slot = 0; return; }
  hc->dcbaa[a->slot] = (u64)a->sortie;
  int mps = vitesse >= 4 ? 512 : vitesse == 3 ? 64 : 8;
  ctx(a, 0)[1] = 3;                                     /* ajoute : appareil + EP0 */
  ecrire_slot(a, 1);
  volatile u32 *ep0 = ctx(a, 2);
  ep0[1] = 3 << 1 | 4 << 3 | (u32)mps << 16;            /* 3 essais, contrôle, taille des paquets */
  ep0[2] = (u32)(u64)a->ep0.trbs | 1;
  ep0[3] = (u32)((u64)a->ep0.trbs >> 32);
  ep0[4] = 8;
  if (!commande(hc, (u64)a->entree, T_ADDRESS << 10 | (u32)a->slot << 24, 0)) {
    journal_nb("usb : adressage refusé, port ", (u64)(parent ? port_parent : racine)); return;
  }
  if (!requete(a, 0x80, 6, 0x100, 0, 8)) { journal("usb : descripteur illisible\n"); return; }
  int vrai_mps = a->tampon[7];
  if (vitesse < 3 && vrai_mps && vrai_mps != mps) {   /* pleine vitesse : taille réelle d'EP0 */
    zero(a->entree, 4096);
    ctx(a, 0)[1] = 2;
    ctx(a, 2)[1] = 3 << 1 | 4 << 3 | (u32)vrai_mps << 16;
    ctx(a, 2)[2] = (u32)(u64)a->ep0.trbs | 1;
    ctx(a, 2)[3] = (u32)((u64)a->ep0.trbs >> 32);
    ctx(a, 2)[4] = 8;
    commande(hc, (u64)a->entree, T_EVALUATE << 10 | (u32)a->slot << 24, 0);
  }
  if (requete(a, 0x80, 6, 0x100, 0, 18)) {              /* descripteur complet : classe, fabricant, modèle */
    a->classe = a->tampon[4];
    a->vendeur = (u16)(a->tampon[8] | a->tampon[9] << 8);
    a->produit = (u16)(a->tampon[10] | a->tampon[11] << 8);
  }
  if (!requete(a, 0x80, 6, 0x200, 0, 9)) return;        /* configuration : longueur totale */
  int total = a->tampon[2] | a->tampon[3] << 8, valeur = a->tampon[5];
  if (total > 1024) total = 1024;
  if (total < 9 || !requete(a, 0x80, 6, 0x200, 0, (u16)total)) return;
  /* une interface (réglage 0) de clavier de démarrage (3/1/1), de souris de démarrage (3/1/2) ou de
   * hub (9), et son point entrant ; le clavier passe avant la souris d'un même appareil */
  int genre = 0, courant = 0, iface_courante = 0, iface = 0, ep_adresse = 0, ep_mps = 8, ep_intervalle = 10;
  for (int i = 0; i + 1 < total && a->tampon[i] >= 2; i += a->tampon[i]) {
    const volatile u8 *d = a->tampon + i;
    if (d[1] == 4) {
      if (!a->classe) a->classe = d[5];                 /* classe donnée par les interfaces : la première */
      iface_courante = d[2];
      courant = d[3] ? 0 : d[5] == 3 && d[6] == 1 && d[7] == 1 ? 1 : d[5] == 9 ? 2 :
                d[5] == 3 && d[6] == 1 && d[7] == 2 ? 3 : 0;
    } else if (d[1] == 5 && courant && (!ep_adresse || (genre == 3 && courant == 1)) && (d[2] & 0x80) && (d[3] & 3) == 3) {
      genre = courant; iface = iface_courante;
      ep_adresse = d[2]; ep_mps = d[4] | (d[5] & 7) << 8; ep_intervalle = d[6];
    }
  }
  if (!genre) { journal_nb("usb : appareil (pas un clavier) sur le port ", (u64)(parent ? port_parent : racine)); return; }
  requete(a, 0x00, 9, (u16)valeur, 0, 0);               /* SET_CONFIGURATION */
  a->interface = iface;
  a->dci = (ep_adresse & 15) * 2 + 1;
  if (genre == 2 && !preparer_hub(a, ep_mps)) return;
  if (genre == 1 || genre == 3) {
    requete(a, 0x21, 0x0B, 0, (u16)iface, 0);           /* SET_PROTOCOL : protocole de démarrage */
    if (genre == 1) requete(a, 0x21, 0x0A, 0, (u16)iface, 0);   /* SET_IDLE : rapport seulement au changement */
    a->longueur = ep_mps > 64 ? 64 : ep_mps > 8 ? ep_mps : 8;
  }
  if (!nouvel_anneau(&a->ep)) return;
  zero(a->entree, 4096);
  ctx(a, 0)[1] = 1 | 1u << a->dci;                      /* appareil (pour un hub : ses ports) + le point */
  ecrire_slot(a, a->dci);
  ecrire_ep_interruption(a, ep_mps, ep_intervalle);
  if (!commande(hc, (u64)a->entree, T_CONFIGURE << 10 | (u32)a->slot << 24, 0)) {
    journal("usb : le contrôleur refuse la configuration\n"); a->hub = 0; return;
  }
  if (genre == 1) {
    a->clavier = 1;
    nb_claviers++;
    if (parent) journal_nb("usb : clavier prêt derrière un hub, port ", (u64)port_parent);
    else journal_nb("usb : clavier prêt sur le port ", (u64)racine);
  } else if (genre == 3) {
    a->souris = 1;
    nb_souris++;
    journal_nb("usb : souris prête sur le port ", (u64)(parent ? port_parent : racine));
  } else {
    journal_nb("usb : hub prêt, ports : ", (u64)a->nb_ports_hub);
    allumer_hub(a);
  }
  demander_rapport(a);
}

/* port du contrôleur : remise à zéro (USB 2 ; l'USB 3 s'en charge seul), puis installation */
static void brancher(struct controleur *hc, int port) {
  u32 o = 0x400 + 0x10 * (port - 1);
  u32 ps = lire32(hc->op, o);
  if (!(ps & 1)) return;
  if (hc->usb2[port]) {
    ecrire32(hc->op, o, port_neutre(ps) | (1 << 4));
    if (!ATTENDRE(lire32(hc->op, o) & (1 << 21), 25)) { journal_nb("usb : port sans réponse ", (u64)port); return; }
    ecrire32(hc->op, o, port_neutre(lire32(hc->op, o)) | (1 << 21) | (1 << 17));
    dormir_ms(20);
  }
  ps = lire32(hc->op, o);
  if (!(ps & 2)) { journal_nb("usb : port pas activé ", (u64)port); return; }
  installer(hc, 0, 0, port, (int)((ps >> 10) & 15));
}

/* port d'un hub : remise à zéro demandée au hub, vitesse lue chez lui, puis installation */
static void brancher_sur_hub(struct appareil *h, int p) {
  dormir_ms(100);                                       /* le contact se stabilise */
  if (!requete(h, 0x23, 3, 4, (u16)p, 0)) return;       /* SET_FEATURE PORT_RESET */
  u16 etat = 0, chg = 0;
  for (int n = 0; n < 50; n++) {                        /* la remise à zéro dure 10 à 20 ms */
    dormir_ms(10);
    if (!requete(h, 0xA3, 0, 0, (u16)p, 4)) return;
    etat = (u16)(h->tampon[0] | h->tampon[1] << 8);
    chg = (u16)(h->tampon[2] | h->tampon[3] << 8);
    if ((chg & 0x10) || !(etat & 0x10)) break;
  }
  if (chg & 0x10) requete(h, 0x23, 1, 20, (u16)p, 0);   /* CLEAR_FEATURE C_PORT_RESET */
  if (!(etat & 1) || !(etat & 2) || (etat & 0x10)) { journal_nb("usb : port de hub pas activé ", (u64)p); return; }
  dormir_ms(10);                                        /* repos après la remise à zéro */
  installer(h->hc, h, p, h->port, etat & 0x200 ? 2 : etat & 0x400 ? 3 : 1);
}

static struct appareil *enfant(struct appareil *h, int p) {
  for (int i = 0; i < h->hc->nb_app; i++) {
    struct appareil *a = &h->hc->app[i];
    if (a->slot && a->parent == h && a->port_parent == p) return a;
  }
  return 0;
}

/* ports signalés par le hub : état lu, changements acquittés, appareil installé ou retiré */
static void examiner_hub(struct appareil *h) {
  u32 a_voir = h->a_voir;
  h->a_voir = 0;
  for (int p = 1; p <= h->nb_ports_hub && h->slot; p++) {
    if (!((a_voir >> p) & 1)) continue;
    if (!requete(h, 0xA3, 0, 0, (u16)p, 4)) continue;   /* GET_STATUS du port */
    u16 etat = (u16)(h->tampon[0] | h->tampon[1] << 8), chg = (u16)(h->tampon[2] | h->tampon[3] << 8);
    for (int f = 0; f < 5; f++)
      if ((chg >> f) & 1) requete(h, 0x23, 1, (u16)(16 + f), (u16)p, 0);   /* CLEAR_FEATURE C_PORT_… */
    struct appareil *e = enfant(h, p);
    if (e && (!(etat & 1) || (chg & 1) || !(etat & 2))) { debrancher(e); e = 0; }   /* parti ou rebranché */
    if ((etat & 1) && !e) brancher_sur_hub(h, p);
  }
}

/* événement lu dans l'anneau : rien de long ici (pas de requête), seulement noter ou relancer */
static void traiter(struct controleur *hc, const trb *e) {
  int t = (e->controle >> 10) & 63;
  if (t == T_PORT) {
    int port = (int)(e->param >> 24);
    if (port > 0 && port <= (int)hc->nb_ports) hc->changement[port] = 1;
  } else if (t == T_TRANSFERT) {
    int slot = (int)(e->controle >> 24), dci = (int)((e->controle >> 16) & 31);
    u32 code = e->statut >> 24;
    int ok = code == 1 || code == 13;
    for (int i = 0; i < hc->nb_app; i++) {
      struct appareil *a = &hc->app[i];
      if (!a->slot || a->slot != slot || a->dci != dci || !(a->clavier || a->hub || a->souris)) continue;
      if (!ok) { a->panne = 1; journal_nb("usb : erreur sur le point « interruption », code ", code); continue; }
      a->pannes = 0;
      if (a->clavier) { u8 r[8]; for (int k = 0; k < 8; k++) r[k] = a->rapport[k]; rapport(a, r); }
      else if (a->souris) rapport_souris(a->rapport);
      else a->a_voir |= (a->rapport[0] | (u32)a->rapport[1] << 8) & tous_les_ports(a);
      demander_rapport(a);
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
  if (!bar || !noyau_mapper(bar, 0x10000)) return 0;
  hc->cap = (volatile u8 *)bar;
  if (lire32(hc->cap, 0) == 0xFFFFFFFFu) { journal("usb : contrôleur muet, laissé de côté\n"); return 0; }
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

static int hubs_en_attente(void) {
  for (int h = 0; h < nb_hc; h++)
    for (int i = 0; i < HC[h].nb_app; i++)
      if (HC[h].app[i].slot && HC[h].app[i].hub && HC[h].app[i].a_voir) return 1;
  return 0;
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
        reveiller_pci(bus, dev, fn);
        u32 bar0 = pci_lire(bus, dev, fn, 0x10);
        u64 bar = bar0 & ~0xFULL;
        if (((bar0 >> 1) & 3) == 2) bar |= (u64)pci_lire(bus, dev, fn, 0x14) << 32;
        pci_ecrire(bus, dev, fn, 4, pci_lire(bus, dev, fn, 4) | 6);   /* mémoire + maître du bus */
        journal_hex("usb : contrôleur xHCI à ", bar);
        if (preparer(&HC[nb_hc], bar)) nb_hc++;
      }
    }
  for (int tour = 0; tour < 8 && hubs_en_attente(); tour++) usb_sonder();   /* claviers derrière des hubs */
  return nb_hc;
}

void usb_sonder(void) {
  for (int h = 0; h < nb_hc; h++) {
    struct controleur *hc = &HC[h];
    trb e;
    while (evenement(hc, &e)) traiter(hc, &e);
    for (u32 p = 1; p <= hc->nb_ports; p++) {           /* ports du contrôleur */
      if (!hc->changement[p]) continue;
      hc->changement[p] = 0;
      u32 o = 0x400 + 0x10 * (p - 1), ps = lire32(hc->op, o);
      ecrire32(hc->op, o, port_neutre(ps) | (ps & (0x7Fu << 17)));
      int deja = 0;
      for (int i = 0; i < hc->nb_app; i++) {
        struct appareil *a = &hc->app[i];
        if (!a->slot || a->parent || a->port != (int)p) continue;
        if (!(ps & 1) || (ps & (1 << 17))) debrancher(a);   /* parti, ou débranché puis rebranché */
        else deja = 1;
      }
      if ((ps & 1) && !deja && (ps & (1 << 17))) brancher(hc, (int)p);
    }
    for (int i = 0; i < hc->nb_app; i++) {
      struct appareil *a = &hc->app[i];
      if (!a->slot || !(a->clavier || a->hub || a->souris)) continue;
      if (a->panne) {                                   /* point « interruption » en erreur : relancé */
        a->panne = 0;
        if (++a->pannes <= 5) { relancer(a, a->dci, &a->ep); demander_rapport(a); }
        else if (a->hub) a->sonde_lente = 1;            /* le hub ne prévient plus : on regarde chaque seconde */
        if (a->hub) a->a_voir |= tous_les_ports(a);
      }
      if (a->hub && a->sonde_lente && noyau_tics() >= a->prochaine_sonde) {
        a->a_voir |= tous_les_ports(a);
        a->prochaine_sonde = noyau_tics() + 50;
      }
      if (a->hub && a->a_voir) examiner_hub(a);
      if (a->clavier && a->repete && noyau_tics() >= a->repete_a) {   /* touche maintenue */
        emettre(a->repete, 0);
        a->repete_a = noyau_tics() + 2;
      }
    }
  }
}

int usb_claviers(void) { return nb_claviers; }

static void ajouter(char *d, int *i, int max, const char *t) { while (*t && *i < max - 1) d[(*i)++] = *t++; d[*i] = 0; }
static void ajouter_nb(char *d, int *i, int max, u64 v, int base, int chiffres) {
  char x[24]; int n = 0;
  do { x[n++] = "0123456789abcdef"[v % (u64)base]; v /= (u64)base; } while ((v || n < chiffres) && n < 22);
  while (n && *i < max - 1) d[(*i)++] = x[--n];
  d[*i] = 0;
}

void usb_etat(char *d, int max) {
  int i = 0, hubs = 0;
  for (int h = 0; h < nb_hc; h++)
    for (int k = 0; k < HC[h].nb_app; k++) hubs += HC[h].app[k].slot && HC[h].app[k].hub;
  d[0] = 0;
  if (!nb_hc) { ajouter(d, &i, max, "USB : aucun contrôleur xHCI"); return; }
  ajouter(d, &i, max, nb_claviers ? "USB : clavier USB prêt" : "USB : contrôleur prêt, aucun clavier");
  if (nb_souris) ajouter(d, &i, max, ", souris prête");
  if (hubs) { ajouter(d, &i, max, " ("); ajouter_nb(d, &i, max, (u64)hubs, 10, 1);
              ajouter(d, &i, max, hubs > 1 ? " hubs)" : " hub)"); }
}

static const char *genre_appareil(const struct appareil *a) {
  if (a->clavier) return "clavier";
  if (a->souris) return "souris";
  if (a->hub) return "hub";
  switch (a->classe) {
    case 1: return "audio";
    case 2: case 0x0A: return "communication";
    case 3: return "HID (pas un clavier simple)";
    case 6: return "images";
    case 7: return "imprimante";
    case 8: return "stockage";
    case 9: return "hub (non géré)";
    case 0x0B: return "carte à puce";
    case 0x0E: return "caméra";
    case 0xE0: return "sans fil (Bluetooth)";
    case 0xEF: return "composite";
    case 0xFF: return "propre au fabricant";
    default: return "appareil";
  }
}

int usb_decrire(int n, char *d, int max) {
  static const char *VITESSES[] = {"?", "pleine vitesse", "basse vitesse", "haut débit", "USB 3", "USB 3", "USB 3", "USB 3"};
  for (int h = 0; h < nb_hc; h++)
    for (int k = 0; k < HC[h].nb_app; k++) {
      struct appareil *a = &HC[h].app[k];
      if (!a->slot || n-- > 0) continue;
      int i = 0;
      d[0] = 0;
      if (nb_hc > 1) { ajouter(d, &i, max, "contrôleur "); ajouter_nb(d, &i, max, (u64)h + 1, 10, 1); ajouter(d, &i, max, ", "); }
      ajouter(d, &i, max, "port "); ajouter_nb(d, &i, max, (u64)a->port, 10, 1);
      for (int e = 0; e < a->etage; e++) { ajouter(d, &i, max, " → "); ajouter_nb(d, &i, max, (a->route >> (4 * e)) & 15, 10, 1); }
      ajouter(d, &i, max, " : "); ajouter(d, &i, max, genre_appareil(a));
      ajouter(d, &i, max, ", "); ajouter(d, &i, max, VITESSES[a->vitesse & 7]);
      ajouter(d, &i, max, " ("); ajouter_nb(d, &i, max, a->vendeur, 16, 4); ajouter(d, &i, max, ":");
      ajouter_nb(d, &i, max, a->produit, 16, 4); ajouter(d, &i, max, ")");
      return 1;
    }
  return 0;
}
