// Smoky — Notes : reconnaître ce que tu dessines.
//   reconnaitre(points)  stylet maintenu immobile au bout d'un trait → forme parfaite (ligne,
//                        rectangle, ellipse, triangle) ou null
//   gribouillis(points)  un trait qui va et vient très vite sur place : c'est pour effacer
//   cibles(...)          ce que le gribouillis recouvre
import { bornes, touche } from "/js/notes/encre.js";

function longueur(p) {
  let l = 0;
  for (let i = 3; i < p.length; i += 3) l += Math.hypot(p[i] - p[i - 3], p[i + 1] - p[i - 2]);
  return l;
}

// n points également espacés le long du trait → [[x, y], …]
function reechantillonner(p, n) {
  const total = longueur(p);
  if (!total) return [[p[0], p[1]]];
  const pas = total / (n - 1);
  const sortie = [[p[0], p[1]]];
  let reste = pas;
  for (let i = 3; i < p.length; i += 3) {
    let ax = p[i - 3], ay = p[i - 2];
    const bx = p[i], by = p[i + 1];
    let seg = Math.hypot(bx - ax, by - ay);
    while (seg >= reste && sortie.length < n) {
      const t = reste / seg;
      ax += (bx - ax) * t;
      ay += (by - ay) * t;
      sortie.push([ax, ay]);
      seg -= reste;
      reste = pas;
    }
    reste -= seg;
  }
  while (sortie.length < n) sortie.push([p[p.length - 3], p[p.length - 2]]);
  return sortie;
}

function boite(pts) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return { x0, y0, x1, y1, w: x1 - x0, h: y1 - y0 };
}

const aplat = (sommets) => sommets.flatMap(([x, y]) => [Math.round(x * 100) / 100, Math.round(y * 100) / 100, 0.5]);

// Coins : là où le trait tourne franchement (angle entre la direction d'avant et d'après)
function coins(pts, ferme) {
  const n = pts.length;
  const k = 4;                                   // regarde 4 points avant et après (sur 64)
  const angles = [];
  for (let i = 0; i < n; i++) {
    const a = ferme ? pts[(i - k + n) % n] : pts[Math.max(0, i - k)];
    const b = ferme ? pts[(i + k) % n] : pts[Math.min(n - 1, i + k)];
    const v1 = [pts[i][0] - a[0], pts[i][1] - a[1]], v2 = [b[0] - pts[i][0], b[1] - pts[i][1]];
    const l1 = Math.hypot(...v1), l2 = Math.hypot(...v2);
    angles.push(l1 && l2 ? Math.acos(Math.max(-1, Math.min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))) : 0);
  }
  const trouves = [];
  for (let i = 0; i < n; i++) {
    if (angles[i] < 0.6) continue;                 // moins de ~35° : pas un coin
    let maxi = true;
    for (let d = -k; d <= k; d++) {
      const j = ferme ? (i + d + n) % n : i + d;
      if (j < 0 || j >= n || j === i) continue;
      if (angles[j] > angles[i] || (angles[j] === angles[i] && j < i)) { maxi = false; break; }
    }
    if (maxi) trouves.push(i);
  }
  return trouves;
}

