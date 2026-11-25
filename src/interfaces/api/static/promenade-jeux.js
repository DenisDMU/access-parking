/* Mini-jeux de la promenade (plan 3D).

   Onze petits jeux en 2D, joués dans un panneau du plan : les stands de la
   fête, la grosse caisse du kiosque, la pompe de la station et les commerces
   du village. Même dessin doux partout : ciels en dégradé, formes rondes. Aucune
   image, aucun son chargé, aucune requête : tout est dessiné sur un canvas.
   Souris, doigt ou clavier (flèches, Espace). Chaque jeu rend un score entier
   entre 0 et `max` ; les mêmes plafonds sont vérifiés côté serveur. */

const W = 360, H = 230;
const BLUE = "#1e66f5", INK = "#22252e", CREAM = "#fdf6e3";
const PADS = ["#04a5e5", "#40a02b", "#df8e1d", "#fe640b"];
const rand = (a, b) => a + Math.random() * (b - a);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

function text(g, str, x, y, size, color, align) {
  g.font = "800 " + size + "px system-ui, sans-serif";
  g.fillStyle = color || INK;
  g.textAlign = align || "center";
  g.fillText(str, x, y);
}
function blob(g, x, y, rx, ry, color) {
  g.fillStyle = color;
  g.beginPath();
  g.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
  g.fill();
}

// Décor doux, façon livre d'images : ciel en dégradé, nuages, ombres portées.
function backdrop(g, top, bottom, t) {
  const sky = g.createLinearGradient(0, 38, 0, H);
  sky.addColorStop(0, top); sky.addColorStop(1, bottom);
  g.fillStyle = sky; g.fillRect(0, 38, W, H - 38);
  if (t == null) return;
  for (let i = 0; i < 3; i++) {
    const x = ((t * (6 + i * 3) + i * 150) % (W + 120)) - 60, y = 58 + i * 16;
    blob(g, x, y, 26, 9, "rgba(255,255,255,.75)"); blob(g, x + 16, y - 6, 16, 9, "rgba(255,255,255,.75)");
  }
}
function soft(g, on) {
  g.shadowColor = on ? "rgba(34,37,46,.28)" : "transparent";
  g.shadowBlur = on ? 8 : 0;
  g.shadowOffsetY = on ? 3 : 0;
}

