from __future__ import annotations

import asyncio
import json
import random

import pytest

from llmarena.arena.advantage import AdvantageRoundRunner
from llmarena.arena.judge import GeneratedProblem, Judge, JudgeError
from llmarena.arena.match import MatchRunner
from llmarena.arena.source import BankSource, CustomSource
from llmarena.domain.models import Difficulty, Side
from llmarena.protocol import ChallengeEvent, HpUpdate, JudgeEvent, MatchEnd, MatchStart
from llmarena.providers.fake import FakeProvider, FakeTurn
from llmarena.sandbox.executor import SubprocessSandbox
from llmarena.ws import Broadcaster
from tests.conftest import GOOD_CODE, make_challenge
from tests.unit.test_arena import SPECS, FakeSandbox, results

JUDGE_JSON = {
    "title": "Soma",
    "function": "add",
    "signature": "def add(a: int, b: int) -> int",
    "statement": "Return a + b.",
    "difficulty": "easy",
    "tests": [
        {"args": [1, 2], "expected": 3},
        {"args": [0, 0], "expected": 0},
        {"args": [-1, 1], "expected": 0},
    ],
    "reference": GOOD_CODE,
}


def judge_turn(data: dict, level: int = 1, fence: bool = False) -> FakeTurn:
    text = json.dumps({**data, "title": f"{data['title']} nível {level}"})
    return FakeTurn(f"```json\n{text}\n```" if fence else f"Here it is:\n{text}")


@pytest.fixture(scope="module")
def sandbox():
    return SubprocessSandbox()


async def test_judge_generates_valid_challenge(sandbox):
    provider = FakeProvider([judge_turn(JUDGE_JSON, fence=True)])
    judge = Judge(provider=provider, model="j", sandbox=sandbox)
    problem = await judge.generate_problem("Some dois números")
    c = problem.challenge
    assert c.custom and c.level == 1 and c.function == "add" and len(c.tests) == 3
    assert c.id.startswith("custom_") and problem.statement_src == "Some dois números"
    assert "Problem written by the user" in provider.calls[0]["user"]


async def test_judge_retries_with_feedback_then_succeeds(sandbox):
    bad = {**JUDGE_JSON, "reference": "def add(a, b):\n    return a - b\n"}
    provider = FakeProvider([FakeTurn("not json at all"), judge_turn(bad), judge_turn(JUDGE_JSON)])
    judge = Judge(provider=provider, model="j", sandbox=sandbox, max_tries=3)
    c = await judge.generate("x" * 10)
    assert c.function == "add"
    assert len(provider.calls) == 3
    assert "no JSON object" in provider.calls[1]["user"]
    assert "failed its own tests" in provider.calls[2]["user"]


async def test_judge_gives_up(sandbox):
    provider = FakeProvider([FakeTurn("nope")])
    judge = Judge(provider=provider, model="j", sandbox=sandbox, max_tries=2)
    with pytest.raises(JudgeError):
        await judge.generate("x" * 10)


async def test_judge_rejects_forbidden_reference(sandbox):
    bad = {**JUDGE_JSON, "reference": "import os\n" + GOOD_CODE}
    provider = FakeProvider([judge_turn(bad), judge_turn(JUDGE_JSON)])
    judge = Judge(provider=provider, model="j", sandbox=sandbox)
    await judge.generate("x" * 10)
    assert "rejected" in provider.calls[1]["user"]


