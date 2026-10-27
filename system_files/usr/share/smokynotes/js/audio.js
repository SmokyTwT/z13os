// Enregistrement audio synchronisé avec l'écriture (comme Notability) :
// chaque trait, texte ou image garde l'heure à laquelle il a été écrit ; en touchant
// un élément avec l'outil « Réécouter », l'audio repart à ce moment-là, et pendant la
// lecture ce qui a été écrit « plus tard » apparaît estompé.
import { api, hashName } from './api.js';
import { $, toast } from './ui.js';

let host = null;          // { nb(), markDirty(), rerender() }
let rec = null;           // enregistrement en cours
let cur = null;           // enregistrement chargé dans le lecteur
let curUrl = null;
let ticker = 0;
const player = new Audio();
player.preload = 'auto';

const fmt = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(r).padStart(2, '0');
};
const timeFmt = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

export function initAudio(h) {
  host = h;
  $('#ed-rec').onclick = () => (rec ? stopRecording() : startRecording());
  $('#au-play').onclick = () => (player.paused ? player.play() : player.pause());
  $('#au-list').onchange = (e) => select(recordings().find((r) => r.id === e.target.value));
  $('#au-seek').oninput = (e) => { if (cur) player.currentTime = (e.target.value / 1000) * (cur.duration / 1000); };
  player.onplay = () => { syncButtons(); clearInterval(ticker); ticker = setInterval(onTick, 250); };
  player.onpause = player.onended = () => { syncButtons(); clearInterval(ticker); host.rerender(); };
}

const recordings = () => host.nb()?.recordings || [];

export function audioOnOpen() {
  player.pause();
  cur = null;
  if (curUrl) URL.revokeObjectURL(curUrl);
  curUrl = null;
  refreshBar();
}

export async function audioOnClose() {
  await stopRecording();
  player.pause();
}

// --- Enregistrement ---------------------------------------------------------------
async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast('Micro indisponible'); return; }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch {
    toast('Accès au micro refusé');
    return;
  }
  player.pause();
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
  // 32 kbit/s en Opus : voix claire, environ 15 Mo par heure de cours
  const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 32000 });
  const chunks = [];
  recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  recorder.start(1000);
  rec = { recorder, chunks, stream, start: Date.now(), timer: setInterval(syncButtons, 1000) };
  syncButtons();
  toast('Enregistrement en cours : écris normalement, tout est synchronisé');
}

export async function stopRecording() {
  if (!rec) return;
  const r = rec;
  rec = null;
  clearInterval(r.timer);
  await new Promise((res) => { r.recorder.onstop = res; r.recorder.stop(); });
  r.stream.getTracks().forEach((t) => t.stop());
  syncButtons();
  const duration = Date.now() - r.start;
  if (duration < 1500) return;                      // clic accidentel
  try {
    const buf = await new Blob(r.chunks, { type: 'audio/webm' }).arrayBuffer();
    const asset = await hashName(buf, 'webm');
    await api.putAsset(host.nb().id, asset, new Blob([buf], { type: 'audio/webm' }));
    const nb = host.nb();
    nb.recordings ||= [];
    nb.recordings.push({ id: 'r' + r.start.toString(36), asset, start: r.start, duration });
    host.markDirty();
    refreshBar();
    toast(`Enregistrement sauvegardé (${fmt(duration)})`);
  } catch (e) {
    toast("L'enregistrement n'a pas pu être sauvegardé : " + e.message, 6000);
  }
}

// --- Lecture --------------------------------------------------------------------------
async function select(r) {
  if (!r || cur?.id === r.id) return;
  player.pause();
  if (curUrl) URL.revokeObjectURL(curUrl);
  const buf = await api.getAsset(host.nb().id, r.asset);
  curUrl = URL.createObjectURL(new Blob([buf], { type: 'audio/webm' }));
  player.src = curUrl;
  cur = r;
  $('#au-list').value = r.id;
  await new Promise((res) => { player.onloadedmetadata = res; setTimeout(res, 1500); });
  syncButtons();
}

// Outil « Réécouter » : l'audio repart 2 s avant le moment où l'élément a été écrit
export async function listenAt(item) {
  if (!item) { toast('Touche un mot ou un dessin pour réécouter ce moment'); return; }
  if (!item.t) { toast('Cet élément a été écrit sans enregistrement en cours'); return; }
  const r = recordings().find((x) => item.t >= x.start - 2000 && item.t <= x.start + x.duration + 2000);
  if (!r) { toast("Aucun enregistrement n'était en cours à ce moment-là"); return; }
  await select(r);
  player.currentTime = Math.max(0, (item.t - r.start) / 1000 - 2);
  player.play();
}

// Pendant la lecture : ce qui a été écrit après la position actuelle est estompé
export function fadeFn() {
  if (!cur || player.paused) return null;
  const now = cur.start + player.currentTime * 1000;
  const end = cur.start + cur.duration;
  return (it) => it.t && it.t >= cur.start && it.t <= end && it.t > now;
}

function onTick() {
  syncButtons();
  host.rerender();
}

// --- Interface ----------------------------------------------------------------------------
function refreshBar() {
  const list = recordings();
  $('#au-bar').classList.toggle('hidden', !list.length);
  const sel = $('#au-list');
  sel.innerHTML = '';
  list.forEach((r, i) => {
    const o = document.createElement('option');
    o.value = r.id;
    o.textContent = `Enregistrement ${i + 1} — ${timeFmt.format(new Date(r.start))} (${fmt(r.duration)})`;
    sel.appendChild(o);
  });
  if (cur) sel.value = cur.id;
  syncButtons();
}

function syncButtons() {
  const b = $('#ed-rec');
  b.classList.toggle('rec-on', !!rec);
  $('#ed-rec-time').textContent = rec ? fmt(Date.now() - rec.start) : '';
  const playing = !player.paused;
  $('#au-play').innerHTML = playing ? PAUSE : PLAY;
  if (cur) {
    $('#au-time').textContent = `${fmt(player.currentTime * 1000)} / ${fmt(cur.duration)}`;
    $('#au-seek').value = Math.round((player.currentTime * 1000 / cur.duration) * 1000);
  } else {
    $('#au-time').textContent = 'Choisis un moment avec l’outil Réécouter';
  }
}

const SVG = (p) => `<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">${p}</svg>`;
const PLAY = SVG('<path d="M8 5.5v13l10.5-6.5z"/>');
const PAUSE = SVG('<rect x="6.5" y="5.5" width="4" height="13" rx="1"/><rect x="13.5" y="5.5" width="4" height="13" rx="1"/>');
