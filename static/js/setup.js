// Tela inicial: carrega /api/models, preenche os selects e cria a luta (POST /api/matches).

export function createSetup({ onStarted, onError } = {}) {
  const form = document.getElementById("setup-form");
  const btn = document.getElementById("fight-btn");
  const errEl = document.getElementById("setup-error");
  const sel = {
    left: { provider: document.getElementById("sel-provider-left"), model: document.getElementById("sel-model-left") },
    right: { provider: document.getElementById("sel-provider-right"), model: document.getElementById("sel-model-right") },
  };
  let providers = [];

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
      const res = await fetch("/api/models");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      providers = data.providers || [];
      if (!providers.length) showError("Nenhum modelo disponível. Configure as chaves de API no servidor.");
      fillProviders();
    } catch (e) {
      showError(`Não foi possível carregar os modelos (${e.message}).`);
    }
  }

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
    btn.disabled = true;
    try {
      const res = await fetch("/api/matches", {
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
  loadModels();

  return { reload: loadModels, showError };
}
