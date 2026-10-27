// Painéis de código (esquerda/direita), chips de status, badge do último golpe e caixa do desafio.

const STATUS_LABEL = {
  idle: "aguardando",
  writing: "escrevendo…",
  testing: "testando…",
  stunned: "atordoado",
  exhausted: "exausto",
  ko: "KO",
  advantage: "VANTAGEM",
};

const JUDGE_HIDE_MS = 4000; // tempo que o banner do juiz fica visível após "ready"/"failed"

const DIFF_LABEL = { easy: "fácil", medium: "médio", hard: "difícil" };

/** Texto do badge do último resultado (mode = "bank" | "custom"). */
export function resultLabel(r, mode = "bank") {
  if (!r) return "";
  if (r.passed && r.damage > 0 && r.category === "advantage") return `✔ golpe livre ${r.damage}`;
  if (r.passed && r.damage > 0) {
    const s = (r.ms / 1000).toFixed(1);
    return `✔ acertou ${r.damage} (${s}s)${r.counter ? " · CONTRA-ATAQUE" : ""}`;
  }
  if (r.passed && r.late) return mode === "custom" ? "✔ resolveu, fim da vantagem" : "✔ válido mas atrasado";
  if (r.passed) return "✔ válido";
  if (r.category === "api_error") return "✘ erro de API";
  const tests = r.tests_total ? ` (${r.tests_passed}/${r.tests_total} testes)` : "";
  return `✘ errou: ${r.category}${tests}`;
}

/** Texto do banner do juiz (modo custom). */
export function judgeLabel(j) {
  if (!j) return "";
  if (j.status === "generating") return `Juiz preparando o nível ${j.level}…`;
  if (j.status === "ready") return `Nível ${j.level} pronto`;
  if (j.status === "failed") return `Juiz falhou: usando o banco${j.message ? ` (${j.message})` : ""}`;
  return j.message || "";
}