export const GAMES = {
  /* Pêche aux canards : toucher les canards qui défilent ; le doré vaut 3. */
  canards: {
    title: "Pêche aux canards", max: 60, time: 25,
    help: "Touchez les canards qui passent. Le canard doré vaut 3 points. Clavier : flèches et Espace.",
    create() {
      const ducks = [], hook = { x: W / 2, y: H / 2 };
      let spawn = 0, splash = 0;
      const game = {
        score: 0,
        step(dt, t, keys) {
          spawn -= dt;
          if (spawn <= 0 && ducks.length < 7) {
            const lane = Math.floor(rand(0, 3)), dir = Math.random() < 0.5 ? 1 : -1;
            ducks.push({ x: dir > 0 ? -20 : W + 20, y: 78 + lane * 48, v: dir * rand(55, 120), gold: Math.random() < 0.14, bob: rand(0, 6) });
            spawn = rand(0.35, 0.8);
          }
          for (let i = ducks.length - 1; i >= 0; i--) {
            ducks[i].x += ducks[i].v * dt;
            if (ducks[i].x < -30 || ducks[i].x > W + 30) ducks.splice(i, 1);
          }
          hook.x = clamp(hook.x + ((keys.ArrowRight ? 1 : 0) - (keys.ArrowLeft ? 1 : 0)) * 190 * dt, 10, W - 10);
          hook.y = clamp(hook.y + ((keys.ArrowDown ? 1 : 0) - (keys.ArrowUp ? 1 : 0)) * 190 * dt, 50, H - 20);
          splash = Math.max(0, splash - dt);
        },
        catchAt(x, y) {
          hook.x = x; hook.y = y; splash = 0.25;
          const i = ducks.findIndex((d) => Math.abs(d.x - x) < 21 && Math.abs(d.y - y) < 19);
          if (i < 0) return;
          game.score = Math.min(60, game.score + (ducks[i].gold ? 3 : 1));
          ducks.splice(i, 1);
        },
        down(x, y) { game.catchAt(x, y); },
        move(x, y) { hook.x = x; hook.y = y; },
        key(code, on) { if (on && code === "Space") game.catchAt(hook.x, hook.y); },
        draw(g, t) {
          backdrop(g, "#9be0ff", "#4fb6ea");
          [[46, 200, 0.3], [300, 66, -0.4], [226, 212, 0.8]].forEach((n) => { // nénuphars
            g.save(); g.translate(n[0], n[1]); g.rotate(n[2]);
            blob(g, 0, 0, 20, 10, "#5fbf62"); blob(g, 5, -2, 5, 3, "#ffb7d5");
            g.restore();
          });
          g.strokeStyle = "rgba(255,255,255,.55)"; g.lineWidth = 2;
          for (let l = 0; l < 3; l++) {
            g.beginPath();
            for (let x = 0; x <= W; x += 12) g.lineTo(x, 96 + l * 48 + Math.sin(x / 22 + t * 2 + l) * 3);
            g.stroke();
          }
          ducks.forEach((d) => {
            const y = d.y + Math.sin(t * 5 + d.bob) * 2, s = d.v > 0 ? 1 : -1, c = d.gold ? "#f2b01e" : "#ffd60a";
            blob(g, d.x, y + 9, 15, 3.5, "rgba(20,70,110,.25)"); // reflet dans l'eau
            soft(g, true); blob(g, d.x, y, 15, 10, c); blob(g, d.x + s * 11, y - 10, 8.5, 8.5, c); soft(g, false);
            blob(g, d.x - s * 3, y + 1, 8, 5, d.gold ? "#d9980f" : "#f2c200"); // l'aile
            blob(g, d.x + s * 20, y - 9, 5.5, 3, "#fe640b");
            blob(g, d.x + s * 13, y - 12, 2.1, 2.1, INK); blob(g, d.x + s * 13.6, y - 12.7, 0.8, 0.8, "#fff");
            blob(g, d.x + s * 9, y - 7, 2.4, 1.6, "rgba(255,120,140,.7)"); // la joue
            if (d.gold) text(g, "★", d.x, y + 4, 11, "#fff");
          });
          g.strokeStyle = INK; g.lineWidth = 2;
          g.beginPath(); g.moveTo(hook.x, 0); g.lineTo(hook.x, hook.y - 8); g.stroke();
          g.beginPath(); g.arc(hook.x, hook.y, 8 + splash * 30, 0, Math.PI * 2); g.stroke();
        },
      };
      return game;
    },
  },

  /* Crêpes : cinq crêpes à retourner ; on appuie quand le curseur est au centre. */
  crepes: {
    title: "Stand de crêpes", max: 100,
    help: "Cinq crêpes à faire sauter : touchez (ou Espace) quand le curseur passe au centre de la zone verte.",
    create() {
      let pos = 0, dir = 1, round = 0, flip = 0, last = "";
      const game = {
        score: 0, done: false,
        step(dt) {
          flip = Math.max(0, flip - dt);
          if (flip > 0 || game.done) return;
          pos += dir * dt * (0.9 + round * 0.28);
          if (pos > 1) { pos = 1; dir = -1; } else if (pos < 0) { pos = 0; dir = 1; }
        },
        hit() {
          if (flip > 0 || game.done) return;
          const off = Math.abs(pos - 0.5), pts = off < 0.04 ? 20 : off < 0.1 ? 14 : off < 0.18 ? 7 : 0;
          last = pts === 20 ? "Parfaite !" : pts >= 14 ? "Bien dorée" : pts ? "Un peu froissée" : "Tombée à côté…";
          game.score += pts; round++; flip = 0.8;
          if (round >= 5) game.done = true;
        },
        down() { game.hit(); },
        key(code, on) { if (on && code === "Space") game.hit(); },
        draw(g) {
          const lift = Math.sin((1 - flip / 0.8) * Math.PI) * (flip > 0 ? 62 : 0);
          backdrop(g, "#fff1d6", "#ffd9a8");
          g.fillStyle = "#e9b98a"; g.fillRect(0, 168, W, H - 168); // le plan de travail
          for (let i = 0; i < 3; i++) blob(g, 150 + i * 22, 118 - ((pos * 40 + i * 13) % 40), 4, 7, "rgba(255,255,255,.55)"); // vapeur
          soft(g, true);
          g.fillStyle = INK; g.beginPath(); g.roundRect(94, 148, 154, 13, 6); g.fill(); // la poêle
          g.beginPath(); g.roundRect(244, 151, 84, 7, 3.5); g.fill();
          soft(g, false);
          g.save(); g.translate(170, 146 - lift); g.scale(1, Math.cos((flip / 0.8) * Math.PI * 2) * 0.72 + 0.28);
          blob(g, 0, 0, 58, 13, "#e9b96e"); blob(g, -12, -2, 9, 3, "#c98f3f"); blob(g, 20, 3, 7, 2.5, "#c98f3f");
          g.restore();
          g.fillStyle = "#fff"; g.beginPath(); g.roundRect(40, 196, 280, 14, 7); g.fill();
          g.fillStyle = "#7ed07f"; g.beginPath(); g.roundRect(40 + 280 * 0.32, 196, 280 * 0.36, 14, 7); g.fill();
          g.fillStyle = "#2f9e44"; g.beginPath(); g.roundRect(40 + 280 * 0.46, 196, 280 * 0.08, 14, 4); g.fill();
          soft(g, true); blob(g, 40 + 280 * pos, 203, 8, 12, BLUE); soft(g, false);
          text(g, "Crêpe " + Math.min(5, round + 1) + "/5", W / 2, 62, 13, INK);
          if (last) text(g, last, W / 2, 84, 15, BLUE);
        },
      };
      return game;
    },
  },

  /* Frites : rattraper les frites dans le cornet, éviter les cornichons. */
  frites: {
    title: "Cornet de frites", max: 80, time: 25,
    help: "Déplacez le cornet (doigt, souris ou flèches) pour rattraper les frites. Les cornichons font perdre 2 points.",
    create() {
      const items = [];
      let x = W / 2, spawn = 0;
      const game = {
        score: 0,
        step(dt, t, keys) {
          x = clamp(x + ((keys.ArrowRight ? 1 : 0) - (keys.ArrowLeft ? 1 : 0)) * 260 * dt, 24, W - 24);
          spawn -= dt;
          if (spawn <= 0) { items.push({ x: rand(16, W - 16), y: 34, v: rand(90, 170), bad: Math.random() < 0.18, r: rand(-0.5, 0.5) }); spawn = rand(0.22, 0.5); }
          for (let i = items.length - 1; i >= 0; i--) {
            const it = items[i];
            it.y += it.v * dt;
            if (it.y > H - 46 && it.y < H - 22 && Math.abs(it.x - x) < 24) {
              game.score = clamp(game.score + (it.bad ? -2 : 1), 0, 80);
              items.splice(i, 1);
            } else if (it.y > H + 10) items.splice(i, 1);
          }
        },
        move(mx) { x = clamp(mx, 24, W - 24); },
        down(mx) { x = clamp(mx, 24, W - 24); },
        draw(g) {
          backdrop(g, "#bfe9ff", "#fff3cf", performance.now() / 1000);
          for (let i = 0; i < 10; i++) { g.fillStyle = i % 2 ? "#fdf6e3" : "#d92b3a"; g.fillRect(i * 36, 38, 36, 12); blob(g, i * 36 + 18, 50, 18, 6, i % 2 ? "#fdf6e3" : "#d92b3a"); }
          soft(g, true);
          items.forEach((it) => {
            g.save(); g.translate(it.x, it.y); g.rotate(it.r);
            g.fillStyle = it.bad ? "#40a02b" : "#f2c14e";
            if (it.bad) blob(g, 0, 0, 5, 11, "#40a02b"); else g.fillRect(-3, -11, 6, 22);
            g.restore();
          });
          g.fillStyle = "#d92b3a"; g.beginPath();
          g.moveTo(x - 24, H - 44); g.lineTo(x + 24, H - 44); g.lineTo(x + 12, H - 6); g.lineTo(x - 12, H - 6); g.closePath(); g.fill();
          g.fillStyle = CREAM; g.fillRect(x - 18, H - 36, 36, 6);
          soft(g, false);
          blob(g, x, H - 2, 22, 3, "rgba(34,37,46,.2)");
        },
      };
      return game;
    },
  },

  /* Barbe à papa : tourner autour du centre pour enrouler le sucre. */
  barbe: {
    title: "Barbe à papa", max: 100, time: 12,
    help: "Tournez autour de la machine (doigt ou souris) pour enrouler le sucre. Clavier : alternez ← et →.",
    create() {
      let turns = 0, prev = null, lastKey = "", spin = 0;
      const game = {
        score: 0,
        add(a) { turns += a; spin += a; game.score = Math.min(100, Math.round(turns * 7)); },
        step() {},
        move(x, y) {
          const a = Math.atan2(y - 128, x - W / 2);
          if (prev != null) {
            let d = a - prev;
            if (d > Math.PI) d -= Math.PI * 2; else if (d < -Math.PI) d += Math.PI * 2;
            if (Math.abs(d) < 1.2) game.add(Math.abs(d) / (Math.PI * 2));
          }
          prev = a;
        },
        down(x, y) { prev = Math.atan2(y - 128, x - W / 2); },
        up() { prev = null; },
        key(code, on) {
          if (!on || (code !== "ArrowLeft" && code !== "ArrowRight") || code === lastKey) return;
          lastKey = code; game.add(0.25);
        },
        draw(g, t) {
          backdrop(g, "#ffe3f1", "#d8ecff");
          for (let i = 0; i < 8; i++) blob(g, 30 + i * 44, 52 + (i % 2) * 8, 7, 9, ["#1e66f5", "#ffd60a", "#d92b3a", "#40a02b"][i % 4]); // guirlande
          soft(g, true); blob(g, W / 2, 176, 78, 20, "#b9bec9"); soft(g, false); blob(g, W / 2, 170, 66, 15, "#e9edf5");
          for (let i = 0; i < 6; i++) { const a = spin * 9 + i; blob(g, W / 2 + Math.cos(a) * (20 + game.score * 0.55), 112 + Math.sin(a) * (16 + game.score * 0.4), 2, 2, "#fff"); }
          const r = 12 + game.score * 0.5;
          for (let i = 0; i < 9; i++) {
            const a = spin * 6.28 + i * 0.7;
            blob(g, W / 2 + Math.cos(a) * r * 0.25, 112 + Math.sin(a) * r * 0.18, r * 0.72, r * 0.6, i % 2 ? "#ff9fc6" : "#ffc2dc");
          }
          g.fillStyle = "#e8cf8a"; g.fillRect(W / 2 - 3, 112, 6, 84);
          text(g, game.score >= 100 ? "Énorme !" : Math.round(turns * 10) / 10 + " tours", W / 2, 62, 13, INK);
          void t;
        },
      };
      return game;
    },
  },

  /* Grosse caisse : refaire le rythme, qui s'allonge à chaque tour. */
  tambour: {
    title: "La grosse caisse", max: 40,
    help: "Écoutez et regardez le rythme, puis refaites-le. Il s'allonge à chaque tour. Clavier : touches fléchées.",
    create(api) {
      const seq = [], KEYS = ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"];
      let show = 0, timer = 0.8, input = 0, lit = -1, litFor = 0, phase = "show";
      const pad = (i) => ({ x: 48 + i * 76, y: 96, w: 60, h: 96 });
      const beat = (i) => { lit = i; litFor = 0.28; api.sound([[92 + i * 26, 0.26, 0]], 0.28, "triangle"); };
      const next = () => { seq.push(Math.floor(rand(0, 4))); show = 0; timer = 0.7; phase = "show"; };
      next();
      const game = {
        score: 0, done: false,
        step(dt) {
          litFor -= dt;
          if (litFor <= 0) lit = -1;
          if (phase !== "show" || game.done) return;
          timer -= dt;
          if (timer > 0) return;
          if (show < seq.length) { beat(seq[show++]); timer = Math.max(0.3, 0.6 - seq.length * 0.02); }
          else { phase = "play"; input = 0; }
        },
        press(i) {
          if (phase !== "play" || game.done) return;
          beat(i);
          if (seq[input] !== i) { game.done = true; phase = "over"; return; }
          if (++input < seq.length) return;
          game.score = seq.length;
          if (game.score >= 40) { game.done = true; return; }
          next();
        },
        down(x, y) { for (let i = 0; i < 4; i++) { const p = pad(i); if (x > p.x && x < p.x + p.w && y > p.y && y < p.y + p.h) game.press(i); } },
        key(code, on) { if (on && KEYS.includes(code)) game.press(KEYS.indexOf(code)); },
        draw(g) {
          for (let i = 0; i < 4; i++) {
            const p = pad(i);
            const cx = p.x + p.w / 2, cy = p.y + p.h / 2, r = lit === i ? 33 : 29;
            g.globalAlpha = lit === i ? 1 : 0.5;
            soft(g, true); blob(g, cx, cy, r, r, PADS[i]); soft(g, false);
            blob(g, cx, cy, r - 7, r - 7, "#fdf6e3"); // la peau du tambour
            g.globalAlpha = 1;
            text(g, "←↑→↓"[i], cx, cy + 8, 22, PADS[i]);
          }
          g.globalCompositeOperation = "destination-over"; backdrop(g, "#e6f0ff", "#fff3cf"); g.globalCompositeOperation = "source-over";
          text(g, phase === "show" ? "Écoutez…" : phase === "play" ? "À vous !" : "Raté !", W / 2, 70, 15, phase === "play" ? BLUE : INK);
        },
      };
      return game;
    },
  },

  /* Le plein pile : maintenir pour remplir, relâcher pile sur la cible. */
  plein: {
    title: "Le plein pile", max: 100,
    help: "Maintenez appuyé (doigt, souris ou Espace) pour remplir, et relâchez pile sur la quantité demandée.",
    create() {
      const target = Math.round(rand(18, 34));
      let liters = 0, held = false;
      const game = {
        score: 0, done: false,
        step(dt) { if (held && !game.done) liters += dt * (5 + liters * 0.55); if (liters > target + 12) game.stop(); },
        stop() {
          if (game.done || liters <= 0) return;
          held = false; game.done = true;
          game.score = Math.max(0, Math.round(100 - Math.abs(liters - target) * 45));
        },
        down() { held = true; },
        up() { if (held) game.stop(); },
        key(code, on) { if (code !== "Space") return; if (on) held = true; else if (held) game.stop(); },
        draw(g) {
          backdrop(g, "#cfeaff", "#eef7ff", performance.now() / 1000);
          g.fillStyle = "#8d93a1"; g.fillRect(0, 206, W, H - 206); // le sol de la station
          soft(g, true);
          g.fillStyle = "#f4f5f7"; g.beginPath(); g.roundRect(60, 56, 110, 160, 10); g.fill();
          soft(g, false);
          g.strokeStyle = INK; g.lineWidth = 5; g.beginPath(); g.moveTo(170, 150); g.quadraticCurveTo(204, 214, 196, 128); g.stroke(); // le tuyau
          g.fillStyle = BLUE; g.fillRect(60, 56, 110, 26);
          g.fillStyle = INK; g.fillRect(74, 94, 82, 40);
          text(g, liters.toFixed(2) + " L", 115, 121, 17, "#7CFC8A");
          text(g, "Objectif : " + target + ",00 L", 262, 96, 14, INK);
          g.fillStyle = "#fff"; g.beginPath(); g.roundRect(212, 112, 100, 14, 7); g.fill();
          g.fillStyle = "#40a02b"; g.beginPath(); g.roundRect(212, 112, Math.max(8, 100 * clamp(liters / target, 0, 1)), 14, 7); g.fill();
          if (game.done) text(g, game.score >= 95 ? "Pile !" : game.score >= 60 ? "Presque" : "À côté…", 262, 160, 18, BLUE);
          else text(g, held ? "Ça coule…" : "Maintenez appuyé", 262, 160, 13, INK);
        },
      };
      return game;
    },
  },

  /* Jeu des paires : douze cartes, six paires ; moins on se trompe, mieux c'est. */
  paires: {
    title: "Jeu des paires", max: 100, time: 60,
    help: "Retournez deux cartes identiques. Moins vous vous trompez, plus le score est haut. Clavier : flèches et Espace.",
    create() {
      const ICONS = ["P", "★", "♥", "●", "▲", "◆"], COLORS = [BLUE, "#f2b01e", "#ff5d8f", "#40a02b", "#fe640b", "#8839ef"];
      const cards = ICONS.concat(ICONS).map((icon, i) => ({ k: i % 6, up: false, found: false, r: Math.random() })).sort((a, b) => a.r - b.r);
      let open = [], wait = 0, miss = 0, cur = 0;
      const at = (i) => ({ x: 28 + (i % 4) * 78, y: 52 + Math.floor(i / 4) * 58 });
      const game = {
        score: 0, done: false,
        step(dt) {
          if (wait <= 0) return;
          wait -= dt;
          if (wait > 0) return;
          open.forEach((c) => { c.up = false; });
          open = [];
        },
        flip(i) {
          const c = cards[i];
          if (!c || c.up || c.found || wait > 0 || game.done) return;
          c.up = true; open.push(c);
          if (open.length < 2) return;
          if (open[0].k === open[1].k) { open.forEach((o) => { o.found = true; }); open = []; } else { miss++; wait = 0.7; }
          const found = cards.filter((o) => o.found).length / 2;
          game.score = Math.max(found * 6, found === 6 ? Math.max(40, 100 - miss * 6) : 0);
          if (found === 6) game.done = true;
        },
        down(x, y) { for (let i = 0; i < 12; i++) { const p = at(i); if (x > p.x && x < p.x + 70 && y > p.y && y < p.y + 50) { cur = i; game.flip(i); } } },
        key(code, on) {
          if (!on) return;
          if (code === "ArrowRight") cur = (cur + 1) % 12; else if (code === "ArrowLeft") cur = (cur + 11) % 12;
          else if (code === "ArrowDown") cur = (cur + 4) % 12; else if (code === "ArrowUp") cur = (cur + 8) % 12;
          else if (code === "Space") game.flip(cur);
        },
        draw(g) {
          backdrop(g, "#fff1d6", "#ffe0b8");
          cards.forEach((c, i) => {
            const p = at(i), show = c.up || c.found;
            soft(g, true);
            g.fillStyle = show ? "#fff" : BLUE; g.globalAlpha = c.found ? 0.55 : 1;
            g.beginPath(); g.roundRect(p.x, p.y, 70, 50, 12); g.fill();
            soft(g, false);
            if (show) text(g, ICONS[c.k], p.x + 35, p.y + 36, 30, COLORS[c.k]);
            else { g.strokeStyle = "rgba(255,255,255,.5)"; g.lineWidth = 2; g.beginPath(); g.roundRect(p.x + 6, p.y + 6, 58, 38, 8); g.stroke(); }
            g.globalAlpha = 1;
            if (i === cur) { g.strokeStyle = "#ffd60a"; g.lineWidth = 3; g.beginPath(); g.roundRect(p.x - 2, p.y - 2, 74, 54, 13); g.stroke(); }
          });
        },
      };
      return game;
    },
  },

  /* Éclate-ballons : toucher les ballons qui montent ; le doré vaut 3, le nuage gris en retire 2. */
  ballons: {
    title: "Éclate-ballons", max: 60, time: 25,
    help: "Éclatez les ballons qui s'envolent. Le doré vaut 3 points, le nuage gris en retire 2. Clavier : flèches et Espace.",
    create() {
      const items = [], pops = [], aim = { x: W / 2, y: H / 2 }, COLORS = [BLUE, "#ff5d8f", "#40a02b", "#8839ef", "#fe640b"];
      let spawn = 0;
      const game = {
        score: 0,
        step(dt, t, keys) {
          spawn -= dt;
          if (spawn <= 0) {
            const roll = Math.random();
            items.push({ x: rand(24, W - 24), y: H + 24, v: rand(60, 120), sway: rand(0, 6), kind: roll < 0.12 ? "gold" : roll < 0.28 ? "bad" : "ok", color: COLORS[Math.floor(rand(0, 5))] });
            spawn = rand(0.25, 0.55);
          }
          for (let i = items.length - 1; i >= 0; i--) { items[i].y -= items[i].v * dt; items[i].x += Math.sin(t * 2 + items[i].sway) * 22 * dt; if (items[i].y < 20) items.splice(i, 1); }
          for (let i = pops.length - 1; i >= 0; i--) { pops[i].t -= dt; if (pops[i].t <= 0) pops.splice(i, 1); }
          aim.x = clamp(aim.x + ((keys.ArrowRight ? 1 : 0) - (keys.ArrowLeft ? 1 : 0)) * 220 * dt, 10, W - 10);
          aim.y = clamp(aim.y + ((keys.ArrowDown ? 1 : 0) - (keys.ArrowUp ? 1 : 0)) * 220 * dt, 48, H - 10);
        },
        pop(x, y) {
          aim.x = x; aim.y = y;
          const i = items.findIndex((b) => Math.hypot(b.x - x, b.y - y) < 22);
          if (i < 0) return;
          const b = items[i];
          game.score = clamp(game.score + (b.kind === "gold" ? 3 : b.kind === "bad" ? -2 : 1), 0, 60);
          pops.push({ x: b.x, y: b.y, t: 0.25, color: b.kind === "bad" ? "#8d93a1" : b.kind === "gold" ? "#ffd60a" : b.color });
          items.splice(i, 1);
        },
        down(x, y) { game.pop(x, y); },
        move(x, y) { aim.x = x; aim.y = y; },
        key(code, on) { if (on && code === "Space") game.pop(aim.x, aim.y); },
        draw(g, t) {
          backdrop(g, "#8fd3ff", "#e9f7ff", t);
          items.forEach((b) => {
            if (b.kind === "bad") { blob(g, b.x, b.y, 22, 13, "#8d93a1"); blob(g, b.x - 12, b.y - 7, 12, 10, "#8d93a1"); blob(g, b.x + 10, b.y - 8, 13, 11, "#8d93a1"); return; }
            const c = b.kind === "gold" ? "#ffd60a" : b.color;
            g.strokeStyle = "rgba(34,37,46,.45)"; g.lineWidth = 1.2; g.beginPath(); g.moveTo(b.x, b.y + 20); g.quadraticCurveTo(b.x + 5, b.y + 32, b.x, b.y + 44); g.stroke();
            soft(g, true); blob(g, b.x, b.y, 17, 21, c); soft(g, false);
            blob(g, b.x - 6, b.y - 8, 4, 6, "rgba(255,255,255,.6)");
            if (b.kind === "gold") text(g, "★", b.x, b.y + 6, 15, "#fff");
          });
          pops.forEach((p) => { g.strokeStyle = p.color; g.lineWidth = 3; g.beginPath(); g.arc(p.x, p.y, 26 - p.t * 60, 0, Math.PI * 2); g.stroke(); });
          g.strokeStyle = INK; g.lineWidth = 2; g.beginPath(); g.arc(aim.x, aim.y, 9, 0, Math.PI * 2); g.moveTo(aim.x - 14, aim.y); g.lineTo(aim.x + 14, aim.y); g.moveTo(aim.x, aim.y - 14); g.lineTo(aim.x, aim.y + 14); g.stroke();
        },
      };
      return game;
    },
  },

  /* Le passage piéton : traverser la rue entre les voitures, autant de fois que possible. */
  passage: {
    title: "Le passage piéton", max: 30, time: 30,
    help: "Traversez la rue sans vous faire toucher : touchez l'écran, Espace ou ↑ pour avancer, ↓ pour reculer.",
    create() {
      const LANES = [84, 116, 148, 180], cars = [];
      let row = 4, hop = 0, hit = 0; // 4 : trottoir du bas, 0 à 3 : voies, -1 : arrivé en haut
      LANES.forEach((y, i) => { for (let k = 0; k < 2; k++) cars.push({ y, x: rand(0, W), v: (i % 2 ? -1 : 1) * rand(60, 110), w: rand(34, 52), color: [BLUE, "#d92b3a", "#f2b01e", "#40a02b", "#8839ef"][Math.floor(rand(0, 5))] }); });
      const yOf = (r) => (r === 4 ? 210 : r < 0 ? 54 : LANES[3 - r] + 0);
      const game = {
        score: 0,
        step(dt) {
          hop = Math.max(0, hop - dt); hit = Math.max(0, hit - dt);
          cars.forEach((c) => { c.x += c.v * dt; if (c.x > W + 60) c.x = -60; else if (c.x < -60) c.x = W + 60; });
          if (row < 4 && row >= 0 && cars.some((c) => c.y === yOf(row) && Math.abs(c.x - W / 2) < c.w / 2 + 9)) { row = 4; hit = 0.6; }
        },
        go(d) {
          if (hop > 0) return;
          row = clamp(row - d, -1, 4); hop = 0.12;
          if (row === -1) { game.score = Math.min(30, game.score + 1); row = 4; }
        },
        down() { game.go(1); },
        key(code, on) { if (!on) return; if (code === "Space" || code === "ArrowUp") game.go(1); else if (code === "ArrowDown") game.go(-1); },
        draw(g) {
          backdrop(g, "#bfe9ff", "#d9f3c4");
          g.fillStyle = "#d9d2c0"; g.fillRect(0, 196, W, 34); g.fillRect(0, 40, W, 28); // trottoirs
          g.fillStyle = "#5a5f6b"; g.fillRect(0, 68, W, 128);
          g.fillStyle = "#fff"; for (let i = 0; i < 6; i++) g.fillRect(W / 2 - 34 + i * 12, 68, 7, 128); // le passage
          cars.forEach((c) => {
            soft(g, true); g.fillStyle = c.color; g.beginPath(); g.roundRect(c.x - c.w / 2, c.y - 10, c.w, 20, 8); g.fill(); soft(g, false);
            g.fillStyle = "#cfe9ff"; g.beginPath(); g.roundRect(c.x - c.w / 4, c.y - 7, c.w / 2, 14, 4); g.fill();
            blob(g, c.x + (c.v > 0 ? 1 : -1) * (c.w / 2 - 3), c.y - 5, 2, 2.5, "#ffd60a"); blob(g, c.x + (c.v > 0 ? 1 : -1) * (c.w / 2 - 3), c.y + 5, 2, 2.5, "#ffd60a");
          });
          const y = yOf(row);
          blob(g, W / 2, y + 12, 9, 3, "rgba(34,37,46,.25)");
          soft(g, true); blob(g, W / 2, y + 2, 8, 9, hit > 0 ? "#d92b3a" : BLUE); blob(g, W / 2, y - 11, 10, 10, "#f0c9a4"); soft(g, false);
          blob(g, W / 2 - 4, y - 12, 1.6, 2.4, INK); blob(g, W / 2 + 4, y - 12, 1.6, 2.4, INK);
          if (hit > 0) text(g, "Aïe ! On recommence.", W / 2, 60, 13, "#d92b3a");
        },
      };
      return game;
    },
  },

  /* Chasse aux olives : toucher les olives qui sortent de la pizza, pas les piments. */
  olives: {
    title: "Chasse aux olives", max: 60, time: 25,
    help: "Touchez les olives qui pointent sur la pizza. Le piment rouge retire 2 points. Clavier : flèches et Espace.",
    create() {
      const holes = [];
      for (let i = 0; i < 9; i++) holes.push({ x: 110 + (i % 3) * 70, y: 84 + Math.floor(i / 3) * 52, kind: null, t: 0 });
      let spawn = 0, cur = 4;
      const game = {
        score: 0,
        step(dt) {
          spawn -= dt;
          holes.forEach((hl) => { if (hl.kind) { hl.t -= dt; if (hl.t <= 0) hl.kind = null; } });
          if (spawn > 0) return;
          const free = holes.filter((hl) => !hl.kind);
          if (free.length) { const hl = free[Math.floor(rand(0, free.length))]; hl.kind = Math.random() < 0.2 ? "bad" : "ok"; hl.t = rand(0.65, 1.1); }
          spawn = rand(0.28, 0.6);
        },
        hit(i) {
          const hl = holes[i];
          if (!hl || !hl.kind) return;
          game.score = clamp(game.score + (hl.kind === "ok" ? 1 : -2), 0, 60);
          hl.kind = null;
        },
        down(x, y) { holes.forEach((hl, i) => { if (Math.hypot(hl.x - x, hl.y - y) < 26) { cur = i; game.hit(i); } }); },
        key(code, on) {
          if (!on) return;
          if (code === "ArrowRight") cur = Math.floor(cur / 3) * 3 + ((cur % 3) + 1) % 3; else if (code === "ArrowLeft") cur = Math.floor(cur / 3) * 3 + ((cur % 3) + 2) % 3;
          else if (code === "ArrowDown") cur = (cur + 3) % 9; else if (code === "ArrowUp") cur = (cur + 6) % 9;
          else if (code === "Space") game.hit(cur);
        },
        draw(g) {
          backdrop(g, "#ffe9d6", "#ffd0a8");
          soft(g, true); blob(g, 180, 136, 128, 88, "#e2a45a"); soft(g, false);
          blob(g, 180, 136, 114, 76, "#e85d4a"); blob(g, 180, 136, 106, 69, "#ffd98a");
          holes.forEach((hl, i) => {
            blob(g, hl.x, hl.y, 20, 13, "rgba(190,120,50,.35)");
            if (hl.kind === "ok") { soft(g, true); blob(g, hl.x, hl.y - 6, 15, 15, "#3d3d2e"); soft(g, false); blob(g, hl.x, hl.y - 6, 6, 6, "#e85d4a"); blob(g, hl.x - 5, hl.y - 12, 3, 4, "rgba(255,255,255,.5)"); }
            if (hl.kind === "bad") { soft(g, true); blob(g, hl.x, hl.y - 6, 9, 17, "#d92b3a"); soft(g, false); blob(g, hl.x, hl.y - 23, 4, 5, "#40a02b"); }
            if (i === cur) { g.strokeStyle = BLUE; g.lineWidth = 2.5; g.beginPath(); g.ellipse(hl.x, hl.y - 2, 26, 22, 0, 0, Math.PI * 2); g.stroke(); }
          });
        },
      };
      return game;
    },
  },

  /* Feu vert ! : cinq départs ; on touche dès que le feu passe au vert, pas avant. */
  feu: {
    title: "Feu vert !", max: 100,
    help: "Attendez le feu vert, puis touchez (ou Espace) le plus vite possible. Cinq départs. Partir au rouge ne rapporte rien.",
    create() {
      let round = 0, state = "red", timer = rand(1.2, 3), since = 0, last = "";
      const game = {
        score: 0, done: false,
        step(dt) {
          if (game.done) return;
          if (state === "red") { timer -= dt; if (timer <= 0) { state = "green"; since = 0; } }
          else if (state === "green") { since += dt; if (since > 1.5) game.tap(); }
          else { timer -= dt; if (timer <= 0) { if (round >= 5) game.done = true; else { state = "red"; timer = rand(1.2, 3); } } }
        },
        tap() {
          if (state === "wait" || game.done) return;
          const pts = state === "red" ? 0 : Math.round(clamp(20 - (since * 1000 - 220) / 22, 0, 20));
          last = state === "red" ? "Trop tôt !" : Math.round(since * 1000) + " ms : " + (pts >= 18 ? "éclair !" : pts >= 10 ? "bien parti" : "un peu endormi");
          game.score += pts; round++; state = "wait"; timer = 1;
        },
        down() { game.tap(); },
        key(code, on) { if (on && code === "Space") game.tap(); },
        draw(g, t) {
          backdrop(g, "#cfeaff", "#eef7ff", t);
          g.fillStyle = "#8d93a1"; g.fillRect(0, 196, W, H - 196);
          soft(g, true); g.fillStyle = INK; g.beginPath(); g.roundRect(150, 58, 60, 132, 16); g.fill(); soft(g, false);
          g.fillStyle = INK; g.fillRect(176, 190, 8, 20);
          const lit = state === "green" || (state === "wait" && !last.startsWith("Trop"));
          blob(g, 180, 92, 20, 20, lit ? "#4a2a2a" : "#ff4d4d"); blob(g, 180, 156, 20, 20, lit ? "#4dff7a" : "#1f4a2c");
          if (!lit) blob(g, 173, 85, 5, 6, "rgba(255,255,255,.45)"); else blob(g, 173, 149, 5, 6, "rgba(255,255,255,.55)");
          text(g, "Départ " + Math.min(5, round + (state === "wait" ? 0 : 1)) + "/5", 76, 110, 13, INK);
          if (last) text(g, last, 278, 110, 12, BLUE);
          text(g, state === "red" ? "Attendez…" : state === "green" ? "GO !" : "", 180, 224, 15, state === "green" ? "#2f9e44" : INK);
        },
      };
      return game;
    },
  },
};

