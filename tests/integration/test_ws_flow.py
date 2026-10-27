from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from llmarena.app import create_app
from llmarena.providers.fake import _TITLE_RE, FakeProvider, FakeTurn
from llmarena.providers.registry import ModelEntry, ProviderEntry
from tests.conftest import GOOD_CODE


def reference_for(bank, user_prompt: str) -> str:
    m = _TITLE_RE.search(user_prompt)
    c = bank.by_title(m.group(1).strip()) if m else None
    return c.reference if c and c.reference else GOOD_CODE


@pytest.fixture
def client(settings):
    settings.fake_providers = True
    settings.round_seconds = 20.0
    settings.max_golpes_per_round = 50
    app = create_app(settings)
    with TestClient(app) as c:
        # Substitui o demo por fakes determinísticos: esquerda rápida, direita lenta
        reg = app.state.registry
        bank = app.state.bank
        reg.register(
            "fake",
            FakeProvider(
                lambda s, u, m: FakeTurn(reference_for(bank, u), delay_s=0.05 if m == "fast" else 5.0)
            ),
            ProviderEntry(
                name="fake",
                display_name="Fake",
                models=[
                    ModelEntry(id="fast", display_name="fast"),
                    ModelEntry(id="slow", display_name="slow"),
                ],
            ),
        )
        yield c


def _recv_until(ws, types: set[str], limit: int = 2000) -> list[dict]:
    seen = []
    for _ in range(limit):
        ev = json.loads(ws.receive_text())
        seen.append(ev)
        if ev["type"] in types:
            return seen
    raise AssertionError(f"never saw {types}; last={seen[-3:]}")


def test_full_match_over_websocket(client):
    models = client.get("/api/models").json()
    names = {p["name"] for p in models["providers"]}
    assert "fake" in names and "demo" in names
    assert client.get("/api/matches/current").status_code == 404

    with client.websocket_connect("/ws") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "state_snapshot" and first["match"] is None
        bad = client.post(
            "/api/matches",
            json={
                "left": {"provider": "fake", "model": "nope"},
                "right": {"provider": "fake", "model": "slow"},
            },
        )
        assert bad.status_code == 400
        r = client.post(
            "/api/matches",
            json={
                "left": {"provider": "fake", "model": "fast"},
                "right": {"provider": "fake", "model": "slow"},
            },
        )
        assert r.status_code == 201, r.text
        match_id = r.json()["match_id"]
        dup = client.post(
            "/api/matches",
            json={
                "left": {"provider": "fake", "model": "fast"},
                "right": {"provider": "fake", "model": "slow"},
            },
        )
        assert dup.status_code == 409

        seen = _recv_until(ws, {"match_end"})
        types = [e["type"] for e in seen]
        for t in (
            "match_start",
            "round_start",
            "challenge",
            "token",
            "golpe_result",
            "hp_update",
            "round_end",
            "match_end",
        ):
            assert t in types, t
        assert types.index("match_start") < types.index("round_start") < types.index("challenge")
        end = seen[-1]
        assert (
            end["match_id"] == match_id
            and end["winner"] == "left"
            and end["score"] == {"left": 2, "right": 0}
        )
        hits = [e for e in seen if e["type"] == "golpe_result" and e["passed"]]
        assert all(h["side"] == "left" for h in hits)
        # os tokens vêm coalescidos, com o seq do desafio
        tok = next(e for e in seen if e["type"] == "token")
        assert tok["side"] == "left" and "seq" in tok

    # quem entra depois recebe o snapshot final
    with client.websocket_connect("/ws") as ws:
        snap = json.loads(ws.receive_text())
        assert snap["type"] == "state_snapshot" and snap["match"]["status"] == "finished"
        assert snap["match"]["winner"] == "left"

    board = client.get("/api/leaderboard").json()["rows"]
    assert board and board[0]["model"] == "fast" and board[0]["wins"] == 1
    recent = client.get("/api/matches").json()["matches"]
    assert recent[0]["id"] == match_id and recent[0]["winner"] == "left"
    golpes = client.get(f"/api/matches/{match_id}/golpes").json()["golpes"]
    assert golpes and all(g["match_id"] == match_id for g in golpes)
    assert client.get("/api/health").json()["ok"] is True


def test_abort_running_match(client):
    reg = client.app.state.registry
    reg.register(
        "fake",
        FakeProvider([FakeTurn(GOOD_CODE, delay_s=30.0)]),
        ProviderEntry(
            name="fake",
            display_name="Fake",
            models=[ModelEntry(id="fast", display_name="fast"), ModelEntry(id="slow", display_name="slow")],
        ),
    )
    assert client.delete("/api/matches/current").status_code == 404
    r = client.post(
        "/api/matches",
        json={"left": {"provider": "fake", "model": "fast"}, "right": {"provider": "fake", "model": "slow"}},
    )
    assert r.status_code == 201
    assert client.get("/api/matches/current").status_code == 200
    assert client.delete("/api/matches/current").status_code == 204
    assert client.get("/api/matches/current").status_code == 404
    assert client.get("/api/matches").json()["matches"][0]["winner"] == "aborted"


def test_index_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "html" in r.headers["content-type"]
