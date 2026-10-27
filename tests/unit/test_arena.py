from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

import pytest

from llmarena.arena.match import MatchRunner
from llmarena.arena.round import RoundRunner
from llmarena.domain.models import Category, FighterSpec, Side
from llmarena.protocol import (
    ErrorEvent,
    FighterStatusEvent,
    GolpeResultEvent,
    HpUpdate,
    MatchEnd,
    RoundEnd,
    RoundStart,
    TimerEvent,
)
from llmarena.providers.base import ProviderError, RateLimitedError
from llmarena.providers.fake import FakeProvider, FakeTurn
from llmarena.sandbox.executor import SandboxResult, SubprocessSandbox
from llmarena.ws import Broadcaster
from tests.conftest import BAD_CODE, GOOD_CODE


@dataclass
class FakeSandbox:
    """Julga pelo conteúdo do código: GOOD_CODE passa, o resto falha."""

    delay_s: float = 0.0
    calls: list[str] = field(default_factory=list)

    async def run(self, code: str, spec) -> SandboxResult:
        self.calls.append(code)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if code.strip() == GOOD_CODE.strip():
            return SandboxResult(True, Category.OK, "3/3", 3, 3)
        return SandboxResult(False, Category.WRONG_ANSWER, "test 0: expected 3, got -1", 0, 3)


SPECS = {
    Side.LEFT: FighterSpec("fake", "fast", "Fast"),
    Side.RIGHT: FighterSpec("fake", "slow", "Slow"),
}


def make_round(settings, bank, left, right, sandbox=None, round_no=1, score=None, **overrides):
    for k, v in overrides.items():
        setattr(settings, k, v)
    bc = Broadcaster()
    runner = RoundRunner(
        round_no=round_no,
        specs=SPECS,
        providers={Side.LEFT: left, Side.RIGHT: right},
        model_extra={Side.LEFT: None, Side.RIGHT: None},
        bank=bank,
        settings=settings,
        broadcaster=bc,
        sandbox=sandbox or FakeSandbox(),
        rng=random.Random(42),
        score=score or {Side.LEFT: 0, Side.RIGHT: 0},
    )
    return runner, bc


def results(bc: Broadcaster) -> list[GolpeResultEvent]:
    return [e for e in bc.history if isinstance(e, GolpeResultEvent)]


async def test_fast_correct_fighter_hits_and_cancels_opponent(settings, small_bank):
    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.05)])
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=5.0)])
    runner, bc = make_round(settings, small_bank, left, right, round_seconds=1.5, max_golpes_per_round=2)
    outcome = await runner.run()
    hits = [r for r in results(bc) if r.passed and not r.late]
    assert hits and all(h.side == "left" for h in hits)
    assert outcome.winner is Side.LEFT and outcome.reason == "timeout"
    assert outcome.hp[Side.RIGHT] < settings.hp and outcome.hp[Side.LEFT] == settings.hp
    assert right.closed == len(right.calls)  # streams do lado lento foram fechadas ao cancelar
    assert any(isinstance(e, TimerEvent) for e in bc.history)
    assert isinstance(bc.history[0], RoundStart)


async def test_miss_opens_counter_and_hit_gets_bonus(settings, small_bank):
    left = FakeProvider([FakeTurn(BAD_CODE, delay_s=0.01), FakeTurn(GOOD_CODE, delay_s=5.0)])
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.3)])
    runner, bc = make_round(settings, small_bank, left, right, round_seconds=1.2)
    await runner.run()
    rs = results(bc)
    miss = rs[0]
    assert miss.side == "left" and not miss.passed and miss.opens_counter and miss.category == "wrong_answer"
    hit = next(r for r in rs if r.passed)
    assert hit.side == "right" and hit.counter
    base = {"easy": 10, "medium": 20, "hard": 35}[hit.difficulty]
    assert hit.damage == int(base * 1.5)
    stunned = [e for e in bc.history if isinstance(e, FighterStatusEvent) and e.status == "stunned"]
    assert stunned and stunned[0].side == "left"


