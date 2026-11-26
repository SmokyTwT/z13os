"""Atelier : zone de notification de la vraie barre. Une fausse appli à icône (comme Proton VPN) s'inscrit
auprès du bureau Smoky ; son icône doit apparaître à droite de la barre, puis disparaître quand l'appli
s'en va. Comparaison de captures (grim) du coin droit de la barre : avant, pendant, après.
Lancé par : bash tests/atelier/bureau.sh /usr/bin/python3 tests/atelier/plateau.py"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from outils import conclure  # noqa: E402

T = os.environ["ATELIER"]
APPLI = r'''
import sys
from gi.repository import Gio, GLib
XML = """<node><interface name="org.kde.StatusNotifierItem">
 <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
 <property name="Id" type="s" access="read"/><property name="Title" type="s" access="read"/>
 <property name="Status" type="s" access="read"/><property name="IconName" type="s" access="read"/>
 <property name="ItemIsMenu" type="b" access="read"/>
</interface></node>"""
P = {"Id": GLib.Variant("s", "essai"), "Title": GLib.Variant("s", "Appli d'essai"), "Status": GLib.Variant("s", "Active"),
     "IconName": GLib.Variant("s", "network-vpn-symbolic"), "ItemIsMenu": GLib.Variant("b", False)}
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
bus.register_object("/StatusNotifierItem", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],
                    lambda *a: a[-1].return_value(None), lambda *a: P[a[4]], None)
bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
              "RegisterStatusNotifierItem", GLib.Variant("(s)", ("/StatusNotifierItem",)), None, 0, 3000, None)
print("inscrite", flush=True)
GLib.MainLoop().run()
'''


def coin(nom):
    """Le coin droit de la barre (là où vont les icônes), en octets bruts."""
    chemin = f"{T}/captures/{nom}.png"
    subprocess.run(["grim", "-g", "1500,0 420x40", chemin], check=True)
    return open(chemin, "rb").read()


avant = coin("plateau-avant")
appli = subprocess.Popen(["/usr/bin/python3", "-c", APPLI], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
ligne = appli.stdout.readline().strip()
time.sleep(2)
pendant = coin("plateau-pendant")
subprocess.run(["grim", f"{T}/captures/plateau-barre.png"])
appli.terminate()
appli.wait(5)
time.sleep(2)
apres = coin("plateau-apres")
conclure("zone de notification", ligne == "inscrite" and pendant != avant and apres == avant,
         f"(appli : {ligne or 'muette'} ; icône apparue : {pendant != avant} ; retirée : {apres == avant})")
