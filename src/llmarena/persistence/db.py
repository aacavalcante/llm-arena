from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from llmarena.challenges.schema import Challenge
from llmarena.domain.models import FighterSpec, GolpeResult, RoundOutcome, Side

LEADERBOARD_SQL = """
SELECT ms.provider, ms.model, MAX(ms.display_name) AS display_name,
       COUNT(DISTINCT ms.match_id) AS matches,
       SUM(ms.won) AS wins, SUM(ms.drew) AS draws, SUM(ms.lost) AS losses,
       COALESCE(g.golpes, 0) AS golpes, COALESCE(g.hits, 0) AS hits,
       g.pass_rate, g.avg_hit_ms, COALESCE(g.total_damage, 0) AS total_damage
FROM match_sides ms
LEFT JOIN (
    SELECT provider, model,
           COUNT(*) AS golpes,
           SUM(CASE WHEN passed = 1 AND late = 0 THEN 1 ELSE 0 END) AS hits,
           AVG(passed) AS pass_rate,
           AVG(CASE WHEN passed = 1 AND late = 0 THEN latency_ms END) AS avg_hit_ms,
           SUM(damage) AS total_damage
    FROM golpes GROUP BY provider, model
) g ON g.provider = ms.provider AND g.model = ms.model
WHERE ms.winner IS NOT NULL AND ms.winner != 'aborted'
GROUP BY ms.provider, ms.model
ORDER BY wins DESC, (SUM(ms.won) * 1.0 / COUNT(DISTINCT ms.match_id)) DESC, avg_hit_ms ASC
"""


class Db:
    """Persistência em SQLite (WAL). Métodos síncronos; a arena chama via asyncio.to_thread."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(
                resources.files("llmarena.persistence").joinpath("schema.sql").read_text()
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- escrita -------------------------------------------------------------------------------------

    def start_match(
        self, match_id: str, specs: dict[Side, FighterSpec], rules_json: str, started_at: str
    ) -> None:
        lf, rt = specs[Side.LEFT], specs[Side.RIGHT]
        with self._lock:
            self._conn.execute(
                "INSERT INTO matches (id, started_at, left_provider, left_model, left_display, right_provider, "
                "right_model, right_display, rules_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    match_id,
                    started_at,
                    lf.provider,
                    lf.model,
                    lf.display_name,
                    rt.provider,
                    rt.model,
                    rt.display_name,
                    rules_json,
                ),
            )

    def record_golpe(
        self, match_id: str, round_no: int, r: GolpeResult, challenge: Challenge, spec: FighterSpec
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO golpes (match_id, round_no, challenge_seq, side, provider, model, challenge_id, "
                "difficulty, attempt, category, passed, late, counter, damage, latency_ms, output_chars, code, "
                "detail, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    match_id,
                    round_no,
                    r.seq,
                    r.side.value,
                    spec.provider,
                    spec.model,
                    challenge.id,
                    challenge.difficulty.value,
                    r.attempt,
                    r.category.value,
                    int(r.passed),
                    int(r.late),
                    int(r.counter),
                    r.damage,
                    r.ms,
                    r.output_chars,
                    r.code,
                    r.detail,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )

    def record_round(self, match_id: str, outcome: RoundOutcome) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO rounds (match_id, round_no, winner, reason, hp_left, hp_right, duration_ms) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    match_id,
                    outcome.round_no,
                    outcome.winner.value if outcome.winner else "draw",
                    outcome.reason,
                    outcome.hp[Side.LEFT],
                    outcome.hp[Side.RIGHT],
                    outcome.duration_ms,
                ),
            )

    def finish_match(self, match_id: str, winner: str, score: dict[Side, int], ended_at: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE matches SET winner = ?, score_left = ?, score_right = ?, ended_at = ? WHERE id = ?",
                (winner, score[Side.LEFT], score[Side.RIGHT], ended_at, match_id),
            )

    def record_generated(self, match_id: str, statement_src: str, challenge: Challenge) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO generated_challenges (id, match_id, level, statement_src, challenge_json, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    challenge.id,
                    match_id,
                    challenge.level,
                    statement_src,
                    challenge.model_dump_json(),
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )

    def match_challenges(self, match_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, level, statement_src, challenge_json, created_at FROM generated_challenges "
                "WHERE match_id = ? ORDER BY level",
                (match_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            c = json.loads(d.pop("challenge_json"))
            c.pop("reference", None)
            d["challenge"] = c
            out.append(d)
        return out

    # ---- leitura -------------------------------------------------------------------------------------

    def leaderboard(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(LEADERBOARD_SQL).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["win_rate"] = (d["wins"] / d["matches"]) if d["matches"] else 0.0
            d["pass_rate"] = float(d["pass_rate"]) if d["pass_rate"] is not None else 0.0
            d["avg_hit_ms"] = int(d["avg_hit_ms"]) if d["avg_hit_ms"] is not None else None
            out.append(d)
        return out

    def recent_matches(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, started_at, ended_at, left_provider, left_model, left_display, right_provider, "
                "right_model, right_display, winner, score_left, score_right FROM matches "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def match_golpes(self, match_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM golpes WHERE match_id = ? ORDER BY id", (match_id,)
            ).fetchall()
        return [dict(r) for r in rows]
