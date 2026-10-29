// Smoky OS — bouton « Tablette » dans le centre de contrôle. Il écrit tablet_mode dans
// ~/.config/smoky/adaptive.json (le même réglage que Smoky Center) ; le service
// smoky-adaptive applique : grandes icônes dans le dock et clavier à l'écran.
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {QuickToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CONF = GLib.build_filenamev([GLib.get_user_config_dir(), 'smoky', 'adaptive.json']);

function readConf() {
    try {
        const [ok, bytes] = GLib.file_get_contents(CONF);
        return ok ? JSON.parse(new TextDecoder().decode(bytes)) : {};
    } catch {
        return {};
    }
}

const TabletToggle = GObject.registerClass(
class TabletToggle extends QuickToggle {
    _init() {
        super._init({title: 'Tablette', iconName: 'input-tablet-symbolic', toggleMode: true});
        this.checked = !!readConf().tablet_mode;
        this.connect('clicked', () => {
            const conf = readConf();
            conf.tablet_mode = this.checked;
            GLib.mkdir_with_parents(GLib.path_get_dirname(CONF), 0o700);
            GLib.file_set_contents(CONF, JSON.stringify(conf, null, 1));
        });
        // Réglage changé ailleurs (Smoky Center) : le bouton suit
        this._monitor = Gio.File.new_for_path(CONF).monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._monitor.connect('changed', () => {
            const on = !!readConf().tablet_mode;
            if (on !== this.checked)
                this.checked = on;
        });
    }

    destroy() {
        this._monitor?.cancel();
        this._monitor = null;
        super.destroy();
    }
});

// Tuiles inutiles retirées du centre de contrôle : « Clavier » (rétroéclairage, déjà réglé
// par asusd et sans objet avec un clavier Bluetooth)
const HIDDEN = [/KeyboardBrightness/i, /^Clavier$|^Keyboard$/i];

function hideUseless(actor) {
    const name = actor.constructor?.name ?? '';
    const title = actor.title ?? '';
    if (!HIDDEN.some(re => re.test(name) || re.test(title)))
        return;
    actor.hide();
    // GNOME la réaffiche quand le rétroéclairage change : on la recache aussitôt
    actor._smokyHideSig ??= actor.connect('notify::visible', () => {
        if (actor.visible)
            actor.hide();
    });
}

export default class SmokyTablet extends Extension {
    enable() {
        this._indicator = new SystemIndicator();
        this._indicator.quickSettingsItems.push(new TabletToggle());
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
        // les tuiles arrivent parfois après le démarrage : on surveille la grille
        const grid = Main.panel.statusArea.quickSettings.menu._grid;
        if (grid) {
            grid.get_children().forEach(hideUseless);
            this._gridSig = grid.connect('child-added', (_g, child) => hideUseless(child));
            this._grid = grid;
        }
    }

    disable() {
        if (this._grid && this._gridSig)
            this._grid.disconnect(this._gridSig);
        this._grid?.get_children().forEach(c => {
            if (c._smokyHideSig) {
                c.disconnect(c._smokyHideSig);
                delete c._smokyHideSig;
                c.show();
            }
        });
        this._grid = this._gridSig = null;
        this._indicator.quickSettingsItems.forEach(i => i.destroy());
        this._indicator.destroy();
        this._indicator = null;
    }
}
