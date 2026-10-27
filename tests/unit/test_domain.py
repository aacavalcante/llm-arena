from __future__ import annotations

import pytest
from pydantic import ValidationError

from llmarena.challenges.schema import Challenge, ChallengeBank, TestCase
from llmarena.domain.codeparse import ensure_function, extract_code
from llmarena.domain.models import Difficulty, Side
from llmarena.domain.rules import damage_for, match_winner, round_winner, rounds_needed
from tests.conftest import make_challenge


def test_damage_table():
    assert damage_for(Difficulty.EASY, False) == 10
    assert damage_for(Difficulty.MEDIUM, False) == 20
    assert damage_for(Difficulty.HARD, False) == 35
    assert damage_for(Difficulty.EASY, True) == 15
    assert damage_for(Difficulty.HARD, True) == 52


def test_winners():
    assert round_winner(10, 5) is Side.LEFT
    assert round_winner(5, 10) is Side.RIGHT
    assert round_winner(7, 7) is None
    assert match_winner({Side.LEFT: 2, Side.RIGHT: 1}) is Side.LEFT
    assert rounds_needed(3) == 2 and rounds_needed(5) == 3 and rounds_needed(1) == 1
    assert Side.LEFT.opponent is Side.RIGHT


@pytest.mark.parametrize(
    "text",
    [
        "def f(x):\n    return x\n",
        "```python\ndef f(x):\n    return x\n```",
        "```\ndef f(x):\n    return x\n```",
        "Sure! Here is the code:\n\n```python\ndef f(x):\n    return x\n```\n\nHope this helps.",
        "Here you go:\ndef f(x):\n    return x\n\nThis function returns x.",
        "```python\ndef f(x):\n    return x\n",
    ],
)
def test_extract_code_variants(text):
    assert extract_code(text).strip() == "def f(x):\n    return x"


def test_extract_code_prefers_first_fence_and_handles_no_code():
    text = "```python\ndef a():\n    pass\n```\nand\n```python\ndef b():\n    pass\n```"
    assert extract_code(text) == "def a():\n    pass"
    assert extract_code("I cannot do that.") == ""
    assert extract_code("") == ""


def test_extract_code_keeps_imports_and_helpers():
    text = (
        "from collections import Counter\n\ndef helper():\n    return 1\n\ndef f(x):\n    return helper()\n"
    )
    assert extract_code(text) == text.strip()


def test_ensure_function_alias():
    code, renamed = ensure_function("def plus(a, b):\n    return a + b\n", "add")
    assert renamed and code.endswith("add = plus\n")
    code, renamed = ensure_function("def add(a, b):\n    return a + b\n", "add")
    assert not renamed
    code, renamed = ensure_function("def a():\n    pass\ndef b():\n    pass\n", "add")
    assert not renamed
    code, renamed = ensure_function("def f(:\n", "add")
    assert not renamed


def test_challenge_validation():
    with pytest.raises(ValidationError):
        make_challenge("Bad-Id")
    with pytest.raises(ValidationError):
        Challenge(
            id="x",
            title="x",
            difficulty="easy",
            function="f",
            signature="def g(a)",
            statement="s",
            tests=[TestCase(expected=1)] * 3,
        )
    with pytest.raises(ValidationError):
        Challenge(
            id="x",
            title="x",
            difficulty="easy",
            function="f",
            signature="def f(a)",
            statement="s",
            tests=[TestCase(expected=1)],
        )
    with pytest.raises(ValidationError):
        ChallengeBank(challenges=[make_challenge("a"), make_challenge("a")])
    with pytest.raises(ValidationError):
        ChallengeBank(challenges=[])


def test_bank_draw_avoids_repeats_then_falls_back(small_bank):
    import random

    rng = random.Random(1)
    used: set[str] = set()
    for _ in range(3):
        c = small_bank.draw(used, rng)
        assert c.id not in used
        used.add(c.id)
    assert small_bank.draw(used, rng).id in used  # esgotou: repete
    assert small_bank.by_title("Add add_easy").id == "add_easy"
    assert make_challenge().example() == "add(1, 2) -> 3"


def test_real_bank_loads(real_bank):
    assert len(real_bank.challenges) >= 30
    counts = real_bank.count_by_difficulty()
    assert all(n >= 5 for n in counts.values())
    assert all(c.reference for c in real_bank.challenges)
