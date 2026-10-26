// Géométrie : gomme, lasso, formes parfaites, reconnaissance de formes.

export function distToSeg(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const l2 = dx * dx + dy * dy;
  let t = l2 ? ((px - ax) * dx + (py - ay) * dy) / l2 : 0;
  t = Math.max(0, Math.min(1, t));
  const x = ax + t * dx, y = ay + t * dy;
  return Math.hypot(px - x, py - y);
}

export function strokeHit(it, x, y, r) {
  const p = it.points;
  const rr = r + it.width / 2;
  if (p.length === 3) return Math.hypot(p[0] - x, p[1] - y) <= rr;
  for (let i = 3; i < p.length; i += 3) {
    if (distToSeg(x, y, p[i - 3], p[i - 2], p[i], p[i + 1]) <= rr) return true;
  }
  return false;
}

// Gomme précise : retire les points touchés et coupe le trait en morceaux.
export function eraseFromStroke(it, x, y, r) {
  const p = it.points;
  const rr = r + it.width / 2;
  const runs = [];
  let cur = [];
  let hit = false;
  for (let i = 0; i < p.length; i += 3) {
    if (Math.hypot(p[i] - x, p[i + 1] - y) <= rr) {
      hit = true;
      if (cur.length >= 6) runs.push(cur);
      cur = [];
    } else cur.push(p[i], p[i + 1], p[i + 2]);
  }
  if (!hit) return null;
  if (cur.length >= 6) runs.push(cur);
  return runs.map((pts) => ({ ...it, points: pts }));
}

export function pointInPoly(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 2; i < poly.length; j = i, i += 2) {
    const xi = poly[i], yi = poly[i + 1], xj = poly[j], yj = poly[j + 1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function itemInLasso(it, poly) {
  if (it.type === 'stroke') {
    const p = it.points;
    let inside = 0;
    const n = p.length / 3;
    for (let i = 0; i < p.length; i += 3) if (pointInPoly(p[i], p[i + 1], poly)) inside++;
    return inside / n >= 0.5;
  }
  return pointInPoly(it.x + it.w / 2, it.y + (it.h || 20) / 2, poly);
}

// --- Formes parfaites ---------------------------------------------------------
function pts(list) {
  const out = [];
  for (const [x, y] of list) out.push(x, y, 0.5);
  return out;
}

export function shapePoints(kind, x0, y0, x1, y1) {
  const l = Math.min(x0, x1), r = Math.max(x0, x1), t = Math.min(y0, y1), b = Math.max(y0, y1);
  if (kind === 'line') return pts([[x0, y0], [x1, y1]]);
  if (kind === 'arrow') {
    const a = Math.atan2(y1 - y0, x1 - x0);
    const len = Math.min(22, Math.hypot(x1 - x0, y1 - y0) * 0.35);
    const h1 = [x1 - len * Math.cos(a - 0.45), y1 - len * Math.sin(a - 0.45)];
    const h2 = [x1 - len * Math.cos(a + 0.45), y1 - len * Math.sin(a + 0.45)];
    return pts([[x0, y0], [x1, y1], h1, [x1, y1], h2]);
  }
  if (kind === 'rect') return pts([[l, t], [r, t], [r, b], [l, b], [l, t]]);
  if (kind === 'triangle') return pts([[(l + r) / 2, t], [r, b], [l, b], [(l + r) / 2, t]]);
  if (kind === 'ellipse') {
    const cx = (l + r) / 2, cy = (t + b) / 2, rx = (r - l) / 2, ry = (b - t) / 2;
    const list = [];
    for (let i = 0; i <= 64; i++) {
      const a = (i / 64) * Math.PI * 2;
      list.push([cx + rx * Math.cos(a), cy + ry * Math.sin(a)]);
    }
    return pts(list);
  }
  return pts([[x0, y0], [x1, y1]]);
}

// --- Reconnaissance : « maintenir à la fin du trait » transforme le dessin ---
// en ligne, rectangle, triangle ou ellipse parfaits.
function simplify(points, eps) {
  // Ramer–Douglas–Peucker sur [x, y]
  if (points.length < 3) return points;
  let dmax = 0, idx = 0;
  const [ax, ay] = points[0], [bx, by] = points[points.length - 1];
  for (let i = 1; i < points.length - 1; i++) {
    const d = distToSeg(points[i][0], points[i][1], ax, ay, bx, by);
    if (d > dmax) { dmax = d; idx = i; }
  }
  if (dmax > eps) {
    const a = simplify(points.slice(0, idx + 1), eps);
    const b = simplify(points.slice(idx), eps);
    return a.slice(0, -1).concat(b);
  }
  return [points[0], points[points.length - 1]];
}

export function recognize(flat) {
  const P = [];
  for (let i = 0; i < flat.length; i += 3) P.push([flat[i], flat[i + 1]]);
  if (P.length < 4) return null;
  let l = Infinity, r = -Infinity, t = Infinity, b = -Infinity, len = 0;
  for (let i = 0; i < P.length; i++) {
    const [x, y] = P[i];
    l = Math.min(l, x); r = Math.max(r, x); t = Math.min(t, y); b = Math.max(b, y);
    if (i) len += Math.hypot(x - P[i - 1][0], y - P[i - 1][1]);
  }
  const size = Math.max(r - l, b - t);
  if (size < 12) return null;
  const [sx, sy] = P[0], [ex, ey] = P[P.length - 1];
  const direct = Math.hypot(ex - sx, ey - sy);
  if (direct / len > 0.92) return { kind: 'line', box: [sx, sy, ex, ey] };
  const closed = direct < size * 0.3;
  if (!closed) return null;
  const poly = simplify(P, size * 0.09);
  const corners = poly.length - 1; // le dernier point rejoint le premier
  if (corners === 3) return { kind: 'triangle', box: [l, t, r, b] };
  if (corners === 4) return { kind: 'rect', box: [l, t, r, b] };
  // ellipse : distance au centre assez régulière (normalisée)
  const cx = (l + r) / 2, cy = (t + b) / 2, rx = (r - l) / 2 || 1, ry = (b - t) / 2 || 1;
  let dev = 0;
  for (const [x, y] of P) dev += Math.abs(Math.hypot((x - cx) / rx, (y - cy) / ry) - 1);
  if (dev / P.length < 0.2) return { kind: 'ellipse', box: [l, t, r, b] };
  return null;
}

export function transformItem(it, fn) {
  // fn(x, y) => [x, y] ; renvoie une copie transformée
  if (it.type === 'stroke') {
    const p = it.points.slice();
    for (let i = 0; i < p.length; i += 3) {
      const [x, y] = fn(p[i], p[i + 1]);
      p[i] = x; p[i + 1] = y;
    }
    return { ...it, points: p };
  }
  const [x0, y0] = fn(it.x, it.y);
  const [x1, y1] = fn(it.x + it.w, it.y + (it.h || 0));
  const out = { ...it, x: x0, y: y0, w: Math.max(10, x1 - x0) };
  if (it.type === 'image') out.h = Math.max(10, y1 - y0);
  if (it.type === 'text') out.size = Math.max(6, it.size * (out.w / it.w));
  return out;
}