export function createPanels(root = document) {
  const sides = {};
  for (const side of ["left", "right"]) {
    const pre = root.getElementById(`code-${side}`);
    const s = {
      name: root.getElementById(`pname-${side}`),
      model: root.getElementById(`pmodel-${side}`),
      status: root.getElementById(`status-${side}`),
      pre,
      caret: pre ? pre.querySelector(".caret") : null,
      result: root.getElementById(`result-${side}`),
      cur: "",
      autoscroll: true,
    };
    if (pre) {
      // Para de rolar automaticamente se o usuário subiu; volta quando ele chega ao fim.
      pre.addEventListener("scroll", () => {
        s.autoscroll = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 12;
      });
    }
    sides[side] = s;
  }

  const ch = {
    box: root.getElementById("challenge-box"),
    title: root.getElementById("challenge-title"),
    diff: root.getElementById("challenge-diff"),
    statement: root.getElementById("challenge-statement"),
    signature: root.getElementById("challenge-signature"),
    mode: root.getElementById("challenge-mode"),
    judge: root.getElementById("judge-banner"),
    problem: root.getElementById("challenge-problem"),
    problemText: root.getElementById("challenge-problem-text"),
  };
  // Banner do juiz: some sozinho alguns segundos depois de "ready"/"failed"
  const judgeUi = { key: "", hiddenKey: "", timer: 0 };

  function setText(el, txt) {
    if (el && el.textContent !== txt) el.textContent = txt;
  }

  // Sincroniza o <pre> com o código do estado: anexa só a diferença quando possível.
  function syncCode(side, code) {
    const s = sides[side];
    if (!s.pre) return;
    const text = code || "";
    if (text === s.cur) return;
    if (text.startsWith(s.cur) && s.cur.length > 0) {
      const node = root.createTextNode(text.slice(s.cur.length));
      s.pre.insertBefore(node, s.caret);
    } else {
      // Recomeço (novo desafio / snapshot): substitui tudo
      while (s.pre.firstChild && s.pre.firstChild !== s.caret) s.pre.removeChild(s.pre.firstChild);
      if (!s.caret || s.caret.parentNode !== s.pre) {
        s.pre.textContent = "";
        s.caret = root.createElement("span");
        s.caret.className = "caret";
        s.pre.appendChild(s.caret);
      }
      s.pre.insertBefore(root.createTextNode(text), s.caret);
    }
    s.cur = text;
    if (s.autoscroll) s.pre.scrollTop = s.pre.scrollHeight;
  }

  function renderSide(state, side) {
    const s = sides[side];
    const m = state.match;
    const f = m ? m[side] : null;
    setText(s.name, f ? f.display_name || f.model : side === "left" ? "Lutador 1" : "Lutador 2");
    setText(s.model, f ? `${f.provider} / ${f.model}` : "—");

    const status = m ? m.fighter_status[side] || "idle" : "idle";
    setText(s.status, STATUS_LABEL[status] || status);
    if (s.status) s.status.dataset.status = status;
    if (s.pre) s.pre.classList.toggle("writing", status === "writing");

    syncCode(side, m ? m.code[side] : "");

    const r = m ? m.last_result[side] : null;
    if (s.result) {
      setText(s.result, resultLabel(r, m ? m.mode : "bank"));
      s.result.title = r ? r.detail || "" : "";
      s.result.dataset.kind = !r ? "" : r.passed && r.damage > 0 ? (r.category === "advantage" ? "free" : "hit") : r.passed ? "late" : "miss";
    }
  }

  function renderJudge(state) {
    if (!ch.judge) return;
    const m = state.match;
    const j = m && m.mode === "custom" && m.status === "running" ? m.judge : null;
    const key = j ? `${j.status}:${j.level}:${j.message || ""}` : "";
    if (key !== judgeUi.key) {
      judgeUi.key = key;
      clearTimeout(judgeUi.timer);
      judgeUi.timer = 0;
      if (j && (j.status === "ready" || j.status === "failed")) {
        judgeUi.timer = setTimeout(() => {
          judgeUi.hiddenKey = key;
          ch.judge.classList.add("hidden");
        }, JUDGE_HIDE_MS);
      }
    }
    const visible = !!j && judgeUi.hiddenKey !== key;
    ch.judge.classList.toggle("hidden", !visible);
    setText(ch.judge, visible ? judgeLabel(j) : "");
    ch.judge.dataset.status = j ? j.status : "";
  }

  function renderCustom(state) {
    const m = state.match;
    const custom = !!m && m.mode === "custom";
    if (ch.mode) {
      const level = m ? (m.challenge && m.challenge.level) || m.level || 0 : 0;
      setText(ch.mode, custom ? `PERSONALIZADO · NÍVEL ${level}` : "");
      ch.mode.classList.toggle("hidden", !custom);
    }
    if (ch.problem) {
      const show = custom && !!m.problem;
      ch.problem.classList.toggle("hidden", !show);
      setText(ch.problemText, show ? m.problem : "");
    }
    renderJudge(state);
  }

  function renderChallenge(state) {
    const c = state.match ? state.match.challenge : null;
    if (ch.box) ch.box.classList.toggle("empty", !c);
    if (ch.box) ch.box.classList.toggle("custom", !!state.match && state.match.mode === "custom");
    renderCustom(state);
    if (!c) {
      const m = state.match;
      setText(ch.title, !m ? "Nenhuma luta em andamento" : m.status === "finished" ? "Luta encerrada" : m.status === "aborted" ? "Luta abortada" : "Aguardando próximo desafio…");
      setText(ch.diff, "");
      setText(ch.statement, "");
      setText(ch.signature, "");
      return;
    }
    setText(ch.title, c.title);
    setText(ch.diff, DIFF_LABEL[c.difficulty] || c.difficulty);
    if (ch.diff) ch.diff.dataset.diff = c.difficulty;
    setText(ch.statement, c.statement);
    setText(ch.signature, c.signature);
  }

  function render(state) {
    renderSide(state, "left");
    renderSide(state, "right");
    renderChallenge(state);
  }

  return { render, syncCode, sides };
}
