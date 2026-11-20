// Smoky — Notes : la géométrie de l'encre, sans rien dessiner (utilisée par l'écran et par l'export
// PDF, et testée seule). Unités : points de page.
//
// Un trait : { id, outil: "stylo" | "surligneur", couleur, largeur, points: [x, y, pression, …],
//              forme?: "ligne" | "rectangle" | "ellipse" | "triangle" | "fleche", ferme?: bool,
//              son?, ts? }
// Le stylo est rempli (largeur qui suit la pression) ; le surligneur et les formes parfaites sont
// des lignes de largeur constante.

// Pression → facteur de largeur ; 0,5 (souris, ou stylet sans pression) donne la largeur choisie.
export function facteurPression(p) {
  const q = Math.min(1, Math.max(0, Number.isFinite(p) ? p : 0.5));
  return 0.42 + 1.1 * Math.pow(q, 0.9);
}

// Largeurs lissées point par point (pas de saut brusque si la pression tremble).
function largeurs(points, largeur) {
  const n = points.length / 3;
  const brutes = new Float64Array(n);
  for (let i = 0; i < n; i++) brutes[i] = largeur * facteurPression(points[i * 3 + 2]);
  const lisses = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0, c = 0;
    for (let k = Math.max(0, i - 2); k <= Math.min(n - 1, i + 2); k++) { s += brutes[k]; c++; }
    lisses[i] = s / c;
  }
  return lisses;
}

function cercle(x, y, r, pas = 16) {
  const poly = [];
  for (let k = 0; k < pas; k++) {
    const a = (k / pas) * Math.PI * 2;
    poly.push(x + Math.cos(a) * r, y + Math.sin(a) * r);
  }
  return poly;
}

// Contour d'une portion de trait (indices i0 à i1 inclus) : côté gauche, bout rond, côté droit à
// l'envers, bout rond.
function contourPortion(pts, W, i0, i1) {
  if (i1 === i0) return cercle(pts[i0 * 3], pts[i0 * 3 + 1], W[i0] / 2);
  const gauche = [], droite = [];
  let tx = 0, ty = 0;
  for (let k = i0; k <= i1; k++) {
    const a = Math.max(i0, k - 1), b = Math.min(i1, k + 1);
    let dx = pts[b * 3] - pts[a * 3], dy = pts[b * 3 + 1] - pts[a * 3 + 1];
    const l = Math.hypot(dx, dy);
    if (l > 1e-6) { tx = dx / l; ty = dy / l; } else if (!tx && !ty) { tx = 1; ty = 0; }
    const r = W[k] / 2, x = pts[k * 3], y = pts[k * 3 + 1];
    gauche.push(x - ty * r, y + tx * r);
    droite.push(x + ty * r, y - tx * r);
  }
  const poly = gauche.slice();
  // bout rond à la fin : du côté gauche au côté droit en passant par l'avant
  const ex = pts[i1 * 3], ey = pts[i1 * 3 + 1], er = W[i1] / 2;
  const [fx, fy] = direction(pts, i1, i1 - 1);
  for (let s = 1; s < 8; s++) {
    const a = (s / 8) * Math.PI;
    const nx = -fy, ny = fx;              // normale gauche
    poly.push(ex + (nx * Math.cos(a) + fx * Math.sin(a)) * er, ey + (ny * Math.cos(a) + fy * Math.sin(a)) * er);
  }
  for (let k = droite.length - 2; k >= 0; k -= 2) poly.push(droite[k], droite[k + 1]);
  // bout rond au début : du côté droit au côté gauche en passant par l'arrière
  const sx = pts[i0 * 3], sy = pts[i0 * 3 + 1], sr = W[i0] / 2;
  const [bx, by] = direction(pts, i0, i0 + 1);   // vers l'arrière du trait
  for (let s = 1; s < 8; s++) {
    const a = (s / 8) * Math.PI;
    const nx = -by, ny = bx;
    poly.push(sx + (nx * Math.cos(a) + bx * Math.sin(a)) * sr, sy + (ny * Math.cos(a) + by * Math.sin(a)) * sr);
  }
  return poly;
}

