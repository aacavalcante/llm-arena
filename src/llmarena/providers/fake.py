from __future__ import annotations

import asyncio
import random
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from llmarena.challenges.schema import ChallengeBank
from llmarena.providers.base import Provider


@dataclass
class FakeTurn:
    code: str
    delay_s: float = 0.0  # antes do primeiro token
    token_delay_s: float = 0.0  # entre tokens
    error: Exception | None = None  # lançado em vez de responder
    chunk: int = 12


class FakeProvider(Provider):
    """Provedor roteirizado para testes: cada chamada consome o próximo FakeTurn (o último repete)."""

    name = "fake"

    def __init__(self, turns: list[FakeTurn] | Callable[[str, str, str], FakeTurn]) -> None:
        self._turns = turns
        self._i = 0
        self.calls: list[dict[str, Any]] = []
        self.closed = 0

    def _next(self, system: str, user: str, model: str) -> FakeTurn:
        if callable(self._turns):
            return self._turns(system, user, model)
        turn = self._turns[min(self._i, len(self._turns) - 1)]
        self._i += 1
        return turn

    async def stream_completion(
        self, *, system: str, user: str, model: str, max_tokens: int, extra: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        self.calls.append({"model": model, "user": user})
        turn = self._next(system, user, model)
        try:
            if turn.delay_s:
                await asyncio.sleep(turn.delay_s)
            if turn.error is not None:
                raise turn.error
            for i in range(0, len(turn.code), turn.chunk):
                yield turn.code[i : i + turn.chunk]
                if turn.token_delay_s:
                    await asyncio.sleep(turn.token_delay_s)
        finally:
            self.closed += 1


_TITLE_RE = re.compile(r"^Task: (.+)$", re.MULTILINE)

DEMO_MODELS: dict[str, dict[str, float]] = {
    "demo/relampago": {"delay": 0.3, "token": 0.004, "accuracy": 0.95},
    "demo/veterano": {"delay": 1.0, "token": 0.015, "accuracy": 0.9},
    "demo/lento": {"delay": 2.5, "token": 0.03, "accuracy": 0.85},
    "demo/atrapalhado": {"delay": 0.5, "token": 0.01, "accuracy": 0.5},
}


class DemoProvider(Provider):
    """Modo demo sem chaves: responde com a solução de referência do banco (às vezes errada de propósito)."""

    name = "demo"

    def __init__(self, bank: ChallengeBank, seed: int | None = None) -> None:
        self._bank = bank
        self._rng = random.Random(seed)

    async def stream_completion(
        self, *, system: str, user: str, model: str, max_tokens: int, extra: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        profile = DEMO_MODELS.get(model, DEMO_MODELS["demo/veterano"])
        m = _TITLE_RE.search(user)
        challenge = self._bank.by_title(m.group(1).strip()) if m else None
        code = (
            challenge.reference if challenge and challenge.reference else "def unknown():\n    return None\n"
        )
        if self._rng.random() > profile["accuracy"]:
            code = (
                code.rstrip()
                + "\n\n"
                + f"{challenge.function if challenge else 'unknown'} = lambda *a, **k: None\n"
            )
        await asyncio.sleep(profile["delay"] * self._rng.uniform(0.7, 1.3))
        for i in range(0, len(code), 8):
            yield code[i : i + 8]
            await asyncio.sleep(profile["token"])
