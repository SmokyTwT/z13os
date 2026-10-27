// Smoky OS — chaque nouvelle fenêtre d'application s'ouvre en grand.
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class SmokyMaximize extends Extension {
    enable() {
        this._createdId = global.display.connect('window-created', (_display, win) => this._onCreated(win));
    }

    disable() {
        if (this._createdId) {
            global.display.disconnect(this._createdId);
            this._createdId = 0;
        }
    }

    _onCreated(win) {
        // On attend la première image de la fenêtre : sa taille minimale est alors connue.
        const actor = win.get_compositor_private();
        if (actor) {
            const id = actor.connect('first-frame', () => {
                actor.disconnect(id);
                this._maximize(win);
            });
        } else {
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                this._maximize(win);
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _maximize(win) {
        try {
            if (win.get_window_type() !== Meta.WindowType.NORMAL)
                return;
            if (win.get_transient_for() || win.is_skip_taskbar())
                return;                          // boîtes de dialogue, fenêtres annexes
            if (!win.can_maximize() || win.is_fullscreen())
                return;
            // GNOME ≤ 48 : maximize(flags) ; GNOME 49 et plus : maximize() sans argument
            if (Meta.MaximizeFlags)
                win.maximize(Meta.MaximizeFlags.BOTH);
            else
                win.maximize();
        } catch (e) {
            console.warn(`smoky-maximize : ${e}`);
        }
    }
}