async def test_fail_then_succeed_on_retry_clears_counter(settings, small_bank):
    left = FakeProvider([FakeTurn(BAD_CODE), FakeTurn(GOOD_CODE)])
    right = FakeProvider([FakeTurn(BAD_CODE, delay_s=0.2), FakeTurn(GOOD_CODE, delay_s=5.0)])
    runner, bc = make_round(settings, small_bank, left, right, round_seconds=1.5)
    await runner.run()
    rs = results(bc)
    first_hit = next(r for r in rs if r.passed)
    assert first_hit.side == "left" and first_hit.attempt == 2
    # o counter do left foi aberto pelo erro do right? right errou DEPOIS do erro do left mas antes do acerto
    # do left (0.2s < 0.5s de stun), então o acerto do left vale 1.5x
    assert first_hit.counter
    assert first_hit.damage == int({"easy": 10, "medium": 20, "hard": 35}[first_hit.difficulty] * 1.5)
    assert not runner.fighters[Side.LEFT].counter_ready and not runner.fighters[Side.RIGHT].counter_ready


async def test_both_valid_second_is_late(settings, small_bank):
    sandbox = FakeSandbox(delay_s=0.3)
    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.01)])
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=0.02)])
    runner, bc = make_round(settings, small_bank, left, right, sandbox=sandbox, round_seconds=0.6)

    # Força os dois resultados na fila antes do árbitro ler: enfileira manualmente
    async def flood():
        await asyncio.sleep(0.05)
        from llmarena.domain.models import GolpeResult

        await runner.results.put(GolpeResult(Side.LEFT, 0, 1, True, Category.OK, "ok", 100, GOOD_CODE))
        await runner.results.put(GolpeResult(Side.RIGHT, 0, 1, True, Category.OK, "ok", 101, GOOD_CODE))

    asyncio.create_task(flood())
    await runner.run()
    rs = [r for r in results(bc) if r.seq == 0]
    assert rs[0].side == "left" and rs[0].passed and not rs[0].late and rs[0].damage > 0
    late = [r for r in rs if r.late]
    assert late and late[0].side == "right" and late[0].damage == 0


async def test_api_error_is_miss_without_counter(settings, small_bank):
    left = FakeProvider([FakeTurn("", error=RateLimitedError("429")), FakeTurn(GOOD_CODE, delay_s=5.0)])
    right = FakeProvider([FakeTurn("", error=ProviderError("boom")), FakeTurn(GOOD_CODE, delay_s=5.0)])
    runner, bc = make_round(settings, small_bank, left, right, round_seconds=1.0)
    outcome = await runner.run()
    rs = results(bc)
    assert rs and all(r.category == "api_error" and not r.opens_counter for r in rs)
    assert outcome.winner is None and outcome.hp == {Side.LEFT: 100, Side.RIGHT: 100}


async def test_no_code_and_forbidden_import_are_misses(settings, small_bank):
    left = FakeProvider(
        [FakeTurn("I refuse to answer."), FakeTurn("import os\n" + GOOD_CODE), FakeTurn(GOOD_CODE)]
    )
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=5.0)])
    runner, bc = make_round(settings, small_bank, left, right, round_seconds=2.5)
    await runner.run()
    cats = [r.category for r in results(bc) if r.side == "left"][:3]
    assert cats == ["no_code", "forbidden_import", "ok"]
    # o feedback do erro vai para o prompt seguinte
    assert "previous attempt failed" in left.calls[1]["user"]


async def test_ko_ends_round_early(settings, small_bank):
    left = FakeProvider([FakeTurn(GOOD_CODE)])
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=5.0)])
    runner, bc = make_round(settings, small_bank, left, right, round_seconds=30.0, max_golpes_per_round=50)
    t0 = asyncio.get_running_loop().time()
    outcome = await runner.run()
    assert outcome.reason == "ko" and outcome.hp[Side.RIGHT] == 0 and outcome.winner is Side.LEFT
    assert asyncio.get_running_loop().time() - t0 < 20
    assert bc.history[-1].status == "ko" or any(
        isinstance(e, FighterStatusEvent) and e.status == "ko" and e.side == "right" for e in bc.history
    )
    assert isinstance([e for e in bc.history if isinstance(e, HpUpdate)][-1], HpUpdate)


