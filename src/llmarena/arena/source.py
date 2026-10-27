"""De onde vêm os desafios de um round: o banco fixo ou o juiz (problema do usuário, níveis crescentes)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Protocol

from llmarena.arena.judge import GeneratedProblem, Judge, JudgeError
from llmarena.challenges.schema import Challenge, ChallengeBank
from llmarena.logging import get_logger
from llmarena.protocol import JudgeEvent
from llmarena.ws import Broadcaster

log = get_logger(__name__)


class ChallengeSource(Protocol):
    async def next(self) -> Challenge: ...

    def new_round(self) -> None: ...

    async def close(self) -> None: ...


class BankSource:
    def __init__(self, bank: ChallengeBank, rng: random.Random) -> None:
        self.bank = bank
        self.rng = rng
        self.used: set[str] = set()

    def new_round(self) -> None:
        self.used = set()

    async def next(self) -> Challenge:
        c = self.bank.draw(self.used, self.rng)
        self.used.add(c.id)
        return c

    async def close(self) -> None:
        pass


class CustomSource:
    """Entrega a variação atual e já pede ao juiz a próxima (nível + 1) em segundo plano."""

    def __init__(
        self,
        *,
        judge: Judge,
        problem: GeneratedProblem,
        broadcaster: Broadcaster,
        fallback: BankSource,
        on_generated: Callable[[Challenge], Awaitable[None]] | None = None,
    ) -> None:
        self.judge = judge
        self.problem = problem
        self.bc = broadcaster
        self.fallback = fallback
        self.on_generated = on_generated
        self._ready: Challenge | None = problem.challenge
        self._last: Challenge = problem.challenge
        self._task: asyncio.Task[Challenge | None] | None = None
        self.generated: list[Challenge] = [problem.challenge]

    def new_round(self) -> None:
        self.fallback.new_round()

    async def _generate(self, level: int, previous: Challenge) -> Challenge | None:
        self.bc.publish(
            JudgeEvent(status="generating", level=level, message=f"Juiz preparando o nível {level}…")
        )
        try:
            ch = await self.judge.generate(self.problem.statement_src, level=level, previous=previous)
        except JudgeError as e:
            log.warning("judge.failed", level=level, error=str(e)[:200])
            self.bc.publish(
                JudgeEvent(status="failed", level=level, message="Juiz falhou; usando um desafio do banco")
            )
            return None
        self.generated.append(ch)
        if self.on_generated is not None:
            try:
                await self.on_generated(ch)
            except Exception:  # noqa: BLE001
                log.exception("judge.persist_failed")
        self.bc.publish(JudgeEvent(status="ready", level=level, message=f"Nível {level} pronto"))
        return ch

    async def next(self) -> Challenge:
        if self._ready is None:
            ch: Challenge | None = None
            if self._task is not None:
                ch = await self._task
            if ch is None:
                ch = await self.fallback.next()
            self._ready = ch
        current = self._ready
        self._ready = None
        if current.custom:
            self._last = current
        self._task = asyncio.create_task(
            self._generate(self._last.level + 1, self._last), name="judge-prefetch"
        )
        return current

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.wait([self._task], timeout=1.0)
