// Lutadores em pixel art procedural. Grade de 16x24 células, escala x4 (64x96 px).
// Tudo é desenhado com fillRect por célula; o lutador da direita é espelhado.

export const CELL = 4; // px por célula
export const GRID_W = 16;
export const GRID_H = 24;

const PALETTES = {
  left: {
    gi: "#2e6ee6", gi2: "#1b48a6", band: "#e23b3b", skin: "#f2c08a", hair: "#3a2213",
    belt: "#1a1a1a", eye: "#111111", foot: "#2a2a2a", key: "#6c6c80", white: "#ffffff",
    energy: "#4fc3ff", energy2: "#dff6ff", star: "#ffd23f",
  },
  right: {
    gi: "#e03e3e", gi2: "#9a2323", band: "#2e6ee6", skin: "#c98a5a", hair: "#161616",
    belt: "#f3f3f3", eye: "#111111", foot: "#2a2a2a", key: "#6c6c80", white: "#ffffff",
    energy: "#ff8c3a", energy2: "#fff0c8", star: "#ffd23f",
  },
};

// Tabela de animações: frames, duração por frame (ms) e próximo estado.
// loop=true repete; next=null e loop=false segura no último frame (terminal).
const ANIMS = {
  idle: { frames: 2, dur: [420, 420], loop: true },
  writing: { frames: 2, dur: [260, 260], loop: true },
  testing: { frames: 2, dur: [360, 360], loop: true },
  stunned: { frames: 2, dur: [220, 220], loop: true },
  exhausted: { frames: 2, dur: [520, 520], loop: true },
  counter_ready: { frames: 2, dur: [420, 420], loop: true },
  attack_light: { frames: 3, dur: [90, 180, 110], loop: false, next: "idle" },
  attack_medium: { frames: 3, dur: [120, 220, 140], loop: false, next: "idle" },
  attack_special: { frames: 3, dur: [180, 620, 160], loop: false, next: "idle" },
  hit: { frames: 3, dur: [70, 180, 130], loop: false, next: "idle" },
  stumble: { frames: 3, dur: [160, 320, 160], loop: false, next: "idle" },
  ko: { frames: 2, dur: [160, 1e9], loop: false, next: null },
  win: { frames: 2, dur: [380, 380], loop: true, terminal: true },
};

const TERMINAL = new Set(["ko", "win"]);

/** Atraso (ms) entre iniciar o ataque e o impacto no adversário. */
export function impactDelay(attackName) {
  const a = ANIMS[attackName];
  if (!a) return 0;
  if (attackName === "attack_special") return a.dur[0] + a.dur[1] * 0.85;
  return a.dur[0] + a.dur[1] * 0.3;
}

export function attackFor(difficulty) {
  if (difficulty === "hard") return "attack_special";
  if (difficulty === "medium") return "attack_medium";
  return "attack_light";
}

