// Estado do cliente: espelha protocol.apply_event (servidor é a autoridade; aqui só refletimos)
// e enfileira efeitos transitórios em state.fx para a arena animar.

export function createState() {
  return {
    match: null, // MatchView (ou null quando não há luta)
    fx: [], // fila de efeitos: {kind:'hit'|'miss'|'late'|'round_start'|'round_end'|'match_end'|'snapshot'|...}
    timer: { remaining_ms: 0, at: 0, active: false }, // base para interpolar o cronômetro localmente
    counterReady: { left: false, right: false }, // quem está com "COUNTER" aberto
    error: null, // última mensagem de erro do servidor
  };
}

export function opponentOf(side) {
  return side === "left" ? "right" : "left";
}

function emptyMatch(ev) {
  return {
    match_id: ev.match_id,
    status: "running",
    left: ev.left,
    right: ev.right,
    rules: ev.rules,
    round_no: 0,
    score: { left: 0, right: 0 },
    hp: { left: ev.rules.hp, right: ev.rules.hp },
    remaining_ms: Math.round(ev.rules.round_seconds * 1000),
    challenge: null,
    fighter_status: { left: "idle", right: "idle" },
    code: { left: "", right: "" },
    last_result: { left: null, right: null },
    winner: null,
  };
}

// Normaliza um MatchView vindo do servidor (snapshot/REST), preenchendo defaults.
export function normalizeMatch(m) {
  if (!m) return null;
  return {
    match_id: m.match_id,
    status: m.status || "running",
    left: m.left,
    right: m.right,
    rules: m.rules,
    round_no: m.round_no || 0,
    score: { left: 0, right: 0, ...(m.score || {}) },
    hp: { left: m.rules?.hp ?? 100, right: m.rules?.hp ?? 100, ...(m.hp || {}) },
    remaining_ms: m.remaining_ms || 0,
    challenge: m.challenge || null,
    fighter_status: { left: "idle", right: "idle", ...(m.fighter_status || {}) },
    code: { left: "", right: "", ...(m.code || {}) },
    last_result: { left: null, right: null, ...(m.last_result || {}) },
    winner: m.winner ?? null,
  };
}

/** Reducer puro: aplica o evento no estado e devolve o próprio estado. */
export function applyEvent(state, ev, now = Date.now()) {
  if (!ev || typeof ev.type !== "string") return state;

  if (ev.type === "state_snapshot") {
    state.match = normalizeMatch(ev.match);
    state.counterReady = { left: false, right: false };
    state.timer = {
      remaining_ms: state.match ? state.match.remaining_ms : 0,
      at: now,
      active: !!state.match && state.match.status === "running" && state.match.round_no > 0,
    };
    state.fx.push({ kind: "snapshot" });
    return state;
  }

  if (ev.type === "match_start") {
    state.match = emptyMatch(ev);
    state.counterReady = { left: false, right: false };
    state.timer = { remaining_ms: state.match.remaining_ms, at: now, active: false };
    state.error = null;
    state.fx.push({ kind: "match_start" });
    return state;
  }

  if (ev.type === "error") {
    state.error = ev.message;
    if (ev.fatal && state.match) {
      state.match.status = "aborted";
      state.timer.active = false;
    }
    state.fx.push({ kind: "error", message: ev.message, fatal: !!ev.fatal });
    return state;
  }

  const m = state.match;
  if (!m) return state; // eventos de luta sem luta conhecida: ignorar (snapshot virá)

  switch (ev.type) {
    case "round_start":
      m.round_no = ev.round_no;
      m.hp = { ...ev.hp };
      m.score = { ...ev.score };
      m.remaining_ms = ev.remaining_ms;
      m.challenge = null;
      m.code = { left: "", right: "" };
      m.last_result = { left: null, right: null };
      m.fighter_status = { left: "idle", right: "idle" };
      state.counterReady = { left: false, right: false };
      state.timer = { remaining_ms: ev.remaining_ms, at: now, active: true };
      state.fx.push({ kind: "round_start", round_no: ev.round_no });
      break;

    case "challenge":
      m.challenge = ev.challenge;
      m.code = { left: "", right: "" };
      state.counterReady = { left: false, right: false };
      state.fx.push({ kind: "challenge", seq: ev.challenge.seq });
      break;

    case "token":
      // Ignora tokens de um desafio antigo (seq diferente do desafio atual).
      if (m.challenge && ev.seq !== m.challenge.seq) break;
      m.code[ev.side] = ((m.code[ev.side] || "") + ev.text).slice(-20000);
      break;

    case "fighter_status":
      m.fighter_status[ev.side] = ev.status;
      if (ev.status === "writing") m.code[ev.side] = "";
      break;

    case "golpe_result": {
      m.last_result[ev.side] = ev;
      const foe = opponentOf(ev.side);
      if (ev.passed && ev.damage > 0) {
        // Golpe acertou: desafio resolvido, qualquer COUNTER aberto se encerra.
        state.counterReady = { left: false, right: false };
        state.fx.push({
          kind: "hit",
          attacker: ev.side,
          defender: foe,
          damage: ev.damage,
          difficulty: ev.difficulty,
          counter: !!ev.counter,
          ms: ev.ms,
        });
      } else if (ev.passed && ev.late) {
        state.fx.push({ kind: "late", side: ev.side });
      } else if (ev.passed) {
        state.fx.push({ kind: "late", side: ev.side }); // válido sem dano: trata como atrasado
      } else {
        if (ev.opens_counter) state.counterReady[foe] = true;
        state.fx.push({ kind: "miss", side: ev.side, opens_counter: !!ev.opens_counter, category: ev.category });
      }
      break;
    }

    case "hp_update":
      m.hp = { left: ev.left, right: ev.right };
      break;

    case "round_end":
      m.score = { ...ev.score };
      m.hp = { ...ev.hp };
      state.counterReady = { left: false, right: false };
      state.timer.active = false;
      state.fx.push({ kind: "round_end", round_no: ev.round_no, reason: ev.reason, winner: ev.winner });
      break;

    case "match_end":
      m.status = "finished";
      m.winner = ev.winner;
      m.score = { ...ev.score };
      state.timer.active = false;
      state.fx.push({ kind: "match_end", winner: ev.winner, stats: ev.stats });
      break;

    case "timer":
      m.remaining_ms = ev.remaining_ms;
      state.timer = { remaining_ms: ev.remaining_ms, at: now, active: m.status === "running" };
      break;

    default:
      break; // tipo desconhecido: ignora
  }
  return state;
}

/** Tempo restante interpolado localmente entre ticks do servidor. */
export function remainingMs(state, now = Date.now()) {
  const t = state.timer;
  if (!t.active) return Math.max(0, t.remaining_ms);
  return Math.max(0, t.remaining_ms - (now - t.at));
}

/** Nome exibível de um lado. */
export function fighterName(state, side) {
  const f = state.match && state.match[side];
  if (!f) return side === "left" ? "Lutador 1" : "Lutador 2";
  return f.display_name || f.model || side;
}
