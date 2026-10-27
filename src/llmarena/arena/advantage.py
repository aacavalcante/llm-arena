"""Modo "vantagem" (problema personalizado): quem resolve primeiro ganha o direito de golpear.

Cada tentativa falha do oponente vira um golpe livre do detentor da vantagem. Quando o oponente também
resolve, a fase acaba e o juiz entrega uma variação mais difícil. Sem contra-ataque neste modo.
"""

from __future__ import annotations

import asyncio

from llmarena.arena.round import RoundRunner
from llmarena.domain.models import Category, FighterStatus, GolpeResult, Side
from llmarena.domain.rules import damage_for
from llmarena.protocol import HpUpdate


class AdvantageRoundRunner(RoundRunner):
    holder: Side | None = None

    def on_phase_start(self) -> None:
        if self.holder is not None and self.fighters[self.holder].status is FighterStatus.ADVANTAGE:
            self._status(self.holder, FighterStatus.IDLE)
        self.holder = None

    async def _judge(self, r: GolpeResult, tasks: dict[Side, asyncio.Task[None]]) -> str | None:
        assert self.challenge is not None
        me = self.fighters[r.side]
        opp = self.fighters[r.side.opponent]
        me.golpes += 1

        if r.passed:
            if self.holder is None:
                # Primeiro a resolver: golpe normal + vantagem; o oponente continua tentando
                r.damage = damage_for(self.challenge.difficulty, False)
                me.hits += 1
                me.hit_ms.append(r.ms)
                opp.hp = max(0, opp.hp - r.damage)
                self.holder = r.side
                self._emit_result(r)
                self.bc.publish(HpUpdate(**self._hp()))
                self._status(r.side, FighterStatus.ADVANTAGE)
                await self._persist(r)
                task = tasks.get(r.side)
                if task is not None:
                    task.cancel()
                if opp.hp == 0:
                    self._status(r.side.opponent, FighterStatus.KO)
                    return "ko"
                return None
            # O oponente também resolveu: fim da sangria, próxima variação
            r.late = True
            self._emit_result(r)
            self._status(r.side, FighterStatus.IDLE)
            self._status(self.holder, FighterStatus.IDLE)
            await self._persist(r)
            self.holder = None
            return "hit"

        # Golpe perdido
        me.misses += 1
        r.opens_counter = False
        self._emit_result(r)
        self._status(r.side, FighterStatus.STUNNED)
        await self._persist(r)
        if self.holder is r.side.opponent and r.category is not Category.API_ERROR:
            holder = self.fighters[self.holder]
            free = GolpeResult(
                side=self.holder,
                seq=r.seq,
                attempt=r.attempt,
                passed=True,
                category=Category.ADVANTAGE,
                detail=f"golpe livre: o oponente errou ({r.category.value})",
                ms=r.ms,
                tests_passed=r.tests_passed,
                tests_total=r.tests_total,
            )
            free.damage = damage_for(self.challenge.difficulty, False)
            holder.hits += 1
            me.hp = max(0, me.hp - free.damage)
            self._emit_result(free)
            self.bc.publish(HpUpdate(**self._hp()))
            await self._persist(free)
            if me.hp == 0:
                self._status(r.side, FighterStatus.KO)
                return "ko"
        if me.golpes >= self.settings.max_golpes_per_round:
            task = tasks.get(r.side)
            if task is not None:
                task.cancel()
            self._status(r.side, FighterStatus.EXHAUSTED)
        return None