// direction unitaire de j vers i (le dernier segment non nul)
function direction(pts, i, j) {
  const pas = j < i ? -1 : 1;
  for (let k = j; k >= 0 && k < pts.length / 3; k += pas) {
    const dx = pts[i * 3] - pts[k * 3], dy = pts[i * 3 + 1] - pts[k * 3 + 1];
    const l = Math.hypot(dx, dy);
    if (l > 1e-6) return [dx / l, dy / l];
  }
  return [1, 0];
}

// Contour rempli d'un trait de stylo : une liste de polygones ([x, y, x, y, …]). Aux virages très
// serrés (un « v », un « z ») le trait est coupé en morceaux aux bouts ronds : pas d'angle rogné.
export function contourStylo(points, largeur) {
  const n = points.length / 3;
  if (!n) return [];
  const W = largeurs(points, largeur);
  const morceaux = [];
  let debut = 0;
  for (let k = 1; k < n - 1; k++) {
    const ax = points[k * 3] - points[(k - 1) * 3], ay = points[k * 3 + 1] - points[(k - 1) * 3 + 1];
    const bx = points[(k + 1) * 3] - points[k * 3], by = points[(k + 1) * 3 + 1] - points[k * 3 + 1];
    const la = Math.hypot(ax, ay), lb = Math.hypot(bx, by);
    if (la > 1e-6 && lb > 1e-6 && (ax * bx + ay * by) / (la * lb) < -0.2) {
      morceaux.push(contourPortion(points, W, debut, k));
      debut = k;
    }
  }
  morceaux.push(contourPortion(points, W, debut, n - 1));
  return morceaux;
}

// --- Ce que l'écran et le PDF dessinent -------------------------------------------------------------
// « remplir » : polygones à remplir (stylo) ; sinon une ligne de largeur constante (surligneur, forme).
export function rempli(trait) {
  return trait.outil === "stylo" && !trait.forme;
}

const caches = new WeakMap();
export function chemin2D(trait) {
  let c = caches.get(trait);
  if (c) return c;
  c = new Path2D();
  if (rempli(trait)) {
    for (const poly of contourStylo(trait.points, trait.largeur)) {
      c.moveTo(poly[0], poly[1]);
      for (let k = 2; k < poly.length; k += 2) c.lineTo(poly[k], poly[k + 1]);
      c.closePath();
    }
  } else {
    const p = trait.points;
    c.moveTo(p[0], p[1]);
    if (p.length === 3) c.lineTo(p[0] + 0.01, p[1]);
    for (let k = 3; k < p.length; k += 3) c.lineTo(p[k], p[k + 1]);
    if (trait.ferme) c.closePath();
  }
  caches.set(trait, c);
  return c;
}

const arrondi = (v) => Math.round(v * 100) / 100;
// Même dessin, en chemin SVG (pour pdf-lib) ; y vers le bas comme sur la page.
export function cheminSVG(trait) {
  let d = "";
  if (rempli(trait)) {
    for (const poly of contourStylo(trait.points, trait.largeur)) {
      d += `M${arrondi(poly[0])} ${arrondi(poly[1])}`;
      for (let k = 2; k < poly.length; k += 2) d += `L${arrondi(poly[k])} ${arrondi(poly[k + 1])}`;
      d += "Z";
    }
  } else {
    const p = trait.points;
    d = `M${arrondi(p[0])} ${arrondi(p[1])}`;
    if (p.length === 3) d += `L${arrondi(p[0] + 0.01)} ${arrondi(p[1])}`;
    for (let k = 3; k < p.length; k += 3) d += `L${arrondi(p[k])} ${arrondi(p[k + 1])}`;
    if (trait.ferme) d += "Z";
  }
  return d;
}

