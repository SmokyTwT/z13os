// Smoky OS — « Maison » dans le centre de contrôle : lumières (Tapo…) et robot aspirateur,
// pilotés via Smoky Home (Home Assistant, http://127.0.0.1:8123) avec un jeton d'accès
// enregistré par Smoky Center dans ~/.config/smoky-home/token.
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Soup from 'gi://Soup?version=3.0';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const HA = 'http://127.0.0.1:8123';
const TOKEN_FILE = GLib.build_filenamev([GLib.get_user_config_dir(), 'smoky-home', 'token']);

function readToken() {
    try {
        const [ok, bytes] = GLib.file_get_contents(TOKEN_FILE);
        return ok ? new TextDecoder().decode(bytes).trim() : null;
    } catch {
        return null;
    }
}

const HomeToggle = GObject.registerClass(
class HomeToggle extends QuickMenuToggle {
    _init() {
        super._init({title: 'Maison', subtitle: 'Smoky Home', iconName: 'go-home-symbolic', toggleMode: false});
        this._session = new Soup.Session({timeout: 6});
        this._lights = [];
        this.menu.setHeader('go-home-symbolic', 'Maison', 'Lumières et robot');
        this._section = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._section);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Ouvrir Smoky Home', () => this._spawn(['/usr/bin/smoky-home']));
        // Clic sur la tuile : allume ou éteint toutes les lumières
        this.connect('clicked', () => this._call('light', this.checked ? 'turn_off' : 'turn_on',
            {entity_id: this._lights.map(l => l.entity_id)}));
        this.menu.connect('open-state-changed', (_m, open) => { if (open) this._refresh(); });
        this._refresh();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, 60, () => { this._refresh(); return GLib.SOURCE_CONTINUE; });
    }

    _spawn(argv) {
        try { Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE); } catch (e) { logError(e); }
    }

    _request(method, path, body, done) {
        const token = readToken();
        if (!token) { done(null, 'token'); return; }
        const msg = Soup.Message.new(method, HA + path);
        msg.request_headers.append('Authorization', `Bearer ${token}`);
        if (body)
            msg.set_request_body_from_bytes('application/json', new GLib.Bytes(new TextEncoder().encode(JSON.stringify(body))));
        this._session.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, null, (s, res) => {
            try {
                const bytes = s.send_and_read_finish(res);
                if (msg.get_status() !== 200) { done(null, 'http'); return; }
                done(JSON.parse(new TextDecoder().decode(bytes.get_data())), null);
            } catch {
                done(null, 'off');
            }
        });
    }

    _call(domain, service, data) {
        this._request('POST', `/api/services/${domain}/${service}`, data, () =>
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 700, () => { this._refresh(); return GLib.SOURCE_REMOVE; }));
    }

    _info(text, action) {
        const item = new PopupMenu.PopupMenuItem(text);
        if (action) item.connect('activate', action); else item.setSensitive(false);
        this._section.addMenuItem(item);
    }

    _refresh() {
        this._request('GET', '/api/states', null, (states, err) => {
            this._section.removeAll();
            if (err === 'token') {
                this.subtitle = 'À configurer';
                this._info('Configurer dans Smoky Center…', () => this._spawn(['/usr/bin/smoky-center']));
                return;
            }
            if (!states) {
                this.subtitle = 'Arrêté';
                this.checked = false;
                this._info('Démarrer Smoky Home', () => this._spawn(['systemctl', '--user', 'start', 'smoky-home.service']));
                return;
            }
            this._lights = states.filter(s => s.entity_id.startsWith('light.'));
            const vacuums = states.filter(s => s.entity_id.startsWith('vacuum.'));
            const on = this._lights.filter(l => l.state === 'on').length;
            this.checked = on > 0;
            this.subtitle = this._lights.length ? `${on} lumière${on > 1 ? 's' : ''} allumée${on > 1 ? 's' : ''}` : 'Smoky Home';
            for (const l of this._lights) {
                const item = new PopupMenu.PopupSwitchMenuItem(l.attributes.friendly_name || l.entity_id, l.state === 'on');
                item.connect('toggled', (_i, state) => this._call('light', state ? 'turn_on' : 'turn_off', {entity_id: l.entity_id}));
                this._section.addMenuItem(item);
            }
            for (const v of vacuums) {
                const name = v.attributes.friendly_name || 'Robot';
                const sub = new PopupMenu.PopupSubMenuMenuItem(`${name} — ${v.state}`, true);
                sub.icon.icon_name = 'media-playback-start-symbolic';
                for (const [label, svc] of [['Lancer le ménage', 'start'], ['Pause', 'pause'], ['Retour à la base', 'return_to_base']])
                    sub.menu.addAction(label, () => this._call('vacuum', svc, {entity_id: v.entity_id}));
                this._section.addMenuItem(sub);
            }
            if (!this._lights.length && !vacuums.length)
                this._info('Aucune lumière ni robot dans Smoky Home');
        });
    }

    destroy() {
        if (this._timer) GLib.source_remove(this._timer);
        this._session.abort();
        super.destroy();
    }
});

export default class SmokyHome extends Extension {
    enable() {
        this._indicator = new SystemIndicator();
        this._indicator.quickSettingsItems.push(new HomeToggle());
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator.quickSettingsItems.forEach(i => i.destroy());
        this._indicator.destroy();
        this._indicator = null;
    }
}
