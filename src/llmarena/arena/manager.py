from __future__ import annotations

import asyncio
import secrets

from llmarena.arena.match import MatchRunner
from llmarena.challenges.schema import ChallengeBank
from llmarena.domain.models import Side
from llmarena.logging import get_logger
from llmarena.persistence.db import Db
from llmarena.protocol import MatchView
from llmarena.providers.registry import ProviderRegistry
from llmarena.sandbox.executor import Sandbox
from llmarena.settings import Settings
from llmarena.ws import Broadcaster

log = get_logger(__name__)


class MatchRunningError(Exception):
    pass


class UnknownModelError(Exception):
    pass


class MatchManager:
    """Uma partida por vez."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        bank: ChallengeBank,
        settings: Settings,
        broadcaster: Broadcaster,
        sandbox: Sandbox,
        db: Db | None,
    ) -> None:
        self.registry = registry
        self.bank = bank
        self.settings = settings
        self.bc = broadcaster
        self.sandbox = sandbox
        self.db = db
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def view(self) -> MatchView | None:
        return self.bc.view

    def start(self, left: tuple[str, str], right: tuple[str, str]) -> str:
        if self.running:
            raise MatchRunningError("já existe uma partida em andamento")
        try:
            specs = {
                Side.LEFT: self.registry.catalog.spec(*left),
                Side.RIGHT: self.registry.catalog.spec(*right),
            }
            providers = {s: self.registry.get(specs[s].provider) for s in Side}
        except KeyError as e:
            raise UnknownModelError(str(e)) from e
        extra = {s: (self.registry.catalog.find(specs[s].provider, specs[s].model) or None) for s in Side}
        match_id = secrets.token_hex(6)
        runner = MatchRunner(
            match_id=match_id,
            specs=specs,
            providers=providers,
            model_extra={s: (e.extra or None) if e else None for s, e in extra.items()},
            bank=self.bank,
            settings=self.settings,
            broadcaster=self.bc,
            sandbox=self.sandbox,
            db=self.db,
        )
        self._task = asyncio.create_task(runner.run(), name=f"match-{match_id}")
        log.info("match.started", match_id=match_id, left=specs[Side.LEFT], right=specs[Side.RIGHT])
        return match_id

    async def abort(self) -> bool:
        if not self.running:
            return False
        assert self._task is not None
        self._task.cancel()
        await asyncio.wait([self._task], timeout=5.0)
        return True

    async def shutdown(self) -> None:
        await self.abort()
