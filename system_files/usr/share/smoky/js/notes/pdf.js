// Smoky — Notes : les PDF. pdf.js les affiche (cours à annoter), pdf-lib fabrique l'export.
// Les deux bibliothèques sont fournies avec Smoky OS (versions figées, dossier /vendor/) et ne
// sont chargées qu'au premier PDF.
import { nouvelId, nomFichier } from "/js/notes/stockage.js";
import { cheminSVG, rempli } from "/js/notes/encre.js";
import { dessinPapier, COULEURS } from "/js/notes/papier.js";

const RESSOURCES = "/vendor/pdfjs/";
let pdfjs = null;
function bibliotheque() {
  if (!pdfjs) {
    pdfjs = import("/vendor/pdf.min.mjs").then((m) => {
      m.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.mjs";
      return m;
    }).catch((e) => { pdfjs = null; throw e; });
  }
  return pdfjs;
}

const options = (data) => ({
  data, isEvalSupported: false, cMapUrl: `${RESSOURCES}cmaps/`, cMapPacked: true,
  standardFontDataUrl: `${RESSOURCES}standard_fonts/`, wasmUrl: `${RESSOURCES}wasm/`, iccUrl: `${RESSOURCES}iccs/`,
});

const documents = new Map();           // « carnet/fichier » → document pdf.js (promesse)

function ouvrir(carnet, nom) {
  const cle = `${carnet.carnet.id}/${nom}`;
  if (!documents.has(cle)) {
    documents.set(cle, (async () => {
      const lib = await bibliotheque();
      const blob = await carnet.octets(nom);
      return lib.getDocument(options(new Uint8Array(await blob.arrayBuffer()))).promise;
    })().catch((e) => { documents.delete(cle); throw e; }));
  }
  return documents.get(cle);
}

// Oublie les documents d'un carnet refermé (mémoire)
export function oublier(carnetId) {
  for (const [cle, doc] of documents) {
    if (cle.startsWith(`${carnetId}/`)) {
      documents.delete(cle);
      doc.then((d) => d.destroy()).catch(() => {});
    }
  }
}

// Peint la page index (0 = première) à l'échelle voulue (pixels par point) ; rappel(canvas) une
// fois prête. → { cancel() } (une page qui quitte l'écran n'est pas peinte pour rien)
export function peindre(carnet, nom, index, echelle, rappel) {
  let annule = false;
  let tache = null;
  (async () => {
    const doc = await ouvrir(carnet, nom);
    if (annule) return;
    const page = await doc.getPage(index + 1);
    if (annule) return;
    const vue = page.getViewport({ scale: echelle });
    const toile = document.createElement("canvas");
    toile.width = Math.max(1, Math.round(vue.width));
    toile.height = Math.max(1, Math.round(vue.height));
    tache = page.render({ canvasContext: toile.getContext("2d"), viewport: vue, background: "rgba(255,255,255,1)" });
    await tache.promise;
    if (!annule) rappel(toile);
  })().catch((e) => {
    if (!annule && e?.name !== "RenderingCancelledException") console.warn("PDF :", e?.message || e);
  });
  return { cancel() { annule = true; tache?.cancel(); } };
}

// Un PDF choisi par toi → envoyé au carnet, et une page de carnet par page du PDF
export async function importer(carnet, fichier) {
  if (fichier.size > 250e6) throw new Error("Ce PDF est trop gros (250 Mo au plus).");
  const octets = await fichier.arrayBuffer();
  if (new TextDecoder().decode(octets.slice(0, 5)) !== "%PDF-") throw new Error("Ce fichier n'est pas un PDF.");
  const lib = await bibliotheque();
  let doc;
  try {
    doc = await lib.getDocument(options(new Uint8Array(octets.slice(0)))).promise;
  } catch (e) {
    throw new Error(e?.name === "PasswordException" ? "Ce PDF est protégé par un mot de passe." : "Ce PDF est illisible.");
  }
  if (doc.numPages > 2000) throw new Error("Ce PDF a trop de pages (2 000 au plus).");
  const nom = await nomFichier(new Blob([octets]), ".pdf");
  await carnet.envoyerFichier(nom, new Blob([octets], { type: "application/pdf" }));
  documents.set(`${carnet.carnet.id}/${nom}`, Promise.resolve(doc));
  const pages = [];
  for (let i = 0; i < doc.numPages; i++) {
    const page = await doc.getPage(i + 1);
    const vue = page.getViewport({ scale: 1 });
    pages.push({ id: nouvelId("p"), w: Math.round(vue.width * 100) / 100, h: Math.round(vue.height * 100) / 100,
      modele: "vierge", couleur: "blanc", signet: false, fond: { pdf: nom, page: i } });
  }
  return pages;
}

// --- Export ------------------------------------------------------------------------------------------
function couleurPdf(css) {
  const { rgb } = self.PDFLib;
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b, a = 1] = m[1].split(",").map(Number);
    return [rgb(r / 255, g / 255, b / 255), a];
  }
  const n = parseInt(css.replace("#", ""), 16);
  return [rgb(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255), 1];
}