// --- Mesures et retouches -----------------------------------------------------------------------------
export function bornes(item) {
  if (item.points) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const p = item.points;
    for (let i = 0; i < p.length; i += 3) {
      if (p[i] < x0) x0 = p[i];
      if (p[i] > x1) x1 = p[i];
      if (p[i + 1] < y0) y0 = p[i + 1];
      if (p[i + 1] > y1) y1 = p[i + 1];
    }
    const m = (item.largeur || 1) * (rempli(item) ? 0.8 : 0.5);
    return { x: x0 - m, y: y0 - m, w: x1 - x0 + 2 * m, h: y1 - y0 + 2 * m };
  }
  return { x: item.x, y: item.y, w: item.w || 0, h: item.h || 0 };
}

export function distanceSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// Le point (x, y), avec une tolérance r, touche-t-il le trait ?
export function touche(item, x, y, r) {
  if (!item.points) {
    const b = bornes(item);
    return x >= b.x - r && x <= b.x + b.w + r && y >= b.y - r && y <= b.y + b.h + r;
  }
  const p = item.points;
  const rr = r + (item.largeur || 1) / 2;
  if (p.length === 3) return Math.hypot(p[0] - x, p[1] - y) <= rr;
  for (let i = 3; i < p.length; i += 3) {
    if (distanceSegment(x, y, p[i - 3], p[i - 2], p[i], p[i + 1]) <= rr) return true;
  }
  if (item.ferme && p.length > 6 && distanceSegment(x, y, p[p.length - 3], p[p.length - 2], p[0], p[1]) <= rr) return true;
  return false;
}

// Gomme précise : retire les points touchés, le trait est coupé en morceaux.
// → null si rien n'est touché, sinon la liste des morceaux restants (peut être vide).
export function gommer(trait, x, y, r, nouvelId) {
  const p = trait.points;
  const rr = r + trait.largeur / 2;
  const morceaux = [];
  let courant = [];
  let touche_ = false;
  for (let i = 0; i < p.length; i += 3) {
    if (Math.hypot(p[i] - x, p[i + 1] - y) <= rr) {
      touche_ = true;
      if (courant.length >= 6) morceaux.push(courant);
      courant = [];
    } else courant.push(p[i], p[i + 1], p[i + 2]);
  }
  if (!touche_) return null;
  if (courant.length >= 6) morceaux.push(courant);
  return morceaux.map((points) => ({ ...trait, id: nouvelId(), points, ferme: false }));
}

export function dansPolygone(x, y, poly) {
  let dedans = false;
  for (let i = 0, j = poly.length - 2; i < poly.length; j = i, i += 2) {
    const xi = poly[i], yi = poly[i + 1], xj = poly[j], yj = poly[j + 1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dedans = !dedans;
  }
  return dedans;
}

// Un élément est pris par le lasso si la moitié de ses points (ou son centre) est dedans.
export function dansLasso(item, poly) {
  if (item.points) {
    const p = item.points;
    let n = 0;
    for (let i = 0; i < p.length; i += 3) if (dansPolygone(p[i], p[i + 1], poly)) n++;
    return n / (p.length / 3) >= 0.5;
  }
  const b = bornes(item);
  return dansPolygone(b.x + b.w / 2, b.y + b.h / 2, poly);
}

// Déplacer et agrandir (autour de ox, oy) : renvoie une copie, l'original ne change pas.
export function transformer(item, dx, dy, s = 1, ox = 0, oy = 0) {
  const x = (v) => ox + (v - ox) * s + dx;
  const y = (v) => oy + (v - oy) * s + dy;
  if (item.points) {
    const p = item.points.slice();
    for (let i = 0; i < p.length; i += 3) { p[i] = arrondi(x(p[i])); p[i + 1] = arrondi(y(p[i + 1])); }
    return { ...item, points: p, largeur: arrondi(item.largeur * s) };
  }
  const copie = { ...item, x: arrondi(x(item.x)), y: arrondi(y(item.y)), w: arrondi(item.w * s) };
  if (item.h !== undefined) copie.h = arrondi(item.h * s);
  if (item.taille !== undefined) copie.taille = arrondi(item.taille * s);
  return copie;
}
