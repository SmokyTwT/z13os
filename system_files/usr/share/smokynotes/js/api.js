// Accès au serveur local (enregistrement dans ~/Notes/Smoky Notes).
const TOKEN = document.querySelector('meta[name="smoky-token"]').content;

async function call(method, path, body, type = 'application/json') {
  const res = await fetch('/api/' + path, {
    method,
    headers: { 'X-Smoky-Token': TOKEN, ...(body !== undefined ? { 'Content-Type': type } : {}) },
    body: body === undefined ? undefined : body,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error || msg; } catch { /* corps vide */ }
    throw new Error(msg);
  }
  return res;
}

export const api = {
  async list() { return (await call('GET', 'notebooks')).json(); },
  async deadlines() { return (await call('GET', 'deadlines')).json(); },
  async load(id) { return (await call('GET', 'notebooks/' + id)).json(); },
  async save(nb) { return (await call('PUT', 'notebooks/' + nb.id, JSON.stringify(nb))).json(); },
  async remove(id) { return call('DELETE', 'notebooks/' + id); },
  async duplicate(src, dst) { return call('POST', `duplicate/${src}/${dst}`); },
  async putAsset(nbId, name, blob) { return call('PUT', `assets/${nbId}/${name}`, blob, blob.type || 'application/octet-stream'); },
  async getAsset(nbId, name) { return (await call('GET', `assets/${nbId}/${name}`)).arrayBuffer(); },
  async exportPdf(fileName, bytes) { return (await call('PUT', 'export/' + encodeURIComponent(fileName), bytes, 'application/pdf')).json(); },
};

// Empreinte courte d'un fichier : même fichier importé deux fois = un seul exemplaire.
export async function hashName(buf, ext) {
  const d = new Uint8Array(await crypto.subtle.digest('SHA-256', buf));
  return Array.from(d.slice(0, 12), (b) => b.toString(16).padStart(2, '0')).join('') + '.' + ext;
}
