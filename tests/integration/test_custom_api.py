from __future__ import annotations

import json

from fastapi.testclient import TestClient

from llmarena.app import create_app
from llmarena.arena.judge import Judge
from llmarena.providers.fake import FakeProvider, FakeTurn
from llmarena.providers.registry import ModelEntry, ProviderEntry
from tests.conftest import GOOD_CODE
from tests.unit.test_custom_mode import JUDGE_JSON, judge_turn


def test_custom_problem_flow(settings):
    settings.fake_providers = True
    settings.round_seconds = 20.0
    settings.max_golpes_per_round = 50
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/judge").json()["available"] is False
        assert (
            client.post("/api/problems/generate", json={"statement": "soma de dois números"}).status_code
            == 503
        )

        manager = app.state.manager
        manager.judge = Judge(
            provider=FakeProvider(lambda s, u, m: judge_turn(JUDGE_JSON, level=u.count("Level") + 1)),
            model="fake-judge",
            sandbox=app.state.sandbox,
        )
        assert client.get("/api/judge").json() == {
            "available": True,
            "provider": "fake",
            "model": "fake-judge",
        }
        assert client.post("/api/problems/generate", json={"statement": "curto"}).status_code == 422

        r = client.post("/api/problems/generate", json={"statement": "some dois números inteiros"})
        assert r.status_code == 200, r.text
        prob = r.json()
        assert prob["function"] == "add" and prob["level"] == 1 and len(prob["tests"]) == 3
        assert "reference" not in prob

        app.state.registry.register(
            "fake",
            FakeProvider(
                lambda s, u, m: FakeTurn(
                    GOOD_CODE if m == "fast" else "def add(a, b):\n    return a - b\n",
                    delay_s=0.05 if m == "fast" else 0.3,
                )
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
        bad = client.post(
            "/api/matches",
            json={
                "left": {"provider": "fake", "model": "fast"},
                "right": {"provider": "fake", "model": "slow"},
                "problem_id": "nope",
            },
        )
        assert bad.status_code == 400
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            r = client.post(
                "/api/matches",
                json={
                    "left": {"provider": "fake", "model": "fast"},
                    "right": {"provider": "fake", "model": "slow"},
                    "problem_id": prob["problem_id"],
                },
            )
            assert r.status_code == 201, r.text
            seen = []
            for _ in range(5000):
                ev = json.loads(ws.receive_text())
                seen.append(ev)
                if ev["type"] == "match_end":
                    break
            types = [e["type"] for e in seen]
            assert seen[0]["type"] == "match_start" and seen[0]["mode"] == "custom"
            assert "judge" in types
            assert any(e["type"] == "fighter_status" and e["status"] == "advantage" for e in seen)
            assert any(e["type"] == "golpe_result" and e["category"] == "advantage" for e in seen)
            assert any(e["type"] == "challenge" and e["challenge"]["level"] >= 2 for e in seen)
            assert seen[-1]["winner"] == "left"
        match_id = r.json()["match_id"]
        ch = client.get(f"/api/matches/{match_id}/challenges").json()["challenges"]
        assert ch and ch[0]["level"] == 1
