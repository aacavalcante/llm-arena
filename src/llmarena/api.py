from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from llmarena.arena.manager import MatchManager, MatchRunningError, UnknownModelError
from llmarena.protocol import MatchView

router = APIRouter()


class SideChoice(BaseModel):
    provider: str
    model: str


class NewMatch(BaseModel):
    left: SideChoice
    right: SideChoice


def _manager(request: Request) -> MatchManager:
    return request.app.state.manager


@router.get("/models")
async def list_models(request: Request) -> dict:
    registry = request.app.state.registry
    return {
        "providers": [
            {
                "name": p.name,
                "display_name": p.display_name,
                "models": [{"id": m.id, "display_name": m.display_name} for m in p.models],
            }
            for p in registry.available()
        ]
    }


@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "ok": True,
        "match_running": _manager(request).running,
        "clients": request.app.state.broadcaster.clients,
        "sandbox_network_isolated": getattr(request.app.state.sandbox, "network_isolated", None),
    }


@router.post("/matches", status_code=201)
async def create_match(body: NewMatch, request: Request) -> dict:
    try:
        match_id = _manager(request).start(
            (body.left.provider, body.left.model), (body.right.provider, body.right.model)
        )
    except MatchRunningError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except UnknownModelError as e:
        raise HTTPException(status_code=400, detail=f"modelo desconhecido: {e}") from e
    return {"match_id": match_id}


@router.get("/matches/current")
async def current_match(request: Request) -> MatchView:
    view = _manager(request).view
    if view is None or not _manager(request).running:
        raise HTTPException(status_code=404, detail="nenhuma partida em andamento")
    return view


@router.delete("/matches/current", status_code=204)
async def abort_match(request: Request) -> Response:
    if not await _manager(request).abort():
        raise HTTPException(status_code=404, detail="nenhuma partida em andamento")
    return Response(status_code=204)


@router.get("/matches")
async def recent_matches(request: Request, limit: int = 20) -> dict:
    db = request.app.state.db
    if db is None:
        return {"matches": []}
    return {"matches": await asyncio.to_thread(db.recent_matches, min(limit, 100))}


@router.get("/matches/{match_id}/golpes")
async def match_golpes(match_id: str, request: Request) -> dict:
    db = request.app.state.db
    if db is None:
        return {"golpes": []}
    return {"golpes": await asyncio.to_thread(db.match_golpes, match_id)}


@router.get("/leaderboard")
async def leaderboard(request: Request) -> dict:
    db = request.app.state.db
    if db is None:
        return {"rows": []}
    return {"rows": await asyncio.to_thread(db.leaderboard)}
