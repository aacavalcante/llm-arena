// Arena em canvas 640x360 (pixels lógicos): fundo, barras de HP, cronômetro,
// lutadores, números de dano, tremor de tela e faixas de texto (ROUND/FIGHT/KO...).
// O servidor é a autoridade: aqui só animamos o que chega via state.fx e state.match.

import { createFighter, attackFor, impactDelay } from "./sprites.js";
import { remainingMs, fighterName } from "./state.js";

export const W = 640;
export const H = 360;
const FLOOR_Y = 300;
const LEFT_X = 160;
const RIGHT_X = 480;
const LAG_DELAY = 300; // ms que a barra amarela espera antes de seguir a vermelha
const FONT = '"Courier New", "Lucida Console", monospace';

const STATUS_TO_ANIM = {
  idle: "idle",
  writing: "writing",
  testing: "testing",
  stunned: "stunned",
  exhausted: "exhausted",
  ko: "ko",
};

// Gerador pseudoaleatório determinístico para o cenário (estrelas, plateia).
function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export function createArena(canvas, state) {
  const ctx = canvas.getContext("2d");
  canvas.width = W;
  canvas.height = H;
  ctx.imageSmoothingEnabled = false;

  const fighters = {
    left: createFighter("left", { reach: RIGHT_X - LEFT_X - 40 }),
    right: createFighter("right", { reach: RIGHT_X - LEFT_X - 40 }),
  };
  const lag = { left: { hp: 100, holdUntil: 0 }, right: { hp: 100, holdUntil: 0 } };
  let floaters = []; // {text, x, y, color, born, life, size}
  let banners = []; // fila: {text, sub, color, dur, start}
  let persistent = null; // faixa fixa (VENCEDOR / ABORTADA)
  let shakeUntil = 0;
  let pending = []; // ações agendadas: {at, fn}
  let last = performance.now();
  let raf = 0;
  let running = false;

  // Cenário fixo
  const rnd = seeded(20261027);
  const stars = Array.from({ length: 60 }, () => ({ x: Math.floor(rnd() * W), y: Math.floor(rnd() * 90), b: rnd() }));
  const skyline = [];
  for (let x = 0; x < W; ) {
    const w = 12 + Math.floor(rnd() * 30);
    const h = 20 + Math.floor(rnd() * 50);
    skyline.push({ x, w, h, lit: rnd() > 0.5 });
    x += w + Math.floor(rnd() * 6);
  }
  const crowd = [];
  for (let row = 0; row < 6; row++) {
    for (let x = 0; x < W; x += 8) {
      crowd.push({ x: x + (row % 2) * 4, y: 150 + row * 13, c: Math.floor(rnd() * 5), t: Math.floor(rnd() * 97) });
    }
  }
  const CROWD_COLORS = ["#3a2a55", "#4b2f6b", "#2c3a66", "#553a3a", "#3c4d4a"];

  // ---------------------------------------------------------------- helpers
  function maxHp() {
    return state.match?.rules?.hp || 100;
  }

  function fighterX(side) {
    return side === "left" ? LEFT_X : RIGHT_X;
  }

  function schedule(delay, fn) {
    pending.push({ at: performance.now() + delay, fn });
  }

  function float(text, side, color, opts = {}) {
    floaters.push({
      text,
      x: fighterX(side) + (opts.dx || 0),
      y: FLOOR_Y - 110 + (opts.dy || 0),
      color,
      born: performance.now(),
      life: opts.life || 1300,
      size: opts.size || 22,
    });
  }

  function banner(text, dur, color = "#ffd23f", sub = "") {
    banners.push({ text, sub, color, dur, start: 0 });
  }

  function syncLag(instant) {
    const m = state.match;
    for (const side of ["left", "right"]) {
      const hp = m ? m.hp[side] ?? maxHp() : maxHp();
      if (instant) lag[side] = { hp, holdUntil: 0 };
    }
  }

  function applyBaseStates() {
    const m = state.match;
    for (const side of ["left", "right"]) {
      const f = fighters[side];
      f.glow = !!state.counterReady[side];
      if (!f.isBase()) continue;
      const status = m ? m.fighter_status[side] : "idle";
      let anim = STATUS_TO_ANIM[status] || "idle";
      if (anim === "idle" && f.glow) anim = "counter_ready";
      f.setState(anim);
    }
  }

  // ------------------------------------------------------------ efeitos fx
  function consumeFx() {
    const m = state.match;
    while (state.fx.length) {
      const fx = state.fx.shift();
      switch (fx.kind) {
        case "snapshot":
          pending = [];
          banners = [];
          floaters = [];
          persistent = null;
          for (const side of ["left", "right"]) {
            const f = fighters[side];
            const status = m ? m.fighter_status[side] : "idle";
            f.setState(STATUS_TO_ANIM[status] || "idle", { force: true });
          }
          syncLag(true);
          if (m && m.status === "finished") showWinner(m.winner);
          if (m && m.status === "aborted") persistent = { text: "LUTA ABORTADA", color: "#ff6b6b" };
          break;

        case "match_start":
          pending = [];
          banners = [];
          floaters = [];
          persistent = null;
          fighters.left.setState("idle", { force: true });
          fighters.right.setState("idle", { force: true });
          syncLag(true);
          break;

        case "round_start":
          pending = [];
          banners = []; // descarta faixas antigas ainda na fila
          persistent = null;
          fighters.left.setState("idle", { force: true });
          fighters.right.setState("idle", { force: true });
          syncLag(true);
          banner(`ROUND ${fx.round_no}`, 1000);
          banner("FIGHT!", 700, "#ff5a5a");
          break;

        case "hit": {
          const atk = fighters[fx.attacker];
          const def = fighters[fx.defender];
          const anim = attackFor(fx.difficulty);
          atk.setState(anim);
          const delay = impactDelay(anim);
          schedule(delay, () => {
            def.setState("hit");
            shakeUntil = performance.now() + 150;
            lag[fx.defender].holdUntil = performance.now() + LAG_DELAY;
            const color = fx.counter ? "#ffd23f" : fx.difficulty === "hard" ? "#ff7a3a" : "#ffffff";
            float(`-${fx.damage}`, fx.defender, color, { size: fx.difficulty === "hard" ? 30 : 24 });
            if (fx.counter) float("COUNTER!", fx.attacker, "#ffd23f", { dy: -20, life: 1600, size: 20 });
          });
          break;
        }

        case "miss":
          fighters[fx.side].setState("stumble");
          float("ERROU", fx.side, "#9aa4b5", { size: 18 });
          if (fx.opens_counter) {
            const foe = fx.side === "left" ? "right" : "left";
            schedule(250, () => float("COUNTER ABERTO", foe, "#ffd23f", { dy: -20, size: 16, life: 1600 }));
          }
          break;

        case "late":
          float("ATRASADO", fx.side, "#9aa4b5", { size: 18 });
          break;

        case "round_end": {
          banners = [];
          banner(fx.reason === "ko" ? "K.O." : "TEMPO", 1200, fx.reason === "ko" ? "#ff5a5a" : "#ffd23f");
          const winner = fx.winner;
          schedule(300, () => {
            if (winner === "draw") return;
            const loser = winner === "left" ? "right" : "left";
            fighters[winner].setState("win", { force: true });
            fighters[loser].setState(fx.reason === "ko" ? "ko" : "idle", { force: true });
          });
          break;
        }

        case "match_end":
          schedule(1500, () => showWinner(fx.winner));
          break;

        case "error":
          if (fx.fatal) {
            persistent = { text: "LUTA ABORTADA", color: "#ff6b6b", sub: fx.message };
          }
          break;

        default:
          break;
      }
    }
  }

  function showWinner(winner) {
    banners = [];
    if (winner === "draw" || !winner) {
      persistent = { text: "EMPATE", color: "#ffd23f" };
      return;
    }
    const loser = winner === "left" ? "right" : "left";
    fighters[winner].setState("win", { force: true });
    fighters[loser].setState("ko", { force: true });
    persistent = { text: `VENCEDOR: ${fighterName(state, winner).toUpperCase()}`, color: "#ffd23f" };
  }

  // ---------------------------------------------------------------- update
  function update(dt, now) {
    // ações agendadas
    if (pending.length) {
      const due = pending.filter((p) => p.at <= now);
      pending = pending.filter((p) => p.at > now);
      for (const p of due) p.fn();
    }
    applyBaseStates();
    fighters.left.update(dt);
    fighters.right.update(dt);

    // barra "lag": espera LAG_DELAY e depois desce rápido até o HP real
    const m = state.match;
    for (const side of ["left", "right"]) {
      const target = m ? m.hp[side] ?? maxHp() : maxHp();
      const l = lag[side];
      if (target >= l.hp) {
        l.hp = target;
      } else if (now >= l.holdUntil) {
        l.hp = Math.max(target, l.hp - dt * 0.05);
      }
    }

    floaters = floaters.filter((f) => now - f.born < f.life);
    if (banners.length && banners[0].start === 0) banners[0].start = now;
    if (banners.length && now - banners[0].start > banners[0].dur) {
      banners.shift();
      if (banners.length) banners[0].start = now;
    }
  }

  // ---------------------------------------------------------------- render
  function text(str, x, y, size, color, align = "center", weight = "bold") {
    ctx.font = `${weight} ${size}px ${FONT}`;
    ctx.textAlign = align;
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#000";
    const o = Math.max(1, Math.round(size / 10));
    for (const [dx, dy] of [[o, 0], [-o, 0], [0, o], [0, -o], [o, o]]) ctx.fillText(str, x + dx, y + dy);
    ctx.fillStyle = color;
    ctx.fillText(str, x, y);
  }

  function drawBackground(now) {
    // céu em faixas
    const bands = ["#070716", "#0b0b24", "#10103a", "#171548", "#1f1a58", "#2a1f66", "#352572"];
    for (let i = 0; i < bands.length; i++) {
      ctx.fillStyle = bands[i];
      ctx.fillRect(0, i * 22, W, 22);
    }
    // estrelas
    for (const s of stars) {
      const tw = (Math.sin(now / 400 + s.b * 20) + 1) / 2;
      ctx.fillStyle = tw > 0.6 ? "#ffffff" : "#8f8fc8";
      ctx.fillRect(s.x, s.y, 2, 2);
    }
    // lua
    ctx.fillStyle = "#f4e7b0";
    ctx.fillRect(540, 30, 28, 28);
    ctx.fillStyle = "#352572";
    ctx.fillRect(552, 24, 24, 26);
    // skyline
    for (const b of skyline) {
      ctx.fillStyle = "#0a0a1c";
      ctx.fillRect(b.x, 150 - b.h, b.w, b.h);
      if (b.lit) {
        ctx.fillStyle = "#e4c35a";
        for (let y = 150 - b.h + 4; y < 146; y += 8) {
          for (let x = b.x + 3; x < b.x + b.w - 3; x += 7) ctx.fillRect(x, y, 2, 3);
        }
      }
    }
    // plateia
    ctx.fillStyle = "#1a1230";
    ctx.fillRect(0, 150, W, 90);
    const tick = Math.floor(now / 200);
    for (const c of crowd) {
      const bob = (tick + c.t) % 7 === 0 ? -1 : 0;
      ctx.fillStyle = CROWD_COLORS[c.c];
      ctx.fillRect(c.x, c.y + bob, 6, 10);
      ctx.fillStyle = "#6c5a8a";
      ctx.fillRect(c.x + 1, c.y + bob, 4, 4);
      if ((tick + c.t) % 53 === 0) {
        ctx.fillStyle = "#ffffff"; // flash de câmera
        ctx.fillRect(c.x + 1, c.y + bob - 2, 3, 3);
      }
    }
    // borda do ringue (cordas)
    ctx.fillStyle = "#c8c8d8";
    ctx.fillRect(0, 238, W, 2);
    ctx.fillStyle = "#e23b3b";
    ctx.fillRect(0, 246, W, 2);
    ctx.fillStyle = "#2e6ee6";
    ctx.fillRect(0, 254, W, 2);
    // piso
    ctx.fillStyle = "#2a2a3c";
    ctx.fillRect(0, 258, W, FLOOR_Y - 258);
    ctx.fillStyle = "#3b3b52";
    for (let x = 0; x < W; x += 32) ctx.fillRect(x + ((x / 32) % 2) * 16, 258, 16, 42);
    ctx.fillStyle = "#8f8fb0";
    ctx.fillRect(0, FLOOR_Y, W, 3);
    ctx.fillStyle = "#1c1c2a";
    ctx.fillRect(0, FLOOR_Y + 3, W, H - FLOOR_Y - 3);
    ctx.fillStyle = "#26263a";
    for (let x = 0; x < W; x += 40) ctx.fillRect(x, FLOOR_Y + 3, 20, H);
  }

  function drawHpBar(side, now) {
    const m = state.match;
    const max = maxHp();
    const hp = m ? m.hp[side] ?? max : max;
    const barW = 256;
    const x0 = side === "left" ? 24 : W - 24 - barW;
    const y0 = 18;
    const h = 16;
    // moldura
    ctx.fillStyle = "#000";
    ctx.fillRect(x0 - 3, y0 - 3, barW + 6, h + 6);
    ctx.fillStyle = "#f0f0f0";
    ctx.fillRect(x0 - 2, y0 - 2, barW + 4, h + 4);
    ctx.fillStyle = "#1a1a1a";
    ctx.fillRect(x0, y0, barW, h);
    // amarela (lag) e vermelha (HP real); esquerda drena para a esquerda, direita para a direita
    const fillW = (v) => Math.round((barW * Math.max(0, Math.min(max, v))) / max);
    const lagW = fillW(lag[side].hp);
    const hpW = fillW(hp);
    const xl = side === "left" ? x0 : x0 + barW - lagW;
    const xh = side === "left" ? x0 : x0 + barW - hpW;
    ctx.fillStyle = "#f5d547";
    ctx.fillRect(xl, y0, lagW, h);
    const low = hp / max < 0.25 && Math.floor(now / 300) % 2 === 0;
    ctx.fillStyle = low ? "#ff8080" : "#e8333a";
    ctx.fillRect(xh, y0, hpW, h);
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.fillRect(xh, y0, hpW, 3);
    // marcas a cada 10%
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    for (let i = 1; i < 10; i++) ctx.fillRect(x0 + Math.round((barW * i) / 10), y0, 1, h);
    // nome
    const name = fighterName(state, side);
    text(name.length > 22 ? name.slice(0, 21) + "…" : name, side === "left" ? x0 : x0 + barW, y0 + h + 14, 13, "#ffffff", side === "left" ? "left" : "right");
    // HP numérico
    text(`${hp}`, side === "left" ? x0 + barW : x0, y0 + h + 14, 12, "#f5d547", side === "left" ? "right" : "left");
  }

  function drawHud(now) {
    drawHpBar("left", now);
    drawHpBar("right", now);
    // cronômetro central
    const ms = remainingMs(state, Date.now());
    const total = Math.ceil(ms / 1000);
    const mm = Math.floor(total / 60);
    const ss = total % 60;
    const tstr = `${mm}:${ss.toString().padStart(2, "0")}`;
    const urgent = state.timer.active && ms < 10000;
    ctx.fillStyle = "#000";
    ctx.fillRect(W / 2 - 38, 8, 76, 34);
    ctx.fillStyle = urgent && Math.floor(now / 250) % 2 === 0 ? "#5a1010" : "#15152a";
    ctx.fillRect(W / 2 - 36, 10, 72, 30);
    text(tstr, W / 2, 26, 24, urgent ? "#ff5a5a" : "#ffffff");
    // pontos de round (bolinhas preenchidas)
    const score = state.match ? state.match.score : { left: 0, right: 0 };
    const rounds = state.match?.rules?.rounds || 3;
    const need = Math.ceil(rounds / 2);
    for (const side of ["left", "right"]) {
      for (let i = 0; i < need; i++) {
        const x = side === "left" ? W / 2 - 14 - i * 12 : W / 2 + 14 + i * 12;
        ctx.fillStyle = "#000";
        ctx.fillRect(x - 5, 46, 10, 10);
        ctx.fillStyle = i < (score[side] || 0) ? "#ffd23f" : "#3a3a55";
        ctx.fillRect(x - 4, 47, 8, 8);
      }
    }
    // round atual
    if (state.match && state.match.round_no > 0) {
      text(`R${state.match.round_no}`, W / 2, 62, 10, "#9aa4b5");
    }
  }

  function drawFighters(now) {
    for (const side of ["left", "right"]) {
      const x = fighterX(side);
      ctx.fillStyle = "rgba(0,0,0,0.45)";
      ctx.fillRect(x - 28, FLOOR_Y - 2, 56, 5); // sombra
      fighters[side].draw(ctx, x, FLOOR_Y);
      if (fighters[side].glow) {
        const pulse = 0.6 + 0.4 * Math.sin(now / 150);
        ctx.globalAlpha = pulse;
        text("COUNTER", x, FLOOR_Y - 112, 14, "#ffd23f");
        ctx.globalAlpha = 1;
      }
    }
  }

  function drawFloaters(now) {
    for (const f of floaters) {
      const p = (now - f.born) / f.life;
      ctx.globalAlpha = p < 0.7 ? 1 : 1 - (p - 0.7) / 0.3;
      text(f.text, f.x, f.y - p * 40, f.size, f.color);
    }
    ctx.globalAlpha = 1;
  }

  function drawBanners(now) {
    if (banners.length) {
      const b = banners[0];
      const p = (now - b.start) / b.dur;
      const scale = p < 0.15 ? 0.6 + (p / 0.15) * 0.4 : 1;
      ctx.save();
      ctx.translate(W / 2, 150);
      ctx.scale(scale, scale);
      text(b.text, 0, 0, 48, b.color);
      ctx.restore();
    }
    if (persistent) {
      const pulse = 0.8 + 0.2 * Math.sin(now / 200);
      ctx.globalAlpha = pulse;
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      ctx.fillRect(40, 118, W - 80, persistent.sub ? 70 : 50);
      text(persistent.text, W / 2, 143, persistent.text.length > 24 ? 20 : 28, persistent.color);
      if (persistent.sub) text(persistent.sub.slice(0, 60), W / 2, 172, 11, "#dddddd");
      ctx.globalAlpha = 1;
    }
    if (!state.match) {
      text("AGUARDANDO LUTA", W / 2, 150, 22, "#9aa4b5");
    }
  }

  function render(now) {
    ctx.save();
    if (now < shakeUntil) {
      ctx.translate(Math.round((Math.random() - 0.5) * 8), Math.round((Math.random() - 0.5) * 8));
    }
    drawBackground(now);
    drawFighters(now);
    drawHud(now);
    drawFloaters(now);
    drawBanners(now);
    ctx.restore();
  }

  function loop(now) {
    if (!running) return;
    const dt = Math.min(50, now - last);
    last = now;
    try {
      consumeFx();
      update(dt, now);
      render(now);
    } catch (e) {
      console.error("arena: erro no frame", e);
    }
    raf = requestAnimationFrame(loop);
  }

  function start() {
    if (running) return;
    running = true;
    last = performance.now();
    raf = requestAnimationFrame(loop);
  }

  function stop() {
    running = false;
    cancelAnimationFrame(raf);
  }

  /** Avança um frame manualmente (útil para testes). */
  function step(ms = 16) {
    const now = last + ms;
    const dt = now - last;
    last = now;
    consumeFx();
    update(dt, now);
    render(now);
  }

  return { start, stop, step, fighters };
}