/* Lance un jeu dans `mount`. `opts.onEnd(score)` à la fin ; `opts.sound` joue
   une note (fournie par le plan). Rend { key(code, on), stop() }. */
export function startGame(id, mount, opts) {
  const def = GAMES[id];
  const canvas = document.createElement("canvas");
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = W * ratio; canvas.height = H * ratio;
  canvas.style.cssText = "display:block;width:100%;border-radius:12px;background:#fdf6e3;touch-action:none;cursor:pointer";
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", def.title);
  mount.appendChild(canvas);
  const g = canvas.getContext("2d");
  if (!g.roundRect) g.roundRect = (x, y, w, h) => g.rect(x, y, w, h); // navigateurs anciens
  const game = def.create({ sound: opts.sound || (() => {}) });
  const keys = {};
  let left = def.time || 0, last = performance.now(), raf = 0, over = false, t = 0;
  const at = (e) => {
    const r = canvas.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H];
  };
  const on = (type, fn) => canvas.addEventListener(type, (e) => { e.preventDefault(); if (!over) fn(e); });
  on("pointerdown", (e) => { const p = at(e); if (game.down) game.down(p[0], p[1]); });
  on("pointermove", (e) => { const p = at(e); if (game.move && (e.pointerType !== "touch" || e.buttons)) game.move(p[0], p[1]); });
  on("pointerup", () => { if (game.up) game.up(); });
  on("pointerleave", () => { if (game.up) game.up(); });
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now; t += dt;
    game.step(dt, t, keys);
    if (def.time) { left -= dt; if (left <= 0) game.done = true; }
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    g.clearRect(0, 0, W, H);
    game.draw(g, t);
    g.fillStyle = BLUE; g.fillRect(0, 0, W, 38);
    g.fillStyle = "#ffd60a"; g.beginPath(); g.roundRect(8, 7, 96, 24, 12); g.fill();
    text(g, "★ " + game.score, 56, 24, 15, INK);
    if (def.time) {
      g.fillStyle = "rgba(255,255,255,.25)"; g.fillRect(W - 132, 15, 120, 8);
      g.fillStyle = "#ffd60a"; g.fillRect(W - 132, 15, 120 * clamp(left / def.time, 0, 1), 8);
    }
    if (game.done) {
      over = true;
      g.fillStyle = "rgba(253,246,227,.82)"; g.fillRect(0, 38, W, H - 38);
      soft(g, true); g.fillStyle = "#fff"; g.beginPath(); g.roundRect(W / 2 - 120, H / 2 - 22, 240, 60, 18); g.fill(); soft(g, false);
      text(g, "Terminé : " + game.score + " / " + def.max, W / 2, H / 2 + 16, 22, BLUE);
      opts.onEnd(clamp(Math.round(game.score), 0, def.max));
      return;
    }
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);
  return {
    key(code, down) { keys[code] = down; if (!over && game.key) game.key(code, down); },
    stop() { over = true; cancelAnimationFrame(raf); },
  };
}
