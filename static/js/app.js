// Bootstrap: liga WebSocket -> reducer -> painéis + arena, e alterna as telas setup/arena.

import { connect as wsConnect } from "./ws.js";
import { createState, applyEvent } from "./state.js";
import { createArena } from "./arena.js";
import { createPanels } from "./panels.js";
import { createSetup } from "./setup.js";

export async function boot({ connect = wsConnect, fetchImpl = (...a) => fetch(...a) } = {}) {
  const state = createState();
  const $ = (id) => document.getElementById(id);
  const views = { setup: $("setup"), arena: $("arena") };
  const conn = $("conn");
  const abortBtn = $("abort-btn");
  const newBtn = $("new-btn");
  const msg = $("arena-msg");

  const panels = createPanels(document);
  const arena = createArena($("canvas"), state);

  function show(name) {
    for (const [k, el] of Object.entries(views)) el.classList.toggle("hidden", k !== name);
  }

  function refreshButtons() {
    const m = state.match;
    const running = !!m && m.status === "running";
    abortBtn.classList.toggle("hidden", !running);
    newBtn.classList.toggle("hidden", running);
    if (msg) {
      msg.textContent = state.error ? `Erro: ${state.error}` : "";
      msg.classList.toggle("error", !!state.error);
    }
  }

  function handleEvent(ev) {
    applyEvent(state, ev);
    panels.render(state);
    refreshButtons();
    // Luta começou (ou snapshot com luta rodando) enquanto estamos na tela inicial: vai para a arena
    if (ev.type === "match_start" || (ev.type === "state_snapshot" && state.match && state.match.status === "running")) {
      show("arena");
    }
  }

  // Tela inicial
  createSetup({
    onStarted: () => {
      show("arena");
    },
  });

  // Se já há luta rodando, pula direto para a arena
  try {
    const res = await fetchImpl("/api/matches/current");
    if (res.ok) {
      const m = await res.json();
      handleEvent({ type: "state_snapshot", match: m });
    }
  } catch (_) {
    /* servidor fora: a tela inicial mostra o erro de modelos */
  }

  // Botões da arena
  abortBtn.addEventListener("click", async () => {
    abortBtn.disabled = true;
    try {
      const res = await fetchImpl("/api/matches/current", { method: "DELETE" });
      if (res.status === 404 && msg) msg.textContent = "Nenhuma luta em andamento.";
    } catch (e) {
      if (msg) msg.textContent = `Falha ao abortar: ${e.message}`;
    } finally {
      abortBtn.disabled = false;
    }
  });
  newBtn.addEventListener("click", () => {
    state.error = null;
    show("setup");
  });

  // WebSocket
  connect(handleEvent, (status) => {
    if (!conn) return;
    conn.dataset.status = status;
    conn.textContent = status === "open" ? "conectado" : status === "connecting" ? "conectando…" : "reconectando…";
  });

  panels.render(state);
  refreshButtons();
  arena.start();

  return { state, panels, arena, handleEvent, show };
}
