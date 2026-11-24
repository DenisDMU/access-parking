/* Access — plan 3D du parking (onglet « Plan 3D » du dashboard).

   Scène three.js construite à partir de l'occupation renvoyée par
   `GET /api/v1/access/parking` (catégories de Parking : capacité, places
   prises, places mises de côté) et des présences d'Access. Chaque catégorie
   devient une zone du parking, chaque place prise un véhicule du bon type
   (citadine, berline, SUV, électrique, utilitaire, camping-car, moto,
   scooter). Quand l'occupation change, les véhicules entrent par la
   barrière et vont se garer, ou sortent.

   Sans clé ou si Parking ne répond pas : données de démonstration,
   clairement signalées. Aucune ressource externe : three.js est servi par
   Access (`vendor/`). Aucune plaque : le plan ne connaît que des compteurs
   et des identifiants pseudonymisés. */

import * as THREE from "./vendor/three-0.160.0.module.min.js";

// --- Catégories de Parking → zones du plan -----------------------------------

const KINDS = {
  STANDARD: { w: 2.6, d: 5.0, color: "#7287fd", models: ["hatch", "sedan", "suv", "sedan", "hatch"] },
  ELECTRIC: { w: 2.7, d: 5.0, color: "#40a02b", models: ["ev", "ev", "hatch"] },
  HANDICAPPED: { w: 3.7, d: 5.0, color: "#04a5e5", models: ["sedan", "suv", "hatch"] },
  XL: { w: 3.5, d: 7.2, color: "#fe640b", models: ["van", "camper", "van"] },
  TWO_WHEELS: { w: 1.35, d: 2.6, color: "#df8e1d", models: ["moto", "scooter"] },
};
const FALLBACK_KIND = { w: 2.6, d: 5.0, color: "#8839ef", models: ["sedan", "hatch"] };
const ZONE_ORDER = ["HANDICAPPED", "ELECTRIC", "TWO_WHEELS", "STANDARD", "XL"];
const MAX_SPOTS = 260; // au-delà, une place affichée en représente plusieurs

const LANE = 7; // voie d'accès à double sens, le long du parking
const IN_X = 1.75;
const OUT_X = 5.25;
const AISLE = 6.4;
const ROAD_Z = -14.5;
const ROAD_NEAR = -12.75; // voie côté parking (vers +x)
const ROAD_FAR = -16.25; // voie opposée (vers -x)

const PAINTS = [
  "#f4f5f7", "#f4f5f7", "#c9cdd6", "#c9cdd6", "#8b909c", "#2b2e37", "#16181d", "#d92b3a",
  "#1f5fd0", "#12305e", "#18877f", "#f2b01e", "#ef6a1c", "#3d8a3a", "#d9c7a3", "#7a2d8f",
];
const GLASS = "#18212d";
const TIRE = "#15161a";
const HUB = "#b9bec9";
const TRIM = "#262932";
const BLANK = "#f1f1ee"; // rectangle blanc, sans aucun numéro
const HEAD = "#fff2c2";
const TAIL = "#ff2638";

const SKY = {
  day: {
    top: "#3f9df0", hor: "#cfe9ff", grass: "#7fc463", sun: "#fff2dc", sunI: 3.0,
    hemiSky: "#d6ecff", hemiGround: "#6f8f5c", hemiI: 0.9, exposure: 1.0,
    cloud: "#ffffff", cloudO: 0.95, asphalt: "#555a69", road: "#474b58",
  },
  night: {
    top: "#060a1c", hor: "#1b2344", grass: "#1d3a2b", sun: "#a9bcff", sunI: 1.25,
    hemiSky: "#4a5c9c", hemiGround: "#10152a", hemiI: 1.05, exposure: 1.15,
    cloud: "#2c3454", cloudO: 0.5, asphalt: "#343847", road: "#2b2e3a",
  },
};

// --- Utilitaires ---------------------------------------------------------------