export function createFighter(side, opts = {}) {
  const mirror = side === "right";
  const pal = PALETTES[side] || PALETTES.left;
  const reach = opts.reach ?? 320; // distância (px) até o adversário, para o projétil
  let state = "idle";
  let frame = 0;
  let t = 0; // tempo no frame atual
  let glow = false; // contorno pulsante: false | true (amarelo, COUNTER) | cor CSS (ex.: verde, VANTAGEM)
  let clock = 0; // tempo total (para pulsar o glow)

  function setState(name, { force = false } = {}) {
    if (!ANIMS[name]) return;
    if (!force && TERMINAL.has(state) && state !== name) return; // ko/win travam até round_start
    if (state === name && ANIMS[name].loop) return; // não reinicia loops
    state = name;
    frame = 0;
    t = 0;
  }

  function update(dt) {
    clock += dt;
    t += dt;
    const a = ANIMS[state];
    while (t >= a.dur[frame]) {
      t -= a.dur[frame];
      frame += 1;
      if (frame >= a.frames) {
        if (a.loop) {
          frame = 0;
        } else if (a.next) {
          state = a.next;
          frame = 0;
          t = 0;
          break;
        } else {
          frame = a.frames - 1; // segura no último frame
          break;
        }
      }
    }
  }

  /** Posiciona num frame específico (páginas de desenvolvimento/testes). */
  function setFrame(n) {
    frame = Math.max(0, Math.min(ANIMS[state].frames - 1, n | 0));
    t = 0;
  }

  function isBase() {
    return ANIMS[state].loop && !TERMINAL.has(state);
  }

  // Pintor na grade; `override` força uma cor única (flash branco / contorno).
  function makePainter(ctx, ox, oy, override) {
    return (cx, cy, w, h, key) => {
      const X = mirror ? GRID_W - cx - w : cx;
      ctx.fillStyle = override || pal[key] || key;
      ctx.fillRect(ox + X * CELL, oy + cy * CELL, w * CELL, h * CELL);
    };
  }

  // ---- partes do corpo -------------------------------------------------
  function head(r, x, y, f) {
    r(x - 1, y, 1, 3, "hair"); // nuca
    r(x, y - 1, 6, 2, "hair"); // cabelo
    r(x, y + 1, 6, 5, "skin"); // rosto
    r(x, y + 2, 6, 1, "band"); // faixa
    r(x - 3, y + 2 + (f % 2), 3, 1, "band"); // ponta da faixa esvoaçando
    r(x + 4, y + 3, 1, 1, "eye"); // olho (voltado para o adversário)
  }

  function torso(r, x, y, h) {
    r(x, y, 8, h, "gi");
    r(x, y, 2, h, "gi2"); // sombra nas costas
    r(x + 3, y, 2, 2, "skin"); // gola em V
    r(x, y + h, 8, 1, "belt");
  }

  function legs(r, kind, top) {
    switch (kind) {
      case "wide":
        r(4, top, 3, 6, "gi"); r(4, top, 1, 6, "gi2");
        r(9, top, 3, 6, "gi");
        r(3, 22, 4, 2, "foot"); r(9, 22, 4, 2, "foot");
        break;
      case "crouch":
        r(3, 18, 10, 2, "gi"); r(3, 18, 2, 2, "gi2"); // coxas
        r(2, 20, 3, 2, "gi2"); r(11, 20, 3, 2, "gi"); // canelas
        r(1, 22, 4, 2, "foot"); r(11, 22, 4, 2, "foot");
        break;
      case "kick":
        r(5, top, 3, 6, "gi"); r(5, top, 1, 6, "gi2");
        r(4, 22, 4, 2, "foot");
        r(8, top - 1, 7, 3, "gi"); // perna estendida
        r(15, top - 2, 2, 4, "foot");
        break;
      case "kneel":
        r(4, top + 2, 3, 4, "gi"); r(4, top + 2, 1, 4, "gi2");
        r(8, top, 3, 6, "gi");
        r(3, 22, 4, 2, "foot"); r(8, 22, 4, 2, "foot");
        break;
      default: // stand
        r(5, top, 3, 6, "gi"); r(5, top, 1, 6, "gi2");
        r(8, top, 3, 6, "gi");
        r(4, 22, 4, 2, "foot"); r(8, 22, 4, 2, "foot");
    }
  }

  // Braço de trás (desenhado antes do torso) e da frente (depois).
  function backArm(r, kind, x, y) {
    switch (kind) {
      case "up": r(x - 1, y - 6, 2, 7, "gi2"); r(x - 1, y - 8, 2, 2, "skin"); break;
      case "forward": r(x + 2, y + 2, 4, 2, "gi2"); break;
      case "side": r(x - 3, y, 3, 2, "gi2"); r(x - 5, y, 2, 2, "skin"); break;
      case "down": r(x - 1, y, 2, 6, "gi2"); r(x - 1, y + 6, 2, 2, "skin"); break;
      default: r(x - 1, y, 2, 4, "gi2"); r(x - 1, y + 4, 2, 2, "skin"); // guard
    }
  }

  function frontArm(r, kind, x, y) {
    // x = borda direita do torso, y = ombro
    switch (kind) {
      case "punch": r(x, y, 5, 2, "gi"); r(x + 5, y, 2, 2, "skin"); break;
      case "windup": r(x - 1, y + 1, 2, 3, "gi"); r(x - 1, y + 4, 2, 2, "skin"); break;
      case "up": r(x, y - 6, 2, 7, "gi"); r(x, y - 8, 2, 2, "skin"); break;
      case "forward": r(x, y, 4, 2, "gi"); r(x, y + 2, 4, 2, "gi2"); r(x + 4, y, 2, 4, "skin"); break;
      case "typing": r(x, y + 1, 3, 2, "gi"); r(x + 3, y + 1, 2, 2, "skin"); break;
      case "side": r(x, y, 3, 2, "gi"); r(x + 3, y, 2, 2, "skin"); break;
      case "down": r(x, y, 2, 6, "gi"); r(x, y + 6, 2, 2, "skin"); break;
      case "out": r(x, y - 1, 4, 2, "gi"); r(x + 4, y - 2, 2, 2, "skin"); break;
      default: r(x, y, 3, 2, "gi"); r(x + 2, y - 2, 2, 3, "skin"); // guard: punho na altura do rosto
    }
  }

  // Pose composta: dx/dy deslocam a parte de cima; pernas ficam no chão.
  function body(r, o) {
    const dx = o.dx || 0;
    const dy = o.dy || 0;
    const hx = 5 + dx + (o.headDx || 0);
    const hy = 2 + dy + (o.headDy || 0);
    const tx = 4 + dx;
    const ty = 9 + dy;
    const th = Math.max(3, 6 - dy); // torso encurta ao agachar
    backArm(r, o.back || "guard", tx, ty + 1);
    legs(r, o.legs || "stand", 16);
    torso(r, tx, ty, th);
    r(hx + 2, hy + 6, 2, 1, "skin"); // pescoço
    head(r, hx, hy, o.f || 0);
    frontArm(r, o.front || "guard", tx + 8, ty + 1);
  }

  function lying(r, f) {
    // Nocauteado: deitado de costas, cabeça para trás, pés para o adversário.
    if (f === 0) {
      body(r, { dx: 1, dy: 3, legs: "kneel", front: "down", back: "down" });
      return;
    }
    r(0, 19, 1, 5, "hair");
    r(1, 18, 5, 1, "hair");
    r(1, 19, 5, 5, "skin");
    r(2, 20, 4, 1, "band");
    r(4, 21, 1, 1, "eye");
    r(6, 19, 8, 5, "gi"); r(6, 23, 8, 1, "gi2");
    r(13, 19, 1, 5, "belt");
    r(14, 20, 6, 4, "gi");
    r(20, 19, 2, 5, "foot");
    r(9, 16, 4, 2, "gi"); r(9, 14, 2, 2, "skin"); // braço caído para cima
  }

  function keyboard(r, f) {
    // Teclado flutuante acima da cabeça + faíscas de digitação.
    const yy = -3 - (f % 2);
    r(4, yy, 8, 2, "key");
    for (let i = 0; i < 4; i++) r(5 + i * 2, yy, 1, 1, "white");
    if (f % 2 === 0) { r(3, yy - 1, 1, 1, "white"); r(13, yy, 1, 1, "white"); }
    else { r(12, yy - 2, 1, 1, "white"); r(2, yy + 1, 1, 1, "white"); }
  }

  function stars(r, f) {
    // Estrelinhas girando (atordoado)
    const pos = [[3, -2], [8, -4], [13, -2], [8, 0]];
    for (let i = 0; i < 3; i++) {
      const p = pos[(i + f) % pos.length];
      r(p[0], p[1], 1, 1, "star");
    }
  }

  // ---- frames por estado ------------------------------------------------
  function drawFrame(r, s, f) {
    switch (s) {
      case "idle":
      case "counter_ready":
        body(r, { dy: f, legs: f ? "wide" : "stand", f });
        break;
      case "writing":
        body(r, { dy: f, legs: "stand", front: "typing", back: "forward", f });
        keyboard(r, f);
        break;
      case "testing":
        body(r, { dy: 5, legs: "crouch", front: f ? "typing" : "guard", f });
        break;
      case "stunned":
        body(r, { dx: f ? 1 : -1, dy: 1, headDx: f ? 1 : -1, legs: "wide", front: "side", back: "side", f });
        stars(r, f);
        break;
      case "exhausted":
        body(r, { dx: 1, dy: 2 + f, headDy: 1, legs: "wide", front: "down", back: "down", f });
        break;
      case "attack_light":
        if (f === 0) body(r, { dx: -1, front: "windup", legs: "wide" });
        else if (f === 1) body(r, { dx: 1, front: "punch", back: "guard", legs: "wide" });
        else body(r, { front: "guard", legs: "stand" });
        break;
      case "attack_medium":
        if (f === 0) body(r, { dx: -1, dy: 1, legs: "wide", front: "windup" });
        else if (f === 1) body(r, { dx: -1, legs: "kick", front: "side", back: "side" });
        else body(r, { legs: "wide" });
        break;
      case "attack_special":
        if (f === 0) body(r, { dx: -1, dy: 1, legs: "wide", front: "windup", back: "down" });
        else if (f === 1) body(r, { dx: 1, dy: 1, legs: "wide", front: "forward", back: "forward" });
        else body(r, { legs: "wide", front: "forward", back: "forward" });
        break;
      case "hit":
        if (f === 0) body(r, { dx: -1, headDx: -1, headDy: 0, legs: "wide", front: "side" });
        else if (f === 1) body(r, { dx: -2, dy: 1, headDx: -1, legs: "wide", front: "out", back: "side" });
        else body(r, { dx: -1, legs: "stand" });
        break;
      case "stumble":
        if (f === 0) body(r, { dx: 2, headDx: 1, legs: "wide", front: "out", back: "forward" });
        else if (f === 1) body(r, { dx: 2, dy: 3, headDx: 1, headDy: 1, legs: "kneel", front: "down", back: "forward" });
        else body(r, { dx: 1, legs: "stand" });
        break;
      case "ko":
        lying(r, f);
        break;
      case "win":
        body(r, { dy: f ? 0 : 1, legs: f ? "wide" : "stand", front: "up", back: "up", f });
        break;
      default:
        body(r, { f });
    }
  }

  function drawProjectile(ctx, x, y) {
    if (state !== "attack_special" || frame !== 1) return;
    const a = ANIMS.attack_special;
    const prog = Math.min(1, t / a.dur[1]);
    const dir = mirror ? -1 : 1;
    const px = x + dir * (CELL * 10 + prog * reach);
    const py = y - CELL * 13 + Math.sin(prog * 12) * 2;
    const r = (cx, cy, w, h, col) => {
      ctx.fillStyle = col;
      ctx.fillRect(px + dir * cx * CELL - (dir < 0 ? w * CELL : 0), py + cy * CELL, w * CELL, h * CELL);
    };
    // rastro
    for (let i = 1; i <= 4; i++) {
      ctx.globalAlpha = 0.5 - i * 0.1;
      r(-i * 2 - 2, -1 + (i % 2), 2, 2, pal.energy);
    }
    ctx.globalAlpha = 1;
    // bola de energia (blob 5x5 com núcleo claro)
    r(-1, -2, 3, 1, pal.energy);
    r(-2, -1, 5, 3, pal.energy);
    r(-1, 2, 3, 1, pal.energy);
    r(-1, -1, 2, 2, pal.energy2);
    r(0, 0, 1, 1, pal.white);
  }

  function draw(ctx, x, y) {
    // (x, y) = centro dos pés, no chão
    const ox = Math.round(x - (GRID_W / 2) * CELL);
    const oy = Math.round(y - GRID_H * CELL);
    const a = ANIMS[state];
    const f = Math.min(frame, a.frames - 1);

    if (glow) {
      const pulse = 0.45 + 0.4 * (0.5 + 0.5 * Math.sin(clock / 120));
      ctx.globalAlpha = pulse;
      const glowColor = typeof glow === "string" ? glow : pal.star;
      for (const [gx, gy] of [[-2, 0], [2, 0], [0, -2], [0, 2], [-2, -2], [2, 2], [-2, 2], [2, -2]]) {
        drawFrame(makePainter(ctx, ox + gx, oy + gy, glowColor), state, f);
      }
      ctx.globalAlpha = 1;
    }

    const flash = state === "hit" && f === 0 ? "#ffffff" : null;
    drawFrame(makePainter(ctx, ox, oy, flash), state, f);
    drawProjectile(ctx, x, y);
  }

  return {
    side,
    get state() { return state; },
    get frame() { return frame; },
    get glow() { return glow; },
    set glow(v) { glow = typeof v === "string" && v ? v : !!v; },
    setState,
    setFrame,
    update,
    draw,
    isBase,
  };
}
