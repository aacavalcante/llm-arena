from __future__ import annotations

from llmarena.domain.models import Difficulty, Side

DAMAGE: dict[Difficulty, int] = {Difficulty.EASY: 10, Difficulty.MEDIUM: 20, Difficulty.HARD: 35}
COUNTER_MULTIPLIER = 1.5


def damage_for(difficulty: Difficulty, counter: bool) -> int:
    base = DAMAGE[difficulty]
    return int(base * COUNTER_MULTIPLIER) if counter else base


def round_winner(hp_left: int, hp_right: int) -> Side | None:
    if hp_left > hp_right:
        return Side.LEFT
    if hp_right > hp_left:
        return Side.RIGHT
    return None


def match_winner(score: dict[Side, int]) -> Side | None:
    return round_winner(score[Side.LEFT], score[Side.RIGHT])


def rounds_needed(total_rounds: int) -> int:
    """Vitórias necessárias para fechar a partida antes do fim (2 numa melhor de 3)."""
    return total_rounds // 2 + 1
