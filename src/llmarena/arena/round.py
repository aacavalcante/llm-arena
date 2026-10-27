from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

from llmarena.arena.fighter import FighterTask
from llmarena.challenges.schema import Challenge, ChallengeBank
from llmarena.domain.models import (
    Category,
    FighterSpec,
    FighterState,
    FighterStatus,
    GolpeResult,
    RoundOutcome,
    Side,
)
from llmarena.domain.rules import damage_for, round_winner
from llmarena.logging import get_logger
from llmarena.protocol import (
    ChallengeEvent,
    ChallengeView,
    FighterStatusEvent,
    GolpeResultEvent,
    HpUpdate,
    RoundStart,
    TimerEvent,
)
from llmarena.providers.base import Provider
from llmarena.sandbox.executor import Sandbox
from llmarena.settings import Settings
from llmarena.ws import Broadcaster

log = get_logger(__name__)

GolpeSink = Callable[[GolpeResult, Challenge, FighterSpec], Awaitable[None]]


class RoundRunner:
    """O árbitro: único coroutine que altera o estado do round. Consome a fila de resultados."""

    def __init__(
        self,
        *,
        round_no: int,
        specs: dict[Side, FighterSpec],
        providers: dict[Side, Provider],
        model_extra: dict[Side, dict[str, Any] | None],
        bank: ChallengeBank,
        settings: Settings,
        broadcaster: Broadcaster,
        sandbox: Sandbox,
        rng: random.Random,
        score: dict[Side, int],
        on_golpe: GolpeSink | None = None,
    ) -> None:
        self.round_no = round_no
        self.specs = specs
        self.providers = providers
        self.model_extra = model_extra
        self.bank = bank
        self.settings = settings
        self.bc = broadcaster
        self.sandbox = sandbox
        self.rng = rng
        self.score = score
        self.on_golpe = on_golpe
        self.fighters: dict[Side, FighterState] = {
            s: FighterState(spec=specs[s], hp=settings.hp) for s in Side
        }
        self.results: asyncio.Queue[GolpeResult] = asyncio.Queue()
        self.seq = 0
        self.used_ids: set[str] = set()
        self.challenge: Challenge | None = None

    # ---- helpers -------------------------------------------------------------------------------------

    def _hp(self) -> dict[str, int]:
        return {s.value: self.fighters[s].hp for s in Side}

    def _status(self, side: Side, status: FighterStatus) -> None:
        self.fighters[side].status = status
        self.bc.publish(FighterStatusEvent(side=side.value, status=status.value))

    def _remaining(self) -> float:
        return max(0.0, self.deadline - asyncio.get_running_loop().time())

    async def _timer(self) -> None:
        while True:
            self.bc.publish(TimerEvent(remaining_ms=int(self._remaining() * 1000)))
            await asyncio.sleep(1.0)

    def _emit_result(self, r: GolpeResult) -> None:
        assert self.challenge is not None
        self.bc.publish(
            GolpeResultEvent(
                side=r.side.value,
                seq=r.seq,
                attempt=r.attempt,
                passed=r.passed,
                category=r.category.value,
                detail=r.detail,
                ms=r.ms,
                damage=r.damage,
                counter=r.counter,
                opens_counter=r.opens_counter,
                late=r.late,
                tests_passed=r.tests_passed,
                tests_total=r.tests_total,
                difficulty=self.challenge.difficulty.value,
            )
        )

    async def _persist(self, r: GolpeResult) -> None:
        if self.on_golpe is not None and self.challenge is not None:
            try:
                await self.on_golpe(r, self.challenge, self.specs[r.side])
            except Exception:  # noqa: BLE001
                log.exception("round.persist_failed")

    def _spawn(self, side: Side, challenge: Challenge, dispatched_at: float) -> asyncio.Task[None]:
        task = FighterTask(
            side=side,
            provider=self.providers[side],
            model=self.specs[side].model,
            model_extra=self.model_extra.get(side),
            challenge=challenge,
            seq=self.seq,
            dispatched_at=dispatched_at,
            results=self.results,
            settings=self.settings,
            broadcaster=self.bc,
            sandbox=self.sandbox,
        )
        return asyncio.create_task(task.run(), name=f"fighter-{side.value}-{self.seq}")

    @staticmethod
    async def _cancel(tasks: dict[Side, asyncio.Task[None]]) -> None:
        for t in tasks.values():
            t.cancel()
        if tasks:
            await asyncio.wait(list(tasks.values()), timeout=2.0)

    def _drain_late(self) -> list[GolpeResult]:
        late: list[GolpeResult] = []
        while not self.results.empty():
            r = self.results.get_nowait()
            if r.seq == self.seq and r.passed:
                r.late = True
                late.append(r)
        return late

    # ---- loop principal ------------------------------------------------------------------------------

    async def run(self) -> RoundOutcome:
        loop = asyncio.get_running_loop()
        started = loop.time()
        self.deadline = started + self.settings.round_seconds
        self.bc.publish(
            RoundStart(
                round_no=self.round_no,
                hp=self._hp(),
                score={s.value: self.score[s] for s in Side},
                remaining_ms=int(self.settings.round_seconds * 1000),
            )
        )
        timer = asyncio.create_task(self._timer(), name=f"timer-{self.round_no}")
        tasks: dict[Side, asyncio.Task[None]] = {}
        reason = "timeout"
        try:
            while self._remaining() > 0:
                active = [s for s in Side if not self.fighters[s].exhausted]
                if not active:
                    break
                self.challenge = self.bank.draw(self.used_ids, self.rng)
                self.used_ids.add(self.challenge.id)
                dispatched_at = loop.time()
                self.bc.publish(
                    ChallengeEvent(
                        challenge=ChallengeView(
                            seq=self.seq,
                            id=self.challenge.id,
                            title=self.challenge.title,
                            difficulty=self.challenge.difficulty.value,
                            statement=self.challenge.statement,
                            signature=self.challenge.signature,
                        )
                    )
                )
                tasks = {s: self._spawn(s, self.challenge, dispatched_at) for s in active}
                phase_done = await self._phase(tasks)
                await self._cancel(tasks)
                tasks = {}
                if phase_done == "ko":
                    reason = "ko"
                    break
                self.seq += 1
        finally:
            timer.cancel()
            await self._cancel(tasks)
        hp = {s: self.fighters[s].hp for s in Side}
        winner = round_winner(hp[Side.LEFT], hp[Side.RIGHT])
        for s in Side:
            if self.fighters[s].hp == 0:
                self._status(s, FighterStatus.KO)
            elif self.fighters[s].status is not FighterStatus.EXHAUSTED:
                self._status(s, FighterStatus.IDLE)
        return RoundOutcome(
            round_no=self.round_no,
            winner=winner,
            reason=reason,
            hp=hp,
            duration_ms=int((loop.time() - started) * 1000),
            fighters=self.fighters,
        )

    async def _phase(self, tasks: dict[Side, asyncio.Task[None]]) -> str:
        """Roda uma fase (um desafio). Retorna 'hit', 'ko' ou 'exhausted' (ninguém mais pode tentar)."""
        assert self.challenge is not None
        while True:
            remaining = self._remaining()
            if remaining <= 0:
                return "timeout"
            pending = [t for t in tasks.values() if not t.done()]
            if not pending and self.results.empty():
                return "exhausted"  # todos esgotaram as tentativas neste desafio: novo desafio
            getter: asyncio.Task[GolpeResult] = asyncio.create_task(self.results.get())
            done, _ = await asyncio.wait(
                [getter, *pending], timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if getter not in done:
                getter.cancel()
                continue
            r = getter.result()
            if r.seq != self.seq:
                continue
            outcome = await self._judge(r, tasks)
            if outcome is not None:
                return outcome

    async def _judge(self, r: GolpeResult, tasks: dict[Side, asyncio.Task[None]]) -> str | None:
        assert self.challenge is not None
        me = self.fighters[r.side]
        opp = self.fighters[r.side.opponent]
        me.golpes += 1
        if not r.passed:
            me.misses += 1
            r.opens_counter = r.category is not Category.API_ERROR and not opp.exhausted
            if r.opens_counter:
                opp.counter_ready = True
            self._emit_result(r)
            self._status(r.side, FighterStatus.STUNNED)
            await self._persist(r)
            if me.golpes >= self.settings.max_golpes_per_round:
                task = tasks.get(r.side)
                if task is not None:
                    task.cancel()
                self._status(r.side, FighterStatus.EXHAUSTED)
            return None
        # Golpe válido: o primeiro a chegar acerta
        r.counter = me.counter_ready
        r.damage = damage_for(self.challenge.difficulty, me.counter_ready)
        me.hits += 1
        me.hit_ms.append(r.ms)
        opp.hp = max(0, opp.hp - r.damage)
        me.counter_ready = False
        opp.counter_ready = False
        self._emit_result(r)
        self.bc.publish(HpUpdate(**self._hp()))
        self._status(r.side, FighterStatus.IDLE)
        await self._persist(r)
        await self._cancel(tasks)
        for late in self._drain_late():
            self._emit_result(late)
            await self._persist(late)
        if opp.hp == 0:
            self._status(r.side.opponent, FighterStatus.KO)
            return "ko"
        if me.golpes >= self.settings.max_golpes_per_round:
            self._status(r.side, FighterStatus.EXHAUSTED)  # teto de custo por round
        return "hit"
