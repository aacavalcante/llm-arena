// Tela inicial: carrega /api/models, preenche os selects, prepara um problema personalizado com o juiz
// (GET /api/judge, POST /api/problems/generate) e cria a luta (POST /api/matches, com problem_id opcional).

const MIN_STATEMENT = 10;
const MAX_STATEMENT = 2000;

/** Renderização compacta de um caso de teste: `f(args, k=v) → expected`. */
export function formatTest(fn, t) {
  const j = (v) => {
    try {
      return JSON.stringify(v);
    } catch (_) {
      return String(v);
    }
  };
  const args = (t.args || []).map(j);
  const kwargs = Object.entries(t.kwargs || {}).map(([k, v]) => `${k}=${j(v)}`);
  return { call: `${fn || "f"}(${[...args, ...kwargs].join(", ")})`, expected: j(t.expected) };
}

export function createSetup({ onStarted, onError, fetchImpl = (...a) => fetch(...a) } = {}) {
  const form = document.getElementById("setup-form");
  const btn = document.getElementById("fight-btn");
  const errEl = document.getElementById("setup-error");
  const sel = {
    left: { provider: document.getElementById("sel-provider-left"), model: document.getElementById("sel-model-left") },
    right: { provider: document.getElementById("sel-provider-right"), model: document.getElementById("sel-model-right") },
  };
  // Problema personalizado
  const cp = {
    details: document.getElementById("custom-problem"),
    unavailable: document.getElementById("judge-unavailable"),
    editor: document.getElementById("custom-editor"),
    text: document.getElementById("problem-text"),
    prepare: document.getElementById("prepare-btn"),
    status: document.getElementById("prepare-status"),
    error: document.getElementById("prepare-error"),
    card: document.getElementById("problem-card"),
    title: document.getElementById("pc-title"),
    diff: document.getElementById("pc-diff"),
    level: document.getElementById("pc-level"),
    signature: document.getElementById("pc-signature"),
    statement: document.getElementById("pc-statement"),
    tests: document.getElementById("pc-tests"),
    change: document.getElementById("change-problem-btn"),
    judge: document.getElementById("pc-judge"),
  };
  const DIFF_LABEL = { easy: "fácil", medium: "médio", hard: "difícil" };
  let providers = [];
  let judge = { available: false, provider: null, model: null };
  let problem = null; // GeneratedProblemView preparado pelo juiz (ou null = modo banco)

  function showError(msg) {
    if (errEl) errEl.textContent = msg || "";
    if (msg && onError) onError(msg);
  }

  function fillModels(side) {
    const p = providers.find((x) => x.name === sel[side].provider.value);
    const ms = sel[side].model;
    ms.innerHTML = "";
    for (const m of p ? p.models : []) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.display_name || m.id;
      ms.appendChild(opt);
    }
  }

  function fillProviders() {
    for (const side of ["left", "right"]) {
      const ps = sel[side].provider;
      ps.innerHTML = "";
      for (const p of providers) {
        const opt = document.createElement("option");
        opt.value = p.name;
        opt.textContent = p.display_name || p.name;
        ps.appendChild(opt);
      }
      // Sugere provedores diferentes para cada lado, quando houver mais de um
      if (side === "right" && providers.length > 1) ps.selectedIndex = 1;
      fillModels(side);
      ps.addEventListener("change", () => fillModels(side));
    }
  }

  async function loadModels() {
    try {
      const res = await fetchImpl("/api/models");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      providers = data.providers || [];
      if (!providers.length) showError("Nenhum modelo disponível. Configure as chaves de API no servidor.");
      fillProviders();
    } catch (e) {
      showError(`Não foi possível carregar os modelos (${e.message}).`);
    }
  }

  // ------------------------------------------------------------ juiz / problema personalizado
  async function loadJudge() {
    if (!cp.details) return;
    try {
      const res = await fetchImpl("/api/judge");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      judge = { available: !!data.available, provider: data.provider || null, model: data.model || null };
    } catch (_) {
      judge = { available: false, provider: null, model: null };
    }
    renderJudgeAvailability();
  }

  function renderJudgeAvailability() {
    const ok = judge.available;
    if (cp.unavailable) cp.unavailable.classList.toggle("hidden", ok);
    if (cp.editor) cp.editor.classList.toggle("hidden", !ok);
    if (!ok) {
      problem = null;
      if (cp.card) cp.card.classList.add("hidden");
    }
    renderFightButton();
  }

  function setPrepareBusy(busy, label = "") {
    if (cp.prepare) cp.prepare.disabled = busy;
    if (cp.text) cp.text.disabled = busy;
    if (cp.status) {
      cp.status.textContent = label;
      cp.status.classList.toggle("busy", busy);
    }
  }

  function showPrepareError(msg) {
    if (cp.error) cp.error.textContent = msg || "";
  }

  function renderProblemCard() {
    if (!cp.card) return;
    const p = problem;
    cp.card.classList.toggle("hidden", !p);
    if (cp.editor) cp.editor.classList.toggle("hidden", !!p || !judge.available);
    if (!p) return;
    cp.title.textContent = p.title || "Problema personalizado";
    cp.diff.textContent = DIFF_LABEL[p.difficulty] || p.difficulty || "";
    cp.diff.dataset.diff = p.difficulty || "";
    cp.level.textContent = `nível ${p.level ?? 1}`;
    cp.level.dataset.level = String(p.level ?? 1);
    cp.signature.textContent = p.signature || "";
    cp.statement.textContent = p.statement || "";
    cp.tests.innerHTML = "";
    for (const t of p.tests || []) {
      const { call, expected } = formatTest(p.function, t);
      const li = document.createElement("li");
      const c = document.createElement("span");
      c.textContent = call;
      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.textContent = " → ";
      const e = document.createElement("span");
      e.className = "expected";
      e.textContent = expected;
      li.append(c, arrow, e);
      cp.tests.appendChild(li);
    }
    if (cp.judge) cp.judge.textContent = p.judge_model ? `preparado por ${p.judge_model}` : "";
  }

  function renderFightButton() {
    if (!btn) return;
    btn.textContent = problem ? "Lutar com o problema personalizado" : "Lutar";
    btn.classList.toggle("btn-custom", !!problem);
  }

  async function prepare() {
    showPrepareError("");
    const statement = (cp.text ? cp.text.value : "").trim();
    if (statement.length < MIN_STATEMENT) {
      showPrepareError(`Descreva o problema com pelo menos ${MIN_STATEMENT} caracteres.`);
      return;
    }
    if (statement.length > MAX_STATEMENT) {
      showPrepareError(`O problema deve ter no máximo ${MAX_STATEMENT} caracteres.`);
      return;
    }
    setPrepareBusy(true, "O juiz está preparando o desafio (pode levar até 40 s)…");
    if (btn) btn.disabled = true;
    try {
      const res = await fetchImpl("/api/problems/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ statement }),
      });
      if (res.ok) {
        problem = await res.json();
        renderProblemCard();
        renderFightButton();
        setPrepareBusy(false, "");
      } else if (res.status === 503) {
        setPrepareBusy(false, "");
        judge = { ...judge, available: false };
        renderJudgeAvailability();
      } else {
        let detail = `HTTP ${res.status}`;
        try {
          const d = await res.json();
          if (d.detail) detail = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
        } catch (_) { /* sem corpo JSON */ }
        setPrepareBusy(false, "");
        showPrepareError(res.status === 422 ? `O juiz não conseguiu montar um desafio: ${detail}. Edite o texto e tente de novo.` : `Falha ao preparar o problema: ${detail}`);
      }
    } catch (e) {
      setPrepareBusy(false, "");
      showPrepareError(`Falha de rede: ${e.message}`);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function clearProblem() {
    problem = null;
    showPrepareError("");
    renderProblemCard();
    renderFightButton();
    if (cp.text) cp.text.focus();
  }

  // ------------------------------------------------------------ luta
  async function submit(ev) {
    ev.preventDefault();
    showError("");
    const body = {
      left: { provider: sel.left.provider.value, model: sel.left.model.value },
      right: { provider: sel.right.provider.value, model: sel.right.model.value },
    };
    if (!body.left.model || !body.right.model) {
      showError("Escolha um modelo para cada lutador.");
      return;
    }
    if (problem && problem.problem_id) body.problem_id = problem.problem_id;
    btn.disabled = true;
    try {
      const res = await fetchImpl("/api/matches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 201) {
        const data = await res.json();
        onStarted && onStarted(data.match_id);
      } else if (res.status === 409) {
        showError("Já existe uma luta em andamento.");
        onStarted && onStarted(null); // mostra a arena da luta corrente
      } else {
        let detail = `HTTP ${res.status}`;
        try {
          const d = await res.json();
          if (d.detail) detail = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
        } catch (_) { /* sem corpo JSON */ }
        showError(`Não foi possível iniciar a luta: ${detail}`);
      }
    } catch (e) {
      showError(`Falha de rede: ${e.message}`);
    } finally {
      btn.disabled = false;
    }
  }

  if (form) form.addEventListener("submit", submit);
  if (cp.prepare) cp.prepare.addEventListener("click", prepare);
  if (cp.change) cp.change.addEventListener("click", clearProblem);
  if (cp.text) cp.text.addEventListener("input", () => showPrepareError(""));
  loadModels();
  loadJudge();

  return {
    reload: loadModels,
    showError,
    prepare,
    clearProblem,
    get problem() { return problem; },
    get judge() { return judge; },
  };
}
