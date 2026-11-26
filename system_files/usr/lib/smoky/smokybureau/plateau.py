"""Smoky OS — zone de notification de la barre (StatusNotifierItem).

Des applis comme Proton VPN posent une icône dans la barre, pour qu'on les retrouve une fois leur
fenêtre fermée. Elles s'inscrivent auprès du « veilleur » (org.kde.StatusNotifierWatcher) que tient
le bureau ; celui-ci lit ensuite chaque icône sur le bus de la session : nom d'icône ou image, titre,
état, et son menu (com.canonical.dbusmenu). Clic gauche : l'appli s'ouvre ; clic droit ou appui long :
son menu. Spécification : StatusNotifierItem de freedesktop.org, et le protocole dbusmenu.

Rien d'autre que le bus de la session : aucun fichier, aucun accès au réseau. Sans affichage :
bureau.py dessine les boutons, ce module ne fait que parler au bus (essayé seul, tests/test_bureau.py).
"""
from gi.repository import Gio, GLib

VEILLEUR = "org.kde.StatusNotifierWatcher"
ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
XML = f"""<node><interface name="{VEILLEUR}">
 <method name="RegisterStatusNotifierItem"><arg type="s" name="service" direction="in"/></method>
 <method name="RegisterStatusNotifierHost"><arg type="s" name="service" direction="in"/></method>
 <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
 <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
 <property name="ProtocolVersion" type="i" access="read"/>
 <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
 <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
 <signal name="StatusNotifierHostRegistered"/>
</interface></node>"""
SIGNAUX = ("NewIcon", "NewAttentionIcon", "NewOverlayIcon", "NewStatus", "NewTitle", "NewToolTip", "NewIconThemePath",
           "NewMenu")


class Element:
    """Une icône inscrite : où la joindre, et ce qu'elle montre."""

    def __init__(self, service, chemin):
        self.service, self.chemin = service, chemin
        self.ident = self.titre = self.bulle = ""
        self.etat = "Active"                  # Passive (cachée), Active, NeedsAttention
        self.icone = self.icone_attention = self.chemin_icones = ""
        self.image = None                     # (largeur, hauteur, octets ARGB de l'image) si pas de nom d'icône
        self.menu = ""                        # chemin de son menu (dbusmenu) ; vide : pas de menu
        self.est_menu = False                 # un clic gauche ouvre le menu, au lieu de l'appli

    @property
    def cle(self):
        return self.service + self.chemin

    @property
    def visible(self):
        return self.etat != "Passive"

    def nom_icone(self):
        return self.icone_attention if self.etat == "NeedsAttention" and self.icone_attention else self.icone


def meilleure_image(images, voulu=24):
    """Parmi les images (l, h, ARGB) d'une icône : la plus petite qui atteint `voulu`, sinon la plus grande."""
    bonnes = [(l, h, bytes(d)) for l, h, d in images or [] if l > 0 and h > 0 and len(bytes(d)) >= l * h * 4]
    if not bonnes:
        return None
    assez = [i for i in bonnes if i[0] >= voulu]
    return min(assez, key=lambda i: i[0]) if assez else max(bonnes, key=lambda i: i[0])


def rgba(image):
    """ARGB (ordre réseau, comme l'envoie l'appli) → RGBA, pour l'affichage."""
    l, h, d = image
    sortie = bytearray(len(d))
    sortie[0::4], sortie[1::4], sortie[2::4], sortie[3::4] = d[1::4], d[2::4], d[3::4], d[0::4]
    return l, h, bytes(sortie)


def etiquette(texte):
    """« _Quitter » → « Quitter » (le souligné marque la touche d'accès) ; « __ » → « _ »."""
    return texte.replace("__", "\0").replace("_", "").replace("\0", "_")


