// Smoky OS — écran de verrouillage : sous l'horloge, la météo et l'état du PC (processeur,
// mémoire, batterie) au lieu des notifications. Rien ne tourne quand l'écran est déverrouillé.
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Soup from 'gi://Soup?version=3.0';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Lieu de la météo : ~/.config/smoky/meteo.json {"ville", "lat", "lon"}, sinon Valenciennes (UPHF)
const CONF = GLib.build_filenamev([GLib.get_user_config_dir(), 'smoky', 'meteo.json']);
const DEFAULT_PLACE = {ville: 'Valenciennes', lat: 50.357, lon: 3.523};
const WEATHER_EVERY = 30 * 60;      // secondes
const STATS_EVERY = 3;
// codes météo WMO (open-meteo.com) → texte et icône
const WMO = [
    [[0], 'Ciel dégagé', 'weather-clear-symbolic'],
    [[1, 2], 'Éclaircies', 'weather-few-clouds-symbolic'],
    [[3], 'Couvert', 'weather-overcast-symbolic'],
    [[45, 48], 'Brouillard', 'weather-fog-symbolic'],
    [[51, 53, 55, 56, 57], 'Bruine', 'weather-showers-scattered-symbolic'],
    [[61, 63, 65, 66, 67, 80, 81, 82], 'Pluie', 'weather-showers-symbolic'],
    [[71, 73, 75, 77, 85, 86], 'Neige', 'weather-snow-symbolic'],
    [[95, 96, 99], 'Orage', 'weather-storm-symbolic'],
];

function readText(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok ? new TextDecoder().decode(bytes) : '';
    } catch {
        return '';
    }
}

function place() {
    try {
        const p = JSON.parse(readText(CONF));
        if (Number.isFinite(p.lat) && Number.isFinite(p.lon))
            return {ville: String(p.ville || ''), lat: p.lat, lon: p.lon};
    } catch {}
    return DEFAULT_PLACE;
}

export default class SmokyLockInfo extends Extension {
    enable() {
        this._session = new Soup.Session({timeout: 15});
        this._weather = null;           // {temp, text, icon, at}
        this._cpuPrev = null;
        this._sig = Main.screenShield.connect('locked-changed', () => this._sync());
        this._sync();
    }

    disable() {
        // reste actif pendant le verrouillage (session-modes) : disable() n'arrive qu'à la vraie désactivation
        Main.screenShield.disconnect(this._sig);
        this._detach();
        this._session?.abort();
        this._session = null;
    }

    _sync() {
        if (Main.screenShield.locked)
            this._attach();
        else
            this._detach();
    }

