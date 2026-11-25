/* Mini-jeux de la promenade (plan 3D).

   Six petits jeux en 2D, joués dans un panneau du plan : les quatre stands de
   la fête, la grosse caisse du kiosque et la pompe de la station. Aucune
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
          g.fillStyle = "#8fd3f4"; g.fillRect(0, 40, W, H - 40);
          g.strokeStyle = "rgba(255,255,255,.55)"; g.lineWidth = 2;
          for (let l = 0; l < 3; l++) {
            g.beginPath();
            for (let x = 0; x <= W; x += 12) g.lineTo(x, 96 + l * 48 + Math.sin(x / 22 + t * 2 + l) * 3);
            g.stroke();
          }
          ducks.forEach((d) => {
            const y = d.y + Math.sin(t * 5 + d.bob) * 2, s = d.v > 0 ? 1 : -1, c = d.gold ? "#f2b01e" : "#ffd60a";
            blob(g, d.x, y, 15, 10, c); blob(g, d.x + s * 11, y - 10, 8, 8, c);
            blob(g, d.x + s * 20, y - 9, 5, 3, "#fe640b"); blob(g, d.x + s * 13, y - 12, 1.6, 1.6, INK);
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
          g.fillStyle = INK; g.fillRect(96, 150, 150, 9); g.fillRect(246, 152, 78, 6); // la poêle
          g.save(); g.translate(170, 146 - lift); g.scale(1, Math.cos((flip / 0.8) * Math.PI * 2) * 0.72 + 0.28);
          blob(g, 0, 0, 58, 13, "#e9b96e"); blob(g, -12, -2, 9, 3, "#c98f3f"); blob(g, 20, 3, 7, 2.5, "#c98f3f");
          g.restore();
          g.fillStyle = "#d5d8de"; g.fillRect(40, 196, 280, 14);
          g.fillStyle = "#40a02b"; g.fillRect(40 + 280 * 0.32, 196, 280 * 0.36, 14);
          g.fillStyle = "#1c7c1c"; g.fillRect(40 + 280 * 0.46, 196, 280 * 0.08, 14);
          g.fillStyle = INK; g.fillRect(38 + 280 * pos, 190, 4, 26);
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
          items.forEach((it) => {
            g.save(); g.translate(it.x, it.y); g.rotate(it.r);
            g.fillStyle = it.bad ? "#40a02b" : "#f2c14e";
            if (it.bad) blob(g, 0, 0, 5, 11, "#40a02b"); else g.fillRect(-3, -11, 6, 22);
            g.restore();
          });
          g.fillStyle = "#d92b3a"; g.beginPath();
          g.moveTo(x - 24, H - 44); g.lineTo(x + 24, H - 44); g.lineTo(x + 12, H - 6); g.lineTo(x - 12, H - 6); g.closePath(); g.fill();
          g.fillStyle = CREAM; g.fillRect(x - 18, H - 36, 36, 6);
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
          blob(g, W / 2, 176, 78, 20, "#b9bec9"); blob(g, W / 2, 170, 66, 15, "#e9edf5");
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
            g.globalAlpha = lit === i ? 1 : 0.42;
            g.fillStyle = PADS[i]; g.beginPath(); g.roundRect(p.x, p.y, p.w, p.h, 12); g.fill();
            g.globalAlpha = 1;
            text(g, "←↑→↓"[i], p.x + p.w / 2, p.y + p.h / 2 + 8, 22, "#fff");
          }
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
          g.fillStyle = "#f4f5f7"; g.beginPath(); g.roundRect(60, 56, 110, 160, 10); g.fill();
          g.fillStyle = BLUE; g.fillRect(60, 56, 110, 26);
          g.fillStyle = INK; g.fillRect(74, 94, 82, 40);
          text(g, liters.toFixed(2) + " L", 115, 121, 17, "#7CFC8A");
          text(g, "Objectif : " + target + ",00 L", 262, 96, 14, INK);
          g.fillStyle = "#d5d8de"; g.fillRect(212, 112, 100, 14);
          g.fillStyle = "#40a02b"; g.fillRect(212, 112, 100 * clamp(liters / target, 0, 1), 14);
          if (game.done) text(g, game.score >= 95 ? "Pile !" : game.score >= 60 ? "Presque" : "À côté…", 262, 160, 18, BLUE);
          else text(g, held ? "Ça coule…" : "Maintenez appuyé", 262, 160, 13, INK);
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
    g.fillStyle = "rgba(34,37,46,.9)"; g.fillRect(0, 0, W, 38);
    text(g, "Score " + game.score, 12, 25, 15, "#fff", "left");
    if (def.time) {
      g.fillStyle = "rgba(255,255,255,.25)"; g.fillRect(W - 132, 15, 120, 8);
      g.fillStyle = "#ffd60a"; g.fillRect(W - 132, 15, 120 * clamp(left / def.time, 0, 1), 8);
    }
    if (game.done) {
      over = true;
      g.fillStyle = "rgba(253,246,227,.82)"; g.fillRect(0, 38, W, H - 38);
      text(g, "Terminé : " + game.score + " / " + def.max, W / 2, H / 2 + 14, 22, BLUE);
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
