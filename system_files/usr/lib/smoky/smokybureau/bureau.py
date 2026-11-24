"""Smoky OS — le bureau : fond d'écran, barre, dock, lanceur, réglages rapides, bulles et
notifications. Un seul programme, lancé par systemd (smoky-bureau.service), relancé s'il tombe.

Règles d'autonomie : aucune minuterie de moins d'une seconde, l'heure à la minute, la batterie
toutes les 30 s, rien ne se redessine quand rien ne change, pas d'animation continue.
"""
import ctypes
import json
import os
import subprocess
import threading
import time
import unicodedata

for _nom in ("libgtk4-layer-shell.so.0", "libgtk4-layer-shell.so"):   # doit précéder libwayland
    try:
        ctypes.CDLL(_nom)
        break
    except OSError:
        pass

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

from . import commun, reseau, wayland  # noqa: E402

JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
PPD = ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles")
PROFILS = [("power-saver", "Économie"), ("balanced", "Équilibré"), ("performance", "Performance")]

INTERFACE = """<node>
 <interface name="fr.smoky.Bureau">
  <method name="Lanceur"/>
  <method name="Panneau"/>
  <method name="Bulle"><arg type="s" name="genre" direction="in"/><arg type="i" name="valeur" direction="in"/></method>
  <method name="Ecran"><arg type="b" name="allume" direction="in"/><arg type="b" name="fait" direction="out"/></method>
  <method name="Etat"><arg type="s" name="json" direction="out"/></method>
 </interface>
 <interface name="org.freedesktop.Notifications">
  <method name="GetCapabilities"><arg type="as" direction="out"/></method>
  <method name="Notify">
   <arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
   <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
   <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/>
  </method>
  <method name="CloseNotification"><arg type="u" direction="in"/></method>
  <method name="GetServerInformation">
   <arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/>
  </method>
  <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
  <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
 </interface>
</node>"""


def couche(fenetre, niveau, bords=(), marges=None, exclusif=None, clavier=None, espace="smoky"):
    """Pose une fenêtre au bord de l'écran (protocole layer-shell)."""
    LS.init_for_window(fenetre)
    LS.set_layer(fenetre, niveau)
    LS.set_namespace(fenetre, espace)
    for bord in bords:
        LS.set_anchor(fenetre, bord, True)
    for bord, px in (marges or {}).items():
        LS.set_margin(fenetre, bord, px)
    if exclusif == "auto":
        LS.auto_exclusive_zone_enable(fenetre)
    elif exclusif is not None:
        LS.set_exclusive_zone(fenetre, exclusif)
    LS.set_keyboard_mode(fenetre, clavier or LS.KeyboardMode.NONE)


def sans_accents(texte):
    return "".join(c for c in unicodedata.normalize("NFD", texte.casefold()) if unicodedata.category(c) != "Mn")


def icone(nom, taille=16):
    img = Gtk.Image.new_from_icon_name(nom)
    img.set_pixel_size(taille)
    return img


def appui_long_ou_droit(widget, rappel):
    """Clic droit ou appui long (tactile) sur un widget → rappel()."""
    droit = Gtk.GestureClick(button=3)
    droit.connect("pressed", lambda *a: rappel())
    widget.add_controller(droit)
    long = Gtk.GestureLongPress(touch_only=True)
    long.connect("pressed", lambda *a: rappel())
    widget.add_controller(long)


class Appli:
    """Une appli du dock ou du lanceur (fichier .desktop)."""

    def __init__(self, info):
        self.info = info
        self.id = info.get_id() or ""
        self.nom = info.get_display_name() or self.id
        cles = [self.id.removesuffix(".desktop"), info.get_startup_wm_class() or ""]
        self.cles = {c.casefold() for c in cles if c}
        self.recherche = sans_accents(" ".join(filter(None, [self.nom, info.get_generic_name() or "",
                                                              " ".join(info.get_keywords() or [])])))

    def correspond(self, appli_id):
        a = appli_id.casefold()
        return a in self.cles or any(c.endswith("." + a) for c in self.cles)

    def lancer(self):
        try:
            self.info.launch([], Gdk.Display.get_default().get_app_launch_context())
        except GLib.Error as e:
            print("lancement impossible :", self.id, e.message, flush=True)


def appli(desktop_id):
    try:
        info = Gio.DesktopAppInfo.new(desktop_id)
    except (TypeError, GLib.Error):
        info = None
    return Appli(info) if info else None


