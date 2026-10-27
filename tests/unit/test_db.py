from __future__ import annotations

from llmarena.domain.models import Category, FighterSpec, GolpeResult, RoundOutcome, Side
from llmarena.persistence.db import Db
from tests.conftest import make_challenge

SPECS = {Side.LEFT: FighterSpec("a", "m1", "M1"), Side.RIGHT: FighterSpec("b", "m2", "M2")}


def _play(db: Db, match_id: str, winner: str, left_hits: int, right_hits: int) -> None:
    db.start_match(match_id, SPECS, "{}", "2026-01-01T00:00:00+00:00")
    ch = make_challenge()
    for i in range(left_hits):
        db.record_golpe(
            match_id,
            1,
            GolpeResult(Side.LEFT, i, 1, True, Category.OK, "ok", 1000 + i, damage=10),
            ch,
            SPECS[Side.LEFT],
        )
    for i in range(right_hits):
        db.record_golpe(
            match_id,
            1,
            GolpeResult(Side.RIGHT, i, 1, True, Category.OK, "ok", 2000, damage=10),
            ch,
            SPECS[Side.RIGHT],
        )
    db.record_golpe(
        match_id,
        1,
        GolpeResult(Side.RIGHT, 9, 1, False, Category.WRONG_ANSWER, "x", 500),
        ch,
        SPECS[Side.RIGHT],
    )
    db.record_golpe(
        match_id,
        1,
        GolpeResult(Side.RIGHT, 9, 2, True, Category.OK, "x", 900, late=True),
        ch,
        SPECS[Side.RIGHT],
    )
    db.record_round(
        match_id,
        RoundOutcome(
            1, Side.LEFT if winner == "left" else None, "timeout", {Side.LEFT: 100, Side.RIGHT: 70}, 90000, {}
        ),
    )
    db.finish_match(
        match_id,
        winner,
        {Side.LEFT: 1 if winner == "left" else 0, Side.RIGHT: 0},
        "2026-01-01T00:05:00+00:00",
    )


def test_leaderboard_aggregates(tmp_path):
    db = Db(tmp_path / "t.db")
    _play(db, "m1", "left", 3, 1)
    _play(db, "m2", "draw", 1, 1)
    db.start_match("m3", SPECS, "{}", "2026-01-02T00:00:00+00:00")  # em andamento / abortada: fora do ranking
    db.finish_match("m3", "aborted", {Side.LEFT: 0, Side.RIGHT: 0}, "2026-01-02T00:01:00+00:00")
    rows = {r["model"]: r for r in db.leaderboard()}
    assert rows["m1"]["matches"] == 2 and rows["m1"]["wins"] == 1 and rows["m1"]["draws"] == 1
    assert rows["m1"]["hits"] == 4 and rows["m1"]["pass_rate"] == 1.0 and rows["m1"]["win_rate"] == 0.5
    assert rows["m2"]["losses"] == 1 and rows["m2"]["hits"] == 2  # os golpes atrasados não contam como acerto
    assert rows["m2"]["pass_rate"] < 1.0 and rows["m2"]["avg_hit_ms"] == 2000
    assert rows["m1"]["display_name"] == "M1"
    assert db.leaderboard()[0]["model"] == "m1"
    recent = db.recent_matches(5)
    assert [m["id"] for m in recent] == ["m3", "m2", "m1"] or [m["id"] for m in recent][0] == "m3"
    assert len(db.match_golpes("m1")) == 6
    db.close()
