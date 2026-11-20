// Smoky — Notes : enregistrer le cours pendant qu'on écrit. Chaque trait écrit pendant
// l'enregistrement garde l'instant où il a été tracé ; « Écouter » s'en sert pour rejouer ce moment.
export class Enregistreur {
  constructor() {
    this.actif = false;
    this.id = null;
  }

  async demarrer(id) {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new Error("Pas de micro disponible.");
    }
    try {
      this.flux = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true } });
    } catch {
      throw new Error("Smoky n'a pas accès au micro (autorise-le quand Smoky le demande).");
    }
    const type = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    this.morceaux = [];
    this.recepteur = new MediaRecorder(this.flux, { mimeType: type, audioBitsPerSecond: 48000 });
    this.recepteur.addEventListener("dataavailable", (e) => { if (e.data.size) this.morceaux.push(e.data); });
    this.recepteur.start(2000);                  // un morceau toutes les 2 s : rien de perdu en cas de souci
    this.id = id;
    this.debut = Date.now();
    this.t0 = performance.now();
    this.actif = true;
  }

  // millisecondes écoulées depuis le début de l'enregistrement
  temps() { return this.actif ? performance.now() - this.t0 : 0; }

  // → { id, blob, debut, duree } (ou null s'il n'y avait rien)
  arreter() {
    if (!this.actif) return Promise.resolve(null);
    this.actif = false;
    const duree = Math.round(performance.now() - this.t0);
    return new Promise((resolve) => {
      this.recepteur.addEventListener("stop", () => {
        for (const piste of this.flux.getTracks()) piste.stop();
        const blob = new Blob(this.morceaux, { type: "audio/webm" });
        this.morceaux = [];
        resolve(blob.size ? { id: this.id, blob, debut: this.debut, duree } : null);
      }, { once: true });
      this.recepteur.stop();
    });
  }
}
