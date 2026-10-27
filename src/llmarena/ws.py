from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from llmarena.logging import get_logger
from llmarena.protocol import MatchView, StateSnapshot, TokenEvent, apply_event

log = get_logger(__name__)
QUEUE_SIZE = 2000


class Broadcaster:
    """Registro de espectadores. Cada cliente tem uma fila; quem não acompanha recebe um snapshot novo."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[Any]] = set()
        self.view: MatchView | None = None
        self.history: list[Any] = []  # eventos da partida atual (sem tokens), útil em testes

    def publish(self, ev: Any) -> None:
        self.view = apply_event(self.view, ev)
        if not isinstance(ev, TokenEvent):
            self.history.append(ev)
        for q in list(self._queues):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                # Cliente lento: descarta o acumulado e manda o estado completo
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(self.snapshot())

    def snapshot(self) -> StateSnapshot:
        return StateSnapshot(match=self.view.model_copy(deep=True) if self.view else None)

    def reset(self) -> None:
        self.view = None
        self.history = []

    def subscribe(self) -> asyncio.Queue[Any]:
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Any]) -> None:
        self._queues.discard(q)

    @property
    def clients(self) -> int:
        return len(self._queues)


async def drain(q: asyncio.Queue[Any]) -> list[Any]:
    """Espera o primeiro evento e pega todos os que já estiverem disponíveis."""
    batch = [await q.get()]
    while not q.empty():
        batch.append(q.get_nowait())
    return batch


def coalesce(events: Iterable[Any]) -> list[Any]:
    """Junta tokens consecutivos do mesmo lado/seq num único evento para aliviar o navegador."""
    out: list[Any] = []
    for ev in events:
        last = out[-1] if out else None
        if (
            isinstance(ev, TokenEvent)
            and isinstance(last, TokenEvent)
            and last.side == ev.side
            and last.seq == ev.seq
        ):
            out[-1] = TokenEvent(side=ev.side, seq=ev.seq, text=last.text + ev.text)
        else:
            out.append(ev)
    return out
