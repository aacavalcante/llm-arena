from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from llmarena.api import router
from llmarena.arena.manager import MatchManager
from llmarena.challenges.loader import load_bank
from llmarena.logging import configure_logging, get_logger
from llmarena.persistence.db import Db
from llmarena.providers.registry import ProviderRegistry, load_catalog
from llmarena.sandbox.executor import SandboxLimits, SubprocessSandbox
from llmarena.settings import Settings
from llmarena.ws import Broadcaster, coalesce, drain

log = get_logger(__name__)


def create_app(settings: Settings | None = None, *, db: Db | None | bool = True) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bank = load_bank(settings.bank_path)
        catalog = load_catalog(settings.models_path)
        registry = ProviderRegistry(settings, catalog, bank)
        sandbox = SubprocessSandbox(
            SandboxLimits(
                wall_s=settings.sandbox_wall_s,
                cpu_s=settings.sandbox_cpu_s,
                mem_mb=settings.sandbox_mem_mb,
                netns=settings.sandbox_netns,
                parallel=settings.sandbox_parallel,
            )
        )
        database = Db(settings.db_path) if db is True else (db or None)
        broadcaster = Broadcaster()
        app.state.settings = settings
        app.state.bank = bank
        app.state.registry = registry
        app.state.sandbox = sandbox
        app.state.db = database
        app.state.broadcaster = broadcaster
        app.state.manager = MatchManager(
            registry=registry,
            bank=bank,
            settings=settings,
            broadcaster=broadcaster,
            sandbox=sandbox,
            db=database,
        )
        if not registry.available():
            log.warning(
                "providers.none", hint="defina ANTHROPIC_API_KEY/OPENROUTER_API_KEY ou FAKE_PROVIDERS=true"
            )
        log.info(
            "app.ready", providers=[p.name for p in registry.available()], challenges=len(bank.challenges)
        )
        try:
            yield
        finally:
            await app.state.manager.shutdown()
            await registry.aclose()
            if database is not None:
                database.close()

    app = FastAPI(title="LLM Arena", lifespan=lifespan)
    app.include_router(router, prefix="/api")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        bc: Broadcaster = app.state.broadcaster
        q = bc.subscribe()

        async def sender() -> None:
            await ws.send_text(bc.snapshot().model_dump_json())
            while True:
                for ev in coalesce(await drain(q)):
                    await ws.send_text(ev.model_dump_json())

        async def receiver() -> None:
            while True:
                await ws.receive_text()  # só pings; levanta WebSocketDisconnect ao fechar

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            for t in tasks:
                t.cancel()
            bc.unsubscribe(q)

    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
    return app