async def test_stale_seq_is_ignored(settings, small_bank):
    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=5.0)])
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=5.0)])
    runner, bc = make_round(settings, small_bank, left, right, round_seconds=0.5)

    async def stale():
        from llmarena.domain.models import GolpeResult

        await asyncio.sleep(0.05)
        await runner.results.put(GolpeResult(Side.LEFT, 99, 1, True, Category.OK, "ok", 1, GOOD_CODE))

    asyncio.create_task(stale())
    outcome = await runner.run()
    assert not results(bc) and outcome.winner is None


async def test_max_golpes_exhausts_fighter(settings, small_bank):
    left = FakeProvider([FakeTurn(BAD_CODE)])
    right = FakeProvider([FakeTurn(BAD_CODE, delay_s=0.1)])
    runner, bc = make_round(
        settings,
        small_bank,
        left,
        right,
        round_seconds=8.0,
        max_golpes_per_round=2,
        max_attempts_per_challenge=2,
    )
    t0 = asyncio.get_running_loop().time()
    outcome = await runner.run()
    assert runner.fighters[Side.LEFT].golpes == 2 and runner.fighters[Side.RIGHT].golpes == 2
    assert any(isinstance(e, FighterStatusEvent) and e.status == "exhausted" for e in bc.history)
    assert asyncio.get_running_loop().time() - t0 < 6  # terminou antes do deadline: ninguém podia mais lutar
    assert outcome.winner is None


async def test_real_sandbox_end_to_end(settings, small_bank):
    left = FakeProvider([FakeTurn("```python\n" + GOOD_CODE + "```")])
    right = FakeProvider([FakeTurn("def plus(a, b):\n    return a - b\n")])
    runner, bc = make_round(
        settings,
        small_bank,
        left,
        right,
        sandbox=SubprocessSandbox(),
        round_seconds=3.0,
        max_golpes_per_round=1,
    )
    await runner.run()
    rs = results(bc)
    assert any(r.side == "left" and r.passed for r in rs)
    assert any(r.side == "right" and r.category == "wrong_answer" for r in rs)


async def test_match_best_of_three(settings, small_bank):
    left = FakeProvider([FakeTurn(GOOD_CODE)])
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=5.0)])
    settings.round_seconds = 30.0
    settings.max_golpes_per_round = 50
    bc = Broadcaster()
    runner = MatchRunner(
        match_id="m1",
        specs=SPECS,
        providers={Side.LEFT: left, Side.RIGHT: right},
        model_extra={Side.LEFT: None, Side.RIGHT: None},
        bank=small_bank,
        settings=settings,
        broadcaster=bc,
        sandbox=FakeSandbox(),
    )
    await runner.run()
    ends = [e for e in bc.history if isinstance(e, RoundEnd)]
    assert len(ends) == 2 and all(e.winner == "left" and e.reason == "ko" for e in ends)
    end = bc.history[-1]
    assert isinstance(end, MatchEnd) and end.winner == "left" and end.score == {"left": 2, "right": 0}
    assert end.stats["left"].hits >= 6 and end.stats["left"].avg_hit_ms is not None
    assert bc.view is not None and bc.view.status == "finished" and bc.view.winner == "left"


async def test_match_abort_publishes_fatal_error(settings, small_bank):
    left = FakeProvider([FakeTurn(GOOD_CODE, delay_s=10.0)])
    right = FakeProvider([FakeTurn(GOOD_CODE, delay_s=10.0)])
    settings.round_seconds = 30.0
    bc = Broadcaster()
    runner = MatchRunner(
        match_id="m2",
        specs=SPECS,
        providers={Side.LEFT: left, Side.RIGHT: right},
        model_extra={Side.LEFT: None, Side.RIGHT: None},
        bank=small_bank,
        settings=settings,
        broadcaster=bc,
        sandbox=FakeSandbox(),
    )
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    err = bc.history[-1]
    assert isinstance(err, ErrorEvent) and err.fatal and bc.view.status == "aborted"
