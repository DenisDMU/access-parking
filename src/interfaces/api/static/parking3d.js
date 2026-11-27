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
import { GAMES as MINI, startGame } from "./promenade-jeux.js?v=4.29.0";

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
    top: "#3f9df0", hor: "#cfe9ff", grass: "#84d86f", sun: "#fff2dc", sunI: 3.0,
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
/* Monde courbé, comme une petite planète : en promenade, chaque point descend
   d'autant plus qu'il est loin de la caméra. C'est un effet de dessin (dans le
   nuanceur) : les positions réelles, les collisions et le plan vu de haut
   restent à plat. Le ciel n'est pas courbé ; les ombres sont calculées à plat. */
const BEND = { value: 0 };
const BEND_MAX = 0.0016;
if (!THREE.Material.prototype.p3dBend) {
  THREE.Material.prototype.p3dBend = true;
  const curve = "mvPosition = modelMatrix * mvPosition;\n\tvec2 bendOff = mvPosition.xz - cameraPosition.xz;\n\tmvPosition.y -= uBend * dot( bendOff, bendOff );\n\tmvPosition = viewMatrix * mvPosition;";
  THREE.Material.prototype.onBeforeCompile = function (shader) {
    if (this.isMeshDepthMaterial || this.isMeshDistanceMaterial || (this.userData && this.userData.noBend)) return;
    shader.uniforms.uBend = BEND;
    shader.vertexShader = "uniform float uBend;\n" + shader.vertexShader
      .replace("#include <project_vertex>", THREE.ShaderChunk.project_vertex.replace("mvPosition = modelViewMatrix * mvPosition;", curve))
      .replace("vec4 mvPosition = modelViewMatrix * vec4( 0.0, 0.0, 0.0, 1.0 );", "vec4 mvPosition = vec4( 0.0, 0.0, 0.0, 1.0 );\n\t" + curve);
  };
  THREE.Material.prototype.customProgramCacheKey = function () {
    return this.isMeshDepthMaterial || this.isMeshDistanceMaterial || (this.userData && this.userData.noBend) ? "plat" : "courbe";
  };
}
// Les grandes surfaces sont découpées en carreaux : sans cela, elles ne pourraient pas se courber.
const seg = (v) => (v > 8 ? Math.ceil(v / 5) : 1);
const box = (w, h, d, color, t) => part(new THREE.BoxGeometry(w, h, d, seg(w), 1, seg(d)), color, t);
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

function wheels(detail, r, w, halfTrack, zs, spots) {
  zs.forEach((z) =>
    [-1, 1].forEach((sx) => {
      if (spots) spots.push({ x: sx * (halfTrack + 0.07), y: r, z, r, w, sx });
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
  const spots = [];
  wheels(detail, spec.r, 0.25, W / 2 - 0.11, spec.axles, spots);
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
  /* Points d'ancrage du tuning : capot, toit, coffre (segments [z, y] à la surface),
     portière (y, z, taille de l'autocollant), aileron et fanion à l'arrière. */
  const up = (seg) => seg && seg.map((pt) => [pt[0], pt[1] + 0.066]);
  const hoodTop = spec.hood ? spec.hood[1][1] : spec.body[0][1] + 0.55;
  const fit = {
    W, len: front - back, side: W / 2 + 0.02, hood: up(spec.hood), trunk: up(spec.trunk),
    roof: [[spec.roof[1][0], spec.roof[1][1] + 0.038], [spec.roof[2][0], spec.roof[2][1] + 0.038]],
    door: [(spec.body[0][1] + hoodTop) / 2 + 0.08, (spec.axles[0] + spec.axles[1]) / 2 - 0.12, (hoodTop - spec.body[0][1]) * 0.66],
    wing: spec.wing, mast: spec.wing ? [W / 2 - 0.16, spec.wing[1], spec.wing[0] + 0.12] : null,
  };
  return { paint, detail, lights, spots, fit };
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
  const spots = [];
  wheels(detail, 0.4, 0.28, W / 2 - 0.12, camper ? [2.1, -2.0] : [2.0, -1.9], spots);
  const fit = {
    W, len: front - back, side: W / 2 + 0.012, hood: null, trunk: null, wing: null,
    roof: [[camper ? 2.85 : 2.0, H + 0.075], [back + 0.25, H + 0.075]],
    door: camper ? [2.12, -1.02, 0.86] : [1.75, -0.6, 0.9], mast: [W / 2 - 0.18, H + 0.07, back + 0.4],
  };
  return { paint, detail, lights, spots, fit };
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
  const spots = [0.72, -0.72].map((z) => ({ x: 0, y: 0.31, z, r: 0.31, w: 0.13, sx: 0 }));
  const fit = { W: 0.5, len: 2.1, side: 0.186, hood: null, trunk: null, roof: null, wing: null, door: [0.89, 0.14, 0.17], mast: [0, 0.98, -0.86] };
  return { paint, detail, lights, spots, fit };
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
  const spots = [0.62, -0.62].map((z) => ({ x: 0, y: 0.22, z, r: 0.22, w: 0.13, sx: 0 }));
  const fit = { W: 0.5, len: 1.9, side: 0.2, hood: null, trunk: null, roof: null, wing: null, door: [0.52, -0.42, 0.28], mast: [0, 1.1, -0.98] };
  return { paint, detail, lights, spots, fit };
}

const MODELS = {
  hatch: {
    label: "Citadine", traffic: true,
    build: () => car({
      W: 1.75, r: 0.31, axles: [1.22, -1.22], ly: 0.66, my: 0.98, mz: 0.9,
      hood: [[1.85, 0.8], [0.95, 0.92]], wing: [-1.4, 1.5],
      body: [[-1.9, 0.32], [1.95, 0.32], [2.0, 0.6], [1.85, 0.8], [0.95, 0.92], [-1.85, 0.95], [-1.95, 0.6]],
      glass: [[1.0, 0.88], [0.45, 1.4], [-1.45, 1.4], [-1.85, 0.9]],
      roof: [[0.48, 1.37], [0.4, 1.46], [-1.42, 1.46], [-1.5, 1.37]],
    }),
  },
  sedan: {
    label: "Berline", traffic: true,
    build: () => car({
      W: 1.8, r: 0.33, axles: [1.38, -1.38], ly: 0.66, my: 0.96, mz: 0.85,
      hood: [[2.1, 0.78], [0.9, 0.9]], trunk: [[-1.5, 0.92], [-2.2, 0.86]], wing: [-2.0, 0.96],
      body: [[-2.2, 0.32], [2.2, 0.32], [2.25, 0.6], [2.1, 0.78], [0.9, 0.9], [-1.5, 0.92], [-2.2, 0.86], [-2.25, 0.58]],
      glass: [[0.95, 0.86], [0.3, 1.36], [-0.95, 1.36], [-1.6, 0.88]],
      roof: [[0.33, 1.33], [0.24, 1.42], [-0.9, 1.42], [-1.0, 1.33]],
    }),
  },
  suv: {
    label: "SUV", traffic: true,
    build: () => car({
      W: 1.92, r: 0.39, axles: [1.45, -1.45], ly: 0.84, my: 1.2, mz: 0.95,
      hood: [[2.2, 1.0], [1.0, 1.1]], wing: [-1.8, 1.77],
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
      hood: [[2.1, 0.74], [1.2, 0.86]], trunk: [[-1.7, 0.95], [-2.25, 0.9]], wing: [-2.05, 0.98],
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

// Emprise au sol de chaque modèle garé (demi-largeur, demi-longueur) : le
// promeneur contourne les véhicules.
const FOOT = {
  hatch: [0.95, 2.0], sedan: [0.97, 2.25], suv: [1.03, 2.35], ev: [1.0, 2.3],
  van: [1.12, 3.1], camper: [1.2, 3.35], moto: [0.36, 0.95], scooter: [0.36, 0.85],
};
const WALK_KEYS = {
  KeyW: 1, KeyA: 1, KeyS: 1, KeyD: 1, ArrowUp: 1, ArrowDown: 1, ArrowLeft: 1, ArrowRight: 1,
  ShiftLeft: 1, ShiftRight: 1, Space: 1,
};
// Véhicules en libre-service, à conduire (garés près de l'entrée, hors du parking :
// ils ne comptent pas dans l'occupation). Vitesses en m/s.
const RENTALS = [
  { model: "camper", name: "Camping-car", label: "le camping-car", color: "#f4f5f7", x: -23.5, max: 18, acc: 5.5, r: 1.3, half: 2.3, cam: 13.5 },
  { model: "sedan", name: "Berline", label: "la berline", color: "#d92b3a", x: -19.5, max: 28, acc: 10.5, r: 1.02, half: 1.45, cam: 9.5 },
  { model: "scooter", name: "Scooter", label: "le scooter", color: "#f2b01e", x: -15.5, max: 15, acc: 7.5, r: 0.45, half: 0.45, cam: 6.5 },
  { model: "suv", name: "4x4", label: "le 4x4", color: "#fe640b", x: -27.5, max: 24, acc: 8.5, r: 1.08, half: 1.55, cam: 10.5 },
  { model: "ev", name: "Citadine électrique", label: "la citadine électrique", color: "#40a02b", x: -31.5, max: 26, acc: 12, r: 1.0, half: 1.45, cam: 9.5 },
  { model: "moto", name: "Moto", label: "la moto", color: "#22252e", x: -35.5, max: 34, acc: 13, r: 0.5, half: 0.6, cam: 7 },
];
const RENTAL_Z = -5.4;
const BIKES = ["scooter", "moto"]; // on s'assoit dessus, à la vue de tous
/* KingPar Tuning : l'atelier où l'on personnalise son véhicule. Tout est offert,
   comme dans les boutiques ; les réglages restent sur l'appareil, un par véhicule. */
const TUNE_KEY = "access.plan3d.garage";
const CAR_PAINTS = ["#d92b3a", "#fe640b", "#f2b01e", "#ffd60a", "#40a02b", "#17c3b2", "#1e66f5", "#27408b", "#8839ef", "#ff5d8f", "#f6a5c0", "#f4f5f7", "#8b909c", "#22252e"];
const FINISHES = [["brillant", "Brillante"], ["mat", "Mate"], ["metal", "Métallisée"], ["nacre", "Nacrée"]];
const RIMS = [["serie", "De série"], ["etoile", "Étoile"], ["rayons", "À rayons"], ["plein", "Pleines"]];
const RIM_COLORS = [HUB, "#22252e", "#f4f5f7", "#d4af37", "#1e66f5", "#d92b3a", "#ff5d8f", "#40a02b"];
const TYRES = [["route", "Route"], ["blanc", "Flancs blancs"], ["sport", "Sport, liseré rouge"], ["cross", "Tout-terrain"]];
const STICKERS = [["none", "Aucun"], ["kingpar", "Couronne KingPar"], ["numero", "Numéro 7"], ["flammes", "Flamme"], ["eclair", "Éclair"], ["coeur", "Cœur"], ["patte", "Patte de Ticket"], ["etoile", "Étoile"], ["damier", "Damier"]];
const STRIPES = [["none", "Aucune"], ["double", "Double bande"], ["simple", "Bande centrale"]];
const STRIPE_COLORS = ["#f4f5f7", "#22252e", "#ffd60a", "#d92b3a", "#1e66f5", "#ff5d8f"];
const TINTS = { serie: ["De série", GLASS], clair: ["Claires", "#7f9bb3"], bleu: ["Bleutées", "#1d4f9c"], rose: ["Rosées", "#b0527a"], or: ["Dorées", "#a8842c"], noir: ["Noires", "#07080a"] };
const ADDONS = [["none", "Aucun"], ["aileron", "Aileron"], ["galerie", "Galerie et bagages"], ["fanion", "Fanion KingPar"]];
const NEONS = { none: ["Éteint", null], bleu: ["Bleu", "#3b82ff"], rose: ["Rose", "#ff4fa3"], vert: ["Vert", "#3ddc6a"], or: ["Or", "#ffc21a"], violet: ["Violet", "#a25bff"], blanc: ["Blanc", "#ffffff"] };
const HORNS = [["tut", "Tut tut"], ["pouet", "Pouêt"], ["melodie", "Mélodie"], ["coin", "Coin coin"]];
const TUNE_DEFAULT = { finish: "brillant", rims: "serie", rimc: HUB, tyres: "route", sticker: "none", stripes: "none", stripec: STRIPE_COLORS[0], tint: "serie", addon: "none", neon: "none", horn: "tut" };
// Ce qui se monte sur chaque véhicule : ni bandes ni vitres sur un deux-roues, pas d'aileron sur le camping-car.
const tuneFits = (model, field, value) => {
  const bike = BIKES.includes(model);
  if (field === "stripes" || field === "tint") return !bike || value === TUNE_DEFAULT[field];
  if (field === "addon") return value === "none" || value === "fanion" || (!bike && (value !== "aileron" || model !== "camper"));
  return true;
};
/* Un réglage de tuning, relu avec prudence : il vient du stockage du navigateur ou
   d'un autre promeneur. Seules les valeurs connues sont reprises. */
function cleanTune(raw, model, color) {
  const t = Object.assign({ paint: color }, TUNE_DEFAULT);
  if (!raw || typeof raw !== "object") return t;
  const hex = (v) => typeof v === "string" && /^#[0-9a-f]{6}$/.test(v);
  const word = (list, v) => list.some((it) => it[0] === v);
  if (hex(raw.paint)) t.paint = raw.paint;
  if (hex(raw.rimc)) t.rimc = raw.rimc;
  if (hex(raw.stripec)) t.stripec = raw.stripec;
  if (word(FINISHES, raw.finish)) t.finish = raw.finish;
  if (word(RIMS, raw.rims)) t.rims = raw.rims;
  if (word(TYRES, raw.tyres)) t.tyres = raw.tyres;
  if (word(STICKERS, raw.sticker)) t.sticker = raw.sticker;
  if (word(STRIPES, raw.stripes) && tuneFits(model, "stripes", raw.stripes)) t.stripes = raw.stripes;
  if (Object.prototype.hasOwnProperty.call(TINTS, raw.tint) && tuneFits(model, "tint", raw.tint)) t.tint = raw.tint;
  if (word(ADDONS, raw.addon) && tuneFits(model, "addon", raw.addon)) t.addon = raw.addon;
  if (Object.prototype.hasOwnProperty.call(NEONS, raw.neon)) t.neon = raw.neon;
  if (word(HORNS, raw.horn)) t.horn = raw.horn;
  return t;
}
function loadGarage() {
  let raw = {};
  try { raw = JSON.parse(window.localStorage.getItem(TUNE_KEY) || "{}") || {}; } catch (err) { /* stockage indisponible : véhicules d'origine */ }
  const garage = {};
  RENTALS.forEach((def) => { garage[def.model] = cleanTune(raw[def.model], def.model, def.color); });
  return garage;
}
// La ville, à l'est du parking, le long de la route (mètres).
const CITY_GAP = 70, CITY_PITCH = 48, CITY_COLS = 4, CITY_AVENUE = 44;
// Le village du parking : « la bonne place », comme celle qu'on y trouve.
const CITY_NAME = "Bonneplace";
const BRAND = "#1e66f5"; // le bleu de KingPar, la marque du parking
const MASCOT = "Ticket"; // le chihuahua, mascotte du parking
// Échoppes de la rue : trois servent vraiment (tenues, coiffure, compagnon), tout y est offert.
const SHOPS = ["BISTROT DU PARVIS", "BOUTIQUE KINGPAR", "CAFÉ LA BARRIÈRE", "ANIMALERIE DU COPILOTE", "COIFFURE LE CRÉNEAU", "PIZZERIA DU ROND-POINT", "GLACES DU FEU VERT", "SPA DU POINT MORT"];
const SHOP_SAYS = {
  "BISTROT DU PARVIS": "Le plat du jour, bien garni !", "CAFÉ LA BARRIÈRE": "Un café, et la barrière se lève.",
  "PIZZERIA DU ROND-POINT": "Une pizza bien ronde, comme le rond-point.",
  "GLACES DU FEU VERT": "Pistache-menthe : feu vert pour la gourmandise !", "SPA DU POINT MORT": "Aaah… au point mort, on se détend.",
};
const SHOP_LABELS = {
  "BISTROT DU PARVIS": "Commander le plat du jour", "CAFÉ LA BARRIÈRE": "Prendre un café", "PIZZERIA DU ROND-POINT": "Goûter la pizza",
  "GLACES DU FEU VERT": "Prendre une glace", "SPA DU POINT MORT": "Voir la course de canards du spa",
  "BOUTIQUE KINGPAR": "Changer de tenue (tout est offert)", "COIFFURE LE CRÉNEAU": "Passer chez le coiffeur (offert)",
  "ANIMALERIE DU COPILOTE": "Choisir un compagnon à l'animalerie",
};
const SHOP_PANELS = { "BOUTIQUE KINGPAR": "tenue", "COIFFURE LE CRÉNEAU": "coiffure", "ANIMALERIE DU COPILOTE": "compagnon" };
const DRINKS = ["Clonk ! Une limonade bien fraîche.", "Clonk ! Un café en canette.", "Clonk ! Un jus de pomme."];
const TOPS = ["#1e66f5", "#1e9e8f", "#d92b3a", "#f2b01e", "#8839ef", "#f4f5f7", "#22252e", "#f6a5c0", "#3d8a3a", "#b388ff", "#fe640b", "#17c3b2", "#ff5d8f"];
const PANTS = ["#27408b", "#22252e", "#6b4a35", "#8b909c", "#3d8a3a", "#b23a48", "#8839ef", "#f4f5f7", "#f2b01e", "#17c3b2"];
const HAIRS = ["#3b2a20", "#15161a", "#e3c26a", "#c2552d", "#b9bec9", "#f6a5c0", "#3f7fd9", "#3fa34d", "#9b5de5", "#f4f5f7", "#ff7b54"];
const HATS = [["none", "Aucun"], ["cap", "Casquette KingPar"], ["straw", "Chapeau de paille"], ["bonnet", "Bonnet"], ["beret", "Béret"], ["couronne", "Couronne KingPar"]];
const CUTS = [["short", "Courte"], ["bob", "Carré"], ["long", "Longue"], ["tail", "Queue-de-cheval"], ["twin", "Couettes"], ["bun", "Chignon"], ["afro", "Afro"], ["mohawk", "Crête"], ["bol", "Au bol"], ["banane", "Banane"], ["tresses", "Tresses"], ["piques", "En piques"], ["boucles", "Bouclée"]];
const OUTFITS = [["tshirt", "T-shirt"], ["pull", "Pull"], ["chemise", "Chemise"], ["veste", "Veste"], ["hoodie", "Sweat à capuche"], ["salopette", "Salopette"], ["robe", "Robe"], ["maillot", "Maillot KingPar"]];
const BOTTOMS = [["pants", "Pantalon"], ["short", "Short"], ["jupe", "Jupe"]];
const EXTRAS = [["none", "Aucun"], ["lunettes", "Lunettes"], ["soleil", "Lunettes de soleil"], ["echarpe", "Écharpe"]];
const EYES = [["ronds", "Ronds"], ["manga", "Manga"], ["malins", "Malins"], ["etoiles", "Étoilés"]];
const BALLOONS = ["#1e66f5", "#ffd60a", "#d92b3a", "#f6a5c0", "#40a02b", "#f4f5f7", "#8839ef"];
const CROWN_WINS = 9; // la couronne KingPar se mérite
const SKINS = ["#f6d7bd", "#f0c9a4", "#dba97c", "#b97f55", "#8a5a3c", "#5c3b28"];
/* Compagnons. `ears` : forme (cone, long, round, flop, none), rayon, hauteur,
   inclinaison, écart. `tail` : longueur, angle, rayon. */
const PETS = {
  chihuahua: { name: "Chihuahua", fur: "#d9a066", ear: "#b07a45", muzzle: "#f0d9b5", scale: 1.4, ears: ["cone", 0.07, 0.2, 0.5, 0.085], tail: [0.13, -0.6, 0.018], collar: "#e0283a", barks: ["Ouaf !", "Wif !", "Ouaf ouaf !", "Grrr… ouaf !", "Waf !"] },
  chat: { name: "Chat", fur: "#9aa0a6", ear: "#7d848c", muzzle: "#f4f5f7", scale: 1.4, ears: ["cone", 0.045, 0.09, 0.25, 0.065], tail: [0.28, -0.9, 0.02], eye: "#3fa34d", wag: 0.25, barks: ["Miaou !", "Mrrr…", "Miaou ?"] },
  shiba: { name: "Shiba", fur: "#d98a3d", ear: "#b86f2c", muzzle: "#fdf6e3", scale: 1.9, ears: ["cone", 0.045, 0.1, 0.15, 0.065], tail: [0.12, 0.6, 0.035], chest: true, collar: BRAND, barks: ["Wouf !", "Ouaf ouaf !", "Wouf wouf !"] },
  lapin: { name: "Lapin", fur: "#f4f5f7", ear: "#f6c1cf", muzzle: "#f4f5f7", scale: 1.5, ears: ["long", 0.028, 0.2, 0.1, 0.045], tail: [0.01, 0, 0.045], hop: true, wag: 0, barks: ["Pouic !", "Snif snif.", "…"] },
  renard: { name: "Renard", fur: "#e2711d", ear: "#22252e", muzzle: "#fdf6e3", scale: 1.65, ears: ["cone", 0.05, 0.13, 0.2, 0.07], tail: [0.26, -0.3, 0.055], tip: "#fdf6e3", chest: true, wag: 0.3, barks: ["Yip !", "Glap glap !", "Yip yip !"] },
  cochon: { name: "Cochon", fur: "#f7a8b8", ear: "#e88aa0", muzzle: "#f7a8b8", snout: "#e0788f", scale: 1.6, ears: ["flop", 0.045, 0, 0, 0.08], tail: [0.05, -0.4, 0.014], wag: 0.9, barks: ["Groin !", "Gruik gruik !", "Rrrron…"] },
  panda: { name: "Panda", fur: "#f4f5f7", ear: "#22252e", muzzle: "#f4f5f7", patch: "#22252e", legs: "#22252e", scale: 1.8, ears: ["round", 0.04, 0, 0, 0.075], tail: [0.01, 0, 0.035], wag: 0, barks: ["Crunch.", "Mmmh…", "On mange quand ?"] },
  mouton: { name: "Mouton", fur: "#3b3b3b", wool: "#fdf6e3", ear: "#3b3b3b", muzzle: "#3b3b3b", scale: 1.7, ears: ["flop", 0.035, 0, 0, 0.095], tail: [0.01, 0, 0.04], wag: 0, barks: ["Bêêê !", "Mêêê.", "Bê ?"] },
  tortue: { name: "Tortue", une: true, fur: "#8fbf6a", shell: "#4f7942", ear: "#8fbf6a", muzzle: "#8fbf6a", scale: 1.35, ears: ["none"], tail: [0.04, -1.2, 0.015], wag: 0.1, barks: ["…", "Doucement.", "J'arrive !"] },
  canard: { name: "Canard", fur: "#ffd60a", ear: "#f2b01e", muzzle: "#ffd60a", beak: "#fe640b", legs: "#fe640b", scale: 1.5, ears: ["none"], tail: [0.05, -0.9, 0.03], wag: 0.8, barks: ["Coin !", "Coin coin !", "Couac ?"] },
};
// Stands de la fête : enseigne, invite, répliques.
const STALLS = [
  ["CRÊPES", "Commander une crêpe", ["Une crêpe au sucre, toute chaude !"], "#8c2f39"],
  ["FRITES", "Prendre un cornet de frites", ["Un cornet de frites bien dorées."], "#b5651d"],
  ["BARBE À PAPA", "Prendre une barbe à papa", ["Une barbe à papa plus grosse que la tête !"], "#c2558a"],
  ["PÊCHE AUX CANARDS", "Jouer à la pêche aux canards", ["Raté… le canard a filé !", "Attrapé ! Le canard numéro 7.", "Presque ! Encore un essai ?"], "#1f6f5c"],
];
// Tickets chance : les prédictions du belvédère (un jeu, comme le carnet).
const LUCK = [
  ["Grande chance", "Une place vous attend tout près de l'entrée."],
  ["Grande chance", "Aujourd'hui, toutes les barrières se lèvent devant vous."],
  ["Chance", "Feu vert sur toute la route du retour."],
  ["Chance", "Votre compagnon aura droit à une friandise."],
  ["Petite chance", "Pensez à réserver : la place sera la vôtre."],
  ["Chance à venir", "L'heure creuse cache toujours un créneau libre."],
  ["Chance à venir", "Les arbres refleuriront ; revenez les voir."],
];
// Carnet de tampons : des choses à faire, du parking au village.
const STAMPS = [
  ["parking", "Visiter une allée du parking", "Entrez par le portique et marchez entre les places."],
  ["resa", "Consulter la borne de réservation", "Sur le parvis, à gauche de l'entrée."],
  ["agent", "Saluer l'agent du parking", "Il fait sa ronde en gilet jaune."],
  ["volant", "Prendre le volant", "Six véhicules attendent en libre-service."],
  ["arche", "Passer sous la grande arche", "Suivez la route vers l'est."],
  ["mascotte", "Saluer " + MASCOT + ", la mascotte", "Sa statue dorée garde l'entrée du village."],
  ["boisson", "Prendre une boisson", "Un distributeur, dans la rue du village."],
  ["cloche", "Sonner la cloche du belvédère", "En haut de l'escalier aux cinq arches."],
  ["pont", "Traverser la passerelle bleue", "Dans le jardin de la tour, au-dessus de l'étang."],
  ["look", "Changer de tenue ou de coiffure", "Boutique KingPar ou coiffeur : tout est offert."],
  ["ami", "Choisir un compagnon", "À l'animalerie du village."],
  ["fete", "Frapper la grosse caisse de la fête", "Sur la place aux guirlandes, derrière la rue."],
  ["chance", "Tirer un ticket chance", "Au belvédère : une prédiction sur ticket."],
  ["station", "S'arrêter à la Station KingPar", "Sur la route du village : jouez au plein pile."],
  ["ferme", "Visiter la Kingfarm", "Au sud du village : potager, verger et mine à minerais."],
  ["tuning", "Passer au KingPar Tuning", "En face de la station : personnalisez un véhicule, tout est offert."],
];
// Tenue, coiffure, compagnon et carnet : gardés sur l'appareil, rien n'est envoyé.
const LOOK_KEY = "access.plan3d.look";
const CARNET_KEY = "access.plan3d.carnet";
const LOOK_DEFAULT = { top: TOPS[0], pants: PANTS[0], hair: HAIRS[0], skin: SKINS[1], hat: "none", cut: "short", pack: true, pet: "chihuahua", outfit: "tshirt", bottom: "pants", extra: "none", balloon: "none", eyes: "ronds" };
function loadLook() {
  const look = Object.assign({}, LOOK_DEFAULT);
  try {
    const raw = JSON.parse(window.localStorage.getItem(LOOK_KEY) || "{}") || {};
    // On ne reprend que des valeurs connues : le stockage n'est pas une source sûre.
    if (TOPS.includes(raw.top)) look.top = raw.top;
    if (PANTS.includes(raw.pants)) look.pants = raw.pants;
    if (HAIRS.includes(raw.hair)) look.hair = raw.hair;
    if (SKINS.includes(raw.skin)) look.skin = raw.skin;
    if (HATS.some((h) => h[0] === raw.hat)) look.hat = raw.hat;
    if (CUTS.some((c) => c[0] === raw.cut)) look.cut = raw.cut;
    if (typeof raw.pack === "boolean") look.pack = raw.pack;
    if (OUTFITS.some((o) => o[0] === raw.outfit)) look.outfit = raw.outfit;
    if (BOTTOMS.some((o) => o[0] === raw.bottom)) look.bottom = raw.bottom;
    if (EXTRAS.some((o) => o[0] === raw.extra)) look.extra = raw.extra;
    if (BALLOONS.includes(raw.balloon)) look.balloon = raw.balloon;
    if (EYES.some((o) => o[0] === raw.eyes)) look.eyes = raw.eyes;
    if (Object.prototype.hasOwnProperty.call(PETS, raw.pet)) look.pet = raw.pet;
  } catch (err) { /* stockage indisponible : tenue par défaut */ }
  return look;
}
/* Progression : tampons, succès, records et compteurs. Relue avec prudence :
   seuls les identifiants connus et les nombres bornés sont repris. */
function loadProgress() {
  const p = { stamps: new Set(), wins: new Set(), best: {}, km: 0, jumps: 0, pets: [], cuts: [], played: [], fits: [], cars: [], tuned: [], day: "", gold: 0, goldDay: "", walked: 0, hellos: 0, quests: {}, qn: 0, qcut: "", duelWins: 0, bag: { plante: 0, bois: 0, minerai: 0 } };
  try {
    const raw = JSON.parse(window.localStorage.getItem(CARNET_KEY) || "{}");
    const src = Array.isArray(raw) ? { stamps: raw } : raw || {};
    if (Array.isArray(src.stamps)) src.stamps.forEach((id) => { if (STAMPS.some((st) => st[0] === id)) p.stamps.add(id); });
    if (Array.isArray(src.wins)) src.wins.forEach((id) => { if (WINS.some((w) => w[0] === id)) p.wins.add(id); });
    Object.keys(GOALS).forEach((game) => {
      const v = src.best && src.best[game];
      if (Number.isFinite(v)) p.best[game] = clamp(Math.round(v), 0, 100);
    });
    if (Number.isFinite(src.km)) p.km = clamp(src.km, 0, 1e5);
    if (Number.isFinite(src.jumps)) p.jumps = clamp(Math.round(src.jumps), 0, 1e6);
    if (Number.isFinite(src.walked)) p.walked = clamp(src.walked, 0, 1e7);
    QUESTS.forEach((q) => { const v = src.quests && src.quests[q.id]; if ([1, 2, 3].includes(v)) p.quests[q.id] = v; });
    if (Number.isFinite(src.qn)) p.qn = clamp(Math.round(src.qn), 0, 5);
    if (Number.isFinite(src.duelWins)) p.duelWins = clamp(Math.round(src.duelWins), 0, 1e6);
    Object.keys(p.bag).forEach((k) => { const v = src.bag && src.bag[k]; if (Number.isFinite(v)) p.bag[k] = clamp(Math.round(v), 0, 1e6); });
    if (typeof src.qcut === "string" && /^[a-z]{1,12}$/.test(src.qcut)) p.qcut = src.qcut;
    if (Number.isFinite(src.hellos)) p.hellos = clamp(Math.round(src.hellos), 0, 1e6);
    ["pets", "cuts", "played", "fits", "cars", "tuned"].forEach((k) => {
      if (Array.isArray(src[k])) p[k] = src[k].filter((v) => typeof v === "string" && /^[a-z]{1,12}$/.test(v)).slice(0, 24);
    });
    if (typeof src.day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(src.day)) p.day = src.day;
    if (typeof src.goldDay === "string" && /^\d{4}-\d{2}-\d{2}$/.test(src.goldDay)) p.goldDay = src.goldDay;
    if (Number.isFinite(src.gold)) p.gold = clamp(Math.round(src.gold), 0, 9999);
  } catch (err) { /* stockage indisponible : on repart de zéro */ }
  return p;
}
// Jeton aléatoire du promeneur : le serveur en tire son pseudo, toujours le même sur cet appareil.
function playerToken() {
  try {
    const kept = window.localStorage.getItem(PLAYER_KEY) || "";
    if (/^"?[0-9a-f]{32}"?$/.test(kept)) return kept.replace(/"/g, "");
  } catch (err) { /* stockage indisponible : jeton le temps de la visite */ }
  const bytes = new Uint8Array(16);
  if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  const token = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  store(PLAYER_KEY, token);
  return token;
}
function store(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (err) { /* non bloquant */ }
}
const FIREWORKS = ["#ff5d8f", "#ffd166", "#7bdff2", "#b8f2a0", "#f7aef8", "#ffffff", "#ff9f1c"];
// Mini-jeux : stand de la fête → jeu, et score à atteindre pour le succès du même nom.
const STALL_GAMES = ["crepes", "frites", "barbe", "canards"];
const SHOP_GAMES = { "BISTROT DU PARVIS": "passage", "CAFÉ LA BARRIÈRE": "paires", "PIZZERIA DU ROND-POINT": "olives", "GLACES DU FEU VERT": "feu", "SPA DU POINT MORT": "course" };
const GOALS = { canards: 15, crepes: 80, frites: 25, barbe: 100, tambour: 8, plein: 95, paires: 70, ballons: 20, passage: 8, olives: 18, feu: 70, course: 80, creneau: 80 };
const GAME_NAMES = { canards: "Pêche aux canards", crepes: "Crêpes", frites: "Frites", barbe: "Barbe à papa", tambour: "Grosse caisse", plein: "Le plein pile", paires: "Jeu des paires", ballons: "Éclate-ballons", passage: "Le passage piéton", olives: "Chasse aux olives", feu: "Feu vert !", course: "Course de canards", creneau: "Le créneau parfait" };
// Succès : ce qu'on gagne en jouant. Le dernier récompense tous les autres.
const WINS = [
  ["carnet", "Carnet complet", "Obtenir tous les tampons du carnet."],
  ["km", "Rouleur", "Parcourir 1 km au volant."],
  ["bolide", "Pied au plancher", "Atteindre la vitesse maximale d'un véhicule."],
  ["creneau", "Créneau parfait", "80 / 100 sur la place d'entraînement de la station."],
  ["kangourou", "Kangourou", "Sauter 25 fois."],
  ["zoo", "Ami des bêtes", "Se promener avec 5 compagnons différents."],
  ["coiffe", "Tête d'affiche", "Essayer 4 coupes de cheveux."],
  ["nuit", "Oiseau de nuit", "Se promener de nuit."],
  ["photo", "Photographe", "Prendre une photo souvenir."],
  ["canards", "Roi de la mare", "Pêcher 15 canards."],
  ["crepes", "Chef crêpier", "80 points au stand de crêpes."],
  ["frites", "Cornet plein", "Rattraper 25 frites."],
  ["barbe", "Nuage de sucre", "Une barbe à papa énorme : 100 points."],
  ["tambour", "Sens du rythme", "Tenir 8 tours à la grosse caisse."],
  ["plein", "Le plein pile", "95 / 100 à la pompe de la station."],
  ["paires", "Mémoire d'éléphant", "70 points au jeu des paires du café."],
  ["ballons", "Fine aiguille", "Éclater 20 ballons."],
  ["passage", "Piéton prudent", "Traverser 8 fois au passage piéton."],
  ["olives", "Pizzaïolo", "Attraper 18 olives."],
  ["feu", "Réflexes de pilote", "70 points à « Feu vert ! »."],
  ["tournee", "Tournée des stands", "Jouer à tous les mini-jeux."],
  ["garage", "Collection de clés", "Conduire tous les véhicules en libre-service."],
  ["marche", "Grand marcheur", "Parcourir 2 km à pied."],
  ["sociable", "Sociable", "Saluer dix fois."],
  ["chance", "Verni", "Tirer une « Grande chance » au belvédère."],
  ["rencontre", "Bonjour voisin", "Croiser un autre promeneur."],
  ["coucou", "Poli", "Saluer un autre promeneur (touches 1 à 4)."],
  ["foule", "Il y a du monde", "Être au moins trois promeneurs en même temps."],
  ["fidele", "Client fidèle", "Revenir se promener un autre jour."],
  ["or", "Chercheur d'or", "Trouver le ticket d'or du jour : il change de cachette chaque jour."],
  ["collection", "Collectionneur", "Trouver 5 tickets d'or, un par jour."],
  ["style", "Garde-robe", "Essayer 4 tenues différentes."],
  ["ballon", "Tête en l'air", "Sauter avec un ballon KingPar : on retombe tout doucement."],
  ["covoit", "Covoiturage", "Monter dans la voiture d'un autre promeneur."],
  ["taxi", "Chauffeur", "Conduire un autre promeneur."],
  ["amitie", "L'amour gagne toujours", "Se saluer à deux, en même temps."],
  ["roi", "Roi de KingPar", "Porter la couronne KingPar (" + CROWN_WINS + " succès pour l'obtenir)."],
  ["duel", "Bon joueur", "Disputer un défi amical avec un autre promeneur."],
  ["champion", "Champion du parvis", "Gagner trois défis."],
  ["jardinier", "Main verte", "Ramasser 10 plantes à la Kingfarm."],
  ["bucheron", "Bûcheron", "Abattre 5 arbres à coups de poing."],
  ["mineur", "Mineur de fond", "Extraire 8 minerais à la mine."],
  ["fermier", "Roi de la Kingfarm", "Récolter 30 ressources en tout."],
  ["voisin", "Bon voisin", "Rendre service à un habitant : terminer une quête."],
  ["serviable", "Serviable", "Terminer trois quêtes."],
  ["heros", "Héros de Bonneplace", "Terminer toutes les quêtes."],
  ["course", "Canard de bain", "80 points à la course de canards du spa."],
  ["tuning", "Premier coup de clé", "Personnaliser un véhicule au KingPar Tuning."],
  ["carrossier", "Carrossier", "Personnaliser trois véhicules différents."],
  ["nuancier", "Nuancier", "Essayer six peintures dans la même visite à l'atelier."],
  ["chef", "Chef d'orchestre", "Klaxonner cinq fois.", true], // les sept suivants sont secrets : « ??? » tant qu'on ne les a pas
  ["showcar", "Bête de concours", "Monter jantes, autocollant, néon et accessoire sur le même véhicule.", true],
  ["bouton", "Il ne fallait pas appuyer", "Appuyer sur le gros bouton rouge, au milieu de la route.", true],
  ["minuit", "Cloche de minuit", "Sonner la cloche du belvédère la nuit.", true],
  ["ange", "Saut de l'ange", "Sauter du haut de la passerelle.", true],
  ["montgolfiere", "Montgolfière", "Sauter au sommet du belvédère avec un ballon.", true],
  ["echo", "Écho", "Saluer au fond de la grotte.", true],
  ["legende", "Légende de Bonneplace", "Obtenir tous les autres succès."],
];
/* Quêtes : six habitants ont un petit service à demander. « ! » : il a quelque
   chose à dire ; « ? » gris : c'est en cours ; « ? » jaune : revenez le voir. */
const QUESTS = [
  { id: "chat", who: "Mamie Gisèle", look: { top: "#b388ff", pants: "#6b4a35", hair: "#b9bec9", skin: "#f6d7bd", cut: "bun", outfit: "pull", bottom: "jupe", extra: "lunettes" },
    ask: "Mon chat Moustache a encore filé du côté de l'étang. Tu veux bien me le ramener, mon petit ?", todo: "Retrouver Moustache près de l'étang du jardin.", done: "Moustache ! Viens là, vilain. Merci, tu es un amour." },
  { id: "fleurs", who: "Lila la fleuriste", look: { top: "#ff5d8f", pants: "#3d8a3a", hair: "#c2552d", skin: "#f0c9a4", cut: "tresses", outfit: "salopette", hat: "straw" },
    ask: "Il me manque cinq fleurs dorées pour mon plus beau bouquet. Elles poussent au bord des champs.", todo: "Cueillir 5 fleurs dorées autour des champs.", done: "Quel bouquet ! Il sent bon le printemps. Merci mille fois." },
  { id: "cloche", who: "Tonton Klaxon", look: { top: "#f2b01e", pants: "#27408b", hair: "#3b2a20", skin: "#dba97c", cut: "banane", outfit: "veste", hat: "beret" },
    ask: "Avec tout ce bazar à la fête, j'entends plus la cloche du belvédère. Tu la fais sonner pour moi ?", todo: "Faire sonner la cloche du belvédère.", done: "Dong ! Ah, là je l'ai entendue. T'es un chef." },
  { id: "olives", who: "Chef Rondo", look: { top: "#f4f5f7", pants: "#22252e", hair: "#15161a", skin: "#b97f55", cut: "boucles", outfit: "chemise", extra: "echarpe" },
    ask: "Mes olives se font la malle ! Attrape-en douze à mon jeu, à la pizzeria, et tu sauves mon service.", todo: "Attraper 12 olives au jeu de la pizzeria.", done: "Mamma mia, quelle main ! La maison t'offre… toute mon admiration." },
  { id: "coupe", who: "Zoé", look: { top: "#17c3b2", pants: "#8839ef", hair: "#9b5de5", skin: "#8a5a3c", cut: "twin", outfit: "robe", eyes: "manga" },
    ask: "Je viens d'ouvrir le salon et personne n'ose ! Change de coupe chez Coiffure Le Créneau, que je voie ça.", todo: "Changer de coupe chez le coiffeur.", done: "Waouh ! Ça te va trop bien. Reviens quand tu veux." },
  { id: "colis", who: "Léo le livreur", look: { top: "#fe640b", pants: "#22252e", hair: "#e3c26a", skin: "#f0c9a4", cut: "piques", outfit: "hoodie", hat: "cap" },
    ask: "J'ai un colis pour la Boutique KingPar et ma camionnette fait la sieste. Tu le déposes pour moi ?", todo: "Déposer le colis devant la Boutique KingPar.", done: "Livré dans les temps ! Tu veux pas mon métier ?" },
];
const RANKS = [[0, "Visiteur"], [4, "Habitué"], [9, "Citoyen de Bonneplace"], [18, "Pilier du parking"], [WINS.length - 1, "Légende de Bonneplace"]];
const EMOTES = ["Coucou !", "Bravo !", "On fait la course ?", "Suivez-moi !"];
const PLAYER_KEY = "access.plan3d.joueur";
const WELCOME_KEY = "access.plan3d.accueil";
/* Le visage, peint sur la tête (512 × 256, le milieu du visage en x = 128) :
   grands yeux, petit nez, sourire, joues roses. C'est lui qui donne le
   regard du personnage ; `closed` dessine les yeux fermés (clignement). */
function drawFace(g, w, h, c, closed) {
  const k = w / 512, X = 128, Y = 138;
  g.save();
  g.scale(k, k);
  g.fillStyle = c.skin; g.fillRect(0, 0, 512, 256);
  const dark = "#2a1f1a", style = c.eyes || "ronds";
  [-1, 1].forEach((sx) => {
    const x = X + sx * 37;
    const blush = g.createRadialGradient(x + sx * 20, Y + 24, 1, x + sx * 20, Y + 24, 17);
    blush.addColorStop(0, "rgba(255,120,140,.62)"); blush.addColorStop(1, "rgba(255,120,140,0)");
    g.fillStyle = blush; g.fillRect(x + sx * 20 - 18, Y + 6, 36, 36);
    g.strokeStyle = c.brow; g.lineWidth = 3.4; g.lineCap = "round"; // sourcil
    g.beginPath(); g.moveTo(x - 12, Y - 29 - sx * 1.5); g.quadraticCurveTo(x, Y - 35, x + 12, Y - 29 + sx * 1.5); g.stroke();
    if (closed) {
      g.strokeStyle = dark; g.lineWidth = 4; g.beginPath(); g.moveTo(x - 11, Y); g.quadraticCurveTo(x, Y + 8, x + 11, Y); g.stroke();
      return;
    }
    if (style === "manga" || style === "etoiles") {
      g.fillStyle = "#ffffff"; g.beginPath(); g.ellipse(x, Y, 16, 20, 0, 0, Math.PI * 2); g.fill();
      const iris = g.createLinearGradient(0, Y - 14, 0, Y + 15);
      iris.addColorStop(0, "#1c4fa8"); iris.addColorStop(1, "#6fc3ff");
      g.fillStyle = iris; g.beginPath(); g.ellipse(x, Y + 1.5, 12.5, 16, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = dark; g.beginPath(); g.ellipse(x, Y + 1, 5, 7, 0, 0, Math.PI * 2); g.fill();
      g.strokeStyle = dark; g.lineWidth = 4.5; g.beginPath(); g.moveTo(x - 17, Y - 8); g.quadraticCurveTo(x, Y - 25, x + 17, Y - 8); g.stroke(); // cils
      g.fillStyle = "#ffffff";
      if (style === "etoiles") {
        g.beginPath();
        for (let i = 0; i < 10; i++) { const a = (i / 10) * Math.PI * 2 - Math.PI / 2, r = i % 2 ? 2.4 : 6; g.lineTo(x - 3 + Math.cos(a) * r, Y - 4 + Math.sin(a) * r); }
        g.fill();
      } else { g.beginPath(); g.arc(x - 4, Y - 6, 4, 0, Math.PI * 2); g.fill(); }
      g.beginPath(); g.arc(x + 4, Y + 8, 2, 0, Math.PI * 2); g.fill();
    } else {
      g.fillStyle = dark; g.beginPath(); g.ellipse(x, Y, 12.5, style === "malins" ? 12 : 19, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#ffffff";
      g.beginPath(); g.arc(x - 4, Y - 7.5, 5.2, 0, Math.PI * 2); g.fill();
      g.beginPath(); g.arc(x + 3.5, Y + 6, 2, 0, Math.PI * 2); g.fill();
      if (style === "malins") { g.fillStyle = c.skin; g.fillRect(x - 13, Y - 16, 26, 9); g.strokeStyle = dark; g.lineWidth = 3.4; g.beginPath(); g.moveTo(x - 12, Y - 7); g.lineTo(x + 12, Y - 7); g.stroke(); }
    }
    if (c.extra === "lunettes") { g.strokeStyle = "#22252e"; g.lineWidth = 3.4; g.beginPath(); g.arc(x, Y, 21, 0, Math.PI * 2); g.stroke(); }
    if (c.extra === "soleil") { g.fillStyle = "#15161a"; roundRect(g, x - 22, Y - 15, 44, 30, 12); g.fill(); g.fillStyle = "rgba(255,255,255,.28)"; g.fillRect(x - 15, Y - 10, 12, 5); }
  });
  if (c.extra === "lunettes" || c.extra === "soleil") { g.strokeStyle = "#22252e"; g.lineWidth = 3.4; g.beginPath(); g.moveTo(X - 12, Y - 3); g.lineTo(X + 12, Y - 3); g.stroke(); }
  g.fillStyle = c.nose; g.beginPath(); g.moveTo(X - 5, Y + 20); g.lineTo(X + 5, Y + 20); g.lineTo(X, Y + 28); g.closePath(); g.fill(); // petit nez
  g.strokeStyle = "#8c3b3b"; g.lineWidth = 3.6; g.lineCap = "round";
  g.beginPath(); g.moveTo(X - 13, Y + 38); g.quadraticCurveTo(X, Y + 51, X + 13, Y + 38); g.stroke(); // sourire
  g.restore();
  void h;
}
/* Le logo KingPar : une couronne imprimée par un pneu, posée sur sa trace.
   Même dessin que `kingpar-logo.svg` (et que le fichier Figma de la marque). */
function drawLogo(g, x, y, size) {
  const crown = new Path2D("M46 154 L36 80 L84 118 L120 56 L156 118 L204 80 L194 154 Z");
  g.save();
  g.translate(x, y);
  g.scale(size / 240, size / 240);
  g.fillStyle = BRAND; roundRect(g, 0, 0, 240, 240, 54); g.fill();
  g.save(); g.clip(crown);
  g.strokeStyle = "#ffffff"; g.lineWidth = 7; g.beginPath();
  for (let row = 0, yy = 50; yy < 160; yy += 17, row++) for (let xx = 22; xx < 226; xx += 24) {
    const ox = xx + (row % 2 ? 12 : 0);
    g.moveTo(ox, yy + 11); g.lineTo(ox + 12, yy); g.lineTo(ox + 24, yy + 11);
  }
  g.stroke(); g.restore();
  g.lineWidth = 6; g.lineJoin = "round"; g.strokeStyle = "#ffffff"; g.stroke(crown);
  g.fillStyle = "#ffd60a";
  [[36, 80, 10], [120, 56, 11], [204, 80, 10]].forEach((c) => { g.beginPath(); g.arc(c[0], c[1], c[2], 0, Math.PI * 2); g.fill(); });
  g.fillStyle = "#ffffff";
  for (let xx = 44; xx < 190; xx += 17) { g.beginPath(); g.moveTo(xx, 190); g.lineTo(xx + 11, 190); g.lineTo(xx + 16, 168); g.lineTo(xx + 5, 168); g.closePath(); g.fill(); }
  g.restore();
}
// Autocollants du tuning : dessinés ici, jamais retournés (ils se lisent des deux côtés).
function drawSticker(g, w, id) {
  const u = w / 100;
  g.clearRect(0, 0, w, w);
  g.lineJoin = "round"; g.lineCap = "round";
  const outline = (path, fill, edge) => { g.lineWidth = 7 * u; g.strokeStyle = edge || "#ffffff"; g.stroke(path); g.fillStyle = fill; g.fill(path); };
  const scaled = (d) => { const m = new Path2D(); m.addPath(new Path2D(d), new DOMMatrix([u, 0, 0, u, 0, 0])); return m; };
  if (id === "kingpar") drawLogo(g, w * 0.04, w * 0.04, w * 0.92);
  else if (id === "numero") {
    g.beginPath(); g.arc(50 * u, 50 * u, 44 * u, 0, Math.PI * 2);
    g.fillStyle = "#ffffff"; g.fill(); g.lineWidth = 6 * u; g.strokeStyle = "#15161a"; g.stroke();
    g.fillStyle = "#15161a"; g.font = "900 " + 62 * u + "px system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText("7", 50 * u, 54 * u);
  } else if (id === "flammes") {
    outline(scaled("M50 6 C58 26 84 40 80 66 C78 84 64 94 50 94 C36 94 22 84 20 66 C17 44 36 38 38 22 C44 28 46 34 46 40 C50 30 52 18 50 6 Z"), "#fe640b", "#ffffff");
    g.fillStyle = "#ffd60a"; g.fill(scaled("M50 44 C56 56 66 62 64 74 C62 84 56 88 50 88 C44 88 38 84 36 74 C35 64 44 58 50 44 Z"));
  } else if (id === "eclair") outline(scaled("M58 6 L22 54 L44 54 L36 94 L78 42 L54 42 Z"), "#ffd60a", "#15161a");
  else if (id === "coeur") {
    outline(scaled("M50 88 C20 66 8 48 12 32 C16 14 38 10 50 28 C62 10 84 14 88 32 C92 48 80 66 50 88 Z"), "#ff4d6d", "#ffffff");
    g.fillStyle = "rgba(255,255,255,.7)"; g.beginPath(); g.ellipse(32 * u, 32 * u, 8 * u, 5 * u, -0.6, 0, Math.PI * 2); g.fill();
  } else if (id === "patte") {
    g.fillStyle = "#ffffff";
    [[50, 64, 27, 22], [22, 40, 12, 14], [40, 24, 12, 15], [60, 24, 12, 15], [78, 40, 12, 14]].forEach((e) => { g.beginPath(); g.ellipse(e[0] * u, e[1] * u, (e[2] + 4) * u, (e[3] + 4) * u, 0, 0, Math.PI * 2); g.fill(); });
    g.fillStyle = "#6b4a35";
    [[50, 64, 27, 22], [22, 40, 12, 14], [40, 24, 12, 15], [60, 24, 12, 15], [78, 40, 12, 14]].forEach((e) => { g.beginPath(); g.ellipse(e[0] * u, e[1] * u, e[2] * u, e[3] * u, 0, 0, Math.PI * 2); g.fill(); });
  } else if (id === "etoile") {
    const star = new Path2D();
    for (let k = 0; k < 10; k++) { const a = (k / 10) * Math.PI * 2 - Math.PI / 2, r = (k % 2 ? 20 : 44) * u; star[k ? "lineTo" : "moveTo"](50 * u + Math.cos(a) * r, 52 * u + Math.sin(a) * r); }
    star.closePath();
    outline(star, "#ffd60a", "#ffffff");
  } else if (id === "damier") {
    g.save(); roundRect(g, 8 * u, 8 * u, 84 * u, 84 * u, 14 * u); g.clip();
    for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) { g.fillStyle = (r + c) % 2 ? "#15161a" : "#ffffff"; g.fillRect((8 + c * 21) * u, (8 + r * 21) * u, 21 * u, 21 * u); }
    g.restore();
    g.lineWidth = 4 * u; g.strokeStyle = "#15161a"; roundRect(g, 8 * u, 8 * u, 84 * u, 84 * u, 14 * u); g.stroke();
  }
}
const ROOF_TILES = ["#e2574c", "#4f86e0", "#e98b3a", "#5fb86a", "#c9546b", "#e2574c"];
const FACADES = ["#ffffff", "#ffe9c9", "#dcebff", "#ffe1e7", "#e2f3da", "#fff3c4"];
const FLOWERS = ["#04a5e5", "#40a02b", "#df8e1d", "#7287fd", "#fe640b", "#f6a5c0", "#ffd60a", "#f4f5f7"];
const BLOSSOM = ["#ffb7c5", "#ff9eb5", "#ffc9d6", "#f8a5c2", "#ffd3de"];
const AWNINGS = ["#2b3a67", "#8c2f39", "#1f6f5c", "#b5651d", "#5b3a8c", "#2f6690", "#9c3d54", "#3a5a40"];
// Borne de réservation et point d'arrivée du promeneur (repère du parking).
const RESA_KIOSK = { x: -8.6, z: -3.4 };
const SPAWN = { x: -8.6, z: -6.4 };

// Hauteur du repère « R » au-dessus de chaque modèle.
const RESA_HEIGHT = { hatch: 2.3, sedan: 2.3, suv: 2.6, ev: 2.3, van: 3.4, camper: 3.9, moto: 1.9, scooter: 1.9 };

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
  if (P.length < 2) { out.x = P[0][0]; out.z = P[0][1]; return; } // trajet d'un seul point : déjà arrivé
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
// Tuiles en écailles : rangées de demi-ronds décalés, teintées par la couleur du toit.
function tileTexture() {
  const t = canvasTexture(128, (g, w) => {
    g.fillStyle = "#f4f4f4"; g.fillRect(0, 0, w, w);
    for (let row = 3; row >= 0; row--) for (let col = -1; col < 4; col++) {
      const x = col * 32 + (row % 2 ? 16 : 0), y = row * 32;
      g.fillStyle = "rgba(0,0,0,.2)"; g.beginPath(); g.arc(x + 16, y + 5, 17, 0, Math.PI); g.fill();
      g.fillStyle = (row + col) % 2 ? "#ffffff" : "#e2e2e2"; g.beginPath(); g.arc(x + 16, y, 16, 0, Math.PI); g.fill();
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(5, 3);
  return t;
}
// Prairie dessinée : fond uni, petits triangles et pastilles clairs ou foncés.
function grassTexture() {
  const rnd = mulberry(11);
  const t = canvasTexture(256, (g, w) => {
    g.fillStyle = "rgb(234,234,234)"; g.fillRect(0, 0, w, w);
    for (let i = 0; i < 44; i++) {
      const x = rnd() * w, y = rnd() * w, sz = 5 + rnd() * 6;
      g.fillStyle = rnd() < 0.5 ? "rgba(255,255,255,.6)" : "rgba(150,150,150,.38)";
      g.beginPath();
      if (i % 3) { g.moveTo(x, y - sz); g.lineTo(x + sz * 0.8, y + sz * 0.6); g.lineTo(x - sz * 0.8, y + sz * 0.6); g.closePath(); } else g.arc(x, y, sz * 0.45, 0, Math.PI * 2);
      g.fill();
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
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
.p3d > canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; cursor: grab; outline: none; }
.p3d > canvas.dragging { cursor: grabbing; }
.p3d > canvas.pointing { cursor: pointer; }
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
.p3d-resa { display: flex; align-items: center; gap: 7px; }
.p3d-resa i { font: 800 10px/16px system-ui, sans-serif; font-style: normal; width: 16px; height: 16px; border-radius: 5px; text-align: center; color: #fff; background: #1e66f5; }
.p3d-tip { position: absolute; left: 0; top: 0; padding: 8px 11px; max-width: 260px; pointer-events: none; opacity: 0;
  transition: opacity .12s; z-index: 3; }
.p3d-tip.on { opacity: 1; }
.p3d-tip b { display: block; }
.p3d-tip span { display: block; color: var(--subtext, #6c6f85); font-size: 12px; }
.p3d-hint { right: 14px; bottom: 14px; padding: 7px 11px; font-size: 11.5px; color: var(--subtext, #6c6f85); }
.p3d-prompt { all: unset; cursor: pointer; pointer-events: auto; position: absolute; left: 50%; bottom: 96px; transform: translateX(-50%);
  display: none; align-items: center; gap: 10px; padding: 10px 16px 10px 10px; border-radius: 999px; white-space: nowrap;
  font: 700 15px/1 system-ui, -apple-system, "Segoe UI", sans-serif; color: #fff; background: rgba(24,24,37,.86);
  border: 1px solid rgba(255,255,255,.28); box-shadow: 0 10px 28px rgba(0,0,0,.35); z-index: 4; }
.p3d-prompt.on { display: inline-flex; }
.p3d-prompt kbd { font: 800 13px/1 system-ui, sans-serif; padding: 6px 9px; border-radius: 8px; color: #11111b; background: #fff; }
.p3d-here { left: 50%; top: 14px; transform: translateX(-50%); padding: 8px 14px; display: none; align-items: center; gap: 8px; font-weight: 700; white-space: nowrap; }
.p3d-here.on { display: flex; }
.p3d-here i { width: 10px; height: 10px; border-radius: 3px; background: var(--c, #888); }
.p3d-here span { font-weight: 500; color: var(--subtext, #6c6f85); font-variant-numeric: tabular-nums; }
.p3d-panel { left: 50%; top: 50%; transform: translate(-50%, -50%); width: min(430px, calc(100% - 28px)); max-height: calc(100% - 28px);
  overflow: auto; padding: 18px; display: none; z-index: 6; }
.p3d-panel.on { display: block; }
.p3d-panel, .p3d-toast { background: linear-gradient(var(--glass-hi, rgba(255,255,255,.72)), var(--glass-hi, rgba(255,255,255,.72))),
  linear-gradient(var(--glass-hi, rgba(255,255,255,.72)), var(--glass-hi, rgba(255,255,255,.72))),
  linear-gradient(145deg, var(--glass-hi, rgba(255,255,255,.72)), var(--glass-lo, rgba(255,255,255,.46))); }
.p3d-panel h3 { margin: 0 0 4px; font-size: 19px; display: flex; align-items: center; gap: 9px; }
.p3d-panel h3 i { font: 800 13px/22px system-ui, sans-serif; font-style: normal; width: 22px; height: 22px; border-radius: 7px; text-align: center; color: #fff; background: #1e66f5; }
.p3d-panel p { margin: 6px 0 12px; color: var(--subtext, #6c6f85); font-size: 13px; }
.p3d-panel table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.p3d-panel th { text-align: left; font-weight: 600; color: var(--subtext, #6c6f85); font-size: 12px; padding: 4px 6px; }
.p3d-panel td { padding: 7px 6px; border-top: 1px solid var(--hairline, rgba(76,79,105,.12)); font-variant-numeric: tabular-nums; }
.p3d-panel td:first-child { font-weight: 600; }
.p3d-panel td i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 8px; background: var(--c); }
.p3d-panel button { all: unset; cursor: pointer; display: block; margin: 14px 0 0 auto; padding: 9px 16px; border-radius: 11px;
  font: 700 13.5px/1 system-ui, sans-serif; color: var(--on-accent, #fff); background: var(--blue, #1e66f5); }
.p3d-panel.side { left: auto; right: 14px; transform: translateY(-50%); width: min(340px, calc(100% - 28px)); }
.p3d-panel h4 { margin: 14px 0 7px; font-size: 11.5px; letter-spacing: .05em; text-transform: uppercase; color: var(--subtext, #6c6f85); }
.p3d-row { display: flex; flex-wrap: wrap; gap: 8px; }
.p3d-panel button.p3d-sw { display: inline-block; margin: 0; padding: 0; width: 32px; height: 32px; border-radius: 50%; background: var(--c);
  border: 2px solid rgba(255,255,255,.85); box-shadow: 0 0 0 1px rgba(17,17,27,.22); }
.p3d-panel button.p3d-chip { display: inline-block; margin: 0; padding: 8px 12px; border-radius: 999px; font-weight: 600;
  color: var(--text, #4c4f69); background: var(--field, rgba(204,208,218,.42)); }
.p3d-panel button.p3d-sw[aria-pressed="true"] { box-shadow: 0 0 0 3px var(--blue, #1e66f5); }
.p3d-panel button.p3d-chip[aria-pressed="true"] { color: var(--on-accent, #fff); background: var(--blue, #1e66f5); }
.p3d-panel button:focus-visible { outline: 2px solid var(--blue, #1e66f5); outline-offset: 2px; }
.p3d-stamps { list-style: none; margin: 0; padding: 0; }
.p3d-stamps li { display: grid; grid-template-columns: 26px 1fr; gap: 0 10px; align-items: center; padding: 7px 2px; border-top: 1px solid var(--hairline, rgba(76,79,105,.12)); }
.p3d-stamps li i { grid-row: 1 / 3; width: 24px; height: 24px; border-radius: 50%; box-sizing: border-box; border: 2px dashed var(--subtext, #6c6f85);
  font: 800 13px/20px system-ui, sans-serif; font-style: normal; text-align: center; color: #fff; }
.p3d-stamps li.done i { border: 2px solid #d92b3a; background: #d92b3a; transform: rotate(-12deg); }
.p3d-stamps li b { font-weight: 600; }
.p3d-stamps li span { font-size: 12px; color: var(--subtext, #6c6f85); }
.p3d-stamps li.done b { text-decoration: line-through; text-decoration-color: rgba(217,43,58,.6); }
.p3d-carnet { all: unset; cursor: pointer; pointer-events: auto; position: absolute; right: 14px; top: 64px; display: none; align-items: center; gap: 8px;
  padding: 8px 13px; border-radius: 999px; font: 700 13px/1 system-ui, -apple-system, "Segoe UI", sans-serif; color: #fff;
  background: #d92b3a; border: 1px solid rgba(255,255,255,.4); box-shadow: 0 8px 22px rgba(0,0,0,.28); z-index: 4; }
.p3d-carnet:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
.p3d.walking .p3d-carnet { display: inline-flex; }
.p3d-carnet span { font-variant-numeric: tabular-nums; opacity: .92; }
.p3d-carnet.p3d-photo { top: 104px; background: rgba(24,24,37,.86); }
.p3d-carnet.p3d-hello { top: 144px; background: rgba(24,24,37,.86); }
.p3d-online { left: 14px; top: 84px; padding: 7px 12px; display: none; align-items: center; gap: 8px; font-weight: 700; font-size: 12.5px; white-space: nowrap; }
.p3d.walking .p3d-online.on, .p3d-online.watch { display: flex; }
.p3d-online i { width: 9px; height: 9px; border-radius: 50%; background: #40a02b; box-shadow: 0 0 0 4px rgba(64,160,43,.25); }
.p3d-online span { font-weight: 500; color: var(--subtext, #6c6f85); }
.p3d-tag.who { background: rgba(30,102,245,.92); font-weight: 700; }
.p3d-stamps li.win.done i { border-color: #f2b01e; background: #f2b01e; transform: none; }
.p3d-stamps li.win.done b { text-decoration: none; }
.p3d-panel table.p3d-scores td:last-child { color: var(--subtext, #6c6f85); }
.p3d-panel img { display: block; width: 100%; border-radius: 12px; margin: 10px 0 4px; }
.p3d-panel a.p3d-save { display: inline-block; margin-top: 6px; font-weight: 700; color: var(--blue, #1e66f5); }
.p3d-panel p.p3d-lead { margin: 8px 0 4px; font-size: 14px; color: var(--text, #4c4f69); }
.p3d-panel p.p3d-lead b { font-size: 30px; line-height: 1; margin-right: 6px; font-variant-numeric: tabular-nums; color: #2a9d4b; }
.p3d-panel p.p3d-luck { margin: 14px 0 4px; font-size: 17px; font-weight: 700; color: var(--text, #4c4f69); }
.p3d-perks { margin: 4px 0 12px; padding: 0 0 0 18px; font-size: 13px; }
.p3d-perks li { margin: 3px 0; }
.p3d-toast { left: 50%; top: 62px; transform: translateX(-50%); padding: 9px 15px; display: none; font-weight: 700; text-align: center;
  max-width: min(460px, calc(100% - 28px)); z-index: 5; }
.p3d-toast.on { display: block; }
.p3d-joy { position: absolute; left: 0; top: 0; width: 120px; height: 120px; margin: -60px 0 0 -60px; border-radius: 50%; display: none;
  background: rgba(255,255,255,.16); border: 2px solid rgba(255,255,255,.55); pointer-events: none; z-index: 3; }
.p3d-joy.on { display: block; }
.p3d-joy i { position: absolute; left: 50%; top: 50%; width: 52px; height: 52px; margin: -26px 0 0 -26px; border-radius: 50%; background: rgba(255,255,255,.85); box-shadow: 0 4px 12px rgba(0,0,0,.3); }
.p3d-speed { right: 14px; bottom: 56px; padding: 10px 14px; display: none; align-items: baseline; gap: 8px; }
.p3d-speed.on { display: flex; }
.p3d-speed b { font-size: 26px; line-height: 1; font-variant-numeric: tabular-nums; min-width: 2ch; text-align: right; }
.p3d-speed span { color: var(--subtext, #6c6f85); font-size: 12.5px; }
.p3d-act { all: unset; cursor: pointer; pointer-events: auto; position: absolute; right: 22px; bottom: 150px; width: 74px; height: 74px;
  border-radius: 50%; display: none; place-items: center; text-align: center; font: 800 13px/1.1 system-ui, sans-serif; color: #11111b;
  background: rgba(255,255,255,.86); border: 2px solid rgba(17,17,27,.18); box-shadow: 0 8px 22px rgba(0,0,0,.3); z-index: 4;
  -webkit-tap-highlight-color: transparent; touch-action: none; }
@media (pointer: coarse) { .p3d.walking .p3d-act { display: grid; } }
.p3d-tag.bubble { background: #fff; color: #11111b; border-color: rgba(17,17,27,.18); font-weight: 800; }
.p3d.walking > canvas { cursor: crosshair; }
.p3d.walking .p3d-legend { opacity: .92; }
.p3d-panel { border-radius: 22px; padding: 20px; box-shadow: 0 24px 60px rgba(17,17,27,.38); border-top: 4px solid #1e66f5; }
.p3d-panel h3 { font-size: 20px; letter-spacing: -.01em; }
.p3d-panel button { transition: transform .12s, filter .12s; }
.p3d-panel button:hover { filter: brightness(1.08); transform: translateY(-1px); }
.p3d-panel button:active { transform: scale(.97); }
.p3d-panel button.p3d-sw:hover { transform: scale(1.14); }
.p3d-panel img.p3d-hero { width: 88px; margin: 0 auto 12px; border-radius: 22px; box-shadow: 0 10px 24px rgba(30,102,245,.35); }
.p3d-panel p.p3d-lead2 { font-size: 15px; font-weight: 600; color: var(--text, #4c4f69); }
.p3d-carnet { transition: transform .12s; }
.p3d-carnet:hover { transform: translateY(-1px) scale(1.04); }
.p3d-toast { border-left: 5px solid #ffd60a; }
.p3d-toast.on { animation: p3d-pop .3s cubic-bezier(.2, 1.4, .4, 1); }
@keyframes p3d-pop { from { opacity: 0; margin-top: -10px; } to { opacity: 1; margin-top: 0; } }
.p3d-prompt { padding: 11px 18px 11px 11px; background: linear-gradient(135deg, rgba(30,102,245,.96), rgba(24,24,37,.92)); }
.p3d-prompt kbd { animation: p3d-pulse 1.4s ease-in-out infinite; }
@keyframes p3d-pulse { 50% { transform: scale(1.13); } }
.p3d-hint { opacity: .8; }
@media (prefers-reduced-motion: reduce) { .p3d-toast.on, .p3d-prompt kbd { animation: none; } }
.p3d-tag.quest { background: #ffd60a; color: #22252e; font-size: 21px; font-weight: 900; padding: 1px 12px; border: 3px solid #fff; animation: p3d-hop 1.1s ease-in-out infinite; }
.p3d-tag.quest.idle { background: #b9bec9; color: #fff; animation: none; }
.p3d-tag.quest.over { background: #ff7aa8; color: #fff; animation: none; font-size: 15px; }
@keyframes p3d-hop { 50% { margin-top: -7px; } }
.p3d-panel.talk { top: auto; bottom: 26px; transform: translateX(-50%); width: min(560px, calc(100% - 28px)); padding: 18px 22px;
  background: #fff8e7; color: #5b4636; border: 4px solid #f1dfb6; border-radius: 30px; backdrop-filter: none; -webkit-backdrop-filter: none; }
.p3d-who { display: inline-block; padding: 6px 15px; border-radius: 999px; background: #ff9f1c; color: #fff; font: 800 14px/1 system-ui, sans-serif; transform: rotate(-2deg); }
.p3d-panel.talk p.p3d-say { margin: 12px 0 4px; font-size: 16.5px; font-weight: 600; line-height: 1.45; color: #5b4636; }
.p3d-panel.talk button { background: #40a02b; }
@media (prefers-reduced-motion: reduce) { .p3d-tag.quest { animation: none; } }
/* La pub du gros bouton rouge : bandes de cinéma, sous-titres, carton final. */
.p3d-cine { position: absolute; inset: 0; display: none; pointer-events: none; overflow: hidden; }
.p3d.cine > .p3d-cine { display: block; }
.p3d.cine > :not(canvas):not(.p3d-cine) { visibility: hidden !important; }
.p3d-cine::before, .p3d-cine::after { content: ""; position: absolute; left: 0; right: 0; height: 11%; background: #0b0c10; animation: p3d-bar .5s ease-out; }
.p3d-cine::before { top: 0; }
.p3d-cine::after { bottom: 0; }
@keyframes p3d-bar { from { height: 0; } }
.p3d-cine-badge { position: absolute; left: 16px; top: 3%; z-index: 1; padding: 4px 10px; border-radius: 8px; background: #d92b3a; color: #fff; font: 900 12px/1 system-ui, sans-serif; letter-spacing: .12em; }
.p3d-cine-skip { position: absolute; right: 16px; top: 2.2%; z-index: 1; pointer-events: auto; padding: 7px 14px; border: 0; border-radius: 999px; background: rgba(255,255,255,.16); color: #fff; font: 700 13px/1 system-ui, sans-serif; cursor: pointer; }
.p3d-cine-skip:hover, .p3d-cine-skip:focus-visible { background: rgba(255,255,255,.3); }
.p3d-cine-sub { position: absolute; left: 50%; bottom: 14%; transform: translateX(-50%); width: max-content; max-width: min(88%, 760px); margin: 0; padding: 10px 18px; border-radius: 18px;
  background: rgba(11,12,16,.74); color: #fff; font: 700 clamp(15px, 2.3vw, 22px)/1.35 system-ui, sans-serif; text-align: center; }
.p3d-cine-sub b { color: #ffd60a; margin-right: 9px; }
.p3d-cine-sub:empty { display: none; }
.p3d-cine-card { position: absolute; left: 50%; top: 46%; transform: translate(-50%, -50%) scale(.6); opacity: 0; transition: opacity .6s, transform .6s cubic-bezier(.2, 1.4, .4, 1);
  display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 22px 34px; border-radius: 30px; background: rgba(255,248,231,.95); color: #22252e; text-align: center; }
.p3d-cine-card.on { opacity: 1; transform: translate(-50%, -50%) scale(1); }
.p3d-cine-card canvas { width: 112px; height: 112px; }
.p3d-cine-card b { font: 900 clamp(26px, 5vw, 44px)/1 system-ui, sans-serif; color: #1e66f5; }
.p3d-cine-card span { font: 700 clamp(14px, 2.2vw, 19px)/1.3 system-ui, sans-serif; }
@media (max-width: 640px) { .p3d-panel.talk { bottom: 94px; } }
/* Habillage doux : cartes crème aux coins ronds, texte brun, police arrondie.
   Les couleurs sont fixées ici pour rester lisibles quel que soit le thème de la page. */
.p3d { --text: #5b4636; --subtext: #8a7460; --field: rgba(214,190,150,.38); --hairline: rgba(91,70,54,.16);
  --glass-hi: #fff8e7; --glass-lo: #fdf0cf; --glass-border: #f1dfb6; --blue: #1e66f5; --on-accent: #fff; }
.p3d-card, .p3d-tag, .p3d-prompt, .p3d-carnet, .p3d-panel button, .p3d-tools button, .p3d-who {
  font-family: ui-rounded, "SF Pro Rounded", "Hiragino Maru Gothic ProN", "Arial Rounded MT Bold", system-ui, -apple-system, "Segoe UI", sans-serif; }
.p3d-card { background: #fff8e7; border: 3px solid #f1dfb6; border-radius: 22px; color: #5b4636;
  backdrop-filter: none; -webkit-backdrop-filter: none; box-shadow: 0 5px 0 rgba(91,70,54,.14), 0 14px 28px rgba(17,17,27,.16); }
.p3d-panel { border-top: 3px solid #f1dfb6; }
.p3d-tools { padding: 5px; border-radius: 999px; }
.p3d-tools button { border-radius: 999px; padding: 8px 13px; font-weight: 700; transition: transform .12s; }
.p3d-tools button:hover { transform: translateY(-1px); }
.p3d-tools button[aria-pressed="true"] { background: #1e66f5; color: #fff; box-shadow: 0 3px 0 #1651c4; }
.p3d-head { border-radius: 20px; }
.p3d-legend { border-radius: 24px; }
.p3d-total b { color: #1e66f5; }
.p3d-hint { border-width: 2px; border-radius: 999px; box-shadow: 0 3px 0 rgba(91,70,54,.12); }
.p3d-here, .p3d-online, .p3d-toast { border-radius: 999px; }
.p3d-toast { border-left: 3px solid #f1dfb6; border-radius: 24px; background: #fffdf4; }
.p3d-tag { border: 2.5px solid #fff; box-shadow: 0 3px 0 rgba(17,17,27,.18); }
.p3d-tag.bubble { border-color: #f1dfb6; color: #5b4636; background: #fffdf4; }
.p3d-carnet { background: #fff8e7; color: #5b4636; border: 3px solid #f1dfb6; box-shadow: 0 4px 0 rgba(91,70,54,.16); }
.p3d-carnet:first-of-type, .p3d-carnet:not(.p3d-photo):not(.p3d-hello) { background: #ffd60a; border-color: #fff; color: #5b4636; }
.p3d-carnet.p3d-photo, .p3d-carnet.p3d-hello { background: #fff8e7; }
.p3d-prompt { background: #fff8e7; color: #5b4636; border: 3px solid #f1dfb6; box-shadow: 0 5px 0 rgba(91,70,54,.16), 0 12px 24px rgba(17,17,27,.2); }
.p3d-prompt kbd { background: #40a02b; color: #fff; border-radius: 50%; padding: 7px 10px; }
.p3d-panel button { border-radius: 999px; box-shadow: 0 3px 0 rgba(17,17,27,.16); }
.p3d-panel button.p3d-sw { box-shadow: 0 0 0 2px #f1dfb6; }
.p3d-panel button.p3d-chip { box-shadow: none; }
.p3d-speed b { color: #1e66f5; }
/* Les autres promeneurs : juste leur nom, sans fond, et seulement de près. */
.p3d-tag.who { background: none; border: 0; box-shadow: none; padding: 0; color: #fff; font-weight: 800; font-size: 13px;
  text-shadow: 0 1px 0 rgba(34,37,46,.85), 0 0 4px rgba(34,37,46,.75), 0 2px 6px rgba(34,37,46,.5); }
.p3d-wheel { position: relative; width: 264px; height: 264px; margin: 12px auto 4px; border-radius: 50%;
  background: radial-gradient(circle, #fffdf4 0 34%, #f6e7c2 35% 100%); box-shadow: inset 0 0 0 4px #f1dfb6, 0 6px 0 rgba(91,70,54,.14); }
.p3d-wheel b { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 78px; text-align: center; font-size: 13px; }
.p3d-panel button.p3d-round { position: absolute; display: grid; place-items: center; margin: 0; padding: 6px; width: 84px; height: 84px; box-sizing: border-box;
  border-radius: 50%; text-align: center; font-size: 12.5px; line-height: 1.15; background: #fff; color: #5b4636; border: 4px solid #1e66f5; }
.p3d-panel button.p3d-round:hover { transform: scale(1.08) rotate(-4deg); filter: none; background: #ffd60a; }
.p3d-grid3 { display: grid; grid-template-columns: repeat(3, 66px); gap: 8px; justify-content: center; margin: 12px 0; }
.p3d-panel button.p3d-cell { display: grid; place-items: center; margin: 0; padding: 0; width: 66px; height: 66px; border-radius: 16px; background: #fff;
  color: #1e66f5; font-size: 32px; font-weight: 900; border: 3px solid #f1dfb6; box-shadow: 0 3px 0 rgba(91,70,54,.14); }
.p3d-panel button.p3d-cell[disabled] { cursor: default; filter: none; transform: none; }
.p3d-row.center { justify-content: center; }
/* Défis : la pièce tourne puis retombe, les mains se secouent trois fois avant de se montrer. */
.p3d-stage { display: flex; align-items: center; justify-content: center; gap: 22px; height: 110px; margin: 6px 0; perspective: 500px; }
.p3d-coin { display: grid; place-items: center; width: 84px; height: 84px; border-radius: 50%; font: 900 17px/1 system-ui, sans-serif; color: #7a5a00;
  background: radial-gradient(circle at 35% 30%, #fff3a8, #ffd60a 55%, #d9a900); border: 4px solid #d9a900; box-shadow: 0 6px 0 rgba(91,70,54,.2);
  animation: p3d-flip 1.5s cubic-bezier(.2, .7, .3, 1) both; }
@keyframes p3d-flip { 0% { transform: translateY(0) rotateX(0); } 45% { transform: translateY(-46px) rotateX(1260deg); } 100% { transform: translateY(0) rotateX(2160deg); } }
.p3d-hand { position: relative; width: 84px; height: 84px; border-radius: 22px; background: #fff; border: 4px solid #f1dfb6; box-shadow: 0 5px 0 rgba(91,70,54,.16);
  animation: p3d-shake .3s ease-in-out 3; }
.p3d-hand i { position: absolute; inset: 0; display: grid; place-items: center; font-style: normal; font-size: 44px; }
.p3d-hand i:first-child { animation: p3d-out .01s .9s both; }
.p3d-hand i:last-child { animation: p3d-in .25s .9s both; }
.p3d-hand.right { transform: scaleX(-1); }
.p3d-hand.right i { transform: scaleX(-1); }
.p3d-stage b { font-size: 18px; color: #d92b3a; }
@keyframes p3d-shake { 50% { margin-top: -26px; } }
@keyframes p3d-out { to { opacity: 0; } }
@keyframes p3d-in { from { opacity: 0; transform: scale(.4); } to { opacity: 1; } }
.p3d-reveal { animation: p3d-in .35s 1.5s both; }
.p3d-reveal.fast { animation-delay: 1s; }
.p3d-panel button.p3d-cell.mark { animation: p3d-in .25s both; }
.p3d-panel button.p3d-cell.won { background: #ffd60a; border-color: #d9a900; color: #5b4636; animation: p3d-pulse .7s ease-in-out 3; }
@media (prefers-reduced-motion: reduce) { .p3d-coin, .p3d-hand, .p3d-hand i, .p3d-reveal, .p3d-panel button.p3d-cell.mark { animation: none; } .p3d-hand i:first-child { display: none; } }
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
  .p3d-zone span { font-size: 11px; }
  .p3d-tag { font-size: 11px; padding: 3px 8px 3px 6px; gap: 6px; }
  .p3d-here { top: 56px; font-size: 12px; padding: 6px 10px; }
  .p3d.walking .p3d-head { display: none; }
  .p3d.walking .p3d-legend { display: none; }
  .p3d-prompt { bottom: 84px; font-size: 14px; }
  .p3d-carnet { right: 10px; top: 98px; padding: 7px 11px; font-size: 12px; }
  .p3d-carnet.p3d-photo { top: 134px; }
  .p3d-carnet.p3d-hello { top: 170px; }
  .p3d-online { left: 10px; top: 98px; font-size: 11.5px; padding: 6px 10px; }
  .p3d.walking .p3d-toast { top: 134px; }
  .p3d-toast { top: 98px; font-size: 12.5px; max-width: calc(100% - 130px); left: 10px; transform: none; text-align: left; }
  .p3d-panel { top: 10px; transform: translateX(-50%); max-height: calc(100% - 106px); }
  .p3d-panel.side { left: 10px; right: 10px; top: auto; bottom: 94px; transform: none; width: auto; max-height: 48%; padding: 14px; }
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
  { name: "HANDICAPPED", label: "PMR", cap: 6, taken: 2, held: 0, reserved: 1, reservable: 1 },
  { name: "ELECTRIC", label: "Électrique", cap: 10, taken: 5, held: 0, reserved: 1, reservable: 2 },
  { name: "TWO_WHEELS", label: "Deux-roues", cap: 12, taken: 6, held: 0, reserved: 0, reservable: 0 },
  { name: "STANDARD", label: "Standard", cap: 38, taken: 19, held: 0, reserved: 3, reservable: 6 },
  { name: "XL", label: "Grand gabarit", cap: 8, taken: 3, held: 0, reserved: 1, reservable: 1 },
];

function liveZones(overview) {
  if (!overview || !overview.available || !Array.isArray(overview.categories)) return null;
  const zones = overview.categories
    .filter((c) => c.totalCapacity != null && c.totalCapacity > 0)
    .map((c) => ({
      name: String(c.name), label: String(c.label || c.name), cap: c.totalCapacity,
      taken: clamp(c.spotTaken || 0, 0, c.totalCapacity),
      held: clamp(c.spotHeld || 0, 0, c.totalCapacity),
      // Véhicules entrés avec une réservation (route publique de la borne).
      reserved: c.reserved != null ? clamp(c.reserved, 0, c.totalCapacity) : null,
      // Places encore réservables chez Booking pour l'heure en cours.
      reservable: c.reservable != null ? c.reservable : null,
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
  const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, coarse ? 1.5 : 2));
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
  const headTitle = elem("strong", null, opts.title || "Plan 3D du parking");
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
  const HINT_ORBIT = hint.textContent;
  const HINT_WALK = "ZQSD : marcher · Maj : courir · Espace : sauter · E : interagir · F : compagnon · 1-4 : saluer · C : carnet · P : photo · Échap : quitter";
  const HINT_DRIVE = "Z : accélérer · S : freiner, reculer · Q D : tourner · Espace : frein à main · H : klaxon · E : descendre · Échap : quitter";
  const speedo = elem("div", "p3d-card p3d-speed");
  const speedoValue = elem("b", null, "0");
  const speedoUnit = elem("span", null, "km/h");
  speedo.append(speedoValue, speedoUnit);
  const actBtn = elem("button", "p3d-act", "Sauter");
  actBtn.type = "button";
  const here = elem("div", "p3d-card p3d-here");
  const hereDot = elem("i");
  const hereName = elem("b");
  const hereCount = elem("span");
  here.append(hereDot, hereName, hereCount);
  const prompt = elem("button", "p3d-prompt");
  prompt.type = "button";
  const promptKey = elem("kbd", null, "E");
  const promptText = elem("span");
  prompt.append(promptKey, promptText);
  const panel = elem("div", "p3d-card p3d-panel");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Borne de réservation");
  const carnetBtn = elem("button", "p3d-carnet");
  carnetBtn.type = "button";
  carnetBtn.title = "Carnet de tampons : des choses à découvrir, du parking au village (C)";
  const carnetCount = elem("span");
  carnetBtn.append(document.createTextNode("★ Carnet"), carnetCount);
  const photoBtn = elem("button", "p3d-carnet p3d-photo", "◎ Photo");
  photoBtn.type = "button";
  photoBtn.title = "Photo souvenir (P)";
  const helloBtn = elem("button", "p3d-carnet p3d-hello", "♥ Coucou");
  helloBtn.type = "button";
  helloBtn.title = "Saluer les autres promeneurs (touches 1 à 4)";
  const onlineBox = elem("div", "p3d-card p3d-online");
  const onlineName = elem("b");
  const onlineCount = elem("span");
  onlineBox.append(elem("i"), onlineName, onlineCount);
  const toastBox = elem("div", "p3d-card p3d-toast");
  toastBox.setAttribute("role", "status");
  const joy = elem("div", "p3d-joy");
  const joyKnob = elem("i");
  joy.appendChild(joyKnob);
  // La pub du gros bouton rouge : calque de cinéma par-dessus le plan.
  const cine = elem("div", "p3d-cine");
  const cineSub = elem("p", "p3d-cine-sub");
  cineSub.setAttribute("aria-live", "polite");
  const cineSkip = elem("button", "p3d-cine-skip", "Passer la pub ▸");
  cineSkip.type = "button";
  const cineCard = elem("div", "p3d-cine-card");
  const cineLogo = document.createElement("canvas");
  cineLogo.width = cineLogo.height = 224;
  drawLogo(cineLogo.getContext("2d"), 0, 0, 224);
  cineCard.append(cineLogo, elem("b", null, "KingPar"), elem("span", null, "À la fin, l'amour gagne toujours."));
  cine.append(elem("span", "p3d-cine-badge", "PUB"), cineSkip, cineSub, cineCard);
  container.append(labelLayer, head, tools, legend, hint, here, prompt, joy, speedo, actBtn, carnetBtn, photoBtn, helloBtn, onlineBox, toastBox, panel, tip, cine);

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
  sky.material.userData.noBend = true;
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

  const cloudMat = new THREE.MeshLambertMaterial({ color: 0xffffff, transparent: true, fog: false }); // nuages tout ronds
  const clouds = new THREE.Group();
  {
    const rnd = mulberry(21);
    for (let i = 0; i < 9; i++) {
      const parts = [];
      const n = 3 + Math.floor(rnd() * 3);
      for (let k = 0; k < n; k++) {
        parts.push(part(new THREE.IcosahedronGeometry(6 + rnd() * 5, 3), "#fff", {
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
  // Pastille ronde aux bords doux : pétales de cerisier, étincelles du feu d'artifice.
  const dotTexture = canvasTexture(64, (ctx, w) => {
    const g = ctx.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.55, "rgba(255,255,255,.95)"); g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, w);
  });
  const M = {
    paint: new THREE.MeshStandardMaterial({ roughness: 0.34, metalness: 0.3, envMapIntensity: 1.1 }),
    detail: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.5, metalness: 0.25, envMapIntensity: 0.9 }),
    lights: new THREE.MeshBasicMaterial({ vertexColors: true, toneMapped: false }),
    props: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, metalness: 0.05, envMapIntensity: 0.5 }),
    asphalt: new THREE.MeshStandardMaterial({ map: noiseTexture(3, 214, 60), roughness: 0.96, metalness: 0, envMapIntensity: 0.35 }),
    road: new THREE.MeshStandardMaterial({ map: noiseTexture(5, 214, 46), roughness: 0.96, metalness: 0, envMapIntensity: 0.35 }),
    grass: new THREE.MeshStandardMaterial({ map: grassTexture(), roughness: 1, metalness: 0, envMapIntensity: 0.3 }),
    line: new THREE.MeshStandardMaterial({ color: 0xf2f3f5, roughness: 0.9, envMapIntensity: 0.3, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }),
    pad: new THREE.MeshStandardMaterial({ roughness: 0.95, transparent: true, opacity: 0.34, depthWrite: false, envMapIntensity: 0.2, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }),
    led: new THREE.MeshBasicMaterial({ toneMapped: false }),
    foliage: new THREE.MeshStandardMaterial({ roughness: 0.95, envMapIntensity: 0.3 }), // feuillages en boules lisses
    bulb: new THREE.MeshBasicMaterial({ color: 0x555a66, toneMapped: false }),
    pool: null,
    screen: new THREE.MeshBasicMaterial({ color: 0x64d7f0, toneMapped: false }),
    boothGlass: new THREE.MeshStandardMaterial({ color: 0x1b2836, roughness: 0.2, metalness: 0.4, emissive: 0xffc56b, emissiveIntensity: 0 }),
    post: new THREE.MeshStandardMaterial({ color: 0x2a2d38, roughness: 0.7 }),
    // Village : tuiles et pierre (teintées par instance), façades à volets bleus dont
    // les fenêtres s'éclairent la nuit, pétales des arbres en fleurs, guirlandes.
    roofTile: new THREE.MeshStandardMaterial({ roughness: 0.78, envMapIntensity: 0.35 }),
    roofSlab: new THREE.MeshStandardMaterial({ map: tileTexture(), roughness: 0.82, envMapIntensity: 0.3 }), // pans de toit en tuiles
    plaster: new THREE.MeshStandardMaterial({ color: 0xfff6e3, roughness: 0.92, envMapIntensity: 0.25 }), // pignons
    stone: new THREE.MeshStandardMaterial({ color: 0xb9b4a6, roughness: 0.95, envMapIntensity: 0.25 }),
    petal: new THREE.PointsMaterial({ color: 0xffc4d6, size: 0.55, sizeAttenuation: true, transparent: true, opacity: 0.95, depthWrite: false, map: dotTexture, alphaTest: 0.25 }),
    chochin: new THREE.MeshBasicMaterial({ color: 0xf2c14e, toneMapped: false }), // ampoules des guirlandes
    logo: new THREE.MeshBasicMaterial({ map: canvasTexture(256, (g, w) => drawLogo(g, 0, 0, w)), transparent: true, toneMapped: false }),
    soil: new THREE.MeshStandardMaterial({ color: 0x8f7355, roughness: 1, envMapIntensity: 0.2 }),
    hill: new THREE.MeshStandardMaterial({ color: 0x8fd97a, roughness: 1, envMapIntensity: 0.3 }),
    water: new THREE.MeshStandardMaterial({ color: 0x8fc7b8, roughness: 0.12, metalness: 0.3, envMapIntensity: 1.3 }),
    far: new THREE.MeshLambertMaterial({ fog: false }), // collines rondes au loin
    spark: new THREE.PointsMaterial({ size: 1.5, map: dotTexture, sizeAttenuation: true, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false, toneMapped: false }),
    koi: new THREE.MeshStandardMaterial({ color: 0xff7a1a, roughness: 0.5 }),
    house: (() => {
      const draw = (glow) => (ctx, w) => {
        const r = (x, y, rw, rh, c) => { ctx.fillStyle = c; ctx.fillRect(x * w, y * w, rw * w, rh * w); };
        if (glow) {
          r(0, 0, 1, 1, "#000000");
          r(0.16, 0.23, 0.24, 0.38, "#ffcf7a"); r(0.6, 0.23, 0.24, 0.38, "#ffcf7a");
          return;
        }
        r(0, 0, 1, 1, "#fff6e3"); // crépi crème (teinté par maison)
        r(0, 0.9, 1, 0.1, "#c9a27a"); // soubassement
        r(0, 0, 1, 0.07, "#b98a5e"); r(0, 0, 0.05, 1, "#b98a5e"); r(0.95, 0, 0.05, 1, "#b98a5e"); // poutres de bois
        [0.16, 0.6].forEach((x) => { // fenêtres à croisillons, cadre de bois, jardinière fleurie
          r(x - 0.03, 0.2, 0.3, 0.44, "#a8743f");
          r(x, 0.23, 0.24, 0.38, "#bfe3ff");
          r(x + 0.112, 0.23, 0.016, 0.38, "#a8743f"); r(x, 0.41, 0.24, 0.016, "#a8743f");
          r(x - 0.03, 0.64, 0.3, 0.05, "#8a5a3c");
          for (let k = 0; k < 5; k++) r(x - 0.012 + k * 0.057, 0.61, 0.036, 0.04, k % 2 ? "#ff7aa8" : "#ffd60a");
        });
      };
      return new THREE.MeshStandardMaterial({
        map: canvasTexture(256, draw(false)), emissiveMap: canvasTexture(256, draw(true)),
        emissive: 0xffffff, emissiveIntensity: 0, roughness: 0.9, envMapIntensity: 0.3,
      });
    })(),
    resa: new THREE.SpriteMaterial({
      map: canvasTexture(128, (ctx, s) => {
        ctx.fillStyle = "rgba(17,17,27,0.28)"; roundRect(ctx, 10, 14, s - 16, s - 16, 26); ctx.fill();
        ctx.fillStyle = "#1e66f5"; roundRect(ctx, 6, 6, s - 16, s - 16, 26); ctx.fill();
        ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 7; roundRect(ctx, 6, 6, s - 16, s - 16, 26); ctx.stroke();
        ctx.fillStyle = "#ffffff"; ctx.font = "800 " + s * 0.54 + "px system-ui, sans-serif";
        ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("R", s / 2 - 5, s / 2 - 1);
      }),
      depthWrite: false, toneMapped: false,
    }),
    trunk: new THREE.MeshStandardMaterial({ color: 0xb9824f, roughness: 0.9 }),
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
  const flat = (w, d) => new THREE.PlaneGeometry(w, d, seg(w), seg(d)).rotateX(-Math.PI / 2);

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
  // Nuit en thème sombre : `theme` imposé par la page, sinon celui du dashboard.
  let night = (opts.theme || document.documentElement.dataset.theme) === "mocha" ? 1 : 0;
  let nightGoal = night;
  let autoRotate = !reduceMotion;
  let idle = 0;
  let demoTimer = 2;
  const movers = [];
  const pops = [];
  const cam = { theta: -0.62, phi: 0.98, radius: 90, tx: 0, tz: 0, gTheta: -0.62, gPhi: 0.98, gRadius: 90, gx: 0, gz: 0, min: 14, max: 260, bx: 60, bz: 60 };

  // --- Promenade : un personnage et son chihuahua, vus à la troisième personne --------
  const walk = {
    on: false, x: SPAWN.x, z: SPAWN.z, rot: 0, speed: 0, phase: 0, still: 0,
    y: 0, vy: 0, // saut
    drive: null, look: 0, fov: 58, // véhicule conduit, dernière fois qu'on a tourné la caméra
    yaw: 0, pitch: 0.4, dist: 7.5, keys: {}, joy: null, near: null, zone: null, panel: false,
    say: 0, toast: 0, met: false, zoom: null,
    tuning: null, podium: null, // véhicule en cours de tuning ; véhicule resté sur le podium
    ad: null, // la pub en cours (gros bouton rouge)
    ride: null, hearts: 0, // voiture d'un autre promeneur où l'on est monté ; délai entre deux pluies de cœurs
    punch: 0, duelSig: "", duelDone: "", // coup de poing en cours, dernier défi affiché, dernier défi terminé
    game: null, parked: false, fuel: 0, saveIn: 20, // mini-jeu en cours, créneau jugé, pompe utilisée, sauvegarde // bulle du promeneur, message du carnet, accueil déjà affiché
    dog: { x: SPAWN.x + 0.9, z: SPAWN.z - 0.5, y: 0, vy: 0, rot: 0, phase: 0, speed: 0, bark: 0, next: 5, tx: null, tz: null, roam: 0 },
  };
  function limb(parts) {
    const mesh = new THREE.Mesh(merge(parts, true), M.props);
    mesh.castShadow = true;
    return mesh;
  }
  function pivot(parent, x, y, z, parts) {
    const g = new THREE.Group();
    g.position.set(x, y, z);
    g.add(limb(parts));
    parent.add(g);
    return g;
  }
  // Formes arrondies : gélule, sphère, tronc de cône.
  const caps = (r, len, color, t) => part(new THREE.CapsuleGeometry(r, len, 4, 10), color, t);
  const orb = (r, color, t) => part(new THREE.SphereGeometry(r, 16, 12), color, t);
  const tube = (r1, r2, len, color, t) => part(new THREE.CylinderGeometry(r1, r2, len, 16), color, t);
  const shade = (color, k) => "#" + new THREE.Color(color).multiplyScalar(k).getHexString();
  /* Un personnage : buste, bassin, cou, tête ovale avec un vrai visage (yeux,
     sourcils, nez, bouche, oreilles), bras et jambes arrondis, mains,
     chaussures. Les cheveux sont des volumes posés sur le crâne : chaque coupe
     se reconnaît de face comme de dos. */
  function buildPerson(c) {
    const root = new THREE.Group(), body = new THREE.Group();
    root.add(body);
    const hat = c.cap ? "cap" : c.hat || "none", cut = c.cut || "short", h = c.hair;
    const fit = c.outfit || "tshirt", low = fit === "robe" ? "robe" : c.bottom || "pants";
    const bare = !["cap", "straw", "bonnet"].includes(hat), longSleeve = ["pull", "chemise", "veste", "hoodie"].includes(fit) || Boolean(c.sleeve);
    const gold = "#d4af37", cream = "#fdf6e3", dark = shade(c.top, 0.72), tilt = -0.17, NECK = 0.78;
    const rAt = (y) => 0.235 - ((y - 0.35) / 0.42) * 0.085; // rayon du buste en cloche à la hauteur y
    // Le corps : petit, en cloche, sans cou — toute la place est pour la tête.
    const t = [orb(0.2, low === "robe" ? c.top : c.pants, { y: 0.38, sy: 0.55, sz: 0.85 })];
    if (fit === "robe") t.push(tube(0.15, 0.3, 0.56, c.top, { y: 0.5, sz: 0.85 }));
    else t.push(tube(0.15, 0.235, 0.42, c.top, { y: 0.56, sz: 0.85 }), tube(0.236, 0.24, 0.035, c.hem || dark, { y: 0.36, sz: 0.85 }));
    t.push(orb(0.15, c.top, { y: 0.77, sy: 0.45, sz: 0.85 }));
    const front = (y) => rAt(y) * 0.85 + 0.008;
    if (fit === "pull") t.push(tube(0.13, 0.15, 0.05, dark, { y: 0.785, sz: 0.85 }));
    if (fit === "chemise") {
      [-1, 1].forEach((sx) => t.push(box(0.075, 0.045, 0.03, cream, { x: sx * 0.045, y: 0.775, z: 0.12, rz: sx * 0.5 })));
      t.push(box(0.014, 0.32, 0.012, cream, { y: 0.57, z: front(0.57), rx: tilt }));
      [0.68, 0.57, 0.46].forEach((y) => t.push(orb(0.011, "#22252e", { y, z: front(y) + 0.004 })));
    }
    if (fit === "veste") {
      t.push(box(0.09, 0.36, 0.014, cream, { y: 0.58, z: front(0.58), rx: tilt }));
      [-1, 1].forEach((sx) => t.push(box(0.045, 0.26, 0.018, dark, { x: sx * 0.062, y: 0.64, z: front(0.64) + 0.004, rz: -sx * 0.2, rx: tilt })));
    }
    if (fit === "hoodie") {
      t.push(orb(0.17, c.top, { y: 0.8, z: -0.13, sy: 0.6 }));
      t.push(box(0.2, 0.09, 0.02, dark, { y: 0.47, z: front(0.47), rx: tilt }));
      [-1, 1].forEach((sx) => t.push(box(0.012, 0.12, 0.012, cream, { x: sx * 0.04, y: 0.7, z: front(0.7) + 0.004, rx: tilt })));
    }
    if (fit === "salopette") {
      t.push(tube(0.2, 0.238, 0.16, c.pants, { y: 0.43, sz: 0.86 }));
      t.push(box(0.17, 0.16, 0.014, c.pants, { y: 0.6, z: front(0.6), rx: tilt }));
      [-1, 1].forEach((sx) => {
        t.push(box(0.035, 0.14, 0.016, c.pants, { x: sx * 0.07, y: 0.72, z: front(0.72), rx: tilt }));
        t.push(orb(0.014, gold, { x: sx * 0.07, y: 0.66, z: front(0.66) + 0.008 }));
      });
    }
    if (fit === "maillot") { // l'écusson : une petite couronne dorée
      t.push(box(0.09, 0.02, 0.012, gold, { y: 0.6, z: front(0.6) + 0.002 }));
      [-0.03, 0, 0.03].forEach((x) => t.push(part(new THREE.ConeGeometry(0.016, 0.05, 4), gold, { x, y: 0.635, z: front(0.63) })));
      t.push(tube(rAt(0.44) + 0.004, rAt(0.4) + 0.004, 0.03, cream, { y: 0.42, sz: 0.85 }));
    }
    if (low === "jupe") t.push(tube(0.2, 0.3, 0.2, c.pants, { y: 0.36, sz: 0.85 }));
    if (c.extra === "echarpe") {
      t.push(tube(0.165, 0.175, 0.07, BRAND, { y: 0.79, sz: 0.9 }));
      t.push(box(0.075, 0.22, 0.03, BRAND, { x: 0.07, y: 0.66, z: front(0.66) + 0.01, rx: tilt }));
    }
    if (c.pack) {
      t.push(box(0.26, 0.3, 0.12, c.pack, { y: 0.58, z: -0.22 }));
      t.push(orb(0.13, c.pack, { y: 0.73, z: -0.22, sy: 0.5, sz: 0.46 }));
    }
    if (c.vest) [0.48, 0.64].forEach((y) => t.push(tube(rAt(y + 0.02) + 0.006, rAt(y - 0.02) + 0.006, 0.045, "#d5d8de", { y, sz: 0.85 }))); // bandes réfléchissantes
    body.add(limb(t));
    /* La tête : une grosse boule un peu aplatie, avec le visage peint dessus.
       Les cheveux et les chapeaux sont dessinés à l'échelle d'une petite tête,
       puis agrandis d'un bloc autour d'elle. */
    const neck = new THREE.Group();
    neck.position.y = NECK;
    body.add(neck);
    const faceOf = (closed) => canvasTexture(c.small ? 256 : 512, (g, w, hh) => drawFace(g, w, hh, {
      skin: c.skin, brow: shade(h, 0.7), nose: shade(c.skin, 0.8), eyes: c.eyes, extra: c.extra,
    }, closed), c.small ? 128 : 256);
    const faces = [faceOf(false)].concat(c.small ? [] : [faceOf(true)]);
    const headMat = new THREE.MeshStandardMaterial({ map: faces[0], emissiveMap: faces[0], emissive: 0xffffff, emissiveIntensity: 0.2, roughness: 0.86, metalness: 0, envMapIntensity: 0.25 });
    const headMesh = new THREE.Mesh(new THREE.SphereGeometry(0.36, 36, 26), headMat);
    headMesh.scale.set(1, 0.92, 0.98);
    headMesh.position.y = 1.1 - NECK;
    headMesh.castShadow = true;
    headMesh.userData.own = faces; // textures à libérer avec le modèle
    neck.add(headMesh);
    const parts = [];
    [-1, 1].forEach((sx) => parts.push(orb(0.03, c.skin, { x: sx * 0.152, y: 1.59, sy: 1.3, sz: 0.7 }))); // oreilles
    const scalp = () => parts.push(orb(0.168, h, { y: 1.64, z: -0.03 }));
    const fringe = () => { if (bare) parts.push(orb(0.078, h, { y: 1.728, z: 0.082, sx: 1.75, sy: 0.5, rx: 0.5 })); };
    if (cut === "mohawk") {
      parts.push(orb(0.158, shade(c.skin, 0.82), { y: 1.63, z: -0.02 })); // tempes rasées
      if (bare) for (let k = 0; k < 6; k++) {
        parts.push(part(new THREE.ConeGeometry(0.042, 0.22, 6), h, { y: 1.84 - k * k * 0.006, z: 0.1 - k * 0.048, rx: 0.3 - k * 0.13 }));
      }
    } else if (cut === "afro") {
      if (bare) parts.push(orb(0.225, h, { y: 1.73, z: -0.07 }));
      else { scalp(); [-1, 1].forEach((sx) => parts.push(orb(0.11, h, { x: sx * 0.17, y: 1.6, z: -0.05 }))); }
    } else {
      scalp();
      if (["short", "bob", "tail", "twin", "tresses"].includes(cut)) fringe();
      if (cut === "bol" && bare) {
        parts.push(orb(0.184, h, { y: 1.665, z: -0.012, sy: 0.72 }));
        parts.push(orb(0.1, h, { y: 1.712, z: 0.075, sx: 1.6, sy: 0.42 }));
      }
      if (cut === "banane" && bare) parts.push(orb(0.09, h, { y: 1.79, z: 0.085, sx: 1.25, sy: 0.75, rx: -0.4 }));
      if (cut === "tresses") [-1, 1].forEach((sx) => {
        [1.56, 1.47, 1.39].forEach((y, k) => parts.push(orb(0.042 - k * 0.004, h, { x: sx * (0.185 + k * 0.012), y })));
        parts.push(orb(0.026, BRAND, { x: sx * 0.212, y: 1.335 }));
      });
      if (cut === "piques" && bare) for (let k = 0; k < 9; k++) {
        const a = (k / 9) * Math.PI * 2, out = k % 2 ? 0.5 : 0.85;
        parts.push(part(new THREE.ConeGeometry(0.05, 0.16, 6), h, { x: Math.sin(a) * 0.1, y: 1.8, z: Math.cos(a) * 0.1 - 0.03, rx: Math.cos(a) * out, rz: -Math.sin(a) * out }));
      }
      if (cut === "boucles") for (let k = 0; k < 12; k++) {
        const a = (k / 12) * Math.PI * 2, up = bare && k % 2 === 0;
        parts.push(orb(0.062, h, { x: Math.sin(a) * (up ? 0.1 : 0.155), y: up ? 1.79 : 1.66 - Math.abs(Math.cos(a)) * 0.05, z: Math.cos(a) * (up ? 0.1 : 0.15) - 0.04 - (Math.cos(a) > 0.5 ? 0.12 : 0) }));
      }
      if (cut === "bob") parts.push(orb(0.185, h, { y: 1.57, z: -0.05, sy: 0.85 }));
      if (cut === "long") {
        parts.push(tube(0.15, 0.17, 0.3, h, { y: 1.5, z: -0.085, sz: 0.55 }));
        [-1, 1].forEach((sx) => parts.push(caps(0.04, 0.16, h, { x: sx * 0.155, y: 1.5, z: 0.02 })));
      }
      if (cut === "bun") parts.push(orb(0.085, h, bare ? { y: 1.82, z: -0.07 } : { y: 1.6, z: -0.2 }));
      if (cut === "tail") {
        parts.push(orb(0.04, BRAND, { y: 1.7, z: -0.17 })); // l'élastique
        parts.push(caps(0.045, 0.18, h, { y: 1.56, z: -0.23, rx: -0.3 }));
      }
      if (cut === "twin") [-1, 1].forEach((sx) => {
        parts.push(orb(0.035, BRAND, { x: sx * 0.165, y: 1.66 }));
        parts.push(caps(0.045, 0.15, h, { x: sx * 0.215, y: 1.55, rz: sx * 0.3 }));
      });
    }
    if (hat === "cap") {
      const color = c.cap || BRAND;
      parts.push(orb(0.178, color, { y: 1.72, sy: 0.75 }));
      parts.push(orb(0.11, color, { y: 1.705, z: 0.19, sy: 0.12, sz: 1.1, rx: 0.12 })); // visière
    } else if (hat === "straw") {
      parts.push(tube(0.34, 0.34, 0.022, "#e8cf8a", { y: 1.715 }));
      parts.push(tube(0.17, 0.186, 0.12, "#e8cf8a", { y: 1.785 }));
      parts.push(tube(0.188, 0.188, 0.036, BRAND, { y: 1.745 }));
    } else if (hat === "bonnet") {
      parts.push(orb(0.18, c.top, { y: 1.69, sy: 0.82 }));
      parts.push(tube(0.176, 0.176, 0.05, dark, { y: 1.675 }));
      parts.push(orb(0.05, cream, { y: 1.855 }));
    } else if (hat === "beret") {
      parts.push(orb(0.2, "#22252e", { x: 0.02, y: 1.775, z: -0.02, sy: 0.3 }));
      parts.push(tube(0.01, 0.01, 0.04, "#22252e", { y: 1.84 }));
    } else if (hat === "couronne") {
      parts.push(tube(0.115, 0.115, 0.05, gold, { y: 1.8 }));
      for (let k = 0; k < 6; k++) {
        const a = (k / 6) * Math.PI * 2;
        parts.push(part(new THREE.ConeGeometry(0.028, 0.08, 4), gold, { x: Math.sin(a) * 0.105, y: 1.86, z: Math.cos(a) * 0.105 }));
        parts.push(orb(0.013, k % 2 ? BRAND : "#d92b3a", { x: Math.sin(a) * 0.117, y: 1.8, z: Math.cos(a) * 0.117 }));
      }
    }
    const BIG = 2.32, FLAT = 0.86; // de la petite tête de travail (centre y = 1,6) à la grosse
    const hairG = new THREE.Group();
    hairG.scale.set(BIG, BIG * FLAT, BIG);
    hairG.position.y = 1.1 - NECK - 1.6 * BIG * FLAT;
    hairG.add(limb(parts));
    neck.add(hairG);
    const bareLeg = low !== "pants";
    const leg = () => [caps(0.085, 0.13, bareLeg ? c.skin : c.pants, { y: -0.14 }), orb(0.105, c.shoes, { y: -0.285, z: 0.035, sy: 0.55, sz: 1.35 })];
    const arm = () => [caps(0.062, 0.1, c.sleeve || c.top, { y: -0.09 }), caps(0.056, 0.08, longSleeve ? c.sleeve || c.top : c.skin, { y: -0.21 }), orb(0.072, c.skin, { y: -0.31 })];
    const person = {
      root, body, head: neck,
      legL: pivot(body, -0.1, 0.34, 0, leg()), legR: pivot(body, 0.1, 0.34, 0, leg()),
      armL: pivot(body, -0.19, 0.72, 0, arm()), armR: pivot(body, 0.19, 0.72, 0, arm()),
      blink(closed) { if (faces[1]) headMat.map = headMat.emissiveMap = faces[closed ? 1 : 0]; },
    };
    person.armL.rotation.z = -0.38; person.armR.rotation.z = 0.38; // bras un peu écartés
    if (c.balloon && c.balloon !== "none") { // un ballon KingPar, tenu au bout de sa ficelle
      const bg = new THREE.Group();
      bg.position.set(0.36, 0.42, 0.04);
      bg.add(limb([
        cyl(0.006, 1.35, cream, { y: 0.675 }, 5), orb(0.24, c.balloon, { y: 1.62, sy: 1.18 }),
        part(new THREE.ConeGeometry(0.03, 0.05, 6), c.balloon, { y: 1.33 }),
      ]));
      [0, Math.PI].forEach((ry) => {
        const badge = new THREE.Mesh(new THREE.PlaneGeometry(0.22, 0.22), M.logo);
        badge.position.set(0, 1.64, ry ? -0.243 : 0.243);
        badge.rotation.y = ry;
        bg.add(badge);
      });
      root.add(bg);
      person.balloon = bg;
    }
    return person;
  }
  // Libère un modèle : géométries, et textures de visage qui lui sont propres.
  function disposeModel(group) {
    group.traverse((node) => {
      if (node.geometry) node.geometry.dispose();
      if (node.userData && node.userData.own) { node.userData.own.forEach((tex) => tex.dispose()); node.material.dispose(); }
    });
  }
  // Le promeneur : sa tenue se choisit dans les boutiques du village (voir `openShop`).
  const look = loadLook();
  const progress = loadProgress();
  const carnet = progress.stamps;
  function saveProgress() {
    store(CARNET_KEY, {
      stamps: Array.from(progress.stamps), wins: Array.from(progress.wins), best: progress.best,
      km: Math.round(progress.km * 1000) / 1000, jumps: progress.jumps,
      pets: progress.pets, cuts: progress.cuts, played: progress.played, fits: progress.fits, cars: progress.cars, tuned: progress.tuned, day: progress.day,
      walked: Math.round(progress.walked), hellos: progress.hellos,
      quests: progress.quests, qn: progress.qn, qcut: progress.qcut, duelWins: progress.duelWins, bag: progress.bag,
      gold: progress.gold, goldDay: progress.goldDay,
    });
  }
  let bareHead = false; // chez le coiffeur, le chapeau se pose le temps de la coupe
  const playerLook = () => ({
    top: look.top, hem: shade(look.top, 0.72), skin: look.skin, hair: look.hair,
    pants: look.pants, shoes: "#f4f5f7", pack: look.pack ? "#f2b01e" : null, hat: bareHead ? "none" : look.hat, cut: look.cut,
    outfit: look.outfit, bottom: look.bottom, extra: look.extra, balloon: look.balloon, eyes: look.eyes,
  });
  const player = buildPerson(playerLook());
  // Remplace un modèle (promeneur, compagnon) sans changer l'objet que tout le monde tient.
  function swapModel(holder, next) {
    const parent = holder.root.parent;
    next.root.position.copy(holder.root.position);
    next.root.rotation.copy(holder.root.rotation);
    next.root.visible = holder.root.visible;
    disposeModel(holder.root);
    holder.root.removeFromParent();
    Object.assign(holder, next);
    if (parent) parent.add(holder.root);
  }
  // L'agent du parking : gilet jaune, casquette, et sa propre volonté (voir `stepAgent`).
  const agent = buildPerson({ top: "#ffd60a", sleeve: "#1f2a44", skin: "#e8b88f", hair: "#2b2018", pants: "#1f2a44", shoes: "#15161a", cap: "#1f2a44", vest: true });
  const npc = { x: LANE + 0.35, z: 6, rot: 0, phase: 0, speed: 0, path: null, s: 0, wait: 2, say: 0, greet: 0, target: null, hold: 0 };
  const AGENT_SAYS = {
    inspect: ["Bien garé.", "Rien à signaler.", "Hmm…", "Tout est en ordre.", "Jolie voiture.", "Ticket en règle."],
    moto: ["Belle bécane.", "Antivol bien mis."],
    pause: ["Petite pause.", "Un café, et j'y retourne."],
    hello: ["Bonjour !", "Bonne journée !", "Besoin d'aide ?", "Bienvenue au parking."],
    dog: ["Qu'il est mignon !", "Il est sage, au moins ?", "Tenu en laisse, hein ?"],
    guide: ["Par ici, votre place vous attend.", "Une arrivée ! J'y vais."],
    full: ["C'est complet par ici."],
    calm: ["Quel calme…", "Belle journée."],
  };
  // Le compagnon : chihuahua par défaut, à changer à l'animalerie du village.
  function buildPet(kind) {
    const p = PETS[kind] || PETS.chihuahua;
    const root = new THREE.Group(), body = new THREE.Group();
    root.add(body);
    root.scale.setScalar(p.scale);
    const legColor = p.legs || p.fur, e = p.ears, eye = p.eye || "#15161a";
    const torso = [caps(p.wool ? 0.135 : 0.098, p.wool ? 0.1 : 0.13, p.wool || p.fur, { y: 0.25, rx: Math.PI / 2 })];
    if (p.shell) torso.push(orb(0.15, p.shell, { y: 0.3, sy: 0.75, sz: 1.2 }));
    if (p.collar) torso.push(tube(0.078, 0.078, 0.035, p.collar, { y: 0.27, z: 0.15, rx: Math.PI / 2 }));
    if (p.chest) torso.push(orb(0.07, p.muzzle, { y: 0.22, z: 0.13 }));
    if (p.beak) [-1, 1].forEach((sx) => torso.push(orb(0.07, p.ear, { x: sx * 0.085, y: 0.27, sx: 0.35, sz: 1.5 }))); // ailes
    body.add(limb(torso));
    const head = [orb(0.1, p.fur, { y: 0.07, z: 0.05 })];
    if (p.beak) head.push(orb(0.045, p.beak, { y: 0.045, z: 0.16, sy: 0.45, sz: 1.3 }));
    else {
      head.push(orb(0.052, p.muzzle, { y: 0.035, z: 0.13, sz: 1.25 }));
      head.push(orb(0.02, p.snout || "#15161a", p.snout ? { y: 0.04, z: 0.19, sx: 1.7, sy: 1.3 } : { y: 0.055, z: 0.19 }));
    }
    [-1, 1].forEach((sx) => {
      if (p.patch) head.push(orb(0.032, p.patch, { x: sx * 0.045, y: 0.095, z: 0.122, sz: 0.5 }));
      head.push(orb(0.024, eye, { x: sx * 0.047, y: 0.1, z: 0.132, sy: 1.2, sz: 0.55 }));
      head.push(orb(0.009, "#ffffff", { x: sx * 0.041, y: 0.11, z: 0.147 })); // reflet
      head.push(orb(0.02, "#ff9db0", { x: sx * 0.078, y: 0.062, z: 0.116, sy: 0.6, sz: 0.3 })); // joue
      if (e[0] === "cone") head.push(part(new THREE.ConeGeometry(e[1], e[2], 8), p.ear, { x: sx * e[4], y: 0.13 + e[2] / 2, z: 0.03, rz: -sx * e[3], sz: 0.5 }));
      else if (e[0] === "long") head.push(caps(e[1], e[2], p.ear, { x: sx * e[4], y: 0.15 + e[2] / 2, z: 0.02, rz: -sx * e[3] }));
      else if (e[0] === "round") head.push(orb(e[1], p.ear, { x: sx * e[4], y: 0.15, z: 0.03, sz: 0.5 }));
      else if (e[0] === "flop") head.push(orb(e[1], p.ear, { x: sx * e[4], y: 0.08, z: 0.04, sx: 0.45, sy: 1.5 }));
    });
    const headG = pivot(body, 0, 0.34, 0.16, head);
    headG.scale.setScalar(1.42); // grosse tête, comme les promeneurs
    const paw = () => [caps(0.034, 0.08, legColor, { y: -0.07 }), orb(0.038, legColor, { y: -0.145, z: 0.01, sy: 0.6 })];
    const spots = p.beak ? [[-0.045, 0], [0.045, 0]] : [[-0.055, 0.12], [0.055, 0.12], [-0.055, -0.12], [0.055, -0.12]];
    const made = spots.map((sp) => pivot(body, sp[0], 0.17, sp[1], paw()));
    const legs = p.beak ? [made[0], made[1], made[1], made[0]] : made; // deux pattes pour le canard
    const t = p.tail, tailParts = [caps(t[2], t[0], p.fur, { y: t[0] / 2 + t[2] })];
    if (p.tip) tailParts.push(orb(t[2] * 1.15, p.tip, { y: t[0] + t[2] }));
    const tail = pivot(body, 0, 0.3, -0.19, tailParts);
    tail.rotation.x = t[1];
    return {
      root, body, head: headG, legs, tail, kind: PETS[kind] ? kind : "chihuahua", def: p,
      wag: p.wag == null ? 0.65 : p.wag, top: (0.56 + (e[0] === "cone" || e[0] === "long" ? e[2] : 0.05)) * Math.min(p.scale, 1.5),
    };
  }
  const dog = buildPet(look.pet);

  // Véhicules en libre-service : un groupe par véhicule (hors flotte instanciée).
  // Autocollants : une texture par motif, partagée par tous les véhicules.
  const stickerMats = {};
  function stickerMat(id) {
    if (!stickerMats[id]) {
      stickerMats[id] = new THREE.MeshStandardMaterial({
        map: canvasTexture(256, (g, w) => drawSticker(g, w, id)), transparent: true, alphaTest: 0.04, roughness: 0.55, metalness: 0.05,
        envMapIntensity: 0.5, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
      });
    }
    return stickerMats[id];
  }
  /* Un véhicule à conduire. Avec un réglage de tuning (`tune`, voir `cleanTune`),
     on repeint, on change jantes et pneus, on colle, on monte les accessoires :
     les pièces s'ajoutent au modèle avant la fusion en trois maillages. */
  function buildCar(model, color, tune) {
    const built = MODELS[model].build(), fit = built.fit, t = tune || null;
    const root = new THREE.Group(), body = new THREE.Group();
    root.add(body);
    const paintMat = M.paint.clone();
    paintMat.color.set(t ? t.paint : color);
    const extras = [];
    if (t && fit) {
      const finish = { mat: [0.88, 0.04, 0.3], metal: [0.2, 0.78, 1.5], nacre: [0.24, 0.42, 1.35] }[t.finish];
      if (finish) { paintMat.roughness = finish[0]; paintMat.metalness = finish[1]; paintMat.envMapIntensity = finish[2]; }
      // Nacrée : un reflet à peine décalé vers la teinte voisine, pour que la couleur choisie reste la même.
      if (t.finish === "nacre") { paintMat.emissive.set(t.paint).offsetHSL(0.035, 0, 0.06); paintMat.emissiveIntensity = 0.13; }
      const P = built.paint, D = built.detail, quarter = Math.PI / 2, dark = "#101114";
      const recolor = (from, to) => D.forEach((pt) => { if (pt.color === from) pt.color = to; });
      if (TINTS[t.tint] && t.tint !== "serie") recolor(GLASS, TINTS[t.tint][1]);
      // Roues : pneu, flanc, puis jante, en couches de plus en plus saillantes.
      const cross = t.tyres === "cross", custom = t.rims !== "serie";
      recolor(HUB, custom ? dark : t.rimc);
      built.spots.forEach((sp) => {
        const r = sp.r, face = (sp.w / 2) * (cross ? 1.14 : 1);
        if (cross) {
          D.push(cyl(r * 1.1, sp.w * 1.14, TIRE, { x: sp.x, y: sp.y, z: sp.z, rz: quarter }, 20));
          for (let k = 0; k < 12; k++) {
            const a = (k / 12) * Math.PI * 2;
            D.push(box(sp.w * 1.14 + 0.03, 0.07, 0.1, TIRE, { x: sp.x, y: sp.y + Math.cos(a) * r * 1.1, z: sp.z + Math.sin(a) * r * 1.1, rx: a }));
          }
        }
        (sp.sx ? [sp.sx] : [-1, 1]).forEach((f) => {
          const at = (out) => sp.x + f * (face + out);
          const disc = (radius, thick, out, color) => D.push(cyl(radius, thick, color, { x: at(out), y: sp.y, z: sp.z, rz: quarter }, 20));
          if (t.tyres === "blanc") { disc(r * 0.88, 0.012, 0, "#f4f5f7"); disc(r * 0.68, 0.02, 0, TIRE); }
          if (t.tyres === "sport") { disc(r * 0.8, 0.012, 0, "#d92b3a"); disc(r * 0.72, 0.02, 0, TIRE); }
          if (!custom) { if (cross) disc(r * 0.56, 0.05, 0.005, t.rimc); return; }
          disc(r * 0.74, 0.04, 0, dark);
          D.push(part(new THREE.TorusGeometry(r * 0.71, 0.024, 6, 22), t.rimc, { x: at(0.022), y: sp.y, z: sp.z, ry: quarter }));
          if (t.rims === "plein") {
            disc(r * 0.68, 0.056, 0, t.rimc);
            for (let k = 0; k < 5; k++) {
              const a = (k / 5) * Math.PI * 2;
              D.push(cyl(r * 0.1, 0.064, dark, { x: at(0), y: sp.y + Math.cos(a) * r * 0.42, z: sp.z + Math.sin(a) * r * 0.42, rz: quarter }, 10));
            }
            disc(r * 0.14, 0.076, 0, dark);
          } else {
            const n = t.rims === "etoile" ? 5 : 10, wide = t.rims === "etoile" ? r * 0.2 : r * 0.07;
            for (let k = 0; k < n; k++) {
              const a = (k / n) * Math.PI * 2;
              D.push(box(0.03, r * 0.66, wide, t.rimc, { x: at(0.03), y: sp.y + Math.cos(a) * r * 0.36, z: sp.z + Math.sin(a) * r * 0.36, rx: a }));
            }
            disc(r * 0.17, 0.1, 0, t.rimc);
          }
        });
      });
      if (cross) body.position.y = Math.max.apply(null, built.spots.map((sp) => sp.r)) * 0.1; // garde au sol relevée
      // Bandes de course : capot, toit, coffre.
      const lanes = t.stripes === "double" ? [-0.21, 0.21] : t.stripes === "simple" ? [0] : [];
      lanes.forEach((x) => [fit.hood, fit.roof, fit.trunk].forEach((sg) => {
        if (!sg) return;
        const len = Math.hypot(sg[0][0] - sg[1][0], sg[0][1] - sg[1][1]);
        D.push(box(t.stripes === "simple" ? 0.36 : 0.15, 0.014, len * 0.97, t.stripec, {
          x, y: (sg[0][1] + sg[1][1]) / 2 + 0.004, z: (sg[0][0] + sg[1][0]) / 2, rx: Math.atan2(sg[1][1] - sg[0][1], sg[0][0] - sg[1][0]),
        }));
      }));
      if (t.addon === "aileron" && fit.wing) {
        const wz = fit.wing[0], wy = fit.wing[1];
        P.push(box(fit.W * 0.94, 0.045, 0.34, "#ffffff", { y: wy + 0.25, z: wz, rx: -0.12 }));
        [-1, 1].forEach((sx) => {
          P.push(box(0.03, 0.16, 0.42, "#ffffff", { x: sx * fit.W * 0.47, y: wy + 0.26, z: wz }));
          D.push(box(0.05, 0.28, 0.12, TRIM, { x: sx * fit.W * 0.28, y: wy + 0.1, z: wz }));
        });
      }
      if (t.addon === "galerie" && fit.roof) {
        const z0 = fit.roof[0][0], z1 = fit.roof[1][0], ry = fit.roof[0][1], long = Math.abs(z0 - z1);
        const half = Math.min(fit.W / 2 - 0.3, 0.62), len = Math.min(1.9, long * 0.9), zc = (z0 + z1) / 2 + (long > 3 ? 1.2 : 0);
        [-1, 1].forEach((sx) => {
          D.push(box(0.04, 0.04, len, TRIM, { x: sx * half, y: ry + 0.1, z: zc }));
          [-0.4, 0.4].forEach((k) => D.push(box(0.04, 0.1, 0.04, TRIM, { x: sx * half, y: ry + 0.05, z: zc + k * len })));
        });
        [-0.42, 0, 0.42].forEach((k) => D.push(box(half * 2, 0.035, 0.05, TRIM, { y: ry + 0.1, z: zc + k * len })));
        D.push(box(half * 1.05, 0.24, len * 0.42, "#8a5a3c", { x: -half * 0.38, y: ry + 0.24, z: zc + len * 0.22 }));
        [-0.1, 0.1].forEach((k) => D.push(box(half * 1.07, 0.25, 0.03, "#3b2a20", { x: -half * 0.38, y: ry + 0.24, z: zc + len * (0.22 + k) })));
        D.push(box(half * 0.85, 0.18, len * 0.36, BRAND, { x: half * 0.42, y: ry + 0.21, z: zc - len * 0.24 }));
        D.push(cyl(0.085, half * 1.5, "#f6a5c0", { y: ry + 0.2, z: zc - len * 0.02, rz: quarter }, 10));
      }
      if (t.addon === "fanion" && fit.mast) {
        const m = fit.mast;
        D.push(cyl(0.014, 0.95, "#d5d8de", { x: m[0], y: m[1] + 0.47, z: m[2] }, 6));
        D.push(ball(0.03, "#ffd60a", { x: m[0], y: m[1] + 0.96, z: m[2] }));
        D.push(box(0.012, 0.25, 0.36, BRAND, { x: m[0], y: m[1] + 0.8, z: m[2] - 0.19 }));
        [-1, 1].forEach((sx) => {
          const badge = new THREE.Mesh(new THREE.PlaneGeometry(0.21, 0.21), M.logo);
          badge.position.set(m[0] + sx * 0.008, m[1] + 0.8, m[2] - 0.19);
          badge.rotation.y = (sx * Math.PI) / 2;
          extras.push(badge);
        });
      }
      if (t.sticker !== "none") {
        const mat = stickerMat(t.sticker), d = fit.door;
        [-1, 1].forEach((sx) => {
          const side = new THREE.Mesh(new THREE.PlaneGeometry(d[2], d[2]), mat);
          side.position.set(sx * fit.side, d[0], d[1]);
          side.rotation.y = (sx * Math.PI) / 2;
          extras.push(side);
        });
        if (fit.hood) {
          const h = fit.hood, size = Math.min(0.62, Math.hypot(h[0][0] - h[1][0], h[0][1] - h[1][1]) * 0.55);
          const top = new THREE.Mesh(new THREE.PlaneGeometry(size, size), mat);
          top.position.set(0, (h[0][1] + h[1][1]) / 2 + 0.014, (h[0][0] + h[1][0]) / 2);
          top.rotation.x = -Math.PI / 2 + Math.atan2(h[1][1] - h[0][1], h[0][0] - h[1][0]);
          extras.push(top);
        }
      }
      const glow = NEONS[t.neon] ? NEONS[t.neon][1] : null;
      if (glow) { // néon sous la caisse : deux tubes et leur halo au sol
        const thin = fit.W < 1;
        [-1, 1].forEach((sx) => built.lights.push(box(0.05, 0.04, fit.len * (thin ? 0.4 : 0.6), glow, { x: sx * (thin ? 0.13 : fit.W / 2 - 0.06), y: 0.24 })));
        const halo = new THREE.Mesh(new THREE.PlaneGeometry(fit.W + 1.5, fit.len + 1.5), new THREE.MeshBasicMaterial({
          map: dotTexture, color: glow, transparent: true, opacity: 0.78, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
        }));
        halo.rotation.x = -Math.PI / 2;
        halo.position.y = 0.17;
        halo.userData.own = []; // sa matière lui est propre : libérée avec le modèle
        root.add(halo);
      }
    }
    [[built.paint, false, paintMat], [built.detail, true, M.detail], [built.lights, true, M.lights]].forEach((part, i) => {
      const mesh = new THREE.Mesh(merge(part[0], part[1]), part[2]);
      mesh.castShadow = i < 2;
      mesh.receiveShadow = i < 2;
      if (i === 0) mesh.userData.own = []; // la peinture est une matière clonée, propre au véhicule
      body.add(mesh);
    });
    extras.forEach((mesh) => body.add(mesh));
    return { root, body, paintMat, tune: t };
  }
  const garage = loadGarage(); // le tuning de chaque véhicule, gardé sur l'appareil
  const rentals = RENTALS.map((def) => Object.assign(buildCar(def.model, def.color, garage[def.model]), { def, x: def.x, z: RENTAL_Z, rot: Math.PI, v: 0, steer: 0 }));
  // Phares du véhicule conduit, la nuit.
  const driveLight = new THREE.PointLight(0xfff2c2, 0, 34, 1.5);

  // --- Construction du parking -------------------------------------------------------
  function displayZones(zones) {
    const total = zones.reduce((s, z) => s + z.cap, 0);
    const unit = total > MAX_SPOTS ? total / MAX_SPOTS : 1;
    return {
      unit,
      zones: zones.map((z) => {
        const n = Math.max(1, Math.round(z.cap / unit));
        const scale = (v) => (v > 0 ? clamp(Math.round(v / unit) || 1, 0, n) : 0);
        return Object.assign({}, z, { n, takenN: scale(z.taken), heldN: scale(z.held), reservedN: scale(z.reserved || 0) });
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
      lot.group.remove(player.root, dog.root, agent.root, driveLight); // gardés d'un plan à l'autre
      rentals.forEach((r) => lot.group.remove(r.root));
      disposeTree(lot.group);
      lot.textures.forEach((t) => t.dispose());
      signMats.forEach((m) => m.dispose());
    }
    movers.length = 0;
    pops.length = 0;
    labelLayer.replaceChildren();
    signMats.length = 0;
    net.others.forEach((o) => { disposeModel(o.group); if (o.car) o.car.paintMat.dispose(); }); // ils reviennent au prochain échange
    if (lot) lot.quest.folk.forEach((f) => disposeModel(f.model.root));
    if (lot) disposeModel(lot.city.mech.root);
    if (lot) lot.city.adBtn.mesh.material.dispose();
    net.others.clear();

    const L = computeLayout(zones);
    const group = new THREE.Group();
    group.position.set(-L.cx, 0, -L.cz);
    world.add(group);
    const textures = [];
    const tags = [];
    const rnd = mulberry(1234);
    const W = L.xMax - L.xMin, D = L.zMax;

    // Sol : herbe, route, parking, voie d'accès
    const grass = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1000, 100, 72).rotateX(-Math.PI / 2), M.grass); // carreaux de 14 m : léger, même sur téléphone
    M.grass.map.repeat.set(110, 79);
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
    // Borne de réservation, sur son parvis, à gauche de la guérite
    props.push(box(5.2, 0.14, 6.4, "#b7bcc6", { x: RESA_KIOSK.x, y: 0.07, z: RESA_KIOSK.z - 1.2 }));
    props.push(box(0.9, 1.9, 0.46, "#2b2f8f", { x: RESA_KIOSK.x, y: 1.09, z: RESA_KIOSK.z }));
    props.push(box(1.0, 0.12, 0.56, "#1e66f5", { x: RESA_KIOSK.x, y: 2.1, z: RESA_KIOSK.z }));
    props.push(box(1.1, 0.14, 0.7, "#8d93a0", { x: RESA_KIOSK.x, y: 0.2, z: RESA_KIOSK.z }));
    // Bancs du parvis
    [-1.9, 1.9].forEach((dx) => {
      props.push(box(0.5, 0.1, 1.5, "#8a5a3c", { x: RESA_KIOSK.x + dx, y: 0.55, z: RESA_KIOSK.z - 2.2 }));
      [-0.6, 0.6].forEach((dz) => props.push(box(0.4, 0.42, 0.1, "#30343f", { x: RESA_KIOSK.x + dx, y: 0.34, z: RESA_KIOSK.z - 2.2 + dz })));
    });
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

    // Libre-service : trois véhicules à conduire, sur leur aire, à gauche du parvis
    props.push(box(13.6, 0.1, 6.8, "#4a4e5c", { x: -19.5, y: 0.05, z: RENTAL_Z }));
    props.push(box(12.2, 0.1, 6.8, "#4a4e5c", { x: -32.4, y: 0.05, z: RENTAL_Z })); // trois places de plus
    [-37.7, -33.6, -29.6, -25.7, -21.5, -17.5, -13.3].forEach((x) => props.push(box(0.12, 0.02, 5.6, "#f2f3f5", { x, y: 0.11, z: RENTAL_Z })));
    props.push(cyl(0.08, 3.4, "#30343f", { x: -19.5, y: 1.7, z: RENTAL_Z + 3.7 }, 8));
    props.push(box(5.0, 1.1, 0.14, "#d92b3a", { x: -19.5, y: 3.5, z: RENTAL_Z + 3.7 }));

    // Bonneplace, le village du parking, à l'est : une rue commerçante le long de la route,
    // le belvédère sur sa colline au nord (escalier aux cinq arches, une par zone du
    // parking), le jardin de la Tour KingPar (étang, passerelle), la place de la fête,
    // des champs de fleurs et quelques fermes au sud, les lettres KINGPAR sur la colline.
    const X0 = L.xMax + CITY_GAP, cityX1 = X0 + 190, R = ROAD_Z;
    const vz0 = R - 86, vz1 = R + 116; // emprise du village
    const cityObstacles = [], cityTrees = [], shopSigns = [], cityPoints = [], cityLeaves = [];
    const slabs = [], gables = [];
    const walls = [], roofLow = [], roofTop = [], bases = [], lanternGlow = [], lanternPools = [], lampions = [];
    const cityRnd = mulberry(2026);
    const stone = "#b9b4a6", wood = "#4a3528", gravel = "#e3dac4", white = "#f4f5f7";
    const archSigns = [], signBoards = [];
    const hill = { x: X0 + 76, z: R + 80, r: 31, rt: 11, h: 8 };
    const hillH = (x, z) => {
      const dd = Math.hypot(x - hill.x, z - hill.z);
      return dd >= hill.r ? 0 : dd <= hill.rt ? hill.h : hill.h * (1 - (dd - hill.rt) / (hill.r - hill.rt));
    };
    // Maison : socle de pierre, étages droits séparés par une corniche, toit à quatre
    // pans avec sa cheminée (plus haut pour le chaume des fermes).
    const house = (hx, hz, w, d, floors, roofColor, o) => {
      o = o || {};
      const y0 = o.y0 || 0;
      bases.push({ x: hx, y: y0 + 0.29, z: hz, sx: w + 0.9, sy: 0.3, sz: d + 0.9 });
      let y = y0 + 0.44;
      for (let f = 0; f < floors; f++) {
        walls.push({ x: hx, y: y + 1.45, z: hz, sx: w, sy: 2.9, sz: d, color: o.wall || "#ffffff" });
        y += 2.9;
        if (f < floors - 1) { bases.push({ x: hx, y: y + 0.08, z: hz, sx: w + 0.35, sy: 0.16, sz: d + 0.35 }); y += 0.16; }
      }
      // Toit à deux pans, épais, qui déborde des murs ; une planche de rive claire dessous.
      /* Le toit : deux pans épais en tuiles, qui débordent des murs ; un pignon
         crème de chaque côté avec son œil-de-bœuf ; une faîtière ; une cheminée. */
      const top = o.steep ? 4.0 : 3.0, run = d / 2 + 0.95, angle = Math.atan2(top, run), len = Math.hypot(run, top) + 0.25;
      [-1, 1].forEach((side) => slabs.push({
        x: hx, y: y + top / 2 + 0.12, z: hz + (side * run) / 2, sx: w + 1.5, sy: 0.3, sz: len, rx: side * angle, color: roofColor,
      }));
      gables.push({ x: hx, y: y + top / 2 - 0.02, z: hz, sx: w, sy: top - 0.05, sz: d + 0.1, color: o.wall || "#ffffff" });
      props.push(cyl(0.2, w + 1.6, shade(roofColor, 0.8), { x: hx, y: y + top + 0.22, z: hz, rz: Math.PI / 2 }, 10)); // faîtière
      [-1, 1].forEach((side) => {
        props.push(cyl(0.46, 0.05, "#a8743f", { x: hx + side * (w / 2 + 0.01), y: y + top * 0.36, z: hz, rz: Math.PI / 2 }, 16));
        props.push(cyl(0.36, 0.07, "#bfe3ff", { x: hx + side * (w / 2 + 0.02), y: y + top * 0.36, z: hz, rz: Math.PI / 2 }, 16));
      });
      if (!o.steep) props.push(box(0.6, 1.6, 0.6, "#c9a27a", { x: hx + w * 0.26, y: y + top * 0.62, z: hz + d * 0.22 }));
      cityObstacles.push([hx - w / 2 - 0.35, hx + w / 2 + 0.35, hz - d / 2 - 0.35, hz + d / 2 + 0.35]);
    };
    // Borne lumineuse, comme celles du parking : elle s'allume la nuit.
    const bollard = (x, z, y0) => {
      y0 = y0 || 0;
      props.push(cyl(0.2, 0.14, "#22252e", { x, y: y0 + 0.07, z }, 10));
      props.push(cyl(0.12, 1.1, white, { x, y: y0 + 0.65, z }, 10));
      props.push(cyl(0.135, 0.14, BRAND, { x, y: y0 + 0.95, z }, 10));
      props.push(cyl(0.2, 0.06, "#22252e", { x, y: y0 + 1.47, z }, 10));
      lanternGlow.push({ x, y: y0 + 1.32, z, sx: 0.26, sy: 0.24, sz: 0.26 });
      lanternPools.push({ x, y: y0 + 0.17, z, sx: 6.5, sz: 6.5 });
      cityObstacles.push([x - 0.22, x + 0.22, z - 0.22, z + 0.22]);
    };
    // Arche du parking : deux poteaux, un linteau, le disque « P ». `alongZ` : le linteau suit l'axe z.
    const arch = (x, y0, z, span, h, alongZ, solid, color) => {
      const k = h / 8.2;
      [-span / 2, span / 2].forEach((o) => {
        const px = alongZ ? x : x + o, pz = alongZ ? z + o : z;
        props.push(cyl(0.4 * k, h, color, { x: px, y: y0 + h / 2, z: pz }, 14));
        props.push(cyl(0.43 * k, 0.55 * k, white, { x: px, y: y0 + 1.7 * k, z: pz }, 14)); // bande réfléchissante
        props.push(cyl(0.56 * k, 0.5 * k, "#22252e", { x: px, y: y0 + 0.25 * k, z: pz }, 14));
        if (solid) cityObstacles.push([px - 0.55 * k, px + 0.55 * k, pz - 0.55 * k, pz + 0.55 * k]);
      });
      const len = span + 1.5 * k, yb = y0 + h + 0.2 * k;
      props.push(alongZ ? box(0.8 * k, 1.3 * k, len, color, { x, y: yb, z }) : box(len, 1.3 * k, 0.8 * k, color, { x, y: yb, z }));
      const yd = yb + 1.75 * k;
      props.push(cyl(1.25 * k, 0.5 * k, white, alongZ ? { x, y: yd, z, rz: Math.PI / 2 } : { x, y: yd, z, rx: Math.PI / 2 }, 20));
      [-1, 1].forEach((side) => archSigns.push({
        x: alongZ ? x + side * 0.27 * k : x, y: yd, z: alongZ ? z : z + side * 0.27 * k,
        ry: alongZ ? (side * Math.PI) / 2 : side === 1 ? 0 : Math.PI, size: 1.7 * k, color,
      }));
    };

    // 1. La rue commerçante : huit échoppes de part et d'autre de la route
    const shopDefs = [[24, 1, 8, 6.5, 1], [52, 1, 7.5, 6, 1], [98, 1, 8.5, 6.5, 2], [124, 1, 7.5, 6, 1], [32, -1, 7.5, 6, 1], [60, -1, 8.5, 6.5, 2], [104, -1, 7.5, 6, 1], [152, -1, 8, 6.5, 1]];
    shopDefs.forEach((sd, i) => {
      const hx = X0 + sd[0], w = sd[2], d = sd[3], out = -sd[1]; // la façade regarde la route
      const hz = R + sd[1] * (7.4 + d / 2);
      house(hx, hz, w, d, sd[4], ROOF_TILES[i % ROOF_TILES.length], { wall: FACADES[i % FACADES.length] });
      const fzFace = hz + (out * d) / 2, sw = Math.min(w - 2.2, 6.4), color = AWNINGS[i % AWNINGS.length];
      shopSigns.push({ text: SHOPS[i], x: hx, z: fzFace + out * 0.12, w: sw, ry: out === 1 ? 0 : Math.PI, color });
      // Store banne rayé, porte vitrée
      for (let k = 0; k < 6; k++) {
        props.push(box(sw / 6, 0.07, 1.35, k % 2 ? "#fdf6e3" : color, { x: hx + (k - 2.5) * (sw / 6), y: 2.3, z: fzFace + out * 0.66, rx: out * 0.28 }));
      }
      props.push(box(sw, 0.26, 0.06, color, { x: hx, y: 2.0, z: fzFace + out * 1.3 }));
      props.push(box(1.25, 1.75, 0.08, "#b9824f", { x: hx, y: 1.32, z: fzFace + out * 0.05 })); // porte en bois, arrondie en haut
      props.push(cyl(0.625, 0.08, "#b9824f", { x: hx, y: 2.19, z: fzFace + out * 0.05, rx: Math.PI / 2 }, 20));
      props.push(part(new THREE.TorusGeometry(0.2, 0.06, 6, 14), "#5fb86a", { x: hx, y: 2.25, z: fzFace + out * 0.12 })); // couronne
      props.push(ball(0.05, "#e2574c", { x: hx + 0.14, y: 2.11, z: fzFace + out * 0.16 }));
      const mbx = hx + sw / 2 + 1.5, mbz = fzFace + out * 1.5; // boîte aux lettres rouge
      props.push(cyl(0.05, 0.9, "#f4f5f7", { x: mbx, y: 0.45, z: mbz }, 8));
      props.push(box(0.34, 0.26, 0.5, "#e2574c", { x: mbx, y: 1.0, z: mbz }));
      props.push(box(0.04, 0.2, 0.04, "#ffd60a", { x: mbx + 0.19, y: 1.12, z: mbz + out * 0.12 }));
      [-1, 1].forEach((sx) => { // haies rondes de chaque côté
        for (let k = 0; k < 3; k++) cityLeaves.push({ x: hx + sx * (w / 2 - 0.5 - k * 0.95), y: 0.55, z: fzFace + out * 0.75, sx: 0.62, sy: 0.6, sz: 0.55, color: k % 2 ? "#6fd36a" : "#4fb957" });
      });
      props.push(box(0.5, 0.5, 0.09, "#bfe3ff", { x: hx, y: 1.72, z: fzFace + out * 0.06 })); // petite vitre
      [-1, 1].forEach((sx) => lampions.push({ x: hx + sx * (sw / 2 + 0.55), y: 2.35, z: fzFace + out * 0.45, sx: 0.2, sy: 0.26, sz: 0.2 }));
      const name = SHOPS[i], kind = SHOP_PANELS[name];
      cityPoints.push({
        x: hx, z: fzFace + out * 1.9, label: SHOP_LABELS[name] + (SHOP_GAMES[name] ? " (mini-jeu)" : ""),
        action: kind ? () => openShop(kind, out === 1 ? 0 : Math.PI)
          : SHOP_GAMES[name] ? () => { say(SHOP_SAYS[name]); openGame(SHOP_GAMES[name]); } : () => say(SHOP_SAYS[name]),
      });
    });
    // La statue dorée de la mascotte garde l'entrée du village.
    const mascot = { x: X0 + 12, z: R + 9.6 };
    props.push(box(2.3, 1.2, 2.3, stone, { x: mascot.x, y: 0.6, z: mascot.z }));
    const gold = "#d4af37", my = 1.2;
    props.push(box(0.52, 0.48, 1.08, gold, { x: mascot.x, y: my + 0.75, z: mascot.z + 0.1 }));
    props.push(box(0.6, 0.54, 0.54, gold, { x: mascot.x, y: my + 1.22, z: mascot.z - 0.58 }));
    props.push(box(0.3, 0.24, 0.3, gold, { x: mascot.x, y: my + 1.12, z: mascot.z - 0.95 }));
    [-1, 1].forEach((sx) => {
      props.push(box(0.33, 0.66, 0.09, gold, { x: mascot.x + sx * 0.39, y: my + 1.82, z: mascot.z - 0.52, rz: -sx * 0.45 }));
      [-0.28, 0.5].forEach((dz) => props.push(box(0.14, 0.52, 0.14, gold, { x: mascot.x + sx * 0.18, y: my + 0.26, z: mascot.z + dz })));
    });
    props.push(box(0.09, 0.5, 0.09, gold, { x: mascot.x, y: my + 1.15, z: mascot.z + 0.66, rx: 0.6 }));
    cityObstacles.push([mascot.x - 1.2, mascot.x + 1.2, mascot.z - 1.2, mascot.z + 1.2]);
    cityPoints.push({ x: mascot.x, z: mascot.z - 2.3, label: "Saluer " + MASCOT + ", la mascotte", action: greetMascot });
    const laneN = X0 + 76, laneS = X0 + 128; // ruelles vers le belvédère (nord) et les fermes (sud)
    const feteLane = X0 + 36; // sentier vers la place de la fête
    const busy = (x, side) => Math.abs(x - (side === 1 ? laneN : laneS)) < 5 || (side === 1 && Math.abs(x - feteLane) < 3.5) ||
      shopDefs.some((sd) => sd[1] === side && Math.abs(x - (X0 + sd[0])) < sd[2] / 2 + 1.6);
    for (let x = X0 + 6; x < cityX1 - 2; x += 6) {
      [1, -1].forEach((side) => {
        const i = Math.round((x - X0) / 6) + (side === 1 ? 0 : 1);
        if (busy(x, side)) return;
        if (i % 3 === 0) bollard(x, R + side * 5.75);
        else if (i % 3 === 1) cityTrees.push([x, R + side * 7.2, true, 0]);
      });
    }
    // Distributeur de boissons, entre deux échoppes (il s'éclaire la nuit)
    const vend = { x: X0 + 40, z: R + 6.6 };
    props.push(box(1.15, 1.95, 0.8, "#f4f5f7", { x: vend.x, y: 0.98, z: vend.z }));
    props.push(box(1.17, 0.3, 0.82, BRAND, { x: vend.x, y: 1.82, z: vend.z }));
    cityObstacles.push([vend.x - 0.6, vend.x + 0.6, vend.z - 0.42, vend.z + 0.42]);
    cityPoints.push({ x: vend.x, z: vend.z - 1.2, label: "Prendre une boisson au distributeur", action: drink });

    // La Station KingPar, entre le parking et le village : auvent, pompes, recharge,
    // boutique, et la place d'entraînement du « créneau parfait ».
    const gs = { x: L.xMax + 34, z: R + 15 }, gz = gs.z - 3;
    props.push(box(34, 0.05, 21, "#5a5f6b", { x: gs.x, y: 0.025, z: gs.z }));
    [[-7, -3.6], [7, -3.6], [-7, 3.6], [7, 3.6]].forEach((c) => {
      props.push(cyl(0.22, 4.6, white, { x: gs.x + c[0], y: 2.3, z: gz + c[1] }, 12));
      cityObstacles.push([gs.x + c[0] - 0.25, gs.x + c[0] + 0.25, gz + c[1] - 0.25, gz + c[1] + 0.25]);
    });
    props.push(box(17.4, 0.5, 9.8, BRAND, { x: gs.x, y: 4.85, z: gz })); // l'auvent
    props.push(box(17.5, 0.14, 9.9, white, { x: gs.x, y: 4.62, z: gz }));
    [-3.6, 3.6].forEach((dx) => { // deux îlots, deux pompes chacun
      props.push(box(1.2, 0.18, 4.6, stone, { x: gs.x + dx, y: 0.09, z: gz }));
      [-1.25, 1.25].forEach((dz) => {
        props.push(box(0.62, 1.5, 0.5, white, { x: gs.x + dx, y: 0.93, z: gz + dz }));
        props.push(box(0.66, 0.22, 0.54, BRAND, { x: gs.x + dx, y: 1.79, z: gz + dz }));
        [-1, 1].forEach((sx) => props.push(box(0.03, 0.34, 0.36, "#22252e", { x: gs.x + dx + sx * 0.32, y: 1.28, z: gz + dz })));
        lanternGlow.push({ x: gs.x + dx, y: 4.5, z: gz + dz, sx: 1.7, sy: 0.08, sz: 0.5 });
      });
      cityObstacles.push([gs.x + dx - 0.6, gs.x + dx + 0.6, gz - 2.3, gz + 2.3]);
    });
    lanternPools.push({ x: gs.x, y: 0.07, z: gz, sx: 21, sz: 14 });
    [-5.8, -1.4, 1.4, 5.8].forEach((dx) => cityPoints.push({
      x: gs.x + dx, z: gz, label: "Faire le plein pile (mini-jeu)", action: () => openGame("plein", "station"),
    }));
    house(gs.x - 9.5, gs.z + 6.4, 9, 6, 1, "#2f4a7a", { wall: "#dcebff" }); // la boutique de la station
    signBoards.push([5.6, 0.6, "BOUTIQUE DE LA STATION", "#fdf6e3", BRAND, gs.x - 9.5, 2.75, gs.z + 3.34, Math.PI]);
    signBoards.push([9, 0.42, "STATION KINGPAR", BRAND, "#ffffff", gs.x, 4.87, gz - 4.91, Math.PI]);
    signBoards.push([9, 0.42, "STATION KINGPAR", BRAND, "#ffffff", gs.x, 4.87, gz + 4.91, 0]);
    const stTotem = { x: gs.x - 15.6, z: R + 6.4 }; // stTotem au bord de la route
    props.push(box(0.36, 7.4, 0.36, "#3b4252", { x: stTotem.x, y: 3.7, z: stTotem.z }));
    props.push(box(0.5, 2.3, 3.5, white, { x: stTotem.x, y: 6.1, z: stTotem.z }));
    cityObstacles.push([stTotem.x - 0.3, stTotem.x + 0.3, stTotem.z - 0.3, stTotem.z + 0.3]);
    [-1, 1].forEach((sx) => {
      signBoards.push([3.3, 1.0, "STATION KINGPAR", BRAND, "#ffffff", stTotem.x + sx * 0.26, 6.6, stTotem.z, (sx * Math.PI) / 2]);
      signBoards.push([3.3, 0.7, "JEU : LE PLEIN PILE", "#ffd60a", "#22252e", stTotem.x + sx * 0.26, 5.6, stTotem.z, (sx * Math.PI) / 2]);
    });
    const evPost = { x: gs.x + 2, z: gs.z + 8.6 }; // borne de recharge, comme la zone Électrique du parking
    props.push(box(0.5, 1.5, 0.36, white, { x: evPost.x, y: 0.75, z: evPost.z }));
    props.push(box(0.52, 0.2, 0.38, KINDS.ELECTRIC.color, { x: evPost.x, y: 1.4, z: evPost.z }));
    props.push(box(2.9, 0.03, 5.2, KINDS.ELECTRIC.color, { x: evPost.x, y: 0.055, z: evPost.z - 3.2 }));
    cityObstacles.push([evPost.x - 0.3, evPost.x + 0.3, evPost.z - 0.25, evPost.z + 0.25]);
    props.push(box(0.3, 3.9, 7.5, "#22252e", { x: gs.x + 16.4, y: 4.5, z: R + 8.2 })); // cadre du panneau des places libres
    [-3, 3].forEach((dz) => {
      props.push(box(0.3, 2.7, 0.3, "#3b4252", { x: gs.x + 16.4, y: 1.35, z: R + 8.2 + dz }));
      cityObstacles.push([gs.x + 16.2, gs.x + 16.6, R + 8.2 + dz - 0.2, R + 8.2 + dz + 0.2]);
    });
    const bay = { x: gs.x + 12.6, z: gz, w: 3.0, d: 5.8 }; // place d'entraînement : se garer droit et au centre
    [[0, -bay.d / 2, bay.w, 0.14], [0, bay.d / 2, bay.w, 0.14], [-bay.w / 2, 0, 0.14, bay.d], [bay.w / 2, 0, 0.14, bay.d]].forEach((ln) => {
      props.push(box(ln[2], 0.03, ln[3], "#ffd60a", { x: bay.x + ln[0], y: 0.06, z: bay.z + ln[1] }));
    });
    props.push(box(0.14, 2.6, 0.14, "#3b4252", { x: bay.x + 2.2, y: 1.3, z: bay.z - 3.4 }));
    signBoards.push([2.6, 0.9, "LE CRÉNEAU PARFAIT", "#ffd60a", "#22252e", bay.x + 2.2, 2.6, bay.z - 3.48, Math.PI]);
    signBoards.push([2.6, 0.9, "LE CRÉNEAU PARFAIT", "#ffd60a", "#22252e", bay.x + 2.2, 2.6, bay.z - 3.32, 0]);
    cityObstacles.push([bay.x + 2.05, bay.x + 2.35, bay.z - 3.55, bay.z - 3.25]);

    /* KingPar Tuning, en face de la station : l'atelier, son podium tournant où l'on
       pose le véhicule, les piles de pneus, les pots de peinture et Jo, le mécano. */
    const tg = { x: gs.x, z: R - 15.5 }, podium = { x: gs.x + 5, z: R - 13.5, mesh: null };
    props.push(box(31, 0.05, 22, "#5a5f6b", { x: tg.x, y: 0.025, z: tg.z }));
    props.push(box(31, 0.04, 1.2, "#5a5f6b", { x: tg.x, y: 0.02, z: R - 4.0 })); // bateau vers la route
    const shopX = tg.x - 8, shopZ = R - 21.5, shopFront = shopZ + 3.5;
    house(shopX, shopZ, 11, 7, 1, "#e2574c", { wall: "#fff3c4" });
    props.push(box(4.6, 2.3, 0.14, "#2b2e37", { x: shopX - 2.2, y: 1.59, z: shopFront + 0.05 })); // rideau de l'atelier
    for (let k = 0; k < 6; k++) props.push(box(4.4, 0.05, 0.16, "#8b909c", { x: shopX - 2.2, y: 0.7 + k * 0.36, z: shopFront + 0.06 }));
    for (let k = 0; k < 8; k++) props.push(box(0.6, 0.2, 0.16, k % 2 ? "#22252e" : "#ffd60a", { x: shopX - 4.3 + k * 0.6, y: 2.84, z: shopFront + 0.06 }));
    props.push(box(1.2, 2.1, 0.14, BRAND, { x: shopX + 2.6, y: 1.49, z: shopFront + 0.05 })); // porte
    props.push(box(0.55, 0.55, 0.16, "#bfe3ff", { x: shopX + 2.6, y: 1.95, z: shopFront + 0.06 }));
    props.push(ball(0.06, "#ffd60a", { x: shopX + 3.02, y: 1.45, z: shopFront + 0.16 }));
    ["#d4af37", BRAND, "#ff5d8f"].forEach((color, k) => { // jantes en vitrine sur la façade
      props.push(cyl(0.4, 0.1, "#15161a", { x: shopX + 4.5, y: 0.95 + k * 0.92, z: shopFront + 0.07, rx: Math.PI / 2 }, 18));
      props.push(cyl(0.27, 0.14, color, { x: shopX + 4.5, y: 0.95 + k * 0.92, z: shopFront + 0.07, rx: Math.PI / 2 }, 14));
    });
    props.push(box(8.6, 0.86, 0.12, "#22252e", { x: shopX - 0.6, y: 3.95, z: shopFront + 0.5 })); // l'enseigne, posée sur le toit
    [-3.6, 3.6].forEach((dx) => props.push(box(0.12, 0.7, 0.12, "#22252e", { x: shopX - 0.6 + dx, y: 3.45, z: shopFront + 0.44 })));
    signBoards.push([8.2, 0.62, "KINGPAR TUNING", "#ffd60a", "#22252e", shopX - 0.6, 3.95, shopFront + 0.57, 0]);
    // Le podium : un plateau qui tourne quand un véhicule y est réglé, des plots lumineux autour.
    props.push(cyl(4.5, 0.05, "#3b4252", { x: podium.x, y: 0.04, z: podium.z }, 40));
    for (let k = 0; k < 12; k++) {
      const a = (k / 12) * Math.PI * 2, px = podium.x + Math.cos(a) * 4.25, pz = podium.z + Math.sin(a) * 4.25;
      props.push(cyl(0.12, 0.08, "#22252e", { x: px, y: 0.09, z: pz }, 10));
      lanternGlow.push({ x: px, y: 0.16, z: pz, sx: 0.16, sy: 0.07, sz: 0.16 });
    }
    lanternPools.push({ x: podium.x, y: 0.09, z: podium.z, sx: 15, sz: 15 });
    [-1, 1].forEach((sx) => { // deux mâts de projecteurs derrière le podium, une guirlande entre eux
      const mx = podium.x + sx * 5.6, mz = podium.z - 5.4;
      props.push(cyl(0.13, 5.2, "#3b4252", { x: mx, y: 2.6, z: mz }, 10));
      props.push(box(0.9, 0.34, 0.4, "#22252e", { x: mx - sx * 0.3, y: 5.15, z: mz + 0.2, rx: 0.5 }));
      lanternGlow.push({ x: mx - sx * 0.3, y: 5.05, z: mz + 0.4, sx: 0.7, sy: 0.22, sz: 0.1 });
      cityObstacles.push([mx - 0.2, mx + 0.2, mz - 0.2, mz + 0.2]);
    });
    for (let k = 1; k < 12; k++) {
      const t = k / 12;
      lampions.push({ x: podium.x - 5.6 + 11.2 * t, y: 4.7 - Math.sin(Math.PI * t) * 0.8, z: podium.z - 5.4, sx: 0.17, sy: 0.21, sz: 0.17 });
    }
    [[tg.x + 13.4, R - 21.6, 4], [tg.x + 12.5, R - 23.2, 3], [tg.x + 14.1, R - 23.6, 2], [shopX - 6.6, shopFront + 1.0, 3]].forEach((st) => { // piles de pneus
      for (let k = 0; k < st[2]; k++) {
        props.push(cyl(0.44, 0.25, "#15161a", { x: st[0], y: 0.18 + k * 0.26, z: st[1] }, 16));
        props.push(cyl(0.24, 0.27, "#3b4252", { x: st[0], y: 0.18 + k * 0.26, z: st[1] }, 12));
      }
      cityObstacles.push([st[0] - 0.46, st[0] + 0.46, st[1] - 0.46, st[1] + 0.46]);
    });
    const cans = { x: tg.x + 0.4, z: R - 20.8 }; // pots de peinture, en pyramide
    [[0, 0, 0], [0.42, 0, 0], [0.84, 0, 0], [1.26, 0, 0], [0.21, 0.4, 0], [0.63, 0.4, 0], [1.05, 0.4, 0], [0.42, 0.8, 0], [0.84, 0.8, 0], [0.63, 1.2, 0]].forEach((c, k) => {
      props.push(cyl(0.19, 0.36, CAR_PAINTS[(k * 3) % CAR_PAINTS.length], { x: cans.x + c[0], y: 0.23 + c[1], z: cans.z }, 12));
      props.push(cyl(0.2, 0.04, "#d5d8de", { x: cans.x + c[0], y: 0.42 + c[1], z: cans.z }, 12));
    });
    cityObstacles.push([cans.x - 0.25, cans.x + 1.5, cans.z - 0.25, cans.z + 0.25]);
    const cart = { x: podium.x - 6.3, z: podium.z - 2.4 }; // servante d'atelier
    props.push(box(0.95, 0.85, 0.55, "#d92b3a", { x: cart.x, y: 0.6, z: cart.z }));
    [0.38, 0.62, 0.86].forEach((y) => props.push(box(0.8, 0.03, 0.57, "#f4f5f7", { x: cart.x, y, z: cart.z })));
    props.push(box(1.0, 0.05, 0.6, "#22252e", { x: cart.x, y: 1.05, z: cart.z }));
    cityObstacles.push([cart.x - 0.5, cart.x + 0.5, cart.z - 0.3, cart.z + 0.3]);
    const tuTotem = { x: tg.x - 14.6, z: R - 6.4 }; // totem au bord de la route
    props.push(box(0.36, 6.2, 0.36, "#3b4252", { x: tuTotem.x, y: 3.1, z: tuTotem.z }));
    props.push(box(0.5, 2.3, 3.5, "#22252e", { x: tuTotem.x, y: 5.0, z: tuTotem.z }));
    cityObstacles.push([tuTotem.x - 0.3, tuTotem.x + 0.3, tuTotem.z - 0.3, tuTotem.z + 0.3]);
    [-1, 1].forEach((sx) => {
      signBoards.push([3.3, 1.0, "KINGPAR TUNING", "#ffd60a", "#22252e", tuTotem.x + sx * 0.26, 5.5, tuTotem.z, (sx * Math.PI) / 2]);
      signBoards.push([3.3, 0.7, "PEINTURE · JANTES · NÉONS", "#22252e", "#ffffff", tuTotem.x + sx * 0.26, 4.5, tuTotem.z, (sx * Math.PI) / 2]);
    });
    const jo = { x: podium.x - 6.2, z: podium.z + 0.6 };
    const mech = buildPerson({ top: "#f4f5f7", hem: "#c9ccd6", skin: "#dba97c", hair: "#3b2a20", pants: BRAND, shoes: "#22252e", cap: "#22252e", hat: "cap", cut: "short", outfit: "salopette", bottom: "pants", extra: "none", eyes: "malins", small: true });
    mech.root.position.set(jo.x, 0, jo.z);
    mech.root.rotation.y = Math.PI / 2;
    group.add(mech.root);
    cityObstacles.push([jo.x - 0.28, jo.x + 0.28, jo.z - 0.28, jo.z + 0.28]);
    cityPoints.push({ x: jo.x + 0.2, z: jo.z + 1.3, label: "Personnaliser un véhicule (tout est offert)", action: () => openTuning(null) });

    // 2. Le belvédère sur sa colline : ruelle, escalier sous cinq arches (une par zone), pavillon et cloche
    props.push(box(5, 0.04, 44.5, "#dcb98a", { x: laneN, y: 0.02, z: R + 4.5 + 22.25 }));
    const hillGeo = new THREE.CylinderGeometry(hill.rt, hill.r, hill.h, 44, 1);
    const hillMesh = new THREE.Mesh(hillGeo, M.hill);
    hillMesh.position.set(hill.x, hill.h / 2, hill.z);
    hillMesh.receiveShadow = true;
    group.add(hillMesh);
    for (let i = 0; i < 16; i++) {
      const z = hill.z - hill.r + ((i + 0.5) / 16) * (hill.r - hill.rt);
      props.push(box(3.3, 0.34, 1.3, "#cfc9b8", { x: hill.x, y: hillH(hill.x, z) + 0.04, z }));
    }
    for (let i = 0; i < 5; i++) {
      const z = hill.z - hill.r + 1.6 + i * 4.3;
      arch(hill.x, hillH(hill.x, z), z, 3.7, 3.7, false, false, KINDS[ZONE_ORDER[i]].color);
    }
    const top = hill.h;
    props.push(cyl(hill.rt - 0.6, 0.06, gravel, { x: hill.x, y: top + 0.03, z: hill.z }, 20));
    house(hill.x, hill.z + 3.4, 7.6, 6, 1, "#2f4a7a", { y0: top, wall: "#ffffff" });
    props.push(box(1.5, 0.7, 0.85, wood, { x: hill.x, y: top + 0.35, z: hill.z - 1.5 })); // socle de la cloche
    props.push(ball(0.3, "#d4af37", { x: hill.x, y: top + 2.75, z: hill.z - 0.55 })); // la cloche
    props.push(box(0.07, 1.9, 0.07, "#fdf6e3", { x: hill.x, y: top + 1.75, z: hill.z - 0.55 }));
    [-2.6, 2.6].forEach((dx) => { // deux chihuahuas de pierre veillent sur l'escalier
      const sx = hill.x + dx, sz = hill.z - 5, st = "#a7a295";
      props.push(box(0.8, 0.5, 1.1, stone, { x: sx, y: top + 0.25, z: sz }));
      props.push(box(0.36, 0.34, 0.7, st, { x: sx, y: top + 0.78, z: sz + 0.08 }));
      props.push(box(0.42, 0.38, 0.38, st, { x: sx, y: top + 1.1, z: sz - 0.36 }));
      [-1, 1].forEach((e) => props.push(box(0.22, 0.44, 0.07, st, { x: sx + e * 0.27, y: top + 1.5, z: sz - 0.34, rz: -e * 0.45 })));
      cityObstacles.push([sx - 0.45, sx + 0.45, sz - 0.6, sz + 0.6]);
      bollard(hill.x + dx * 1.5, hill.z - 8.2, top);
    });
    cityPoints.push({ x: hill.x, z: hill.z - 2.4, label: "Faire sonner la cloche du belvédère", action: ringBell });
    const omi = { x: hill.x - 3.9, z: hill.z - 1.0 }; // distributeur de tickets chance, comme une caisse de parking
    props.push(box(0.85, 1.5, 0.6, "#f2b01e", { x: omi.x, y: top + 0.75, z: omi.z }));
    props.push(box(0.91, 0.12, 0.66, BRAND, { x: omi.x, y: top + 1.56, z: omi.z }));
    props.push(box(0.5, 0.34, 0.04, "#22252e", { x: omi.x, y: top + 1.16, z: omi.z - 0.31 }));
    props.push(box(0.42, 0.06, 0.05, "#22252e", { x: omi.x, y: top + 0.72, z: omi.z - 0.31 }));
    cityObstacles.push([omi.x - 0.5, omi.x + 0.5, omi.z - 0.35, omi.z + 0.35]);
    cityPoints.push({ x: omi.x, z: omi.z - 1.2, label: "Tirer un ticket chance", action: luckyTicket });
    for (let i = 0; i < 9; i++) { // arbres en fleurs en couronne autour du pavillon
      const a = -Math.PI / 2 + ((i + 1) / 10) * Math.PI * 2;
      if (Math.abs(Math.cos(a)) < 0.55 && Math.sin(a) < 0) continue; // l'arrivée de l'escalier reste dégagée
      cityTrees.push([hill.x + Math.cos(a) * 9.2, hill.z + Math.sin(a) * 9.2, true, top]);
    }
    for (let i = 0; i < 34; i++) { // bois sur les pentes : pins et cerisiers
      const a = cityRnd() * Math.PI * 2, rr = hill.rt + 2.5 + cityRnd() * (hill.r - hill.rt - 2);
      const x = hill.x + Math.cos(a) * rr, z = hill.z + Math.sin(a) * rr;
      if (Math.abs(x - hill.x) < 3.6 && z < hill.z) continue; // pas dans l'escalier
      cityTrees.push([x, z, cityRnd() < 0.42, hillH(x, z)]);
    }

    // 2 bis. La place de la fête : kiosque à musique et sa grosse caisse, stands, guirlandes
    const fete = { x: X0 + 24, z: R + 36 };
    props.push(box(3, 0.04, 21, "#dcb98a", { x: feteLane, y: 0.02, z: R + 15 }));
    props.push(box(31, 0.04, 23, gravel, { x: fete.x, y: 0.025, z: fete.z }));
    props.push(box(3.9, 1.3, 3.9, BRAND, { x: fete.x, y: 0.65, z: fete.z })); // le kiosque et sa jupe bleue et blanche
    props.push(box(3.96, 0.32, 3.96, "#fdf6e3", { x: fete.x, y: 0.95, z: fete.z }));
    props.push(box(4.3, 0.22, 4.3, wood, { x: fete.x, y: 1.41, z: fete.z }));
    [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((c) => props.push(box(0.18, 2.7, 0.18, wood, { x: fete.x + c[0] * 1.95, y: 2.85, z: fete.z + c[1] * 1.95 })));
    roofTop.push({ x: fete.x, y: 4.85, z: fete.z, sx: 3.9, sy: 1.3, sz: 3.9, color: "#2f4a7a" });
    props.push(box(1.2, 0.5, 0.9, wood, { x: fete.x, y: 1.77, z: fete.z }));
    props.push(cyl(0.7, 1.1, BRAND, { x: fete.x, y: 2.7, z: fete.z, rx: Math.PI / 2 })); // la grosse caisse, peau vers la rue
    props.push(cyl(0.64, 1.16, "#f3e6c8", { x: fete.x, y: 2.7, z: fete.z, rx: Math.PI / 2 }));
    cityObstacles.push([fete.x - 2.15, fete.x + 2.15, fete.z - 2.15, fete.z + 2.15]);
    cityPoints.push({ x: fete.x, z: fete.z - 3.3, label: "Frapper la grosse caisse de la fête", action: bassDrum });
    const stallSigns = [];
    [[-10.5, -6], [10.5, -6], [-10.5, 6], [10.5, 6]].forEach((st, i) => {
      const def = STALLS[i], sx = fete.x + st[0], sz = fete.z + st[1], dir = st[0] < 0 ? 1 : -1; // le comptoir regarde la tour
      props.push(box(1.1, 1.0, 2.9, wood, { x: sx, y: 0.5, z: sz }));
      props.push(box(1.2, 0.08, 3.0, "#e8d9b8", { x: sx, y: 1.04, z: sz }));
      props.push(box(0.06, 1.35, 2.9, def[3], { x: sx - dir * 0.7, y: 1.75, z: sz })); // toile du fond
      [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((c) => props.push(box(0.09, 2.5, 0.09, wood, { x: sx + c[0] * 0.75, y: 1.25, z: sz + c[1] * 1.45 })));
      for (let k = 0; k < 5; k++) { // auvent rayé
        props.push(box(2.3, 0.07, 0.6, k % 2 ? "#fdf6e3" : def[3], { x: sx + dir * 0.2, y: 2.52, z: sz + (k - 2) * 0.6, rz: -dir * 0.16 }));
      }
      [-1, 1].forEach((c) => lampions.push({ x: sx + dir * 1.25, y: 2.0, z: sz + c * 1.5, sx: 0.16, sy: 0.2, sz: 0.16 }));
      stallSigns.push({ text: def[0], x: sx + dir * 0.57, z: sz, ry: (dir * Math.PI) / 2, color: def[3] });
      cityObstacles.push([sx - 0.8, sx + 0.8, sz - 1.55, sz + 1.55]);
      cityPoints.push({ x: sx + dir * 2.0, z: sz, label: def[1] + " (mini-jeu)", action: () => { say(def[2][Math.floor(Math.random() * def[2].length)]); openGame(STALL_GAMES[i]); } });
    });
    [[-14.5, -10.5], [14.5, -10.5], [-14.5, 10.5], [14.5, 10.5]].forEach((c) => { // mâts et guirlandes d'ampoules
      const px = fete.x + c[0], pz = fete.z + c[1];
      props.push(box(0.14, 5.2, 0.14, wood, { x: px, y: 2.6, z: pz }));
      cityObstacles.push([px - 0.15, px + 0.15, pz - 0.15, pz + 0.15]);
      for (let k = 1; k <= 8; k++) {
        const t = k / 9;
        lampions.push({ x: fete.x + c[0] * t, y: 5.3 + (5.0 - 5.3) * t - Math.sin(Math.PI * t) * 0.9, z: fete.z + c[1] * t, sx: 0.17, sy: 0.21, sz: 0.17 });
      }
      cityTrees.push([px + Math.sign(c[0]) * 2.6, pz + Math.sign(c[1]) * 1.8, true, 0]);
    });
    const bal = { x: fete.x + 5.5, z: fete.z - 9.6 }; // le marchand de ballons KingPar
    props.push(box(0.9, 0.9, 0.9, BRAND, { x: bal.x, y: 0.45, z: bal.z }));
    props.push(cyl(0.05, 2.6, wood, { x: bal.x, y: 2.1, z: bal.z }, 8));
    BALLOONS.forEach((color, k) => {
      const a = (k / BALLOONS.length) * Math.PI * 2, r = 0.42 + (k % 2) * 0.16;
      props.push(ball(0.3, color, { x: bal.x + Math.cos(a) * r, y: 3.5 + (k % 3) * 0.28, z: bal.z + Math.sin(a) * r, sy: 1.15 }));
    });
    cityObstacles.push([bal.x - 0.5, bal.x + 0.5, bal.z - 0.5, bal.z + 0.5]);
    cityPoints.push({ x: bal.x, z: bal.z + 1.5, label: "Prendre un ballon KingPar (offert)", action: openBalloons });
    signBoards.push([0.86, 0.3, "BALLONS", "#ffd60a", "#22252e", bal.x, 0.6, bal.z + 0.46, 0]);
    cityPoints.push({ x: bal.x + 2.6, z: bal.z + 0.4, label: "Jouer à l'éclate-ballons (mini-jeu)", action: () => openGame("ballons") });
    lanternPools.push({ x: fete.x, y: 0.06, z: fete.z, sx: 30, sz: 24 });

    // 3. Le jardin de la Tour KingPar : étang aux carpes, passerelle bleue, tour aux cinq étages (un par zone)
    const gx0 = X0 + 150, gz0 = R + 36;
    props.push(cyl(1, 0.04, gravel, { x: gx0, y: 0.03, z: gz0, sx: 23, sz: 19 }, 28));
    props.push(box(3, 0.04, 14, gravel, { x: gx0 - 12, y: 0.025, z: R + 11.5 }));
    const pond = { x: gx0 - 6, z: gz0 + 3, rx: 7.0, rz: 4.4 };
    props.push(cyl(1, 0.12, stone, { x: pond.x, y: 0.17, z: pond.z, sx: 7.6, sz: 5.0 }, 28));
    props.push(cyl(1, 0.06, "#5bb5e8", { x: pond.x, y: 0.24, z: pond.z, sx: pond.rx, sz: pond.rz }, 28));
    for (let i = -2; i <= 2; i++) {
      props.push(box(1.7, 0.14, 2.15, BRAND, { x: pond.x, y: 0.5 + (1 - (i / 2) * (i / 2)) * 0.9, z: pond.z + i * 1.9, rx: i * 0.22 }));
    }
    [-1, 1].forEach((sx) => [-3.8, 0, 3.8].forEach((dz) => {
      props.push(box(0.14, 0.8, 0.14, white, { x: pond.x + sx * 0.85, y: 0.9 + (dz === 0 ? 0.9 : 0), z: pond.z + dz }));
    }));
    cityObstacles.push([pond.x - 7.4, pond.x - 1.0, pond.z - 4.6, pond.z + 4.6], [pond.x + 1.0, pond.x + 7.4, pond.z - 4.6, pond.z + 4.6]);
    const pgx = gx0 + 10, pgz = gz0 - 6;
    bases.push({ x: pgx, y: 0.34, z: pgz, sx: 9.5, sy: 0.4, sz: 9.5 });
    let py = 0.54;
    ZONE_ORDER.forEach((name, t) => { // un étage par zone du parking, à sa couleur
      const size = 6.6 - t * 0.75;
      walls.push({ x: pgx, y: py + 1.2, z: pgz, sx: size, sy: 2.4, sz: size, color: KINDS[name].color });
      py += 2.4;
      props.push(box(size + 0.8, 0.24, size + 0.8, white, { x: pgx, y: py + 0.12, z: pgz }));
      py += 0.24;
    });
    props.push(cyl(0.22, 0.7, "#22252e", { x: pgx, y: py + 0.35, z: pgz }, 10));
    const cube = { x: pgx, y: py + 1.85, z: pgz }; // au sommet, le cube « P » (éclairé la nuit par ses faces)
    props.push(box(2.4, 2.4, 2.4, BRAND, cube));
    [[0, 1, 0], [0, -1, Math.PI], [1, 0, Math.PI / 2], [-1, 0, -Math.PI / 2]].forEach((f) => archSigns.push({
      x: cube.x + f[0] * 1.21, y: cube.y, z: cube.z + f[1] * 1.21, ry: f[2], size: 2.3, color: BRAND, logo: true,
    }));
    cityObstacles.push([pgx - 3.6, pgx + 3.6, pgz - 3.6, pgz + 3.6]);
    [[pond.x - 8.6, pond.z - 5.8], [pond.x + 8.4, pond.z + 5.8], [pond.x + 2.6, pond.z - 6.4], [pgx - 5.6, pgz + 5.6]].forEach((t) => bollard(t[0], t[1]));
    [[-12, 12], [4, 13.5]].forEach((b) => {
      props.push(box(1.6, 0.1, 0.5, "#8a5a3c", { x: gx0 + b[0], y: 0.5, z: gz0 + b[1] }));
      props.push(box(1.4, 0.44, 0.1, wood, { x: gx0 + b[0], y: 0.26, z: gz0 + b[1] }));
    });
    for (let i = 0; i < 13; i++) {
      const a = (i / 13) * Math.PI * 2;
      if (Math.abs(a - Math.PI * 1.36) < 0.3) continue; // l'allée d'entrée
      cityTrees.push([gx0 + Math.cos(a) * 21.5, gz0 + Math.sin(a) * 17.5, true, 0]);
    }

    // 4. Au sud : champs de fleurs aux couleurs des zones, épouvantail en gilet jaune, fermes, petit bois de bouleaux
    props.push(box(5, 0.04, 52, "#dcb98a", { x: laneS, y: 0.02, z: R - 4.5 - 26 }));
    props.push(box(46, 0.04, 4, "#dcb98a", { x: laneS + 21, y: 0.02, z: R - 48 }));
    const paddies = [], rice = [];
    props.push(box(4 * 24.5 + 1.5, 0.22, 2 * 18.5 + 1.5, "#8a7355", { x: X0 + 61.75, y: 0.11, z: R - 43.25 })); // diguettes
    for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) {
      const cx = X0 + 25 + i * 24.5, cz = R - 34 - j * 18.5;
      paddies.push({ x: cx, y: 0.235, z: cz, sx: 22, sz: 16 });
      for (let r = 0; r < 12; r++) rice.push({ x: cx, y: 0.42, z: cz - 7 + r * 1.27, sx: 20.6, sy: 0.42, sz: 0.34, color: r % 3 === 2 ? "#6fbf5a" : FLOWERS[(i * 2 + j) % FLOWERS.length] });
    }
    instanced(group, new THREE.PlaneGeometry(1, 1, 5, 4).rotateX(-Math.PI / 2), M.soil, paddies, "receive");
    instanced(group, new THREE.BoxGeometry(1, 1, 1, 5, 1, 1), M.foliage, rice);
    const crow = { x: X0 + 49.5, z: R - 34 }; // l'épouvantail
    props.push(box(0.1, 2.0, 0.1, wood, { x: crow.x, y: 1.2, z: crow.z }));
    props.push(box(1.7, 0.1, 0.1, wood, { x: crow.x, y: 1.78, z: crow.z }));
    props.push(box(0.72, 0.82, 0.14, "#ffd60a", { x: crow.x, y: 1.5, z: crow.z })); // le gilet de l'agent
    [1.32, 1.62].forEach((y) => props.push(box(0.74, 0.07, 0.16, "#d5d8de", { x: crow.x, y, z: crow.z })));
    props.push(ball(0.24, "#f0d9b5", { x: crow.x, y: 2.34, z: crow.z }));
    props.push(box(0.5, 0.2, 0.5, "#1f2a44", { x: crow.x, y: 2.62, z: crow.z })); // et sa casquette
    props.push(box(0.42, 0.05, 0.24, "#1f2a44", { x: crow.x, y: 2.55, z: crow.z - 0.34 }));
    [[22, -28, 9, 7], [44, -46, 8.5, 6.5], [18, -66, 9, 7]].forEach((f, i) => {
      house(laneS + f[0], R + f[1], f[2], f[3], 1, i % 2 ? "#7a5a36" : "#8a6b3c", { steep: true, wall: "#efe0c4" });
      cityTrees.push([laneS + f[0] - f[2] / 2 - 3, R + f[1] + 3, i !== 1, 0], [laneS + f[0] + f[2] / 2 + 2.6, R + f[1] - f[3] / 2 - 2, false, 0]);
    });
    const bamboo = [];
    for (let i = 0; i < 110; i++) {
      const x = laneS + 34 + cityRnd() * 26, z = R - 82 + cityRnd() * 22, h = 5 + cityRnd() * 3.5;
      bamboo.push({ x, y: h / 2, z, sx: 0.13, sy: h, sz: 0.13, color: cityRnd() < 0.5 ? "#ece7dc" : "#ddd6c8" }); // troncs clairs des bouleaux
      cityLeaves.push({ x, y: h - 0.2, z, sx: 1.25, sy: 1.5, sz: 1.25, ry: cityRnd() * 6, color: cityRnd() < 0.5 ? "#9ccc65" : "#b5d86b" });
    }
    instanced(group, new THREE.CylinderGeometry(1, 1, 1, 6), M.foliage, bamboo, "cast");

    // 5. Maisons, toits, grande arche d'entrée, collines au loin et lettres KINGPAR
    const unit = new THREE.BoxGeometry(1, 1, 1);
    instanced(group, unit, M.stone, bases, "both");
    instanced(group, unit.clone(), M.house, walls, "both");
    const frustum = (topR) => {
      const g = new THREE.CylinderGeometry(topR, 1, 1, 4, 1).toNonIndexed();
      g.rotateY(Math.PI / 4);
      g.computeVertexNormals();
      return g;
    };
    // Toits à deux pans : un prisme dont le faîte suit la longueur de la maison.
    const corners = [[-0.5, -0.5, -0.5], [0.5, -0.5, -0.5], [0.5, -0.5, 0.5], [-0.5, -0.5, 0.5], [-0.5, 0.5, 0], [0.5, 0.5, 0]];
    const faces = [[3, 2, 5], [3, 5, 4], [1, 0, 4], [1, 4, 5], [0, 3, 4], [2, 1, 5], [0, 1, 2], [0, 2, 3]];
    const gable = new THREE.BufferGeometry();
    gable.setAttribute("position", new THREE.Float32BufferAttribute(faces.flat().flatMap((i) => corners[i]), 3));
    gable.computeVertexNormals();
    instanced(group, new THREE.BoxGeometry(1, 1, 1), M.roofTile, roofLow, "both");
    instanced(group, gable, M.roofTile, roofTop, "cast");
    instanced(group, new THREE.BoxGeometry(1, 1, 1), M.roofSlab, slabs, "both");
    instanced(group, gable.clone(), M.plaster, gables, "both");
    void frustum;
    const tx = X0 - 12;
    arch(tx, 0, R, 12.4, 8.2, true, true, BRAND);
    bollard(tx + 1.5, R + 8.4);
    bollard(tx + 1.5, R - 8.4);
    cityTrees.push([tx - 3, R + 10.5, true, 0], [tx - 3, R - 10.5, true, 0]);
    const peaks = [], vx = (X0 + cityX1) / 2;
    const haze = ["#9fdc8f", "#8fd3a6", "#a9e39a", "#8ccbb8", "#b4e6a0"];
    for (let i = 0; i < 16; i++) {
      const a = -1.75 + (i / 15) * 3.5 + (cityRnd() - 0.5) * 0.12, dist = 330 + cityRnd() * 190;
      const rr = 75 + cityRnd() * 70, hh = 55 + cityRnd() * 80;
      peaks.push({ x: vx + Math.cos(a) * dist, y: hh / 2 - 2, z: R + 20 + Math.sin(a) * dist, sx: rr, sy: hh, sz: rr, color: haze[i % haze.length] });
    }
    // … et, plein est, la colline aux lettres KINGPAR (on roule droit dessus)
    const sign = { x: cityX1 + 205, z: R + 30, r: 150, h: 72 };
    peaks.push({ x: sign.x, y: sign.h / 2 - 2, z: sign.z, sx: sign.r, sy: sign.h, sz: sign.r, color: "#86c46a" });
    "KINGPAR".split("").forEach((letter, i) => {
      const lz = sign.z + (i - 3) * 13.4, lx = sign.x - 92;
      const ground = sign.h * Math.sqrt(Math.max(0, 1 - Math.pow(Math.hypot(lx - sign.x, lz - sign.z) / sign.r, 2))) - 2;
      props.push(box(0.7, 14, 0.7, "#3b4252", { x: lx + 0.6, y: ground + 3, z: lz }));
      archSigns.push({ x: lx, y: ground + 15, z: lz, ry: -Math.PI / 2, size: 12, color: BRAND, text: letter, bg: "#ffffff" });
    });
    peaks.forEach((pk) => { pk.y = -2; }); // des dômes : le centre de la boule est au sol
    const peakGeo = new THREE.SphereGeometry(1, 24, 16);
    instanced(group, peakGeo, M.far, peaks);

    const propsMesh = new THREE.Mesh(merge(props, true), M.props);
    propsMesh.castShadow = true;
    propsMesh.receiveShadow = true;
    group.add(propsMesh);
    // Plateau tournant du KingPar Tuning : damier jaune et noir au bord, flèches au centre.
    const plate = [cyl(3.9, 0.04, "#4a4f5c", { y: 0.02 }, 40)];
    for (let k = 0; k < 16; k++) {
      const a = (k / 16) * Math.PI * 2;
      plate.push(box(0.72, 0.012, 1.0, k % 2 ? "#22252e" : "#ffd60a", { x: Math.sin(a) * 3.38, y: 0.045, z: Math.cos(a) * 3.38, ry: a }));
    }
    podium.mesh = new THREE.Mesh(merge(plate, true), M.props);
    podium.mesh.position.set(podium.x, 0.062, podium.z);
    podium.mesh.receiveShadow = true;
    group.add(podium.mesh);

    // Guérite : vitrage (s'éclaire la nuit)
    const glass = new THREE.Mesh(new THREE.BoxGeometry(2.66, 0.95, 3.06), M.boothGlass);
    glass.position.set(-3.4, 1.55, -3.4);
    group.add(glass);

    // Écrans des bornes, voyants des bornes de recharge
    instanced(group, new THREE.BoxGeometry(1, 1, 1), M.screen, [
      { x: LANE / 2 - 0.37, y: 1.25, z: -3.6, sx: 0.03, sy: 0.4, sz: 0.24 },
      { x: LANE / 2 + 0.37, y: 1.25, z: 3.4, sx: 0.03, sy: 0.4, sz: 0.24 },
      { x: RESA_KIOSK.x, y: 1.4, z: RESA_KIOSK.z - 0.24, sx: 0.62, sy: 0.52, sz: 0.03 },
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
    const ring = (x, z, pink, y0) => trees.push({
      x: x + (rnd() - 0.5) * (pink || y0 != null ? 0.6 : 1.5), z: z + (rnd() - 0.5) * (pink || y0 != null ? 0.6 : 1.5),
      s: pink ? 0.95 + rnd() * 0.45 : 0.8 + rnd() * 0.6, pink: Boolean(pink), y0: y0 || 0,
    });
    for (let z = 4; z < D; z += 8) { ring(L.xMin - 4.5, z); ring(L.xMax + 4.6, z); }
    for (let x = L.xMin; x < L.xMax + 3; x += 8) ring(x, D + 4.8);
    for (let x = LANE + 7; x < L.xMax + 2; x += 9) ring(x, -4.6);
    const inCity = (x, z) => x > X0 - 22 && x < cityX1 + 14 && z > vz0 - 4 && z < vz1 + 4;
    for (let i = 0; i < 46; i++) {
      const x = L.cx - 210 + rnd() * 420, z = ROAD_Z - 12 - rnd() * 90;
      if (!inCity(x, z)) ring(x, z);
    }
    cityTrees.forEach((t) => ring(t[0], t[1], t[2], t[3]));
    // Lisière boisée autour du village
    for (let i = 0; i < 70; i++) {
      const x = X0 - 10 + rnd() * (cityX1 - X0 + 30), north = rnd() < 0.5;
      const z = north ? vz1 + 4 + rnd() * 26 : vz0 - 6 - rnd() * 24;
      ring(x, z, rnd() < 0.2);
    }
    for (let i = 0; i < 70; i++) {
      const a = rnd() * Math.PI * 2, r = Math.max(W, D) * 0.75 + 22 + rnd() * 150;
      const x = L.cx + Math.cos(a) * r, z = D / 2 + Math.sin(a) * r;
      if (z < ROAD_Z + 9 && z > ROAD_Z - 9) continue;
      if (x > -42 && x < L.xMax + 6 && z > -10 && z < D + 6) continue;
      if (inCity(x, z)) continue;
      ring(x, z);
    }
    for (let i = trees.length - 1; i >= 0; i--) { // l'aire du KingPar Tuning reste dégagée
      if (Math.abs(trees[i].x - tg.x) < 18 && trees[i].z < R - 3 && trees[i].z > R - 30) trees.splice(i, 1);
    }
    instanced(group, new THREE.CylinderGeometry(0.24, 0.36, 1.8, 10), M.trunk,
      trees.map((t) => ({ x: t.x, y: t.y0 + 0.9 * t.s, z: t.z, sy: t.s })), "cast");
    const greens = ["#4fb957", "#5cc95a", "#6fd36a", "#49b05a", "#7ed36f", "#58c26b"];
    const lighter = (color) => "#" + new THREE.Color(color).lerp(new THREE.Color("#ffffff"), 0.22).getHexString();
    const leaves = [];
    trees.forEach((t) => {
      if (t.pink) {
        // Cerisier en fleurs : une couronne large et ronde, en trois touffes roses.
        const pick = () => BLOSSOM[Math.floor(rnd() * BLOSSOM.length)];
        leaves.push({ x: t.x, y: t.y0 + 2.9 * t.s, z: t.z, sx: 2.2 * t.s, sy: 1.6 * t.s, sz: 2.2 * t.s, ry: rnd() * 6, color: pick() });
        leaves.push({ x: t.x + 0.9 * t.s, y: t.y0 + 3.5 * t.s, z: t.z + 0.5 * t.s, sx: 1.5 * t.s, sy: 1.25 * t.s, sz: 1.5 * t.s, ry: rnd() * 6, color: pick() });
        leaves.push({ x: t.x - 0.8 * t.s, y: t.y0 + 3.7 * t.s, z: t.z - 0.6 * t.s, sx: 1.4 * t.s, sy: 1.2 * t.s, sz: 1.4 * t.s, ry: rnd() * 6, color: pick() });
        leaves.push({ x: t.x - 0.5 * t.s, y: t.y0 + 4.1 * t.s, z: t.z + 0.5 * t.s, sx: 0.8 * t.s, sy: 0.7 * t.s, sz: 0.8 * t.s, color: "#ffe3ec" }); // reflet
        for (let k = 0; k < 4; k++) {
          const a = k * 1.57 + rnd() * 0.8;
          leaves.push({ x: t.x + Math.cos(a) * 1.5 * t.s, y: t.y0 + (2.7 + (k % 2) * 0.5) * t.s, z: t.z + Math.sin(a) * 1.5 * t.s, sx: 1.0 * t.s, sy: 0.85 * t.s, sz: 1.0 * t.s, color: pick() });
        }
        return;
      }
      const color = greens[Math.floor(rnd() * greens.length)];
      for (let k = 0; k < 4; k++) { // des bosses tout autour : une couronne touffue
        const a = k * 1.57 + rnd() * 0.8;
        leaves.push({ x: t.x + Math.cos(a) * 1.0 * t.s, y: t.y0 + (2.35 + (k % 2) * 0.85) * t.s, z: t.z + Math.sin(a) * 1.0 * t.s, sx: 0.9 * t.s, sy: 0.85 * t.s, sz: 0.9 * t.s, color: k % 2 ? lighter(color) : color });
      }
      leaves.push({ x: t.x, y: t.y0 + 2.6 * t.s, z: t.z, sx: 1.7 * t.s, sy: 1.9 * t.s, sz: 1.7 * t.s, ry: rnd() * 6, color });
      leaves.push({ x: t.x + 0.3, y: t.y0 + 3.9 * t.s, z: t.z - 0.2, sx: 1.15 * t.s, sy: 1.3 * t.s, sz: 1.15 * t.s, ry: rnd() * 6, color });
      leaves.push({ x: t.x - 0.55 * t.s, y: t.y0 + 3.5 * t.s, z: t.z + 0.6 * t.s, sx: 0.8 * t.s, sy: 0.85 * t.s, sz: 0.8 * t.s, color: lighter(color) }); // reflet
      leaves.push({ x: t.x + 0.75 * t.s, y: t.y0 + 2.9 * t.s, z: t.z + 0.55 * t.s, sx: 0.95 * t.s, sy: 1.0 * t.s, sz: 0.95 * t.s, color });
      if (rnd() < 0.3) [[0.9, 2.6, 1.0], [-0.9, 3.0, 0.9], [0.2, 2.2, 1.45]].forEach((at) => { // pommes
        leaves.push({ x: t.x + at[0] * t.s, y: t.y0 + at[1] * t.s, z: t.z + at[2] * t.s, sx: 0.2, sy: 0.2, sz: 0.2, color: "#e2372f" });
      });
    });
    cityLeaves.forEach((l) => leaves.push(l));
    for (let i = 0; i < 16; i++) { // rochers ronds
      const x = X0 - 30 + rnd() * (cityX1 - X0 + 40), z = vz0 + rnd() * (vz1 - vz0), rs = 0.5 + rnd() * 0.5;
      if (Math.abs(z - ROAD_Z) < 7) continue;
      leaves.push({ x, y: rs * 0.45, z, sx: rs * 1.2, sy: rs * 0.75, sz: rs, ry: rnd() * 3, color: i % 2 ? "#b9b4a6" : "#a39d92" });
    }
    // Fleurs et buissons ronds, semés dans le village et autour du parking.
    const petalsOf = ["#ff7aa8", "#ffd60a", "#ffffff", "#ff9f1c", "#b388ff", "#ff5d6c"];
    for (let i = 0; i < 340; i++) {
      const x = X0 - 60 + rnd() * (cityX1 - X0 + 70), z = vz0 + rnd() * (vz1 - vz0);
      if (Math.abs(z - ROAD_Z) < 5.5) continue;
      if (i % 9 === 0) {
        const bs = 0.45 + rnd() * 0.4, color = greens[i % greens.length];
        leaves.push({ x, y: bs * 0.75, z, sx: bs * 1.25, sy: bs, sz: bs * 1.25, color });
        leaves.push({ x: x + bs * 0.7, y: bs * 0.6, z: z + 0.2, sx: bs * 0.85, sy: bs * 0.75, sz: bs * 0.85, color: lighter(color) });
      } else {
        leaves.push({ x, y: 0.2, z, sx: 0.035, sy: 0.2, sz: 0.035, color: "#49b05a" });
        leaves.push({ x, y: 0.42, z, sx: 0.15, sy: 0.11, sz: 0.15, color: petalsOf[i % petalsOf.length] });
        leaves.push({ x, y: 0.47, z, sx: 0.06, sy: 0.06, sz: 0.06, color: "#ffd60a" });
      }
    }
    L.islands.forEach((it) => {
      leaves.push({ x: it.x, y: 0.55, z: it.z - 1.2, sx: 0.6, sy: 0.6, sz: 0.6, color: "#3f9447" });
      leaves.push({ x: it.x, y: 0.55, z: it.z + 1.2, sx: 0.6, sy: 0.6, sz: 0.6, color: "#2f7d3b" });
      leaves.push({ x: it.x, y: 0.7, z: it.z, sx: 0.75, sy: 0.75, sz: 0.75, color: "#4fa64f" });
    });
    instanced(group, new THREE.SphereGeometry(1, 16, 12), M.foliage, leaves, "cast");

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
    // Enseignes des commerces, panneau « Bienvenue »
    const board = (w, h, text, bg, fg, x, y, z, ry) => {
      const mat = signMaterial(512, (ctx, cw, ch) => {
        ctx.fillStyle = bg; ctx.fillRect(0, 0, cw, ch);
        ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        let size = ch * 0.58;
        ctx.font = "800 " + size + "px system-ui, sans-serif";
        while (ctx.measureText(text).width > cw * 0.92 && size > 10) { size -= 2; ctx.font = "800 " + size + "px system-ui, sans-serif"; }
        ctx.fillText(text, cw / 2, ch * 0.54);
      }, Math.max(48, Math.round((512 * h) / w)));
      signMats.push(mat);
      textures.push(mat.map);
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
      mesh.position.set(x, y, z);
      mesh.rotation.y = ry;
      group.add(mesh);
    };
    shopSigns.forEach((sg) => board(sg.w, 0.72, sg.text, "#fdf6e3", sg.color, sg.x, 2.86, sg.z, sg.ry));
    stallSigns.forEach((sg) => board(2.5, 0.42, sg.text, "#fdf6e3", sg.color, sg.x, 0.55, sg.z, sg.ry));
    board(0.7, 0.26, "TICKET CHANCE", "#fdf6e3", BRAND, omi.x, top + 0.42, omi.z - 0.305, Math.PI);
    board(2.0, 0.5, MASCOT.toUpperCase() + " · NOTRE MASCOTTE", "#3b2a20", "#fdf6e3", mascot.x, 0.62, mascot.z - 1.16, Math.PI);
    signBoards.forEach((b) => board(b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8]));
    // Grand panneau au bord de la route : les vraies places libres du parking, en direct.
    const liveCanvas = document.createElement("canvas");
    liveCanvas.width = 512; liveCanvas.height = 256;
    const liveTex = new THREE.CanvasTexture(liveCanvas);
    liveTex.colorSpace = THREE.SRGBColorSpace;
    textures.push(liveTex);
    const liveMat = new THREE.MeshBasicMaterial({ map: liveTex, toneMapped: false });
    const liveAt = { x: gs.x + 16.4, z: R + 8.2 };
    [-1, 1].forEach((side) => {
      const face = new THREE.Mesh(new THREE.PlaneGeometry(7.2, 3.6), liveMat);
      face.position.set(liveAt.x + side * 0.16, 4.5, liveAt.z);
      face.rotation.y = (side * Math.PI) / 2;
      group.add(face);
    });
    const live = { ctx: liveCanvas.getContext("2d"), tex: liveTex, shown: "" };
    // Disques « P » des arches et du cube de la tour, lettres KINGPAR de la colline
    archSigns.forEach((sg) => {
      if (!sg.logo) { board(sg.size, sg.size, sg.text || "P", sg.bg || sg.color, sg.bg ? sg.color : "#ffffff", sg.x, sg.y, sg.z, sg.ry); return; }
      const face = new THREE.Mesh(new THREE.PlaneGeometry(sg.size, sg.size), M.logo); // le logo KingPar
      face.position.set(sg.x, sg.y, sg.z);
      face.rotation.y = sg.ry;
      group.add(face);
    });
    board(9.4, 1.0, "BIENVENUE À " + CITY_NAME.toUpperCase(), BRAND, "#ffffff", X0 - 12.42, 8.4, ROAD_Z, -Math.PI / 2);
    board(9.4, 1.0, "À BIENTÔT · KINGPAR", BRAND, "#ffffff", X0 - 11.58, 8.4, ROAD_Z, Math.PI / 2);
    // Lueurs du village : bornes lumineuses, ampoules des guirlandes, halos au sol
    instanced(group, new THREE.BoxGeometry(1, 1, 1), M.bulb, lanternGlow);
    instanced(group, flat(1, 1), M.pool, lanternPools);
    instanced(group, new THREE.SphereGeometry(1, 10, 8), M.chochin, lampions);
    // Pétales de cerisier qui tombent sur le village
    const petalCount = 900, petalPos = new Float32Array(petalCount * 3), petalSeed = [];
    const pRnd = mulberry(88);
    for (let i = 0; i < petalCount; i++) {
      petalPos[i * 3] = X0 - 16 + pRnd() * (cityX1 - X0 + 30);
      petalPos[i * 3 + 1] = 0.3 + pRnd() * 13;
      petalPos[i * 3 + 2] = vz0 + pRnd() * (vz1 - vz0);
      petalSeed.push(pRnd() * 6.28);
    }
    const petalGeo = new THREE.BufferGeometry();
    petalGeo.setAttribute("position", new THREE.BufferAttribute(petalPos, 3));
    const petals = new THREE.Points(petalGeo, M.petal);
    petals.frustumCulled = false;
    petals.userData.seed = petalSeed;
    group.add(petals);
    // Feu d'artifice (tiré quand on sonne la cloche du belvédère, ou quand le carnet est complet)
    const sparkCount = 420, sparkGeo = new THREE.BufferGeometry();
    const sparkPos = new Float32Array(sparkCount * 3).fill(-999);
    sparkGeo.setAttribute("position", new THREE.BufferAttribute(sparkPos, 3));
    sparkGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(sparkCount * 3), 3));
    const sparks = new THREE.Points(sparkGeo, M.spark);
    sparks.frustumCulled = false;
    group.add(sparks);
    const fireworks = { points: sparks, vel: new Float32Array(sparkCount * 3), life: new Float32Array(sparkCount), base: new Float32Array(sparkCount * 3), left: 0, next: 0, slot: 0 };
    // Façade du distributeur
    board(0.95, 1.2, "BOISSONS", "#1f6f5c", "#fdf6e3", vend.x, 0.95, vend.z - 0.41, Math.PI);
    // Carpes de l'étang
    const koi = [];
    if (pond) {
      for (let i = 0; i < 5; i++) {
        const fish = new THREE.Mesh(new THREE.SphereGeometry(0.22, 8, 6), i % 2 ? M.koi : M.stone);
        fish.scale.set(0.5, 0.3, 1.5);
        fish.userData = { a: i * 1.3, r: 0.45 + (i % 3) * 0.2, speed: 0.35 + i * 0.06 };
        group.add(fish);
        koi.push(fish);
      }
    }
    board(4.8, 0.95, "LIBRE-SERVICE", "#d92b3a", "#ffffff", -19.5, 3.5, RENTAL_Z + 3.62, Math.PI);

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
      let capacity = MODELS[name].traffic ? 16 : 0;
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
    tag("Réservation", RESA_KIOSK.x, 3.9, RESA_KIOSK.z, "#1e66f5", true).node.style.background = "#1e66f5";
    const dogTag = tag("Ouaf !", 0, 1, 0, null, true);
    dogTag.node.classList.add("bubble");
    dogTag.hidden = true;
    const playerTag = tag("…", 0, 2.3, 0, null, true);
    playerTag.node.classList.add("bubble");
    playerTag.hidden = true;
    const resaSign = new THREE.Sprite(M.resa);
    resaSign.scale.set(1.5, 1.5, 1);
    resaSign.position.set(RESA_KIOSK.x, 2.95, RESA_KIOSK.z);
    group.add(resaSign);

    // Promeneur : obstacles fixes (x0, x1, z0, z1), points d'interaction, emprise des zones
    const obstacles = [
      [-4.75, -2.05, -4.95, -1.85], // guérite
      [RESA_KIOSK.x - 0.6, RESA_KIOSK.x + 0.6, RESA_KIOSK.z - 0.4, RESA_KIOSK.z + 0.4],
      [RESA_KIOSK.x - 2.2, RESA_KIOSK.x - 1.6, RESA_KIOSK.z - 3.0, RESA_KIOSK.z - 1.4],
      [RESA_KIOSK.x + 1.6, RESA_KIOSK.x + 2.2, RESA_KIOSK.z - 3.0, RESA_KIOSK.z - 1.4],
      [LANE / 2 - 0.45, LANE / 2 + 0.45, -4.35, 3.15], // îlot, bornes et socles des barrières
      [-1.1, -0.7, -2.4, -2.0], [LANE + 0.7, LANE + 1.1, -2.4, -2.0], // portique
      [-4.55, -4.25, -8.35, -8.05], // totem
      [L.xMax + 0.65, L.xMax + 1.55, -1, D + 1.6], // haies
      [L.xMin - 1.6, L.xMax + 1.6, D + 0.65, D + 1.55],
      [L.xMin - 1.55, L.xMin - 0.65, 6, D],
      [LANE + 3, L.xMax + 1.55, -1.55, -0.65],
    ];
    trees.forEach((t) => obstacles.push([t.x - 0.28, t.x + 0.28, t.z - 0.28, t.z + 0.28]));
    cityObstacles.forEach((o) => obstacles.push(o));
    obstacles.push([-19.7, -19.3, RENTAL_Z + 3.5, RENTAL_Z + 3.9]); // panneau du libre-service
    lampSpots.forEach((l, i) => { if (i % 2 === 0) obstacles.push([l.x - 0.15, l.x + 0.15, l.z + 2.05, l.z + 2.35]); });
    const points = [{ x: RESA_KIOSK.x, z: RESA_KIOSK.z - 1.0, label: "Consulter la borne de réservation", action: openResa }].concat(cityPoints);
    if (opts.onUseBorne) {
      points.push({ x: LANE / 2 - 0.9, z: -3.6, label: "Utiliser la borne d'entrée", action: () => opts.onUseBorne(1) });
      points.push({ x: LANE / 2 + 0.9, z: 3.4, label: "Utiliser la borne de sortie", action: () => opts.onUseBorne(2) });
    }
    zones.forEach((zone) => {
      let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
      zone.spots.forEach((sp) => {
        x0 = Math.min(x0, sp.x - sp.w / 2); x1 = Math.max(x1, sp.x + sp.w / 2);
        z0 = Math.min(z0, sp.z - sp.d / 2, sp.aisleZ); z1 = Math.max(z1, sp.z + sp.d / 2, sp.aisleZ);
      });
      zone.bounds = [x0, x1, z0, z1];
    });
    group.add(player.root, dog.root, agent.root, driveLight);
    const agentTag = tag("…", 0, 2.3, 0, null, true);
    agentTag.node.classList.add("bubble");
    agentTag.hidden = true;
    npc.x = LANE + 0.35; npc.z = L.aisles.length ? L.aisles[0] : 6; npc.path = null; npc.wait = 2;
    rentals.forEach((r) => group.add(r.root));
    tag("Véhicules à conduire", -19.5, 4.9, RENTAL_Z + 3.7, null, true).node.style.background = "#d92b3a";
    tag("KingPar Tuning", podium.x, 6.2, podium.z, null, true).node.style.background = "#22252e";
    // Le gros bouton rouge, sur son îlot au milieu de la route : il lance la pub KingPar.
    const adBtn = { x: SPAWN.x, z: ROAD_Z, mesh: null, press: 0 };
    const island = [cyl(0.74, 0.12, "#ffd60a", { y: 0.06 }, 24), cyl(0.36, 0.86, "#f4f5f7", { y: 0.55 }, 16), cyl(0.5, 0.12, "#22252e", { y: 1.0 }, 20)];
    for (let k = 0; k < 8; k += 2) {
      const a = (k / 8) * Math.PI * 2 + 0.39;
      island.push(box(0.3, 0.125, 0.4, "#22252e", { x: Math.sin(a) * 0.55, y: 0.062, z: Math.cos(a) * 0.55, ry: a }));
    }
    const islandMesh = new THREE.Mesh(merge(island, true), M.props);
    islandMesh.position.set(adBtn.x, 0.03, adBtn.z);
    islandMesh.castShadow = islandMesh.receiveShadow = true;
    adBtn.mesh = new THREE.Mesh(new THREE.SphereGeometry(0.43, 24, 14, 0, Math.PI * 2, 0, Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: 0xe0202e, emissive: 0xff1a2a, emissiveIntensity: 0.35, roughness: 0.3, metalness: 0.1 }));
    adBtn.mesh.position.set(adBtn.x, 1.09, adBtn.z);
    adBtn.mesh.castShadow = true;
    group.add(islandMesh, adBtn.mesh);
    obstacles.push([adBtn.x - 0.45, adBtn.x + 0.45, adBtn.z - 0.45, adBtn.z + 0.45]);
    points.push({ x: adBtn.x, z: adBtn.z, label: "Appuyer sur le gros bouton rouge", action: startAd });
    tag("NE PAS APPUYER", adBtn.x, 2.25, adBtn.z, null, true).node.style.background = "#d92b3a";
    tag(CITY_NAME, (X0 + cityX1) / 2, 46, ROAD_Z, null, true);
    const city = { x0: X0, x1: cityX1, z0: vz0, z1: vz1, pond, hill, petals, koi, fireworks, gate: tx, bay, pumps: { x: gs.x, z: gz }, podium, mech, adBtn };
    // La Kingfarm, au sud des champs : potager de citrouilles, verger à cogner, mine à ciel ouvert.
    const farm = { x: X0 + 104, z: R - 75, nodes: [] };
    const addNode = (kind, x, z, parts) => {
      const mesh = limb(parts);
      mesh.position.set(x, 0, z);
      group.add(mesh);
      const node = { kind, x, z, mesh, hp: FARM[kind].hp, out: 0, shake: 0 };
      node.action = { label: FARM[kind].verb, action: () => hitNode(node) };
      farm.nodes.push(node);
    };
    const timber = "#b9824f", plank = "#c9955f", rock = ["#a39d92", "#b9b4a6", "#8f897f"];
    const fx0 = farm.x - 19.4, fx1 = farm.x - 4.6, fz0 = farm.z - 4.4, fz1 = farm.z + 5.2;
    const decor = [box(fx1 - fx0 - 0.5, 0.1, fz1 - fz0 - 0.5, "#a9764d", { x: (fx0 + fx1) / 2, y: 0.05, z: (fz0 + fz1) / 2 })]; // la terre du potager
    const veg = ["#f28c28", "#ffd60a", "#fdf6e3", "#f28c28"];
    for (let k = 0; k < 15; k++) { // citrouilles posées sur leur feuillage, chacune sur sa butte
      const px = farm.x - 17.4 + (k % 5) * 2.7, pz = farm.z - 2.6 + Math.floor(k / 5) * 2.9;
      decor.push(orb(0.62, "#8f6240", { x: px, y: 0.08, z: pz, sy: 0.22 }));
      const parts = [orb(0.3, veg[k % 4], { y: 0.34, sy: 0.74 }), orb(0.3, shade(veg[k % 4], 0.9), { y: 0.34, sx: 0.55, sy: 0.76 }), cyl(0.03, 0.12, "#5a8f3c", { y: 0.6 }, 6)];
      for (let j = 0; j < 4; j++) parts.push(orb(0.24, j % 2 ? "#5cc95a" : "#49b05a", { x: Math.cos(j * 1.57 + 0.6) * 0.34, y: 0.17, z: Math.sin(j * 1.57 + 0.6) * 0.34, sy: 0.22 }));
      addNode("plante", px, pz, parts);
    }
    // Clôture en bois, ouverte au nord ; pompe à eau et seau
    for (let x = fx0; x <= fx1 + 0.01; x += 1.3) {
      decor.push(cyl(0.09, 1.0, timber, { x, y: 0.5, z: fz0 }, 8));
      if (Math.abs(x - (fx0 + fx1) / 2) > 1.2) decor.push(cyl(0.09, 1.0, timber, { x, y: 0.5, z: fz1 }, 8));
    }
    for (let z = fz0 + 1.24; z < fz1; z += 1.24) [fx0, fx1].forEach((x) => decor.push(cyl(0.09, 1.0, timber, { x, y: 0.5, z }, 8)));
    [0.45, 0.8].forEach((y) => {
      decor.push(box(fx1 - fx0, 0.07, 0.06, plank, { x: (fx0 + fx1) / 2, y, z: fz0 }));
      [fx0, fx1].forEach((x) => decor.push(box(0.06, 0.07, fz1 - fz0, plank, { x, y, z: (fz0 + fz1) / 2 })));
      [-1, 1].forEach((sx) => decor.push(box((fx1 - fx0) / 2 - 1.2, 0.07, 0.06, plank, { x: (fx0 + fx1) / 2 + sx * ((fx1 - fx0) / 4 + 0.6), y, z: fz1 })));
    });
    obstacles.push([fx0 - 0.1, fx1 + 0.1, fz0 - 0.1, fz0 + 0.1], [fx0 - 0.1, fx0 + 0.1, fz0, fz1], [fx1 - 0.1, fx1 + 0.1, fz0, fz1],
      [fx0, (fx0 + fx1) / 2 - 1.2, fz1 - 0.1, fz1 + 0.1], [(fx0 + fx1) / 2 + 1.2, fx1, fz1 - 0.1, fz1 + 0.1]);
    const pump = { x: fx1 + 1.4, z: fz1 - 0.6 };
    decor.push(box(0.5, 0.16, 0.5, "#cfc6b4", { x: pump.x, y: 0.08, z: pump.z }), cyl(0.11, 0.9, "#3f8f77", { x: pump.x, y: 0.6, z: pump.z }, 10),
      orb(0.16, "#3f8f77", { x: pump.x, y: 1.08, z: pump.z }), box(0.5, 0.07, 0.07, "#3f8f77", { x: pump.x + 0.25, y: 1.0, z: pump.z }),
      cyl(0.22, 0.34, "#8a5a3c", { x: pump.x + 0.75, y: 0.17, z: pump.z + 0.2 }, 12), cyl(0.19, 0.04, "#7fc8f0", { x: pump.x + 0.75, y: 0.33, z: pump.z + 0.2 }, 12));
    obstacles.push([pump.x - 0.3, pump.x + 1.0, pump.z - 0.3, pump.z + 0.45]);
    [[-1.5, 2.5], [1.5, -2.5], [4.5, 3], [6.5, -2], [-1, -6.5], [8, 5.5], [3, 7.5], [-3.5, 8], [9.5, -6.5]].forEach((at, k) => { // le verger : arbres touffus à pommes, à abattre
      const tx2 = farm.x + at[0], tz2 = farm.z + at[1], green = k % 2 ? "#4fb957" : "#5cc95a";
      const parts = [cyl(0.26, 1.5, timber, { y: 0.75 }, 10), cyl(0.36, 0.3, timber, { y: 0.15 }, 10), orb(1.15, green, { y: 2.35 })];
      for (let j = 0; j < 5; j++) parts.push(orb(0.72, j % 2 ? "#7ed36f" : green, { x: Math.cos(j * 1.26) * 0.9, y: 2.1 + (j % 2) * 0.75, z: Math.sin(j * 1.26) * 0.9 }));
      [[0.85, 2.0, 0.75], [-0.75, 1.85, 0.85], [0.1, 1.55, 1.2], [-1.0, 2.5, -0.6]].forEach((a) => parts.push(orb(0.14, "#e2372f", { x: a[0], y: a[1], z: a[2] })));
      addNode("bois", tx2, tz2, parts);
      obstacles.push([tx2 - 0.3, tx2 + 0.3, tz2 - 0.3, tz2 + 0.3]);
    });
    // La mine à ciel ouvert : un fer à cheval de gros rochers ronds, un portail en bois au nord,
    // des rails, un wagonnet, et quatre filons de pierres précieuses.
    const cave = { x: farm.x + 15, z: farm.z - 1, r: 5.2 };
    decor.push(cyl(cave.r + 0.5, 0.06, "#d6ccb8", { x: cave.x, y: 0.04, z: cave.z }, 30));
    for (let k = 0; k < 13; k++) {
      const a = (k / 13) * Math.PI * 2;
      if (Math.abs(angleTo(Math.PI / 2, a, 1) - Math.PI / 2) < 0.6) continue;
      const bx = cave.x + Math.cos(a) * (cave.r + 0.5), bz = cave.z + Math.sin(a) * (cave.r + 0.5);
      decor.push(orb(1.5, rock[k % 3], { x: bx, y: 0.95, z: bz, sy: 0.85 }));
      obstacles.push([bx - 1.3, bx + 1.3, bz - 1.3, bz + 1.3]);
    }
    /* La voûte de pierre : fermée vue de dehors ; quand on entre, elle s'efface
       et on voit l'intérieur de la grotte. */
    const vault = (radius, material) => {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 30, 14, Math.PI / 2 + 0.42, Math.PI * 2 - 0.84, 0, Math.PI / 2), material);
      mesh.position.set(cave.x, 0, cave.z);
      mesh.scale.y = 0.82;
      group.add(mesh);
      return mesh;
    };
    cave.outer = vault(cave.r + 1.0, new THREE.MeshStandardMaterial({ color: 0xa39d92, roughness: 1, flatShading: true }));
    cave.outer.castShadow = true;
    cave.inner = vault(cave.r + 0.9, new THREE.MeshStandardMaterial({ color: 0x6f6a78, roughness: 1, side: THREE.BackSide }));
    cave.inner.visible = false;
    const moss = [];
    for (let k = 0; k < 9; k++) { const a = k * 0.7 + 0.3, rr = 1.2 + (k % 3) * 1.5; moss.push(orb(0.9, k % 2 ? "#6fd36a" : "#58c26b", { x: Math.cos(a) * rr, y: Math.sqrt(Math.max(0.1, 38 - rr * rr)) * 0.82 + 0.1, z: Math.sin(a) * rr, sy: 0.35 })); }
    cave.outer.add(limb(moss));
    // La voûte se referme au-dessus du portail : il ne reste que l'arche d'entrée.
    cave.outer.add(new THREE.Mesh(new THREE.SphereGeometry(cave.r + 1.0, 8, 8, Math.PI / 2 - 0.43, 0.86, 0, 0.95), cave.outer.material));
    farm.cave = cave;
    const gateZ = cave.z + cave.r + 0.5; // le portail
    [-1.5, 1.5].forEach((dx) => { decor.push(box(0.32, 3.0, 0.32, "#8a5a3c", { x: cave.x + dx, y: 1.5, z: gateZ })); obstacles.push([cave.x + dx - 0.2, cave.x + dx + 0.2, gateZ - 0.2, gateZ + 0.2]); });
    decor.push(box(3.6, 0.34, 0.4, "#8a5a3c", { x: cave.x, y: 3.05, z: gateZ }), cyl(0.03, 0.4, "#22252e", { x: cave.x + 1.0, y: 2.7, z: gateZ }, 6), orb(0.16, "#ffd98a", { x: cave.x + 1.0, y: 2.45, z: gateZ }));
    [-0.4, 0.4].forEach((dx) => decor.push(box(0.07, 0.06, cave.r + 2.5, "#6b6f7a", { x: cave.x + dx, y: 0.1, z: cave.z + 1.6 }))); // rails
    for (let k = 0; k < 7; k++) decor.push(box(1.2, 0.05, 0.16, "#8a5a3c", { x: cave.x, y: 0.07, z: cave.z - 1.6 + k * 1.1 }));
    decor.push(box(1.0, 0.55, 0.75, "#6b6f7a", { x: cave.x, y: 0.55, z: cave.z - 0.6 }), box(0.86, 0.14, 0.6, "#3b3b3b", { x: cave.x, y: 0.8, z: cave.z - 0.6 }),
      orb(0.2, "#ffd60a", { x: cave.x - 0.15, y: 0.93, z: cave.z - 0.6 }), orb(0.16, BRAND, { x: cave.x + 0.2, y: 0.92, z: cave.z - 0.5 }));
    [-0.42, 0.42].forEach((dx) => [-0.85, -0.35].forEach((dz) => decor.push(cyl(0.14, 0.08, "#22252e", { x: cave.x + dx, y: 0.2, z: cave.z + dz, rz: Math.PI / 2 }, 10))));
    obstacles.push([cave.x - 0.6, cave.x + 0.6, cave.z - 1.1, cave.z - 0.1]);
    [[-3.0, -1.2, BRAND], [-1.6, -3.3, "#ffd60a"], [3.0, -0.9, "#ff5d8f"], [1.9, -3.2, "#17c3b2"]].forEach((at) => { // les filons
      const gem = (dx, dz, h2) => part(new THREE.OctahedronGeometry(0.26), at[2], { x: dx, y: h2, z: dz, sy: 1.5, ry: rnd() * 3 });
      addNode("minerai", cave.x + at[0], cave.z + at[1], [orb(0.7, rock[0], { y: 0.34, sy: 0.7 }), orb(0.45, rock[1], { x: 0.4, y: 0.25, z: 0.3, sy: 0.7 }), gem(-0.15, 0, 0.78), gem(0.25, 0.2, 0.6), gem(0.05, -0.3, 0.62)]);
    });
    [-3.2, 3.2].forEach((dx) => decor.push(box(0.22, 3.6, 0.22, "#8a5a3c", { x: farm.x - 11.8 + dx, y: 1.8, z: farm.z + 9 }))); // portique d'entrée
    group.add(limb(decor));
    board(6.2, 1.0, "KINGFARM", "#8a5a3c", "#fff8e7", farm.x - 11.8, 3.2, farm.z + 9.13, 0);
    board(6.2, 1.0, "KINGFARM", "#8a5a3c", "#fff8e7", farm.x - 11.8, 3.2, farm.z + 8.87, Math.PI);
    board(2.4, 0.5, "MINE", "#fff8e7", "#8a5a3c", cave.x, 3.05, gateZ + 0.21, 0);
    // Les habitants et leurs quêtes : chacun attend près de chez lui.
    const spots = {
      chat: [X0 + 103.5, R + 6.1, Math.PI], fleurs: [X0 + 13, R - 26, 0], cloche: [fete.x - 5.5, fete.z - 9.4, Math.PI],
      olives: [X0 + 65.6, R - 6.1, 0], coupe: [X0 + 26.6, R - 6.1, 0], colis: [gs.x - 3, gs.z + 3.2, Math.PI],
    };
    const folk = QUESTS.map((q) => {
      const at = spots[q.id], lk = q.look;
      const model = buildPerson({
        top: lk.top, hem: shade(lk.top, 0.72), skin: lk.skin, hair: lk.hair, pants: lk.pants, shoes: "#f4f5f7",
        hat: lk.hat, cut: lk.cut, outfit: lk.outfit, bottom: lk.bottom, extra: lk.extra, eyes: lk.eyes, small: true,
      });
      model.root.position.set(at[0], 0, at[1]);
      model.root.rotation.y = at[2];
      group.add(model.root);
      const mark = tag("!", at[0], 2.15, at[1], null, true);
      mark.node.classList.add("quest");
      obstacles.push([at[0] - 0.28, at[0] + 0.28, at[1] - 0.28, at[1] + 0.28]);
      points.push({ x: at[0] + Math.sin(at[2]) * 1.2, z: at[1] + Math.cos(at[2]) * 1.2, label: "Parler à " + q.who, action: () => talk(q.id) });
      return { id: q.id, x: at[0], z: at[1], rot: at[2], model, tag: mark };
    });
    const moustache = buildPet("chat"); // le chat de Mamie Gisèle, caché près de l'étang
    moustache.root.position.set(pond.x + 9.6, 0, pond.z + 6.6);
    moustache.root.rotation.y = -2.2;
    group.add(moustache.root);
    const goldFlower = new THREE.MeshBasicMaterial({ color: 0xffd60a, toneMapped: false });
    const blooms = [[X0 + 25, R - 24.4], [X0 + 49.5, R - 26.4], [X0 + 74, R - 24.4], [X0 + 98.5, R - 25.2], [X0 + 61.75, R - 53.2]].map((at) => {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.2, 12, 8), goldFlower);
      mesh.position.set(at[0], 0.55, at[1]);
      group.add(mesh);
      return { mesh, x: at[0], z: at[1] };
    });
    const quest = { folk, cat: { model: moustache, x: pond.x + 9.6, z: pond.z + 6.6 }, blooms, drop: { x: X0 + 52, z: R + 5.6 } };
    // Des papillons au-dessus des fleurs du village.
    const flyGeo = new THREE.BufferGeometry();
    flyGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(18 * 3), 3));
    const flyPoints = new THREE.Points(flyGeo, new THREE.PointsMaterial({ color: 0xffe066, size: 0.34, map: dotTexture, transparent: true, alphaTest: 0.2 }));
    flyPoints.frustumCulled = false;
    group.add(flyPoints);
    const flies = { points: flyPoints, home: Array.from({ length: 18 }, () => [X0 + 8 + rnd() * 150, vz0 + 24 + rnd() * (vz1 - vz0 - 48), rnd() * 6]) };
    // Le ticket d'or du jour : une cachette parmi douze, choisie par la date.
    const hides = [
      [mascot.x + 2.4, mascot.z + 1.6, 0], [pond.x, pond.z, 1.47], [hill.x + 5.2, hill.z + 8.4, hill.h], [fete.x - 13, fete.z + 9.4, 0],
      [laneS + 44, R - 58, 0], [laneS + 47, R - 71, 0], [gs.x - 9.5, gs.z + 10.4, 0], [L.xMax - 2, D - 2.2, 0],
      [pgx + 5.4, pgz - 5.4, 0], [X0 + 61.75, R - 24.6, 0], [tx - 4, R - 13, 0], [-23.5, RENTAL_Z + 5.6, 0],
    ];
    const today = new Date().toISOString().slice(0, 10), hide = hides[hash("or-" + today) % hides.length];
    const goldMesh = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.36, 0.05), new THREE.MeshBasicMaterial({ color: 0xffd60a, toneMapped: false }));
    goldMesh.position.set(hide[0], hide[2] + 1.15, hide[1]);
    goldMesh.visible = progress.goldDay !== today;
    group.add(goldMesh);
    const goldTicket = { mesh: goldMesh, x: hide[0], z: hide[1], day: today };
    // Étiquettes des autres promeneurs : créées et retirées au fil des arrivées.
    const addTag = (text) => { const t = tag(text, 0, 0, 0, null, true); t.node.classList.add("who"); return t; };
    const removeTag = (t) => { t.node.remove(); const i = tags.indexOf(t); if (i >= 0) tags.splice(i, 1); };
    const bounds = [L.cx - 150, cityX1 + 70, vz0 - 30, Math.max(D + 60, vz1 + 34)];

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

    // Repères « R » des véhicules entrés avec une réservation (toujours face caméra).
    const resaSprites = [];
    for (let i = 0; i < 48; i++) {
      const sprite = new THREE.Sprite(M.resa);
      sprite.scale.set(1.7, 1.7, 1);
      sprite.visible = false;
      sprite.renderOrder = 4;
      group.add(sprite);
      resaSprites.push(sprite);
    }

    lot = {
      L, group, zones, fleet, leds, rings, hover, gateIn, gateOut, textures, tags, resaSprites,
      obstacles, points, dogTag, agentTag, playerTag, addTag, removeTag, live, gold: goldTicket, quest, farm, flies, D, city, bounds, decor: [], seq: 0, pickDirty: true,
    };
    spawnTraffic();
    refreshQuests();
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
    // Voitures garées le long de l'avenue, en ville (décor ; on les contourne).
    const c = lot.city;
    for (let i = 0; i < 8; i++) {
      const name = names[(i * 3 + 1) % names.length];
      const v = createVehicle(name, PAINTS[(i * 7 + 2) % PAINTS.length]);
      if (!v) continue;
      v.state = "traffic";
      const north = i % 2 === 0;
      const x = c.x0 + 14 + Math.floor(i / 2) * CITY_PITCH + (north ? 0 : 9);
      const z = ROAD_Z + (north ? 3.55 : -3.55), rot = north ? Math.PI / 2 : -Math.PI / 2;
      place(v, x, z, rot, 1);
      lot.decor.push({ x, z, rot });
    }
    for (let i = 0; i < 6; i++) {
      const name = names[i % names.length];
      const v = createVehicle(name, PAINTS[(i * 5 + 3) % PAINTS.length]);
      if (!v) continue;
      v.state = "traffic";
      const far = i % 2 === 1;
      const west = lot.L.cx - 170, east = c.x1 + 110;
      const x0 = far ? east : west, x1 = far ? west : east;
      const path = makePath([[x0, far ? ROAD_FAR : ROAD_NEAR], [x1, far ? ROAD_FAR : ROAD_NEAR]], 1);
      const mover = { v, path, s: 0, speed: 12 + i * 1.3, delay: 2 + i * 5.5, loop: true, cruise: true };
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
        zone.reserved = z.reserved; zone.reservedN = z.reservedN; zone.reservable = z.reservable;
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
    markReservations();
    refreshSpots();
    renderLegend();
    firstSync = false;
  }

  /* Véhicules entrés avec une réservation : un « R » bleu flotte au-dessus.
     Dashboard : ceux dont la présence d'Access le dit. Borne (et démo) : le
     nombre par zone, appliqué aux plus anciens véhicules garés de la zone. */
  function markReservations() {
    lot.zones.forEach((zone) => {
      const known = zone.vehicles.some((v) => v.info);
      let left = known ? 0 : zone.reservedN || 0;
      zone.vehicles.slice().sort((a, b) => a.id - b.id).forEach((v) => {
        if (known) v.reserved = Boolean(v.info && v.info.reservation);
        else { v.reserved = left > 0; if (v.reserved) left--; }
      });
    });
  }

  function assignPresences() {
    if (!lot) return;
    const byZone = {};
    // Dashboard : le nombre de réservations par zone se lit dans les présences.
    if (data.source === "live" && presences.length) {
      const counts = {};
      presences.forEach((p) => { if (p.reservation) counts[categoryOfPresence(p)] = (counts[categoryOfPresence(p)] || 0) + 1; });
      lot.zones.forEach((zone) => {
        if (zone.reserved == null) { zone.reserved = counts[zone.name] || 0; zone.reservedN = zone.reserved; }
      });
    }
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
      const extra = (zone.held ? " · " + zone.held + " en attente" : "") + (zone.reserved ? " · " + zone.reserved + " R" : "");
      b.append(elem("i"), elem("em", null, zone.label), elem("span", null, zone.taken + "/" + zone.cap + extra), bar);
      if (zone.reserved) b.title += " · " + zone.reserved + " véhicule(s) entré(s) avec une réservation";
      b.addEventListener("click", () => focusZone(zone));
      legend.appendChild(b);
    });
    const reservedTotal = lot.zones.reduce((s, z) => s + (z.reserved || 0), 0);
    if (reservedTotal) {
      const note = elem("div", "p3d-note p3d-resa");
      note.append(elem("i", null, "R"), document.createTextNode(reservedTotal + " véhicule(s) entré(s) avec une réservation"));
      legend.appendChild(note);
    }
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
    if (walk.on) {
      // Tactile : pouce gauche = manette de déplacement, le reste = regarder.
      const rect = canvas.getBoundingClientRect();
      const stick = e.pointerType === "touch" && e.clientX - rect.left < rect.width * 0.45 && !walk.joy;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, ox: e.clientX, oy: e.clientY, stick });
      if (stick) {
        walk.joy = { x: 0, y: 0, mag: 0 };
        joy.style.transform = "translate(" + (e.clientX - rect.left) + "px," + (e.clientY - rect.top) + "px)";
        joyKnob.style.transform = "";
        joy.classList.add("on");
      }
      dragMoved = 0;
      return;
    }
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
    if (walk.on) {
      if (p.stick) {
        const jx = clamp((e.clientX - p.ox) / 55, -1, 1), jy = clamp((e.clientY - p.oy) / 55, -1, 1);
        const mag = Math.min(1, Math.hypot(jx, jy));
        walk.joy = { x: jx, y: jy, mag };
        joyKnob.style.transform = "translate(" + jx * 34 + "px," + jy * 34 + "px)";
      } else {
        walk.yaw -= dx * 0.006;
        walk.pitch = clamp(walk.pitch + dy * 0.004, 0.06, 1.25);
        walk.look = performance.now() / 1000; // en voiture, la caméra ne se recale pas tout de suite
      }
      return;
    }
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
    const released = pointers.get(e.pointerId);
    const had = pointers.delete(e.pointerId);
    if (!pointers.size) canvas.classList.remove("dragging");
    pinch = 0;
    if (released && released.stick) { walk.joy = null; joy.classList.remove("on"); }
    if (walk.on) return;
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
    if (walk.on) { walk.dist = clamp(walk.dist * Math.exp(e.deltaY * 0.0011), 3, 18); return; }
    cam.gRadius = clamp(cam.gRadius * Math.exp(e.deltaY * 0.0011), cam.min, cam.max);
    idle = 0;
  }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    if (walk.on) return; // les touches pilotent le promeneur
    const step = { ArrowLeft: [0.12, 0], ArrowRight: [-0.12, 0], ArrowUp: [0, -0.06], ArrowDown: [0, 0.06] }[e.key];
    if (step) { cam.gTheta += step[0]; cam.gPhi = clamp(cam.gPhi + step[1], 0.18, 1.46); idle = 0; e.preventDefault(); }
    if (e.key === "+" || e.key === "=") cam.gRadius = clamp(cam.gRadius * 0.88, cam.min, cam.max);
    if (e.key === "-") cam.gRadius = clamp(cam.gRadius * 1.14, cam.min, cam.max);
    if (e.key === "0" || e.key === "Home") overview();
  });

  // --- Promenade ------------------------------------------------------------------------------
  // Touches lues par leur position (ZQSD sur un clavier français, WASD sinon).
  function onKey(e, down) {
    if (!walk.on || !active) return;
    const t = e.target;
    if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || "")) return;
    // Dans un panneau ouvert, Entrée et Espace servent aux boutons qui ont le focus.
    if (t && t.tagName === "BUTTON" && panel.contains(t) && e.code !== "Escape") return;
    if (walk.game && e.code !== "Escape") { // un mini-jeu est ouvert : les touches sont pour lui
      walk.game.key(e.code, down);
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (e.code === "Escape") {
      if (down) { if (walk.panel) closeResa(); else setWalk(false); }
    } else if (WALK_KEYS[e.code]) {
      walk.keys[e.code] = down;
    } else if (e.code === "KeyE" || e.code === "Enter") {
      if (down && !e.repeat) { if (walk.panel) closeResa(); else interact(); }
    } else if (e.code === "KeyF") {
      if (down && !e.repeat) { bark(); sound([[980 / dog.def.scale, 0.07, 0], [760 / dog.def.scale, 0.06, 0.09]], 0.13, "triangle", true); }
    } else if (e.code === "KeyH") {
      if (down && !e.repeat && walk.drive) { honk(garage[walk.drive.def.model].horn); walk.honks = (walk.honks || 0) + 1; if (walk.honks >= 5) win("chef"); }
    } else if (e.code === "KeyC") {
      if (down && !e.repeat) { if (walk.panel) closeResa(); else openCarnet(); }
    } else if (/^Digit[1-4]$/.test(e.code)) {
      if (down && !e.repeat && !walk.panel) emote(Number(e.code.slice(5)) - 1);
    } else if (e.code === "KeyP") {
      if (down && !e.repeat) { if (walk.panel) closeResa(); else photo(); }
    } else {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }
  const keyDown = (e) => onKey(e, true), keyUp = (e) => onKey(e, false);
  const keyBlur = () => { walk.keys = {}; };
  window.addEventListener("keydown", keyDown, true);
  window.addEventListener("keyup", keyUp, true);
  window.addEventListener("blur", keyBlur);

  function setWalk(on) {
    if (!lot || walk.on === on) return;
    if (!on && walk.ad) endAd();
    if (!on && walk.drive) exitVehicle();
    if (!on && walk.ride) stopRide();
    walk.on = on;
    walk.keys = {};
    walk.joy = null;
    joy.classList.remove("on");
    pointers.clear();
    setHover(null);
    container.classList.toggle("walking", on);
    walkBtn.setAttribute("aria-pressed", String(on));
    hint.textContent = on ? HINT_WALK : HINT_ORBIT;
    if (on) {
      walk.yaw = walk.rot; // caméra dans le dos du personnage
      walk.dog.next = 1.2;
      net.wait = 0.1; // on rejoint les autres promeneurs tout de suite
      canvas.focus({ preventScroll: true });
      if (!walk.met) {
        walk.met = true;
        const today = new Date().toISOString().slice(0, 10);
        if (progress.day && progress.day !== today) win("fidele");
        if (!progress.day) { progress.day = today; saveProgress(); }
        toast(carnet.size >= STAMPS.length
          ? "Carnet complet. Le village de " + CITY_NAME + " vous attend toujours, par la route de l'est."
          : "Carnet de tampons : " + STAMPS.length + " choses à découvrir, du parking au village. Touche C pour l'ouvrir.", 6);
      }
    } else {
      closeResa();
      saveProgress();
      net.wait = 0.2; // on redevient simple spectateur
      toastBox.classList.remove("on");
      walk.toast = 0; walk.say = 0;
      lot.playerTag.hidden = true;
      prompt.classList.remove("on");
      here.classList.remove("on");
      walk.near = null;
      walk.zone = null;
      // Retour à la vue d'ensemble, centrée sur l'endroit où l'on se trouvait.
      cam.gx = clamp(walk.x - lot.L.cx, -cam.bx, cam.bx);
      cam.gz = clamp(walk.z - lot.L.cz, -cam.bz, cam.bz);
      cam.tx = cam.gx; cam.tz = cam.gz;
      cam.theta = cam.gTheta = walk.yaw + Math.PI;
      cam.radius = walk.dist * 1.4;
      cam.gRadius = cam.home * 0.7;
      idle = 0;
    }
    width = 0; // recalcule le cadrage (champ plus large en promenade)
  }

  function collide(px, pz, r, skip) {
    // Obstacle rond (véhicule posé n'importe comment) : trois cercles le long de sa longueur.
    const round = (ox, oz, rot, half, or) => {
      const fx = Math.sin(rot) * half * 0.85, fz = Math.cos(rot) * half * 0.85;
      for (let kk = -1; kk <= 1; kk++) {
        const dx = px - (ox + fx * kk), dz = pz - (oz + fz * kk), dd = Math.hypot(dx, dz), min = r + or;
        if (dd >= min) continue;
        if (dd < 1e-6) { px += min; continue; }
        px = ox + fx * kk + (dx / dd) * min; pz = oz + fz * kk + (dz / dd) * min;
      }
    };
    rentals.forEach((rv) => { if (rv !== skip) round(rv.x, rv.z, rv.rot, rv.def.half, rv.def.r); });
    lot.decor.forEach((c) => round(c.x, c.z, c.rot, 1.45, 1.0));
    const hit = (x0, x1, z0, z1) => {
      const cx = clamp(px, x0, x1), cz = clamp(pz, z0, z1);
      const dx = px - cx, dz = pz - cz, d2 = dx * dx + dz * dz;
      if (d2 >= r * r) return;
      if (d2 > 1e-8) {
        const d = Math.sqrt(d2);
        px = cx + (dx / d) * r; pz = cz + (dz / d) * r;
      } else {
        // Centre à l'intérieur : sortie par le bord le plus proche.
        const l = px - x0, rr = x1 - px, t = pz - z0, b = z1 - pz, m = Math.min(l, rr, t, b);
        if (m === l) px = x0 - r; else if (m === rr) px = x1 + r; else if (m === t) pz = z0 - r; else pz = z1 + r;
      }
    };
    lot.obstacles.forEach((o) => hit(o[0], o[1], o[2], o[3]));
    const pond = lot.city.pond;
    if (pond && skip) hit(pond.x - pond.rx, pond.x + pond.rx, pond.z - pond.rz, pond.z + pond.rz);
    if (skip) { // la colline du belvédère se monte à pied, pas en voiture
      const hl = lot.city.hill, dx = px - hl.x, dz = pz - hl.z, dd = Math.hypot(dx, dz), min = hl.r + r;
      if (dd < min && dd > 1e-6) { px = hl.x + (dx / dd) * min; pz = hl.z + (dz / dd) * min; }
    }
    lot.zones.forEach((zone) => zone.spots.forEach((sp) => {
      const v = sp.vehicle;
      if (!v || v.state !== "parked") return;
      const f = FOOT[v.model] || FOOT.sedan;
      hit(sp.x - f[0], sp.x + f[0], sp.z - f[1], sp.z + f[1]);
    }));
    const b = lot.bounds;
    return [clamp(px, b[0], b[1]), clamp(pz, b[2], b[3])];
  }

  // Hauteur du sol : la colline du belvédère et la passerelle arquée de l'étang.
  function groundAt(x, z) {
    const hl = lot.city.hill, hd = Math.hypot(x - hl.x, z - hl.z);
    if (hd < hl.r) return hd <= hl.rt ? hl.h : hl.h * (1 - (hd - hl.rt) / (hl.r - hl.rt));
    const pond = lot.city.pond;
    if (!pond || Math.abs(x - pond.x) > 1.0) return 0;
    const dz = Math.abs(z - pond.z);
    if (dz > 4.85) return 0;
    if (dz > 3.8) return 0.57 * (1 - (dz - 3.8) / 1.05);
    return 0.57 + 0.9 * (1 - (dz / 3.8) * (dz / 3.8));
  }

  /* --- Les autres promeneurs (multijoueur) -----------------------------------------------
     La page donne l'adresse de la route (`opts.multi`), sinon rien n'est envoyé.
     En promenade, le plan envoie sa position et sa tenue et reçoit celles des
     autres ; vu de haut, il les regarde seulement. Aucun texte libre : le
     pseudo est attribué par le serveur, les saluts viennent d'une liste. */
  const net = {
    url: typeof opts.multi === "string" && opts.multi.charAt(0) === "/" ? opts.multi : null,
    token: playerToken(), you: null, others: new Map(), wait: 0.4, busy: false, online: 0, emote: 0, emoteFor: 0, fails: 0, duels: [],
  };
  function netDrop(id) {
    const o = net.others.get(id);
    if (!o) return;
    disposeModel(o.group);
    o.group.removeFromParent();
    if (o.car) o.car.paintMat.dispose();
    lot.removeTag(o.tag);
    net.others.delete(id);
  }
  function netApply(players) {
    const seen = new Set();
    players.slice(0, 60).forEach((p) => {
      if (!p || typeof p.id !== "string" || !p.look) return;
      seen.add(p.id);
      let o = net.others.get(p.id);
      if (!o) {
        o = { cur: { x: p.x, y: p.y, z: p.z, rot: p.rot }, phase: 0, group: new THREE.Group(), tag: lot.addTag(p.pseudo), sig: "" };
        o.rideAction = { label: "Monter avec " + p.pseudo, action: () => rideWith(p.id) };
        o.duelAction = { label: "Défier " + p.pseudo, action: () => openWheel(p.id, p.pseudo) };
        lot.group.add(o.group);
        net.others.set(p.id, o);
      }
      const sig = JSON.stringify(p.look) + "|" + (p.drive || "") + "|" + (p.tune ? JSON.stringify(p.tune) : "");
      if (o.sig !== sig) { // tenue, compagnon ou véhicule changés : on refait le modèle
        o.sig = sig;
        disposeModel(o.group);
        o.group.clear();
        if (o.car) o.car.paintMat.dispose();
        const lk = p.look;
        o.person = buildPerson({
          top: lk.top, hem: shade(lk.top, 0.72), skin: lk.skin, hair: lk.hair, pants: lk.pants, shoes: "#f4f5f7",
          pack: lk.pack ? "#f2b01e" : null, hat: lk.hat, cut: lk.cut,
          outfit: lk.outfit, bottom: lk.bottom, extra: lk.extra, balloon: /^#[0-9a-f]{6}$/.test(lk.balloon || "") ? lk.balloon : null, eyes: lk.eyes, small: true,
        });
        o.pet = buildPet(lk.pet);
        o.car = p.drive && MODELS[p.drive] ? buildCar(p.drive, lk.top, p.tune ? cleanTune(p.tune, p.drive, lk.top) : null) : null;
        o.group.add(o.person.root, o.pet.root);
        if (o.car) o.group.add(o.car.root);
      }
      o.goal = p;
    });
    Array.from(net.others.keys()).forEach((id) => { if (!seen.has(id)) netDrop(id); });
  }
  function netSync() {
    net.busy = true;
    const rv = walk.drive, lk = look;
    const request = walk.on
      ? fetch(net.url, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "omit", cache: "no-store",
        body: JSON.stringify({
          token: net.token,
          x: Math.round(walk.x * 100) / 100, z: Math.round(walk.z * 100) / 100,
          y: Math.round((rv ? 0 : walk.y + groundAt(walk.x, walk.z)) * 100) / 100,
          rot: Math.round(Math.atan2(Math.sin(walk.rot), Math.cos(walk.rot)) * 1000) / 1000,
          speed: Math.round(Math.min(80, Math.abs(walk.speed)) * 10) / 10,
          look: {
            top: lk.top, pants: lk.pants, hair: lk.hair, skin: lk.skin, hat: lk.hat, cut: lk.cut, pet: lk.pet, pack: lk.pack,
            outfit: lk.outfit, bottom: lk.bottom, extra: lk.extra, balloon: lk.balloon, eyes: lk.eyes,
          },
          ride: walk.ride || null,
          drive: rv ? rv.def.model : null,
          tune: rv ? garage[rv.def.model] : null,
          emote: net.emoteFor > 0 ? net.emote : null,
          stars: Math.min(99, progress.wins.size),
        }),
      })
      : fetch(net.url, { credentials: "omit", cache: "no-store" }); // vu de haut : on regarde seulement
    request
      .then((res) => {
        if (res.status === 403) net.url = null; // multijoueur coupé côté serveur
        return res.ok ? res.json() : Promise.reject(new Error(String(res.status)));
      })
      .then((data) => {
        net.fails = 0;
        net.wait = walk.on ? clamp((data.nextMs || 700) / 1000, 0.3, 5) : 2.5;
        if (walk.on) setDuels(Array.isArray(data.duels) ? data.duels : []);
        net.you = data.you || net.you;
        net.online = data.online || 0;
        if (lot) netApply(Array.isArray(data.players) ? data.players : []);
        if (walk.on && net.online >= 3) win("foule");
      })
      .catch(() => { net.fails++; net.wait = Math.min(20, 2 * net.fails); })
      .finally(() => { net.busy = false; });
  }
  function emote(i) {
    if (!walk.on || walk.drive) return;
    say(EMOTES[i]);
    if (++progress.hellos >= 10) win("sociable");
    sfx("coucou");
    if (Math.hypot(walk.x - lot.farm.cave.x, walk.z - lot.farm.cave.z) < lot.farm.cave.r) win("echo");
    net.emote = i;
    net.emoteFor = 3.5;
  }
  helloBtn.addEventListener("click", () => emote(0));
  function stepNet(dt) {
    net.emoteFor = Math.max(0, net.emoteFor - dt);
    if (net.url && active && !document.hidden) {
      net.wait -= dt;
      if (net.wait <= 0 && !net.busy) { net.wait = 6; netSync(); }
    }
    const L = lot.L;
    onlineBox.classList.toggle("on", Boolean(net.url && net.you));
    onlineBox.classList.toggle("watch", Boolean(net.url && !walk.on && net.others.size));
    onlineName.textContent = walk.on && net.you ? net.you.pseudo : "Promeneurs";
    onlineCount.textContent = net.online + " en ligne";
    let offer = null, duelOffer = null;
    walk.hearts = Math.max(0, walk.hearts - dt);
    net.others.forEach((o) => {
      const g = o.goal, c = o.cur, k = 1 - Math.exp(-dt * 7);
      if (Math.hypot(g.x - c.x, g.z - c.z) > 30) { c.x = g.x; c.z = g.z; c.y = g.y; }
      const moved = Math.hypot(g.x - c.x, g.z - c.z);
      c.x = lerp(c.x, g.x, k); c.z = lerp(c.z, g.z, k); c.y = lerp(c.y, g.y, k);
      c.rot = angleTo(c.rot, g.rot, k);
      const speed = moved > 0.03 ? Math.min(g.speed, 9) : 0, sn = Math.sin(c.rot), cs = Math.cos(c.rot);
      const car = o.car, onBike = car && BIKES.includes(g.drive);
      const riding = Boolean(g.ride); // passager d'une autre voiture : on ne voit que son nom
      o.person.root.visible = !riding && (!car || onBike);
      o.pet.root.visible = !riding && !car;
      if (o.person.balloon) o.person.balloon.rotation.z = Math.sin(performance.now() / 600 + c.x) * 0.07;
      if (car) {
        car.root.position.set(c.x, 0, c.z);
        car.root.rotation.y = c.rot;
      }
      if (onBike) {
        o.person.root.position.set(c.x - sn * 0.25, 0.26, c.z - cs * 0.25);
        o.person.root.rotation.set(0, c.rot, 0);
        o.person.legL.rotation.x = o.person.legR.rotation.x = -1.35;
        o.person.armL.rotation.x = o.person.armR.rotation.x = -1.15;
      } else if (!car) {
        o.phase += speed * dt * 2.4;
        const stride = Math.min(1, speed / 4.3), swing = Math.sin(o.phase) * 0.8 * stride;
        o.person.legL.rotation.x = swing; o.person.legR.rotation.x = -swing;
        o.person.armL.rotation.x = -swing * 0.85; o.person.armR.rotation.x = swing * 0.85;
        o.person.body.position.y = Math.abs(Math.sin(o.phase)) * 0.06 * stride;
        o.person.body.rotation.z = Math.sin(o.phase) * 0.07 * stride;
        o.person.root.position.set(c.x, c.y, c.z);
        o.person.root.rotation.set(0, c.rot, 0);
        const px = c.x - sn * 0.7 - cs * 0.6, pz = c.z - cs * 0.7 + sn * 0.6, trot = Math.min(1, speed / 3) * 0.9;
        o.pet.root.position.set(px, groundAt(px, pz), pz);
        o.pet.root.rotation.y = c.rot;
        o.pet.legs[0].rotation.x = o.pet.legs[3].rotation.x = Math.sin(o.phase * 3.6) * trot;
        o.pet.legs[1].rotation.x = o.pet.legs[2].rotation.x = -Math.sin(o.phase * 3.6) * trot;
        o.pet.tail.rotation.z = Math.sin(performance.now() / 70) * o.pet.wag;
      }
      // Le nom ne s'affiche que de près en promenade ; vu de haut, on voit tout le monde.
      o.tag.hidden = walk.on && !walk.ride && Math.hypot(c.x - walk.x, c.z - walk.z) > 14;
      const hello = g.emote != null && EMOTES[g.emote] ? " : " + EMOTES[g.emote] : "";
      const label = g.pseudo + (g.stars ? " ★" + g.stars : "") + hello;
      if (o.label !== label) { o.label = label; o.tag.name.textContent = label; }
      o.tag.pos.set(c.x - L.cx, c.y + (riding ? 3.5 : car && !onBike ? 2.7 : 2.2), c.z - L.cz);
      if (walk.on) {
        const near = walk.ride ? 99 : Math.hypot(c.x - walk.x, c.z - walk.z);
        if (near < 6 && !riding) win("rencontre");
        if (near < 12 && net.emoteFor > 0) win("coucou");
        if (near < 9 && net.emoteFor > 0 && g.emote != null && walk.hearts <= 0) { // on se salue à deux : pluie de cœurs
          walk.hearts = 6;
          launchFireworks(2, true);
          win("amitie", true);
          toast("♥ L'amour gagne toujours.", 4);
        }
        if (car && !onBike && !walk.drive && !walk.ride && near < 4.6 && g.speed < 3 && (!offer || near < offer.d)) offer = { d: near, o };
        if (net.you && g.ride === net.you.id && walk.drive) win("taxi");
        if (!car && !riding && !walk.drive && !walk.ride && near < 3.2 && (!duelOffer || near < duelOffer.d)) duelOffer = { d: near, o };
      }
    });
    net.offer = offer;
    net.duelOffer = duelOffer;
  }

  // --- Bulles, carnet de tampons, boutiques ------------------------------------------------
  function say(text, secs) {
    lot.playerTag.name.textContent = text;
    walk.say = secs || 2.8;
  }
  function toast(text, secs) {
    toastBox.textContent = text;
    toastBox.classList.add("on");
    walk.toast = secs || 4;
  }
  function refreshCarnet() {
    carnetCount.textContent = carnet.size + "/" + STAMPS.length + (progress.wins.size ? " · ★" + progress.wins.size : "");
  }
  refreshCarnet();
  /* Un tampon de plus au carnet (une seule fois chacun). Le dernier tire un feu
     d'artifice. Le carnet est un jeu : il ne donne droit à aucun tarif. */
  function stamp(id) {
    if (carnet.has(id) || !walk.on) return;
    const def = STAMPS.find((st) => st[0] === id);
    if (!def) return;
    carnet.add(id);
    saveProgress();
    refreshCarnet();
    sfx("ding");
    if (carnet.size >= STAMPS.length) {
      toast("Carnet complet, bravo ! Pour venir pour de vrai, la borne de réservation est sur le parvis du parking.", 8);
      launchFireworks(7);
      win("carnet", true);
    } else {
      toast("Tampon " + carnet.size + "/" + STAMPS.length + " : " + def[1].toLowerCase() + ".");
    }
  }
  // Bouquets tirés devant le promeneur, là où la caméra regarde.
  /* Un succès de plus (une seule fois chacun). `quiet` : sans message, quand
     un autre vient d'être affiché. */
  function win(id, quiet) {
    if (progress.wins.has(id) || !walk.on) return;
    const def = WINS.find((w) => w[0] === id);
    if (!def) return;
    progress.wins.add(id);
    saveProgress();
    refreshCarnet();
    sfx("succes");
    if (!quiet) { toast("Succès : " + def[1] + " !", 5); launchFireworks(2); }
    if (id !== "legende" && progress.wins.size >= WINS.length - 1) win("legende");
  }
  const rank = () => RANKS.filter((r) => progress.wins.size >= r[0]).pop()[1];
  // Fin d'un mini-jeu (ou du créneau) : record, succès, score partagé avec les autres promeneurs.
  function gameDone(id, score) {
    const record = score > (progress.best[id] || 0);
    progress.best[id] = Math.max(progress.best[id] || 0, score);
    if (!progress.played.includes(id) && MINI[id]) progress.played.push(id);
    saveProgress();
    if (score >= GOALS[id]) win(id);
    if (id === "olives" && score >= 12) questEvent("olives");
    if (progress.played.length >= Object.keys(MINI).length) win("tournee");
    if (net.url && score > 0) {
      fetch(net.url + "/scores", {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "omit",
        body: JSON.stringify({ token: net.token, game: id, score }),
      }).catch(() => { /* hors ligne : le record reste sur l'appareil */ });
    }
    return record;
  }
  function openGame(id, stampId) {
    const def = MINI[id];
    if (!def) return;
    if (stampId) stamp(stampId);
    const mount = elem("div");
    const result = elem("p", "p3d-luck", "Record : " + (progress.best[id] || 0) + " / " + def.max);
    const replay = elem("button", null, "Rejouer");
    replay.type = "button";
    replay.style.display = "none";
    replay.addEventListener("click", () => openGame(id));
    showPanel(def.title, false, [panelTitle("J", def.title, BRAND), elem("p", null, def.help), mount, result, replay, panelClose()]);
    walk.game = startGame(id, mount, {
      sound,
      onEnd(score) {
        const record = gameDone(id, score);
        result.textContent = "Score : " + score + " / " + def.max + (record ? ". Nouveau record !" : ". Record : " + progress.best[id]) +
          (score >= GOALS[id] ? "" : " — succès à " + GOALS[id] + ".");
        replay.style.display = "";
        if (id === "plein") walk.fuel = 8;
      },
    });
  }
  /* Le panneau de la station affiche les places libres du parking (les vraies,
     dès que Parking répond), et le ticket d'or du jour tourne dans sa cachette. */
  function stepLive(now) {
    const fp = lot.flies.points.geometry.attributes.position;
    lot.flies.home.forEach((h, i) => { // les papillons tournent autour de leur coin de fleurs
      const a = now * 0.8 + h[2];
      fp.setXYZ(i, h[0] + Math.cos(a) * 1.6, 0.9 + Math.sin(now * 3 + i) * 0.35 + groundAt(h[0], h[1]), h[1] + Math.sin(a * 1.3) * 1.6);
    });
    fp.needsUpdate = true;
    const live = lot.live, free = lot.zones.reduce((n, zone) => n + Math.max(0, zone.cap - zone.taken), 0);
    const shown = free + ":" + data.source;
    if (live.shown !== shown) {
      live.shown = shown;
      const g = live.ctx;
      g.fillStyle = BRAND; g.fillRect(0, 0, 512, 256);
      g.fillStyle = "#ffffff"; g.textAlign = "center";
      g.font = "800 30px system-ui, sans-serif"; drawLogo(g, 132, 14, 44); g.textAlign = "left"; g.fillText("KingPar", 186, 47); g.textAlign = "center";
      g.font = "900 128px system-ui, sans-serif"; g.fillText(String(free), 256, 166);
      g.font = "800 34px system-ui, sans-serif"; g.fillText(free > 1 ? "PLACES LIBRES" : "PLACE LIBRE", 256, 208);
      g.fillStyle = "#ffd60a"; g.font = "700 22px system-ui, sans-serif";
      g.fillText(data.source === "live" ? "en direct · réservez à la borne" : "démonstration", 256, 240);
      live.tex.needsUpdate = true;
    }
    const gold = lot.gold;
    if (!gold.mesh.visible) return;
    gold.mesh.rotation.y = now * 2.4;
    gold.mesh.position.y += Math.sin(now * 3) * 0.002;
    if (!walk.on || walk.drive || Math.hypot(walk.x - gold.x, walk.z - gold.z) > 1.7) return;
    gold.mesh.visible = false;
    progress.goldDay = gold.day;
    progress.gold++;
    saveProgress();
    toast("Ticket d'or du jour trouvé ! " + progress.gold + " au total. Il change de cachette chaque jour : revenez demain.", 7);
    launchFireworks(4);
    win("or", true);
    if (progress.gold >= 5) win("collection", true);
  }
  function launchFireworks(count, cozy, at) {
    const fw = lot.city.fireworks;
    fw.left = count; fw.next = 0; fw.cozy = Boolean(cozy);
    fw.at = at || null; // { x, z, yaw } : tirés devant ce point plutôt que devant le promeneur
  }
  function stepFireworks(dt) {
    const fw = lot.city.fireworks, pos = fw.points.geometry.attributes.position, col = fw.points.geometry.attributes.color;
    const per = Math.floor(fw.life.length / 3);
    if (fw.left > 0) {
      if (walk.on && !fw.cozy && !fw.at) walk.pitch = lerp(walk.pitch, 0.1, 1 - Math.exp(-dt * 2.2)); // la caméra se lève vers le ciel
      fw.next -= dt;
      if (fw.next <= 0) {
        fw.left--;
        fw.next = 0.4 + Math.random() * 0.5;
        const from = (fw.slot++ % 3) * per, tint = cA.set(fw.cozy ? "#ff5d8f" : FIREWORKS[Math.floor(Math.random() * FIREWORKS.length)]);
        const ahead = fw.cozy ? 1.2 : 42 + Math.random() * 22, aside = fw.cozy ? 0 : (Math.random() - 0.5) * 46, org = fw.at || { x: walk.x, z: walk.z, yaw: walk.yaw }, sn = Math.sin(org.yaw), cs = Math.cos(org.yaw);
        const ox = org.x + sn * ahead + cs * aside, oy = groundAt(org.x, org.z) + (fw.cozy ? 2.3 : 15 + Math.random() * 11), oz = org.z + cs * ahead - sn * aside;
        for (let i = from; i < from + per; i++) {
          const a = Math.random() * Math.PI * 2, u = Math.random() * 2 - 1, q = Math.sqrt(1 - u * u), sp = (6 + Math.random() * 6) * (fw.cozy ? 0.28 : 1);
          fw.vel[i * 3] = Math.cos(a) * q * sp; fw.vel[i * 3 + 1] = u * sp + 2; fw.vel[i * 3 + 2] = Math.sin(a) * q * sp;
          fw.life[i] = 1.5 + Math.random() * 0.8;
          fw.base[i * 3] = tint.r; fw.base[i * 3 + 1] = tint.g; fw.base[i * 3 + 2] = tint.b;
          pos.setXYZ(i, ox, oy, oz);
        }
        fw.live = true;
      }
    }
    if (!fw.live) return;
    let alive = false;
    const drag = Math.exp(-dt * 1.3);
    for (let i = 0; i < fw.life.length; i++) {
      if (fw.life[i] <= 0) continue;
      fw.life[i] -= dt;
      if (fw.life[i] <= 0) { pos.setY(i, -999); continue; }
      alive = true;
      fw.vel[i * 3] *= drag; fw.vel[i * 3 + 1] = fw.vel[i * 3 + 1] * drag - 5.5 * dt; fw.vel[i * 3 + 2] *= drag;
      pos.setXYZ(i, pos.getX(i) + fw.vel[i * 3] * dt, pos.getY(i) + fw.vel[i * 3 + 1] * dt, pos.getZ(i) + fw.vel[i * 3 + 2] * dt);
      const glow = Math.min(1, fw.life[i] / 0.7);
      col.setXYZ(i, fw.base[i * 3] * glow, fw.base[i * 3 + 1] * glow, fw.base[i * 3 + 2] * glow);
    }
    fw.live = alive || fw.left > 0;
    pos.needsUpdate = true; col.needsUpdate = true;
  }
  function drink() {
    say(DRINKS[Math.floor(Math.random() * DRINKS.length)]);
    stamp("boisson");
  }
  // Sons synthétisés (aucun fichier) : notes [fréquence, volume, départ], durée de l'écho.
  let audio = null, master = null;
  const audioMix = { vol: 0.6, music: true }; // réglages du son, gardés sur l'appareil
  try {
    const kept = JSON.parse(window.localStorage.getItem("access.plan3d.son") || "{}") || {};
    if (Number.isFinite(kept.vol)) audioMix.vol = clamp(kept.vol, 0, 1);
    if (typeof kept.music === "boolean") audioMix.music = kept.music;
  } catch (err) { /* réglages par défaut */ }
  // Petite musique de promenade : une ritournelle pentatonique et sa basse, jouées note à note.
  const TUNE = [659, 0, 784, 659, 587, 0, 523, 587, 659, 784, 880, 0, 784, 659, 587, 0, 523, 0, 587, 659, 784, 0, 659, 587, 523, 587, 659, 0, 587, 523, 440, 0];
  const BASS = [262, 196, 220, 196, 262, 196, 175, 196];
  const music = { t: 0, i: 0 };
  function stepMusic(dt) {
    if (!walk.on || !audioMix.music || audioMix.vol <= 0 || walk.game || walk.ad) return;
    music.t -= dt;
    if (music.t > 0) return;
    music.t += 0.36;
    const note = TUNE[music.i % TUNE.length];
    if (note) sound([[note, 0.028, 0], [note * 2, 0.008, 0]], 0.5, null, true);
    if (music.i % 4 === 0) sound([[BASS[(music.i / 4) % BASS.length], 0.035, 0]], 1.3, null, true);
    music.i++;
  }
  // La « voix » d'un habitant : quelques notes rapides, d'une hauteur propre à chacun.
  function babble(seed) {
    const base = 300 + (hash(seed) % 9) * 45;
    sound(Array.from({ length: 8 }, (_, i) => [base * (1 + ((i * 7 + hash(seed)) % 5) * 0.07), 0.05, i * 0.075]), 0.07, "triangle", true);
  }
  const SFX = { // petits sons synthétisés : notes [fréquence, volume, départ], durée, forme d'onde
    saut: [[[330, 0.07, 0], [520, 0.06, 0.07]], 0.16],
    pop: [[[620, 0.05, 0], [830, 0.04, 0.05]], 0.1],
    ding: [[[880, 0.08, 0], [1320, 0.06, 0.09]], 0.35],
    succes: [[[523, 0.09, 0], [659, 0.09, 0.12], [784, 0.09, 0.24], [1047, 0.1, 0.36]], 0.5],
    coucou: [[[700, 0.06, 0], [930, 0.06, 0.1]], 0.2],
    porte: [[[140, 0.14, 0], [95, 0.1, 0.06]], 0.16, "triangle"],
    klaxon: [[[392, 0.07, 0], [494, 0.07, 0]], 0.4, "square"],
    pouet: [[[233, 0.1, 0], [185, 0.09, 0.16]], 0.28, "sawtooth"],
    melodie: [[[392, 0.06, 0], [494, 0.06, 0.13], [587, 0.06, 0.26], [784, 0.07, 0.39], [587, 0.06, 0.56], [784, 0.08, 0.69]], 0.2, "square"],
    coin: [[[720, 0.08, 0], [540, 0.08, 0.08], [720, 0.08, 0.24], [540, 0.08, 0.32]], 0.1, "sawtooth"],
    pas: [[[90, 0.035, 0]], 0.05, "triangle"],
  };
  /* Sons enregistrés (packs Kenney, licence CC0, dans `sons/`). Si le navigateur
     ne lit pas ce format, on garde les sons synthétisés ci-dessus. */
  const SAMPLES = {}, LEVEL = { pas: 0.35, pop: 0.6, saut: 0.7, porte: 0.8 };
  try {
    if (new Audio().canPlayType("audio/ogg; codecs=vorbis")) {
      ["pop", "ding", "coucou", "saut", "pas", "coup", "pioche", "porte", "cloche", "succes"].forEach((name) => {
        const clip = new Audio(new URL("./sons/" + name + ".ogg", import.meta.url).href);
        clip.preload = "auto";
        SAMPLES[name] = clip;
      });
    }
  } catch (err) { /* pas de lecteur audio : sons synthétisés */ }
  function sample(name) {
    const clip = SAMPLES[name];
    if (!clip || audioMix.vol <= 0) return Boolean(clip);
    const one = clip.cloneNode();
    one.volume = clamp(audioMix.vol * (LEVEL[name] || 1), 0, 1);
    one.play().catch(() => { /* lecture refusée tant qu'on n'a pas touché la page */ });
    return true;
  }
  function sfx(name) { if (sample(name)) return; const it = SFX[name]; if (it) sound(it[0], it[1], it[2], true); }
  function sound(notes, ring, shape, steady) {
    if (audioMix.vol <= 0) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      if (!audio) { audio = new Ctx(); master = audio.createGain(); master.connect(audio.destination); }
      master.gain.value = audioMix.vol;
      const t0 = audio.currentTime;
      notes.forEach((n) => {
        const osc = audio.createOscillator(), gain = audio.createGain(), at = t0 + (n[2] || 0);
        osc.type = shape || "sine";
        osc.frequency.setValueAtTime(n[0], at);
        if (shape && !steady) osc.frequency.exponentialRampToValueAtTime(n[0] * 0.55, at + ring); // peau de tambour
        gain.gain.setValueAtTime(0.0001, t0);
        gain.gain.setValueAtTime(n[1], at);
        gain.gain.exponentialRampToValueAtTime(0.0008, at + ring);
        osc.connect(gain).connect(master);
        osc.start(at);
        osc.stop(at + ring + 0.1);
      });
    } catch (err) { /* son indisponible : sans importance */ }
  }
  const dong = () => { if (!sample("cloche")) sound([[196, 0.16], [392.6, 0.07], [588, 0.035]], 2.4); };
  function bassDrum() {
    say("Boum ! Boum ! Tchak-boum !", 3);
    openGame("tambour", "fete");
  }
  function greetMascot() {
    say("Bonjour " + MASCOT + " !");
    bark();
    stamp("mascotte");
  }
  function luckyTicket() {
    const draw = LUCK[Math.floor(Math.random() * LUCK.length)];
    showPanel("Ticket chance", false, [
      panelTitle("T", "Ticket chance : " + draw[0], BRAND),
      elem("p", "p3d-luck", draw[1]),
      elem("p", null, "Un ticket pour rire, tiré au belvédère de " + CITY_NAME + "."),
      panelClose("Merci"),
    ]);
    stamp("chance");
    if (draw[0] === "Grande chance") win("chance");
  }
  /* Photo souvenir : l'image du plan, avec un bandeau. Elle reste dans la page
     (rien n'est envoyé) ; un lien permet de l'enregistrer. */
  function photo() {
    if (!walk.on || !lot) return;
    renderer.render(scene, camera);
    const shot = document.createElement("canvas"), k = Math.min(1, 1280 / canvas.width);
    shot.width = Math.round(canvas.width * k); shot.height = Math.round(canvas.height * k);
    const ctx = shot.getContext("2d");
    ctx.drawImage(canvas, 0, 0, shot.width, shot.height);
    const band = Math.round(shot.height * 0.13), c = lot.city;
    const inTown = walk.x > c.x0 - 14 && walk.x < c.x1 + 14 && walk.z > c.z0 && walk.z < c.z1;
    const shade = ctx.createLinearGradient(0, shot.height - band * 1.6, 0, shot.height);
    shade.addColorStop(0, "rgba(17,17,27,0)"); shade.addColorStop(1, "rgba(17,17,27,.78)");
    ctx.fillStyle = shade; ctx.fillRect(0, shot.height - band * 1.6, shot.width, band * 1.6);
    ctx.fillStyle = "#fff"; ctx.textBaseline = "alphabetic";
    ctx.font = "800 " + Math.round(band * 0.42) + "px system-ui, sans-serif";
    ctx.fillText(inTown ? "Souvenir de " + CITY_NAME : "Souvenir du parking", band * 0.4, shot.height - band * 0.36);
    ctx.font = "600 " + Math.round(band * 0.26) + "px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("KingPar · plan 3D", shot.width - band * 0.4, shot.height - band * 0.38);
    const url = shot.toDataURL("image/jpeg", 0.88);
    const img = elem("img");
    img.src = url;
    img.alt = "Photo souvenir de la promenade";
    const save = elem("a", "p3d-save", "Enregistrer la photo");
    save.href = url;
    save.download = "souvenir-" + (inTown ? "bonneplace" : "parking") + ".jpg";
    showPanel("Photo souvenir", false, [panelTitle("P", "Photo souvenir", "#b5651d"), img, save, panelClose()]);
    win("photo");
  }
  photoBtn.addEventListener("click", () => { if (walk.panel) closeResa(); else photo(); });
  function ringBell() {
    say("Dong… dong…", 3.2);
    dong();
    launchFireworks(3);
    stamp("cloche");
    questEvent("cloche");
    if (night > 0.5) win("minuit");
  }
  function panelTitle(letter, text, color) {
    const title = elem("h3");
    const badge = elem("i", null, letter);
    if (color) badge.style.background = color;
    title.append(badge, document.createTextNode(text));
    return title;
  }
  function panelClose(label) {
    const close = elem("button", null, label || "Fermer");
    close.type = "button";
    close.addEventListener("click", closeResa);
    return close;
  }
  function showPanel(label, side, nodes) {
    if (walk.ad) endAd();
    if (walk.game) { walk.game.stop(); walk.game = null; }
    panel.classList.remove("talk");
    sfx("pop");
    panel.replaceChildren();
    nodes.forEach((n) => panel.appendChild(n));
    panel.setAttribute("aria-label", label);
    panel.classList.toggle("side", Boolean(side));
    panel.classList.add("on");
    panel.scrollTop = 0;
    prompt.classList.remove("on");
    walk.panel = true;
    walk.keys = {};
  }
  // Une rangée de choix (pastilles de couleur ou étiquettes) ; un seul actif à la fois.
  function choices(title, items, current, onPick, swatch) {
    const row = elem("div", "p3d-row");
    items.forEach((item, i) => {
      const value = swatch ? item : item[0];
      const b = elem("button", swatch ? "p3d-sw" : "p3d-chip", swatch ? null : item[1]);
      b.type = "button";
      if (swatch) { b.style.setProperty("--c", value); b.setAttribute("aria-label", title + ", couleur " + (i + 1)); }
      b.setAttribute("aria-pressed", String(value === current));
      b.addEventListener("click", () => {
        Array.from(row.children).forEach((other) => other.setAttribute("aria-pressed", String(other === b)));
        onPick(value);
      });
      row.appendChild(b);
    });
    return [elem("h4", null, title), row];
  }
  function redress(stampId) {
    swapModel(player, buildPerson(playerLook()));
    store(LOOK_KEY, look);
    stamp(stampId);
    if (!progress.cuts.includes(look.cut)) { progress.cuts.push(look.cut); saveProgress(); }
    if (!progress.fits.includes(look.outfit)) { progress.fits.push(look.outfit); saveProgress(); }
    if (progress.fits.length >= 4) win("style");
    if (qs("coupe") === 1 && look.cut !== progress.qcut) questEvent("coupe");
    if (progress.cuts.length >= 4) win("coiffe");
  }
  function changePet(kind) {
    look.pet = kind;
    swapModel(dog, buildPet(kind));
    store(LOOK_KEY, look);
    bark();
    stamp("ami");
    if (!progress.pets.includes(kind)) { progress.pets.push(kind); saveProgress(); }
    if (progress.pets.length >= 5) win("zoo");
  }
  /* Boutiques du village : tout est offert, rien n'est payé ni envoyé. Le
     personnage se tourne vers la caméra pour qu'on voie le résultat. */
  function openShop(kind, facing) {
    if (facing != null) { walk.rot = facing; walk.yaw = facing + Math.PI; }
    if (kind === "coiffure" && look.hat !== "none") { bareHead = true; swapModel(player, buildPerson(playerLook())); }
    // La caméra s'approche : le visage chez le coiffeur, la silhouette ailleurs.
    walk.zoom = kind === "coiffure" ? { dist: 2.3, pitch: 0.05, y: 1.12 } : { dist: 4.0, pitch: 0.14, y: 0.85 };
    const set = (field, stampId) => (value) => { look[field] = value; redress(stampId); };
    let nodes;
    if (kind === "tenue") {
      nodes = [panelTitle("K", "Boutique KingPar", BRAND), elem("p", null, "Aux couleurs du parking. Servez-vous : tout est offert.")]
        .concat(choices("Carnation", SKINS, look.skin, set("skin", "look"), true))
        .concat(choices("Haut", TOPS, look.top, set("top", "look"), true))
        .concat(choices("Pantalon", PANTS, look.pants, set("pants", "look"), true))
        .concat(choices("Tenue", OUTFITS, look.outfit, set("outfit", "look")))
        .concat(choices("Bas", BOTTOMS, look.bottom, set("bottom", "look")))
        .concat(choices("Accessoire", EXTRAS, look.extra, set("extra", "look")))
        .concat(choices("Couvre-chef", HATS, look.hat, (value) => {
          if (value === "couronne" && progress.wins.size < CROWN_WINS) { // elle se mérite
            toast("La couronne KingPar se mérite : " + CROWN_WINS + " succès (vous en avez " + progress.wins.size + ").", 5);
            openShop("tenue");
            return;
          }
          look.hat = value;
          redress("look");
          if (value === "couronne") win("roi");
        }))
        .concat(choices("Sac à dos", [[true, "Avec"], [false, "Sans"]], look.pack, set("pack", "look")));
    } else if (kind === "coiffure") {
      nodes = [panelTitle("C", "Coiffure Le Créneau", "#5b3a8c"), elem("p", null, "Ici, on réussit tous les créneaux. C'est la maison qui offre." + (look.hat !== "none" ? " Votre chapeau vous attend à la sortie." : ""))]
        .concat(choices("Couleur", HAIRS, look.hair, set("hair", "look"), true))
        .concat(choices("Coupe", CUTS, look.cut, set("cut", "look")))
        .concat(choices("Regard", EYES, look.eyes, set("eyes", "look")));
    } else {
      nodes = [panelTitle("C", "Animalerie du Copilote", "#1f6f5c"), elem("p", null, "Qui sera votre copilote ? Il monte aussi en voiture.")]
        .concat(choices("Compagnon", Object.keys(PETS).map((k) => [k, PETS[k].name]), look.pet, changePet));
    }
    nodes.push(panelClose("C'est parfait"));
    showPanel(kind === "tenue" ? "Boutique KingPar" : kind === "coiffure" ? "Coiffure Le Créneau" : "Animalerie du Copilote", true, nodes);
  }
  /* --- Le gros bouton rouge : une publicité KingPar tournée dans le décor. Six plans,
     une caméra qui se promène, des sous-titres, et des voix enregistrées (voir
     `sayLine`). En secours : la synthèse vocale de l'appareil quand il en a une en
     français (jamais une voix en ligne), sinon la voix chantonnée des habitants.
     Tout est servi par Access ; rien n'est envoyé. */
  function speak(text, pitch, seed) {
    try {
      const synth = window.speechSynthesis;
      const voice = synth && audioMix.vol > 0 ? synth.getVoices().find((v) => /^fr/i.test(v.lang) && v.localService) : null;
      if (voice) {
        const line = new SpeechSynthesisUtterance(text);
        line.voice = voice; line.lang = voice.lang; line.pitch = pitch; line.rate = 1.05;
        line.volume = clamp(audioMix.vol * 1.5, 0, 1);
        if (synth.speaking) synth.cancel();
        synth.speak(line);
        return;
      }
    } catch (err) { /* pas de synthèse vocale : la voix chantonnée la remplace */ }
    babble(seed);
  }
  /* Les voix des acteurs sont enregistrées (dossier `sons/pub/`, synthèse vocale
     libre, voix sous licence CC BY 4.0). Si le navigateur ne les lit pas, on
     retombe sur la synthèse de l'appareil, puis sur la voix chantonnée. */
  const adClips = {};
  function adClip(name) {
    if (!adClips[name]) {
      const clip = new Audio(new URL("./sons/pub/" + name + ".m4a", import.meta.url).href);
      clip.preload = "auto";
      adClips[name] = clip;
    }
    return adClips[name];
  }
  function sayLine(shot) {
    const fallback = () => speak(shot.text, shot.pitch, shot.who || "kingpar");
    try {
      if (audioMix.vol > 0 && new Audio().canPlayType("audio/mp4")) {
        const clip = adClip(shot.clip);
        clip.currentTime = 0;
        clip.volume = clamp(audioMix.vol * 1.5, 0, 1);
        clip.preservesPitch = clip.webkitPreservesPitch = false; // un peu plus vite, donc un peu plus aigu
        clip.playbackRate = shot.rate || 1;
        walk.ad.clip = clip;
        clip.play().catch(fallback);
        return;
      }
    } catch (err) { /* pas de lecteur audio : voix de l'appareil */ }
    fallback();
  }
  function startAd() {
    if (walk.ad || !walk.on || walk.drive || walk.ride) return;
    const L = lot.L, c = lot.city, pod = c.podium, live = { x: c.pumps.x + 16.4, z: ROAD_Z + 8.2 };
    c.adBtn.press = 1;
    sfx("ding");
    try { if (window.speechSynthesis) window.speechSynthesis.getVoices(); } catch (err) { /* sans voix */ }
    try { ["1-ticket", "2-ticket", "3-agent", "4-jo", "5-ticket", "6-kingpar"].forEach((name) => adClip(name).load()); } catch (err) { /* sans lecteur audio */ }
    const star = walk.podium || rentals[1]; // la voiture qui tourne sur le podium pendant le plan de l'atelier
    walk.ad = {
      t: -1.1, i: -1, star, home: walk.podium ? null : { x: star.x, z: star.z, rot: star.rot }, from: new THREE.Vector3(), to: new THREE.Vector3(), look: new THREE.Vector3(),
      shots: [
        { dur: 5.6, who: MASCOT, pitch: 1.5, clip: "1-ticket", rate: 1.07, text: "Vous tournez en rond pour trouver une place ?",
          from: [L.cx - 36, 27, -32], to: [L.cx - 10, 20, -24], look: [L.cx, 0, lot.D / 2] },
        { dur: 6.2, who: MASCOT, pitch: 1.5, clip: "2-ticket", rate: 1.07, text: "Chez KingPar, les places libres s'affichent en direct. Promis, on ne triche pas.",
          from: [live.x + 5.6, 4.2, live.z - 5.6], to: [live.x + 5, 4.7, live.z - 3], look: [live.x, 4.5, live.z] },
        { dur: 5.6, who: "L'agent du parking", pitch: 0.9, clip: "3-agent", text: "Bienvenue ! Ici, la barrière se lève avec le sourire.", agent: true },
        { dur: 6.2, who: "Jo, le mécano", pitch: 0.7, clip: "4-jo", text: "Peinture, jantes, néons… C'est la maison qui offre !", tune: true,
          from: [pod.x + 7.5, 2.0, pod.z + 7.5], to: [pod.x - 0.5, 2.7, pod.z + 9.5], look: [pod.x - 1.6, 1.0, pod.z] },
        { dur: 6.2, who: MASCOT, pitch: 1.5, clip: "5-ticket", rate: 1.07, text: "Et juste à côté, " + CITY_NAME + " : on se gare, et on reste pour la fête.", fire: 4,
          from: [c.x0 - 12, 5, ROAD_Z - 4], to: [c.x0 - 2, 8, ROAD_Z], look: [c.x0 + 30, 9, ROAD_Z + 24] },
        { dur: 6.5, who: "", pitch: 1.1, clip: "6-kingpar", text: "KingPar. À la fin, l'amour gagne toujours.", card: true, fire: 5,
          from: [L.cx - 6, 24, -44], to: [L.cx + 8, 30, -52], look: [L.cx + 10, 6, 10] },
      ],
    };
    walk.panel = true;
    walk.keys = {};
    walk.near = false;
    prompt.classList.remove("on");
    cineSub.replaceChildren();
    cineCard.classList.remove("on");
    container.classList.add("cine");
    sound([[523, 0.08, 0], [659, 0.08, 0.14], [784, 0.08, 0.28], [1047, 0.1, 0.42]], 0.5, "triangle", true); // fanfare d'ouverture
    win("bouton", true);
  }
  function endAd() {
    const ad = walk.ad;
    if (!ad) return;
    walk.ad = null;
    try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (err) { /* sans voix */ }
    try { if (ad.clip) ad.clip.pause(); } catch (err) { /* sans lecteur audio */ }
    container.classList.remove("cine");
    cineCard.classList.remove("on");
    npc.star = null;
    walk.tuning = null;
    if (ad.home) { ad.star.x = ad.home.x; ad.star.z = ad.home.z; ad.star.rot = ad.home.rot; }
    const jo = lot.city.mech;
    jo.armR.rotation.x = 0; jo.head.rotation.y = 0;
    walk.panel = false;
    walk.near = false;
    toast("Fin de la pub. Merci de votre attention !", 4);
  }
  function stepAd(dt, now) {
    const ad = walk.ad, L = lot.L;
    ad.t += dt;
    const next = ad.i < 0 ? ad.t >= 0 : ad.t >= ad.shots[ad.i].dur;
    if (next) {
      ad.i++;
      ad.t = 0;
      const shot = ad.shots[ad.i];
      if (!shot) { endAd(); return; }
      npc.star = null;
      walk.tuning = null;
      lot.city.mech.armR.rotation.x = 0;
      if (shot.agent) { // la caméra se place devant l'agent, là où il se trouve
        const a = npc.rot, sn = Math.sin(a), cs = Math.cos(a);
        shot.from = [npc.x + sn * 5.2 + cs * 1.6, 2.5, npc.z + cs * 5.2 - sn * 1.6];
        shot.to = [npc.x + sn * 3.6 + cs * 0.8, 2.0, npc.z + cs * 3.6 - sn * 0.8];
        shot.look = [npc.x, 1.25, npc.z];
        npc.star = { x: shot.to[0], z: shot.to[2] };
      }
      if (shot.tune) { ad.star.rot = 2.4; walk.tuning = ad.star; }
      ad.from.set(shot.from[0] - L.cx, shot.from[1], shot.from[2] - L.cz);
      ad.to.set(shot.to[0] - L.cx, shot.to[1], shot.to[2] - L.cz);
      ad.look.set(shot.look[0] - L.cx, shot.look[1], shot.look[2] - L.cz);
      camera.position.copy(ad.from);
      if (shot.fire) launchFireworks(shot.fire, false, { x: shot.to[0], z: shot.to[2], yaw: Math.atan2(shot.look[0] - shot.to[0], shot.look[2] - shot.to[2]) });
      cineSub.replaceChildren();
      if (shot.who) cineSub.appendChild(elem("b", null, shot.who));
      cineSub.appendChild(document.createTextNode(shot.text));
      cineCard.classList.toggle("on", Boolean(shot.card));
      if (shot.card) sound([[523, 0.08, 0], [659, 0.08, 0.16], [784, 0.08, 0.32], [1047, 0.09, 0.48], [784, 0.07, 0.72], [1047, 0.11, 0.86]], 0.7, "triangle", true); // le jingle
      sayLine(shot);
    }
    if (ad.i < 0) return; // le temps que le bouton s'enfonce
    const shot = ad.shots[ad.i], k = clamp(ad.t / shot.dur, 0, 1), ease = k * k * (3 - 2 * k);
    camera.position.lerpVectors(ad.from, ad.to, ease);
    camera.lookAt(ad.look);
    if (Math.abs(camera.fov - 58) > 0.05) { camera.fov = walk.fov = 58; camera.updateProjectionMatrix(); }
    if (shot.tune) { // Jo salue la caméra pendant que la voiture tourne
      const jo = lot.city.mech;
      jo.armR.rotation.x = -2.7 + Math.sin(now * 9) * 0.3;
      jo.head.rotation.y = -0.8;
    }
  }
  cineSkip.addEventListener("click", endAd);
  /* --- KingPar Tuning : le véhicule monte sur le podium tournant et change sous nos
     yeux. Tout est offert ; le réglage de chaque véhicule reste sur l'appareil. */
  const HORN_SFX = { tut: "klaxon", pouet: "pouet", melodie: "melodie", coin: "coin" };
  function honk(kind) {
    const it = SFX[HORN_SFX[kind] || "klaxon"];
    sound(it[0], it[1], it[2], true);
  }
  function retune(rv) {
    const next = buildCar(rv.def.model, rv.def.color, garage[rv.def.model]), parent = rv.root.parent;
    disposeModel(rv.root);
    rv.root.removeFromParent();
    Object.assign(rv, next);
    rv.root.position.set(rv.x, 0, rv.z);
    rv.root.rotation.y = rv.rot;
    if (parent) parent.add(rv.root);
    store(TUNE_KEY, garage);
  }
  function openTuning(rv) {
    if (!lot) return;
    const pod = lot.city.podium;
    rv = rv || walk.tuning || walk.podium || rentals[1];
    if (walk.podium && walk.podium !== rv && walk.podium !== walk.drive) { // l'ancien retourne à sa place
      const old = walk.podium;
      old.x = old.def.x; old.z = RENTAL_Z; old.rot = Math.PI;
    }
    if (walk.tuning !== rv) rv.rot = walk.drive === rv ? rv.rot : 2.4;
    walk.podium = walk.tuning = rv;
    rv.x = pod.x; rv.z = pod.z; rv.v = 0; rv.steer = 0;
    if (walk.drive === rv) { walk.x = rv.x; walk.z = rv.z; }
    if (!walk.zoom || !walk.zoom.at) walk.yaw = 2.75; // caméra côté route, l'atelier en fond
    walk.zoom = { dist: rv.def.cam * 0.88, pitch: 0.2, y: rv.def.model === "camper" ? 1.5 : 0.85, at: pod };
    stamp("tuning");
    const model = rv.def.model, t = garage[model], driving = walk.drive === rv;
    const fits = (field, list) => list.filter((it) => tuneFits(model, field, it[0]));
    const pairs = (table) => Object.keys(table).map((k) => [k, table[k][0]]);
    const set = (field) => (value) => {
      t[field] = value;
      retune(rv);
      if (field === "horn") honk(value); else sfx("ding");
      if (field === "paint") { walk.paints = walk.paints || new Set(); walk.paints.add(value); if (walk.paints.size >= 6) win("nuancier"); }
      if (!progress.tuned.includes(model)) { progress.tuned.push(model); saveProgress(); }
      win("tuning");
      if (progress.tuned.length >= 3) win("carrossier");
      if (t.rims !== "serie" && t.sticker !== "none" && t.neon !== "none" && t.addon !== "none") win("showcar");
    };
    let nodes = [panelTitle("K", "KingPar Tuning", "#22252e"),
      elem("p", null, "Jo, le mécano : « " + (driving ? "Beau châssis ! On en fait quoi ?" : "Je vous sors lequel ?") + " » Tout est offert, et le véhicule garde son style.")];
    if (!driving) nodes = nodes.concat(choices("Véhicule sur le podium", RENTALS.map((def) => [def.model, def.name]), model, (m) => openTuning(rentals.find((r) => r.def.model === m))));
    nodes = nodes
      .concat(choices("Peinture", CAR_PAINTS, t.paint, set("paint"), true))
      .concat(choices("Finition", FINISHES, t.finish, set("finish")))
      .concat(choices("Jantes", RIMS, t.rims, set("rims")))
      .concat(choices("Couleur des jantes", RIM_COLORS, t.rimc, set("rimc"), true))
      .concat(choices("Pneus", TYRES, t.tyres, set("tyres")))
      .concat(choices("Autocollant", STICKERS, t.sticker, set("sticker")));
    if (tuneFits(model, "stripes", "double")) {
      nodes = nodes.concat(choices("Bandes de course", STRIPES, t.stripes, set("stripes")))
        .concat(choices("Couleur des bandes", STRIPE_COLORS, t.stripec, set("stripec"), true))
        .concat(choices("Vitres", pairs(TINTS), t.tint, set("tint")));
    }
    nodes = nodes
      .concat(choices("Accessoire", fits("addon", ADDONS), t.addon, set("addon")))
      .concat(choices("Néon sous la caisse", pairs(NEONS), t.neon, set("neon")))
      .concat(choices("Klaxon (touche H)", HORNS, t.horn, set("horn")));
    const pick = (list) => list[Math.floor(Math.random() * list.length)];
    nodes.push(button("Surprise !", () => {
      Object.assign(t, {
        paint: pick(CAR_PAINTS), finish: pick(FINISHES)[0], rims: pick(RIMS)[0], rimc: pick(RIM_COLORS), tyres: pick(TYRES)[0], sticker: pick(STICKERS)[0],
        stripes: pick(fits("stripes", STRIPES))[0], stripec: pick(STRIPE_COLORS), tint: pick(fits("tint", pairs(TINTS)))[0], addon: pick(fits("addon", ADDONS))[0], neon: pick(Object.keys(NEONS)),
      });
      set("finish")(t.finish);
      openTuning(rv);
    }));
    nodes.push(button("Remettre d'origine", () => {
      garage[model] = cleanTune(null, model, rv.def.color);
      retune(rv);
      openTuning(rv);
    }));
    if (driving) nodes.push(button("Descendre ici", () => { closeResa(); exitVehicle(); }));
    nodes.push(panelClose("Ça roule !"));
    showPanel("KingPar Tuning", true, nodes);
  }
  /* --- Défis amicaux entre promeneurs : morpion, pierre-feuille-ciseaux, pile ou face.
     Le serveur arbitre ; ici on montre la roulette, l'invitation et la partie. */
  const DUEL_NAMES = { morpion: "Morpion", pfc: "Pierre-feuille-ciseaux", piece: "Pile ou face" };
  const HANDS = ["Pierre", "Feuille", "Ciseaux"], SIDES = ["Pile", "Face"];
  const button = (label, fn, cls) => { const b = elem("button", cls || null, label); b.type = "button"; b.addEventListener("click", fn); return b; };
  function duelSend(body) {
    if (!net.url) return;
    fetch(net.url + "/defi", {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "omit",
      body: JSON.stringify(Object.assign({ token: net.token }, body)),
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then((r) => { if (r.ok) setDuels(r.data.duels || []); else toast(typeof r.data.detail === "string" ? r.data.detail : "Défi impossible pour l'instant.", 4); })
      .catch(() => toast("Défi impossible : pas de connexion.", 4));
  }
  // La roulette : quatre pastilles autour d'un disque, une par défi.
  function openWheel(id, pseudo) {
    const wheel = elem("div", "p3d-wheel");
    wheel.appendChild(elem("b", null, "Quel défi ?"));
    [["Morpion", { game: "morpion" }, "left:50%;top:6px;margin-left:-42px"], ["Pierre feuille ciseaux", { game: "pfc" }, "right:6px;top:50%;margin-top:-42px"],
      ["Je prends pile", { game: "piece", move: 0 }, "left:50%;bottom:6px;margin-left:-42px"], ["Je prends face", { game: "piece", move: 1 }, "left:6px;top:50%;margin-top:-42px"]].forEach((it) => {
      const b = button(it[0], () => duelSend(Object.assign({ action: "invite", target: id }, it[1])), "p3d-round");
      b.style.cssText = it[2];
      wheel.appendChild(b);
    });
    showPanel("Défier " + pseudo, false, [panelTitle("VS", "Défier " + pseudo, "#d92b3a"),
      elem("p", null, "Un défi amical, pour rire. L'autre promeneur choisit d'accepter ou non."), wheel, panelClose("Annuler")]);
  }
  function setDuels(list) {
    net.duels = list;
    const d = list[0];
    if (!d) { if (walk.duelSig) { walk.duelSig = ""; closeResa(); } return; }
    const sig = [d.id, d.status, d.board.join(""), d.mine, d.theirs, d.turn].join("|");
    if (sig === walk.duelSig) return;
    walk.duelSig = sig;
    const name = DUEL_NAMES[d.game] || "Défi", quit = () => { duelSend({ action: "decline", duel: d.id }); walk.duelSig = ""; closeResa(); };
    const nodes = [panelTitle("VS", name + " contre " + d.other, "#d92b3a")];
    if (d.status === "invite") {
      if (d.role === "b") nodes.push(elem("p", "p3d-luck", d.other + " vous lance un défi !" + (d.game === "piece" ? " Vous aurez " + SIDES[d.mine].toLowerCase() + "." : "")),
        button("Accepter", () => duelSend({ action: "accept", duel: d.id })), button("Pas maintenant", quit));
      else nodes.push(elem("p", "p3d-luck", "Invitation envoyée. On attend la réponse de " + d.other + "…"), button("Annuler", quit));
    } else if (d.status === "play" && d.game === "morpion") {
      const grid = elem("div", "p3d-grid3");
      d.board.forEach((v, i) => {
        const cell = button(v === 1 ? "✕" : v === 2 ? "○" : "", () => duelSend({ action: "move", duel: d.id, move: i }), "p3d-cell");
        cell.disabled = Boolean(v) || !d.turn;
        if (v) cell.classList.add("mark");
        cell.setAttribute("aria-label", "Case " + (i + 1) + (v ? (v === 1 ? " : croix" : " : rond") : " : libre"));
        grid.appendChild(cell);
      });
      nodes.push(elem("p", "p3d-luck", d.turn ? "À vous de jouer (" + (d.role === "a" ? "✕" : "○") + ")." : "Au tour de " + d.other + "…"), grid, button("Abandonner", quit));
    } else if (d.status === "play") {
      if (d.mine == null) {
        const row = elem("div", "p3d-row center");
        HANDS.forEach((label, i) => row.appendChild(button(label, () => duelSend({ action: "move", duel: d.id, move: i }), "p3d-chip")));
        nodes.push(elem("p", "p3d-luck", "Votre choix ?"), row);
      } else nodes.push(elem("p", "p3d-luck", "Vous avez joué " + HANDS[d.mine].toLowerCase() + ". On attend " + d.other + "…"));
      nodes.push(button("Abandonner", quit));
    } else {
      const text = d.result === "win" ? "Gagné, bravo !" : d.result === "lose" ? "Perdu… belle partie quand même." : "Égalité !";
      const detail = d.game === "pfc" ? "Vous : " + HANDS[d.mine] + " · " + d.other + " : " + HANDS[d.theirs] + "."
        : d.game === "piece" ? "La pièce tombe sur " + SIDES[d.coin].toLowerCase() + ". Vous aviez " + SIDES[d.mine].toLowerCase() + "." : "";
      const stage = elem("div", "p3d-stage");
      if (d.game === "piece") {
        stage.appendChild(elem("div", "p3d-coin", SIDES[d.coin]));
        sfx("ding");
      } else if (d.game === "pfc") {
        const hand = (cls, pick) => { const h = elem("span", "p3d-hand " + cls); h.append(elem("i", null, "✊"), elem("i", null, ["✊", "✋", "✌"][pick])); return h; };
        stage.append(hand("left", d.mine), elem("b", null, "VS"), hand("right", d.theirs));
        sfx("pas");
      }
      const verdict = elem("p", "p3d-luck p3d-reveal" + (d.game === "pfc" ? " fast" : ""), text);
      const more = elem("p", "p3d-reveal" + (d.game === "pfc" ? " fast" : ""), detail + " Sans rancune : à la fin, l'amour gagne toujours.");
      if (d.game === "morpion") { // la grille finale, avec la ligne gagnante en jaune
        verdict.className = "p3d-luck"; more.className = "";
        const line = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]].find((l) => d.board[l[0]] && l.every((c) => d.board[c] === d.board[l[0]])) || [];
        const grid = elem("div", "p3d-grid3");
        d.board.forEach((v, i) => { const cell = button(v === 1 ? "✕" : v === 2 ? "○" : "", () => {}, "p3d-cell" + (line.includes(i) ? " won" : "")); cell.disabled = true; grid.appendChild(cell); });
        nodes.push(grid);
      } else nodes.push(stage);
      nodes.push(verdict, more, panelClose("Fermer"));
      if (walk.duelDone !== d.id) {
        walk.duelDone = d.id;
        win("duel", true);
        if (d.result === "win" && ++progress.duelWins >= 3) win("champion");
        saveProgress();
        launchFireworks(1, true);
      }
    }
    showPanel(name, false, nodes);
  }

  /* --- La Kingfarm : plantes à ramasser, arbres à abattre à coups de poing,
     minerais à extraire dans la grotte. Tout repousse au bout d'un moment. */
  const FARM = {
    plante: { hp: 1, back: 25, verb: "Cueillir la citrouille", got: "Citrouille cueillie", win: ["jardinier", 10] },
    bois: { hp: 3, back: 40, verb: "Donner un coup de poing à l'arbre", got: "Arbre abattu : du bois", win: ["bucheron", 5] },
    minerai: { hp: 2, back: 45, verb: "Miner le filon", got: "Minerai extrait", win: ["mineur", 8] },
  };
  function hitNode(node) {
    if (!node.mesh.visible || performance.now() - walk.punch < 260) return;
    const def = FARM[node.kind];
    walk.rot = Math.atan2(node.x - walk.x, node.z - walk.z);
    walk.punch = performance.now();
    node.shake = 0.35;
    if (!sample(node.kind === "minerai" ? "pioche" : "coup")) sound([[node.kind === "minerai" ? 520 : 130, 0.16, 0.12]], 0.14, "triangle");
    if (--node.hp > 0) return;
    node.mesh.visible = false;
    node.out = def.back;
    node.hp = def.hp;
    walk.near = false;
    const bag = progress.bag;
    bag[node.kind]++;
    saveProgress();
    toast(def.got + " (" + bag[node.kind] + ").", 2.5);
    if (bag[node.kind] >= def.win[1]) win(def.win[0]);
    if (bag.plante + bag.bois + bag.minerai >= 30) win("fermier");
  }
  function stepFarm(dt, now) {
    let best = null;
    lot.farm.nodes.forEach((node) => {
      if (node.out > 0) { node.out -= dt; if (node.out <= 0) node.mesh.visible = true; }
      node.shake = Math.max(0, node.shake - dt);
      node.mesh.rotation.z = Math.sin(now * 46) * 0.09 * (node.shake / 0.35);
      if (!node.mesh.visible || !walk.on || walk.drive || walk.ride) return;
      const d = Math.hypot(walk.x - node.x, walk.z - node.z);
      if (d < 2.0 && (!best || d < best.d)) best = { d, node };
    });
    walk.farmNear = best;
    const cv = lot.farm.cave, inside = walk.on && Math.hypot(walk.x - cv.x, walk.z - cv.z) < cv.r + 0.3;
    cv.outer.visible = !inside;
    cv.inner.visible = inside;
  }
  const qs = (id) => progress.quests[id] || 0; // 0 : à proposer, 1 : en cours, 2 : à rendre, 3 : terminée
  function refreshQuests() {
    if (!lot) return;
    lot.quest.folk.forEach((f) => {
      const v = qs(f.id);
      f.tag.name.textContent = v === 0 ? "!" : v === 3 ? "♥" : "?";
      f.tag.node.classList.toggle("idle", v === 1);
      f.tag.node.classList.toggle("over", v === 3);
    });
    lot.quest.cat.model.root.visible = qs("chat") === 1;
    lot.quest.blooms.forEach((b, i) => { b.mesh.visible = qs("fleurs") === 1 && i >= progress.qn; });
  }
  function setQuest(id, v) {
    progress.quests[id] = v;
    saveProgress();
    refreshQuests();
  }
  // L'objectif d'une quête vient d'être rempli : il reste à retourner voir l'habitant.
  function questEvent(id) {
    if (qs(id) !== 1) return;
    setQuest(id, 2);
    toast("Quête : c'est fait ! Retournez voir " + QUESTS.find((q) => q.id === id).who + ".", 5);
  }
  /* Parler à un habitant : une bulle douce en bas de l'écran, comme dans les
     jeux de vie tranquille. */
  function talk(id) {
    const q = QUESTS.find((it) => it.id === id), v = qs(id);
    const f = lot.quest.folk.find((it) => it.id === id);
    walk.rot = Math.atan2(f.x - walk.x, f.z - walk.z);
    babble(id);
    const button = (label, fn) => { const b = elem("button", null, label); b.type = "button"; b.addEventListener("click", fn); return b; };
    const line = v === 0 ? q.ask : v === 1 ? "Alors, ça avance ? " + q.todo : v === 2 ? q.done : "Encore merci pour tout à l'heure !";
    const nodes = [elem("span", "p3d-who", q.who), elem("p", "p3d-say", line)];
    if (v === 0) {
      nodes.push(button("D'accord !", () => {
        if (id === "fleurs") progress.qn = 0;
        if (id === "coupe") progress.qcut = look.cut;
        setQuest(id, 1);
        closeResa();
        toast("Nouvelle quête : " + q.todo, 5);
      }), panelClose("Plus tard"));
    } else if (v === 2) {
      nodes.push(button("Avec plaisir !", () => {
        setQuest(id, 3);
        closeResa();
        const count = QUESTS.filter((it) => qs(it.id) === 3).length;
        toast("Quête terminée (" + count + "/" + QUESTS.length + ") : merci de la part de " + q.who + " !", 5);
        launchFireworks(2, true);
        win("voisin", true);
        if (count >= 3) win("serviable", true);
        if (count >= QUESTS.length) win("heros");
      }));
    } else nodes.push(panelClose(v === 1 ? "J'y vais" : "À bientôt"));
    showPanel(q.who, false, nodes);
    panel.classList.add("talk");
  }
  // Objectifs qu'on remplit en marchant : le chat, les fleurs dorées, le colis.
  function stepQuests(now) {
    const qz = lot.quest;
    qz.folk.forEach((f) => { // les habitants suivent le promeneur du regard
      const d = Math.hypot(walk.x - f.x, walk.z - f.z);
      const want = walk.on && d < 7 ? clamp(angleTo(0, Math.atan2(walk.x - f.x, walk.z - f.z) - f.rot, 1), -1, 1) : Math.sin(now * 0.6 + f.x) * 0.25;
      f.model.head.rotation.y = lerp(f.model.head.rotation.y, want, 0.08);
      f.model.body.position.y = Math.sin(now * 2 + f.x) * 0.012;
    });
    if (!walk.on || walk.drive || walk.ride) return;
    if (qs("chat") === 1 && Math.hypot(walk.x - qz.cat.x, walk.z - qz.cat.z) < 2.2) { say("Moustache ! Viens là."); questEvent("chat"); }
    if (qs("colis") === 1 && Math.hypot(walk.x - qz.drop.x, walk.z - qz.drop.z) < 3) { say("Colis déposé !"); questEvent("colis"); }
    if (qs("fleurs") === 1) qz.blooms.forEach((b, i) => {
      b.mesh.position.y = 0.55 + Math.sin(now * 3 + i) * 0.08;
      if (!b.mesh.visible || Math.hypot(walk.x - b.x, walk.z - b.z) > 1.4) return;
      b.mesh.visible = false;
      progress.qn = Math.min(5, progress.qn + 1);
      saveProgress();
      if (qz.blooms.every((bl) => !bl.mesh.visible)) questEvent("fleurs");
      else toast("Fleur dorée cueillie.", 2.5);
    });
  }
  // Réglages : volume par paliers, musique oui ou non. Gardés sur l'appareil.
  function openSettings() {
    const save = () => { store("access.plan3d.son", { vol: audioMix.vol, music: audioMix.music }); if (master) master.gain.value = audioMix.vol; openSettings(); sfx("pop"); };
    const row = elem("div", "p3d-row center");
    row.append(button("−", () => { audioMix.vol = Math.max(0, Math.round((audioMix.vol - 0.2) * 10) / 10); save(); }, "p3d-chip"),
      elem("b", null, audioMix.vol <= 0 ? "Son coupé" : "Volume " + Math.round(audioMix.vol * 100) + " %"),
      button("+", () => { audioMix.vol = Math.min(1, Math.round((audioMix.vol + 0.2) * 10) / 10); save(); }, "p3d-chip"));
    showPanel("Réglages du son", false, [panelTitle("⚙", "Réglages du son", "#5b4636"), elem("h4", null, "Volume"), row]
      .concat(choices("Musique de promenade", [[true, "Avec"], [false, "Sans"]], audioMix.music, (v) => { audioMix.music = v; save(); }))
      .concat([panelClose()]));
  }
  function openBalloons() {
    walk.zoom = { dist: 5.2, pitch: 0.12, y: 1.6 };
    const pick = (value) => { look.balloon = value; redress(); };
    showPanel("Ballons KingPar", true, [panelTitle("B", "Ballons KingPar", "#d92b3a"),
      elem("p", null, "Un ballon aux couleurs de la maison, offert. Avec lui, on saute plus haut et on retombe tout doucement.")]
      .concat(choices("Couleur", BALLOONS, look.balloon, pick, true))
      .concat(choices("Ou bien", [["none", "Lâcher le ballon"]], look.balloon === "none" ? "none" : "", pick))
      .concat([panelClose("C'est parfait")]));
  }
  /* L'accueil : à quoi sert ce monde en 3D. Affiché à la première visite sur
     l'appareil, puis à la demande (bouton « ? »). */
  function openWelcome() {
    const logo = elem("img", "p3d-hero");
    logo.src = new URL("./kingpar-logo.svg", import.meta.url).href;
    logo.alt = "KingPar";
    const go = elem("button", null, "Me promener");
    go.type = "button";
    go.addEventListener("click", () => { closeResa(); setWalk(true); });
    showPanel("Bienvenue chez KingPar", false, [logo, panelTitle("K", "Bienvenue chez KingPar", BRAND),
      elem("p", "p3d-lead2", "Ce monde en 3D montre le parking en direct : chaque place, chaque véhicule, à l'instant même."),
      elem("p", null, "Mais on n'est pas là que pour regarder. Promenez-vous, prenez le volant, filez au village de " + CITY_NAME +
        ", jouez aux stands, changez de tenue, adoptez un compagnon, croisez les autres visiteurs. On vient voir sa place… et profiter de la vie."),
      elem("p", "p3d-luck", "Et souvenez-vous : à la fin, l'amour gagne toujours."),
      go, panelClose("Voir le parking")]);
    store(WELCOME_KEY, true);
  }
  let welcomed = false;
  /* Monter dans la voiture d'un autre promeneur : on le suit, assis à côté de lui. */
  function rideWith(id) {
    const o = net.others.get(id);
    if (!o || !o.car || walk.drive || walk.ride) return;
    walk.ride = id;
    walk.y = 0; walk.vy = 0;
    walk.near = false;
    say("En voiture !");
    win("covoit");
  }
  function stopRide() {
    if (!walk.ride) return;
    const o = net.others.get(walk.ride), rot = o ? o.cur.rot : walk.rot;
    walk.ride = null;
    walk.near = false;
    const out = collide(walk.x + Math.cos(rot) * 2.1, walk.z - Math.sin(rot) * 2.1, 0.36, null);
    walk.x = out[0]; walk.z = out[1];
    walk.dog.x = walk.x + 0.7; walk.dog.z = walk.z - 0.5;
    player.root.visible = dog.root.visible = true;
    prompt.classList.remove("on");
  }
  const stopRideAction = { label: "Descendre de la voiture", action: stopRide };
  function openCarnet(tab) {
    tab = tab || "tampons";
    const tabs = choices("Carnet", [["tampons", "Tampons " + carnet.size + "/" + STAMPS.length],
      ["succes", "Succès " + progress.wins.size + "/" + WINS.length],
      ["quetes", "Quêtes " + QUESTS.filter((q) => qs(q.id) === 3).length + "/" + QUESTS.length], ["scores", "Scores"]], tab, openCarnet);
    const nodes = [panelTitle("★", "Carnet de " + (net.you ? net.you.pseudo : "promenade"), "#d92b3a"), tabs[1]];
    const listOf = (items, done, cls) => {
      const list = elem("ul", "p3d-stamps");
      items.forEach((it) => {
        const ok = done.has(it[0]);
        const li = elem("li", (cls || "") + (ok ? " done" : ""));
        li.append(elem("i", null, ok ? (cls ? "★" : "✓") : ""), elem("b", null, it[1]), elem("span", null, it[2]));
        list.appendChild(li);
      });
      return list;
    };
    if (tab === "tampons") {
      nodes.push(elem("p", null, carnet.size >= STAMPS.length
        ? "Carnet complet, bravo ! Vous connaissez le parking et son village par cœur."
        : STAMPS.length + " choses à découvrir, du parking au village de " + CITY_NAME + "."), listOf(STAMPS, carnet));
    } else if (tab === "quetes") {
      nodes.push(elem("p", null, "Les habitants de " + CITY_NAME + " ont un « ! » au-dessus de la tête quand ils ont un service à demander."),
        listOf(QUESTS.map((q) => [q.id, q.who, qs(q.id) === 0 ? "Allez lui parler." : qs(q.id) === 3 ? "Quête terminée." : qs(q.id) === 2 ? "C'est fait : retournez le voir." : q.todo]),
          new Set(QUESTS.filter((q) => qs(q.id) === 3).map((q) => q.id))));
    } else if (tab === "succes") {
      nodes.push(elem("p", null, "Votre rang : " + rank() + ". Les autres promeneurs voient votre nombre d'étoiles. " +
        (progress.goldDay === new Date().toISOString().slice(0, 10) ? "Ticket d'or du jour : trouvé." : "Un ticket d'or est caché quelque part aujourd'hui.")), listOf(WINS.map((w) => (w[3] && !progress.wins.has(w[0]) ? [w[0], "???", "Succès secret : à vous de le trouver."] : w)), progress.wins, "win"));
    } else {
      const table = elem("table", "p3d-scores"), head = elem("tr");
      ["Jeu", "Votre record", "Meilleur en ligne"].forEach((hh) => head.appendChild(elem("th", null, hh)));
      table.appendChild(head);
      const cells = {};
      Object.keys(GOALS).forEach((game) => {
        const row = elem("tr");
        cells[game] = elem("td", null, net.url ? "…" : "hors ligne");
        row.append(elem("td", null, GAME_NAMES[game]), elem("td", null, progress.best[game] != null ? String(progress.best[game]) : "—"), cells[game]);
        table.appendChild(row);
      });
      nodes.push(elem("p", null, "Les scores en ligne sont ceux des promeneurs depuis le dernier redémarrage du service."), table);
      if (net.url) {
        fetch(net.url + "/scores", { credentials: "omit", cache: "no-store" })
          .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
          .then((data) => Object.keys(cells).forEach((game) => {
            const top = data.scores && data.scores[game] && data.scores[game][0];
            cells[game].textContent = top ? top.score + " · " + top.pseudo : "personne encore";
          }))
          .catch(() => Object.keys(cells).forEach((game) => { cells[game].textContent = "indisponible"; }));
      }
    }
    nodes.push(elem("p", null, "Envie de venir pour de vrai ? La borne de réservation, sur le parvis, montre les places à réserver cette heure. " +
      "Le carnet est un jeu, gardé sur cet appareil : il ne donne droit à aucun tarif."), panelClose());
    showPanel("Carnet de promenade", false, nodes);
  }
  carnetBtn.addEventListener("click", () => { if (walk.panel) closeResa(); else openCarnet(); });

  /* L'agent du parking : il fait sa ronde tout seul. Il va voir une place mise
     de côté (un véhicule arrive), inspecte les véhicules garés, fait une pause
     à la guérite, salue le promeneur et complimente le chien. */
  function agentSay(kind) {
    let lines = AGENT_SAYS[kind];
    if (kind === "dog") lines = lines.concat("Oh, " + (dog.def.une ? "une " : "un ") + dog.def.name.toLowerCase() + " !");
    lot.agentTag.name.textContent = lines[Math.floor(Math.random() * lines.length)];
    npc.say = 2.6;
  }
  function agentRoute(tx, tz) {
    const side = LANE + 0.35, pts = [[npc.x, npc.z]];
    if (npc.x < 0) { pts.push([-1.3, 4.2]); pts.push([side, 4.2]); }
    else if (Math.abs(npc.z - tz) > 0.6 || tx < 0) pts.push([side, npc.z]);
    if (tx < 0) { pts.push([side, 4.2]); pts.push([-1.3, 4.2]); }
    else if (Math.abs(pts[pts.length - 1][1] - tz) > 0.6) pts.push([side, tz]);
    pts.push([tx, tz]);
    return makePath(pts, 0.8);
  }
  function agentThink() {
    const spots = [];
    let held = null;
    lot.zones.forEach((zone) => zone.spots.forEach((sp) => {
      if (sp.held && !held) held = sp;
      if (sp.vehicle && sp.vehicle.state === "parked") spots.push(sp);
    }));
    const front = (sp) => [sp.x, sp.aisleZ + Math.sign(sp.z - sp.aisleZ) * (AISLE / 2 - 0.7)];
    const roll = Math.random();
    let t;
    if (held) {
      const p = front(held);
      t = { x: p[0], z: p[1], face: [held.x, held.z], say: "guide", pause: 5 };
    } else if (roll < 0.14) {
      t = { x: -1.3, z: -0.9, face: [-1.3, -6], say: "pause", pause: 5 + Math.random() * 4 };
    } else if (spots.length && roll < 0.86) {
      const sp = spots[Math.floor(Math.random() * spots.length)], p = front(sp);
      t = { x: p[0], z: p[1], face: [sp.x, sp.z], say: MODELS[sp.vehicle.model].lean ? "moto" : "inspect", pause: 2.5 + Math.random() * 2.5 };
    } else {
      const az = lot.L.aisles[Math.floor(Math.random() * lot.L.aisles.length)] || 6;
      t = { x: lot.L.R0 + 2 + Math.random() * (lot.L.rowLen - 4), z: az, face: null, say: spots.length ? "calm" : "calm", pause: 2 + Math.random() * 2 };
    }
    npc.target = t;
    npc.path = agentRoute(t.x, t.z);
    npc.s = 0;
  }
  function stepAgent(dt, now) {
    npc.say = Math.max(0, npc.say - dt);
    npc.greet = Math.max(0, npc.greet - dt);
    // Il s'arrête pour saluer le promeneur, et remarque le chien qui aboie.
    const near = walk.on && !walk.drive ? Math.hypot(walk.x - npc.x, walk.z - npc.z) : 99;
    let goal = 0;
    if (npc.star) { // son plan dans la pub : il s'arrête, regarde la caméra et salue
      npc.rot = angleTo(npc.rot, Math.atan2(npc.star.x - npc.x, npc.star.z - npc.z), 1 - Math.exp(-dt * 6));
    } else if (near < 3.2) {
      if (npc.greet <= 0) { agentSay("hello"); npc.greet = 16; stamp("agent"); }
      npc.rot = angleTo(npc.rot, Math.atan2(walk.x - npc.x, walk.z - npc.z), 1 - Math.exp(-dt * 6));
    } else if (npc.path) {
      goal = 1.55;
      npc.s += npc.speed * dt;
      pathAt(npc.path, npc.s, pt);
      npc.x = pt.x; npc.z = pt.z;
      npc.rot = angleTo(npc.rot, pt.h, 1 - Math.exp(-dt * 8));
      if (npc.s >= npc.path.total) {
        npc.path = null;
        npc.wait = npc.target.pause;
        if (Math.random() < 0.75) agentSay(npc.target.say);
      }
    } else {
      const t = npc.target;
      if (t && t.face) npc.rot = angleTo(npc.rot, Math.atan2(t.face[0] - npc.x, t.face[1] - npc.z), 1 - Math.exp(-dt * 5));
      npc.wait -= dt;
      if (npc.wait <= 0) agentThink();
    }
    if (walk.dog.bark > 1.05 && npc.say <= 0 && Math.hypot(walk.dog.x - npc.x, walk.dog.z - npc.z) < 8) agentSay("dog");
    npc.speed = lerp(npc.speed, goal, 1 - Math.exp(-dt * 8));
    npc.phase += npc.speed * dt * 2.6;
    const stride = Math.min(1, npc.speed / 1.55), swing = Math.sin(npc.phase) * 0.6 * stride;
    agent.legL.rotation.x = swing; agent.legR.rotation.x = -swing;
    // À l'arrêt devant un véhicule : il note quelque chose (un bras levé).
    const noting = !npc.path && npc.target && npc.target.face && near >= 3.2;
    agent.armL.rotation.x = -swing * 0.8;
    agent.armR.rotation.x = npc.star ? -2.7 + Math.sin(now * 9) * 0.3 : noting ? -1.1 + Math.sin(now * 6) * 0.08 : swing * 0.8;
    agent.body.position.y = Math.abs(Math.sin(npc.phase)) * 0.04 * stride;
    agent.root.position.set(npc.x, 0, npc.z);
    agent.root.rotation.y = npc.rot;
    lot.agentTag.hidden = npc.say <= 0;
    lot.agentTag.pos.set(npc.x - lot.L.cx, 2.25, npc.z - lot.L.cz);
  }

  function bark() {
    const d = walk.dog;
    d.bark = 1.2;
    d.next = 7 + Math.random() * 10;
    const barks = dog.def.barks;
    lot.dogTag.name.textContent = barks[Math.floor(Math.random() * barks.length)];
  }
  function interact() {
    if (walk.near) walk.near.action();
  }
  function enterVehicle(rv) {
    if (walk.drive || !walk.on) return;
    walk.drive = rv;
    walk.y = 0; walk.vy = 0; walk.speed = 0;
    walk.keys = {};
    walk.near = false; // force le recalcul de l'invite
    walk.yaw = rv.rot;
    hint.textContent = HINT_DRIVE;
    actBtn.textContent = "Frein";
    speedoUnit.textContent = "km/h · " + rv.def.name;
    speedo.classList.add("on");
    sfx("porte");
    bark();
    stamp("volant");
  }
  function exitVehicle() {
    const rv = walk.drive;
    if (!rv) return;
    rv.v = 0; rv.steer = 0;
    rv.body.rotation.z = 0;
    // On descend côté conducteur (à gauche), là où il y a de la place.
    const side = rv.def.r + 0.85;
    const out = collide(rv.x + Math.cos(rv.rot) * side, rv.z - Math.sin(rv.rot) * side, 0.36, null);
    walk.x = out[0]; walk.z = out[1];
    walk.rot = rv.rot; walk.yaw = rv.rot;
    walk.dog.x = walk.x + 0.7; walk.dog.z = walk.z - 0.5; walk.dog.y = 0;
    walk.drive = null;
    walk.near = false; // force le recalcul de l'invite
    prompt.classList.remove("on");
    player.root.visible = dog.root.visible = true;
    dog.root.scale.setScalar(dog.def.scale);
    dog.head.rotation.z = 0;
    player.root.rotation.z = 0;
    hint.textContent = walk.on ? HINT_WALK : HINT_ORBIT;
    actBtn.textContent = "Sauter";
    speedo.classList.remove("on");
  }
  const leaveAction = { label: "Descendre du véhicule", action: exitVehicle };
  const tuneAction = { label: "Personnaliser le véhicule (KingPar Tuning)", action: () => openTuning(walk.drive) };
  const pumpAction = { label: "Faire le plein pile (mini-jeu)", action: () => openGame("plein", "station") };
  const rentalActions = rentals.map((rv) => ({ rv, label: "Conduire " + rv.def.label, action: () => enterVehicle(rv) }));
  ["pointerdown", "pointerup", "pointercancel", "pointerleave"].forEach((type) => {
    actBtn.addEventListener(type, (e) => { walk.keys.Space = type === "pointerdown"; e.preventDefault(); });
  });

  /* Conduite : accélérateur, frein, direction ; la vitesse retombe seule ; on
     glisse le long des obstacles et on rebondit sur un choc de face. */
  function stepDrive(dt, now, throttle, steer, handbrake) {
    const rv = walk.drive, def = rv.def;
    if (throttle > 0.05) rv.v += (rv.v < -0.2 ? 22 : def.acc) * throttle * dt;
    else if (throttle < -0.05) rv.v -= (rv.v > 0.3 ? 24 : def.acc * 0.55) * -throttle * dt;
    rv.v *= Math.exp(-dt * (handbrake ? 3.4 : 0.32));
    if (Math.abs(throttle) < 0.05 && Math.abs(rv.v) < 0.12) rv.v = 0;
    rv.v = clamp(rv.v, -7, def.max);
    rv.steer = lerp(rv.steer, clamp(steer, -1, 1), 1 - Math.exp(-dt * 8));
    rv.rot -= rv.steer * (2.3 / (1 + Math.abs(rv.v) / 11)) * clamp(rv.v / 4, -1, 1) * dt;
    const travel = rv.v * dt, steps = Math.max(1, Math.ceil(Math.abs(travel) / 0.25));
    for (let i = 0; i < steps; i++) {
      const fx = Math.sin(rv.rot), fz = Math.cos(rv.rot);
      let cx = rv.x + (fx * travel) / steps, cz = rv.z + (fz * travel) / steps, pushed = 0;
      for (let kk = 0; kk < 3; kk++) {
        const off = [0, 1, -1][kk] * def.half * 0.8;
        const res = collide(cx + fx * off, cz + fz * off, def.r, rv);
        const ddx = res[0] - (cx + fx * off), ddz = res[1] - (cz + fz * off);
        cx += ddx; cz += ddz;
        pushed += Math.hypot(ddx, ddz);
      }
      rv.x = cx; rv.z = cz;
      if (pushed > 0.004) {
        if (pushed > (Math.abs(travel) / steps) * 0.7) { rv.v *= -0.22; break; } // choc de face
        rv.v *= 0.9; // frottement le long d'un obstacle
      }
    }
    const ratio = clamp(rv.v / def.max, -1, 1);
    const lean = BIKES.includes(rv.def.model) ? rv.steer * 0.36 * Math.abs(ratio) * 2 : -rv.steer * 0.05 * Math.abs(ratio) * 2;
    rv.body.rotation.z = lerp(rv.body.rotation.z, clamp(lean, -0.4, 0.4), 1 - Math.exp(-dt * 9));
    walk.x = rv.x; walk.z = rv.z; walk.rot = rv.rot; walk.speed = Math.abs(rv.v);
    // Le conducteur : assis sur le scooter (le chien à ses pieds), caché en voiture —
    // où le chien passe la tête par la fenêtre du passager.
    const onBike = BIKES.includes(def.model);
    if (!progress.cars.includes(def.model)) { progress.cars.push(def.model); saveProgress(); }
    if (progress.cars.length >= RENTALS.length) win("garage");
    player.root.visible = onBike;
    dog.root.visible = true;
    dog.root.scale.setScalar(Math.min(dog.def.scale, 1.5)); // à bord, les grands se font petits
    if (!onBike) {
      const seat = def.model === "camper" ? { fwd: 2.3, side: 1.0, y: 1.02 } : def.model === "suv" ? { fwd: 0.3, side: 0.8, y: 0.68 } : { fwd: 0.3, side: 0.76, y: 0.52 };
      const d = walk.dog, fx = Math.sin(rv.rot), fz = Math.cos(rv.rot);
      d.x = rv.x + fx * seat.fwd - fz * seat.side; d.z = rv.z + fz * seat.fwd + fx * seat.side;
      d.rot = rv.rot - Math.PI / 2; d.y = seat.y - Math.max(0, dog.top - 0.96);
    }
    if (onBike) {
      player.root.position.set(rv.x - Math.sin(rv.rot) * 0.25, 0.26, rv.z - Math.cos(rv.rot) * 0.25);
      player.root.rotation.set(0, rv.rot, rv.body.rotation.z);
      player.legL.rotation.x = player.legR.rotation.x = -1.35;
      player.armL.rotation.x = player.armR.rotation.x = -1.15;
      player.body.position.y = 0; player.body.rotation.x = 0.1;
      const d = walk.dog;
      d.x = rv.x + Math.sin(rv.rot) * 0.42; d.z = rv.z + Math.cos(rv.rot) * 0.42; d.rot = rv.rot; d.y = 0.3;
    }
    // La caméra se replace dans l'axe du véhicule, sauf si on vient de regarder ailleurs.
    if (now - walk.look > 1.6 && !walk.tuning) walk.yaw = angleTo(walk.yaw, rv.rot, 1 - Math.exp(-dt * 3.2));
    speedoValue.textContent = String(Math.round(Math.abs(rv.v) * 3.6));
    // Succès du volant, et la place d'entraînement : arrêté dedans, on est noté.
    progress.km += (Math.abs(rv.v) * dt) / 1000;
    if (progress.km >= 1) win("km");
    if (rv.v >= def.max * 0.97) win("bolide");
    const bay = lot.city.bay, inBay = Math.abs(rv.x - bay.x) < bay.w / 2 && Math.abs(rv.z - bay.z) < bay.d / 2;
    if (!inBay) walk.parked = false;
    else if (!walk.parked && Math.abs(rv.v) < 0.15 && !onBike) {
      walk.parked = true;
      const off = Math.hypot(rv.x - bay.x, (rv.z - bay.z) * 0.6);
      const score = clamp(Math.round(100 - off * 48 - Math.abs(Math.sin(rv.rot)) * 150), 0, 100);
      toast("Créneau : " + score + " / 100" + (score >= GOALS.creneau ? ". Parfait !" : ". Garez-vous droit, bien au centre."), 5);
      gameDone("creneau", score);
    }
  }
  function openResa() {
    const title = panelTitle("R", "Borne de réservation");
    const free = lot.zones.reduce((n, zone) => n + Math.max(0, zone.cap - zone.taken), 0);
    const lead = elem("p", "p3d-lead");
    lead.append(elem("b", null, String(free)), document.createTextNode(
      (free > 1 ? " places libres" : " place libre") + " en ce moment" + (data.source === "live" ? "" : " (démonstration)")));
    const perks = elem("ul", "p3d-perks");
    [
      "Entrée sans ticket : votre plaque suffit.",
      "Une zone pour chacun : " + lot.zones.map((zone) => zone.label).join(", ") + ".",
      "Réservation à l'heure : votre place vous attend à l'arrivée.",
      "Occupation affichée en direct, ici même.",
    ].forEach((line) => perks.appendChild(elem("li", null, line)));
    const intro = elem("p", null,
      "Une réservation se prend à l'heure, auprès du service Booking, et se paie à l'avance. " +
      "À votre arrivée, la borne reconnaît votre plaque et vous attribue une place réservée ; " +
      "rien à payer en sortant dans votre créneau.");
    const table = elem("table");
    const headRow = elem("tr");
    ["Zone", "Réservables cette heure", "Sur place avec réservation"].forEach((h) => headRow.appendChild(elem("th", null, h)));
    table.appendChild(headRow);
    lot.zones.forEach((zone) => {
      const row = elem("tr");
      const name = elem("td");
      const dot = elem("i");
      dot.style.setProperty("--c", zone.kind.color);
      name.append(dot, document.createTextNode(zone.label));
      row.append(name,
        elem("td", null, zone.reservable == null ? "non communiqué" : zone.reservable ? zone.reservable + " place(s)" : "aucune"),
        elem("td", null, zone.reserved ? zone.reserved + " véhicule(s)" : "aucun"));
      table.appendChild(row);
    });
    const source = elem("p", null, data.source === "live"
      ? "Chiffres de Booking pour l'heure en cours, véhicules comptés par Access."
      : "Chiffres de démonstration.");
    showPanel("Borne de réservation", false, [title, lead, perks, intro, table, source, panelClose()]);
    stamp("resa");
  }
  function closeResa() {
    if (walk.ad) { endAd(); return; }
    panel.classList.remove("on");
    if (walk.panel) walk.near = false; // l'invite revient à la prochaine image
    if (walk.game) { walk.game.stop(); walk.game = null; }
    if (bareHead) { bareHead = false; swapModel(player, buildPerson(playerLook())); }
    walk.zoom = null;
    walk.tuning = null;
    walk.panel = false;
  }
  prompt.addEventListener("click", () => { if (walk.panel) closeResa(); else interact(); });

  /* Personnage et chien : déplacement, animation, caméra. Appelé à chaque image
     (le chien remue la queue même quand on regarde le plan de haut). */
  function stepWalk(dt, now) {
    const L = lot.L, d = walk.dog, k = walk.keys;
    let f = 0, sd = 0, turn = 0, run = false;
    if (walk.ride) { // passager : on suit la voiture de l'autre promeneur
      const host = net.others.get(walk.ride);
      if (!host || !host.car || BIKES.includes(host.goal.drive) || !walk.on) stopRide();
      else {
        walk.x = host.cur.x; walk.z = host.cur.z; walk.rot = host.cur.rot;
        walk.yaw = angleTo(walk.yaw, host.cur.rot, 1 - Math.exp(-dt * 3));
      }
    }
    if (walk.on && !walk.panel && !walk.ride) {
      f = (k.KeyW || k.ArrowUp ? 1 : 0) - (k.KeyS || k.ArrowDown ? 1 : 0);
      sd = (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0);
      turn = (k.ArrowRight ? 1 : 0) - (k.ArrowLeft ? 1 : 0);
      run = Boolean(k.ShiftLeft || k.ShiftRight);
      if (walk.joy) { f -= walk.joy.y; sd += walk.joy.x; run = run || walk.joy.mag > 0.9; }
    }
    if (walk.tuning) { // sur le podium, le véhicule tourne pour se montrer sous tous les angles
      const tv = walk.tuning, pod = lot.city.podium;
      tv.x = pod.x; tv.z = pod.z; tv.v = 0;
      tv.rot += dt * 0.5;
      pod.mesh.rotation.y = tv.rot;
    }
    rentals.forEach((rv) => {
      if (rv !== walk.drive) rv.v = 0;
      rv.root.position.set(rv.x, 0, rv.z);
      rv.root.rotation.y = rv.rot;
    });
    driveLight.intensity = walk.drive ? driveLightNight * 60 : 0;
    if (walk.drive) {
      stepDrive(dt, now, f, sd + turn, Boolean(k.Space));
      const rv = walk.drive;
      rv.root.position.set(rv.x, 0, rv.z);
      rv.root.rotation.y = rv.rot;
      driveLight.position.set(rv.x + Math.sin(rv.rot) * (rv.def.half + 1.6), 1.1, rv.z + Math.cos(rv.rot) * (rv.def.half + 1.6));
    }
    const driving = Boolean(walk.drive);
    if (!driving) walk.yaw -= turn * dt * 2.0;
    const len = driving ? 0 : Math.hypot(f, sd);
    const goal = len > 0.08 ? (run ? 8.4 : 4.3) * Math.min(1, len) : 0;
    if (!driving) walk.speed = lerp(walk.speed, goal, 1 - Math.exp(-dt * 11));
    // Saut (Espace) : le chien saute avec son maître.
    if (!driving) {
      if (k.Space && walk.on && !walk.panel && !walk.ride && walk.y === 0) {
        if (look.balloon !== "none") win("ballon");
        sfx("saut");
        const pd = lot.city.pond;
        if (pd && Math.abs(walk.x - pd.x) < 1.1 && Math.abs(walk.z - pd.z) < 1.6) win("ange");
        if (look.balloon !== "none" && groundAt(walk.x, walk.z) >= lot.city.hill.h - 0.01) win("montgolfiere");
        walk.vy = look.balloon !== "none" ? 6.6 : 5.8;
        if (d.y === 0) d.vy = 4.4;
        if (++progress.jumps >= 25) win("kangourou");
      }
      walk.vy -= (look.balloon !== "none" && walk.vy < 0 ? 5.5 : 17) * dt; // le ballon freine la chute
      walk.y = Math.max(0, walk.y + walk.vy * dt);
      if (walk.y === 0) walk.vy = 0;
      d.vy -= 17 * dt;
      d.y = Math.max(0, d.y + d.vy * dt);
      if (d.y === 0) d.vy = 0;
    }
    if (len > 0.08) {
      const dx = Math.sin(walk.yaw), dz = Math.cos(walk.yaw);
      const mx = (dx * f - dz * sd) / len, mz = (dz * f + dx * sd) / len;
      walk.rot = angleTo(walk.rot, Math.atan2(mx, mz), 1 - Math.exp(-dt * 13));
      // Par petits pas : même à faible cadence d'images, on ne traverse rien.
      const steps = Math.max(1, Math.ceil((walk.speed * dt) / 0.2));
      for (let i = 0; i < steps; i++) {
        const next = collide(walk.x + (mx * walk.speed * dt) / steps, walk.z + (mz * walk.speed * dt) / steps, 0.36);
        walk.x = next[0]; walk.z = next[1];
      }
      walk.still = 0;
      if (walk.y === 0 && Math.floor(walk.phase / Math.PI) !== Math.floor((walk.phase - walk.speed * dt * 2.4) / Math.PI)) sfx("pas"); // un pas
      progress.walked += walk.speed * dt;
      if (progress.walked >= 2000) win("marche");
    } else {
      walk.still += dt;
    }
    if (!driving) {
      walk.phase += walk.speed * dt * 2.4;
      const stride = Math.min(1, walk.speed / 4.3), swing = Math.sin(walk.phase) * 0.8 * stride;
      const air = walk.y > 0.02;
      player.legL.rotation.x = air ? -0.55 : swing; player.legR.rotation.x = air ? 0.45 : -swing;
      player.armL.rotation.x = air ? -2.5 : -swing * 0.85; player.armR.rotation.x = air ? -2.5 : swing * 0.85;
      player.body.position.y = Math.abs(Math.sin(walk.phase)) * 0.06 * stride + Math.sin(now * 2.1) * 0.008;
      player.body.rotation.x = stride * (walk.speed > 6 ? 0.12 : 0.04);
      player.root.position.set(walk.x, walk.y + groundAt(walk.x, walk.z), walk.z);
      player.root.rotation.set(0, walk.rot, 0);
      player.head.rotation.y = walk.speed < 0.3 ? Math.sin(now * 0.7) * 0.28 : 0; // à l'arrêt, il regarde autour de lui
      player.body.rotation.z = Math.sin(walk.phase) * 0.07 * stride; // il se dandine
      const punched = (performance.now() - walk.punch) / 300; // coup de poing : le bras droit part en avant
      if (punched < 1) {
        player.armR.rotation.x = -2.7 + punched * 2.3;
        player.body.rotation.x = 0.14;
      }
      player.blink(now % 4.3 < 0.13 || (now % 9.7 > 5 && now % 9.7 < 5.12));
      player.head.rotation.x = air ? -0.2 : 0;
      if (player.balloon) {
        player.balloon.rotation.z = Math.sin(now * 1.7) * 0.07;
        player.balloon.rotation.x = -Math.min(0.5, walk.speed * 0.045);
      }
    }
    if (walk.ride) { player.root.visible = false; dog.root.visible = false; }
    // Bulle du promeneur, message du carnet
    walk.say = Math.max(0, walk.say - dt);
    lot.playerTag.hidden = walk.say <= 0 || !walk.on;
    lot.playerTag.pos.set(walk.x - L.cx, (driving ? 2.6 : 2.2 + walk.y + groundAt(walk.x, walk.z)), walk.z - L.cz);
    if (walk.toast > 0) { walk.toast -= dt; if (walk.toast <= 0) toastBox.classList.remove("on"); }

    if (driving) {
      // À bord : immobile aux pieds du conducteur (scooter), ou caché (voiture).
      dog.root.position.set(d.x, d.y, d.z);
      dog.root.rotation.y = d.rot;
      dog.tail.rotation.z = Math.sin(now * 18) * dog.wag;
      dog.legs.forEach((leg) => { leg.rotation.x = 0; });
      d.bark = Math.max(0, d.bark - dt);
      dog.head.rotation.x = d.bark > 0 ? -0.5 : 0;
      // La tête au vent : elle dodeline avec la vitesse.
      dog.head.rotation.z = Math.sin(now * 11) * 0.1 * Math.min(1, walk.speed / 8);
      dog.body.position.y = 0;
      d.next -= dt;
      if (d.next <= 0 && walk.speed > 10) bark();
      lot.dogTag.hidden = d.bark <= 0;
      lot.dogTag.pos.set(d.x - L.cx, 1.6, d.z - L.cz);
    } else {
      stepDog(dt, now);
    }
    stepCamera(dt, now);
  }

  function stepDog(dt, now) {
    const L = lot.L, d = walk.dog;
    // Le chihuahua : au pied quand on marche, il flâne et aboie quand on s'arrête.
    const sn = Math.sin(walk.rot), cs = Math.cos(walk.rot);
    let tx = walk.x - sn * 0.7 - cs * 0.6, tz = walk.z - cs * 0.7 + sn * 0.6;
    if (walk.still > 2.5) {
      d.roam -= dt;
      if (d.roam <= 0 || d.tx == null) {
        const a = Math.random() * Math.PI * 2, r = 0.9 + Math.random() * 1.9;
        d.tx = walk.x + Math.cos(a) * r; d.tz = walk.z + Math.sin(a) * r;
        d.roam = 2.2 + Math.random() * 3.5;
      }
      tx = d.tx; tz = d.tz;
    } else {
      d.tx = null;
    }
    // Panneau ouvert (boutique) : il vient s'asseoir devant, bien en vue.
    if (walk.panel) { tx = walk.x + sn * 1.0 + cs * 0.95; tz = walk.z + cs * 1.0 - sn * 0.95; }
    let ddx = tx - d.x, ddz = tz - d.z;
    const dist = Math.hypot(ddx, ddz);
    if (dist > 16) { d.x = tx; d.z = tz; ddx = ddz = 0; }
    const dogGoal = dist > 0.22 ? clamp(dist * 3.6, 1.1, 11) : 0;
    d.speed = lerp(d.speed, dogGoal, 1 - Math.exp(-dt * 12));
    if (dist > 0.22) {
      d.rot = angleTo(d.rot, Math.atan2(ddx, ddz), 1 - Math.exp(-dt * 14));
      const next = collide(d.x + (ddx / dist) * d.speed * dt, d.z + (ddz / dist) * d.speed * dt, 0.2);
      d.x = next[0]; d.z = next[1];
    } else if (walk.still > 0.6) {
      d.rot = angleTo(d.rot, Math.atan2(walk.x - d.x, walk.z - d.z), 1 - Math.exp(-dt * 4)); // regarde son maître
    }
    d.phase += d.speed * dt * 9;
    const trot = Math.min(1, d.speed / 3) * 0.9;
    dog.legs[0].rotation.x = dog.legs[3].rotation.x = Math.sin(d.phase) * trot;
    dog.legs[1].rotation.x = dog.legs[2].rotation.x = -Math.sin(d.phase) * trot;
    dog.tail.rotation.z = Math.sin(now * (d.speed > 0.5 ? 20 : 12)) * dog.wag;
    dog.head.rotation.z = d.speed < 0.3 ? Math.sin(now * 1.3) * 0.16 : 0;
    d.bark = Math.max(0, d.bark - dt);
    dog.body.position.y = d.bark > 0 ? Math.abs(Math.sin(d.bark * 13)) * 0.13 : Math.abs(Math.sin(d.phase)) * (dog.def.hop ? 0.1 : 0.015) * trot;
    dog.head.rotation.x = d.bark > 0 ? -0.5 : 0;
    dog.root.position.set(d.x, d.y + groundAt(d.x, d.z), d.z);
    dog.root.rotation.y = d.rot;
    d.next -= dt;
    if (d.next <= 0) { if (walk.on) bark(); else d.next = 8; }
    lot.dogTag.hidden = d.bark <= 0;
    lot.dogTag.pos.set(d.x - L.cx, 0.3 + 0.46 * dog.def.scale + d.y + groundAt(d.x, d.z), d.z - L.cz);
  }

  function stepCamera(dt, now) {
    if (!walk.on) return;
    const red = lot.city.adBtn; // le bouton rouge palpite, et s'enfonce quand on appuie
    red.press = Math.max(0, red.press - dt * 2.5);
    red.mesh.scale.y = 1 - 0.6 * Math.sin(Math.min(1, red.press) * Math.PI);
    red.mesh.material.emissiveIntensity = walk.ad ? 1.1 : 0.35 + 0.3 * Math.sin(now * 4);
    if (walk.ad) { stepAd(dt, now); return; }
    const L = lot.L, rv = walk.drive;
    // Caméra dans le dos, un peu au-dessus ; plus loin et plus large en voiture.
    const zoom = rv && !(walk.zoom && walk.zoom.at) ? null : walk.zoom, wide = renderer.domElement.clientWidth > 720;
    let pitch = zoom ? zoom.pitch : walk.pitch, aim = zoom ? zoom.y : 1.5;
    let dist = zoom ? zoom.dist : rv ? rv.def.cam * (walk.dist / 7.5) : walk.dist;
    if (zoom && !wide) { // sur téléphone, le panneau monte du bas : on cadre le sujet dans le haut de l'écran
      if (zoom.at) dist *= 1.55;
      aim -= dist * 0.27;
      pitch += 0.25;
    }
    const focus = zoom && zoom.at ? zoom.at : walk; // le podium du tuning, ou le promeneur
    // Le panneau occupe la droite de l'écran : on vise un peu à côté, le véhicule reste visible.
    const aside = zoom && zoom.at && wide ? dist * 0.24 : 0;
    const cp = Math.cos(pitch), px = focus.x - L.cx - Math.cos(walk.yaw) * aside, pz = focus.z - L.cz + Math.sin(walk.yaw) * aside;
    const lift = rv || focus !== walk ? 0 : walk.y * 0.6 + groundAt(walk.x, walk.z);
    walkCam.set(px - Math.sin(walk.yaw) * dist * cp, aim + 0.1 + lift + dist * Math.sin(pitch), pz - Math.cos(walk.yaw) * dist * cp);
    camera.position.lerp(walkCam, 1 - Math.exp(-dt * 12));
    camera.lookAt(px, aim + lift, pz);
    const fov = 58 + (rv ? clamp(Math.abs(rv.v), 0, 30) * 0.5 : 0);
    walk.fov = lerp(walk.fov, fov, 1 - Math.exp(-dt * 4));
    if (Math.abs(camera.fov - walk.fov) > 0.05) { camera.fov = walk.fov; camera.updateProjectionMatrix(); }

    // Ce qu'on peut utiliser ici, et la zone où l'on se trouve.
    let near = null, best = 2.6;
    if (walk.ride) near = stopRideAction;
    else if (rv) {
      const pump = lot.city.pumps, pod = lot.city.podium;
      if (Math.abs(rv.v) < 2.5 && Math.hypot(rv.x - pod.x, rv.z - pod.z) < 8) near = tuneAction;
      else if (Math.abs(rv.v) < 2.5) near = walk.fuel <= 0 && Math.hypot(rv.x - pump.x, rv.z - pump.z) < 7.5 ? pumpAction : leaveAction;
    } else {
      lot.points.forEach((pt) => {
        const dd = Math.hypot(pt.x - walk.x, pt.z - walk.z);
        if (dd < best) { best = dd; near = pt; }
      });
      rentalActions.forEach((ra) => {
        const dd = Math.hypot(ra.rv.x - walk.x, ra.rv.z - walk.z) - ra.rv.def.half;
        if (dd < best - 0.4) { best = dd; near = ra; }
      });
      if (net.offer && net.offer.d < best) { best = net.offer.d; near = net.offer.o.rideAction; }
      if (net.duelOffer && net.duelOffer.d < best && !net.duels.length) { best = net.duelOffer.d; near = net.duelOffer.o.duelAction; }
      if (walk.farmNear && walk.farmNear.d < best) near = walk.farmNear.node.action;
    }
    if (near !== walk.near) {
      walk.near = near;
      prompt.classList.toggle("on", Boolean(near));
      if (near) promptText.textContent = near.label;
    }
    const zone = lot.zones.find((z) => walk.x > z.bounds[0] - 0.5 && walk.x < z.bounds[1] + 0.5 && walk.z > z.bounds[2] - 0.5 && walk.z < z.bounds[3] + 0.5) || null;
    const c = lot.city;
    const inTown = !zone && walk.x > c.x0 - 14 && walk.x < c.x1 + 14 && walk.z > c.z0 && walk.z < c.z1;
    if (zone && !rv) stamp("parking");
    if (night > 0.5) win("nuit");
    walk.fuel = Math.max(0, walk.fuel - dt);
    walk.saveIn -= dt;
    if (walk.saveIn <= 0) { walk.saveIn = 20; saveProgress(); }
    if (walk.x > c.gate && walk.x < c.gate + 8 && Math.abs(walk.z - ROAD_Z) < 7) stamp("arche");
    if (c.pond && !rv && Math.abs(walk.x - c.pond.x) < 1.1 && Math.abs(walk.z - c.pond.z) < 1.6) stamp("pont");
    const bag = progress.bag, inFarm = inTown && Math.hypot(walk.x - lot.farm.x, walk.z - lot.farm.z) < 24;
    if (inFarm) stamp("ferme");
    const key = zone ? zone.name + ":" + zone.taken + ":" + zone.cap : inFarm ? "ferme:" + bag.plante + ":" + bag.bois + ":" + bag.minerai : inTown ? "ville" : "";
    if (key !== walk.zone) {
      walk.zone = key;
      here.classList.toggle("on", Boolean(zone) || inTown);
      if (inTown) {
        hereDot.style.setProperty("--c", "#1e66f5");
        hereName.textContent = CITY_NAME;
        hereCount.textContent = "le village du parking";
        if (inFarm) {
          hereDot.style.setProperty("--c", "#40a02b");
          hereName.textContent = "Kingfarm";
          hereCount.textContent = "citrouilles " + bag.plante + " · bois " + bag.bois + " · minerai " + bag.minerai;
        }
      }
      if (zone) {
        hereDot.style.setProperty("--c", zone.kind.color);
        hereName.textContent = "Zone " + zone.label;
        const free = zone.cap - zone.taken;
        hereCount.textContent = zone.taken + "/" + zone.cap + (free > 0 ? " · " + free + " libre(s)" : " · complet");
      }
    }
  }
  const walkCam = new THREE.Vector3();

  // --- Survol : véhicule ou place ----------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const hit = new THREE.Vector3();
  function updateHover(force) {
    if (!lot || !pointer || walk.on || (pointers.size && !force)) return;
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
        tipSub.textContent = (data.source === "live" ? "Place comptée par Parking" : "Véhicule de démonstration") +
          (v.reserved ? " · entré avec une réservation" : "");
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
  let driveLightNight = 0;
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
    M.house.emissiveIntensity = n * 1.25;
    M.chochin.color.copy(mix("#f2c14e", "#ffe7a8", n));
    M.petal.opacity = lerp(0.95, 0.6, n);
    M.far.color.setScalar(lerp(1, 0.16, n));
    M.hill.color.copy(mix("#86c46a", "#24452f", n));
    driveLightNight = n;
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
    // Barrières (elles s'ouvrent aussi devant le véhicule qu'on conduit)
    if (walk.drive && walk.drive.z > -11 && walk.drive.z < 5.5) {
      if (Math.abs(walk.drive.x - IN_X) < 1.75) wantIn = true;
      if (Math.abs(walk.drive.x - OUT_X) < 1.75) wantOut = true;
    }
    [[lot.gateIn, wantIn], [lot.gateOut, wantOut]].forEach((g) => {
      g[0].angle = lerp(g[0].angle, g[1] ? 1.42 : 0, 1 - Math.exp(-dt * (g[1] ? 9 : 4)));
      g[0].pivot.rotation.z = g[0].angle;
    });
    // Repères « R » : suivent les véhicules réservés, avec un léger flottement.
    let r = 0;
    lot.zones.forEach((zone) => {
      zone.vehicles.forEach((v) => {
        if (!v.reserved || v.state === "gone" || r >= lot.resaSprites.length) return;
        const sprite = lot.resaSprites[r++];
        sprite.visible = true;
        sprite.position.set(v.x, (RESA_HEIGHT[v.model] || 2.4) + Math.sin(now * 2.2 + v.id) * 0.12, v.z);
      });
    });
    for (; r < lot.resaSprites.length; r++) lot.resaSprites[r].visible = false;
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
    // L'agent fait sa ronde ; pétales et carpes du village.
    stepAgent(dt, now);
    const city = lot.city, pp = city.petals.geometry.attributes.position, seed = city.petals.userData.seed;
    for (let i = 0; i < pp.count; i++) {
      let y = pp.getY(i) - (0.55 + (i % 5) * 0.09) * dt;
      if (y < 0.15) y = 13.5;
      pp.setY(i, y);
      pp.setX(i, pp.getX(i) + Math.sin(now * 0.9 + seed[i]) * 0.45 * dt);
    }
    pp.needsUpdate = true;
    city.koi.forEach((fish) => {
      const u = fish.userData, a = u.a + now * u.speed;
      fish.position.set(city.pond.x + Math.cos(a) * city.pond.rx * u.r, 0.25, city.pond.z + Math.sin(a) * city.pond.rz * u.r);
      fish.rotation.y = -a;
    });
    stepMusic(dt);
    BEND.value = lerp(BEND.value, walk.on && !reduceMotion ? BEND_MAX : 0, 1 - Math.exp(-dt * 2.5));
    stepFireworks(dt);
    stepNet(dt);
    stepLive(now);
    stepQuests(now);
    stepFarm(dt, now);
    // Promeneur et chien (toujours animés) ; en promenade, la caméra les suit.
    stepWalk(dt, now);
    sun.target.position.set(0, 0, 0);
    if (walk.on) return;
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
      const bx = t.pos.x - camera.position.x, bz = t.pos.z - camera.position.z; // même courbure que le décor
      proj.set(t.pos.x, t.pos.y - BEND.value * (bx * bx + bz * bz), t.pos.z).project(camera);
      const visible = !t.hidden && proj.z < 1 && proj.x > -1.15 && proj.x < 1.15 && proj.y > -1.15 && proj.y < 1.15;
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
    camera.fov = walk.on ? walk.fov : w < h ? 54 : 40;
    // Le parking est décalé pour ne pas passer sous la légende (pas en promenade).
    const narrow = w < 640;
    if (walk.on) camera.clearViewOffset();
    else camera.setViewOffset(w, h, narrow ? 0 : -w * 0.07, narrow ? h * 0.09 : h * 0.04, w, h);
    camera.updateProjectionMatrix();
  }
  const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
  if (observer) observer.observe(container);

  function frame(time) {
    raf = requestAnimationFrame(frame);
    const now = time / 1000;
    const dt = Math.min(0.1, Math.max(0.001, now - last));
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
  const walkBtn = toolButton("Promenade", "Se promener dans le parking avec un personnage (ZQSD)", () => setWalk(!walk.on), false);
  toolButton("?", "À propos de ce monde en 3D", () => openWelcome());
  toolButton("⚙", "Réglages du son : volume et musique", () => openSettings());
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
      if (on && !welcomed && lot) {
        welcomed = true;
        let seen = false;
        try { seen = Boolean(window.localStorage.getItem(WELCOME_KEY)); } catch (err) { /* stockage indisponible */ }
        if (!seen) openWelcome();
      }
    },
    focus(name) {
      const zone = lot && lot.zones.find((z) => z.name === name);
      if (zone) focusZone(zone);
    },
    /* Entre en promenade (personnage à la troisième personne) ou en sort. */
    walk(on, at) {
      setWalk(on !== false);
      if (at && lot) {
        // Placement direct (repère du parking) : utile aux démonstrations et aux tests.
        if (at.x != null) walk.x = at.x;
        if (at.z != null) walk.z = at.z;
        if (at.rot != null) { walk.rot = at.rot; walk.yaw = at.rot; }
        walk.dog.x = walk.x + 0.8; walk.dog.z = walk.z - 0.6;
      }
    },
    /* Monte dans un véhicule en libre-service (0 : camping-car, 1 : berline,
       2 : scooter), ou en descend (`false`). `at` : placement direct. */
    drive(index, at) {
      if (index === false) { exitVehicle(); return; }
      const rv = rentals[index];
      if (!rv || !lot) return;
      setWalk(true);
      if (walk.drive) exitVehicle();
      if (at) { if (at.x != null) rv.x = at.x; if (at.z != null) rv.z = at.z; if (at.rot != null) rv.rot = at.rot; }
      enterVehicle(rv);
    },
    /* Ouvre l'atelier de tuning sur un véhicule (index du libre-service), avec un
       réglage éventuel : utile aux démonstrations et aux tests. */
    tune(index, patch) {
      const rv = rentals[index];
      if (!rv || !lot) return;
      setWalk(true);
      if (patch) { garage[rv.def.model] = cleanTune(Object.assign({}, garage[rv.def.model], patch), rv.def.model, rv.def.color); retune(rv); }
      openTuning(rv);
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
        walk: {
          on: walk.on, x: Math.round(walk.x * 100) / 100, y: Math.round(walk.y * 100) / 100, z: Math.round(walk.z * 100) / 100,
          near: walk.near ? walk.near.label : null, panel: walk.panel,
          drive: walk.drive ? walk.drive.def.name : null, speed: walk.drive ? Math.round(walk.drive.v * 10) / 10 : 0,
          ground: lot ? Math.round(groundAt(walk.x, walk.z) * 100) / 100 : 0,
          says: walk.say > 0 && lot ? lot.playerTag.name.textContent : null,
          toast: walk.toast > 0 ? toastBox.textContent : null,
        },
        look: Object.assign({}, look),
        tuning: walk.tuning ? walk.tuning.def.model : null,
        ad: walk.ad ? { shot: walk.ad.i, text: cineSub.textContent } : null,
        garage: JSON.parse(JSON.stringify(garage)),
        podium: lot ? { x: Math.round(lot.city.podium.x * 10) / 10, z: Math.round(lot.city.podium.z * 10) / 10 } : null,
        carnet: Array.from(carnet),
        wins: Array.from(progress.wins),
        quests: Object.assign({}, progress.quests),
        bag: Object.assign({}, progress.bag),
        farm: lot ? { x: Math.round(lot.farm.x * 10) / 10, z: Math.round(lot.farm.z * 10) / 10, nodes: lot.farm.nodes.map((n) => ({ kind: n.kind, x: Math.round(n.x * 10) / 10, z: Math.round(n.z * 10) / 10, up: n.mesh.visible })) } : null,
        duels: net.duels.map((d) => ({ game: d.game, status: d.status, role: d.role, result: d.result })),
        folk: lot ? lot.quest.folk.map((f) => ({ id: f.id, x: Math.round(f.x * 10) / 10, z: Math.round(f.z * 10) / 10, mark: f.tag.name.textContent })) : [],
        gold: lot ? { x: Math.round(lot.gold.x * 10) / 10, z: Math.round(lot.gold.z * 10) / 10, hidden: lot.gold.mesh.visible, found: progress.gold } : null,
        best: Object.assign({}, progress.best),
        game: Boolean(walk.game),
        ride: walk.ride,
        offer: net.offer ? net.offer.o.rideAction.label : null,
        net: {
          on: Boolean(net.url), you: net.you ? net.you.pseudo : null, online: net.online,
          others: Array.from(net.others.values()).map((o) => ({ pseudo: o.goal.pseudo, x: Math.round(o.cur.x * 10) / 10, z: Math.round(o.cur.z * 10) / 10, drive: o.goal.drive || null })),
        },
        fireworks: lot ? lot.city.fireworks.left : 0,
        city: lot ? { x0: Math.round(lot.city.x0), x1: Math.round(lot.city.x1) } : null,
        agent: { x: Math.round(npc.x * 10) / 10, z: Math.round(npc.z * 10) / 10, moving: Boolean(npc.path), says: npc.say > 0 && lot ? lot.agentTag.name.textContent : null },
      };
    },
    dispose() {
      api.setActive(false);
      if (walk.game) walk.game.stop();
      net.url = null;
      net.others.forEach((o) => { if (o.car) o.car.paintMat.dispose(); });
      window.removeEventListener("keydown", keyDown, true);
      window.removeEventListener("keyup", keyUp, true);
      window.removeEventListener("blur", keyBlur);
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
