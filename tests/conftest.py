from __future__ import annotations

from pathlib import Path

import pytest

from llmarena.challenges.loader import load_bank
from llmarena.challenges.schema import Challenge, ChallengeBank, TestCase
from llmarena.domain.models import Difficulty
from llmarena.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def make_challenge(
    cid: str = "add", difficulty: Difficulty = Difficulty.EASY, function: str = "add"
) -> Challenge:
    return Challenge(
        id=cid,
        title=f"Add {cid}",
        difficulty=difficulty,
        function=function,
        signature=f"def {function}(a: int, b: int) -> int",
        statement="Return a + b.",
        tests=[
            TestCase(args=[1, 2], expected=3),
            TestCase(args=[0, 0], expected=0),
            TestCase(args=[-1, 1], expected=0),
        ],
        reference=f"def {function}(a, b):\n    return a + b\n",
    )


GOOD_CODE = "def add(a, b):\n    return a + b\n"
BAD_CODE = "def add(a, b):\n    return a - b\n"


@pytest.fixture
def challenge() -> Challenge:
    return make_challenge()


@pytest.fixture
def small_bank() -> ChallengeBank:
    return ChallengeBank(
        challenges=[
            make_challenge("add_easy", Difficulty.EASY),
            make_challenge("add_medium", Difficulty.MEDIUM),
            make_challenge("add_hard", Difficulty.HARD),
        ]
    )


@pytest.fixture(scope="session")
def real_bank() -> ChallengeBank:
    return load_bank(ROOT / "challenges" / "bank.yaml")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key=None,
        openrouter_api_key=None,
        db_path=tmp_path / "arena.db",
        bank_path=ROOT / "challenges" / "bank.yaml",
        models_path=ROOT / "config" / "models.yaml",
        static_dir=ROOT / "static",
        round_seconds=5.0,
        intermission_seconds=0.0,
        max_attempts_per_challenge=3,
        max_golpes_per_round=6,
        llm_timeout_s=5.0,
        first_token_timeout_s=3.0,
    )
