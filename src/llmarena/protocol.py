"""Contrato de eventos servidor -> cliente (WebSocket) e vistas REST. Fonte única da verdade."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FighterSpecView(BaseModel):
    provider: str
    model: str
    display_name: str


class RulesView(BaseModel):
    hp: int
    rounds: int
    round_seconds: float
    damage: dict[str, int]
    counter_multiplier: float


class ChallengeView(BaseModel):
    seq: int
    id: str
    title: str
    difficulty: Literal["easy", "medium", "hard"]
    statement: str
    signature: str


class MatchStart(BaseModel):
    type: Literal["match_start"] = "match_start"
    match_id: str
    left: FighterSpecView
    right: FighterSpecView
    rules: RulesView


class RoundStart(BaseModel):
    type: Literal["round_start"] = "round_start"
    round_no: int
    hp: dict[str, int]
    score: dict[str, int]
    remaining_ms: int


class ChallengeEvent(BaseModel):
    type: Literal["challenge"] = "challenge"
    challenge: ChallengeView


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    side: Literal["left", "right"]
    seq: int
    text: str


class FighterStatusEvent(BaseModel):
    type: Literal["fighter_status"] = "fighter_status"
    side: Literal["left", "right"]
    status: Literal["idle", "writing", "testing", "stunned", "exhausted", "ko"]


class GolpeResultEvent(BaseModel):
    type: Literal["golpe_result"] = "golpe_result"
    side: Literal["left", "right"]
    seq: int
    attempt: int
    passed: bool
    category: str
    detail: str
    ms: int
    damage: int
    counter: bool
    opens_counter: bool
    late: bool
    tests_passed: int
    tests_total: int
    difficulty: Literal["easy", "medium", "hard"]


class HpUpdate(BaseModel):
    type: Literal["hp_update"] = "hp_update"
    left: int
    right: int


class RoundEnd(BaseModel):
    type: Literal["round_end"] = "round_end"
    round_no: int
    reason: Literal["ko", "timeout"]
    winner: Literal["left", "right", "draw"]
    hp: dict[str, int]
    score: dict[str, int]


class SideStats(BaseModel):
    hits: int
    misses: int
    avg_hit_ms: int | None


class MatchEnd(BaseModel):
    type: Literal["match_end"] = "match_end"
    match_id: str
    winner: Literal["left", "right", "draw"]
    score: dict[str, int]
    stats: dict[str, SideStats]


class TimerEvent(BaseModel):
    type: Literal["timer"] = "timer"
    remaining_ms: int


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    fatal: bool = False


class MatchView(BaseModel):
    """Estado completo para quem entra no meio da luta."""

    match_id: str
    status: Literal["running", "finished", "aborted"]
    left: FighterSpecView
    right: FighterSpecView
    rules: RulesView
    round_no: int = 0
    score: dict[str, int] = Field(default_factory=lambda: {"left": 0, "right": 0})
    hp: dict[str, int] = Field(default_factory=dict)
    remaining_ms: int = 0
    challenge: ChallengeView | None = None
    fighter_status: dict[str, str] = Field(default_factory=lambda: {"left": "idle", "right": "idle"})
    code: dict[str, str] = Field(default_factory=lambda: {"left": "", "right": ""})
    last_result: dict[str, GolpeResultEvent | None] = Field(
        default_factory=lambda: {"left": None, "right": None}
    )
    winner: Literal["left", "right", "draw"] | None = None


class StateSnapshot(BaseModel):
    type: Literal["state_snapshot"] = "state_snapshot"
    match: MatchView | None


Event = (
    MatchStart
    | RoundStart
    | ChallengeEvent
    | TokenEvent
    | FighterStatusEvent
    | GolpeResultEvent
    | HpUpdate
    | RoundEnd
    | MatchEnd
    | TimerEvent
    | ErrorEvent
    | StateSnapshot
)


def apply_event(view: MatchView | None, ev: Any) -> MatchView | None:
    """Reducer servidor-side: mantém o MatchView atualizado a partir dos eventos publicados."""
    if isinstance(ev, MatchStart):
        return MatchView(
            match_id=ev.match_id,
            status="running",
            left=ev.left,
            right=ev.right,
            rules=ev.rules,
            hp={"left": ev.rules.hp, "right": ev.rules.hp},
            remaining_ms=int(ev.rules.round_seconds * 1000),
        )
    if view is None:
        return None
    match ev:
        case RoundStart():
            view.round_no = ev.round_no
            view.hp = dict(ev.hp)
            view.score = dict(ev.score)
            view.remaining_ms = ev.remaining_ms
            view.challenge = None
            view.code = {"left": "", "right": ""}
            view.last_result = {"left": None, "right": None}
            view.fighter_status = {"left": "idle", "right": "idle"}
        case ChallengeEvent():
            view.challenge = ev.challenge
            view.code = {"left": "", "right": ""}
        case TokenEvent():
            if view.challenge is None or ev.seq == view.challenge.seq:
                view.code[ev.side] = (view.code.get(ev.side, "") + ev.text)[-20000:]
        case FighterStatusEvent():
            view.fighter_status[ev.side] = ev.status
            if ev.status == "writing":
                view.code[ev.side] = ""
        case GolpeResultEvent():
            view.last_result[ev.side] = ev
        case HpUpdate():
            view.hp = {"left": ev.left, "right": ev.right}
        case RoundEnd():
            view.score = dict(ev.score)
            view.hp = dict(ev.hp)
        case MatchEnd():
            view.status = "finished"
            view.winner = ev.winner
            view.score = dict(ev.score)
        case TimerEvent():
            view.remaining_ms = ev.remaining_ms
        case ErrorEvent() if ev.fatal:
            view.status = "aborted"
    return view