    _attach() {
        const dialog = Main.screenShield._dialog;
        if (!dialog || this._box)
            return;
        // plus de notifications sur l'écran verrouillé (le réglage GNOME en masque déjà le contenu)
        this._notifs = dialog._notificationsBox ?? null;
        if (this._notifs) {
            this._notifs.hide();
            this._notifsSig = this._notifs.connect('show', () => this._notifs.hide());
        }
        this._box = new St.BoxLayout({vertical: true, x_align: Clutter.ActorAlign.CENTER, style_class: 'smoky-lockinfo'});
        this._weatherRow = new St.BoxLayout({x_align: Clutter.ActorAlign.CENTER, style_class: 'smoky-lockinfo-weather'});
        this._weatherIcon = new St.Icon({icon_size: 28, style_class: 'smoky-lockinfo-icon'});
        this._weatherLabel = new St.Label({y_align: Clutter.ActorAlign.CENTER});
        this._weatherRow.add_child(this._weatherIcon);
        this._weatherRow.add_child(this._weatherLabel);
        this._weatherRow.hide();
        this._stats = new St.Label({x_align: Clutter.ActorAlign.CENTER, style_class: 'smoky-lockinfo-stats'});
        this._box.add_child(this._weatherRow);
        this._box.add_child(this._stats);
        const parent = dialog._clock ?? dialog._stack ?? dialog;
        parent.add_child(this._box);
        // l'écran de verrouillage est détruit au déverrouillage, avec tout ce qu'il contient
        this._box.connect('destroy', () => {
            this._box = null;
            this._notifs = this._notifsSig = null;
            this._stop();
        });
        this._cpuPrev = null;
        this._updateStats();
        this._renderWeather();
        this._fetchWeather();
        this._statsId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, STATS_EVERY, () => {
            this._updateStats();
            return GLib.SOURCE_CONTINUE;
        });
        this._weatherId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, WEATHER_EVERY, () => {
            this._fetchWeather();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stop() {
        for (const k of ['_statsId', '_weatherId']) {
            if (this[k])
                GLib.source_remove(this[k]);
            this[k] = 0;
        }
    }

    _detach() {
        this._stop();
        if (this._notifs && this._notifsSig)
            this._notifs.disconnect(this._notifsSig);
        this._notifs = this._notifsSig = null;
        this._box?.destroy();
        this._box = null;
    }

    _updateStats() {
        if (!this._box)
            return;
        const parts = [];
        // processeur : écart entre deux lectures de /proc/stat
        const f = readText('/proc/stat').split('\n')[0].trim().split(/\s+/).slice(1).map(Number);
        if (f.length >= 5) {
            const idle = f[3] + (f[4] || 0), total = f.reduce((a, b) => a + b, 0);
            if (this._cpuPrev) {
                const dt = total - this._cpuPrev.total, di = idle - this._cpuPrev.idle;
                if (dt > 0)
                    parts.push(`Processeur ${Math.round(100 * (1 - di / dt))} %`);
            }
            this._cpuPrev = {idle, total};
        }
        const mem = readText('/proc/meminfo');
        const tot = Number(mem.match(/MemTotal:\s+(\d+)/)?.[1]), avail = Number(mem.match(/MemAvailable:\s+(\d+)/)?.[1]);
        if (tot && avail)
            parts.push(`Mémoire ${((tot - avail) / 1048576).toFixed(1).replace('.', ',')} / ${Math.round(tot / 1048576)} Go`);
        const cap = readText('/sys/class/power_supply/BAT0/capacity').trim();
        const st = readText('/sys/class/power_supply/BAT0/status').trim();
        if (cap)
            parts.push(`Batterie ${cap} %${st === 'Charging' ? ' ⚡' : ''}`);
        this._stats.text = parts.join('   ·   ');
    }

    _renderWeather() {
        const w = this._weather;
        if (!this._box || !w)
            return;
        this._weatherIcon.icon_name = w.icon;
        this._weatherLabel.text = `${w.temp}°  ${w.text}${w.ville ? '  ·  ' + w.ville : ''}`;
        this._weatherRow.show();
    }

    _fetchWeather() {
        const w = this._weather;
        if (w && GLib.get_monotonic_time() / 1e6 - w.at < WEATHER_EVERY - 60)
            return;
        const p = place();
        const url = `https://api.open-meteo.com/v1/forecast?latitude=${p.lat}&longitude=${p.lon}` +
            '&current=temperature_2m,weather_code&timezone=auto';
        const msg = Soup.Message.new('GET', url);
        if (!msg || !this._session)
            return;
        this._session.send_and_read_async(msg, GLib.PRIORITY_LOW, null, (session, res) => {
            try {
                const bytes = session.send_and_read_finish(res);
                if (msg.get_status() !== Soup.Status.OK)
                    return;
                const cur = JSON.parse(new TextDecoder().decode(bytes.get_data())).current;
                const code = Number(cur.weather_code);
                const [, text, icon] = WMO.find(([codes]) => codes.includes(code)) ?? [null, '', 'weather-overcast-symbolic'];
                this._weather = {temp: Math.round(cur.temperature_2m), text, icon, ville: p.ville,
                    at: GLib.get_monotonic_time() / 1e6};
                this._renderWeather();
            } catch {
                // hors ligne : la météo reste cachée, le reste s'affiche
            }
        });
    }
}
