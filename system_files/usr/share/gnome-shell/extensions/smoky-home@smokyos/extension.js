// Smoky OS — « Maison » dans le centre de contrôle : lumières (Tapo…) et robot aspirateur,
// pilotés via Smoky Home (Home Assistant, http://127.0.0.1:8123) avec un jeton d'accès
// enregistré par Smoky Center dans ~/.config/smoky-home/token.
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Soup from 'gi://Soup?version=3.0';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const HA = 'http://127.0.0.1:8123';
const TOKEN_FILE = GLib.build_filenamev([GLib.get_user_config_dir(), 'smoky-home', 'token']);

// états du robot (Home Assistant) en clair
const VAC_STATE = {cleaning: 'En ménage', docked: 'Sur sa base', idle: 'En attente', paused: 'En pause',
    returning: 'Retour à la base', error: 'Erreur', charging: 'En charge', unavailable: 'Hors ligne'};
// puissances d'aspiration courantes (Xiaomi, Dreame) en clair
const FAN = {silent: 'Silencieux', quiet: 'Silencieux', standard: 'Standard', medium: 'Standard', strong: 'Fort',
    turbo: 'Turbo', max: 'Max', gentle: 'Doux'};
const fanLabel = f => FAN[String(f).toLowerCase()] ?? String(f);

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
            for (const v of vacuums)
                this._addVacuum(v, states);
            if (vacuums.some(v => v.state === 'cleaning'))
                this.subtitle = 'Robot en ménage';
            if (!this._lights.length && !vacuums.length)
                this._info('Aucune lumière ni robot dans Smoky Home');
        });
    }

    // Robot : une ligne d'état (nom court, état, batterie) et une ligne de boutons ronds,
    // puis la puissance d'aspiration. Pas de sous-menu à déplier.
    _addVacuum(v, states) {
        const a = v.attributes;
        // nom court : « X20 Max » plutôt que « Xiaomi Robot Vacuum X20 Max Xiaomi Robot Cleaner »
        const full = String(a.friendly_name || 'Robot');
        const model = full.match(/\b([A-Z]\d+[A-Za-z]*(?:\s(?:Max|Pro|Ultra|Plus|\+))?)\b/);
        const name = model ? `Robot ${model[1]}` : (full.length > 22 ? 'Robot' : full);
        let battery = a.battery_level;
        if (battery === undefined) {
            const prefix = v.entity_id.split('.')[1].split('_').slice(0, 3).join('_');
            const sensor = states.find(s => s.entity_id.startsWith('sensor.') && s.entity_id.includes(prefix) &&
                /batter/.test(s.entity_id));
            battery = sensor?.state;
        }
        const state = VAC_STATE[v.state] ?? v.state;
        this._info(`${name} · ${state}${battery !== undefined && battery !== 'unknown' ? ` · ${battery} %` : ''}`);

        const row = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        const box = new St.BoxLayout({x_expand: true, x_align: Clutter.ActorAlign.CENTER, style: 'spacing: 12px;'});
        const cleaning = v.state === 'cleaning';
        for (const [icon, label, svc] of [
            [cleaning ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic', cleaning ? 'Pause' : 'Lancer', cleaning ? 'pause' : 'start'],
            ['media-playback-stop-symbolic', 'Arrêter', 'stop'],
            ['go-home-symbolic', 'Base', 'return_to_base'],
            ['find-location-symbolic', 'Localiser', 'locate'],
        ]) {
            const btn = new St.Button({style_class: 'icon-button', can_focus: true, accessible_name: label,
                child: new St.Icon({icon_name: icon, icon_size: 18})});
            btn.connect('clicked', () => this._call('vacuum', svc, {entity_id: v.entity_id}));
            box.add_child(btn);
        }
        row.add_child(box);
        this._section.addMenuItem(row);

        const speeds = a.fan_speed_list ?? [];
        if (speeds.length) {
            const sub = new PopupMenu.PopupSubMenuMenuItem(`Aspiration : ${fanLabel(a.fan_speed ?? '?')}`, true);
            sub.icon.icon_name = 'weather-windy-symbolic';
            for (const f of speeds) {
                const item = sub.menu.addAction(fanLabel(f), () =>
                    this._call('vacuum', 'set_fan_speed', {entity_id: v.entity_id, fan_speed: f}));
                if (f === a.fan_speed)
                    item.setOrnament(PopupMenu.Ornament.CHECK);
            }
            this._section.addMenuItem(sub);
        }
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
