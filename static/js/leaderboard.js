// Ranking (/api/leaderboard) e últimas lutas (/api/matches).

function pct(v) {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function td(text, cls) {
  const el = document.createElement("td");
  el.textContent = text;
  if (cls) el.className = cls;
  return el;
}

async function loadLeaderboard() {
  const tbody = document.querySelector("#lb-table tbody");
  const empty = document.getElementById("lb-empty");
  try {
    const res = await fetch("/api/leaderboard");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const rows = (data.rows || []).slice().sort((a, b) => b.wins - a.wins || (b.win_rate || 0) - (a.win_rate || 0));
    tbody.innerHTML = "";
    rows.forEach((r, i) => {
      const tr = document.createElement("tr");
      tr.appendChild(td(String(i + 1), "num"));
      tr.appendChild(td(r.display_name || r.model));
      tr.appendChild(td(r.provider, "muted"));
      tr.appendChild(td(String(r.matches), "num"));
      tr.appendChild(td(`${r.wins}/${r.draws}/${r.losses}`, "num"));
      tr.appendChild(td(pct(r.win_rate), "num"));
      tr.appendChild(td(`${r.hits}/${r.golpes}`, "num"));
      tr.appendChild(td(pct(r.pass_rate), "num"));
      tr.appendChild(td(r.avg_hit_ms == null ? "—" : `${(r.avg_hit_ms / 1000).toFixed(1)}s`, "num"));
      tr.appendChild(td(String(r.total_damage), "num"));
      tbody.appendChild(tr);
    });
    empty.textContent = rows.length ? "" : "Nenhuma luta registrada ainda.";
  } catch (e) {
    empty.textContent = `Não foi possível carregar o ranking (${e.message}).`;
  }
}

async function loadMatches() {
  const list = document.getElementById("matches-list");
  try {
    const res = await fetch("/api/matches?limit=20");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    list.innerHTML = "";
    const ms = data.matches || [];
    if (!ms.length) {
      list.innerHTML = "<li class='muted'>Nenhuma luta ainda.</li>";
      return;
    }
    for (const m of ms) {
      const li = document.createElement("li");
      const left = document.createElement("span");
      left.className = "side-left" + (m.winner === "left" ? " winner" : "");
      left.textContent = m.left_model;
      const right = document.createElement("span");
      right.className = "side-right" + (m.winner === "right" ? " winner" : "");
      right.textContent = m.right_model;
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = `${m.score_left ?? 0} × ${m.score_right ?? 0}`;
      const when = document.createElement("span");
      when.className = "muted when";
      when.textContent = fmtDate(m.started_at) + (m.ended_at ? "" : " · em andamento");
      li.append(left, score, right, when);
      list.appendChild(li);
    }
  } catch (e) {
    list.innerHTML = `<li class='muted'>Não foi possível carregar as lutas (${e.message}).</li>`;
  }
}

loadLeaderboard();
loadMatches();
