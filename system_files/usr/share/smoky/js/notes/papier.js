// Smoky — Notes : les papiers. Une seule description des lignes sert à l'écran (canvas) et à
// l'export PDF, pour que le PDF ressemble exactement à la page. Unités : points PDF (1/72 pouce).

export const MODELES = {
  vierge: "Vierge", ligne: "Ligné", carreaux: "Quadrillé", points: "Pointillé",
  seyes: "Seyès", cornell: "Cornell", portees: "Portées",
};

export const COULEURS = {
  blanc: { nom: "Blanc", fond: "#ffffff", trait: "rgba(28,28,36,0.15)", fort: "rgba(28,28,36,0.32)", clair: true },
  ivoire: { nom: "Ivoire", fond: "#f9f6ee", trait: "rgba(70,58,36,0.16)", fort: "rgba(70,58,36,0.32)", clair: true },
  cendre: { nom: "Cendre", fond: "#e6e6ea", trait: "rgba(20,20,30,0.15)", fort: "rgba(20,20,30,0.3)", clair: true },
  fumee: { nom: "Fumée", fond: "#18181c", trait: "rgba(255,255,255,0.12)", fort: "rgba(255,255,255,0.26)", clair: false },
};

export const FORMATS = {
  a4: { nom: "A4", w: 595.28, h: 841.89 },
  "a4-paysage": { nom: "A4 paysage", w: 841.89, h: 595.28 },
  ecran: { nom: "Écran", w: 841.89, h: 526.18 },
};

// Couvertures : dégradés sombres et argentés, comme le thème de Smoky OS ; braise reste rare.
export const COUVERTURES = {
  fumee: { nom: "Fumée", a: "#34343a", b: "#121214", texte: "#f3f3f6" },
  argent: { nom: "Argent", a: "#d9dae0", b: "#8f909a", texte: "#121214" },
  onyx: { nom: "Onyx", a: "#151517", b: "#020203", texte: "#e4e4ea" },
  ivoire: { nom: "Ivoire", a: "#f6f3ea", b: "#d4cfbf", texte: "#1d1b16" },
  ardoise: { nom: "Ardoise", a: "#59616d", b: "#262b32", texte: "#eef0f4" },
  encre: { nom: "Encre", a: "#3b4f73", b: "#161f30", texte: "#eaf0ff" },
  sauge: { nom: "Sauge", a: "#76877a", b: "#343f37", texte: "#eef4ef" },
  braise: { nom: "Braise", a: "#a8473c", b: "#4a1a15", texte: "#fff0ed" },
};

// Couleurs d'encre et de surligneur proposées
export const ENCRES = ["#141417", "#5d5d68", "#f3f3f6", "#2d6fe0", "#d4392f", "#21915a", "#e2a114", "#8d4bb0"];
export const SURLIGNEURS = ["#ffe45c", "#a6ec9a", "#9bd6ff", "#ffa6cf", "#ffbd73", "#cfd0d6"];

// Lignes du papier : { lignes: [[x1, y1, x2, y2, fort]], points: [[x, y, r]] }
export function dessinPapier(page) {
  const { w, h } = page;
  const lignes = [];
  const points = [];
  const marge = 36;
  switch (page.modele) {
    case "ligne":
      for (let y = 92; y < h - 30; y += 24) lignes.push([marge, y, w - marge, y, false]);
      lignes.push([marge + 46, 0, marge + 46, h, true]);
      break;
    case "carreaux":
      for (let x = 17.85; x < w; x += 14.17) lignes.push([x, 0, x, h, false]);       // carreaux de 5 mm
      for (let y = 17.85; y < h; y += 14.17) lignes.push([0, y, w, y, false]);
      break;
    case "points":
      for (let x = 21; x < w - 8; x += 19.84) for (let y = 21; y < h - 8; y += 19.84) points.push([x, y, 0.9]);  // 7 mm
      break;
    case "seyes": {
      // cahier français : grands carreaux de 8 mm, trois lignes fines entre deux lignes fortes
      const grand = 22.68;
      const pas = grand / 4;
      let i = 0;
      for (let y = 62; y < h - 22; y += pas, i++) lignes.push([marge, y, w - 22, y, i % 4 === 0]);
      for (let x = marge + 56.7; x < w - 22; x += grand) lignes.push([x, 62, x, h - 22, false]);
      lignes.push([marge + 56.7, 0, marge + 56.7, h, true]);
      break;
    }
    case "cornell": {
      const colonne = Math.round(w * 0.3);
      const bas = h - Math.round(h * 0.2);
      for (let y = 98; y < bas - 8; y += 24) lignes.push([colonne + 10, y, w - marge, y, false]);
      lignes.push([0, 72, w, 72, true], [colonne, 72, colonne, bas, true], [0, bas, w, bas, true]);
      break;
    }
    case "portees":
      for (let haut = 72; haut < h - 60; haut += 74) for (let k = 0; k < 5; k++) lignes.push([marge, haut + k * 7.2, w - marge, haut + k * 7.2, true]);
      break;
    default:
  }
  return { lignes, points };
}

// Dessine le papier dans un contexte déjà mis à l'échelle (1 unité = 1 point de page).
export function peindrePapier(ctx, page) {
  const c = COULEURS[page.couleur] || COULEURS.blanc;
  ctx.fillStyle = c.fond;
  ctx.fillRect(0, 0, page.w, page.h);
  const { lignes, points } = dessinPapier(page);
  ctx.lineWidth = 0.6;
  for (const fort of [false, true]) {
    ctx.strokeStyle = fort ? c.fort : c.trait;
    ctx.beginPath();
    for (const [x1, y1, x2, y2, f] of lignes) {
      if (f !== fort) continue;
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
    }
    ctx.stroke();
  }
  if (points.length) {
    ctx.fillStyle = c.fort;
    ctx.beginPath();
    for (const [x, y, r] of points) { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, Math.PI * 2); }
    ctx.fill();
  }
}
