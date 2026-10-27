from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    LEFT = "left"
    RIGHT = "right"

    @property
    def opponent(self) -> Side:
        return Side.RIGHT if self is Side.LEFT else Side.LEFT


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Category(StrEnum):
    OK = "ok"
    WRONG_ANSWER = "wrong_answer"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    SYNTAX_ERROR = "syntax_error"
    FORBIDDEN_IMPORT = "forbidden_import"
    NO_CODE = "no_code"
    API_ERROR = "api_error"
    ADVANTAGE = "advantage"  # golpe livre de quem tem a vantagem (modo custom)


class FighterStatus(StrEnum):
    IDLE = "idle"
    WRITING = "writing"
    TESTING = "testing"
    STUNNED = "stunned"
    EXHAUSTED = "exhausted"
    KO = "ko"
    ADVANTAGE = "advantage"


@dataclass(frozen=True)
class FighterSpec:
    provider: str
    model: str
    display_name: str


@dataclass
class GolpeResult:
    """Resultado de uma tentativa de golpe, produzido pela FighterTask e julgado pelo árbitro."""

    side: Side
    seq: int
    attempt: int
    passed: bool
    category: Category
    detail: str
    ms: int
    code: str = ""
    output_chars: int = 0
    tests_passed: int = 0
    tests_total: int = 0
    # Preenchidos pelo árbitro
    late: bool = False
    damage: int = 0
    counter: bool = False
    opens_counter: bool = False


@dataclass
class FighterState:
    spec: FighterSpec
    hp: int
    counter_ready: bool = False
    status: FighterStatus = FighterStatus.IDLE
    golpes: int = 0
    hits: int = 0
    misses: int = 0
    hit_ms: list[int] = field(default_factory=list)

    @property
    def exhausted(self) -> bool:
        return self.status is FighterStatus.EXHAUSTED


@dataclass
class RoundOutcome:
    round_no: int
    winner: Side | None  # None = empate
    reason: str  # ko | timeout
    hp: dict[Side, int]
    duration_ms: int
    fighters: dict[Side, FighterState]