async def test_custom_source_prefetches_levels(sandbox, small_bank):
    provider = FakeProvider(lambda s, u, m: judge_turn(JUDGE_JSON, level=u.count("Level") + 1))
    judge = Judge(provider=provider, model="j", sandbox=sandbox)
    problem = await judge.generate_problem("x" * 10)
    bc = Broadcaster()
    seen: list[int] = []

    async def on_generated(c):
        seen.append(c.level)

    src = CustomSource(
        judge=judge,
        problem=problem,
        broadcaster=bc,
        fallback=BankSource(small_bank, random.Random(1)),
        on_generated=on_generated,
    )
    c1 = await src.next()
    c2 = await src.next()
    c3 = await src.next()
    assert (c1.level, c2.level, c3.level) == (1, 2, 3)
    assert all(c.custom for c in (c1, c2, c3))
    assert "STRICTLY HARDER" in provider.calls[1]["user"] and "level 1" in provider.calls[1]["user"]
    statuses = [(e.status, e.level) for e in bc.history if isinstance(e, JudgeEvent)]
    assert ("generating", 2) in statuses and ("ready", 2) in statuses and ("ready", 3) in statuses
    assert seen[:2] == [2, 3]
    await src.close()


async def test_custom_source_falls_back_to_bank_when_judge_fails(sandbox, small_bank):
    provider = FakeProvider([judge_turn(JUDGE_JSON), FakeTurn("garbage")])
    judge = Judge(provider=provider, model="j", sandbox=sandbox, max_tries=1)
    problem = await judge.generate_problem("x" * 10)
    bc = Broadcaster()
    src = CustomSource(
        judge=judge, problem=problem, broadcaster=bc, fallback=BankSource(small_bank, random.Random(1))
    )
    c1 = await src.next()
    c2 = await src.next()
    assert c1.custom and not c2.custom and c2.id in {c.id for c in small_bank.challenges}
    assert any(isinstance(e, JudgeEvent) and e.status == "failed" for e in bc.history)
    await src.close()


def make_adv_round(settings, bank, left, right, problem, judge, **overrides):
    for k, v in overrides.items():
        setattr(settings, k, v)
    bc = Broadcaster()
    src = CustomSource(
        judge=judge, problem=problem, broadcaster=bc, fallback=BankSource(bank, random.Random(1))
    )
    runner = AdvantageRoundRunner(
        round_no=1,
        specs=SPECS,
        providers={Side.LEFT: left, Side.RIGHT: right},
        model_extra={Side.LEFT: None, Side.RIGHT: None},
        bank=bank,
        settings=settings,
        broadcaster=bc,
        sandbox=FakeSandbox(),
        rng=random.Random(1),
        score={Side.LEFT: 0, Side.RIGHT: 0},
        source=src,
    )
    return runner, bc


@pytest.fixture
def problem():
    return GeneratedProblem(
        problem_id="p1",
        statement_src="soma",
        challenge=make_challenge("custom_1").model_copy(update={"level": 1, "custom": True}),
        judge_model="j",
    )


@pytest.fixture
def fake_judge(sandbox):
    return Judge(
        provider=FakeProvider(lambda s, u, m: judge_turn(JUDGE_JSON, level=u.count("Level") + 1)),
        model="j",
        sandbox=sandbox,
    )


async def test_advantage_free_hits_until_opponent_solves(settings, small_bank, problem, fake_judge):
    bad = "def add(a, b):\n    return a - b\n"
    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.05)])
    right = FakeProvider(
        [
            FakeTurn(bad, delay_s=0.2),
            FakeTurn(bad, delay_s=0.05),
            FakeTurn(GOOD_CODE, delay_s=0.05),
            FakeTurn(GOOD_CODE, delay_s=5.0),
        ]
    )
    runner, bc = make_adv_round(
        settings,
        small_bank,
        left,
        right,
        problem,
        fake_judge,
        round_seconds=4.0,
        max_golpes_per_round=50,
        max_attempts_per_challenge=5,
    )
    await runner.run()
    rs = [r for r in results(bc) if r.seq == 0]
    kinds = [(r.side, r.category, r.damage, r.late) for r in rs]
    assert kinds[0] == ("left", "ok", 10, False)  # primeiro a resolver: golpe + vantagem
    assert kinds[1] == ("right", "wrong_answer", 0, False)
    assert kinds[2] == ("left", "advantage", 10, False)  # golpe livre
    assert kinds[3] == ("right", "wrong_answer", 0, False)
    assert kinds[4] == ("left", "advantage", 10, False)
    assert kinds[5] == ("right", "ok", 0, True)  # resolveu: fim da vantagem, sem dano
    hps = [e.right for e in bc.history if isinstance(e, HpUpdate)]
    assert hps[:3] == [90, 80, 70]  # golpe inicial + dois golpes livres de 10
    assert not any(r.opens_counter for r in rs)
    statuses = [(e.side, e.status) for e in bc.history if e.__class__.__name__ == "FighterStatusEvent"]
    assert ("left", "advantage") in statuses
    # a fase seguinte é o nível 2 gerado pelo juiz
    levels = [e.challenge.level for e in bc.history if isinstance(e, ChallengeEvent)]
    assert levels[:2] == [1, 2]