export function reconnaitre(points) {
  if (points.length < 9) return null;
  const total = longueur(points);
  if (total < 18) return null;
  const pts = reechantillonner(points, 64);
  const [sx, sy] = pts[0], [ex, ey] = pts[pts.length - 1];
  const corde = Math.hypot(ex - sx, ey - sy);
  // ligne : rien ne s'écarte de la droite début → fin
  let ecart = 0;
  for (const [x, y] of pts) {
    const t = corde ? ((x - sx) * (ex - sx) + (y - sy) * (ey - sy)) / (corde * corde) : 0;
    ecart = Math.max(ecart, Math.hypot(x - (sx + t * (ex - sx)), y - (sy + t * (ey - sy))));
  }
  if (corde > 0.85 * total && ecart < Math.max(3, 0.07 * corde)) {
    // presque horizontale ou verticale : on la redresse
    let [x2, y2] = [ex, ey];
    const angle = Math.abs(Math.atan2(ey - sy, ex - sx));
    if (Math.min(angle, Math.PI - angle) < 0.09) y2 = sy;
    else if (Math.abs(angle - Math.PI / 2) < 0.09) x2 = sx;
    return { forme: "ligne", ferme: false, points: aplat([[sx, sy], [x2, y2]]) };
  }
  // formes fermées : le bout revient près du début
  if (corde > Math.max(24, 0.22 * total)) return null;
  const ferme = pts.slice(0, -1);
  const b = boite(ferme);
  if (b.w < 10 || b.h < 10) return null;
  const c = coins(ferme, true);
  if (c.length === 3) return { forme: "triangle", ferme: true, points: aplat(c.map((i) => ferme[i])) };
  if (c.length === 4) {
    const s = c.map((i) => ferme[i]);
    // côtés à peu près droits : rectangle aligné sur la page ; sinon le quadrilatère tel quel
    const penche = s.some((p, i) => {
      const q = s[(i + 1) % 4];
      const a = Math.abs(Math.atan2(q[1] - p[1], q[0] - p[0])) % (Math.PI / 2);
      return Math.min(a, Math.PI / 2 - a) > 0.26;
    });
    const sommets = penche ? s : [[b.x0, b.y0], [b.x1, b.y0], [b.x1, b.y1], [b.x0, b.y1]];
    return { forme: "rectangle", ferme: true, points: aplat(sommets) };
  }
  if (c.length <= 1) {
    // ellipse : chaque point à peu près à la même « distance normalisée » du centre
    const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, rx = b.w / 2, ry = b.h / 2;
    let erreur = 0;
    for (const [x, y] of ferme) erreur += Math.abs(Math.hypot((x - cx) / rx, (y - cy) / ry) - 1);
    if (erreur / ferme.length > 0.16) return null;
    const rond = Math.abs(rx - ry) < 0.12 * Math.max(rx, ry);       // presque un cercle : un cercle
    const r = (rx + ry) / 2;
    const sommets = [];
    for (let k = 0; k < 72; k++) {
      const a = (k / 72) * Math.PI * 2;
      sommets.push([cx + Math.cos(a) * (rond ? r : rx), cy + Math.sin(a) * (rond ? r : ry)]);
    }
    return { forme: "ellipse", ferme: true, points: aplat(sommets) };
  }
  return null;
}

// Gribouillis : beaucoup d'allers-retours sur une petite surface.
export function gribouillis(points) {
  if (points.length < 3 * 12) return false;
  const pts = reechantillonner(points, 48);
  const b = boite(pts);
  const diag = Math.hypot(b.w, b.h);
  if (!diag || longueur(points) / diag < 2.6) return false;
  let demis = 0;
  for (const axe of [0, 1]) {
    let sens = 0, n = 0, cumul = 0;
    for (let i = 1; i < pts.length; i++) {
      const d = pts[i][axe] - pts[i - 1][axe];
      cumul += d;
      if (Math.abs(cumul) < diag * 0.08) continue;   // tremblement : pas un vrai changement de sens
      const s = Math.sign(cumul);
      if (sens && s !== sens) n++;
      sens = s;
      cumul = 0;
    }
    demis = Math.max(demis, n);
  }
  return demis >= 4;
}

// Ce que le gribouillis recouvre : touché par lui, et surtout dans sa surface (un long trait qu'il
// ne fait que croiser n'est pas effacé).
export function cibles(items, points, exclu = null) {
  const g = bornes({ points, largeur: 0, outil: "surligneur" });
  const pas = Math.max(3, Math.floor(points.length / 3 / 60)) * 3;
  return items.filter((it) => {
    if (it === exclu) return false;
    const b = bornes(it);
    const ix = Math.max(0, Math.min(b.x + b.w, g.x + g.w) - Math.max(b.x, g.x));
    const iy = Math.max(0, Math.min(b.y + b.h, g.y + g.h) - Math.max(b.y, g.y));
    if (ix * iy < 0.5 * Math.max(1, b.w * b.h)) return false;
    for (let i = 0; i < points.length; i += pas) if (touche(it, points[i], points[i + 1], 2)) return true;
    return false;
  });
}
