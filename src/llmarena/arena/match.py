from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from typing import Any

from llmarena.arena.round import RoundRunner
from llmarena.challenges.schema import Challenge, ChallengeBank
from llmarena.domain.models import FighterSpec, FighterState, GolpeResult, Side
from llmarena.domain.rules import COUNTER_MULTIPLIER, DAMAGE, match_winner, rounds_needed
from llmarena.logging import get_logger
from llmarena.persistence.db import Db
from llmarena.protocol import (
    ErrorEvent,
    FighterSpecView,
    MatchEnd,
    MatchStart,
    RoundEnd,
    RulesView,
    SideStats,
)
from llmarena.providers.base import Provider
from llmarena.sandbox.executor import Sandbox
from llmarena.settings import Settings
from llmarena.ws import Broadcaster

log = get_logger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class MatchRunner:
    def __init__(
        self,
        *,
        match_id: str,
        specs: dict[Side, FighterSpec],
        providers: dict[Side, Provider],
        model_extra: dict[Side, dict[str, Any] | None],
        bank: ChallengeBank,
        settings: Settings,
        broadcaster: Broadcaster,
        sandbox: Sandbox,
        db: Db | None = None,
        seed: int | str | None = None,
    ) -> None:
        self.match_id = match_id
        self.specs = specs
        self.providers = providers
        self.model_extra = model_extra
        self.bank = bank
        self.settings = settings
        self.bc = broadcaster
        self.sandbox = sandbox
        self.db = db
        self.rng = random.Random(seed if seed is not None else match_id)
        self.score: dict[Side, int] = {Side.LEFT: 0, Side.RIGHT: 0}
        self.stats: dict[Side, dict[str, Any]] = {s: {"hits": 0, "misses": 0, "hit_ms": []} for s in Side}

    def rules(self) -> RulesView:
        return RulesView(
            hp=self.settings.hp,
            rounds=self.settings.rounds,
            round_seconds=self.settings.round_seconds,
            damage={k.value: v for k, v in DAMAGE.items()},
            counter_multiplier=COUNTER_MULTIPLIER,
        )

    async def _on_golpe(self, r: GolpeResult, challenge: Challenge, spec: FighterSpec) -> None:
        if self.db is not None:
            await asyncio.to_thread(self.db.record_golpe, self.match_id, self.round_no, r, challenge, spec)

    def _accumulate(self, fighters: dict[Side, FighterState]) -> None:
        for s, f in fighters.items():
            self.stats[s]["hits"] += f.hits
            self.stats[s]["misses"] += f.misses
            self.stats[s]["hit_ms"].extend(f.hit_ms)

    def _score_view(self) -> dict[str, int]:
        return {s.value: self.score[s] for s in Side}

    async def run(self) -> None:
        self.bc.reset()
        self.bc.publish(
            MatchStart(
                match_id=self.match_id,
                left=FighterSpecView(**vars(self.specs[Side.LEFT])),
                right=FighterSpecView(**vars(self.specs[Side.RIGHT])),
                rules=self.rules(),
            )
        )
        if self.db is not None:
            await asyncio.to_thread(
                self.db.start_match, self.match_id, self.specs, self.rules().model_dump_json(), _now()
            )
        winner_str = "aborted"
        try:
            need = rounds_needed(self.settings.rounds)
            for round_no in range(1, self.settings.rounds + 1):
                self.round_no = round_no
                runner = RoundRunner(
                    round_no=round_no,
                    specs=self.specs,
                    providers=self.providers,
                    model_extra=self.model_extra,
                    bank=self.bank,
                    settings=self.settings,
                    broadcaster=self.bc,
                    sandbox=self.sandbox,
                    rng=self.rng,
                    score=self.score,
                    on_golpe=self._on_golpe,
                )
                outcome = await runner.run()
                self._accumulate(outcome.fighters)
                if outcome.winner is not None:
                    self.score[outcome.winner] += 1
                self.bc.publish(
                    RoundEnd(
                        round_no=round_no,
                        reason=outcome.reason,  # type: ignore[arg-type]
                        winner=outcome.winner.value if outcome.winner else "draw",
                        hp={s.value: outcome.hp[s] for s in Side},
                        score=self._score_view(),
                    )
                )
                if self.db is not None:
                    await asyncio.to_thread(self.db.record_round, self.match_id, outcome)
                if max(self.score.values()) >= need:
                    break
                if round_no < self.settings.rounds:
                    await asyncio.sleep(self.settings.intermission_seconds)
            winner = match_winner(self.score)
            winner_str = winner.value if winner else "draw"
            self.bc.publish(
                MatchEnd(
                    match_id=self.match_id,
                    winner=winner_str,
                    score=self._score_view(),  # type: ignore[arg-type]
                    stats={
                        s.value: SideStats(
                            hits=st["hits"],
                            misses=st["misses"],
                            avg_hit_ms=int(sum(st["hit_ms"]) / len(st["hit_ms"])) if st["hit_ms"] else None,
                        )
                        for s, st in self.stats.items()
                    },
                )
            )
        except asyncio.CancelledError:
            self.bc.publish(ErrorEvent(message="Partida abortada", fatal=True))
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("match.crashed", match_id=self.match_id)
            self.bc.publish(ErrorEvent(message=f"Erro interno na partida: {e!r}"[:300], fatal=True))
        finally:
            if self.db is not None:
                try:
                    await asyncio.shield(
                        asyncio.to_thread(self.db.finish_match, self.match_id, winner_str, self.score, _now())
                    )
                except Exception:  # noqa: BLE001
                    log.exception("match.persist_failed")