// Les polices standard des PDF ne connaissent que l'alphabet latin (accents compris)
const latin = (texte) => texte.replace(/[^\x20-\x7e\xa0-\xffŒœ€’‘“”…–—]/g, "?");

async function imagePdf(sortie, carnet, nom, deja) {
  if (deja.has(nom)) return deja.get(nom);
  const blob = await carnet.octets(nom);
  let image;
  if (nom.endsWith(".png")) image = await sortie.embedPng(await blob.arrayBuffer());
  else if (nom.endsWith(".jpg") || nom.endsWith(".jpeg")) image = await sortie.embedJpg(await blob.arrayBuffer());
  else {                                             // WebP : converti en PNG pour le PDF
    const bitmap = await createImageBitmap(blob);
    const toile = new OffscreenCanvas(bitmap.width, bitmap.height);
    toile.getContext("2d").drawImage(bitmap, 0, 0);
    image = await sortie.embedPng(await (await toile.convertToBlob({ type: "image/png" })).arrayBuffer());
  }
  deja.set(nom, image);
  return image;
}

// → octets du PDF (vectoriel : les traits restent nets à tous les zooms)
export async function exporter(carnet) {
  if (!self.PDFLib) await import("/vendor/pdf-lib.min.js");
  const { PDFDocument, StandardFonts, LineCapStyle, degrees } = self.PDFLib;
  const sortie = await PDFDocument.create();
  sortie.setTitle(carnet.carnet.titre);
  sortie.setCreator("Smoky — Notes");
  sortie.setProducer("Smoky OS");
  const police = await sortie.embedFont(StandardFonts.Helvetica);
  const sources = new Map();
  const images = new Map();
  for (const p of carnet.carnet.pages) {
    const c = await carnet.contenu(p.id);
    let page;
    if (p.fond) {
      if (!sources.has(p.fond.pdf)) {
        const octets = await (await carnet.octets(p.fond.pdf)).arrayBuffer();
        sources.set(p.fond.pdf, await PDFDocument.load(octets, { ignoreEncryption: true }));
      }
      const source = sources.get(p.fond.pdf);
      const tourne = source.getPage(p.fond.page).getRotation().angle % 360;
      if (!tourne) {
        const [copie] = await sortie.copyPages(source, [p.fond.page]);
        page = sortie.addPage(copie);
      } else {
        // page tournée dans le PDF d'origine : on la pose droite sur une page à sa taille visible
        const [incrustee] = await sortie.embedPdf(source, [p.fond.page]);
        page = sortie.addPage([p.w, p.h]);
        const w = incrustee.width, h = incrustee.height;
        const pos = { 90: { x: 0, y: p.h }, 180: { x: p.w, y: p.h }, 270: { x: p.w, y: 0 } }[tourne] || { x: 0, y: 0 };
        page.drawPage(incrustee, { ...pos, width: w, height: h, rotate: degrees(-tourne) });
      }
    } else {
      page = sortie.addPage([p.w, p.h]);
      const papier = COULEURS[p.couleur] || COULEURS.blanc;
      page.drawRectangle({ x: 0, y: 0, width: p.w, height: p.h, color: couleurPdf(papier.fond)[0] });
      const { lignes, points } = dessinPapier(p);
      for (const [x1, y1, x2, y2, fort] of lignes) {
        const [couleur, opacite] = couleurPdf(fort ? papier.fort : papier.trait);
        page.drawLine({ start: { x: x1, y: p.h - y1 }, end: { x: x2, y: p.h - y2 }, thickness: 0.6, color: couleur, opacity: opacite });
      }
      const [cp, op] = couleurPdf(papier.fort);
      for (const [x, y, r] of points) page.drawCircle({ x, y: p.h - y, size: r, color: cp, opacity: op });
    }
    const H = page.getHeight();
    const sx = page.getWidth() / p.w;                      // la page d'un PDF peut différer d'un poil
    for (const im of c.images) {
      try {
        const image = await imagePdf(sortie, carnet, im.fichier, images);
        page.drawImage(image, { x: im.x * sx, y: H - (im.y + im.h) * sx, width: im.w * sx, height: im.h * sx });
      } catch { /* image illisible : la page sort sans elle */ }
    }
    for (const passe of ["surligneur", "stylo"]) {
      for (const t of c.traits) {
        if (t.outil !== passe || !t.points?.length) continue;
        const [couleur] = couleurPdf(t.couleur);
        const d = cheminSVG(t);
        if (rempli(t)) page.drawSvgPath(d, { x: 0, y: H, scale: sx, color: couleur, borderWidth: 0 });
        else {
          page.drawSvgPath(d, { x: 0, y: H, scale: sx, borderColor: couleur, borderWidth: t.largeur * sx,
            borderOpacity: passe === "surligneur" ? 0.38 : 1, borderLineCap: LineCapStyle.Round });
        }
      }
    }
    for (const t of c.textes) {
      const [couleur] = couleurPdf(t.couleur);
      t.texte.split("\n").forEach((ligne, i) => {
        if (!ligne) return;
        page.drawText(latin(ligne), { x: t.x * sx, y: H - (t.y + t.taille * 0.9 + i * t.taille * 1.3) * sx, size: t.taille * sx, font: police, color: couleur });
      });
    }
  }
  return sortie.save();
}