class Bureau(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="fr.smoky.BureauGtk", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.batterie = commun.Batterie()
        self.fenetres = None
        self.notifs = {}
        self.prochain_notif = 1
        self.connexion_dbus = None
        self.panneau_confirmer = None
        self.historique = []                  # dernières notifications (montrées dans les réglages rapides)
        self.ne_pas_deranger = False

    # --- démarrage ---------------------------------------------------------------------
    def do_activate(self):
        self.hold()
        css = Gtk.CssProvider()
        css.load_from_path(str(commun.CSS))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.ecran = Gdk.Display.get_default().get_monitors().get_item(0)
        self.creer_fonds()
        self.creer_barre()
        self.creer_dock()
        self.creer_lanceur()
        self.creer_panneau()
        self.creer_bulle()
        self.creer_notifications()
        self.connecter_wayland()
        self.surveiller_reglages()
        self.tic_minute()
        GLib.timeout_add_seconds(30, self.tic_batterie)
        self.tic_batterie()
        self.surveiller_reseau()
        if commun.lire_json(commun.BUREAU, {}).get("nuit"):
            subprocess.Popen(["systemctl", "--user", "start", "smoky-nuit.service"])
        Gio.bus_own_name(Gio.BusType.SESSION, "fr.smoky.Bureau", Gio.BusNameOwnerFlags.NONE,
                         self.bus_obtenu, None, lambda *a: print("nom D-Bus perdu", flush=True))
        Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications",
                         Gio.BusNameOwnerFlags.REPLACE, None, None, None)

    # --- fond d'écran (un par écran) -------------------------------------------------------
    def creer_fonds(self):
        self.fonds = []
        moniteurs = Gdk.Display.get_default().get_monitors()
        for i in range(moniteurs.get_n_items()):
            w = Gtk.Window(application=self)
            w.add_css_class("smoky-fond")
            couche(w, LS.Layer.BACKGROUND, (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT),
                   exclusif=-1, espace="smoky-fond")
            LS.set_monitor(w, moniteurs.get_item(i))
            image = Gtk.Picture.new_for_filename(commun.fond_ecran())
            image.set_content_fit(Gtk.ContentFit.COVER)
            w.set_child(image)
            appui_long_ou_droit(image, self.menu_secours)
            w.present()
            self.fonds.append(w)

    def menu_secours(self):
        self.ouvrir_lanceur()

    # --- barre ---------------------------------------------------------------------------
    def creer_barre(self):
        w = self.barre = Gtk.Window(application=self)
        w.add_css_class("smoky-barre")
        couche(w, LS.Layer.TOP, (LS.Edge.TOP, LS.Edge.LEFT, LS.Edge.RIGHT), exclusif="auto", espace="smoky-barre")
        LS.set_monitor(w, self.ecran)
        boite = Gtk.CenterBox()
        gauche = Gtk.Box(spacing=6)
        b = Gtk.Button(css_classes=["barre-bouton", "bouton-applis"], tooltip_text="Applications (touche Windows)")
        b.set_child(Gtk.Label(label="Smoky", css_classes=["marque"]))
        b.connect("clicked", lambda *a: self.ouvrir_lanceur())
        gauche.append(b)
        self.titre = Gtk.Label(css_classes=["titre-fenetre"], ellipsize=Pango.EllipsizeMode.END, max_width_chars=48,
                               single_line_mode=True, valign=Gtk.Align.CENTER, visible=False)
        gauche.append(self.titre)
        self.horloge = Gtk.Button(css_classes=["barre-bouton", "horloge"], tooltip_text="Agenda")
        self.horloge.connect("clicked", lambda *a: subprocess.Popen(["/usr/bin/smoky", "--aller", "/agenda"]))
        droite = Gtk.Button(css_classes=["barre-bouton", "etat"], tooltip_text="Réglages rapides")
        etat = Gtk.Box(spacing=8)
        self.icone_reseau = icone("network-wireless-offline-symbolic")
        self.icone_son = icone("audio-volume-high-symbolic")
        self.icone_batterie = icone("battery-level-100-symbolic")
        self.texte_batterie = Gtk.Label(css_classes=["batterie"])
        for x in (self.icone_reseau, self.icone_son, self.icone_batterie, self.texte_batterie):
            etat.append(x)
        droite.set_child(etat)
        droite.connect("clicked", lambda *a: self.basculer_panneau())
        boite.set_start_widget(gauche)
        boite.set_center_widget(self.horloge)
        boite.set_end_widget(droite)
        w.set_child(boite)
        w.present()

    def tic_minute(self):
        t = time.localtime()
        self.horloge.set_label(f"{JOURS[t.tm_wday]} {t.tm_mday} {MOIS[t.tm_mon - 1]}   {t.tm_hour:02d}:{t.tm_min:02d}")
        GLib.timeout_add_seconds(60 - t.tm_sec, self.tic_minute)
        return False

    def tic_batterie(self):
        e = self.batterie.etat()
        if e is None or e["niveau"] is None:
            self.icone_batterie.set_visible(False)
            self.texte_batterie.set_visible(False)
            return True
        n, charge = e["niveau"], e["statut"] in ("Charging", "Full", "Not charging")
        palier = min(100, max(0, round(n / 10) * 10))
        self.icone_batterie.set_from_icon_name(f"battery-level-{palier}{'-charging' if charge else ''}-symbolic")
        self.texte_batterie.set_label(f"{n} %")
        bas = n <= 15 and not charge
        for x in (self.texte_batterie, self.icone_batterie):
            (x.add_css_class if bas else x.remove_css_class)("faible")
        self.etat_batterie = e
        return True

    def surveiller_reseau(self):
        try:
            self.systeme = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        except GLib.Error:
            self.systeme = None
            return
        self.systeme.signal_subscribe("org.freedesktop.NetworkManager", "org.freedesktop.DBus.Properties",
                                      "PropertiesChanged", "/org/freedesktop/NetworkManager", None,
                                      Gio.DBusSignalFlags.NONE, lambda *a: self.maj_reseau())
        self.maj_reseau()
        self.maj_son()

    def maj_reseau(self):
        sortie = commun.commande("nmcli", "-t", "-f", "TYPE,STATE", "device", delai=4)
        actifs = [l.split(":")[0] for l in sortie.splitlines() if l.endswith(":connected")]
        nom = ("network-wireless-signal-good-symbolic" if "wifi" in actifs else
               "network-wired-symbolic" if "ethernet" in actifs else "network-wireless-offline-symbolic")
        self.icone_reseau.set_from_icon_name(nom)
        return False

    def maj_son(self, pourcent=None, muet=None):
        if pourcent is None:
            pourcent, muet = commun.volume()
        if pourcent is None:
            self.icone_son.set_visible(False)
            return
        nom = ("audio-volume-muted-symbolic" if muet or pourcent == 0 else "audio-volume-low-symbolic"
               if pourcent < 34 else "audio-volume-medium-symbolic" if pourcent < 67 else "audio-volume-high-symbolic")
        self.icone_son.set_from_icon_name(nom)

    # --- dock ----------------------------------------------------------------------------
    def creer_dock(self):
        w = self.dock = Gtk.Window(application=self)
        w.add_css_class("smoky-dock-fenetre")
        couche(w, LS.Layer.TOP, (LS.Edge.BOTTOM,), marges={LS.Edge.BOTTOM: 8}, exclusif=0, espace="smoky-dock")
        LS.set_monitor(w, self.ecran)
        self.boite_dock = Gtk.Box(css_classes=["dock"], spacing=4)
        w.set_child(self.boite_dock)
        survol = Gtk.EventControllerMotion()
        survol.connect("enter", lambda *a: self.montrer_dock(True))
        survol.connect("leave", lambda *a: self.cacher_dock_bientot())
        w.add_controller(survol)
        # poignée invisible au bas de l'écran : la souris ou le doigt fait apparaître le dock
        p = self.poignee = Gtk.Window(application=self)
        p.add_css_class("smoky-poignee")
        couche(p, LS.Layer.TOP, (LS.Edge.BOTTOM,), exclusif=0, espace="smoky-poignee")
        LS.set_monitor(p, self.ecran)
        zone = Gtk.Box()
        zone.set_size_request(640, 4)
        p.set_child(zone)
        s2 = Gtk.EventControllerMotion()
        s2.connect("enter", lambda *a: self.montrer_dock(True))
        p.add_controller(s2)
        toucher = Gtk.GestureClick()
        toucher.connect("pressed", lambda *a: self.montrer_dock(True))
        p.add_controller(toucher)
        p.present()
        self.dock_survole = False
        self.minuterie_dock = 0
        self.maj_dock()

    def montrer_dock(self, survole):
        self.dock_survole = survole
        if self.minuterie_dock:
            GLib.source_remove(self.minuterie_dock)
            self.minuterie_dock = 0
        self.dock.set_visible(True)

    def cacher_dock_bientot(self):
        self.dock_survole = False
        if not self.minuterie_dock:
            self.minuterie_dock = GLib.timeout_add(900, self.cacher_dock)

    def cacher_dock(self):
        self.minuterie_dock = 0
        if not self.dock_survole and self.fenetres_visibles():
            self.dock.set_visible(False)
        return False

    def fenetres_visibles(self):
        if self.fenetres is None:
            return False
        return any("reduite" not in f.etats for f in self.fenetres.fenetres.values())

    def maj_dock(self):
        enfant = self.boite_dock.get_first_child()
        while enfant:
            suivant = enfant.get_next_sibling()
            self.boite_dock.remove(enfant)
            enfant = suivant
        taille = 64 if commun.lire_json(commun.ADAPTIVE, {}).get("tablet_mode") else 48
        fenetres = list(self.fenetres.fenetres.values()) if self.fenetres else []
        favoris = [a for a in (appli(d) for d in commun.dock()) if a]
        vues = set()
        for a in favoris:
            siennes = [f for f in fenetres if a.correspond(f.appli)]
            vues.update(f.id for f in siennes)
            self.boite_dock.append(self.bouton_dock(a, siennes, taille, favori=True))
        autres = {}
        for f in fenetres:
            if f.id not in vues and f.parent is None:
                autres.setdefault(f.appli, []).append(f)
        if autres:
            self.boite_dock.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, css_classes=["dock-separateur"]))
            for appli_id, siennes in autres.items():
                a = appli(appli_id + ".desktop") or self.appli_par_cle(appli_id)
                self.boite_dock.append(self.bouton_dock(a, siennes, taille, favori=False, appli_id=appli_id))
        if not self.fenetres_visibles():
            self.dock.set_visible(True)
        elif not self.dock_survole and not self.minuterie_dock:
            self.dock.set_visible(False)
        actives = [f for f in fenetres if "active" in f.etats]
        self.titre.set_label(actives[0].titre if actives else "")
        self.titre.set_visible(bool(actives and actives[0].titre))
        return False

    def appli_par_cle(self, appli_id):
        for info in Gio.AppInfo.get_all():
            if isinstance(info, Gio.DesktopAppInfo):
                a = Appli(info)
                if a.correspond(appli_id):
                    return a
        return None

    def bouton_dock(self, a, siennes, taille, favori, appli_id=""):
        b = Gtk.Button(css_classes=["dock-bouton"], tooltip_text=a.nom if a else appli_id)
        pile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        img = Gtk.Image.new_from_gicon(a.info.get_icon()) if a and a.info.get_icon() else \
            Gtk.Image.new_from_icon_name("application-x-executable")
        img.set_pixel_size(taille)
        pile.append(img)
        point = Gtk.Box(css_classes=["dock-point"] + (["ouvert"] if siennes else []), halign=Gtk.Align.CENTER)
        pile.append(point)
        b.set_child(pile)

        def clic(*_):
            if siennes:
                active = [f for f in siennes if "active" in f.etats]
                if active and len(siennes) == 1:
                    active[0].reduire()
                else:
                    cible = next((f for f in siennes if "active" not in f.etats), siennes[0])
                    cible.activer()
            elif a:
                a.lancer()
            self.cacher_dock_bientot()
        b.connect("clicked", clic)
        appui_long_ou_droit(b, lambda: self.menu_dock(b, a, siennes, favori))
        return b

    def menu_dock(self, bouton, a, siennes, favori):
        pop = Gtk.Popover(css_classes=["menu-dock"])
        pop.set_parent(bouton)
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        def entree(texte, action):
            e = Gtk.Button(label=texte, css_classes=["menu-entree"])
            e.connect("clicked", lambda *x: (pop.popdown(), action(), GLib.idle_add(self.maj_dock)))
            boite.append(e)
        if a:
            entree("Nouvelle fenêtre", a.lancer)
        if siennes:
            entree("Fermer" if len(siennes) == 1 else f"Fermer les {len(siennes)} fenêtres",
                   lambda: [f.fermer() for f in siennes])
        if a and favori:
            entree("Retirer du dock", lambda: commun.enregistrer_dock([d for d in commun.dock() if d != a.id]))
        elif a and a.id:
            entree("Garder dans le dock", lambda: commun.enregistrer_dock(commun.dock() + [a.id]))
        pop.set_child(boite)
        self.dock_survole = True
        pop.connect("closed", lambda *x: (pop.unparent(), self.cacher_dock_bientot()))
        pop.popup()

    # --- lanceur -------------------------------------------------------------------------
    def creer_lanceur(self):
        w = self.lanceur = Gtk.Window(application=self)
        w.add_css_class("smoky-lanceur")
        couche(w, LS.Layer.OVERLAY, (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT),
               exclusif=-1, clavier=LS.KeyboardMode.EXCLUSIVE, espace="smoky-lanceur")
        LS.set_monitor(w, self.ecran)
        fond = Gtk.Overlay()
        voile = Gtk.Box(css_classes=["voile"], hexpand=True, vexpand=True)
        clic = Gtk.GestureClick()
        clic.connect("released", lambda *a: self.fermer_lanceur())
        voile.add_controller(clic)
        fond.set_child(voile)
        centre = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, css_classes=["lanceur"],
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self.recherche = Gtk.SearchEntry(placeholder_text="Chercher une appli", css_classes=["recherche"])
        self.recherche.connect("search-changed", lambda *a: self.grille.invalidate_filter())
        self.recherche.connect("activate", lambda *a: self.lancer_premiere())
        self.recherche.connect("stop-search", lambda *a: self.fermer_lanceur())
        centre.set_size_request(860, -1)
        centre.append(self.recherche)
        defile = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                    max_content_height=620, min_content_width=760)
        self.grille = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                                  min_children_per_line=6, homogeneous=True, row_spacing=6, column_spacing=6)
        self.grille.set_filter_func(self.filtre_lanceur)
        defile.set_child(self.grille)
        centre.append(defile)
        fond.add_overlay(centre)
        w.set_child(fond)
        touches = Gtk.EventControllerKey()
        touches.connect("key-pressed", lambda c, k, *r: (self.fermer_lanceur() or True) if k == Gdk.KEY_Escape else False)
        w.add_controller(touches)
        self.applis_lanceur = None
        Gio.AppInfoMonitor.get().connect("changed", lambda *a: setattr(self, "applis_lanceur", None))

    def remplir_lanceur(self):
        while (enfant := self.grille.get_first_child()):
            self.grille.remove(enfant)
        infos = [i for i in Gio.AppInfo.get_all() if isinstance(i, Gio.DesktopAppInfo) and i.should_show()]
        self.applis_lanceur = sorted((Appli(i) for i in infos), key=lambda a: sans_accents(a.nom))
        for a in self.applis_lanceur:
            b = Gtk.Button(css_classes=["lanceur-appli"])
            pile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            img = Gtk.Image.new_from_gicon(a.info.get_icon()) if a.info.get_icon() else icone("application-x-executable")
            img.set_pixel_size(56)
            pile.append(img)
            pile.append(Gtk.Label(label=a.nom, ellipsize=Pango.EllipsizeMode.END, max_width_chars=14))
            b.set_child(pile)
            b.connect("clicked", lambda _b, a=a: (a.lancer(), self.fermer_lanceur()))
            b.appli = a
            self.grille.append(b)

    def filtre_lanceur(self, enfant):
        texte = sans_accents(self.recherche.get_text().strip())
        return not texte or texte in enfant.get_child().appli.recherche

    def lancer_premiere(self):
        enfant = self.grille.get_first_child()
        while enfant:
            if enfant.get_child_visible() and self.filtre_lanceur(enfant):
                enfant.get_child().appli.lancer()
                self.fermer_lanceur()
                return
            enfant = enfant.get_next_sibling()

    def ouvrir_lanceur(self):
        if self.lanceur.get_visible():
            self.fermer_lanceur()
            return
        if self.applis_lanceur is None:
            self.remplir_lanceur()
        self.recherche.set_text("")
        self.lanceur.present()
        self.recherche.grab_focus()

    def fermer_lanceur(self):
        self.lanceur.set_visible(False)

    # --- réglages rapides --------------------------------------------------------------------
    def creer_panneau(self):
        w = self.panneau = Gtk.Window(application=self)
        w.add_css_class("smoky-panneau-fenetre")
        couche(w, LS.Layer.OVERLAY, (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT),
               exclusif=-1, clavier=LS.KeyboardMode.ON_DEMAND, espace="smoky-panneau")
        LS.set_monitor(w, self.ecran)
        fond = Gtk.Overlay()
        vide = Gtk.Box(hexpand=True, vexpand=True)
        clic = Gtk.GestureClick()
        clic.connect("released", lambda *a: self.panneau.set_visible(False))
        vide.add_controller(clic)
        fond.set_child(vide)
        p = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, css_classes=["panneau"],
                    halign=Gtk.Align.END, valign=Gtk.Align.START)
        self.panneau_batterie = Gtk.Label(css_classes=["panneau-batterie"], xalign=0, wrap=True)
        p.append(self.panneau_batterie)
        profils = Gtk.Box(css_classes=["profils"], homogeneous=True, spacing=6)
        self.boutons_profil = {}
        for cle, nom in PROFILS:
            b = Gtk.ToggleButton(label=nom, css_classes=["profil"])
            b.connect("clicked", lambda _b, cle=cle: self.choisir_profil(cle))
            self.boutons_profil[cle] = b
            profils.append(b)
        p.append(profils)
        self.curseur_son = self.ligne_curseur(p, "audio-volume-high-symbolic", 0, 100, self.regler_son)
        self.curseur_lumiere = self.ligne_curseur(p, "display-brightness-symbolic", 3, 100, self.regler_lumiere)
        bascules = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        self.bascule_wifi = self.bascule(bascules, 0, 0, "network-wireless-symbolic", "Wi-Fi", self.basculer_wifi)
        self.bascule_charge = self.bascule(bascules, 1, 0, "battery-full-charging-symbolic", "Charger à 100 %",
                                           self.charger_une_fois)
        self.bascule_eveil = self.bascule(bascules, 0, 1, "weather-clear-night-symbolic", "Ne pas mettre en veille",
                                          self.basculer_eveil)
        self.bascule_tablette = self.bascule(bascules, 1, 1, "input-tablet-symbolic", "Tablette", self.basculer_tablette)
        self.bascule_bluetooth = self.bascule(bascules, 0, 2, "bluetooth-active-symbolic", "Bluetooth", self.basculer_bluetooth)
        self.bascule_nuit = self.bascule(bascules, 1, 2, "night-light-symbolic", "Éclairage du soir", self.basculer_nuit)
        p.append(bascules)
        liens = Gtk.Box(spacing=6, homogeneous=True)
        b_wifi = Gtk.Button(label="Réseaux Wi-Fi", css_classes=["lien"])
        b_wifi.connect("clicked", lambda *a: self.ouvrir_wifi())
        b_bt = Gtk.Button(label="Appareils Bluetooth", css_classes=["lien"])
        b_bt.connect("clicked", lambda *a: (self.panneau.set_visible(False), subprocess.Popen(["blueman-manager"])))
        liens.append(b_wifi)
        liens.append(b_bt)
        p.append(liens)
        self.zone_wifi = Gtk.Box(visible=False)
        boite_wifi = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.etat_wifi = Gtk.Label(css_classes=["wifi-etat"], xalign=0)
        boite_wifi.append(self.etat_wifi)
        defile = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                    max_content_height=250)
        self.liste_wifi = Gtk.ListBox(css_classes=["liste-wifi"], selection_mode=Gtk.SelectionMode.NONE)
        defile.set_child(self.liste_wifi)
        boite_wifi.append(defile)
        self.ligne_mdp = Gtk.Box(spacing=6, visible=False)
        self.mdp_wifi = Gtk.PasswordEntry(placeholder_text="Mot de passe du Wi-Fi", show_peek_icon=True, hexpand=True)
        self.mdp_wifi.connect("activate", lambda *a: self.connecter_reseau())
        ok = Gtk.Button(label="Se connecter", css_classes=["lien"])
        ok.connect("clicked", lambda *a: self.connecter_reseau())
        self.ligne_mdp.append(self.mdp_wifi)
        self.ligne_mdp.append(ok)
        boite_wifi.append(self.ligne_mdp)
        boite_wifi.set_hexpand(True)
        self.zone_wifi.append(boite_wifi)
        p.append(self.zone_wifi)
        self.reseau_choisi = None
        actions = Gtk.Box(css_classes=["actions"], homogeneous=True, spacing=6)
        for nom_icone, texte, action, confirmer in (
                ("system-lock-screen-symbolic", "Verrouiller", self.verrouiller, False),
                ("weather-clear-night-symbolic", "Veille", lambda: commun.commande("systemctl", "suspend"), False),
                ("system-reboot-symbolic", "Redémarrer", lambda: commun.commande("systemctl", "reboot"), True),
                ("system-shutdown-symbolic", "Éteindre", lambda: commun.commande("systemctl", "poweroff"), True),
                ("computer-symbolic", "Windows",
                 lambda: commun.commande("systemctl", "start", "--no-block", "smoky-windows.service"), True)):
            b = Gtk.Button(css_classes=["action"], tooltip_text=texte)
            pile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            pile.append(icone(nom_icone, 20))
            lbl = Gtk.Label(label=texte, css_classes=["action-texte"])
            pile.append(lbl)
            b.set_child(pile)
            b.connect("clicked", lambda _b, a=action, c=confirmer, l=lbl, t=texte: self.action_panneau(a, c, l, t))
            actions.append(b)
        p.append(actions)
        entete = Gtk.Box(spacing=6)
        entete.append(Gtk.Label(label="Notifications", css_classes=["section"], hexpand=True, xalign=0))
        self.bouton_silence = Gtk.ToggleButton(label="Ne pas déranger", css_classes=["lien", "petit"])
        self.bouton_silence.connect("toggled", lambda b: setattr(self, "ne_pas_deranger", b.get_active()))
        effacer = Gtk.Button(label="Effacer", css_classes=["lien", "petit"])
        effacer.connect("clicked", lambda *a: (self.historique.clear(), self.remplir_historique()))
        entete.append(self.bouton_silence)
        entete.append(effacer)
        p.append(entete)
        self.liste_historique = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        p.append(self.liste_historique)
        fond.add_overlay(p)
        w.set_child(fond)
        touches = Gtk.EventControllerKey()
        touches.connect("key-pressed", lambda c, k, *r: (w.set_visible(False) or True) if k == Gdk.KEY_Escape else False)
        w.add_controller(touches)

    def ligne_curseur(self, parent, nom_icone, mini, maxi, rappel):
        ligne = Gtk.Box(spacing=10, css_classes=["curseur"])
        ligne.append(icone(nom_icone, 18))
        c = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, mini, maxi, 1)
        c.set_hexpand(True)
        c.set_draw_value(False)
        c.attente = 0
        def change(*_):
            if c.attente:
                GLib.source_remove(c.attente)
            c.attente = GLib.timeout_add(90, lambda: (setattr(c, "attente", 0), rappel(int(c.get_value())))[1] or False)
        c.connect("value-changed", change)
        ligne.append(c)
        parent.append(ligne)
        return c

    def bascule(self, grille, x, y, nom_icone, texte, rappel):
        b = Gtk.ToggleButton(css_classes=["bascule"])
        boite = Gtk.Box(spacing=8)
        boite.append(icone(nom_icone, 18))
        boite.append(Gtk.Label(label=texte, xalign=0, wrap=True, hexpand=True))
        b.set_child(boite)
        b.rappel_id = b.connect("toggled", lambda _b: rappel(_b.get_active()))
        grille.attach(b, x, y, 1, 1)
        return b

    @staticmethod
    def poser(bascule, actif):
        bascule.handler_block(bascule.rappel_id)
        bascule.set_active(bool(actif))
        bascule.handler_unblock(bascule.rappel_id)

    def basculer_panneau(self):
        if self.panneau.get_visible():
            self.panneau.set_visible(False)
            return
        e = getattr(self, "etat_batterie", None) or self.batterie.etat()
        if e and e["niveau"] is not None:
            texte = f"Batterie {e['niveau']} %"
            if e["minutes"]:
                texte += f" · environ {commun.duree(e['minutes'])} restantes"
            if e["watts"]:
                texte += f" · {str(e['watts']).replace('.', ',')} W"
            if e["statut"] == "Charging":
                texte += " · en charge"
            if e["limite"] and e["limite"] < 100:
                texte += f" · chargée jusqu'à {e['limite']} %"
        else:
            texte = "Sur secteur"
        self.panneau_batterie.set_label(texte)
        actif = self.profil_actuel()
        for cle, b in self.boutons_profil.items():
            b.set_active(cle == actif)
        pourcent, muet = commun.volume()
        if pourcent is not None:
            self.curseur_son.set_value(pourcent)
        lum = commun.luminosite()
        self.curseur_lumiere.get_parent().set_visible(lum is not None)
        if lum is not None:
            self.curseur_lumiere.set_value(lum)
        self.poser(self.bascule_wifi, "enabled" in commun.commande("nmcli", "radio", "wifi", delai=4))
        self.poser(self.bascule_charge, (commun.CONFIG / "charge-once").exists())
        self.poser(self.bascule_eveil, commun.commande("systemctl", "--user", "is-active", "smoky-veille.service").strip() != "active")
        self.poser(self.bascule_tablette, commun.lire_json(commun.ADAPTIVE, {}).get("tablet_mode"))
        self.poser(self.bascule_bluetooth, "true" in commun.commande(
            "busctl", "get-property", "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered", delai=3))
        self.poser(self.bascule_nuit, commun.commande("systemctl", "--user", "is-active", "smoky-nuit.service").strip() == "active")
        self.zone_wifi.set_visible(False)
        self.remplir_historique()
        self.panneau.present()

    def remplir_historique(self):
        while (enfant := self.liste_historique.get_first_child()):
            self.liste_historique.remove(enfant)
        if not self.historique:
            self.liste_historique.append(Gtk.Label(label="Rien de nouveau.", css_classes=["wifi-etat"], xalign=0))
        for n in self.historique[:5]:
            ligne = Gtk.Box(spacing=8, css_classes=["historique"])
            ligne.append(Gtk.Label(label=n["heure"], css_classes=["wifi-etat"]))
            texte = n["titre"] + (" — " + n["corps"] if n["corps"] else "")
            ligne.append(Gtk.Label(label=texte, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                   max_width_chars=42))
            self.liste_historique.append(ligne)

    def action_panneau(self, action, confirmer, etiquette, texte):
        if confirmer and self.panneau_confirmer is not etiquette:
            self.panneau_confirmer = etiquette
            etiquette.set_label("Confirmer")
            GLib.timeout_add_seconds(4, lambda: (etiquette.set_label(texte), setattr(self, "panneau_confirmer", None))[1])
            return
        self.panneau_confirmer = None
        self.panneau.set_visible(False)
        action()

    def profil_actuel(self):
        try:
            v = self.systeme.call_sync(PPD[0], PPD[1], "org.freedesktop.DBus.Properties", "Get",
                                       GLib.Variant("(ss)", (PPD[0], "ActiveProfile")), None,
                                       Gio.DBusCallFlags.NONE, 2000, None)
            return v.unpack()[0]
        except (GLib.Error, AttributeError):
            return None

    def choisir_profil(self, cle):
        try:
            self.systeme.call_sync(PPD[0], PPD[1], "org.freedesktop.DBus.Properties", "Set",
                                   GLib.Variant("(ssv)", (PPD[0], "ActiveProfile", GLib.Variant("s", cle))),
                                   None, Gio.DBusCallFlags.NONE, 3000, None)
        except (GLib.Error, AttributeError) as e:
            print("profil d'énergie :", getattr(e, "message", e), flush=True)
        actif = self.profil_actuel()
        for c, b in self.boutons_profil.items():
            b.set_active(c == actif)

    def regler_son(self, valeur):
        commun.commande("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{valeur}%")
        self.maj_son(valeur, False)

    def regler_lumiere(self, valeur):
        commun.regler_luminosite(valeur)

    def basculer_wifi(self, actif):
        commun.commande("nmcli", "radio", "wifi", "on" if actif else "off")

    def charger_une_fois(self, actif):
        marque = commun.CONFIG / "charge-once"
        e = self.batterie.etat() or {}
        if actif:
            avant = e.get("limite") or 80
            if avant < 100:
                marque.parent.mkdir(parents=True, exist_ok=True)
                marque.write_text(str(avant))
            commun.commande("asusctl", "battery", "limit", "100") or commun.commande("asusctl", "-c", "100")
        else:
            avant = marque.read_text().strip() if marque.exists() else "80"
            commun.commande("asusctl", "battery", "limit", avant) or commun.commande("asusctl", "-c", avant)
            marque.unlink(missing_ok=True)

    def basculer_bluetooth(self, actif):
        commun.commande("busctl", "set-property", "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1",
                        "Powered", "b", "true" if actif else "false")

    def basculer_nuit(self, actif):
        commun.commande("systemctl", "--user", "start" if actif else "stop", "smoky-nuit.service")
        reglages = commun.lire_json(commun.BUREAU, {})
        reglages["nuit"] = bool(actif)
        commun.ecrire_json(commun.BUREAU, reglages)

    # --- Wi-Fi : liste des réseaux, connexion (le travail de nmcli se fait hors de l'affichage) --------
    def ouvrir_wifi(self):
        visible = not self.zone_wifi.get_visible()
        self.zone_wifi.set_visible(visible)
        if visible:
            self.etat_wifi.set_label("Recherche des réseaux…")
            self.ligne_mdp.set_visible(False)
            threading.Thread(target=lambda: GLib.idle_add(self.remplir_wifi, reseau.reseaux(True)), daemon=True).start()

    def remplir_wifi(self, liste):
        while (enfant := self.liste_wifi.get_first_child()):
            self.liste_wifi.remove(enfant)
        self.etat_wifi.set_label("" if liste else "Aucun réseau Wi-Fi en vue.")
        for r in liste[:14]:
            ligne = Gtk.Button(css_classes=["reseau"] + (["actif"] if r["actif"] else []))
            boite = Gtk.Box(spacing=8)
            barres = "▂▄▆█"[:max(1, min(4, round(r["signal"] / 25)))]
            boite.append(Gtk.Label(label=barres, css_classes=["signal"], width_chars=4, xalign=0))
            boite.append(Gtk.Label(label=r["nom"], hexpand=True, xalign=0, ellipsize=Pango.EllipsizeMode.END))
            if r["actif"]:
                boite.append(Gtk.Label(label="connecté", css_classes=["wifi-etat"]))
            elif r["securite"] and r["securite"] != "--":
                boite.append(icone("network-wireless-encrypted-symbolic", 14))
            ligne.set_child(boite)
            ligne.connect("clicked", lambda _b, r=r: self.choisir_reseau(r))
            self.liste_wifi.append(ligne)
        return False

    def choisir_reseau(self, r):
        if r["actif"]:
            return
        self.reseau_choisi = r
        if r["entreprise"] and not r["connu"]:      # eduroam et autres réseaux d'entreprise
            self.panneau.set_visible(False)
            subprocess.Popen(["nm-connection-editor", "--create", "--type=802-11-wireless"])
        elif r["connu"] or not r["securite"] or r["securite"] == "--":
            self.connecter_reseau()
        else:
            self.etat_wifi.set_label(f"Mot de passe pour « {r['nom']} »")
            self.ligne_mdp.set_visible(True)
            self.mdp_wifi.set_text("")
            self.mdp_wifi.grab_focus()

    def connecter_reseau(self):
        r = self.reseau_choisi
        if not r:
            return
        mot_de_passe = self.mdp_wifi.get_text() if self.ligne_mdp.get_visible() else None
        self.mdp_wifi.set_text("")
        self.etat_wifi.set_label(f"Connexion à « {r['nom']} »…")

        def travail():
            erreur = reseau.connecter(r, mot_de_passe)
            GLib.idle_add(self.reseau_connecte, r, erreur)
        threading.Thread(target=travail, daemon=True).start()

    def reseau_connecte(self, r, erreur):
        if erreur:
            self.etat_wifi.set_label(erreur)
        else:
            self.etat_wifi.set_label(f"Connecté à « {r['nom']} ».")
            self.ligne_mdp.set_visible(False)
            self.maj_reseau()
        return False

    def basculer_eveil(self, actif):
        commun.commande("systemctl", "--user", "stop" if actif else "start", "smoky-veille.service")

    def basculer_tablette(self, actif):
        conf = commun.lire_json(commun.ADAPTIVE, {})
        conf["tablet_mode"] = bool(actif)
        commun.ecrire_json(commun.ADAPTIVE, conf)

    def verrouiller(self):
        subprocess.Popen(["systemctl", "--user", "start", "smoky-verrou.service"])

    # --- bulle (son, luminosité) -----------------------------------------------------------
    def creer_bulle(self):
        w = self.bulle = Gtk.Window(application=self)
        w.add_css_class("smoky-bulle-fenetre")
        couche(w, LS.Layer.OVERLAY, (LS.Edge.BOTTOM,), marges={LS.Edge.BOTTOM: 96}, espace="smoky-bulle")
        LS.set_monitor(w, self.ecran)
        boite = Gtk.Box(spacing=12, css_classes=["bulle"])
        self.bulle_icone = icone("audio-volume-high-symbolic", 22)
        self.bulle_niveau = Gtk.LevelBar(min_value=0, max_value=100, hexpand=True, valign=Gtk.Align.CENTER)
        self.bulle_niveau.set_size_request(220, -1)
        self.bulle_texte = Gtk.Label(css_classes=["bulle-texte"], width_chars=4, xalign=1)
        for x in (self.bulle_icone, self.bulle_niveau, self.bulle_texte):
            boite.append(x)
        w.set_child(boite)
        self.bulle_minuterie = 0

    def montrer_bulle(self, genre, valeur):
        noms = {"volume": "audio-volume-high-symbolic", "luminosite": "display-brightness-symbolic",
                "micro": "audio-input-microphone-symbolic"}
        muet = valeur < 0
        self.bulle_icone.set_from_icon_name("audio-volume-muted-symbolic" if genre == "volume" and muet else
                                            "microphone-disabled-symbolic" if genre == "micro" and muet else
                                            noms.get(genre, "dialog-information-symbolic"))
        self.bulle_niveau.set_value(max(0, min(100, valeur)))
        self.bulle_texte.set_label("muet" if muet else f"{valeur} %")
        if genre == "volume":
            self.maj_son(max(valeur, 0), muet)
        self.bulle.present()
        if self.bulle_minuterie:
            GLib.source_remove(self.bulle_minuterie)
        self.bulle_minuterie = GLib.timeout_add(1500, self.cacher_bulle)

    def cacher_bulle(self):
        self.bulle_minuterie = 0
        self.bulle.set_visible(False)
        return False

    # --- notifications -------------------------------------------------------------------------
    def creer_notifications(self):
        w = self.fenetre_notifs = Gtk.Window(application=self)
        w.add_css_class("smoky-notifs-fenetre")
        couche(w, LS.Layer.OVERLAY, (LS.Edge.TOP, LS.Edge.RIGHT), marges={LS.Edge.TOP: 8, LS.Edge.RIGHT: 8},
               espace="smoky-notifications")
        LS.set_monitor(w, self.ecran)
        self.pile_notifs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        w.set_child(self.pile_notifs)

    def notifier(self, appli_nom, remplace, nom_icone, titre, corps, actions, indices, delai):
        nid = remplace if remplace in self.notifs else self.prochain_notif
        if nid == self.prochain_notif:
            self.prochain_notif += 1
        t = time.localtime()
        self.historique.insert(0, {"heure": f"{t.tm_hour:02d}:{t.tm_min:02d}", "titre": titre or appli_nom,
                                   "corps": self.texte_simple(corps or "").replace("\n", " ")})
        del self.historique[30:]
        if self.ne_pas_deranger and indices.get("urgency") != 2:
            return nid                         # rangée dans l'historique, sans bulle
        self.fermer_notif(nid, raison=None)
        carte = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["notif"])
        if indices.get("urgency") == 2:
            carte.add_css_class("urgente")
        haut = Gtk.Box(spacing=10)
        if nom_icone:
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            if not nom_icone.startswith("/") and not theme.has_icon(nom_icone) and theme.has_icon(nom_icone + "-symbolic"):
                nom_icone += "-symbolic"
            img = Gtk.Image.new_from_file(nom_icone) if nom_icone.startswith("/") else icone(nom_icone, 28)
            img.set_pixel_size(28)
            haut.append(img)
        textes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        textes.append(Gtk.Label(label=titre or appli_nom, css_classes=["notif-titre"], xalign=0, wrap=True,
                                max_width_chars=40))
        if corps:
            textes.append(Gtk.Label(label=self.texte_simple(corps),
                                    css_classes=["notif-corps"], xalign=0, wrap=True, max_width_chars=44, lines=4,
                                    ellipsize=Pango.EllipsizeMode.END))
        haut.append(textes)
        fermer = Gtk.Button(css_classes=["notif-fermer"], icon_name="window-close-symbolic", valign=Gtk.Align.START)
        fermer.connect("clicked", lambda *a: self.fermer_notif(nid, raison=2))
        haut.append(fermer)
        carte.append(haut)
        paires = list(zip(actions[::2], actions[1::2]))
        boutons = [(cle, nom) for cle, nom in paires if cle != "default"]
        if boutons:
            ligne = Gtk.Box(spacing=6, homogeneous=True)
            for cle, nom in boutons:
                b = Gtk.Button(label=nom, css_classes=["notif-action"])
                b.connect("clicked", lambda _b, cle=cle: self.action_notif(nid, cle))
                ligne.append(b)
            carte.append(ligne)
        if any(cle == "default" for cle, _ in paires):
            clic = Gtk.GestureClick()
            clic.connect("released", lambda *a: self.action_notif(nid, "default"))
            textes.add_controller(clic)
        self.pile_notifs.prepend(carte)
        minuterie = 0
        if delai != 0 and indices.get("urgency") != 2:
            minuterie = GLib.timeout_add(delai if delai > 0 else 6000, lambda: self.fermer_notif(nid, raison=1) or False)
        self.notifs[nid] = (carte, minuterie)
        while len(self.notifs) > 4:
            self.fermer_notif(min(self.notifs), raison=1)
        self.fenetre_notifs.present()
        return nid

    @staticmethod
    def texte_simple(corps):
        import re
        return re.sub(r"<[^>]+>", "", corps).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    def action_notif(self, nid, cle):
        self.signal_notif("ActionInvoked", GLib.Variant("(us)", (nid, cle)))
        self.fermer_notif(nid, raison=2)

    def fermer_notif(self, nid, raison):
        carte, minuterie = self.notifs.pop(nid, (None, 0))
        if carte is None:
            return
        if minuterie:
            GLib.source_remove(minuterie)
        self.pile_notifs.remove(carte)
        if raison is not None:
            self.signal_notif("NotificationClosed", GLib.Variant("(uu)", (nid, raison)))
        if not self.notifs:
            self.fenetre_notifs.set_visible(False)

    def signal_notif(self, nom, params):
        if self.connexion_dbus:
            self.connexion_dbus.emit_signal(None, "/org/freedesktop/Notifications",
                                            "org.freedesktop.Notifications", nom, params)

    # --- D-Bus -------------------------------------------------------------------------------
    def bus_obtenu(self, connexion, nom):
        self.connexion_dbus = connexion
        noeud = Gio.DBusNodeInfo.new_for_xml(INTERFACE)
        connexion.register_object("/fr/smoky/Bureau", noeud.interfaces[0], self.appel_dbus, None, None)
        connexion.register_object("/org/freedesktop/Notifications", noeud.interfaces[1], self.appel_dbus, None, None)

    def appel_dbus(self, connexion, expediteur, chemin, interface, methode, params, invocation):
        p = params.unpack()
        try:
            if methode == "Lanceur":
                self.ouvrir_lanceur()
                invocation.return_value(None)
            elif methode == "Panneau":
                self.basculer_panneau()
                invocation.return_value(None)
            elif methode == "Bulle":
                self.montrer_bulle(*p)
                invocation.return_value(None)
            elif methode == "Ecran":
                fait = bool(self.fenetres and self.fenetres.ecran_allume(p[0]))
                invocation.return_value(GLib.Variant("(b)", (fait,)))
            elif methode == "Etat":
                fen = [vars(f) | {"client": None, "etats": sorted(f.etats)}
                       for f in (self.fenetres.fenetres.values() if self.fenetres else [])]
                etat = {"dock": commun.dock(), "fenetres": [{k: v for k, v in f.items() if k in ("titre", "appli", "etats")}
                                                            for f in fen],
                        "dock_visible": self.dock.get_visible(), "notifications": len(self.notifs)}
                invocation.return_value(GLib.Variant("(s)", (json.dumps(etat, ensure_ascii=False),)))
            elif methode == "GetCapabilities":
                invocation.return_value(GLib.Variant("(as)", (["body", "actions", "persistence"],)))
            elif methode == "GetServerInformation":
                invocation.return_value(GLib.Variant("(ssss)", ("Smoky", "Smoky OS", "1.0", "1.2")))
            elif methode == "Notify":
                invocation.return_value(GLib.Variant("(u)", (self.notifier(*p),)))
            elif methode == "CloseNotification":
                self.fermer_notif(p[0], raison=3)
                invocation.return_value(None)
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", methode)
        except Exception as e:      # une erreur ne doit jamais faire tomber le bureau
            invocation.return_dbus_error("fr.smoky.Bureau.Erreur", str(e))

    # --- fenêtres ouvertes (client Wayland maison) et réglages ---------------------------------
    def connecter_wayland(self):
        try:
            self.fenetres = wayland.Client(quand_change=self.fenetres_changees)
        except (OSError, KeyError) as e:
            print("liste des fenêtres indisponible :", e, flush=True)
            return
        self.maj_prevue = False
        GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, self.fenetres.fileno(),
                              GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                              lambda *a: self.fenetres.lire())

    def fenetres_changees(self):
        if not self.maj_prevue:              # une seule mise à jour du dock pour une rafale d'événements
            self.maj_prevue = True
            GLib.timeout_add(50, lambda: (setattr(self, "maj_prevue", False), self.maj_dock())[1])

    def surveiller_reglages(self):
        commun.CONFIG.mkdir(parents=True, exist_ok=True)
        self.moniteurs = []
        for chemin in (commun.BUREAU, commun.ADAPTIVE):
            m = Gio.File.new_for_path(str(chemin)).monitor_file(Gio.FileMonitorFlags.NONE, None)
            m.connect("changed", lambda *a: GLib.timeout_add(200, self.maj_dock))
            self.moniteurs.append(m)


def main():
    os.environ.setdefault("GDK_BACKEND", "wayland")
    Bureau().run([])


if __name__ == "__main__":
    main()