async def test_advantage_api_error_gives_no_free_hit(settings, small_bank, problem, fake_judge):
    from llmarena.providers.base import ProviderError

    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.05)])
    right = FakeProvider(
        [FakeTurn("", error=ProviderError("boom"), delay_s=0.2), FakeTurn(GOOD_CODE, delay_s=5.0)]
    )
    runner, bc = make_adv_round(
        settings, small_bank, left, right, problem, fake_judge, round_seconds=1.5, max_golpes_per_round=50
    )
    await runner.run()
    rs = [r for r in results(bc) if r.seq == 0]
    assert [r.category for r in rs][:2] == ["ok", "api_error"]
    assert not any(r.category == "advantage" for r in rs)
    assert runner.fighters[Side.RIGHT].hp == 90


async def test_advantage_ko_by_free_hits(settings, small_bank, problem, fake_judge):
    hard = problem.challenge.model_copy(update={"difficulty": Difficulty.HARD})
    problem = GeneratedProblem(problem_id="p2", statement_src="soma", challenge=hard, judge_model="j")
    bad = "def add(a, b):\n    return a - b\n"
    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.05)])
    right = FakeProvider([FakeTurn(bad, delay_s=0.1)])
    runner, bc = make_adv_round(
        settings,
        small_bank,
        left,
        right,
        problem,
        fake_judge,
        round_seconds=10.0,
        max_golpes_per_round=50,
        max_attempts_per_challenge=5,
    )
    outcome = await runner.run()
    assert outcome.reason == "ko" and outcome.winner is Side.LEFT and outcome.hp[Side.RIGHT] == 0
    assert isinstance([e for e in bc.history if isinstance(e, HpUpdate)][-1], HpUpdate)


async def test_match_runner_custom_mode_end_to_end(settings, small_bank, problem, fake_judge, tmp_path):
    from llmarena.persistence.db import Db

    db = Db(tmp_path / "c.db")
    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.02)])
    right = FakeProvider([FakeTurn("def add(a, b):\n    return a - b\n", delay_s=0.05)])
    settings.round_seconds = 10.0
    settings.max_golpes_per_round = 50
    settings.max_attempts_per_challenge = 6
    bc = Broadcaster()
    runner = MatchRunner(
        match_id="cm1",
        specs=SPECS,
        providers={Side.LEFT: left, Side.RIGHT: right},
        model_extra={Side.LEFT: None, Side.RIGHT: None},
        bank=small_bank,
        settings=settings,
        broadcaster=bc,
        sandbox=FakeSandbox(),
        db=db,
        problem=problem,
        judge=fake_judge,
    )
    await asyncio.wait_for(runner.run(), 60)
    start = bc.history[0]
    assert isinstance(start, MatchStart) and start.mode == "custom" and start.problem == "soma"
    end = bc.history[-1]
    assert isinstance(end, MatchEnd) and end.winner == "left"
    assert bc.view.mode == "custom"
    stored = db.match_challenges("cm1")
    assert stored and stored[0]["level"] == 1 and "reference" not in stored[0]["challenge"]
    assert any(g["category"] == "advantage" for g in db.match_golpes("cm1"))
    db.close()