function mulberry(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const lerp = (a, b, t) => a + (b - a) * t;
function angleTo(from, to, k) {
  let d = (to - from) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return from + d * k;
}

// --- Géométrie : pièces fusionnées en un seul maillage par modèle ---------------

function part(geo, color, t) {
  t = t || {};
  const g = geo.index ? geo.toNonIndexed() : geo;
  g.applyMatrix4(
    new THREE.Matrix4().compose(
      new THREE.Vector3(t.x || 0, t.y || 0, t.z || 0),
      new THREE.Quaternion().setFromEuler(new THREE.Euler(t.rx || 0, t.ry || 0, t.rz || 0)),
      new THREE.Vector3(t.sx || 1, t.sy || 1, t.sz || 1),
    ),
  );
  return { g, color };
}
const box = (w, h, d, color, t) => part(new THREE.BoxGeometry(w, h, d), color, t);
const cyl = (r, len, color, t, seg) => part(new THREE.CylinderGeometry(r, r, len, seg || 16), color, t);
const ball = (r, color, t) => part(new THREE.SphereGeometry(r, 12, 8), color, t);

/* Profil latéral (longueur, hauteur) extrudé sur la largeur, bords adoucis :
   c'est ce qui donne une vraie silhouette de voiture. */
function prof(points, width, color, bevel) {
  bevel = bevel == null ? 0.07 : bevel;
  const shape = new THREE.Shape();
  points.forEach((p, i) => (i ? shape.lineTo(p[0], p[1]) : shape.moveTo(p[0], p[1])));
  shape.closePath();
  const depth = Math.max(0.02, width - 2 * bevel);
  const g = new THREE.ExtrudeGeometry(shape, {
    depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel * 0.9,
    bevelSegments: 2, steps: 1, curveSegments: 4,
  });
  g.rotateY(-Math.PI / 2); // longueur du profil → axe z, largeur → axe x
  g.translate(depth / 2, 0, 0);
  return part(g, color);
}

function merge(parts, withColor) {
  let n = 0;
  parts.forEach((p) => (n += p.g.attributes.position.count));
  const pos = new Float32Array(n * 3);
  const nor = new Float32Array(n * 3);
  const col = withColor ? new Float32Array(n * 3) : null;
  const c = new THREE.Color();
  let o = 0;
  parts.forEach((p) => {
    const count = p.g.attributes.position.count;
    pos.set(p.g.attributes.position.array, o * 3);
    nor.set(p.g.attributes.normal.array, o * 3);
    if (col) {
      c.set(p.color);
      for (let i = 0; i < count; i++) {
        col[(o + i) * 3] = c.r;
        col[(o + i) * 3 + 1] = c.g;
        col[(o + i) * 3 + 2] = c.b;
      }
    }
    o += count;
    p.g.dispose();
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
  if (col) g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.computeBoundingSphere();
  return g;
}

// --- Modèles de véhicules (nez vers +z, posés sur y = 0) ----------------------

function wheels(detail, r, w, halfTrack, zs) {
  zs.forEach((z) =>
    [-1, 1].forEach((sx) => {
      // La roue dépasse un peu de la carrosserie, dans un passage de roue sombre.
      const x = sx * (halfTrack + 0.07);
      const t = { x, y: r, z, rz: Math.PI / 2 };
      detail.push(cyl(r + 0.09, 0.05, TRIM, { x: sx * (halfTrack + 0.115), y: r + 0.02, z, rz: Math.PI / 2 }, 18));
      detail.push(cyl(r, w, TIRE, t, 18));
      detail.push(cyl(r * 0.56, w + 0.03, HUB, t, 10));
    }),
  );
}

function car(spec) {
  const paint = [], detail = [], lights = [];
  const W = spec.W;
  const front = Math.max.apply(null, spec.body.map((p) => p[0])) + 0.06;
  const back = Math.min.apply(null, spec.body.map((p) => p[0])) - 0.06;
  paint.push(prof(spec.body, W, "#ffffff"));
  detail.push(prof(spec.glass, W - 0.24, GLASS, 0.05));
  paint.push(prof(spec.roof, W - 0.3, "#ffffff", 0.04));
  wheels(detail, spec.r, 0.25, W / 2 - 0.11, spec.axles);
  detail.push(box(W + 0.02, 0.13, front - back - 0.9, TRIM, { y: spec.body[0][1] + 0.05, z: (front + back) / 2 }));
  [-1, 1].forEach((sx) => {
    if (!spec.lightBar) {
      lights.push(box(0.38, 0.12, 0.08, HEAD, { x: sx * (W / 2 - 0.34), y: spec.ly, z: front }));
      lights.push(box(0.36, 0.11, 0.08, TAIL, { x: sx * (W / 2 - 0.32), y: spec.ly + 0.1, z: back }));
    }
    paint.push(box(0.17, 0.1, 0.2, "#ffffff", { x: sx * (W / 2 + 0.07), y: spec.my, z: spec.mz }));
  });
  if (spec.lightBar) {
    lights.push(box(W - 0.4, 0.05, 0.08, HEAD, { y: spec.ly + 0.04, z: front }));
    lights.push(box(W - 0.36, 0.05, 0.08, TAIL, { y: spec.ly + 0.14, z: back }));
  } else {
    detail.push(box(W * 0.4, 0.15, 0.06, TRIM, { y: spec.ly - 0.02, z: front + 0.005 }));
  }
  detail.push(box(0.5, 0.12, 0.04, BLANK, { y: spec.ly - 0.22, z: front + 0.02 }));
  detail.push(box(0.5, 0.12, 0.04, BLANK, { y: spec.ly - 0.12, z: back - 0.02 }));
  if (spec.extra) spec.extra(paint, detail, lights);
  return { paint, detail, lights };
}

function slantedGlass(detail, W, s0, y0, s1, y1) {
  // Vitre posée sur un pan incliné du profil, entre (s0, y0) et (s1, y1).
  const len = Math.hypot(s1 - s0, y1 - y0);
  const a = Math.atan2(s1 - s0, y1 - y0);
  const ny = -Math.sin(a), nz = Math.cos(a);
  detail.push(
    box(W, len * 0.82, 0.06, GLASS, {
      y: (y0 + y1) / 2 + ny * 0.07, z: (s0 + s1) / 2 + nz * 0.07, rx: a,
    }),
  );
}

function van(camper) {
  const paint = [], detail = [], lights = [];
  const W = camper ? 2.25 : 2.1;
  const H = camper ? 2.95 : 2.5;
  const body = camper
    ? [[-3.3, 0.45], [3.2, 0.45], [3.3, 0.85], [3.2, 1.3], [2.75, 1.9], [3.0, 1.95], [3.0, H], [-3.3, H]]
    : [[-3.05, 0.42], [3.0, 0.42], [3.1, 0.8], [3.0, 1.25], [2.35, 2.0], [2.2, H], [-3.05, H]];
  paint.push(prof(body, W, "#ffffff", 0.08));
  const front = (camper ? 3.3 : 3.1) + 0.07;
  const back = (camper ? -3.3 : -3.05) - 0.07;
  if (camper) slantedGlass(detail, W - 0.3, 3.2, 1.3, 2.75, 1.9);
  else slantedGlass(detail, W - 0.3, 3.0, 1.25, 2.35, 2.0);
  [-1, 1].forEach((sx) => {
    const side = sx * (W / 2 + 0.005);
    detail.push(box(0.05, 0.5, 0.75, GLASS, { x: side, y: 1.62, z: camper ? 2.35 : 1.85 }));
    if (camper) {
      detail.push(box(0.05, 0.6, 1.3, GLASS, { x: side, y: 2.05, z: 0.2 }));
      detail.push(box(0.05, 0.5, 0.8, GLASS, { x: side, y: 2.05, z: -2.0 }));
      detail.push(box(0.05, 0.16, 5.6, "#18a999", { x: side, y: 1.28, z: -0.4 }));
      detail.push(box(0.05, 0.07, 5.6, "#f2b01e", { x: side, y: 1.1, z: -0.4 }));
    } else {
      detail.push(box(0.05, 0.1, 4.6, TRIM, { x: side, y: 1.15, z: -0.6 }));
    }
    lights.push(box(0.34, 0.16, 0.08, HEAD, { x: sx * (W / 2 - 0.3), y: 0.95, z: front }));
    lights.push(box(0.16, 0.5, 0.08, TAIL, { x: sx * (W / 2 - 0.14), y: 1.3, z: back }));
    paint.push(box(0.18, 0.26, 0.16, "#ffffff", { x: sx * (W / 2 + 0.1), y: 1.75, z: camper ? 2.7 : 2.2 }));
  });
  if (camper) {
    detail.push(box(0.7, 0.14, 0.7, "#d5d8de", { y: H + 0.13, z: -1.0 }));
    detail.push(cyl(0.09, 3.4, "#d5d8de", { x: W / 2 + 0.1, y: H - 0.2, z: -0.4, rx: Math.PI / 2 }, 10));
  }
  detail.push(box(W * 0.5, 0.2, 0.06, TRIM, { y: 0.92, z: front + 0.005 }));
  detail.push(box(W + 0.03, 0.2, 0.4, TRIM, { y: 0.55, z: front - 0.2 }));
  detail.push(box(W + 0.03, 0.2, 0.3, TRIM, { y: 0.55, z: back + 0.15 }));
  detail.push(box(0.5, 0.12, 0.04, BLANK, { y: 0.62, z: front + 0.02 }));
  detail.push(box(0.5, 0.12, 0.04, BLANK, { y: 0.75, z: back - 0.02 }));
  wheels(detail, 0.4, 0.28, W / 2 - 0.12, camper ? [2.1, -2.0] : [2.0, -1.9]);
  return { paint, detail, lights };
}

function moto() {
  const paint = [], detail = [], lights = [];
  [0.72, -0.72].forEach((z) => {
    detail.push(cyl(0.31, 0.13, TIRE, { y: 0.31, z, rz: Math.PI / 2 }, 18));
    detail.push(cyl(0.15, 0.15, HUB, { y: 0.31, z, rz: Math.PI / 2 }, 10));
  });
  [-0.08, 0.08].forEach((x) => detail.push(box(0.05, 0.78, 0.05, "#9aa0ad", { x, y: 0.68, z: 0.6, rx: -0.38 })));
  detail.push(box(0.3, 0.34, 0.6, TRIM, { y: 0.5, z: -0.02 }));
  detail.push(box(0.08, 0.06, 0.8, "#9aa0ad", { y: 0.36, z: -0.4 }));
  paint.push(ball(0.22, "#ffffff", { y: 0.88, z: 0.14, sx: 0.85, sy: 0.62, sz: 1.5 }));
  paint.push(ball(0.2, "#ffffff", { y: 0.99, z: 0.62, sx: 0.8, sy: 0.85, sz: 0.8 }));
  paint.push(box(0.22, 0.12, 0.34, "#ffffff", { y: 0.93, z: -0.74, rx: -0.2 }));
  detail.push(box(0.2, 0.2, 0.05, GLASS, { y: 1.14, z: 0.7, rx: -0.5 }));
  detail.push(box(0.28, 0.1, 0.62, "#101114", { y: 0.86, z: -0.38 }));
  detail.push(box(0.64, 0.04, 0.05, TRIM, { y: 1.08, z: 0.5 }));
  detail.push(cyl(0.055, 0.7, "#aeb3bf", { x: 0.18, y: 0.42, z: -0.5, rx: Math.PI / 2 }, 10));
  lights.push(box(0.16, 0.1, 0.05, HEAD, { y: 0.97, z: 0.79 }));
  lights.push(box(0.14, 0.06, 0.05, TAIL, { y: 0.93, z: -0.93 }));
  return { paint, detail, lights };
}

function scooter() {
  const paint = [], detail = [], lights = [];
  [0.62, -0.62].forEach((z) => {
    detail.push(cyl(0.22, 0.13, TIRE, { y: 0.22, z, rz: Math.PI / 2 }, 16));
    detail.push(cyl(0.1, 0.15, HUB, { y: 0.22, z, rz: Math.PI / 2 }, 10));
  });
  paint.push(box(0.36, 0.09, 0.62, "#ffffff", { y: 0.3, z: 0.05 }));
  paint.push(box(0.42, 0.66, 0.09, "#ffffff", { y: 0.62, z: 0.5, rx: -0.22 }));
  paint.push(box(0.38, 0.36, 0.74, "#ffffff", { y: 0.52, z: -0.42 }));
  paint.push(box(0.3, 0.1, 0.3, "#ffffff", { y: 0.3, z: 0.66 }));
  detail.push(box(0.05, 0.5, 0.05, "#9aa0ad", { y: 0.98, z: 0.54, rx: -0.22 }));
  detail.push(box(0.58, 0.04, 0.05, TRIM, { y: 1.14, z: 0.5 }));
  detail.push(box(0.32, 0.09, 0.68, "#101114", { y: 0.75, z: -0.4 }));
  detail.push(box(0.38, 0.3, 0.36, TRIM, { y: 0.95, z: -0.88 }));
  lights.push(box(0.16, 0.1, 0.05, HEAD, { y: 0.78, z: 0.6 }));
  lights.push(box(0.2, 0.06, 0.05, TAIL, { y: 0.6, z: -0.8 }));
  return { paint, detail, lights };
}

const MODELS = {
  hatch: {
    label: "Citadine", traffic: true,
    build: () => car({
      W: 1.75, r: 0.31, axles: [1.22, -1.22], ly: 0.66, my: 0.98, mz: 0.9,
      body: [[-1.9, 0.32], [1.95, 0.32], [2.0, 0.6], [1.85, 0.8], [0.95, 0.92], [-1.85, 0.95], [-1.95, 0.6]],
      glass: [[1.0, 0.88], [0.45, 1.4], [-1.45, 1.4], [-1.85, 0.9]],
      roof: [[0.48, 1.37], [0.4, 1.46], [-1.42, 1.46], [-1.5, 1.37]],
    }),
  },
  sedan: {
    label: "Berline", traffic: true,
    build: () => car({
      W: 1.8, r: 0.33, axles: [1.38, -1.38], ly: 0.66, my: 0.96, mz: 0.85,
      body: [[-2.2, 0.32], [2.2, 0.32], [2.25, 0.6], [2.1, 0.78], [0.9, 0.9], [-1.5, 0.92], [-2.2, 0.86], [-2.25, 0.58]],
      glass: [[0.95, 0.86], [0.3, 1.36], [-0.95, 1.36], [-1.6, 0.88]],
      roof: [[0.33, 1.33], [0.24, 1.42], [-0.9, 1.42], [-1.0, 1.33]],
    }),
  },
  suv: {
    label: "SUV", traffic: true,
    build: () => car({
      W: 1.92, r: 0.39, axles: [1.45, -1.45], ly: 0.84, my: 1.2, mz: 0.95,
      body: [[-2.3, 0.42], [2.3, 0.42], [2.35, 0.75], [2.2, 1.0], [1.0, 1.1], [-2.25, 1.12], [-2.35, 0.75]],
      glass: [[1.05, 1.05], [0.55, 1.66], [-1.85, 1.66], [-2.2, 1.08]],
      roof: [[0.58, 1.63], [0.5, 1.73], [-1.82, 1.73], [-1.9, 1.63]],
      extra: (paint, detail) => {
        [-0.62, 0.62].forEach((x) => detail.push(box(0.06, 0.06, 2.0, TRIM, { x, y: 1.8, z: -0.65 })));
      },
    }),
  },
  ev: {
    label: "Électrique", traffic: true,
    build: () => car({
      W: 1.85, r: 0.34, axles: [1.42, -1.42], ly: 0.64, my: 0.94, mz: 1.05, lightBar: true,
      body: [[-2.25, 0.3], [2.25, 0.3], [2.3, 0.55], [2.1, 0.74], [1.2, 0.86], [-1.7, 0.95], [-2.25, 0.9], [-2.3, 0.55]],
      glass: [[1.25, 0.82], [0.2, 1.38], [-0.7, 1.4], [-1.9, 0.92]],
      roof: [[0.24, 1.35], [0.1, 1.44], [-0.68, 1.45], [-0.85, 1.36]],
      extra: (paint, detail) => detail.push(box(1.88, 0.05, 2.7, "#2fd07c", { y: 0.6, z: -0.1 })),
    }),
  },
  van: { label: "Utilitaire", build: () => van(false) },
  camper: { label: "Camping-car", paints: ["#f4f5f7", "#eceae2", "#f4f5f7", "#dfe3ea"], build: () => van(true) },
  moto: { label: "Moto", lean: 0.16, build: moto },
  scooter: { label: "Scooter", lean: 0.14, build: scooter },
};

// --- Trajets : polyligne aux angles arrondis -----------------------------------

function makePath(pts, radius) {
  const P = [];
  const push = (x, z) => {
    const n = P.length;
    if (n && Math.hypot(P[n - 1][0] - x, P[n - 1][1] - z) < 1e-4) return;
    P.push([x, z]);
  };
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    if (i === 0 || i === pts.length - 1) { push(p[0], p[1]); continue; }
    const a = pts[i - 1], b = pts[i + 1];
    const d1 = Math.hypot(p[0] - a[0], p[1] - a[1]);
    const d2 = Math.hypot(b[0] - p[0], b[1] - p[1]);
    const r = Math.min(radius, d1 * 0.5, d2 * 0.5);
    if (r < 0.05) { push(p[0], p[1]); continue; }
    const s = [p[0] + ((a[0] - p[0]) / d1) * r, p[1] + ((a[1] - p[1]) / d1) * r];
    const e = [p[0] + ((b[0] - p[0]) / d2) * r, p[1] + ((b[1] - p[1]) / d2) * r];
    for (let k = 0; k <= 10; k++) {
      const t = k / 10, u = 1 - t;
      push(u * u * s[0] + 2 * u * t * p[0] + t * t * e[0], u * u * s[1] + 2 * u * t * p[1] + t * t * e[1]);
    }
  }
  const cum = [0];
  for (let i = 1; i < P.length; i++) cum.push(cum[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
  return { P, cum, total: cum[cum.length - 1] };
}
function pathAt(path, s, out) {
  const { P, cum } = path;
  s = clamp(s, 0, path.total);
  let i = 1;
  while (i < cum.length - 1 && cum[i] < s) i++;
  const t = (s - cum[i - 1]) / Math.max(1e-6, cum[i] - cum[i - 1]);
  out.x = lerp(P[i - 1][0], P[i][0], t);
  out.z = lerp(P[i - 1][1], P[i][1], t);
  out.h = Math.atan2(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]);
}

// --- Textures dessinées (aucune image externe) ---------------------------------

function canvasTexture(size, draw, h) {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = h || size;
  draw(c.getContext("2d"), c.width, c.height);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}
function noiseTexture(seed, base, spread) {
  const rnd = mulberry(seed);
  const t = canvasTexture(256, (ctx, w) => {
    ctx.fillStyle = "rgb(" + base + "," + base + "," + base + ")";
    ctx.fillRect(0, 0, w, w);
    for (let i = 0; i < 5200; i++) {
      const v = Math.round(base + (rnd() - 0.5) * spread);
      ctx.fillStyle = "rgba(" + v + "," + v + "," + v + "," + (0.25 + rnd() * 0.5) + ")";
      const s = 1 + rnd() * 2.4;
      ctx.fillRect(rnd() * w, rnd() * w, s, s);
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
const PICTOS = {
  HANDICAPPED: (ctx, s) => {
    ctx.fillStyle = "#1e66f5"; roundRect(ctx, 6, 6, s - 12, s - 12, 22); ctx.fill();
    ctx.strokeStyle = "#fff"; ctx.fillStyle = "#fff"; ctx.lineWidth = 11; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath(); ctx.arc(s * 0.44, s * 0.24, 10, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.moveTo(s * 0.44, s * 0.36); ctx.lineTo(s * 0.44, s * 0.58); ctx.lineTo(s * 0.64, s * 0.58); ctx.lineTo(s * 0.74, s * 0.78); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(s * 0.44, s * 0.45); ctx.lineTo(s * 0.62, s * 0.45); ctx.stroke();
    ctx.beginPath(); ctx.arc(s * 0.46, s * 0.66, s * 0.17, Math.PI * 0.12, Math.PI * 1.35); ctx.stroke();
  },
  ELECTRIC: (ctx, s) => {
    ctx.fillStyle = "#40a02b"; roundRect(ctx, 6, 6, s - 12, s - 12, 22); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.beginPath();
    ctx.moveTo(s * 0.57, s * 0.14); ctx.lineTo(s * 0.3, s * 0.55); ctx.lineTo(s * 0.48, s * 0.55);
    ctx.lineTo(s * 0.42, s * 0.86); ctx.lineTo(s * 0.71, s * 0.44); ctx.lineTo(s * 0.52, s * 0.44);
    ctx.closePath(); ctx.fill();
  },
  TWO_WHEELS: (ctx, s) => {
    ctx.fillStyle = "#df8e1d"; roundRect(ctx, 6, 6, s - 12, s - 12, 22); ctx.fill();
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 9; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath(); ctx.arc(s * 0.27, s * 0.64, s * 0.13, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(s * 0.73, s * 0.64, s * 0.13, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(s * 0.27, s * 0.64); ctx.lineTo(s * 0.44, s * 0.42); ctx.lineTo(s * 0.62, s * 0.42); ctx.lineTo(s * 0.73, s * 0.64); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(s * 0.62, s * 0.42); ctx.lineTo(s * 0.58, s * 0.3); ctx.lineTo(s * 0.68, s * 0.3); ctx.stroke();
  },
  XL: (ctx, s) => {
    ctx.fillStyle = "#fe640b"; roundRect(ctx, 6, 6, s - 12, s - 12, 22); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "800 " + s * 0.48 + "px system-ui, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("XL", s / 2, s * 0.54);
  },
};

// --- Style de l'interface posée sur la scène -----------------------------------

const CSS = `
.p3d { position: relative; width: 100%; height: clamp(440px, 68vh, 780px); border-radius: 18px; overflow: hidden;
  background: #cfe9ff; isolation: isolate; user-select: none; -webkit-user-select: none; touch-action: none; }
.p3d:fullscreen { height: 100vh; border-radius: 0; }
.p3d canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; cursor: grab; outline: none; }
.p3d canvas.dragging { cursor: grabbing; }
.p3d canvas.pointing { cursor: pointer; }
.p3d-layer { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.p3d-tag { position: absolute; left: 0; top: 0; transform: translate(-50%, -100%); white-space: nowrap;
  display: flex; align-items: center; gap: 8px; padding: 5px 10px 5px 8px; border-radius: 999px;
  font: 700 12.5px/1.2 system-ui, -apple-system, "Segoe UI", sans-serif; color: #fff;
  background: color-mix(in srgb, var(--c, #555) 88%, #000); box-shadow: 0 6px 18px rgba(0,0,0,.28);
  border: 1px solid rgba(255,255,255,.35); will-change: transform; transition: opacity .25s; }
.p3d-tag i { width: 8px; height: 8px; border-radius: 50%; background: #fff; opacity: .9; }
.p3d-tag span { font-weight: 600; opacity: .92; font-variant-numeric: tabular-nums; }
.p3d-tag.gate { background: rgba(24,24,37,.82); font-weight: 600; }
.p3d-card { pointer-events: auto; position: absolute; color: var(--text, #4c4f69);
  background: linear-gradient(145deg, var(--glass-hi, rgba(255,255,255,.72)), var(--glass-lo, rgba(255,255,255,.46)));
  border: 1px solid var(--glass-border, rgba(255,255,255,.7)); border-radius: 16px;
  backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
  box-shadow: 0 12px 34px rgba(17,17,27,.22); font: 500 13px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif; }
.p3d-head { left: 14px; top: 14px; padding: 10px 14px; max-width: min(360px, calc(100% - 28px)); }
.p3d-head strong { display: block; font-size: 15px; }
.p3d-src { display: inline-flex; align-items: center; gap: 7px; margin-top: 4px; font-size: 12.5px; color: var(--subtext, #6c6f85); }
.p3d-src i { width: 9px; height: 9px; border-radius: 50%; background: var(--c, #40a02b); box-shadow: 0 0 0 4px color-mix(in srgb, var(--c, #40a02b) 25%, transparent); }
.p3d-tools { right: 14px; top: 14px; padding: 6px; display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; max-width: calc(100% - 28px); }
.p3d-tools button { all: unset; cursor: pointer; padding: 7px 11px; border-radius: 11px; font: 600 12.5px/1 system-ui, sans-serif; color: var(--subtext, #6c6f85); }
.p3d-tools button:hover { color: var(--text, #4c4f69); background: var(--field, rgba(204,208,218,.42)); }
.p3d-tools button[aria-pressed="true"] { color: var(--on-accent, #fff); background: var(--blue, #1e66f5); }
.p3d-tools button:focus-visible { outline: 2px solid var(--blue, #1e66f5); outline-offset: 2px; }
.p3d-legend { left: 14px; bottom: 14px; padding: 10px; width: min(300px, calc(100% - 28px)); }
.p3d-total { display: flex; align-items: baseline; gap: 8px; padding: 2px 6px 8px; }
.p3d-total b { font-size: 26px; line-height: 1; font-variant-numeric: tabular-nums; white-space: nowrap; }
.p3d-total span { color: var(--subtext, #6c6f85); font-size: 12.5px; }
.p3d-zone { all: unset; cursor: pointer; display: grid; grid-template-columns: 12px 1fr auto; align-items: center; gap: 2px 9px;
  width: 100%; box-sizing: border-box; padding: 6px; border-radius: 10px; }
.p3d-zone:hover, .p3d-zone:focus-visible { background: var(--field, rgba(204,208,218,.42)); }
.p3d-zone i { width: 12px; height: 12px; border-radius: 4px; background: var(--c); }
.p3d-zone em { font-style: normal; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.p3d-zone span { font-variant-numeric: tabular-nums; color: var(--subtext, #6c6f85); }
.p3d-zone u { grid-column: 2 / 4; height: 4px; border-radius: 4px; text-decoration: none; background: var(--hairline, rgba(76,79,105,.12)); overflow: hidden; }
.p3d-zone u b { display: block; height: 100%; width: 0; border-radius: 4px; background: var(--c); transition: width .6s cubic-bezier(.2,.8,.2,1); }
.p3d-note { padding: 6px 6px 0; font-size: 11.5px; color: var(--subtext, #6c6f85); }
.p3d-tip { position: absolute; left: 0; top: 0; padding: 8px 11px; max-width: 260px; pointer-events: none; opacity: 0;
  transition: opacity .12s; z-index: 3; }
.p3d-tip.on { opacity: 1; }
.p3d-tip b { display: block; }
.p3d-tip span { display: block; color: var(--subtext, #6c6f85); font-size: 12px; }
.p3d-hint { right: 14px; bottom: 14px; padding: 7px 11px; font-size: 11.5px; color: var(--subtext, #6c6f85); }
.p3d-fail { position: absolute; inset: 0; display: grid; place-items: center; padding: 24px; text-align: center;
  color: var(--text, #4c4f69); background: var(--mantle, #e6e9ef); font: 600 15px/1.4 system-ui, sans-serif; }
@media (max-width: 640px) {
  .p3d { height: clamp(420px, 70vh, 640px); }
  .p3d-hint { display: none; }
  .p3d-tools { left: 10px; right: 10px; top: 10px; max-width: none; flex-wrap: nowrap; justify-content: space-around; padding: 4px; }
  .p3d-tools button { padding: 7px 9px; font-size: 12px; }
  .p3d-tools button:last-child { display: none; }
  .p3d-head { left: 10px; top: 56px; padding: 6px 10px; max-width: calc(100% - 20px); }
  .p3d-head strong { display: none; }
  .p3d-src { margin-top: 0; font-size: 11.5px; }
  .p3d-legend { left: 10px; right: 10px; bottom: 10px; width: auto; padding: 8px; display: grid; grid-template-columns: 1fr 1fr; gap: 0 6px; }
  .p3d-total { grid-column: 1 / 3; padding: 0 4px 4px; }
  .p3d-total b { font-size: 18px; }
  .p3d-zone { padding: 4px; font-size: 12px; }
  .p3d-zone u { display: none; }
  .p3d-note { grid-column: 1 / 3; }
  .p3d-tag { font-size: 11px; padding: 3px 8px 3px 6px; gap: 6px; }
}
`;
function injectStyle() {
  if (document.getElementById("p3d-style")) return;
  const style = document.createElement("style");
  style.id = "p3d-style";
  style.textContent = CSS;
  document.head.appendChild(style);
}
function elem(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

// --- Données ---------------------------------------------------------------------

const DEMO_ZONES = [
  { name: "HANDICAPPED", label: "PMR", cap: 6, taken: 2, held: 0 },
  { name: "ELECTRIC", label: "Électrique", cap: 10, taken: 5, held: 0 },
  { name: "TWO_WHEELS", label: "Deux-roues", cap: 12, taken: 6, held: 0 },
  { name: "STANDARD", label: "Standard", cap: 38, taken: 19, held: 0 },
  { name: "XL", label: "Grand gabarit", cap: 8, taken: 3, held: 0 },
];

function liveZones(overview) {
  if (!overview || !overview.available || !Array.isArray(overview.categories)) return null;
  const zones = overview.categories
    .filter((c) => c.totalCapacity != null && c.totalCapacity > 0)
    .map((c) => ({
      name: String(c.name), label: String(c.label || c.name), cap: c.totalCapacity,
      taken: clamp(c.spotTaken || 0, 0, c.totalCapacity),
      held: clamp(c.spotHeld || 0, 0, c.totalCapacity),
    }));
  if (!zones.length) return null;
  zones.sort((a, b) => {
    const ia = ZONE_ORDER.indexOf(a.name), ib = ZONE_ORDER.indexOf(b.name);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return zones;
}

function categoryOfPresence(p) {
  if (p.placeId && String(p.placeId).indexOf(":") > 0) return String(p.placeId).split(":")[0];
  const t = p.placeType || {};
  if (t.isHandicap) return "HANDICAPPED";
  if (t.category === 1) return "TWO_WHEELS";
  if (t.isElectric) return "ELECTRIC";
  if (t.isXl) return "XL";
  return "STANDARD";
}

// --- Scène -----------------------------------------------------------------------

export function createParking3D(container, options) {
  const opts = options || {};
  injectStyle();
  container.classList.add("p3d");
  container.replaceChildren();

  const canvas = document.createElement("canvas");
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Plan 3D du parking : zones, places et véhicules présents");
  container.appendChild(canvas);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  } catch (err) {
    container.replaceChildren(elem("div", "p3d-fail", "Le plan 3D a besoin de WebGL, indisponible dans ce navigateur."));
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;

  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 1, 1800);
  const world = new THREE.Group(); // tout le parking, recentré sur l'origine
  scene.add(world);

  // Interface
  const labelLayer = elem("div", "p3d-layer");
  const head = elem("div", "p3d-card p3d-head");
  const headTitle = elem("strong", null, "Plan 3D du parking");
  const src = elem("span", "p3d-src");
  const srcDot = elem("i");
  const srcText = elem("span", null, "Chargement…");
  src.append(srcDot, srcText);
  head.append(headTitle, src);
  const tools = elem("div", "p3d-card p3d-tools");
  const legend = elem("div", "p3d-card p3d-legend");
  const tip = elem("div", "p3d-card p3d-tip");
  const tipTitle = elem("b");
  const tipSub = elem("span");
  const tipMore = elem("span");
  tip.append(tipTitle, tipSub, tipMore);
  const hint = elem("div", "p3d-card p3d-hint", "Glisser : tourner · Molette : zoom · Clic droit ou Maj : déplacer");
  container.append(labelLayer, head, tools, legend, hint, tip);

  function toolButton(label, title, onClick, pressed) {
    const b = elem("button", null, label);
    b.type = "button";
    b.title = title;
    if (pressed != null) b.setAttribute("aria-pressed", String(pressed));
    b.addEventListener("click", onClick);
    tools.appendChild(b);
    return b;
  }

  // --- Lumières, ciel ------------------------------------------------------------
  const hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xffffff, 3);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0005;
  sun.shadow.normalBias = 0.04;
  scene.add(sun, sun.target);
  scene.fog = new THREE.Fog(0xcfe9ff, 180, 620);

  const skyGeo = new THREE.SphereGeometry(900, 32, 16);
  skyGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(skyGeo.attributes.position.count * 3), 3));
  const sky = new THREE.Mesh(skyGeo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false, depthWrite: false }));
  sky.renderOrder = -10;
  scene.add(sky);

  const starGeo = new THREE.BufferGeometry();
  {
    const rnd = mulberry(7);
    const pts = new Float32Array(500 * 3);
    for (let i = 0; i < 500; i++) {
      const a = rnd() * Math.PI * 2, e = 0.08 + rnd() * 1.4;
      pts[i * 3] = Math.cos(a) * Math.cos(e) * 850;
      pts[i * 3 + 1] = Math.sin(e) * 850;
      pts[i * 3 + 2] = Math.sin(a) * Math.cos(e) * 850;
    }
    starGeo.setAttribute("position", new THREE.BufferAttribute(pts, 3));
  }
  const starMat = new THREE.PointsMaterial({ color: 0xffffff, size: 1.8, sizeAttenuation: false, transparent: true, opacity: 0, fog: false, depthWrite: false });
  scene.add(new THREE.Points(starGeo, starMat));

  const cloudMat = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true, transparent: true, fog: false });
  const clouds = new THREE.Group();
  {
    const rnd = mulberry(21);
    for (let i = 0; i < 9; i++) {
      const parts = [];
      const n = 3 + Math.floor(rnd() * 3);
      for (let k = 0; k < n; k++) {
        parts.push(part(new THREE.IcosahedronGeometry(6 + rnd() * 5, 1), "#fff", {
          x: (k - n / 2) * 8 + rnd() * 3, y: rnd() * 3, z: rnd() * 6 - 3, sy: 0.55 + rnd() * 0.2,
        }));
      }
      const mesh = new THREE.Mesh(merge(parts, false), cloudMat);
      mesh.position.set(-320 + rnd() * 640, 70 + rnd() * 40, -260 + rnd() * 520);
      mesh.userData.speed = 1.2 + rnd() * 1.6;
      clouds.add(mesh);
    }
  }
  scene.add(clouds);

  // Reflets : carte d'environnement tirée du ciel (jour et nuit).
  const pmrem = new THREE.PMREMGenerator(renderer);
  function buildEnv(theme) {
    const env = new THREE.Scene();
    const geo = new THREE.SphereGeometry(50, 24, 12);
    const col = new Float32Array(geo.attributes.position.count * 3);
    const top = new THREE.Color(theme.top), hor = new THREE.Color(theme.hor), ground = new THREE.Color(theme.grass), c = new THREE.Color();
    for (let i = 0; i < geo.attributes.position.count; i++) {
      const y = geo.attributes.position.getY(i) / 50;
      if (y >= 0) c.copy(hor).lerp(top, Math.pow(y, 0.6));
      else c.copy(hor).lerp(ground, Math.min(1, -y * 3));
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    env.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
    const disc = new THREE.Mesh(new THREE.SphereGeometry(5, 12, 8), new THREE.MeshBasicMaterial({ color: theme.sun }));
    disc.position.set(-22, 34, -18);
    env.add(disc);
    const target = pmrem.fromScene(env, 0.03);
    geo.dispose();
    return target.texture;
  }
  const envDay = buildEnv(SKY.day);
  const envNight = buildEnv(SKY.night);

  // --- Matériaux partagés -------------------------------------------------------------
  const M = {
    paint: new THREE.MeshStandardMaterial({ roughness: 0.34, metalness: 0.3, envMapIntensity: 1.1 }),
    detail: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.5, metalness: 0.25, envMapIntensity: 0.9 }),
    lights: new THREE.MeshBasicMaterial({ vertexColors: true, toneMapped: false }),
    props: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, metalness: 0.05, envMapIntensity: 0.5 }),
    asphalt: new THREE.MeshStandardMaterial({ map: noiseTexture(3, 214, 60), roughness: 0.96, metalness: 0, envMapIntensity: 0.35 }),
    road: new THREE.MeshStandardMaterial({ map: noiseTexture(5, 214, 46), roughness: 0.96, metalness: 0, envMapIntensity: 0.35 }),
    grass: new THREE.MeshStandardMaterial({ map: noiseTexture(9, 226, 44), roughness: 1, metalness: 0, envMapIntensity: 0.3 }),
    line: new THREE.MeshStandardMaterial({ color: 0xf2f3f5, roughness: 0.9, envMapIntensity: 0.3, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }),
    pad: new THREE.MeshStandardMaterial({ roughness: 0.95, transparent: true, opacity: 0.34, depthWrite: false, envMapIntensity: 0.2, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }),
    led: new THREE.MeshBasicMaterial({ toneMapped: false }),
    foliage: new THREE.MeshStandardMaterial({ flatShading: true, roughness: 0.95, envMapIntensity: 0.3 }),
    bulb: new THREE.MeshBasicMaterial({ color: 0x555a66, toneMapped: false }),
    pool: null,
    screen: new THREE.MeshBasicMaterial({ color: 0x64d7f0, toneMapped: false }),
    boothGlass: new THREE.MeshStandardMaterial({ color: 0x1b2836, roughness: 0.2, metalness: 0.4, emissive: 0xffc56b, emissiveIntensity: 0 }),
    post: new THREE.MeshStandardMaterial({ color: 0x2a2d38, roughness: 0.7 }),
    trunk: new THREE.MeshStandardMaterial({ color: 0x6b4a32, roughness: 0.9 }),
    totem: new THREE.MeshStandardMaterial({ color: 0x174fc0, roughness: 0.6 }),
  };
  M.pool = new THREE.MeshBasicMaterial({
    map: canvasTexture(128, (ctx, s) => {
      const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
      g.addColorStop(0, "rgba(255,214,140,0.95)");
      g.addColorStop(0.45, "rgba(255,196,110,0.32)");
      g.addColorStop(1, "rgba(255,190,100,0)");
      ctx.fillStyle = g; ctx.fillRect(0, 0, s, s);
    }),
    transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
    polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4,
  });
  const pictoMats = {};
  Object.keys(PICTOS).forEach((name) => {
    pictoMats[name] = new THREE.MeshStandardMaterial({
      map: canvasTexture(128, PICTOS[name]), transparent: true, roughness: 0.9, envMapIntensity: 0.2,
      polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3, side: THREE.DoubleSide,
    });
  });
  const arrowMat = new THREE.MeshStandardMaterial({
    map: canvasTexture(128, (ctx, s) => {
      ctx.fillStyle = "#f2f3f5"; ctx.beginPath();
      ctx.moveTo(s * 0.5, s * 0.04); ctx.lineTo(s * 0.86, s * 0.42); ctx.lineTo(s * 0.62, s * 0.42);
      ctx.lineTo(s * 0.62, s * 0.96); ctx.lineTo(s * 0.38, s * 0.96); ctx.lineTo(s * 0.38, s * 0.42);
      ctx.lineTo(s * 0.14, s * 0.42); ctx.closePath(); ctx.fill();
    }),
    transparent: true, roughness: 0.9, opacity: 0.85, envMapIntensity: 0.2,
    polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3,
  });
  function signMaterial(w, draw, h) {
    const map = canvasTexture(w, draw, h);
    return new THREE.MeshStandardMaterial({ map, emissive: 0xffffff, emissiveMap: map, emissiveIntensity: 0.2, roughness: 0.6, envMapIntensity: 0.3 });
  }
  const signMats = [];

  const dummy = new THREE.Object3D();
  const tmpColor = new THREE.Color();
  const HIDDEN = new THREE.Matrix4().makeScale(0, 0, 0);
  const flat = (w, d) => new THREE.PlaneGeometry(w, d).rotateX(-Math.PI / 2);

  function instanced(parent, geo, mat, items, shadow) {
    if (!items.length) return null;
    const mesh = new THREE.InstancedMesh(geo, mat, items.length);
    items.forEach((it, i) => {
      dummy.position.set(it.x || 0, it.y || 0, it.z || 0);
      dummy.rotation.set(it.rx || 0, it.ry || 0, it.rz || 0);
      dummy.scale.set(it.sx || 1, it.sy || 1, it.sz || 1);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      if (it.color != null) mesh.setColorAt(i, tmpColor.set(it.color));
    });
    mesh.frustumCulled = false;
    mesh.castShadow = shadow === "cast" || shadow === "both";
    mesh.receiveShadow = shadow === "receive" || shadow === "both";
    parent.add(mesh);
    return mesh;
  }

  // --- État ------------------------------------------------------------------------
  let lot = null; // parking construit : zones, places, flotte
  let signature = "";
  let data = { source: "demo", reason: "", zones: DEMO_ZONES.map((z) => Object.assign({}, z)), unit: 1 };
  let presences = [];
  let firstSync = true;
  let active = false;
  let raf = 0;
  let last = 0;
  let night = document.documentElement.dataset.theme === "mocha" ? 1 : 0;
  let nightGoal = night;
  let autoRotate = !reduceMotion;
  let idle = 0;
  let demoTimer = 2;
  const movers = [];
  const pops = [];
  const cam = { theta: -0.62, phi: 0.98, radius: 90, tx: 0, tz: 0, gTheta: -0.62, gPhi: 0.98, gRadius: 90, gx: 0, gz: 0, min: 14, max: 260, bx: 60, bz: 60 };

  // --- Construction du parking -------------------------------------------------------
  function displayZones(zones) {
    const total = zones.reduce((s, z) => s + z.cap, 0);
    const unit = total > MAX_SPOTS ? total / MAX_SPOTS : 1;
    return {
      unit,
      zones: zones.map((z) => {
        const n = Math.max(1, Math.round(z.cap / unit));
        const scale = (v) => (v > 0 ? clamp(Math.round(v / unit) || 1, 0, n) : 0);
        return Object.assign({}, z, { n, takenN: scale(z.taken), heldN: scale(z.held) });
      }),
    };
  }

  function computeLayout(zones) {
    const R0 = LANE + 0.8;
    const widthSum = zones.reduce((s, z) => s + z.n * (KINDS[z.name] || FALLBACK_KIND).w, 0);
    const rowLen = clamp(Math.sqrt(widthSum * 13), 26, 74);
    const rows = [];
    const islands = [];
    let cur = null;
    zones.forEach((zone) => {
      const kind = KINDS[zone.name] || FALLBACK_KIND;
      const big = kind.d > 6;
      zone.kind = kind;
      zone.spots = [];
      let left = zone.n;
      while (left > 0) {
        if (!cur || cur.free < kind.w + (cur.zones.length ? 1.4 : 0) || (cur.big !== big && kind.d > 3)) {
          cur = { x: R0, free: rowLen, depth: kind.d, big, zones: [], spots: [] };
          rows.push(cur);
        }
        if (cur.zones.length && cur.zones[cur.zones.length - 1] !== zone) {
          islands.push({ row: cur, x: cur.x + 0.7 });
          cur.x += 1.4;
          cur.free -= 1.4;
        }
        const fit = Math.min(left, Math.floor(cur.free / kind.w + 1e-6));
        if (fit <= 0) { cur = null; continue; }
        cur.zones.push(zone);
        cur.depth = Math.max(cur.depth, kind.d);
        for (let i = 0; i < fit; i++) {
          const spot = { zone, row: cur, x: cur.x + kind.w / 2, w: kind.w, d: kind.d, vehicle: null, held: false };
          cur.spots.push(spot);
          zone.spots.push(spot);
          cur.x += kind.w;
        }
        cur.free -= fit * kind.w;
        left -= fit;
      }
    });
    // Rangées : dos à dos, une allée pour deux rangées.
    let z = 3.2;
    const aisles = [];
    rows.forEach((row, i) => {
      row.z0 = z;
      row.z1 = z + row.depth;
      if (i % 2 === 0) {
        row.side = 1; // allée du côté +z
        row.aisleZ = row.z1 + AISLE / 2;
        aisles.push(row.aisleZ);
        z = row.z1 + AISLE;
      } else {
        row.side = -1;
        row.aisleZ = row.z0 - AISLE / 2;
        z = row.z1 + 1.1;
      }
      row.spots.forEach((s) => {
        s.z = row.side === 1 ? row.z1 - s.d / 2 : row.z0 + s.d / 2;
        s.nz = row.side === 1 ? -1 : 1; // sens du nez : dos à l'allée
        s.rot = s.nz === 1 ? 0 : Math.PI;
        s.aisleZ = row.aisleZ;
      });
    });
    const xMax = R0 + rowLen + 1.6;
    const zMax = z + 1.4;
    islands.forEach((it) => { it.z = (it.row.z0 + it.row.z1) / 2; });
    return { rows, aisles, islands, R0, rowLen, xMin: -0.6, xMax, zMax, cx: (xMax - 0.6) / 2, cz: (zMax - 20) / 2 };
  }

  function disposeTree(root) {
    root.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.isInstancedMesh) o.dispose();
    });
    root.removeFromParent();
  }

  function buildLot(zones) {
    if (lot) {
      disposeTree(lot.group);
      lot.textures.forEach((t) => t.dispose());
      signMats.forEach((m) => m.dispose());
    }
    movers.length = 0;
    pops.length = 0;
    labelLayer.replaceChildren();
    signMats.length = 0;

    const L = computeLayout(zones);
    const group = new THREE.Group();
    group.position.set(-L.cx, 0, -L.cz);
    world.add(group);
    const textures = [];
    const tags = [];
    const rnd = mulberry(1234);
    const W = L.xMax - L.xMin, D = L.zMax;

    // Sol : herbe, route, parking, voie d'accès
    const grass = new THREE.Mesh(new THREE.CircleGeometry(700, 48).rotateX(-Math.PI / 2), M.grass);
    M.grass.map.repeat.set(230, 230);
    grass.position.set(L.cx, -0.06, L.cz);
    grass.receiveShadow = true;
    group.add(grass);

    const lotMesh = new THREE.Mesh(flat(W, D), M.asphalt);
    M.asphalt.map.repeat.set(W / 7, D / 7);
    lotMesh.position.set(L.xMin + W / 2, 0, D / 2);
    lotMesh.receiveShadow = true;
    group.add(lotMesh);

    const drive = new THREE.Mesh(flat(LANE + 1.2, 9.2), M.road);
    drive.position.set(LANE / 2, -0.005, -4.5);
    drive.receiveShadow = true;
    group.add(drive);
    const road = new THREE.Mesh(flat(900, 9), M.road);
    M.road.map.repeat.set(1.4, 1.4);
    road.position.set(L.cx, -0.01, ROAD_Z);
    road.receiveShadow = true;
    group.add(road);

    // Décor fusionné (bordures, haies, portique, guérite, bornes…)
    const props = [];
    const curb = "#c9cdd6";
    props.push(box(0.35, 0.18, D, curb, { x: L.xMin - 0.17, y: 0.09, z: D / 2 }));
    props.push(box(0.35, 0.18, D, curb, { x: L.xMax + 0.17, y: 0.09, z: D / 2 }));
    props.push(box(W + 0.7, 0.18, 0.35, curb, { x: L.xMin + W / 2, y: 0.09, z: D + 0.17 }));
    props.push(box(L.xMax - LANE - 0.6, 0.18, 0.35, curb, { x: (L.xMax + LANE + 0.6) / 2, y: 0.09, z: -0.17 }));
    const hedge = "#2f6b3a";
    props.push(box(0.9, 0.95, D + 2, hedge, { x: L.xMax + 1.1, y: 0.47, z: D / 2 }));
    props.push(box(W + 2.2, 0.95, 0.9, hedge, { x: L.xMin + W / 2, y: 0.47, z: D + 1.1 }));
    props.push(box(0.9, 0.95, D - 6, hedge, { x: L.xMin - 1.1, y: 0.47, z: D / 2 + 3 }));
    props.push(box(L.xMax - LANE - 3, 0.95, 0.9, hedge, { x: (L.xMax + LANE + 3) / 2, y: 0.47, z: -1.1 }));
    // Trottoirs le long de la route
    props.push(box(900, 0.12, 1.4, "#b7bcc6", { x: L.cx, y: 0.02, z: ROAD_Z - 5.2 }));
    const walkL = [L.cx - 450, -0.6], walkR = [LANE + 0.6, L.cx + 450]; // de part et d'autre de l'accès
    [walkL, walkR].forEach((w) => {
      props.push(box(w[1] - w[0], 0.12, 1.4, "#b7bcc6", { x: (w[0] + w[1]) / 2, y: 0.02, z: ROAD_Z + 5.2 }));
    });
    // Îlot central des barrières
    props.push(box(0.9, 0.24, 7.5, "#b7bcc6", { x: LANE / 2, y: 0.12, z: -0.6 }));
    // Séparateurs entre rangées dos à dos
    L.rows.forEach((row, i) => {
      if (i % 2 === 1 && i < L.rows.length - 1) {
        props.push(box(L.rowLen, 0.16, 0.7, "#8fa58a", { x: L.R0 + L.rowLen / 2, y: 0.08, z: row.z1 + 0.55 }));
      }
    });
    // Portique d'entrée
    [-0.9, LANE + 0.9].forEach((x) => props.push(box(0.36, 5.2, 0.36, "#30343f", { x, y: 2.6, z: -2.2 })));
    props.push(box(LANE + 2.4, 0.9, 0.4, "#1f2330", { x: LANE / 2, y: 5.0, z: -2.2 }));
    // Guérite
    props.push(box(4.6, 0.14, 4.6, "#b7bcc6", { x: -3.6, y: 0.07, z: -3.4 }));
    props.push(box(2.6, 2.5, 3.0, "#eef0f4", { x: -3.4, y: 1.25, z: -3.4 }));
    props.push(box(3.2, 0.22, 3.6, "#1e66f5", { x: -3.4, y: 2.62, z: -3.4 }));
    // Barrières : socles
    [[LANE / 2 - 0.2, 0.2], [LANE / 2 + 0.2, 0.2]].forEach((p) => props.push(box(0.38, 1.1, 0.38, "#f2b01e", { x: p[0], y: 0.79, z: p[1] })));
    // Bornes Access (entrée et sortie)
    [[LANE / 2 - 0.15, -3.6], [LANE / 2 + 0.15, 3.4]].forEach((p) => {
      props.push(box(0.42, 1.45, 0.36, "#262a36", { x: p[0], y: 0.96, z: p[1] }));
      props.push(box(0.5, 0.08, 0.44, "#1e66f5", { x: p[0], y: 1.72, z: p[1] }));
    });
    // Totem « P »
    props.push(cyl(0.12, 4.4, "#30343f", { x: -4.4, y: 2.2, z: -8.2 }, 10));
    // Bornes de recharge et panneaux PMR
    const ledItems = [], postItems = [], chargerGlow = [], pmrSigns = [];
    zones.forEach((zone) => {
      zone.spots.forEach((s) => {
        const hz = s.z + s.nz * (s.d / 2 - 0.22);
        s.ledIndex = ledItems.length;
        if (zone.name === "ELECTRIC") {
          props.push(box(0.4, 1.35, 0.3, "#f2f4f8", { x: s.x + s.w / 2 - 0.3, y: 0.67, z: hz }));
          props.push(box(0.42, 0.1, 0.32, "#40a02b", { x: s.x + s.w / 2 - 0.3, y: 1.4, z: hz }));
          chargerGlow.push({ x: s.x + s.w / 2 - 0.3, y: 0.95, z: hz - s.nz * 0.16, sx: 0.22, sy: 0.3, sz: 0.03 });
        }
        if (zone.name === "HANDICAPPED") {
          props.push(cyl(0.045, 2.1, "#8d93a0", { x: s.x, y: 1.05, z: hz }, 8));
          pmrSigns.push({ x: s.x, y: 1.85, z: hz - s.nz * 0.06, ry: s.nz === 1 ? Math.PI : 0, sx: 0.62, sy: 0.62 });
        }
        postItems.push({ x: s.x - s.w / 2 + 0.28, y: 0.2, z: hz });
        ledItems.push({ x: s.x - s.w / 2 + 0.28, y: 0.44, z: hz });
      });
    });
    // Lampadaires
    const lampSpots = [];
    const lampAt = (x, z) => {
      props.push(cyl(0.09, 6.2, "#30343f", { x, y: 3.1, z }, 8));
      props.push(box(0.12, 0.12, 4.6, "#30343f", { x, y: 6.15, z }));
      [-2.2, 2.2].forEach((dz) => {
        props.push(box(0.5, 0.14, 0.9, "#30343f", { x, y: 6.08, z: z + dz }));
        lampSpots.push({ x, z: z + dz });
      });
    };
    L.rows.forEach((row, i) => {
      const zc = i % 2 === 1 ? row.z1 + 0.55 : i === 0 ? row.z0 - 0.5 : null;
      if (zc == null && i !== L.rows.length - 1) return;
      const zz = zc != null ? zc : row.side === 1 ? row.z0 - 0.5 : row.z1 + 0.5;
      const n = Math.max(2, Math.round(L.rowLen / 17));
      for (let k = 0; k < n; k++) lampAt(L.R0 + (L.rowLen * (k + 0.5)) / n, zz);
    });
    lampAt(-2.0, -0.4);
    lampAt(LANE + 3.2, -6.5);

    const propsMesh = new THREE.Mesh(merge(props, true), M.props);
    propsMesh.castShadow = true;
    propsMesh.receiveShadow = true;
    group.add(propsMesh);

    // Guérite : vitrage (s'éclaire la nuit)
    const glass = new THREE.Mesh(new THREE.BoxGeometry(2.66, 0.95, 3.06), M.boothGlass);
    glass.position.set(-3.4, 1.55, -3.4);
    group.add(glass);

    // Écrans des bornes, voyants des bornes de recharge
    instanced(group, new THREE.BoxGeometry(1, 1, 1), M.screen, [
      { x: LANE / 2 - 0.37, y: 1.25, z: -3.6, sx: 0.03, sy: 0.4, sz: 0.24 },
      { x: LANE / 2 + 0.37, y: 1.25, z: 3.4, sx: 0.03, sy: 0.4, sz: 0.24 },
    ].concat(chargerGlow));
    instanced(group, new THREE.PlaneGeometry(1, 1), pictoMats.HANDICAPPED, pmrSigns);

    // Marquages : lignes des places, lignes de tête, axe de la voie
    const lines = [];
    L.rows.forEach((row) => {
      let prev = null;
      row.spots.forEach((s) => {
        const zc = s.z;
        if (!prev || prev.zone !== s.zone || Math.abs(prev.x + prev.w / 2 - (s.x - s.w / 2)) > 0.01) {
          lines.push({ x: s.x - s.w / 2, y: 0.012, z: zc, sx: 0.12, sz: s.d });
        }
        lines.push({ x: s.x + s.w / 2, y: 0.012, z: zc, sx: 0.12, sz: s.d });
        lines.push({ x: s.x, y: 0.012, z: s.z + s.nz * (s.d / 2), sx: s.w, sz: 0.12 });
        prev = s;
      });
    });
    for (let z = 2; z < D - 3; z += 4.2) lines.push({ x: LANE / 2, y: 0.012, z, sx: 0.13, sz: 2.2 });
    lines.push({ x: IN_X, y: 0.012, z: -1.1, sx: 3.0, sz: 0.3 });
    lines.push({ x: OUT_X, y: 0.012, z: 1.5, sx: 3.0, sz: 0.3 });
    for (let x = L.cx - 300; x < L.cx + 300; x += 7) lines.push({ x, y: 0.0, z: ROAD_Z, sx: 3, sz: 0.16 });
    instanced(group, flat(1, 1), M.line, lines, "receive");

    // Zones colorées et pictogrammes au sol
    const pads = [];
    const pictos = {};
    zones.forEach((zone) => {
      if (zone.name === "STANDARD") return;
      zone.spots.forEach((s) => {
        pads.push({ x: s.x, y: 0.008, z: s.z, sx: s.w - 0.24, sz: s.d - 0.24, color: zone.kind.color });
        if (PICTOS[zone.name]) {
          const size = Math.min(1.5, s.w - 0.3);
          (pictos[zone.name] = pictos[zone.name] || []).push({
            x: s.x, y: 0.016, z: s.z - s.nz * (s.d / 2 - size / 2 - 0.35), ry: s.nz === 1 ? Math.PI : 0, sx: size, sz: size,
          });
        }
      });
    });
    instanced(group, flat(1, 1), M.pad, pads, "receive");
    Object.keys(pictos).forEach((name) => instanced(group, flat(1, 1), pictoMats[name], pictos[name], "receive"));

    // Flèches de circulation
    const arrows = [];
    for (let z = 4; z < D - 4; z += 12) {
      arrows.push({ x: IN_X, y: 0.014, z, ry: Math.PI, sx: 1.1, sz: 2.6 });
      arrows.push({ x: OUT_X, y: 0.014, z: z + 5, sx: 1.1, sz: 2.6 });
    }
    L.aisles.forEach((az) => {
      for (let x = L.R0 + 9; x < L.R0 + L.rowLen - 4; x += 18) arrows.push({ x, y: 0.014, z: az, ry: -Math.PI / 2, sx: 1.0, sz: 2.4 });
    });
    arrows.push({ x: IN_X, y: 0.01, z: -5.5, ry: Math.PI, sx: 1.1, sz: 2.6 });
    arrows.push({ x: OUT_X, y: 0.01, z: -5.5, sx: 1.1, sz: 2.6 });
    instanced(group, flat(1, 1), arrowMat, arrows, "receive");

    // Capteurs de place (vert : libre, rouge : prise, ambre : mise de côté)
    instanced(group, new THREE.CylinderGeometry(0.05, 0.07, 0.4, 8), M.post, postItems, "cast");
    const leds = instanced(group, new THREE.CylinderGeometry(0.11, 0.11, 0.09, 12), M.led, ledItems.map((it) => Object.assign({ color: "#3ddc6a" }, it)));

    // Lampadaires : ampoules et halos au sol
    instanced(group, new THREE.BoxGeometry(0.4, 0.06, 0.7), M.bulb, lampSpots.map((p) => ({ x: p.x, y: 5.98, z: p.z })));
    instanced(group, flat(15, 15), M.pool, lampSpots.map((p) => ({ x: p.x, y: 0.03, z: p.z })));

    // Arbres et buissons
    const trees = [];
    const ring = (x, z) => trees.push({ x: x + (rnd() - 0.5) * 1.5, z: z + (rnd() - 0.5) * 1.5, s: 0.8 + rnd() * 0.6 });
    for (let z = 4; z < D; z += 8) { ring(L.xMin - 4.5, z); ring(L.xMax + 4.6, z); }
    for (let x = L.xMin; x < L.xMax + 3; x += 8) ring(x, D + 4.8);
    for (let x = LANE + 7; x < L.xMax + 2; x += 9) ring(x, -4.6);
    for (let i = 0; i < 46; i++) ring(L.cx - 210 + rnd() * 420, ROAD_Z - 12 - rnd() * 90);
    for (let i = 0; i < 70; i++) {
      const a = rnd() * Math.PI * 2, r = Math.max(W, D) * 0.75 + 22 + rnd() * 150;
      const x = L.cx + Math.cos(a) * r, z = D / 2 + Math.sin(a) * r;
      if (z < ROAD_Z + 9 && z > ROAD_Z - 9) continue;
      if (x > L.xMin - 6 && x < L.xMax + 6 && z > -9 && z < D + 6) continue;
      ring(x, z);
    }
    instanced(group, new THREE.CylinderGeometry(0.16, 0.24, 1.8, 7), M.trunk,
      trees.map((t) => ({ x: t.x, y: 0.9 * t.s, z: t.z, sy: t.s })), "cast");
    const greens = ["#2f7d3b", "#3f9447", "#4fa64f", "#2c6e3f", "#5aa845", "#39853f"];
    const leaves = [];
    trees.forEach((t) => {
      const color = greens[Math.floor(rnd() * greens.length)];
      leaves.push({ x: t.x, y: 2.6 * t.s, z: t.z, sx: 1.7 * t.s, sy: 1.9 * t.s, sz: 1.7 * t.s, ry: rnd() * 6, color });
      leaves.push({ x: t.x + 0.3, y: 3.9 * t.s, z: t.z - 0.2, sx: 1.15 * t.s, sy: 1.3 * t.s, sz: 1.15 * t.s, ry: rnd() * 6, color });
    });
    L.islands.forEach((it) => {
      leaves.push({ x: it.x, y: 0.55, z: it.z - 1.2, sx: 0.6, sy: 0.6, sz: 0.6, color: "#3f9447" });
      leaves.push({ x: it.x, y: 0.55, z: it.z + 1.2, sx: 0.6, sy: 0.6, sz: 0.6, color: "#2f7d3b" });
      leaves.push({ x: it.x, y: 0.7, z: it.z, sx: 0.75, sy: 0.75, sz: 0.75, color: "#4fa64f" });
    });
    instanced(group, new THREE.IcosahedronGeometry(1, 0), M.foliage, leaves, "cast");

    // Panneaux : portique, totem
    const gantry = signMaterial(1024, (ctx, w, h) => {
      ctx.fillStyle = "#11131c"; ctx.fillRect(0, 0, w, h);
      ctx.font = "800 " + h * 0.56 + "px system-ui, sans-serif"; ctx.textBaseline = "middle"; ctx.textAlign = "center";
      ctx.fillStyle = "#ff5d6c"; ctx.fillText("SORTIE", w * 0.25, h * 0.54);
      ctx.fillStyle = "#4ade80"; ctx.fillText("ENTRÉE", w * 0.75, h * 0.54);
      ctx.fillStyle = "#3a3f52"; ctx.fillRect(w / 2 - 2, h * 0.15, 4, h * 0.7);
    }, 112);
    const back = signMaterial(1024, (ctx, w, h) => {
      ctx.fillStyle = "#11131c"; ctx.fillRect(0, 0, w, h);
      ctx.font = "700 " + h * 0.5 + "px system-ui, sans-serif"; ctx.textBaseline = "middle"; ctx.textAlign = "center";
      ctx.fillStyle = "#cdd6f4"; ctx.fillText("MERCI · À BIENTÔT", w / 2, h * 0.54);
    }, 112);
    const totem = signMaterial(256, (ctx, w, h) => {
      ctx.fillStyle = "#1e66f5"; roundRect(ctx, 0, 0, w, h, 34); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "800 " + h * 0.74 + "px system-ui, sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("P", w / 2, h * 0.55);
    });
    signMats.push(gantry, back, totem);
    textures.push(gantry.map, back.map, totem.map);
    const g1 = new THREE.Mesh(new THREE.PlaneGeometry(LANE + 2.0, 0.72), gantry);
    g1.position.set(LANE / 2, 5.0, -2.41); g1.rotation.y = Math.PI;
    const g2 = new THREE.Mesh(new THREE.PlaneGeometry(LANE + 2.0, 0.72), back);
    g2.position.set(LANE / 2, 5.0, -1.99);
    const t1 = new THREE.Mesh(new THREE.PlaneGeometry(1.9, 1.9), totem);
    t1.position.set(-4.4, 4.6, -8.27); t1.rotation.y = Math.PI;
    const t2 = new THREE.Mesh(new THREE.PlaneGeometry(1.9, 1.9), totem);
    t2.position.set(-4.4, 4.6, -8.13);
    const totemBody = new THREE.Mesh(new THREE.BoxGeometry(2.0, 2.0, 0.12), M.totem);
    totemBody.position.set(-4.4, 4.6, -8.2);
    totemBody.castShadow = true;
    group.add(g1, g2, t1, t2, totemBody);

    // Barrières levantes (bras rayé rouge et blanc)
    function barrier(x, z, towardNegX) {
      const pivot = new THREE.Group();
      pivot.position.set(x, 1.25, z);
      if (towardNegX) pivot.rotation.y = Math.PI;
      const parts = [];
      for (let i = 0; i < 6; i++) parts.push(box(0.5, 0.12, 0.1, i % 2 ? "#f4f5f7" : "#e0283a", { x: 0.45 + i * 0.5 }));
      parts.push(box(0.3, 0.3, 0.2, "#30343f", { x: -0.05 }));
      const arm = new THREE.Mesh(merge(parts, true), M.props);
      arm.castShadow = true;
      pivot.add(arm);
      group.add(pivot);
      return { pivot, angle: 0 };
    }
    const gateIn = barrier(LANE / 2 - 0.2, 0.2, true);
    const gateOut = barrier(LANE / 2 + 0.2, 0.2, false);

    // Flotte : trois maillages instanciés par modèle (peinture, détails, feux)
    const fleet = {};
    const total = zones.reduce((s, z) => s + z.spots.length, 0);
    Object.keys(MODELS).forEach((name) => {
      let capacity = MODELS[name].traffic ? 8 : 0;
      zones.forEach((z) => { if (z.kind.models.indexOf(name) >= 0) capacity += z.spots.length; });
      if (!capacity) return;
      capacity = Math.min(capacity, total + 8);
      const built = MODELS[name].build();
      const meshes = [
        new THREE.InstancedMesh(merge(built.paint, false), M.paint, capacity),
        new THREE.InstancedMesh(merge(built.detail, true), M.detail, capacity),
        new THREE.InstancedMesh(merge(built.lights, true), M.lights, capacity),
      ];
      meshes.forEach((mesh, i) => {
        for (let k = 0; k < capacity; k++) mesh.setMatrixAt(k, HIDDEN);
        mesh.frustumCulled = false;
        mesh.castShadow = i < 2;
        mesh.receiveShadow = i < 2;
        mesh.userData.model = name;
        group.add(mesh);
      });
      for (let k = 0; k < capacity; k++) meshes[0].setColorAt(k, tmpColor.set("#ffffff"));
      const free = [];
      for (let k = capacity - 1; k >= 0; k--) free.push(k);
      fleet[name] = { meshes, free, bySlot: new Array(capacity).fill(null), lean: MODELS[name].lean || 0 };
    });

    // Marqueurs : place mise de côté, survol
    const rings = [];
    for (let i = 0; i < 12; i++) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.8, 28).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: 0xffb020, transparent: true, opacity: 0.9, depthWrite: false, toneMapped: false }));
      ring.visible = false;
      group.add(ring);
      rings.push(ring);
    }
    const hover = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.06, 40).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95, depthWrite: false, toneMapped: false }));
    hover.visible = false;
    hover.renderOrder = 5;
    group.add(hover);

    // Étiquettes
    function tag(text, x, y, z, color, gate) {
      const node = elem("div", "p3d-tag" + (gate ? " gate" : ""));
      if (color) node.style.setProperty("--c", color);
      const name = elem("b", null, text);
      const count = elem("span");
      if (!gate) node.append(elem("i"), name, count); else node.append(name);
      labelLayer.appendChild(node);
      const t = { node, name, count, pos: new THREE.Vector3(x - L.cx, y, z - L.cz) };
      tags.push(t);
      return t;
    }
    zones.forEach((zone, zi) => {
      let sx = 0, sz = 0;
      zone.spots.forEach((s) => { sx += s.x; sz += s.z; });
      zone.cx = sx / zone.spots.length;
      zone.czz = sz / zone.spots.length;
      zone.tag = tag(zone.label, zone.cx, 4.6, zone.czz, zone.kind.color);
      zone.vehicles = [];
      const order = zone.spots.map((_, i) => i);
      const r = mulberry(hash(zone.name) + zi);
      for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(r() * (i + 1));
        const tmp = order[i]; order[i] = order[j]; order[j] = tmp;
      }
      zone.order = order;
    });
    tag("Entrée", IN_X - 2.6, 6.6, -2.2, null, true);
    tag("Sortie", OUT_X + 2.6, 6.6, -2.2, null, true);

    // Ombres et caméra adaptées à la taille du parking
    const reach = Math.hypot(W, D + 24) / 2 + 12;
    const sc = sun.shadow.camera;
    sc.left = -reach; sc.right = reach; sc.top = reach; sc.bottom = -reach;
    sc.near = 10; sc.far = 400;
    sc.updateProjectionMatrix();
    const fit = Math.max(W * 0.7, (D + 14) * 0.96) + 10;
    cam.gRadius = fit;
    cam.max = fit * 2.4;
    cam.bx = W / 2 + 14;
    cam.bz = D / 2 + 22;
    cam.home = fit;

    lot = { L, group, zones, fleet, leds, rings, hover, gateIn, gateOut, textures, tags, seq: 0, pickDirty: true };
    spawnTraffic();
  }

  // --- Véhicules -----------------------------------------------------------------------
  function createVehicle(modelName, colorHex) {
    const f = lot.fleet[modelName];
    if (!f || !f.free.length) return null;
    const slot = f.free.pop();
    const v = { model: modelName, slot, x: 0, z: 0, rot: 0, state: "new", spot: null, zone: null, info: null, id: ++lot.seq };
    f.bySlot[slot] = v;
    f.meshes[0].setColorAt(slot, tmpColor.set(colorHex));
    f.meshes[0].instanceColor.needsUpdate = true;
    return v;
  }
  function place(v, x, z, rot, scale, lean) {
    const f = lot.fleet[v.model];
    dummy.position.set(x, 0, z);
    dummy.rotation.set(0, rot, lean ? f.lean : 0, "YXZ");
    dummy.scale.setScalar(scale == null ? 1 : scale);
    dummy.updateMatrix();
    dummy.rotation.order = "XYZ";
    for (let i = 0; i < 3; i++) {
      f.meshes[i].setMatrixAt(v.slot, dummy.matrix);
      f.meshes[i].instanceMatrix.needsUpdate = true;
    }
    v.x = x; v.z = z; v.rot = rot;
    lot.pickDirty = true;
  }
  function destroyVehicle(v) {
    const f = lot.fleet[v.model];
    for (let i = 0; i < 3; i++) {
      f.meshes[i].setMatrixAt(v.slot, HIDDEN);
      f.meshes[i].instanceMatrix.needsUpdate = true;
    }
    f.bySlot[v.slot] = null;
    f.free.push(v.slot);
    v.state = "gone";
    lot.pickDirty = true;
  }
  function pickModel(zone, seed) {
    const r = mulberry(seed);
    const names = zone.kind.models.filter((n) => lot.fleet[n] && lot.fleet[n].free.length);
    if (!names.length) return null;
    const name = names[Math.floor(r() * names.length)];
    const palette = MODELS[name].paints || PAINTS;
    return { name, color: palette[Math.floor(r() * palette.length)] };
  }

  function addVehicle(zone, animate) {
    const index = zone.order.find((i) => !zone.spots[i].vehicle);
    if (index == null) return;
    const spot = zone.spots[index];
    const choice = pickModel(zone, hash(zone.name) * 31 + index * 977 + (animate ? lot.seq : 0));
    if (!choice) return;
    const v = createVehicle(choice.name, choice.color);
    if (!v) return;
    v.zone = zone;
    v.spot = spot;
    spot.vehicle = v;
    zone.vehicles.push(v);
    if (animate && movers.length < 10) {
      v.state = "entering";
      const path = makePath([[-70, ROAD_NEAR], [IN_X, ROAD_NEAR], [IN_X, spot.aisleZ], [spot.x, spot.aisleZ], [spot.x, spot.z]], 3.2);
      movers.push({ v, path, s: 0, speed: 12, delay: movers.length * 0.9, done: () => park(v) });
      place(v, -70, ROAD_NEAR, Math.PI / 2, 0);
    } else {
      v.state = "parked";
      place(v, spot.x, spot.z, spot.rot, 0, true);
      pops.push({ v, t: -(firstSync ? Math.min(1.6, zone.vehicles.length * 0.05 + lot.zones.indexOf(zone) * 0.12) : 0), from: 0, to: 1 });
    }
  }
  function park(v) {
    v.state = "parked";
    place(v, v.spot.x, v.spot.z, v.spot.rot, 1, true);
    refreshSpots();
  }
  function removeVehicle(v, animate) {
    const zone = v.zone;
    zone.vehicles.splice(zone.vehicles.indexOf(v), 1);
    v.info = null;
    if (v.state === "entering") {
      // Repart avant d'être garé : il disparaît simplement, sa place est rendue.
      const at = movers.findIndex((m) => m.v === v);
      if (at >= 0) movers.splice(at, 1);
      v.spot.vehicle = null;
      destroyVehicle(v);
      return;
    }
    if (animate && v.state === "parked" && movers.length < 10) {
      v.state = "leaving";
      const s = v.spot;
      const backPath = makePath([[s.x, s.z], [s.x, s.aisleZ], [s.x + 4.2, s.aisleZ]], 2.6);
      const outPath = makePath([[s.x + 4.2, s.aisleZ], [OUT_X, s.aisleZ], [OUT_X, ROAD_NEAR], [lot.L.cx + 120, ROAD_NEAR]], 3.2);
      movers.push({
        v, path: backPath, s: 0, speed: 3.6, reverse: true, delay: movers.length * 0.7,
        done: () => {
          s.vehicle = null;
          refreshSpots();
          movers.push({ v, path: outPath, s: 0, speed: 12, delay: 0, done: () => destroyVehicle(v) });
        },
      });
    } else {
      const idx = movers.findIndex((m) => m.v === v);
      if (idx >= 0) movers.splice(idx, 1);
      v.state = "leaving";
      pops.push({ v, t: 0, from: 1, to: 0, done: () => { v.spot.vehicle = null; destroyVehicle(v); refreshSpots(); } });
    }
  }

  function spawnTraffic() {
    const names = Object.keys(MODELS).filter((n) => MODELS[n].traffic && lot.fleet[n]);
    if (!names.length) return;
    for (let i = 0; i < 4; i++) {
      const name = names[i % names.length];
      const v = createVehicle(name, PAINTS[(i * 5 + 3) % PAINTS.length]);
      if (!v) continue;
      v.state = "traffic";
      const far = i % 2 === 1;
      const x0 = lot.L.cx + (far ? 170 : -170), x1 = lot.L.cx + (far ? -170 : 170);
      const path = makePath([[x0, far ? ROAD_FAR : ROAD_NEAR], [x1, far ? ROAD_FAR : ROAD_NEAR]], 1);
      const mover = { v, path, s: 0, speed: 13 + i * 1.5, delay: 2 + i * 6.5, loop: true, cruise: true };
      place(v, x0, far ? ROAD_FAR : ROAD_NEAR, far ? -Math.PI / 2 : Math.PI / 2, 0);
      movers.push(mover);
    }
  }

  function refreshSpots() {
    if (!lot || !lot.leds) return;
    let ring = 0;
    lot.rings.forEach((r) => (r.visible = false));
    lot.zones.forEach((zone) => {
      let toHold = zone.heldN || 0;
      zone.order.forEach((i) => {
        const s = zone.spots[i];
        s.held = false;
        if (!s.vehicle && toHold > 0) {
          s.held = true;
          toHold--;
          if (ring < lot.rings.length) {
            const r = lot.rings[ring++];
            r.position.set(s.x, 0.05, s.z);
            r.visible = true;
          }
        }
      });
      zone.spots.forEach((s) => {
        lot.leds.setColorAt(s.ledIndex, tmpColor.set(s.vehicle ? "#ff3b4e" : s.held ? "#ffb020" : "#3ddc6a"));
      });
    });
    lot.leds.instanceColor.needsUpdate = true;
  }

  // --- Synchronisation avec les données ------------------------------------------------
  function sync() {
    const shown = displayZones(data.zones);
    data.unit = shown.unit;
    const sig = shown.zones.map((z) => z.name + ":" + z.n).join("|");
    const rebuilt = sig !== signature;
    if (rebuilt) {
      signature = sig;
      buildLot(shown.zones);
      firstSync = true;
    } else {
      shown.zones.forEach((z, i) => {
        const zone = lot.zones[i];
        zone.label = z.label; zone.cap = z.cap; zone.taken = z.taken; zone.held = z.held;
        zone.takenN = z.takenN; zone.heldN = z.heldN;
      });
    }
    lot.zones.forEach((zone) => {
      const current = zone.vehicles.length;
      const target = Math.min(zone.takenN, zone.spots.length);
      for (let i = current; i < target; i++) addVehicle(zone, !firstSync);
      if (current > target) {
        const candidates = zone.vehicles.slice().sort((a, b) => (a.info ? 1 : 0) - (b.info ? 1 : 0) || b.id - a.id);
        candidates.slice(0, current - target).forEach((v) => removeVehicle(v, !firstSync));
      }
      zone.tag.name.textContent = zone.label;
      zone.tag.count.textContent = zone.taken + "/" + zone.cap;
    });
    assignPresences();
    refreshSpots();
    renderLegend();
    firstSync = false;
  }

  function assignPresences() {
    if (!lot) return;
    const byZone = {};
    if (data.source === "live") {
      presences.forEach((p) => {
        const name = categoryOfPresence(p);
        (byZone[name] = byZone[name] || []).push(p);
      });
    }
    lot.zones.forEach((zone) => {
      const list = byZone[zone.name] || [];
      const ids = {};
      list.forEach((p) => (ids[p.vehicleId] = p));
      zone.vehicles.forEach((v) => {
        if (v.info && ids[v.info.vehicleId]) { v.info = ids[v.info.vehicleId]; delete ids[v.info.vehicleId]; }
        else v.info = null;
      });
      const waiting = Object.keys(ids).map((k) => ids[k]);
      zone.vehicles.slice().sort((a, b) => b.id - a.id).forEach((v) => {
        if (!v.info && waiting.length) v.info = waiting.shift();
      });
    });
  }

  function renderLegend() {
    const taken = data.zones.reduce((s, z) => s + z.taken, 0);
    const cap = data.zones.reduce((s, z) => s + z.cap, 0);
    legend.replaceChildren();
    const total = elem("div", "p3d-total");
    total.append(elem("b", null, cap ? Math.round((taken / cap) * 100) + " %" : "—"), elem("span", null, taken + " place(s) prise(s) sur " + cap));
    legend.appendChild(total);
    lot.zones.forEach((zone) => {
      const b = elem("button", "p3d-zone");
      b.type = "button";
      b.style.setProperty("--c", zone.kind.color);
      b.title = "Zoomer sur la zone " + zone.label;
      const bar = elem("u");
      const fill = elem("b");
      fill.style.width = (zone.cap ? Math.min(100, (zone.taken / zone.cap) * 100) : 0) + "%";
      bar.appendChild(fill);
      b.append(elem("i"), elem("em", null, zone.label), elem("span", null, zone.taken + "/" + zone.cap + (zone.held ? " · " + zone.held + " en attente" : "")), bar);
      b.addEventListener("click", () => focusZone(zone));
      legend.appendChild(b);
    });
    if (data.unit > 1) legend.appendChild(elem("div", "p3d-note", "Grand parking : 1 place affichée ≈ " + Math.round(data.unit * 10) / 10 + " places."));
    srcDot.parentElement.style.setProperty("--c", data.source === "live" ? "#40a02b" : "#fe640b");
    srcText.textContent = data.source === "live" ? "Temps réel · occupation vue par Parking" : "Démonstration · " + (data.reason || "données simulées");
  }

  // --- Caméra ----------------------------------------------------------------------------
  function focusZone(zone) {
    cam.gx = zone.cx - lot.L.cx;
    cam.gz = zone.czz - lot.L.cz;
    cam.gRadius = clamp(Math.sqrt(zone.spots.length) * 7 + 16, 22, cam.home);
    cam.gPhi = 0.86;
    idle = 0;
  }
  function overview() {
    cam.gx = 0; cam.gz = 2; cam.gRadius = cam.home; cam.gPhi = 0.98; idle = 0;
  }

  const pointers = new Map();
  let dragMoved = 0, pinch = 0, pointer = null, pointerDirty = false, hovered = null;
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointerdown", (e) => {
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* pointeur déjà relâché */ }
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.button === 1 || e.shiftKey });
    dragMoved = 0;
    idle = 0;
    if (pointers.size === 2) {
      const p = Array.from(pointers.values());
      pinch = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y);
    }
    canvas.classList.add("dragging");
    tip.classList.remove("on");
  });
  canvas.addEventListener("pointermove", (e) => {
    const rect = canvas.getBoundingClientRect();
    pointer = { x: e.clientX - rect.left, y: e.clientY - rect.top, w: rect.width, h: rect.height };
    pointerDirty = true;
    const p = pointers.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    dragMoved += Math.abs(dx) + Math.abs(dy);
    idle = 0;
    if (pointers.size >= 2) {
      const pts = Array.from(pointers.values());
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      if (pinch > 0) cam.gRadius = clamp(cam.gRadius * (pinch / Math.max(1, dist)), cam.min, cam.max);
      pinch = dist;
      pan(dx * 0.5, dy * 0.5);
    } else if (p.pan) {
      pan(dx, dy);
    } else {
      cam.gTheta -= dx * 0.0052;
      cam.gPhi = clamp(cam.gPhi - dy * 0.0042, 0.18, 1.46);
    }
  });
  function pan(dx, dy) {
    const k = cam.radius * 0.0017;
    const cs = Math.cos(cam.theta), sn = Math.sin(cam.theta);
    cam.gx = clamp(cam.gx - (cs * dx + sn * dy) * k, -cam.bx, cam.bx);
    cam.gz = clamp(cam.gz - (-sn * dx + cs * dy) * k, -cam.bz, cam.bz);
  }
  function endPointer(e) {
    const had = pointers.delete(e.pointerId);
    if (!pointers.size) canvas.classList.remove("dragging");
    pinch = 0;
    if (had && dragMoved < 6 && e.type === "pointerup") {
      updateHover(true);
      if (hovered && hovered.vehicle && hovered.vehicle.info && opts.onVehicleClick) opts.onVehicleClick(hovered.vehicle.info);
      else if (hovered && hovered.zone) focusZone(hovered.zone);
    }
  }
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);
  canvas.addEventListener("pointerleave", () => { pointer = null; setHover(null); });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    cam.gRadius = clamp(cam.gRadius * Math.exp(e.deltaY * 0.0011), cam.min, cam.max);
    idle = 0;
  }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: [0.12, 0], ArrowRight: [-0.12, 0], ArrowUp: [0, -0.06], ArrowDown: [0, 0.06] }[e.key];
    if (step) { cam.gTheta += step[0]; cam.gPhi = clamp(cam.gPhi + step[1], 0.18, 1.46); idle = 0; e.preventDefault(); }
    if (e.key === "+" || e.key === "=") cam.gRadius = clamp(cam.gRadius * 0.88, cam.min, cam.max);
    if (e.key === "-") cam.gRadius = clamp(cam.gRadius * 1.14, cam.min, cam.max);
    if (e.key === "0" || e.key === "Home") overview();
  });

  // --- Survol : véhicule ou place ----------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const hit = new THREE.Vector3();
  function updateHover(force) {
    if (!lot || !pointer || (pointers.size && !force)) return;
    ndc.set((pointer.x / pointer.w) * 2 - 1, -(pointer.y / pointer.h) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const meshes = [];
    Object.keys(lot.fleet).forEach((name) => {
      const mesh = lot.fleet[name].meshes[0];
      if (lot.pickDirty) mesh.computeBoundingSphere();
      meshes.push(mesh);
    });
    lot.pickDirty = false;
    const hits = raycaster.intersectObjects(meshes, false);
    if (hits.length) {
      const v = lot.fleet[hits[0].object.userData.model].bySlot[hits[0].instanceId];
      if (v && v.state !== "traffic") { setHover({ vehicle: v, zone: v.zone }); return; }
    }
    if (raycaster.ray.intersectPlane(groundPlane, hit)) {
      const x = hit.x + lot.L.cx, z = hit.z + lot.L.cz;
      for (let i = 0; i < lot.zones.length; i++) {
        const zone = lot.zones[i];
        for (let k = 0; k < zone.spots.length; k++) {
          const s = zone.spots[k];
          if (Math.abs(x - s.x) < s.w / 2 && Math.abs(z - s.z) < s.d / 2) { setHover({ spot: s, zone }); return; }
        }
      }
    }
    setHover(null);
  }
  function setHover(h) {
    hovered = h;
    if (!lot) return;
    canvas.classList.toggle("pointing", Boolean(h));
    if (!h) { tip.classList.remove("on"); lot.hover.visible = false; return; }
    const zone = h.zone;
    if (h.vehicle) {
      const v = h.vehicle;
      tipTitle.textContent = MODELS[v.model].label + " · " + zone.label;
      if (v.info) {
        const t = v.info.enteredAt ? new Date(v.info.enteredAt) : null;
        tipSub.textContent = "Véhicule " + String(v.info.vehicleId).slice(0, 8) + "…" +
          (t ? " · entré à " + t.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "") +
          (v.info.reservation ? " · réservation" : "");
        tipMore.textContent = "Cliquer pour ouvrir sa demande d'entrée";
      } else {
        tipSub.textContent = data.source === "live" ? "Place comptée par Parking" : "Véhicule de démonstration";
        tipMore.textContent = v.state === "entering" ? "En train de se garer" : v.state === "leaving" ? "En train de sortir" : "";
      }
      lot.hover.position.set(v.x, 0.06, v.z);
      lot.hover.scale.setScalar(MODELS[v.model].lean ? 1.1 : v.zone.kind.d > 6 ? 3.6 : 2.6);
    } else {
      const s = h.spot;
      tipTitle.textContent = (s.held ? "Place mise de côté" : s.vehicle ? "Place prise" : "Place libre") + " · " + zone.label;
      tipSub.textContent = zone.taken + " prise(s) sur " + zone.cap + (zone.held ? " · " + zone.held + " mise(s) de côté" : "");
      tipMore.textContent = s.held ? "Réservée 30 s pour un véhicule à la barrière" : "Cliquer pour zoomer sur la zone";
      lot.hover.position.set(s.x, 0.06, s.z);
      lot.hover.scale.setScalar(Math.min(s.w, s.d) * 0.42);
    }
    lot.hover.visible = true;
    if (pointer) {
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      const x = clamp(pointer.x + 16, 8, pointer.w - tw - 8);
      const y = pointer.y + 18 + th > pointer.h - 8 ? pointer.y - th - 12 : pointer.y + 18;
      tip.style.transform = "translate(" + Math.round(x) + "px," + Math.round(y) + "px)";
      tip.classList.add("on");
    }
  }

  // --- Jour / nuit -----------------------------------------------------------------------
  const cA = new THREE.Color(), cB = new THREE.Color();
  const mix = (a, b, t) => cA.set(a).lerp(cB.set(b), t);
  let envNight01 = -1;
  function applyNight(n) {
    const d = SKY.day, k = SKY.night;
    const top = new THREE.Color().copy(mix(d.top, k.top, n));
    const hor = new THREE.Color().copy(mix(d.hor, k.hor, n));
    const pos = skyGeo.attributes.position, col = skyGeo.attributes.color;
    for (let i = 0; i < pos.count; i++) {
      const y = Math.max(0, pos.getY(i) / 900);
      cA.copy(hor).lerp(top, Math.pow(y, 0.55));
      col.setXYZ(i, cA.r, cA.g, cA.b);
    }
    col.needsUpdate = true;
    scene.fog.color.copy(hor);
    container.style.background = "#" + hor.getHexString();
    hemi.color.copy(mix(d.hemiSky, k.hemiSky, n));
    hemi.groundColor.copy(mix(d.hemiGround, k.hemiGround, n));
    hemi.intensity = lerp(d.hemiI, k.hemiI, n);
    sun.color.copy(mix(d.sun, k.sun, n));
    sun.intensity = lerp(d.sunI, k.sunI, n);
    sun.position.set(lerp(-70, 60, n), lerp(105, 95, n), lerp(-55, 45, n));
    renderer.toneMappingExposure = lerp(d.exposure, k.exposure, n);
    M.grass.color.copy(mix(d.grass, k.grass, n));
    M.asphalt.color.copy(mix(d.asphalt, k.asphalt, n));
    M.road.color.copy(mix(d.road, k.road, n));
    cloudMat.color.copy(mix(d.cloud, k.cloud, n));
    cloudMat.opacity = lerp(d.cloudO, k.cloudO, n);
    starMat.opacity = n * 0.95;
    M.pool.opacity = n * 0.62;
    M.bulb.color.copy(mix("#6a6f7c", "#ffe2a8", n));
    M.boothGlass.emissiveIntensity = n * 1.3;
    M.lights.color.setScalar(lerp(0.82, 1.25, n));
    M.led.color.setScalar(lerp(0.9, 1.3, n));
    signMats.forEach((m) => (m.emissiveIntensity = lerp(0.18, 0.95, n)));
    const want = n > 0.5 ? 1 : 0;
    if (want !== envNight01) { envNight01 = want; scene.environment = want ? envNight : envDay; }
  }

  // --- Boucle ------------------------------------------------------------------------------
  const pt = { x: 0, z: 0, h: 0 };
  const proj = new THREE.Vector3();
  function step(dt, now) {
    // Démonstration : le parking vit tout seul
    if (data.source === "demo" && !firstSync) {
      demoTimer -= dt;
      if (demoTimer <= 0) {
        demoTimer = 2.4 + Math.random() * 3.2;
        const zone = data.zones[Math.floor(Math.random() * data.zones.length)];
        const rate = zone.taken / zone.cap;
        if (zone.held > 0) { zone.held--; zone.taken = Math.min(zone.cap, zone.taken + 1); }
        else if (Math.random() > rate * 0.85 + 0.08 && zone.taken < zone.cap) { if (Math.random() < 0.4) zone.held++; else zone.taken++; }
        else if (zone.taken > 0) zone.taken--;
        sync();
      }
    }

    // Véhicules en mouvement
    let wantIn = false, wantOut = false;
    for (let i = movers.length - 1; i >= 0; i--) {
      const m = movers[i];
      if (m.delay > 0) { m.delay -= dt; continue; }
      const edge = Math.min(m.s, m.path.total - m.s);
      const ease = m.cruise ? 1 : clamp(edge / 5 + 0.22, 0.22, 1);
      m.s += m.speed * ease * dt;
      pathAt(m.path, m.s, pt);
      const heading = m.reverse ? pt.h + Math.PI : pt.h;
      const rot = m.started ? angleTo(m.v.rot, heading, 1 - Math.exp(-dt * 9)) : heading;
      m.started = true;
      place(m.v, pt.x, pt.z, rot, 1, false);
      if (m.v.state !== "traffic" && pt.z > -11 && pt.z < 5.5) {
        if (Math.abs(pt.x - IN_X) < 1.6) wantIn = true;
        if (Math.abs(pt.x - OUT_X) < 1.6) wantOut = true;
      }
      if (m.s >= m.path.total) {
        if (m.loop) { m.s = 0; m.started = false; m.delay = 3 + Math.random() * 9; place(m.v, m.path.P[0][0], m.path.P[0][1], pt.h, 0); }
        else { movers.splice(i, 1); if (m.done) m.done(); }
      }
    }
    // Apparitions et disparitions sans trajet
    for (let i = pops.length - 1; i >= 0; i--) {
      const p = pops[i];
      p.t += dt / 0.55;
      if (p.t < 0) continue;
      const t = clamp(p.t, 0, 1);
      const back = 1 + 2.2 * Math.pow(t - 1, 3) + 1.2 * Math.pow(t - 1, 2); // léger rebond
      const s = lerp(p.from, p.to, p.to > p.from ? back : t);
      if (p.v.state !== "gone") place(p.v, p.v.spot.x, p.v.spot.z, p.v.spot.rot, Math.max(0, s), true);
      if (p.t >= 1) { pops.splice(i, 1); if (p.done) p.done(); }
    }
    // Barrières
    [[lot.gateIn, wantIn], [lot.gateOut, wantOut]].forEach((g) => {
      g[0].angle = lerp(g[0].angle, g[1] ? 1.42 : 0, 1 - Math.exp(-dt * (g[1] ? 9 : 4)));
      g[0].pivot.rotation.z = g[0].angle;
    });
    // Places mises de côté : anneau qui pulse
    const pulse = 1 + Math.sin(now * 4.2) * 0.14;
    lot.rings.forEach((r) => { if (r.visible) { r.scale.setScalar(pulse); r.material.opacity = 0.55 + Math.sin(now * 4.2) * 0.35; } });
    if (lot.hover.visible) lot.hover.material.opacity = 0.75 + Math.sin(now * 5) * 0.2;
    // Nuages
    clouds.children.forEach((c) => { c.position.x += c.userData.speed * dt; if (c.position.x > 340) c.position.x = -340; });
    // Jour / nuit
    if (Math.abs(night - nightGoal) > 0.001) {
      night = lerp(night, nightGoal, 1 - Math.exp(-dt * 3.2));
      if (Math.abs(night - nightGoal) < 0.004) night = nightGoal;
      applyNight(night);
    }
    // Caméra
    idle += dt;
    if (autoRotate && idle > 3.5 && !pointers.size) cam.gTheta += dt * 0.045;
    const k = 1 - Math.exp(-dt * 6.5);
    cam.theta = lerp(cam.theta, cam.gTheta, k);
    cam.phi = lerp(cam.phi, cam.gPhi, k);
    cam.radius = lerp(cam.radius, cam.gRadius, k * 0.8);
    cam.tx = lerp(cam.tx, cam.gx, k);
    cam.tz = lerp(cam.tz, cam.gz, k);
    const sp = Math.sin(cam.phi);
    camera.position.set(cam.tx + cam.radius * sp * Math.sin(cam.theta), cam.radius * Math.cos(cam.phi) + 1.5, cam.tz + cam.radius * sp * Math.cos(cam.theta));
    camera.lookAt(cam.tx, 1.5, cam.tz);
    sun.target.position.set(0, 0, 0);
    if (pointerDirty) { pointerDirty = false; updateHover(false); }
  }

  function updateTags(w, h) {
    lot.tags.forEach((t) => {
      proj.copy(t.pos).project(camera);
      const visible = proj.z < 1 && proj.x > -1.15 && proj.x < 1.15 && proj.y > -1.15 && proj.y < 1.15;
      t.node.style.opacity = visible ? "1" : "0";
      if (visible) {
        t.node.style.transform = "translate(-50%, -100%) translate(" + ((proj.x * 0.5 + 0.5) * w).toFixed(1) + "px," + ((-proj.y * 0.5 + 0.5) * h).toFixed(1) + "px)";
      }
    });
  }

  let width = 0, height = 0;
  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h || (w === width && h === height)) return;
    width = w; height = h;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.fov = w < h ? 54 : 40;
    // Le parking est décalé pour ne pas passer sous la légende.
    const narrow = w < 640;
    camera.setViewOffset(w, h, narrow ? 0 : -w * 0.07, narrow ? h * 0.09 : h * 0.04, w, h);
    camera.updateProjectionMatrix();
  }
  const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
  if (observer) observer.observe(container);

  function frame(time) {
    raf = requestAnimationFrame(frame);
    const now = time / 1000;
    const dt = Math.min(0.05, Math.max(0.001, now - last));
    last = now;
    resize();
    if (!lot || !width) return;
    step(dt, now);
    renderer.render(scene, camera);
    updateTags(width, height);
  }

  // --- Boutons ------------------------------------------------------------------------------
  toolButton("Vue d'ensemble", "Revenir à la vue complète du parking", overview);
  const rotateBtn = toolButton("Rotation", "Faire tourner lentement la caméra", () => {
    autoRotate = !autoRotate;
    idle = 10;
    rotateBtn.setAttribute("aria-pressed", String(autoRotate));
  }, autoRotate);
  const nightBtn = toolButton("Nuit", "Passer du jour à la nuit", () => api.setTheme(nightGoal > 0.5 ? "latte" : "mocha"), nightGoal > 0.5);
  toolButton("Plein écran", "Afficher le plan en plein écran", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (container.requestFullscreen) container.requestFullscreen().catch(() => {});
  });

  // --- API publique ----------------------------------------------------------------------------
  const api = {
    /* update({ overview, presences, reason }) : occupation de Parking (ou rien → démonstration). */
    update(input) {
      input = input || {};
      const zones = liveZones(input.overview);
      presences = Array.isArray(input.presences) ? input.presences : [];
      if (zones) {
        data = { source: "live", reason: "", zones, unit: 1 };
      } else if (data.source !== "demo") {
        data = { source: "demo", reason: input.reason || "", zones: DEMO_ZONES.map((z) => Object.assign({}, z)), unit: 1 };
      } else {
        data.reason = input.reason || data.reason;
      }
      sync();
    },
    setTheme(theme) {
      nightGoal = theme === "mocha" ? 1 : 0;
      nightBtn.setAttribute("aria-pressed", String(nightGoal > 0.5));
      nightBtn.textContent = nightGoal > 0.5 ? "Jour" : "Nuit";
    },
    setActive(on) {
      if (on === active) return;
      active = on;
      cancelAnimationFrame(raf);
      if (on) { last = performance.now() / 1000; raf = requestAnimationFrame(frame); }
    },
    focus(name) {
      const zone = lot && lot.zones.find((z) => z.name === name);
      if (zone) focusZone(zone);
    },
    /* Place la caméra : point visé (repère du parking, mètres), distance, angles. */
    view(v) {
      if (!lot) return;
      if (v.x != null) cam.gx = v.x - lot.L.cx;
      if (v.z != null) cam.gz = v.z - lot.L.cz;
      if (v.radius != null) cam.gRadius = clamp(v.radius, cam.min, cam.max);
      if (v.theta != null) cam.gTheta = v.theta;
      if (v.phi != null) cam.gPhi = clamp(v.phi, 0.18, 1.46);
      idle = 0;
    },
    /* État lisible par les tests et le débogage (aucune donnée personnelle). */
    snapshot() {
      return {
        source: data.source,
        zones: lot ? lot.zones.map((z) => ({ name: z.name, spots: z.spots.length, vehicles: z.vehicles.length, held: z.spots.filter((s) => s.held).length })) : [],
        moving: movers.filter((m) => m.v.state !== "traffic").length,
        night: nightGoal,
      };
    },
    dispose() {
      api.setActive(false);
      if (observer) observer.disconnect();
      if (lot) disposeTree(lot.group);
      pmrem.dispose();
      renderer.dispose();
      container.replaceChildren();
    },
  };

  applyNight(night);
  api.setTheme(night > 0.5 ? "mocha" : "latte");
  sync();
  // Arrivée : la caméra descend vers le parking.
  if (!reduceMotion) { cam.radius = cam.gRadius * 2.1; cam.phi = 0.42; cam.theta = cam.gTheta - 0.9; }
  else { cam.radius = cam.gRadius; }
  return api;
}