def arbre_menu(disposition):
    """Disposition dbusmenu (id, propriétés, enfants) → entrées visibles :
    {id, texte, actif, coche (None : sans case), enfants} ou {id, separateur: True}."""
    sortie = []
    for ident, props, enfants in disposition[2]:
        if not props.get("visible", True):
            continue
        if props.get("type") == "separator":
            sortie.append({"id": ident, "separateur": True})
            continue
        case = props.get("toggle-type") in ("checkmark", "radio")
        sortie.append({"id": ident, "texte": etiquette(props.get("label", "")), "actif": props.get("enabled", True),
                       "coche": props.get("toggle-state") == 1 if case else None,
                       "enfants": arbre_menu((ident, props, enfants)) if enfants else []})
    return sortie


class Plateau:
    """Le veilleur des icônes et ce qu'il en sait. quand_change(liste) à chaque changement."""

    def __init__(self, bus, quand_change):
        self.bus = bus
        self.quand_change = quand_change
        self.elements = {}                    # clé (service + chemin) → Element, dans l'ordre d'arrivée
        self.abonnements = {}                 # clé → numéro de l'abonnement à ses signaux
        self.ids = []
        self.actif = False                    # le nom du veilleur est à nous

    # --- le veilleur ----------------------------------------------------------------------
    def demarrer(self):
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        self.ids.append(("objet", self.bus.register_object("/StatusNotifierWatcher", info.interfaces[0],
                                                           self._appel, self._propriete, None)))
        self.ids.append(("signal", self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                                             "NameOwnerChanged", "/org/freedesktop/DBus", None,
                                                             Gio.DBusSignalFlags.NONE, self._nom_change)))
        self.ids.append(("nom", Gio.bus_own_name_on_connection(self.bus, VEILLEUR, Gio.BusNameOwnerFlags.REPLACE,
                                                                self._nom_obtenu, None)))

    def arreter(self):
        for genre, n in self.ids:
            if genre == "objet":
                self.bus.unregister_object(n)
            elif genre == "signal":
                self.bus.signal_unsubscribe(n)
            else:
                Gio.bus_unown_name(n)
        for n in self.abonnements.values():
            self.bus.signal_unsubscribe(n)
        self.ids, self.abonnements, self.elements = [], {}, {}

    def _nom_obtenu(self, *_):                # les applis qui attendaient un hôte s'inscrivent
        self.actif = True
        self.bus.emit_signal(None, "/StatusNotifierWatcher", VEILLEUR, "StatusNotifierHostRegistered", None)

    def _propriete(self, connexion, expediteur, chemin, interface, nom):
        if nom == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", list(self.elements))
        if nom == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if nom == "ProtocolVersion":
            return GLib.Variant("i", 0)
        return None

    def _appel(self, connexion, expediteur, chemin, interface, methode, params, invocation):
        try:
            if methode == "RegisterStatusNotifierItem":
                (service,) = params.unpack()
                if service.startswith("/"):    # un chemin : l'objet est sur la connexion de l'appelant
                    self.inscrire(expediteur, service)
                else:                          # un nom sur le bus : l'objet est au chemin habituel
                    self.inscrire(service or expediteur, "/StatusNotifierItem")
                invocation.return_value(None)
            elif methode == "RegisterStatusNotifierHost":
                invocation.return_value(None)
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", methode)
        except Exception as e:                 # une appli mal écrite ne doit pas faire tomber le bureau
            invocation.return_dbus_error("fr.smoky.Bureau.Erreur", str(e))

    def inscrire(self, service, chemin):
        el = Element(service, chemin)
        if el.cle not in self.elements:
            self.elements[el.cle] = el
            self.abonnements[el.cle] = self.bus.signal_subscribe(
                service, ITEM, None, chemin, None, Gio.DBusSignalFlags.NONE,
                lambda c, exp, ch, i, signal, p, cle=el.cle: signal in SIGNAUX and self.relire(cle))
            self.bus.emit_signal(None, "/StatusNotifierWatcher", VEILLEUR, "StatusNotifierItemRegistered",
                                 GLib.Variant("(s)", (el.cle,)))
        self.relire(el.cle)

    def retirer(self, cle):
        if self.elements.pop(cle, None) is None:
            return
        n = self.abonnements.pop(cle, None)
        if n:
            self.bus.signal_unsubscribe(n)
        self.bus.emit_signal(None, "/StatusNotifierWatcher", VEILLEUR, "StatusNotifierItemUnregistered",
                             GLib.Variant("(s)", (cle,)))
        self.quand_change(self.liste())

    def _nom_change(self, connexion, expediteur, chemin, interface, signal, params):
        nom, _, nouveau = params.unpack()
        if not nouveau:                         # l'appli est partie (ou son nom n'a plus de propriétaire)
            for cle in [c for c, el in self.elements.items() if el.service == nom]:
                self.retirer(cle)

    def liste(self):
        return list(self.elements.values())

    # --- ce que montre une icône ---------------------------------------------------------------
    def relire(self, cle):
        el = self.elements.get(cle)
        if not el:
            return False
        self.bus.call(el.service, el.chemin, "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (ITEM,)),
                      GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, 3000, None, self._lu, cle)
        return False

    def _lu(self, connexion, resultat, cle):
        try:
            (p,) = connexion.call_finish(resultat).unpack()
        except GLib.Error:                      # l'appli ne répond pas (encore) : on garde ce qu'on sait
            return
        el = self.elements.get(cle)
        if not el:
            return
        el.ident, el.titre = p.get("Id", ""), p.get("Title", "")
        el.etat = p.get("Status", "Active") or "Active"
        el.icone, el.icone_attention = p.get("IconName", ""), p.get("AttentionIconName", "")
        el.chemin_icones = p.get("IconThemePath", "")
        el.image = meilleure_image(p.get("IconPixmap"))
        menu = p.get("Menu", "")
        el.menu = menu if menu and menu != "/" else ""
        el.est_menu = bool(p.get("ItemIsMenu", False))
        bulle = p.get("ToolTip")
        el.bulle = " — ".join(t for t in (bulle[2], bulle[3]) if t) if bulle and len(bulle) >= 4 else ""
        self.quand_change(self.liste())

    # --- ce qu'on lui demande ---------------------------------------------------------------------
    def _appeler(self, service, chemin, interface, methode, params, rappel=None):
        def fini(connexion, resultat, _):
            try:
                r = connexion.call_finish(resultat)
            except GLib.Error as e:
                print("zone de notification :", methode, e.message, flush=True)
                r = None
            if rappel:
                rappel(r)
        self.bus.call(service, chemin, interface, methode, params, None, Gio.DBusCallFlags.NONE, 3000, None, fini, None)

    def activer(self, el, x=0, y=0):
        self._appeler(el.service, el.chemin, ITEM, "Activate", GLib.Variant("(ii)", (x, y)))

    def activer_second(self, el, x=0, y=0):
        self._appeler(el.service, el.chemin, ITEM, "SecondaryActivate", GLib.Variant("(ii)", (x, y)))

    def menu_de_l_appli(self, el, x=0, y=0):
        """Appli sans menu dbusmenu : elle montre le sien (ContextMenu)."""
        self._appeler(el.service, el.chemin, ITEM, "ContextMenu", GLib.Variant("(ii)", (x, y)))

    def lire_menu(self, el, rappel):
        """Le menu de l'icône, lu en entier : rappel(arbre_menu(…)) ; rappel(None) s'il est illisible."""
        if not el.menu:
            rappel(None)
            return

        def lu(r):
            rappel(arbre_menu(r.unpack()[1]) if r else None)
        self._appeler(el.service, el.menu, MENU, "AboutToShow", GLib.Variant("(i)", (0,)))
        self._appeler(el.service, el.menu, MENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])), lu)

    def choisir(self, el, ident):
        self._appeler(el.service, el.menu, MENU, "Event",
                      GLib.Variant("(isvu)", (ident, "clicked", GLib.Variant("s", ""), int(GLib.get_real_time() // 1000000))))
